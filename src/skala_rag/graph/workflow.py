"""Parallel LangGraph pipeline with bounded, targeted evidence repair (design D.3, D.4).

START → prepare → technical → {market, stakeholder, domain, trl} (one superstep)
→ evidence_check → (retry → repair[per perspective, Send] → evidence_check, at most
twice) → synthesis → report → save → END. Fatal errors in prepare/technical skip
straight to save so a manifest is always written.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any

from langgraph.errors import GraphBubbleUp
from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from skala_rag.agents.report import build_report, save_outputs
from skala_rag.agents.synthesis import synthesize

from .evidence_check import SemanticReview, check_evidence
from .schemas import PERSPECTIVES, RunConfig, validate_update
from .state import GraphState, metric_event

Service = Callable[[GraphState], dict[str, Any]]
MAX_RETRIES = 2
SHARED_UPDATE_KEYS = {"evidence", "sources", "errors", "metrics"}


@dataclass
class PipelineServices:
    """Integration boundary for the paper, web and evaluation branches.

    Each callable receives the State (a mapping) and returns a partial State
    dict. ``retry`` is optional: without it the graph re-invokes the perspective
    services whose items failed, passing only their ``missing_questions`` and
    ``retry_mode=True``. ``semantic_review`` defaults to the review LLM in live mode.
    """

    prepare: Service
    technical: Service
    market: Service
    stakeholder: Service
    domain: Service
    trl: Service
    retry: Service | None = None
    semantic_review: SemanticReview | None = None
    synthesis_writer: Service | None = None
    report_writer: Service | None = None


def initial_state(
    *,
    mode: str,
    technologies: tuple[str, str] | list[str] = ("KIVI", "InfiniGen"),
    domain: str = "클라우드 LLM 서빙",
    model_id: str = "gpt-5.4-mini",
    paper_dir: str | None = None,
    as_of: str | None = None,
    budget: Mapping[str, Any] | None = None,
    max_paper_pages: int = 200,
    fixture: bool = False,
    **extra: Any,
) -> GraphState:
    """Validated initial State. Raises ``ValueError`` (pydantic) on bad settings."""
    payload: dict[str, Any] = {
        "mode": mode,
        "technologies": list(technologies),
        "domain": domain,
        "model_id": model_id,
        "paper_dir": paper_dir,
        "as_of": as_of or datetime.now(timezone.utc).date().isoformat(),
        "max_paper_pages": max_paper_pages,
        "fixture": fixture,
        **extra,
    }
    if budget:
        payload["budget"] = dict(budget)
    config = RunConfig.model_validate(payload)
    return {
        "run_config": config.model_dump(),
        "sources": {},
        "evidence": {},
        "errors": {},
        "missing_questions": [],
        "retry_count": 0,
        "artifacts": {},
        "metrics": [],
        "started_at": datetime.now(timezone.utc).isoformat(),
    }


def _error(node: str, retry_count: int, reason: str, fatal: bool, kind: str = "service") -> dict[str, Any]:
    key = f"{node}-{retry_count}" + ("" if kind == "service" else f"-{kind}")
    return {"errors": {key: {"node": node, "reason": reason, "fatal": fatal, "recovered": False, "kind": kind}}}


def _call_service(name: str, service: Service, state: Mapping[str, Any], allowed: set[str], *, fatal: bool = False) -> dict[str, Any]:
    """Call a branch service, validate its update at the boundary, time it."""
    started = perf_counter()
    retry_count = int(state.get("retry_count", 0) or 0)
    try:
        update = service(state)  # type: ignore[arg-type]
        if not isinstance(update, Mapping):
            raise TypeError("service must return a partial State mapping")
    except GraphBubbleUp:
        raise
    except Exception as exc:
        result = _error(name, retry_count, f"{type(exc).__name__}: {exc}", fatal)
        result["metrics"] = [metric_event(name, elapsed_seconds=round(perf_counter() - started, 3), failures=1)]
        return result
    update = dict(update)
    problems: list[str] = []
    for key in sorted(set(update) - set(allowed)):
        update.pop(key)
        problems.append(f"unexpected state key dropped: {key}")
    clean, schema_problems = validate_update(name, update)
    problems.extend(schema_problems)
    if problems:
        errors = dict(clean.get("errors") or {})
        errors[f"{name}-{retry_count}-schema"] = {
            "node": name,
            "reason": "; ".join(problems)[:1000],
            "fatal": False,
            "recovered": False,
            "kind": "schema",
        }
        clean["errors"] = errors
    clean["metrics"] = list(clean.get("metrics") or []) + [metric_event(name, elapsed_seconds=round(perf_counter() - started, 3))]
    return clean


def _has_fatal(state: Mapping[str, Any]) -> bool:
    return any(item.get("fatal") for item in (state.get("errors") or {}).values())


def _paper_pages(sources: Mapping[str, Any]) -> int:
    return sum(
        int(item.get("pages") or 0)
        for item in sources.values()
        if isinstance(item, Mapping) and str(item.get("source_type") or "").lower() == "paper"
    )


def build_graph(services: PipelineServices, *, output_dir: str | Path, report_name: str = "report"):
    """Compile the executable graph. The four perspective nodes share one superstep."""
    destination = Path(output_dir)
    builder = StateGraph(GraphState)

    def prepare(state: GraphState) -> dict[str, Any]:
        update = _call_service("prepare", services.prepare, state, {"sources", "evidence", "errors", "metrics"}, fatal=True)
        limit = int(state["run_config"].get("max_paper_pages") or 0)
        pages = _paper_pages(update.get("sources") or {})
        if limit and pages > limit:
            errors = dict(update.get("errors") or {})
            errors["prepare-0-pages"] = {
                "node": "prepare",
                "reason": f"paper pages {pages} exceed the limit of {limit}",
                "fatal": True,
                "recovered": False,
                "kind": "service",
            }
            update["errors"] = errors
        return update

    def technical(state: GraphState) -> dict[str, Any]:
        return _call_service("technical", services.technical, state, {"technical_findings", "evidence", "sources", "errors", "metrics"}, fatal=True)

    def route_after_prepare(state: GraphState) -> str:
        return "save" if _has_fatal(state) else "technical"

    def route_after_technical(state: GraphState) -> str | list[str]:
        if _has_fatal(state):
            return "save"
        evidence = state.get("evidence") or {}
        absent = [
            technology
            for technology in state["run_config"]["technologies"]
            if not any(item.get("technology") == technology for item in evidence.values())
        ]
        if absent or not state.get("technical_findings"):
            return "technical_failed"
        return list(PERSPECTIVES)

    def technical_failed(state: GraphState) -> dict[str, Any]:
        return _error("technical", 0, "one or both technologies lack technical findings or evidence", True)

    def perspective_node(name: str):
        def node(state: GraphState) -> dict[str, Any]:
            return _call_service(name, getattr(services, name), state, {f"{name}_analysis", *SHARED_UPDATE_KEYS})

        node.__name__ = name
        return node

    def evidence_node(state: GraphState) -> dict[str, Any]:
        return check_evidence(state, services.semantic_review)

    def route_after_check(state: GraphState) -> str:
        return "retry" if state.get("missing_questions") and int(state.get("retry_count", 0)) < MAX_RETRIES else "synthesis"

    def retry(state: GraphState) -> dict[str, Any]:
        count = int(state.get("retry_count", 0)) + 1
        if services.retry is not None:
            update = _call_service("retry", services.retry, state, {f"{name}_analysis" for name in PERSPECTIVES} | SHARED_UPDATE_KEYS)
            update["retry_count"] = count
            return update
        targets = sorted({question["perspective"] for question in state.get("missing_questions", []) or []})
        return {"retry_count": count, "metrics": [metric_event("retry", repair_rounds=1, repairs=len(targets))]}

    def dispatch_repairs(state: GraphState):
        if services.retry is not None:
            return "evidence_check"
        questions = list(state.get("missing_questions", []) or [])
        targets = sorted({question["perspective"] for question in questions})
        if not targets:
            return "evidence_check"
        return [
            Send(
                "repair",
                {
                    **state,
                    "repair_perspective": name,
                    "missing_questions": [question for question in questions if question["perspective"] == name],
                    "retry_mode": True,
                },
            )
            for name in targets
        ]

    def repair(payload: Mapping[str, Any]) -> dict[str, Any]:
        name = payload["repair_perspective"]
        return _call_service(name, getattr(services, name), payload, {f"{name}_analysis", *SHARED_UPDATE_KEYS})

    def synthesis_node(state: GraphState) -> dict[str, Any]:
        result = dict((services.synthesis_writer or synthesize)(state) or {})
        events = result.pop("metrics", []) or []
        return {"synthesis": result, "metrics": list(events)}

    def report_node(state: GraphState) -> dict[str, Any]:
        result = dict((services.report_writer or build_report)(state) or {})
        events = result.pop("metrics", []) or []
        return {"report": result, "metrics": list(events)}

    def save(state: GraphState) -> dict[str, Any]:
        return {"artifacts": save_outputs(state, destination, report_name=report_name)}

    builder.add_node("prepare", prepare)
    builder.add_node("technical", technical)
    builder.add_node("technical_failed", technical_failed)
    for name in PERSPECTIVES:
        builder.add_node(name, perspective_node(name))
    builder.add_node("evidence_check", evidence_node)
    builder.add_node("retry", retry)
    builder.add_node("repair", repair)
    builder.add_node("synthesis", synthesis_node)
    builder.add_node("report", report_node)
    builder.add_node("save", save)

    builder.add_edge(START, "prepare")
    builder.add_conditional_edges("prepare", route_after_prepare, {"save": "save", "technical": "technical"})
    builder.add_conditional_edges("technical", route_after_technical, [*PERSPECTIVES, "save", "technical_failed"])
    builder.add_edge("technical_failed", "save")
    builder.add_edge(list(PERSPECTIVES), "evidence_check")
    builder.add_conditional_edges("evidence_check", route_after_check, {"retry": "retry", "synthesis": "synthesis"})
    builder.add_conditional_edges("retry", dispatch_repairs, ["repair", "evidence_check"])
    builder.add_edge("repair", "evidence_check")
    builder.add_edge("synthesis", "report")
    builder.add_edge("report", "save")
    builder.add_edge("save", END)
    return builder.compile()


def draw_mermaid(services: PipelineServices | None = None) -> str:
    """Mermaid source of the compiled graph (for the README architecture figure)."""
    if services is None:
        from .demo import create_services

        services = create_services()
    return build_graph(services, output_dir=".").get_graph().draw_mermaid()
