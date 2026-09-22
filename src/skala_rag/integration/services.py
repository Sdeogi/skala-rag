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

Repair rounds (``state["retry_mode"]``) re-run only the technologies/items named
in ``state["missing_questions"]`` and merge into the previous perspective result.

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
from typing import Any

from skala_rag.graph.schemas import LABELS, UNKNOWN_LABELS
from skala_rag.graph.workflow import PipelineServices

logger = logging.getLogger(__name__)

DEFAULT_PAPERS_DIR = "data/papers"
DEFAULT_INDEX_DIR = "indexes"
TRL_ESTIMATION_NOTE = "공개 정보 기반 추정. 논문 발표 시점과 실제 채택 시점 사이에 시차가 있어 확정 단계가 아님"
NOTE_LIMIT = 220
_RETRIEVE_LOCK = threading.Lock()  # the four perspective nodes run in threads; FAISS/e5 access is serialized


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


def _missing(state: Mapping[str, Any], perspective: str) -> list[dict[str, Any]]:
    return [q for q in (state.get("missing_questions") or []) if q.get("perspective") == perspective]


def _retry_technologies(state: Mapping[str, Any], perspective: str, technologies: list[str]) -> list[str]:
    """Technologies to (re)run: all on a normal call, only the failing ones in a repair round."""
    if not state.get("retry_mode"):
        return technologies
    wanted = sorted({str(q["technology"]) for q in _missing(state, perspective)})
    return [tech for tech in technologies if tech in wanted] or technologies


def _retry_items(state: Mapping[str, Any], perspective: str) -> set[tuple[str, str]] | None:
    if not state.get("retry_mode"):
        return None
    return {(str(q["technology"]), str(q["field"])) for q in _missing(state, perspective)}


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


