"""Wire the A/B/C branch modules into D's ``PipelineServices`` contract.

Every conversion between branch formats lives here so each branch keeps its own
modules untouched:

- A ``agents.technical`` + ``tools.retrieve`` (paper RAG): findings/evidence use
  ``tech_name``/``page``/``section``; converted to ``technology``/``location``.
- B ``agents.market`` / ``agents.stakeholder`` (web evidence + rubric labels):
  already D-shaped; wrapped for repair rounds and error keys.
- C ``agents.domain`` / ``agents.trl`` (rubric judges over ``schemas.state``):
  ``RubricItem``/``PerspectiveResult(items)`` converted to
  ``technologies{tech: {field: Judgment}}``; A's chunks and B's web tools are
  adapted to the ``Evidence`` objects C's judges expect.

Rework rounds (``state["rework_requests"]`` non-empty for a perspective) re-run only
the technologies/items named in those requests and merge into the previous result.
Each request carries ``perspective``, ``technology``, ``field``, ``reasons``,
``review_reason``, ``question`` and an ``attempt`` counter. A legacy
``retry_mode`` + ``missing_questions`` + ``retry_count`` shape is accepted during
the Supervisor transition and converted internally.

Usage: ``python app.py --mode live`` (default factory) or
``--services skala_rag.integration.services:create_services``.
"""

from __future__ import annotations

import json
import logging
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from skala_rag.graph.schemas import LABELS, UNKNOWN_LABELS
from skala_rag.graph.workflow import PipelineServices
from skala_rag.integration.rework import build_rework_queries, needs_research
from skala_rag.tools.budget import BudgetExhausted, WebBudget
from skala_rag.tools.web import install_web_budget

logger = logging.getLogger(__name__)

DEFAULT_PAPERS_DIR = "data/papers"
DEFAULT_INDEX_DIR = "indexes"
TRL_ESTIMATION_NOTE = "공개 정보 기반 추정. 논문 발표 시점과 실제 채택 시점 사이에 시차가 있어 확정 단계가 아님"
NOTE_LIMIT = 220
_RETRIEVE_LOCK = threading.Lock()  # the four perspective nodes run in threads; FAISS/e5 access is serialized

# arXiv IDs of the two covered techniques; used by the rework query builder to narrow
# searches when the Supervisor flags claims as unsupported.
_TECH_PAPER_IDS: dict[str, str] = {"KIVI": "2402.02750", "InfiniGen": "2406.19707"}

# Judgment-field name → agent topic key for stakeholder (market's fields already equal topic names).
_STAKEHOLDER_FIELD_TO_TOPIC: dict[str, str] = {
    "competitor_view": "competitors",
    "adopter_view": "adopters",
    "investor_view": "industry_media",
}


def _field_to_topic(perspective: str, field: str) -> str:
    if perspective == "market":
        return field
    if perspective == "stakeholder":
        return _STAKEHOLDER_FIELD_TO_TOPIC.get(field, "")
    return ""


def _merge_search_log(prior: dict[str, dict[str, list[str]]], new: dict[str, dict[str, list[str]]]) -> dict[str, dict[str, list[str]]]:
    """Combine per-technology query logs so a later rework knows what has been tried."""
    merged: dict[str, dict[str, list[str]]] = {}
    technologies = set(prior) | set(new)
    for tech in technologies:
        combined = dict(prior.get(tech) or {})
        for field, queries in (new.get(tech) or {}).items():
            combined[field] = list(dict.fromkeys([*(combined.get(field) or []), *queries]))
        if combined:
            merged[tech] = combined
    return merged


def _rebuild_and_install_budget(settings: IntegrationSettings, state: Mapping[str, Any]) -> None:
    """Reset the shared web budget from ``run_config["budget"]`` and install it.

    Called from ``prepare`` so one WebBudget serves the whole run, no matter how
    many perspective nodes run in parallel afterwards.
    """
    if settings.budget is None:
        return
    config_budget = _config(state).get("budget") or {}
    settings.budget.reset(
        search_max=config_budget.get("web_search_max", settings.budget.search_max),
        fetch_max=config_budget.get("fetch_max", settings.budget.fetch_max),
    )
    install_web_budget(settings.budget)


def _ensure_budget_installed(settings: IntegrationSettings) -> None:
    """Re-install the budget in case this service node is reached before ``prepare``
    on the same process (parallel graph runs, tests calling a service directly)."""
    if settings.budget is not None:
        install_web_budget(settings.budget)


def _combined_evidence(state_evidence: Any, collected_evidence: Any) -> dict[str, dict[str, Any]]:
    """Merge the state's pre-existing evidence with the one just collected so
    bias checks can look up every cited id."""
    merged: dict[str, dict[str, Any]] = dict(state_evidence or {})
    merged.update(collected_evidence or {})
    return merged


def _mark_single_source(
    judgments: dict[str, dict[str, dict[str, Any]]],
    evidence_dict: dict[str, dict[str, Any]],
) -> None:
    """If a judgment cites only one source, append '단일 출처' to its ``conditions``.

    This surfaces the confirmation-bias risk (one voice, one reading) to the
    report and to the quality evaluator, instead of relying on the collection
    stage to always hit two independent sources.
    """
    marker = "단일 출처"
    for tech_judgments in judgments.values():
        if not isinstance(tech_judgments, dict):
            continue
        for judgment in tech_judgments.values():
            if not isinstance(judgment, dict):
                continue
            evidence_ids = judgment.get("evidence_ids") or []
            if not evidence_ids:
                continue
            source_ids: set[str] = set()
            for identifier in evidence_ids:
                entry = evidence_dict.get(str(identifier))
                if entry and entry.get("source_id"):
                    source_ids.add(str(entry["source_id"]))
            if len(source_ids) != 1:
                continue
            conditions = str(judgment.get("conditions") or "").strip()
            if marker in conditions:
                continue
            judgment["conditions"] = f"{conditions} / {marker}" if conditions else marker


