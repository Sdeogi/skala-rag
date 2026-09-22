"""Parallel LangGraph pipeline with bounded targeted evidence repair."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from langgraph.graph import END, START, StateGraph

from skala_rag.agents.report import build_report, save_outputs
from skala_rag.agents.synthesis import synthesize

from .evidence_check import SemanticReview, check_evidence
from .state import GraphState


Service = Callable[[GraphState], dict[str, Any]]


@dataclass
class PipelineServices:
    """Integration boundary for paper, web, and evaluation branches."""

    prepare: Service
    technical: Service
    market: Service
    stakeholder: Service
    domain: Service
    trl: Service
    retry: Service
    semantic_review: SemanticReview | None = None
    synthesis_writer: Service | None = None
    report_writer: Service | None = None


def initial_state(
    *,
    mode: str,
    technologies: tuple[str, str] = ("KIVI", "InfiniGen"),
    domain: str = "클라우드 LLM 서빙",
    model_id: str = "gpt-5.4-mini",
    paper_dir: str | None = None,
) -> GraphState:
    if mode not in {"live", "replay"}:
        raise ValueError("mode must be live or replay")
    if len(technologies) != 2 or len(set(technologies)) != 2 or not all(technologies):
        raise ValueError("technologies must contain two different names")
    if not domain.strip():
        raise ValueError("domain is required")
    return {
        "run_config": {"mode": mode, "technologies": list(technologies), "domain": domain, "model_id": model_id, "paper_dir": paper_dir},
        "sources": {}, "evidence": {}, "errors": {}, "missing_questions": [],
        "retry_count": 0, "artifacts": {}, "metrics": {},
        "started_at": datetime.now(timezone.utc).isoformat(),
    }


def _error(node: str, retry_count: int, reason: str, fatal: bool) -> dict[str, Any]:
    return {"errors": {f"{node}-{retry_count}": {"node": node, "reason": reason, "fatal": fatal, "recovered": False}}}


def _call_service(name: str, service: Service, state: GraphState, allowed: set[str], *, fatal: bool = False) -> dict[str, Any]:
    try:
        update = service(state)
        if not isinstance(update, Mapping):
            raise TypeError("service must return a partial State mapping")
        unexpected = set(update) - allowed
        if unexpected:
            raise ValueError(f"unexpected state keys: {sorted(unexpected)}")
        return dict(update)
    except Exception as exc:
        return _error(name, state.get("retry_count", 0), f"{type(exc).__name__}: {exc}", fatal)


def _has_fatal(state: GraphState) -> bool:
    return any(item.get("fatal") for item in state.get("errors", {}).values())


def build_graph(services: PipelineServices, *, output_dir: str | Path):
    """Compile an executable graph. The four perspective nodes share one superstep."""
    destination = Path(output_dir)
    builder = StateGraph(GraphState)

    def prepare(state: GraphState) -> dict[str, Any]:
        return _call_service("prepare", services.prepare, state, {"sources", "evidence", "errors", "metrics"}, fatal=True)

    def technical(state: GraphState) -> dict[str, Any]:
        return _call_service("technical", services.technical, state, {"technical_findings", "evidence", "sources", "errors", "metrics"}, fatal=True)

    def after_technical(state: GraphState) -> str:
        if _has_fatal(state):
            return "save"
        evidence = state.get("evidence", {})
        absent = [tech for tech in state["run_config"]["technologies"] if not any(item.get("technology") == tech for item in evidence.values())]
        return "technical_failed" if absent or not state.get("technical_findings") else "perspectives"

    def technical_failed(state: GraphState) -> dict[str, Any]:
        return _error("technical", 0, "one or both technologies lack technical findings or evidence", True)

    def perspective_node(name: str, service: Service):
        def node(state: GraphState) -> dict[str, Any]:
            return _call_service(name, service, state, {f"{name}_analysis", "evidence", "sources", "errors", "metrics"})
        return node

    def evidence_node(state: GraphState) -> dict[str, Any]:
        return check_evidence(state, services.semantic_review)

    def route_after_check(state: GraphState) -> str:
        return "retry" if state.get("missing_questions") and state.get("retry_count", 0) < 2 else "synthesis"

    def retry(state: GraphState) -> dict[str, Any]:
        update = _call_service("retry", services.retry, state, {"market_analysis", "stakeholder_analysis", "domain_analysis", "trl_analysis", "evidence", "sources", "errors", "metrics"})
        update["retry_count"] = state.get("retry_count", 0) + 1
        return update

    builder.add_node("prepare", prepare)
    builder.add_node("technical", technical)
    builder.add_node("technical_failed", technical_failed)
    builder.add_node("fan_out", lambda state: {})
    for name in ("market", "stakeholder", "domain", "trl"):
        builder.add_node(name, perspective_node(name, getattr(services, name)))
    builder.add_node("evidence_check", evidence_node)
    builder.add_node("retry", retry)
    builder.add_node("synthesis", lambda state: {"synthesis": (services.synthesis_writer or synthesize)(state)})
    builder.add_node("report", lambda state: {"report": (services.report_writer or build_report)(state)})
    builder.add_node("save", lambda state: {"artifacts": save_outputs(state, destination)})

    builder.add_edge(START, "prepare")
    builder.add_conditional_edges("prepare", lambda state: "save" if _has_fatal(state) else "technical")
    builder.add_conditional_edges("technical", after_technical, {"save": "save", "technical_failed": "technical_failed", "perspectives": "fan_out"})
    builder.add_edge("technical_failed", "save")
    for name in ("market", "stakeholder", "domain", "trl"):
        builder.add_edge("fan_out", name)
    builder.add_edge(["market", "stakeholder", "domain", "trl"], "evidence_check")
    builder.add_conditional_edges("evidence_check", route_after_check, {"retry": "retry", "synthesis": "synthesis"})
    builder.add_edge("retry", "evidence_check")
    builder.add_edge("synthesis", "report")
    builder.add_edge("report", "save")
    builder.add_edge("save", END)
    return builder.compile()
