"""팀 공용 State/Evidence/PerspectiveResult 등 Pydantic 스키마.

출처: RAG-Design_*.pdf
- D.1 State 설계표
- B.2 에이전트 표 (관점 결과 형식)
- B.7 확증편향 방지 (주장 유형)
- C.2 TRL, C.3 시장성, C.4 이해관계자, C.5 도메인, C.6 종합, C.7 점검표
- D.4 분기와 종료 규칙

이 파일은 `notebooks/20-Schemas.ipynb`에서 셀별로 검증한 뒤 이관한 것.
스키마 변경 시 노트북과 이 파일을 함께 수정하고 HANDOFF.md에 diff 기록.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Annotated, Any, Literal, Optional, TypedDict

from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# 1. Enum
# ---------------------------------------------------------------------------
class TechName(str, Enum):
    KIVI = "KIVI"
    INFINIGEN = "InfiniGen"


class PerspectiveName(str, Enum):
    MARKET = "market"           # 시장성 (B 담당)
    STAKEHOLDER = "stakeholder"  # 이해관계자 (B 담당)
    DOMAIN = "domain"           # 도메인 (C 담당, C.5)
    TRL = "trl"                 # 기술 성숙도 (C 담당, C.2)


class ClaimType(str, Enum):
    """주장 유형 (PDF B.7)"""
    REPORTED_FACT = "reported_fact"
    INFERENCE = "inference"
    UNVERIFIED = "unverified"


class SourceType(str, Enum):
    PAPER = "paper"
    WEB = "web"
    REPO = "repo"
    FRAMEWORK_DOC = "framework_doc"
    BLOG = "blog"
    RELEASE_NOTE = "release_note"
    OTHER = "other"


class CompleteStatus(str, Enum):
    """PDF B.2"""
    COMPLETE = "complete"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


class StandardVerdict(str, Enum):
    """도메인 관점의 memory/quality/latency/throughput 4항목 판정 라벨 (PDF C.5)"""
    APPLICABLE = "적용 가능 보고"
    CONDITIONAL = "조건부 보고"
    NOT_REPORTED = "보고 없음"
    UNCLEAR = "미확인"


class IntegrationVerdict(str, Enum):
    """도메인 관점의 '통합 부담' 항목 전용 (PDF C.5)"""
    LOW = "낮음 보고"
    HIGH = "높음 보고"
    NOT_REPORTED = "보고 없음"
    UNCLEAR = "미확인"


class StakeholderVerdict(str, Enum):
    """이해관계자 관점 (PDF C.4, B 담당)"""
    SUPPORT = "지지"
    CONCERN = "우려"
    NEUTRAL = "중립"
    UNCLEAR = "미확인"


class MarketVerdict(str, Enum):
    """시장성 관점 (PDF C.3, B 담당)"""
    DIRECT = "직접 자료 있음"
    RELATED_ONLY = "관련 시장 자료만 있음"
    ACTIVE = "활발"
    PARTIAL = "일부 있음"
    UNCLEAR = "미확인"


class TRLLevel(str, Enum):
    """PDF C.2. 증거가 두 단계 걸치면 L4_5 처럼 범위 사용."""
    L1_2 = "TRL 1-2"
    L3 = "TRL 3"
    L4 = "TRL 4"
    L4_5 = "TRL 4-5"
    L5 = "TRL 5"
    L6 = "TRL 6"
    L7_8 = "TRL 7-8"
    L9 = "TRL 9"
    UNCLEAR = "미확인"


# ---------------------------------------------------------------------------
# 2. Source / Evidence (PDF D.1)
# ---------------------------------------------------------------------------
class Source(BaseModel):
    source_id: str = Field(..., description="예: src_kivi_p3, src_web_a1b2")
    title: str
    author_or_org: Optional[str] = None
    url: Optional[str] = None
    version: Optional[str] = None
    published_at: Optional[str] = None
    collected_at: Optional[str] = None
    page_count: Optional[int] = None
    content_hash: Optional[str] = None
    source_type: SourceType = SourceType.OTHER


class Evidence(BaseModel):
    evidence_id: str = Field(..., description="예: ev_kivi_001")
    source_id: str
    tech: TechName
    claim: str = Field(..., description="이 근거가 주장하는 사실 한 줄")
    quote: str = Field(..., description="원문 인용 구절 (판정을 뒷받침해야 함)")
    location: Optional[str] = Field(
        None, description="페이지 또는 절. 예: 'p.5', '§4.2', 'Table 3'"
    )
    claim_type: ClaimType = ClaimType.REPORTED_FACT
    experimental_condition: Optional[str] = Field(
        None,
        description="수치라면 모델·하드웨어·문맥 길이·배치·정밀도·지표를 함께 기록",
    )


# ---------------------------------------------------------------------------
# 3. 기술 조사 결과 (PDF B.2)
# ---------------------------------------------------------------------------
class TechFindingItem(BaseModel):
    principle: Optional[str] = Field(None, description="원리")
    experimental_condition: Optional[str] = None
    performance_number: Optional[str] = Field(
        None,
        description="지표·값·단위·비교기준·모델·하드웨어·문맥·배치·정밀도·페이지 묶음",
    )
    limitation: Optional[str] = None
    evidence_ids: list[str] = Field(default_factory=list)


class TechFindings(BaseModel):
    """두 기술을 같은 필드 구성으로 기록 (PDF D.1)."""
    kivi: TechFindingItem
    infinigen: TechFindingItem
    common_questions: list[str] = Field(
        default_factory=list,
        description="네 관점 에이전트가 공통으로 받을 질문 목록",
    )


# ---------------------------------------------------------------------------
# 4. 관점 평가 결과 (도메인/TRL/시장성/이해관계자 공용)
# ---------------------------------------------------------------------------
class RubricItem(BaseModel):
    """관점 하나의 rubric 항목 하나에 대한, 한 기술의 판정."""

    item_key: str = Field(
        ...,
        description=(
            "관점별 rubric 키. 예: 'memory', 'quality', 'latency', "
            "'throughput', 'integration', 'trl_level'"
        ),
    )
    tech: TechName
    verdict: str = Field(
        ...,
        description="판정 라벨 문자열. 관점별 Enum(.value)만 사용. 검증은 evidence_check에서.",
    )
    reason: str = Field(..., description="이 판정을 내린 이유")
    evidence_ids: list[str] = Field(
        default_factory=list,
        description=(
            "판정을 뒷받침하는 evidence_id 목록. 최소 1개(PDF C.7)."
            " 못 채우면 verdict를 '미확인'으로."
        ),
    )
    conditions: Optional[str] = Field(
        None,
        description="'조건부 보고'일 때 자료가 밝힌 조건(모델·GPU·문맥 길이 등)을 그대로 기록",
    )


class PerspectiveResult(BaseModel):
    """PDF B.2, C.1. 네 관점 에이전트의 공통 반환 형식."""

    perspective: PerspectiveName
    items: list[RubricItem] = Field(
        ...,
        description="rubric 항목 × 두 기술. 도메인이면 5×2=10개.",
    )
    unresolved_questions: list[str] = Field(
        default_factory=list,
        description="조사했지만 확인하지 못한 질문 목록 (PDF B.2)",
    )
    status: CompleteStatus = Field(
        ...,
        description="모든 항목에 근거가 있으면 complete, 하나라도 없으면 insufficient_evidence",
    )

    def items_by_tech(self, tech: TechName) -> list[RubricItem]:
        return [it for it in self.items if it.tech == tech]

    @field_validator("items")
    @classmethod
    def _non_empty(cls, v: list[RubricItem]) -> list[RubricItem]:
        if not v:
            raise ValueError("items는 최소 1개 이상이어야 합니다.")
        return v


# ---------------------------------------------------------------------------
# 5. 근거 검사 결과 (PDF D.4)
# ---------------------------------------------------------------------------
class Question(BaseModel):
    perspective: PerspectiveName
    tech: TechName
    item_key: str
    query: str = Field(
        ...,
        description="자연어 검색 질문. 관점명과 기술명이 포함되어야 함(PDF D.4).",
    )


class FailedItem(BaseModel):
    perspective: PerspectiveName
    tech: TechName
    item_key: str
    reason: str = Field(..., description="실패 이유: 근거 없음/enum 불일치/근거 부실 등")


class CheckResult(BaseModel):
    """근거 검사 노드의 출력. D의 조건 분기가 needs_retry로 보완/종합을 결정."""
    passed_keys: list[str] = Field(
        default_factory=list,
        description="'perspective|tech|item_key' 문자열 목록",
    )
    failed_items: list[FailedItem] = Field(default_factory=list)
    needs_retry: bool = False
    notes: Optional[str] = None


# ---------------------------------------------------------------------------
# 6. 종합·보고서·오류 (PDF C.6, D.1)
# ---------------------------------------------------------------------------
class ConflictPair(BaseModel):
    perspective_a: PerspectiveName
    verdict_a: str
    perspective_b: PerspectiveName
    verdict_b: str
    reason: str
    evidence_ids_a: list[str]
    evidence_ids_b: list[str]
    condition_a: str
    condition_b: str
    residual_uncertainty: str


class Agreement(BaseModel):
    description: str
    perspectives: list[PerspectiveName]
    evidence_ids: list[str] = Field(default_factory=list)


class Synthesis(BaseModel):
    agreements: list[Agreement] = Field(default_factory=list)
    conflicts: list[ConflictPair] = Field(default_factory=list)


class Report(BaseModel):
    sections: dict[str, str] = Field(
        default_factory=dict,
        description="예: {'SUMMARY': '...', 'A': '...', 'REFERENCE': '...'}",
    )
    used_source_ids: list[str] = Field(default_factory=list)


class ErrorRecord(BaseModel):
    node: str
    cause: str
    recoverable: bool = False
    at: Optional[str] = None


# ---------------------------------------------------------------------------
# 7. RunConfig (PDF D.1)
# ---------------------------------------------------------------------------
class RunConfig(BaseModel):
    """시작 후 고정."""
    tech_names: list[TechName] = Field(
        default_factory=lambda: [TechName.KIVI, TechName.INFINIGEN]
    )
    domain: str = "클라우드 LLM 서빙"
    model_id: str = "gpt-5.4-mini"                     # PDF B.1
    embedding_id: str = "intfloat/multilingual-e5-small"   # PDF B.5
    reference_date: str = Field(
        default_factory=lambda: datetime.now().date().isoformat()
    )
    max_web_calls_per_run: int = 20    # PDF B.6
    max_fetch_calls_per_run: int = 30  # PDF B.6
    max_retries: int = 2                # PDF D.4
    mode: Literal["live", "replay"] = "live"  # PDF E.2


# ---------------------------------------------------------------------------
# 8. LangGraph State (TypedDict + reducer)
# ---------------------------------------------------------------------------
def merge_by_id(a: dict, b: dict) -> dict:
    """PDF D.1: sources/evidence/errors는 ID 기준 병합."""
    out = dict(a or {})
    out.update(b or {})
    return out


def replace_perspective(
    a: Optional[PerspectiveResult], b: Optional[PerspectiveResult]
) -> Optional[PerspectiveResult]:
    """관점 결과는 해당 관점 결과만 교체."""
    return b if b is not None else a


class State(TypedDict, total=False):
    """LangGraph용 State. PDF D.1 표 그대로.
    total=False로 두어 노드가 자신이 쓰는 키만 반환하면 되도록 함."""
    run_config: RunConfig
    sources: Annotated[dict[str, Source], merge_by_id]
    evidence: Annotated[dict[str, Evidence], merge_by_id]
    technical_findings: TechFindings

    market_analysis: Annotated[Optional[PerspectiveResult], replace_perspective]
    stakeholder_analysis: Annotated[Optional[PerspectiveResult], replace_perspective]
    domain_analysis: Annotated[Optional[PerspectiveResult], replace_perspective]
    trl_analysis: Annotated[Optional[PerspectiveResult], replace_perspective]

    evidence_check: Optional[CheckResult]
    missing_questions: list[Question]
    retry_count: int

    synthesis: Optional[Synthesis]
    report: Optional[Report]

    errors: Annotated[dict[str, ErrorRecord], merge_by_id]
    artifacts: dict[str, Any]


__all__ = [
    # Enum
    "TechName", "PerspectiveName", "ClaimType", "SourceType", "CompleteStatus",
    "StandardVerdict", "IntegrationVerdict", "StakeholderVerdict",
    "MarketVerdict", "TRLLevel",
    # 데이터
    "Source", "Evidence", "TechFindingItem", "TechFindings",
    "RubricItem", "PerspectiveResult",
    "Question", "FailedItem", "CheckResult",
    "ConflictPair", "Agreement", "Synthesis", "Report", "ErrorRecord",
    "RunConfig",
    # LangGraph
    "State", "merge_by_id", "replace_perspective",
]