def _round_key(state: Mapping[str, Any], key: str) -> str:
    return f"{key}-r{int(state.get('retry_count', 0) or 0)}" if state.get("retry_mode") else key


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
        self.existing = dict(state.get("evidence") or {})
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
            records[_round_key(state, f"{node}-web-{index}")] = {
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

    Each technology is collected separately so one failure (missing replay cache,
    search API error) degrades that technology to 미확인 instead of dropping the
    whole perspective. Repair rounds re-run only the failing technologies.
    """
    runner = branches.market_agent if name == "market" else branches.stakeholder_agent
    kwargs = settings.market_kwargs if name == "market" else settings.stakeholder_kwargs

    def service(state: Mapping[str, Any]) -> dict[str, Any]:
        technologies = _technologies(state)
        previous = (state.get(f"{name}_analysis") or {}).get("technologies") if state.get("retry_mode") else None
        judgments: dict[str, dict[str, dict[str, Any]]] = {tech: dict((previous or {}).get(tech) or {}) for tech in technologies}
        evidence: dict[str, Any] = {}
        sources: dict[str, Any] = {}
        errors: dict[str, Any] = {}
        metrics: dict[str, Any] = {}
        targets = _retry_technologies(state, name, technologies)
        if state.get("retry_mode") and previous:
            # B's agents search fixed query templates, not the missing questions, so repeating a
            # successful collection would repeat the same searches (and API budget) for the same
            # outcome. Only technologies whose collection itself failed are collected again.
            targets = [tech for tech in targets if _collection_failed(judgments.get(tech) or {})]
            metrics["repair_skipped"] = len(_retry_technologies(state, name, technologies)) - len(targets)
            if not targets:
                return {
                    f"{name}_analysis": _perspective_result(name, judgments, technologies),
                    "evidence": {},
                    "sources": {},
                    "errors": {},
                    "metrics": metrics,
                }
        for tech in targets:
            try:
                result = runner(technologies=(tech,), mode=_mode(state), **_cache_kw(settings.cache_dir), **kwargs)
            except Exception as exc:
                errors[_round_key(state, f"{name}-{tech}-collect")] = {
                    "node": name,
                    "reason": f"{type(exc).__name__}: {exc}"[:500],
                    "fatal": False,
                    "recovered": False,
                    "kind": "service",
                }
                judgments[tech] = {
                    field: {"label": "미확인", "reason": f"{COLLECTION_FAILURE_PREFIX}({type(exc).__name__})로 판정하지 못함", "conditions": "", "evidence_ids": []}
                    for field in LABELS[name]
                }
                metrics["failures"] = metrics.get("failures", 0) + 1
                continue
            analysis = result.get(f"{name}_analysis") or {}
            judgments[tech] = dict((analysis.get("technologies") or {}).get(tech) or judgments[tech])
            evidence.update(result.get("evidence") or {})
            sources.update(result.get("sources") or {})
            for key, value in (result.get("errors") or {}).items():
                errors[_round_key(state, key)] = value
            for key, value in (result.get("metrics") or {}).items():
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    metrics[key] = metrics.get(key, 0) + value
        return {
            f"{name}_analysis": _perspective_result(name, judgments, technologies),
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

        technologies = _technologies(state)
        wanted = _retry_items(state, "domain")
        previous = (state.get("domain_analysis") or {}).get("technologies") if state.get("retry_mode") else None
        judgments: dict[str, dict[str, dict[str, Any]]] = {tech: dict((previous or {}).get(tech) or {}) for tech in technologies}
        collector = _EvidenceCollector(state, branches)
        model = _model_id(state, settings)
        llm_calls = 0
        for tech in technologies:
            for spec in DOMAIN_RUBRIC:
                if wanted is not None and (tech, spec.item_key) not in wanted:
                    continue
                query = spec.query_hints_by_tech.get(tech) or f"{tech} {spec.question}"
                candidates = collector.retrieve(query, tech, settings.k_rag)
                item = branches.judge_domain(spec, _tech_enum(tech), candidates, model)
                llm_calls += 1
                judgments[tech][spec.item_key] = _judgment_from_item(item)
        return {
            "domain_analysis": _perspective_result("domain", judgments, technologies),
            "evidence": collector.evidence,
            "sources": collector.sources,
            "errors": collector.error_records("domain", state),
            "metrics": collector.metrics(llm_calls=llm_calls),
        }

    return domain


def make_trl(settings: IntegrationSettings, branches: _Branches):
    def trl(state: Mapping[str, Any]) -> dict[str, Any]:
        from skala_rag.prompts.trl import TRL_STAGES

        technologies = _technologies(state)
        targets = _retry_technologies(state, "trl", technologies)
        previous = (state.get("trl_analysis") or {}).get("technologies") if state.get("retry_mode") else None
        judgments: dict[str, dict[str, dict[str, Any]]] = {tech: dict((previous or {}).get(tech) or {}) for tech in technologies}
        collector = _EvidenceCollector(state, branches)
        model = _model_id(state, settings)
        # Repair rounds re-judge with the web pages cached by the first round instead of searching again.
        mode = "replay" if state.get("retry_mode") else _mode(state)
        llm_calls = 0
        for tech in targets:
            stage_results: list[tuple[Any, Any]] = []
            for spec in TRL_STAGES:
                query = spec.query_hints_by_tech.get(tech) or f"{tech} {spec.description}"
                if spec.evidence_mode == "rag":
                    candidates = collector.retrieve(query, tech, settings.k_rag)
                else:
                    question = (
                        f"[{spec.trl_label}] {spec.description}. {tech}에 대해 이 단계의 증거(공개 재현 코드, 주류 프레임워크 통합, "
                        "서비스 규모 시연, 상용 출시, 운영 실적)가 원문에 명시되어 있는가? 실제로 보고된 사실만 적어라."
                    )
                    candidates = collector.web_search(query, tech, question, f"trl-{spec.stage_key}", settings.k_web, settings.fetch_per_stage, mode, settings.cache_dir)
                judgement = branches.judge_stage(spec, _tech_enum(tech), candidates, model)
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
        return {
            "trl_analysis": _perspective_result("trl", judgments, technologies),
            "evidence": collector.evidence,
            "sources": collector.sources,
            "errors": collector.error_records("trl", state),
            "metrics": collector.metrics(llm_calls=llm_calls),
        }

    return trl


def create_services(settings: IntegrationSettings | None = None, **overrides: Any) -> PipelineServices:
    """Factory used by ``app.py``: ``--services skala_rag.integration.services:create_services``."""
    settings = settings or IntegrationSettings(**overrides)
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
