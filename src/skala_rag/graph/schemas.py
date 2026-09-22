"""Shared Pydantic contracts for every record that crosses a branch boundary.

A/B/C branches validate their outputs against these models. The graph validates
each service update at the node boundary (``validate_update``) and records
violations in ``errors`` instead of crashing or silently accepting bad data.
Label sets (``LABELS``) are the single source of truth for the rubric.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

Mode = Literal["live", "replay"]
ClaimType = Literal["reported_fact", "inference", "unverified"]
Perspective = Literal["market", "stakeholder", "domain", "trl"]
Status = Literal["complete", "insufficient_evidence"]

PERSPECTIVES: tuple[str, ...] = ("market", "stakeholder", "domain", "trl")
PERSPECTIVE_TITLES: dict[str, str] = {
    "market": "시장성",
    "stakeholder": "이해관계자",
    "domain": "도메인 적용",
    "trl": "기술 성숙도",
}
FIELD_TITLES: dict[str, str] = {
    "market_size": "시장 규모와 성장",
    "adoption": "상용화와 채택 현황",
    "ecosystem": "생태계 지지",
    "competitor_view": "경쟁 기술 진영",
    "adopter_view": "도입 기업과 개발자",
    "investor_view": "투자 업계와 미디어",
    "memory": "메모리 절감",
    "quality": "생성 품질",
    "latency": "응답 지연",
    "throughput": "처리량",
    "integration": "통합 부담",
    "trl": "기술 성숙도(TRL)",
}
# Labels every field accepts when no evidence was found (design C.1).
UNKNOWN_LABELS: tuple[str, ...] = ("미확인", "판단 유보")
# Labels that mean "no material found" (UNKNOWN_LABELS plus the domain perspective's 보고 없음, design C.5).
# They need no evidence and are not semantically reviewed, but they never count as a supported judgment.
NOT_FOUND_LABELS: tuple[str, ...] = UNKNOWN_LABELS + ("보고 없음",)
# Rubric label sets from design C.2~C.5. ``None`` means the TRL pattern applies.
LABELS: dict[str, dict[str, tuple[str, ...] | None]] = {
    "market": {
        "market_size": ("직접 자료 있음", "관련 시장 자료만 있음", "미확인"),
        "adoption": ("상용 서비스 적용 확인", "주류 프레임워크 통합", "연구 재현 수준", "미확인"),
        "ecosystem": ("활발", "일부 있음", "미확인"),
    },
    "stakeholder": {
        name: ("지지", "우려", "중립", "미확인") for name in ("competitor_view", "adopter_view", "investor_view")
    },
    "domain": {
        **{name: ("적용 가능 보고", "조건부 보고", "보고 없음") for name in ("memory", "quality", "latency", "throughput")},
        "integration": ("낮음 보고", "높음 보고", "보고 없음"),
    },
    "trl": {"trl": None},
}
TRL_PATTERN = re.compile(r"TRL\s*[1-9](?:\s*(?:-|~|에서)\s*(?:TRL\s*)?[1-9])?")
TRL_DISCLAIMER = (
    "기술 성숙도(TRL) 판정은 논문 발표 시점과 실제 채택 시점 사이의 시차를 고려해 "
    "공개 정보에 근거한 추정이며, 확정된 단계가 아니다."
)


def rubric_fields(perspective: str) -> tuple[str, ...]:
    return tuple(LABELS[perspective])


def allowed_labels(perspective: str, field: str) -> tuple[str, ...] | None:
    return LABELS[perspective][field]


def is_valid_label(perspective: str, field: str, label: Any) -> bool:
    text = str(label or "").strip()
    if text in UNKNOWN_LABELS:
        return True
    allowed = LABELS.get(perspective, {}).get(field)
    if allowed is None:
        return bool(TRL_PATTERN.fullmatch(text))
    return text in allowed


class SearchBudget(BaseModel):
    """Per-run tool budget from design B.6."""

    model_config = ConfigDict(extra="allow")

    web_search_max: int = 20
    fetch_max: int = 30
    tool_timeout_seconds: int = 20
    tool_retries: int = 2


class RunConfig(BaseModel):
    model_config = ConfigDict(extra="allow")

    mode: Mode
    technologies: list[str]
    domain: str
    model_id: str = "gpt-5.4-mini"
    as_of: str | None = None
    paper_dir: str | None = None
    max_paper_pages: int = 200
    budget: SearchBudget = Field(default_factory=SearchBudget)
    fixture: bool = False
    background: str | None = None
    selection_rationale: str | None = None
    report_title: str | None = None

    @field_validator("technologies")
    @classmethod
    def _two_distinct(cls, value: list[str]) -> list[str]:
        names = [str(item).strip() for item in value]
        if len(names) != 2 or len(set(names)) != 2 or not all(names):
            raise ValueError("technologies must contain two different non-empty names")
        return names

    @field_validator("domain")
    @classmethod
    def _domain_required(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("domain is required")
        return value.strip()


class Source(BaseModel):
    """One source (design D.1). ``source_id`` is filled from the State key."""

    model_config = ConfigDict(extra="allow")

    source_id: str | None = None
    title: str = "제목 미상"
    author_or_org: str | None = None
    url: str | None = None
    version: str | None = None
    published_at: str | None = None
    retrieved_at: str | None = None
    pages: int | None = None
    content_hash: str | None = None
    source_type: str = "web"  # paper | web | code | report | fixture
    venue: str | None = None  # 학회·학술지 또는 사이트명 (REFERENCE 표기용)

    @field_validator("pages", mode="before")
    @classmethod
    def _pages_int(cls, value: Any) -> int | None:
        if value in (None, ""):
            return None
        return int(value)


class Measurement(BaseModel):
    """Quantitative bundle from design C.6. Missing parts stay empty."""

    model_config = ConfigDict(extra="allow")

    metric: str | None = None
    value: str | float | int | None = None
    unit: str | None = None
    baseline: str | None = None
    model: str | None = None
    hardware: str | None = None
    context_length: str | None = None
    batch_size: str | None = None
    precision: str | None = None
    location: str | None = None


class Evidence(BaseModel):
    """One evidence record (design D.1, B.7)."""

    model_config = ConfigDict(extra="allow")

    evidence_id: str | None = None
    source_id: str
    technology: str
    claim: str = ""
    quote: str = ""
    location: str = ""
    claim_type: ClaimType = "unverified"
    conditions: str = ""
    measurement: Measurement | None = None
    speaker: str | None = None  # 이해관계자 발언 주체 (design C.4)
    stated_at: str | None = None
    context: str | None = None


class Judgment(BaseModel):
    model_config = ConfigDict(extra="allow")

    label: str
    reason: str = ""
    conditions: str = ""
    evidence_ids: list[str] = Field(default_factory=list)

    @field_validator("evidence_ids", mode="before")
    @classmethod
    def _ids_list(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            return [value]
        return [str(item) for item in value]

    @field_validator("label", mode="before")
    @classmethod
    def _label_text(cls, value: Any) -> str:
        return str(value or "").strip()


class TRLStage(BaseModel):
    model_config = ConfigDict(extra="allow")

    met: bool = False
    evidence_ids: list[str] = Field(default_factory=list)
    note: str = ""


class TRLJudgment(Judgment):
    """TRL output from design C.2: highest confirmed stage, stage evidence, gaps."""

    highest_confirmed: str | None = None
    stages: dict[str, TRLStage] = Field(default_factory=dict)
    missing_evidence: list[str] = Field(default_factory=list)
    estimation_note: str = ""


class PerspectiveResult(BaseModel):
    """Perspective output frame from design B.2."""

    model_config = ConfigDict(extra="allow")

    perspective: Perspective
    technologies: dict[str, dict[str, Judgment | None]]
    unresolved_questions: list[str] = Field(default_factory=list)
    status: Status = "complete"

    @model_validator(mode="after")
    def _known_fields(self) -> "PerspectiveResult":
        allowed = set(LABELS[self.perspective])
        for technology, judgments in self.technologies.items():
            unknown = set(judgments) - allowed
            if unknown:
                raise ValueError(f"{technology}: unknown rubric fields {sorted(unknown)} for {self.perspective}")
        return self


class TechFinding(BaseModel):
    """Per-technology technical findings (design B.2)."""

    model_config = ConfigDict(extra="allow")

    principle: str = ""
    experiment_conditions: list[str] = Field(default_factory=list)
    performance: list[str] = Field(default_factory=list)  # 성능 수치 보고 문장 (수치 묶음은 measurements)
    measurements: list[Measurement] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)


class MissingQuestion(BaseModel):
    perspective: str
    technology: str
    field: str
    question: str
    reasons: list[str] = Field(default_factory=list)


class ErrorRecord(BaseModel):
    model_config = ConfigDict(extra="allow")

    node: str
    reason: str
    fatal: bool = False
    recovered: bool = False
    kind: str = "service"  # service | schema | pipeline | conflict


class JudgmentRef(BaseModel):
    perspective: str
    field: str
    label: str
    reason: str = ""
    conditions: str = ""
    evidence_ids: list[str] = Field(default_factory=list)


class SynthesisPair(BaseModel):
    """Six elements of design C.6: two judgments, reason, evidence, conditions, uncertainty."""

    technology: str
    first: JudgmentRef
    second: JudgmentRef
    reason: str
    uncertainty: str
    generation: str = "deterministic"


class Synthesis(BaseModel):
    model_config = ConfigDict(extra="allow")

    agreements: list[SynthesisPair] = Field(default_factory=list)
    conflicts: list[SynthesisPair] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    generation_mode: str = "deterministic"


class ReportTable(BaseModel):
    columns: list[str]
    rows: list[list[str]]


class ReportSection(BaseModel):
    heading: str
    paragraphs: list[str] = Field(default_factory=list)
    table: ReportTable | None = None
    level: int = 1


class Report(BaseModel):
    model_config = ConfigDict(extra="allow")

    title: str
    sections: list[ReportSection]
    markdown: str
    used_source_ids: list[str] = Field(default_factory=list)
    generation_mode: str = "deterministic"


PERSPECTIVE_KEYS: dict[str, str] = {f"{name}_analysis": name for name in PERSPECTIVES}
RECORD_SCHEMAS: dict[str, tuple[type[BaseModel], str | None]] = {
    "sources": (Source, "source_id"),
    "evidence": (Evidence, "evidence_id"),
    "errors": (ErrorRecord, None),
}


def summarize_validation_error(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        parts = []
        for item in exc.errors()[:3]:
            location = ".".join(str(piece) for piece in item.get("loc", ())) or "value"
            parts.append(f"{location}: {item.get('msg', 'invalid')}")
        return "; ".join(parts)
    return f"{type(exc).__name__}: {exc}"


def normalize_metric_events(node: str, value: Any) -> tuple[list[dict[str, Any]], list[str]]:
    """Accept a mapping (auto-tagged with the node) or a list of event mappings."""
    if isinstance(value, Mapping):
        return [{"node": node, **dict(value)}], []
    if isinstance(value, list):
        events, problems = [], []
        for index, item in enumerate(value):
            if isinstance(item, Mapping):
                events.append({"node": node, **dict(item)})
            else:
                problems.append(f"metrics[{index}]: event must be a mapping")
        return events, problems
    return [], ["metrics: must be a mapping or a list of mappings"]


def validate_update(node: str, update: Mapping[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Validate a service's partial State update.

    Returns the cleaned update and a list of human-readable problems. Invalid
    records are dropped individually; an invalid perspective result is dropped
    as a whole so the evidence check can request a repair.
    """
    clean: dict[str, Any] = {}
    problems: list[str] = []
    for key, value in update.items():
        if key in RECORD_SCHEMAS:
            schema, id_field = RECORD_SCHEMAS[key]
            if not isinstance(value, Mapping):
                problems.append(f"{key}: must be a mapping keyed by ID")
                continue
            kept: dict[str, Any] = {}
            for identifier, record in value.items():
                if not isinstance(record, Mapping):
                    problems.append(f"{key}[{identifier}]: record must be a mapping")
                    continue
                payload = dict(record)
                if id_field:
                    declared = payload.get(id_field)
                    if declared not in (None, identifier):
                        problems.append(f"{key}[{identifier}]: {id_field} mismatch ({declared})")
                        continue
                    payload[id_field] = identifier
                try:
                    kept[str(identifier)] = schema.model_validate(payload).model_dump()
                except ValidationError as exc:
                    problems.append(f"{key}[{identifier}]: {summarize_validation_error(exc)}")
            clean[key] = kept
        elif key in PERSPECTIVE_KEYS:
            expected = PERSPECTIVE_KEYS[key]
            if value is None:
                clean[key] = None
                continue
            try:
                result = PerspectiveResult.model_validate(value)
                if result.perspective != expected:
                    raise ValueError(f"perspective must be {expected!r}, got {result.perspective!r}")
                clean[key] = result.model_dump()
            except (ValidationError, ValueError) as exc:
                problems.append(f"{key}: {summarize_validation_error(exc)}")
        elif key == "technical_findings":
            if not isinstance(value, Mapping):
                problems.append("technical_findings: must be a mapping keyed by technology")
                continue
            findings: dict[str, Any] = {}
            for technology, finding in value.items():
                try:
                    findings[str(technology)] = TechFinding.model_validate(finding or {}).model_dump()
                except ValidationError as exc:
                    problems.append(f"technical_findings[{technology}]: {summarize_validation_error(exc)}")
            clean[key] = findings
        elif key == "metrics":
            events, metric_problems = normalize_metric_events(node, value)
            clean[key] = events
            problems.extend(metric_problems)
        else:
            clean[key] = value
    return clean, problems