@dataclass
class IntegrationSettings:
    """Tunables and injectable branch functions (``None`` = import the real module lazily)."""

    model_id: str | None = None
    papers_dir: str = DEFAULT_PAPERS_DIR
    index_dir: str = DEFAULT_INDEX_DIR
    cache_dir: Path | None = None
    k_rag: int = 5
    k_web: int = 3
    fetch_per_stage: int = 2
    market_kwargs: dict[str, Any] = field(default_factory=dict)
    stakeholder_kwargs: dict[str, Any] = field(default_factory=dict)
    budget: WebBudget | None = None  # shared across the three web-touching services
    retrieve: Callable[..., Any] | None = None  # A: retrieve_papers(query, tech_name, k=...)
    build_index: Callable[..., Any] | None = None  # A: build_index(papers_dir, index_dir)
    technical_research: Callable[..., Any] | None = None  # A: run_technical_research(tech_names, model=...)
    market_agent: Callable[..., Any] | None = None  # B: run_market_agent(technologies=..., mode=..., **kw)
    stakeholder_agent: Callable[..., Any] | None = None  # B: run_stakeholder_agent(...)
    judge_domain: Callable[..., Any] | None = None  # C: judge_one(spec, tech, candidates, model_name)
    judge_stage: Callable[..., Any] | None = None  # C: judge_stage(spec, tech, candidates, model_name)
    search_results: Callable[..., Any] | None = None  # B: get_search_results(query, max_results, mode, cache_dir)
    fetch_source: Callable[..., Any] | None = None  # B: get_source(url, mode, cache_dir)
    summarize: Callable[..., Any] | None = None  # B: summarize_source(source, question, topic=, mode=, cache_dir=)


class _Branches:
    """Resolves branch functions on first use so importing this module stays light."""

    def __init__(self, settings: IntegrationSettings):
        self.settings = settings

    def retrieve(self, query: str, tech: str, k: int) -> list[Any]:
        function = self.settings.retrieve
        if function is None:
            from skala_rag.tools.retrieve import retrieve_papers

            function = retrieve_papers
        with _RETRIEVE_LOCK:
            return list(function(query, tech, k=k))

    def build_index(self, papers_dir: str, index_dir: str) -> None:
        function = self.settings.build_index
        if function is None:
            from skala_rag.tools.retrieve.ingest import build_index

            function = build_index
        function(papers_dir=papers_dir, index_dir=index_dir)

    def technical_research(self, technologies: list[str], model: str) -> Any:
        function = self.settings.technical_research
        if function is None:
            from skala_rag.agents.technical import run_technical_research

            function = run_technical_research
        return function(technologies, model=model)

    def market_agent(self, **kwargs: Any) -> dict[str, Any]:
        function = self.settings.market_agent
        if function is None:
            from skala_rag.agents.market import run_market_agent

            function = run_market_agent
        return function(**kwargs)

    def stakeholder_agent(self, **kwargs: Any) -> dict[str, Any]:
        function = self.settings.stakeholder_agent
        if function is None:
            from skala_rag.agents.stakeholder import run_stakeholder_agent

            function = run_stakeholder_agent
        return function(**kwargs)

    def judge_domain(self, spec: Any, tech: Any, candidates: list[Any], model: str) -> Any:
        function = self.settings.judge_domain
        if function is None:
            from skala_rag.agents.domain import judge_one

            function = judge_one
        return function(spec, tech, candidates, model)

    def judge_stage(self, spec: Any, tech: Any, candidates: list[Any], model: str) -> Any:
        function = self.settings.judge_stage
        if function is None:
            from skala_rag.agents.trl import judge_stage

            function = judge_stage
        return function(spec, tech, candidates, model)

    def search_results(self, query: str, max_results: int, mode: str, cache_dir: Path | None) -> list[dict[str, Any]]:
        function = self.settings.search_results
        if function is None:
            from skala_rag.tools.web import get_search_results

            function = get_search_results
        return function(query, max_results=max_results, mode=mode, **_cache_kw(cache_dir))

    def fetch_source(self, url: str, mode: str, cache_dir: Path | None) -> dict[str, Any]:
        function = self.settings.fetch_source
        if function is None:
            from skala_rag.tools.web import get_source

            function = get_source
        return function(url, mode=mode, **_cache_kw(cache_dir))

    def summarize(self, source: dict[str, Any], question: str, topic: str, mode: str, cache_dir: Path | None) -> dict[str, Any]:
        function = self.settings.summarize
        if function is None:
            from skala_rag.tools.web import summarize_source

            function = summarize_source
        return function(source, question=question, topic=topic, mode=mode, **_cache_kw(cache_dir))


def _cache_kw(cache_dir: Path | None) -> dict[str, Any]:
    return {"cache_dir": Path(cache_dir)} if cache_dir else {}


# ---------------------------------------------------------------------------
# State helpers
# ---------------------------------------------------------------------------
def _config(state: Mapping[str, Any]) -> dict[str, Any]:
    return dict(state.get("run_config") or {})


def _mode(state: Mapping[str, Any]) -> str:
    return str(_config(state).get("mode") or "live")


def _technologies(state: Mapping[str, Any]) -> list[str]:
    return [str(item) for item in (_config(state).get("technologies") or ["KIVI", "InfiniGen"])]


def _model_id(state: Mapping[str, Any], settings: IntegrationSettings) -> str:
    return settings.model_id or str(_config(state).get("model_id") or "gpt-5.4-mini")


def _rework_requests(state: Mapping[str, Any], perspective: str) -> list[dict[str, Any]]:
    """Normalized rework instructions for one perspective.

    Reads ``state["rework_requests"]`` (list of dicts with ``perspective``, ``technology``,
    ``field``, ``reasons``, ``review_reason``, ``question``, ``attempt``). While the
    Supervisor still emits the legacy keys (``retry_mode`` + ``missing_questions`` +
    ``retry_count``), those are mapped to the new shape so services keep working during
    the transition. Remove the legacy branch once the Supervisor rewrite lands.
    """
    requests = state.get("rework_requests")
    if requests is not None:
        return [dict(r) for r in requests if r and r.get("perspective") == perspective]
    if not state.get("retry_mode"):
        return []
    attempt = int(state.get("retry_count", 1) or 1)
    return [{**q, "attempt": attempt} for q in (state.get("missing_questions") or []) if q.get("perspective") == perspective]


def _is_rework(state: Mapping[str, Any], perspective: str) -> bool:
    return bool(_rework_requests(state, perspective))


def _rework_attempt(state: Mapping[str, Any], perspective: str, tech: str | None = None) -> int:
    requests = _rework_requests(state, perspective)
    if tech is not None:
        requests = [r for r in requests if r.get("technology") == tech]
    return max((int(r.get("attempt", 1) or 1) for r in requests), default=0)


def _known_evidence_ids(state: Mapping[str, Any]) -> set[str]:
    ids = state.get("known_evidence_ids")
    if ids is not None:
        return {str(identifier) for identifier in ids}
    return {str(identifier) for identifier in (state.get("evidence") or {}).keys()}


def _retry_technologies(state: Mapping[str, Any], perspective: str, technologies: list[str]) -> list[str]:
    """Technologies to (re)run: all on a normal call, only the ones named in rework_requests otherwise."""
    if not _is_rework(state, perspective):
        return technologies
    wanted = sorted({str(r["technology"]) for r in _rework_requests(state, perspective)})
    return [tech for tech in technologies if tech in wanted] or technologies


def _retry_items(state: Mapping[str, Any], perspective: str) -> set[tuple[str, str]] | None:
    if not _is_rework(state, perspective):
        return None
    return {(str(r["technology"]), str(r["field"])) for r in _rework_requests(state, perspective)}


def _dump(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump()
    return value


def _clip(text: Any, limit: int = NOTE_LIMIT) -> str:
    compact = " ".join(str(text or "").split())
    return compact if len(compact) <= limit else compact[: limit - 1] + "…"


def _first_sentence(text: str, limit: int = 160) -> str:
    compact = " ".join(str(text or "").split())
    for marker in (". ", "。", "! ", "? "):
        index = compact.find(marker)
        if 20 < index < limit:
            return compact[: index + 1]
    return compact[:limit]


def _tech_enum(tech: str) -> Any:
    from skala_rag.schemas.state import TechName

    try:
        return TechName(tech)
    except ValueError as exc:
        raise ValueError(f"C 브랜치 평가기는 KIVI/InfiniGen만 지원한다: {tech}") from exc


def _round_key(state: Mapping[str, Any], key: str, perspective: str | None = None, tech: str | None = None) -> str:
    """Suffix an error/record key with the rework attempt so repeat rounds don't overwrite earlier records.

    ``perspective`` is required to look up the attempt from ``rework_requests``. The legacy
    ``retry_count`` fallback keeps working while workflow still sets it.
    """
    if perspective is None:
        if state.get("retry_mode"):
            return f"{key}-r{int(state.get('retry_count', 0) or 0)}"
        return key
    if not _is_rework(state, perspective):
        return key
    attempt = _rework_attempt(state, perspective, tech)
    return f"{key}-r{attempt}" if attempt else key


def _perspective_result(perspective: str, judgments: dict[str, dict[str, dict[str, Any]]], technologies: list[str]) -> dict[str, Any]:
    unresolved: list[str] = []
    for tech in technologies:
        for field_name, judgment in (judgments.get(tech) or {}).items():
            if str(judgment.get("label") or "") in UNKNOWN_LABELS or not judgment.get("evidence_ids"):
                unresolved.append(f"[{perspective}|{tech}|{field_name}] 근거가 확인된 판정 없음")
    return {
        "perspective": perspective,
        "technologies": {tech: judgments.get(tech) or {} for tech in technologies},
        "unresolved_questions": unresolved,
        "status": "insufficient_evidence" if unresolved else "complete",
    }


COLLECTION_FAILURE_PREFIX = "근거 수집 실패"


def _collection_failed(judgments: Mapping[str, Any]) -> bool:
    """True when a technology's judgments are the fallback written after a collection error."""
    return bool(judgments) and all(str(j.get("reason", "")).startswith(COLLECTION_FAILURE_PREFIX) for j in judgments.values() if isinstance(j, Mapping))


def _judgment_from_item(item: Any) -> dict[str, Any]:
    """C ``RubricItem`` → D judgment dict."""
    data = _dump(item)
    return {
        "label": str(data.get("verdict") or "미확인"),
        "reason": str(data.get("reason") or ""),
        "conditions": str(data.get("conditions") or ""),
        "evidence_ids": [str(identifier) for identifier in (data.get("evidence_ids") or [])],
    }


# ---------------------------------------------------------------------------
# Evidence adapters (A chunks / B web pages → C Evidence objects + D records)
# ---------------------------------------------------------------------------
class _EvidenceCollector:
    """Collects D-format evidence/sources produced while judging, skipping IDs already in State."""

    def __init__(self, state: Mapping[str, Any], branches: _Branches):
        self.state = state
        self.branches = branches
        self.existing = _known_evidence_ids(state)
        self.evidence: dict[str, dict[str, Any]] = {}
        self.sources: dict[str, dict[str, Any]] = {}
        self.errors: list[dict[str, Any]] = []
        self.retrieve_calls = 0
        self.search_calls = 0
        self.fetch_calls = 0
        self.summary_calls = 0

    def _c_evidence(self, **fields: Any) -> Any:
        from skala_rag.schemas.state import ClaimType, Evidence

        return Evidence(claim_type=ClaimType.REPORTED_FACT, **fields)

    def retrieve(self, query: str, tech: str, k: int) -> list[Any]:
        chunks = self.branches.retrieve(query, tech, k)
        self.retrieve_calls += 1
        candidates: list[Any] = []
        for chunk in chunks:
            data = _dump(chunk) if isinstance(chunk, Mapping) or hasattr(chunk, "model_dump") else vars(chunk)
            evidence_id = str(data["evidence_id"])
            text = str(data.get("text") or data.get("quote") or "")
            location = f"p.{data.get('page')} {data.get('section') or ''}".strip()
            technology = str(data.get("tech_name") or data.get("technology") or tech)
            candidates.append(
                self._c_evidence(
                    evidence_id=evidence_id,
                    source_id=str(data["source_id"]),
                    tech=_tech_enum(technology),
                    claim=_first_sentence(text),
                    quote=text,
                    location=location,
                )
            )
            if evidence_id not in self.existing and evidence_id not in self.evidence:
                self.evidence[evidence_id] = {
                    "source_id": str(data["source_id"]),
                    "technology": technology,
                    "claim": _first_sentence(text),
                    "quote": text,
                    "location": location,
                    "claim_type": "reported_fact",
                    "conditions": "",
                    "page": data.get("page"),
                    "section": data.get("section"),
                }
        return candidates

    def web_search(self, query: str, tech: str, question: str, topic: str, k: int, fetch_limit: int, mode: str, cache_dir: Path | None) -> list[Any]:
        """B search → fetch → verified summary → C Evidence + D records (design B.6)."""
        try:
            hits = self.branches.search_results(query, k, mode, cache_dir)
            self.search_calls += 1
        except Exception as exc:
            self.errors.append({"stage": "search", "topic": topic, "query": query, "reason": f"{type(exc).__name__}: {exc}"[:300]})
            return []
        candidates: list[Any] = []
        for hit in list(hits or [])[:fetch_limit]:
            url = hit.get("url") if isinstance(hit, Mapping) else None
            if not url:
                continue
            try:
                source = self.branches.fetch_source(url, mode, cache_dir)
                self.fetch_calls += 1
                summary = self.branches.summarize(source, question, topic, mode, cache_dir)
                self.summary_calls += 1
            except Exception as exc:
                self.errors.append({"stage": "fetch_or_summarize", "topic": topic, "url": url, "reason": f"{type(exc).__name__}: {exc}"[:300]})
                continue
            if summary.get("evidence_status") == "not_found" or summary.get("quote_verified") is not True:
                continue
            source_key = str(summary.get("source_url") or url)
            digest = str(summary.get("content_hash") or sha256(source_key.encode()).hexdigest())
            source_id = "web-source-" + sha256(f"{source_key}|{digest}".encode()).hexdigest()[:24]
            evidence_id = "web-evidence-" + sha256(f"{source_id}|{tech}|{topic}|{summary.get('quote')}|{summary.get('claim')}".encode()).hexdigest()[:24]
            self.sources[source_id] = {
                "source_id": source_id,
                "title": summary.get("source_title") or "제목 미상",
                "url": summary.get("source_url") or url,
                "retrieved_at": summary.get("collected_at"),
                "content_hash": digest,
                "source_type": "web",
            }
            location = str(summary.get("location") or "웹 추출문")
            self.evidence[evidence_id] = {
                "source_id": source_id,
                "technology": tech,
                "claim": str(summary.get("claim") or ""),
                "quote": str(summary.get("quote") or ""),
                "location": location,
                "claim_type": "reported_fact",
                "conditions": str(summary.get("limitation") or ""),
                "topic": topic,
                "evidence_status": summary.get("evidence_status"),
                "relation_kind": summary.get("relation_kind"),
                "related_entity": summary.get("related_entity"),
            }
            candidates.append(
                self._c_evidence(
                    evidence_id=evidence_id,
                    source_id=source_id,
                    tech=_tech_enum(tech),
                    claim=str(summary.get("claim") or ""),
                    quote=str(summary.get("quote") or ""),
                    location=location,
                    experimental_condition=summary.get("limitation") or None,
                )
            )
        return candidates

    def metrics(self, **extra: Any) -> dict[str, Any]:
        return {
            "retrieve_calls": self.retrieve_calls,
            "web_search_calls": self.search_calls,
            "fetch_calls": self.fetch_calls,
            "summary_llm_calls": self.summary_calls,
            **extra,
        }

    def error_records(self, node: str, state: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
        """One record per (stage, error type): topics are listed inside the reason."""
        grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for item in self.errors:
            error_type = str(item.get("reason", "")).split(":", 1)[0].strip() or "Error"
            grouped.setdefault((str(item.get("stage")), error_type), []).append(item)
        records: dict[str, dict[str, Any]] = {}
        for index, ((stage, error_type), items) in enumerate(grouped.items()):
            topics = ", ".join(dict.fromkeys(str(item.get("topic")) for item in items))
            detail = str(items[0].get("reason", ""))[:160]
            records[_round_key(state, f"{node}-web-{index}", node)] = {
                "node": node,
                "reason": f"{stage} {error_type} ×{len(items)} ({topics}): {detail}",
                "fatal": False,
                "recovered": False,
                "kind": "service",
            }
        return records


# ---------------------------------------------------------------------------
# Services
# ---------------------------------------------------------------------------
def _load_manifest(papers_dir: Path) -> list[dict[str, Any]]:
    manifest_path = papers_dir / "manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"논문 목록이 없다: {manifest_path}")
    return list(json.loads(manifest_path.read_text(encoding="utf-8")).get("papers") or [])


def make_prepare(settings: IntegrationSettings, branches: _Branches):
    def prepare(state: Mapping[str, Any]) -> dict[str, Any]:
        _rebuild_and_install_budget(settings, state)
        papers_dir = Path(_config(state).get("paper_dir") or settings.papers_dir)
        papers = _load_manifest(papers_dir)
        known = {str(paper.get("tech_name")) for paper in papers}
        absent = [tech for tech in _technologies(state) if tech not in known]
        if absent:
            raise ValueError(f"manifest에 논문이 없는 기술: {absent}")
        sources: dict[str, dict[str, Any]] = {}
        for paper in papers:
            sources[str(paper["source_id"])] = {
                "title": paper.get("title") or paper.get("filename") or "제목 미상",
                "author_or_org": paper.get("authors"),
                "url": paper.get("source_url"),
                "version": paper.get("version"),
                "published_at": paper.get("published_date"),
                "retrieved_at": paper.get("collected_at"),
                "pages": paper.get("page_count"),
                "content_hash": paper.get("sha256"),
                "source_type": "paper",
                "venue": paper.get("venue"),
                "technology": paper.get("tech_name"),
            }
        index_built = 0
        index_dir = Path(settings.index_dir)
        if not (index_dir / "index.faiss").is_file():
            logger.info("FAISS index missing; building into %s", index_dir)
            branches.build_index(str(papers_dir), str(index_dir))
            index_built = 1
        return {
            "sources": sources,
            "metrics": {
                "papers": len(papers),
                "indexed_pages": sum(int(paper.get("page_count") or 0) for paper in papers),
                "index_built": index_built,
            },
        }

    return prepare


def make_technical(settings: IntegrationSettings, branches: _Branches):
    def technical(state: Mapping[str, Any]) -> dict[str, Any]:
        technologies = _technologies(state)
        result = branches.technical_research(technologies, _model_id(state, settings))
        raw_evidence = getattr(result, "evidence", None) if not isinstance(result, Mapping) else result.get("evidence")
        raw_findings = getattr(result, "technical_findings", None) if not isinstance(result, Mapping) else result.get("technical_findings")
        raw_errors = getattr(result, "errors", None) if not isinstance(result, Mapping) else result.get("errors")
        evidence: dict[str, dict[str, Any]] = {}
        for evidence_id, item in (raw_evidence or {}).items():
            data = _dump(item)
            evidence[str(evidence_id)] = {
                "source_id": str(data.get("source_id") or ""),
                "technology": str(data.get("tech_name") or data.get("technology") or ""),
                "claim": str(data.get("claim") or ""),
                "quote": str(data.get("quote") or ""),
                "location": f"p.{data.get('page')} {data.get('section') or ''}".strip(),
                "claim_type": str(data.get("claim_type") or "reported_fact"),
                "conditions": str(data.get("experimental_condition") or data.get("conditions") or ""),
                "page": data.get("page"),
                "section": data.get("section"),
            }
        findings: dict[str, dict[str, Any]] = {}
        for tech, item in (raw_findings or {}).items():
            data = _dump(item)

            def category(name: str) -> dict[str, Any]:
                value = data.get(name) or {}
                return _dump(value) if not isinstance(value, Mapping) else dict(value)

            principle, setup = category("principle"), category("experimental_setup")
            performance, limitations = category("performance"), category("limitations")
            ids = [identifier for part in (principle, setup, performance, limitations) for identifier in (part.get("evidence_ids") or [])]
            findings[str(tech)] = {
                "principle": " ".join(str(claim) for claim in (principle.get("claims") or [])),
                "experiment_conditions": [str(claim) for claim in (setup.get("claims") or [])],
                "performance": [str(claim) for claim in (performance.get("claims") or [])],
                "limitations": [str(claim) for claim in (limitations.get("claims") or [])],
                "evidence_ids": list(dict.fromkeys(ids)),
            }
        errors = {
            f"technical-{index}": {
                "node": "technical",
                "reason": json.dumps(item, ensure_ascii=False, default=str)[:1000],
                "fatal": False,
                "recovered": False,
                "kind": "service",
            }
            for index, item in enumerate(raw_errors or [])
        }
        return {
            "technical_findings": findings,
            "evidence": evidence,
            "errors": errors,
            "metrics": {"llm_calls": 8 * len(technologies), "retrieve_calls": 8 * len(technologies), "claims": sum(len(f["evidence_ids"]) for f in findings.values())},
        }

    return technical


def make_web_perspective(name: str, settings: IntegrationSettings, branches: _Branches):
    """B's market/stakeholder agents already return D-shaped results.

    First pass: collect all three fields for every technology; one technology's
    collection failure degrades only that technology to 미확인. On a rework pass the
    Supervisor names the (technology, field) pairs that still need evidence; we build
    fresh queries from each request's reasons/review_reason/question (via
    ``rework.build_rework_queries``) and re-collect only those field/topic pairs.
    Fields flagged with purely re-judge reasons (``wrong_technology``,
    ``unknown_evidence``, ``invalid_label``, …) keep their previous judgment untouched
    because no new web traffic would change the label.
    """
    runner = branches.market_agent if name == "market" else branches.stakeholder_agent
    kwargs = settings.market_kwargs if name == "market" else settings.stakeholder_kwargs

    def service(state: Mapping[str, Any]) -> dict[str, Any]:
        _ensure_budget_installed(settings)
        technologies = _technologies(state)
        is_rework = _is_rework(state, name)
        previous_analysis = state.get(f"{name}_analysis") or {}
        previous = (previous_analysis.get("technologies") or {}) if is_rework else {}
        prior_search_log: dict[str, dict[str, list[str]]] = {
            str(tech): {str(field): [str(query) for query in queries] for field, queries in (fields or {}).items()}
            for tech, fields in ((previous_analysis.get("search_log") or {}) if is_rework else {}).items()
        }
        judgments: dict[str, dict[str, dict[str, Any]]] = {tech: dict((previous or {}).get(tech) or {}) for tech in technologies}
        evidence: dict[str, Any] = {}
        sources: dict[str, Any] = {}
        errors: dict[str, Any] = {}
        metrics: dict[str, Any] = {}
        new_search_log: dict[str, dict[str, list[str]]] = {}

        if is_rework:
            research_by_tech: dict[str, list[dict[str, Any]]] = {}
            for request in _rework_requests(state, name):
                tech = str(request.get("technology") or "")
                if tech not in technologies:
                    continue
                if needs_research(request):
                    research_by_tech.setdefault(tech, []).append(request)
            targets = [tech for tech in technologies if tech in research_by_tech]
        else:
            research_by_tech = {}
            targets = _retry_technologies(state, name, technologies)

        for tech in targets:
            tech_requests = research_by_tech.get(tech, [])
            runtime_kwargs: dict[str, Any] = {}
            if is_rework and tech_requests:
                queries_by_topic: dict[str, list[str]] = {}
                topic_set: list[str] = []
                for request in tech_requests:
                    field = str(request.get("field") or "")
                    topic = _field_to_topic(name, field)
                    if not topic:
                        continue
                    prior_for_field = list(prior_search_log.get(tech, {}).get(field, []))
                    fresh = build_rework_queries(request, prior_for_field, paper_id=_TECH_PAPER_IDS.get(tech))
                    if fresh:
                        queries_by_topic.setdefault(topic, []).extend(fresh)
                    if topic not in topic_set:
                        topic_set.append(topic)
                    new_search_log.setdefault(tech, {})[field] = list(dict.fromkeys([*prior_for_field, *fresh]))
                if not topic_set:
                    continue
                runtime_kwargs["topics"] = tuple(topic_set)
                if queries_by_topic:
                    runtime_kwargs["queries_by_topic"] = queries_by_topic

            try:
                result = runner(
                    technologies=(tech,),
                    mode=_mode(state),
                    **_cache_kw(settings.cache_dir),
                    **kwargs,
                    **runtime_kwargs,
                )
            except Exception as exc:
                errors[_round_key(state, f"{name}-{tech}-collect", name, tech)] = {
                    "node": name,
                    "reason": f"{type(exc).__name__}: {exc}"[:500],
                    "fatal": False,
                    "recovered": False,
                    "kind": "service",
                }
                fallback = {
                    "label": "미확인",
                    "reason": f"{COLLECTION_FAILURE_PREFIX}({type(exc).__name__})로 판정하지 못함",
                    "conditions": "",
                    "evidence_ids": [],
                }
                if is_rework and tech_requests:
                    for request in tech_requests:
                        field = str(request.get("field") or "")
                        if field in LABELS[name]:
                            judgments[tech][field] = dict(fallback)
                else:
                    judgments[tech] = {field: dict(fallback) for field in LABELS[name]}
                metrics["failures"] = metrics.get("failures", 0) + 1
                continue

            analysis = result.get(f"{name}_analysis") or {}
            new_tech_judgments = dict((analysis.get("technologies") or {}).get(tech) or {})
            if is_rework and tech_requests:
                for request in tech_requests:
                    field = str(request.get("field") or "")
                    if field in new_tech_judgments:
                        judgments[tech][field] = new_tech_judgments[field]
            elif new_tech_judgments:
                judgments[tech] = new_tech_judgments
            evidence.update(result.get("evidence") or {})
            sources.update(result.get("sources") or {})
            for key, value in (result.get("errors") or {}).items():
                errors[_round_key(state, key, name, tech)] = value
            for key, value in (result.get("metrics") or {}).items():
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    metrics[key] = metrics.get(key, 0) + value

        _mark_single_source(judgments, _combined_evidence(state.get("evidence"), evidence))
        perspective_result = _perspective_result(name, judgments, technologies)
        merged_log = _merge_search_log(prior_search_log, new_search_log)
        if merged_log:
            perspective_result["search_log"] = merged_log
        return {
            f"{name}_analysis": perspective_result,
            "evidence": evidence,
            "sources": sources,
            "errors": errors,
            "metrics": metrics,
        }

    service.__name__ = name
    return service


def make_domain(settings: IntegrationSettings, branches: _Branches):
    def domain(state: Mapping[str, Any]) -> dict[str, Any]:
        from skala_rag.prompts.domain import DOMAIN_RUBRIC

        _ensure_budget_installed(settings)
        technologies = _technologies(state)
        is_rework = _is_rework(state, "domain")
        wanted = _retry_items(state, "domain")
        previous_analysis = state.get("domain_analysis") or {}
        previous = previous_analysis.get("technologies") if is_rework else None
        prior_search_log: dict[str, dict[str, list[str]]] = {
            str(tech): {str(field): [str(query) for query in queries] for field, queries in (fields or {}).items()}
            for tech, fields in ((previous_analysis.get("search_log") or {}) if is_rework else {}).items()
        }
        judgments: dict[str, dict[str, dict[str, Any]]] = {tech: dict((previous or {}).get(tech) or {}) for tech in technologies}
        collector = _EvidenceCollector(state, branches)
        model = _model_id(state, settings)
        rework_by_item: dict[tuple[str, str], dict[str, Any]] = {}
        if is_rework:
            for request in _rework_requests(state, "domain"):
                tech = str(request.get("technology") or "")
                field = str(request.get("field") or "")
                if tech and field:
                    rework_by_item[(tech, field)] = request
        new_search_log: dict[str, dict[str, list[str]]] = {}
        llm_calls = 0
        for tech in technologies:
            for spec in DOMAIN_RUBRIC:
                if wanted is not None and (tech, spec.item_key) not in wanted:
                    continue
                default_query = spec.query_hints_by_tech.get(tech) or f"{tech} {spec.question}"
                request = rework_by_item.get((tech, spec.item_key))
                if request and needs_research(request):
                    prior = list(prior_search_log.get(tech, {}).get(spec.item_key, []))
                    if default_query and default_query not in prior:
                        prior.append(default_query)
                    extra = build_rework_queries(request, prior, paper_id=_TECH_PAPER_IDS.get(tech))
                    queries = extra or [default_query]
                    k_each = settings.k_rag + 3  # widen the candidate pool on rework
                    new_search_log.setdefault(tech, {})[spec.item_key] = list(dict.fromkeys([*prior, *extra]))
                else:
                    queries = [default_query]
                    k_each = settings.k_rag
                all_candidates: list[Any] = []
                seen_ids: set[str] = set()
                for query in queries:
                    for candidate in collector.retrieve(query, tech, k_each):
                        candidate_id = str(getattr(candidate, "evidence_id", ""))
                        if candidate_id and candidate_id in seen_ids:
                            continue
                        if candidate_id:
                            seen_ids.add(candidate_id)
                        all_candidates.append(candidate)
                item = branches.judge_domain(spec, _tech_enum(tech), all_candidates, model)
                llm_calls += 1
                judgments[tech][spec.item_key] = _judgment_from_item(item)
        _mark_single_source(judgments, _combined_evidence(state.get("evidence"), collector.evidence))
        result = _perspective_result("domain", judgments, technologies)
        merged_log = _merge_search_log(prior_search_log, new_search_log)
        if merged_log:
            result["search_log"] = merged_log
        return {
            "domain_analysis": result,
            "evidence": collector.evidence,
            "sources": collector.sources,
            "errors": collector.error_records("domain", state),
            "metrics": collector.metrics(llm_calls=llm_calls),
        }

    return domain


def make_trl(settings: IntegrationSettings, branches: _Branches):
    def trl(state: Mapping[str, Any]) -> dict[str, Any]:
        from skala_rag.prompts.trl import TRL_STAGES

        _ensure_budget_installed(settings)
        technologies = _technologies(state)
        is_rework = _is_rework(state, "trl")
        targets = _retry_technologies(state, "trl", technologies)
        previous_analysis = state.get("trl_analysis") or {}
        previous = previous_analysis.get("technologies") if is_rework else None
        prior_search_log: dict[str, dict[str, list[str]]] = {
            str(tech): {str(field): [str(query) for query in queries] for field, queries in (fields or {}).items()}
            for tech, fields in ((previous_analysis.get("search_log") or {}) if is_rework else {}).items()
        }
        judgments: dict[str, dict[str, dict[str, Any]]] = {tech: dict((previous or {}).get(tech) or {}) for tech in technologies}
        collector = _EvidenceCollector(state, branches)
        model = _model_id(state, settings)
        mode = _mode(state)  # keep the run's live/replay choice; no more forced replay on rework
        rework_by_tech: dict[str, dict[str, Any]] = {}
        if is_rework:
            for request in _rework_requests(state, "trl"):
                tech = str(request.get("technology") or "")
                if tech:
                    rework_by_tech[tech] = request
        new_search_log: dict[str, dict[str, list[str]]] = {}
        llm_calls = 0
        for tech in targets:
            request = rework_by_tech.get(tech) if is_rework else None
            prev_stages: dict[str, dict[str, Any]] = (
                ((judgments[tech].get("trl") or {}).get("stages") or {}) if is_rework else {}
            )
            stage_results: list[tuple[Any, Any]] = []
            for spec in TRL_STAGES:
                prev_stage = prev_stages.get(spec.trl_label) if is_rework else None
                if prev_stage and prev_stage.get("met"):
                    # Previously confirmed stage: keep its judgment and skip new searches so
                    # the rework round focuses budget on genuinely unmet stages.
                    reused = SimpleNamespace(
                        verdict=prev_stage.get("verdict") or "충족",
                        reason=prev_stage.get("reason") or "",
                        evidence_ids=list(prev_stage.get("evidence_ids") or []),
                        missing_evidence_note=prev_stage.get("note") or "",
                    )
                    stage_results.append((spec, reused))
                    continue

                default_query = spec.query_hints_by_tech.get(tech) or f"{tech} {spec.description}"
                if is_rework and request and needs_research(request):
                    prior = list(prior_search_log.get(tech, {}).get(spec.stage_key, []))
                    if default_query and default_query not in prior:
                        prior.append(default_query)
                    extra = build_rework_queries(request, prior, paper_id=_TECH_PAPER_IDS.get(tech))
                    queries = extra or [default_query]
                    new_search_log.setdefault(tech, {})[spec.stage_key] = list(dict.fromkeys([*prior, *extra]))
                else:
                    queries = [default_query]

                all_candidates: list[Any] = []
                seen_ids: set[str] = set()
                if spec.evidence_mode == "rag":
                    for query in queries:
                        for candidate in collector.retrieve(query, tech, settings.k_rag):
                            candidate_id = str(getattr(candidate, "evidence_id", ""))
                            if candidate_id and candidate_id in seen_ids:
                                continue
                            if candidate_id:
                                seen_ids.add(candidate_id)
                            all_candidates.append(candidate)
                else:
                    question = (
                        f"[{spec.trl_label}] {spec.description}. {tech}에 대해 이 단계의 증거(공개 재현 코드, 주류 프레임워크 통합, "
                        "서비스 규모 시연, 상용 출시, 운영 실적)가 원문에 명시되어 있는가? 실제로 보고된 사실만 적어라."
                    )
                    for query in queries:
                        for candidate in collector.web_search(
                            query,
                            tech,
                            question,
                            f"trl-{spec.stage_key}",
                            settings.k_web,
                            settings.fetch_per_stage,
                            mode,
                            settings.cache_dir,
                        ):
                            candidate_id = str(getattr(candidate, "evidence_id", ""))
                            if candidate_id and candidate_id in seen_ids:
                                continue
                            if candidate_id:
                                seen_ids.add(candidate_id)
                            all_candidates.append(candidate)
                judgement = branches.judge_stage(spec, _tech_enum(tech), all_candidates, model)
                llm_calls += 1
                stage_results.append((spec, judgement))
            highest_label = "미확인"
            highest_reason = ""
            stages: dict[str, dict[str, Any]] = {}
            all_ids: list[str] = []
            top_ids: list[str] = []
            next_stage: tuple[str, str, str] | None = None  # (label, reason, missing note) of the first unmet stage above the highest met one
            for spec, judgement in stage_results:
                verdict = str(getattr(judgement, "verdict", "미확인"))
                ids = [str(identifier) for identifier in (getattr(judgement, "evidence_ids", None) or [])]
                reason_text = _clip(getattr(judgement, "reason", ""), 300)
                note = _clip(getattr(judgement, "missing_evidence_note", "") or "")
                met = verdict == "충족" and bool(ids)  # a stage without evidence IDs never counts as reached
                if verdict == "충족" and not ids:
                    verdict = "미확인"
                if met:
                    highest_label, highest_reason, top_ids = spec.trl_label, reason_text, ids
                    next_stage = None
                elif next_stage is None:
                    next_stage = (spec.trl_label, reason_text, note)
                stages[spec.trl_label] = {"met": met, "verdict": verdict, "evidence_ids": ids, "reason": reason_text, "note": note}
                all_ids.extend(ids)
            if highest_label == "미확인":
                reason = "어느 단계도 근거로 확인되지 않음"
            else:
                reason = f"확인된 최고 단계 {highest_label}: {highest_reason}"
            if next_stage is not None:
                reason += f" | 다음 단계 {next_stage[0]} 미충족: {next_stage[1]}"
            missing_notes = [f"[{next_stage[0]}] {next_stage[2] or next_stage[1]}"] if next_stage is not None else []
            judgments[tech]["trl"] = {
                "label": highest_label,
                "reason": reason,
                "conditions": missing_notes[0] if missing_notes else "",
                "evidence_ids": list(dict.fromkeys(top_ids or all_ids))[:5],
                "highest_confirmed": highest_label if highest_label != "미확인" else None,
                "stages": stages,
                "missing_evidence": missing_notes,
                "estimation_note": TRL_ESTIMATION_NOTE,
            }
        _mark_single_source(judgments, _combined_evidence(state.get("evidence"), collector.evidence))
        trl_result = _perspective_result("trl", judgments, technologies)
        merged_log = _merge_search_log(prior_search_log, new_search_log)
        if merged_log:
            trl_result["search_log"] = merged_log
        return {
            "trl_analysis": trl_result,
            "evidence": collector.evidence,
            "sources": collector.sources,
            "errors": collector.error_records("trl", state),
            "metrics": collector.metrics(llm_calls=llm_calls),
        }

    return trl


def create_services(settings: IntegrationSettings | None = None, **overrides: Any) -> PipelineServices:
    """Factory used by ``app.py``: ``--services skala_rag.integration.services:create_services``."""
    settings = settings or IntegrationSettings(**overrides)
    if settings.budget is None:
        # One shared budget per set of services, used by the three web-touching
        # perspective nodes. Caps are updated from run_config["budget"] when
        # ``prepare`` runs — see ``_rebuild_and_install_budget``.
        settings.budget = WebBudget()
    install_web_budget(settings.budget)
    branches = _Branches(settings)
    return PipelineServices(
        prepare=make_prepare(settings, branches),
        technical=make_technical(settings, branches),
        market=make_web_perspective("market", settings, branches),
        stakeholder=make_web_perspective("stakeholder", settings, branches),
        domain=make_domain(settings, branches),
        trl=make_trl(settings, branches),
    )


__all__ = ["IntegrationSettings", "create_services", "make_prepare", "make_technical", "make_web_perspective", "make_domain", "make_trl"]
