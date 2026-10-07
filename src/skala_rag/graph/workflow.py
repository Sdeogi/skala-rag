"""Supervisor-hub LangGraph pipeline.

START → prepare → supervisor ⇄ technical
                            ⇄ market / stakeholder / domain / trl   (Send, several at once)
                            ⇄ synthesis
                            ⇄ report
                            ⇄ quality
                 supervisor → save → END

Every node except ``prepare`` and ``save`` returns to ``supervisor``; sub-agents
never talk to each other. The supervisor reads the State (which perspectives
came back, whether their evidence is sufficient, the quality verdict) and picks
the next node(s) with ``add_conditional_edges``. Perspective agents are always
dispatched with ``Send`` and receive only the four payload keys they need.
Rework and quality loops are bounded per agent, per loop and by a global
decision budget, so the graph always terminates.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any
from uuid import uuid4

from langgraph.errors import GraphBubbleUp
from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from skala_rag.config import DEFAULT_MODEL_ID
from skala_rag.agents.report import build_report, save_outputs
from skala_rag.agents.synthesis import synthesize

from .evidence_check import SemanticReview, check_evidence
from .schemas import (
    AGENTS,
    DECISION_LOG_LIMIT,
    MAX_QUALITY_LOOPS,
    MAX_REWORK_PER_AGENT,
    MAX_SUPERVISOR_STEPS,
    PERSPECTIVE_TITLES,
    PERSPECTIVES,
    QUALITY_ITEMS,
    QUALITY_THRESHOLD,
    QualityResult,
    RunConfig,
    summarize_validation_error,
    validate_update,
)
from .state import GraphState, metric_event

Service = Callable[[GraphState], dict[str, Any]]
SHARED_UPDATE_KEYS = {"evidence", "sources", "errors", "metrics"}
# Everything the supervisor can route to. Perspectives are reached through ``Send``.
ROUTES: tuple[str, ...] = ("technical", *PERSPECTIVES, "synthesis", "report", "quality", "save")
# The only keys a perspective agent receives (contract between the graph and the sub-agents).
SEND_PAYLOAD_KEYS: tuple[str, ...] = ("run_config", "{name}_analysis", "rework_requests", "known_evidence_ids")


@dataclass
class PipelineServices:
    """Integration boundary for the paper, web, quality and output branches.

    Each callable receives a State mapping and returns a partial State dict.
    Perspective services receive only ``run_config``, their previous
    ``{name}_analysis``, their own ``rework_requests`` and ``known_evidence_ids``.
    ``semantic_review`` defaults to the review LLM in live mode. ``quality_evaluator``
    is ``None`` until the quality branch is merged; the graph then uses a
    placeholder that always passes.
    """

    prepare: Service
    technical: Service
    market: Service
    stakeholder: Service
    domain: Service
    trl: Service
    semantic_review: SemanticReview | None = None
    synthesis_writer: Service | None = None
    report_writer: Service | None = None
    quality_evaluator: Service | None = None


def new_agent_status() -> dict[str, dict[str, Any]]:
    return {name: {"status": "pending", "attempts": 0, "last_error": ""} for name in AGENTS}


def initial_state(
    *,
    mode: str,
    technologies: tuple[str, str] | list[str] = ("KIVI", "InfiniGen"),
    domain: str = "클라우드 LLM 서빙",
    model_id: str = DEFAULT_MODEL_ID,
    paper_dir: str | None = None,
    as_of: str | None = None,
    budget: Mapping[str, Any] | None = None,
    max_paper_pages: int = 200,
    fixture: bool = False,
    run_id: str | None = None,
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
        "run_id": run_id or uuid4().hex,
        "next": [],
        "step_count": 0,
        "agent_status": new_agent_status(),
        "rework_requests": [],
        "decision_log": [],
        "quality_result": {},
        "quality_attempts": 0,
        "run_config": config.model_dump(),
        "sources": {},
        "evidence": {},
        "errors": {},
        "artifacts": {},
        "metrics": [],
        "started_at": datetime.now(timezone.utc).isoformat(),
    }


def placeholder_quality(state: Mapping[str, Any]) -> dict[str, Any]:
    """Quality evaluator used until the real one is wired in: every criterion passes."""
    return {
        "quality_result": {
            "passed": True,
            "threshold": QUALITY_THRESHOLD,
            "items": {name: {"score": 5, "rule_score": 5, "llm_score": None, "reasons": []} for name in QUALITY_ITEMS},
            "action": "pass",
            "instructions": [],
            "rework_requests": [],
            "evaluator": "placeholder",
        },
        "metrics": {"placeholder": 1},
    }


def send_payload(state: Mapping[str, Any], name: str) -> dict[str, Any]:
    """The four keys a perspective agent receives through ``Send``."""
    return {
        "run_config": state.get("run_config") or {},
        f"{name}_analysis": state.get(f"{name}_analysis"),
        "rework_requests": [item for item in (state.get("rework_requests") or []) if item.get("perspective") == name],
        "known_evidence_ids": sorted(state.get("evidence") or {}),
    }


def _round(state: Mapping[str, Any]) -> int:
    """Rework round of the payload (0 on the first run), used to key error records."""
    return max((int(item.get("attempt") or 0) for item in (state.get("rework_requests") or []) if isinstance(item, Mapping)), default=0)


def _error(node: str, round_: int, reason: str, fatal: bool, kind: str = "service") -> dict[str, Any]:
    key = f"{node}-{round_}" + ("" if kind == "service" else f"-{kind}")
    return {"errors": {key: {"node": node, "reason": reason, "fatal": fatal, "recovered": False, "kind": kind}}}


def _call_service(
    name: str,
    service: Service,
    state: Mapping[str, Any],
    allowed: set[str],
    *,
    fatal: bool = False,
    round_: int | None = None,
) -> dict[str, Any]:
    """Call a branch service, validate its update at the boundary, time it.

    Keys outside ``allowed`` (control fields included) are dropped and recorded
    as a schema error, so a sub-agent can never steer the supervisor.
    """
    started = perf_counter()
    current = _round(state) if round_ is None else round_
    try:
        update = service(state)  # type: ignore[arg-type]
        if not isinstance(update, Mapping):
            raise TypeError("service must return a partial State mapping")
    except GraphBubbleUp:
        raise
    except Exception as exc:
        result = _error(name, current, f"{type(exc).__name__}: {exc}", fatal)
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
        errors[f"{name}-{current}-schema"] = {
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


def _statuses(state: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """A private copy of ``agent_status`` with every agent present."""
    current = state.get("agent_status") or {}
    statuses = new_agent_status()
    for name in AGENTS:
        entry = current.get(name) or {}
        statuses[name].update({key: entry[key] for key in ("status", "attempts", "last_error") if key in entry})
        statuses[name]["attempts"] = int(statuses[name]["attempts"] or 0)
    return statuses


def _title(name: str) -> str:
    return PERSPECTIVE_TITLES.get(name, name)


def _codes(questions: list[Mapping[str, Any]]) -> str:
    return ",".join(sorted({code for question in questions for code in (question.get("reasons") or [])})) or "근거 미확인"


def supervise(state: GraphState, semantic_review: SemanticReview | None = None) -> dict[str, Any]:
    """One supervisor decision. Returns the control-field update for this turn.

    Order (first match wins): fatal error → save; decision budget exhausted →
    forced finish; no technical findings → technical; pending perspectives →
    run them; perspectives just returned → judge evidence sufficiency and
    rework the insufficient ones or move to synthesis; synthesis → report →
    quality; quality verdict → rewrite, recollect or save.
    """
    step = int(state.get("step_count", 0) or 0) + 1
    previous = list(state.get("next") or [])
    statuses = _statuses(state)
    errors = state.get("errors") or {}
    quality = dict(state.get("quality_result") or {})
    quality_attempts = int(state.get("quality_attempts", 0) or 0)
    technologies = list((state.get("run_config") or {}).get("technologies") or [])
    update: dict[str, Any] = {"step_count": step, "rework_requests": [], "agent_status": statuses}
    metrics: list[dict[str, Any]] = [metric_event("supervisor", decisions=1)]

    def decide(next_nodes: list[str], decision: str, reason: str) -> dict[str, Any]:
        log = list(state.get("decision_log") or []) + [{"step": step, "decision": decision, "reason": reason}]
        update.update(next=list(next_nodes), decision_log=log[-DECISION_LOG_LIMIT:], metrics=metrics)
        return update

    # ── settle agents that ran in the previous superstep ──
    technical = statuses["technical"]
    if technical["status"] == "running":
        if state.get("technical_findings"):
            technical.update(status="done", last_error="")
        else:
            technical.update(status="failed", last_error=str((errors.get("technical-0") or {}).get("reason") or "no technical findings"))
    failing: dict[str, list[dict[str, Any]]] = {}
    evaluated = any(statuses[name]["status"] == "running" for name in PERSPECTIVES)
    if evaluated:
        result = check_evidence(state, semantic_review)
        update["evidence_check"] = result["evidence_check"]
        metrics.extend(result.get("metrics") or [])
        for question in result.get("missing_questions") or []:
            failing.setdefault(str(question["perspective"]), []).append(dict(question))
        for name in PERSPECTIVES:
            entry = statuses[name]
            error = errors.get(f"{name}-{entry['attempts']}") or {}
            if error and error.get("kind") == "service":
                entry.update(status="failed", last_error=str(error.get("reason") or ""))
            elif failing.get(name):
                entry.update(status="insufficient")
            else:
                entry.update(status="done", last_error="")

    # ── 1. fatal error ──
    if _has_fatal(state):
        return decide(["save"], "save", "치명 오류가 기록되어 있는 자료만 저장하고 종료")

    # ── 2. decision budget ──
    if step > MAX_SUPERVISOR_STEPS:
        if state.get("report"):
            return decide(["save"], "step_limit:save", f"Supervisor 결정 횟수 상한({MAX_SUPERVISOR_STEPS}회) 도달 → 현재 보고서로 저장")
        return decide(["report"], "step_limit:report", f"Supervisor 결정 횟수 상한({MAX_SUPERVISOR_STEPS}회) 도달 → 있는 자료로 보고서를 한 번 쓰고 종료")

    # ── 3. technical findings first ──
    if not state.get("technical_findings"):
        technical.update(status="running")
        return decide(["technical"], "technical", "기술 분석 결과가 없어 기술 에이전트를 실행")

    # ── 4. perspectives that never ran ──
    pending = [name for name in PERSPECTIVES if statuses[name]["status"] == "pending"]
    if pending:
        for name in pending:
            statuses[name]["status"] = "running"
        return decide(pending, "run:" + ",".join(pending), ", ".join(_title(name) for name in pending) + " 관점 결과가 없어 실행")

    # ── 5. evidence sufficiency of the perspectives that just returned ──
    if evaluated:
        targets = [name for name in PERSPECTIVES if failing.get(name) and statuses[name]["attempts"] < MAX_REWORK_PER_AGENT]
        capped = [name for name in PERSPECTIVES if failing.get(name) and statuses[name]["attempts"] >= MAX_REWORK_PER_AGENT]
        notes = [f"{_title(name)} {len(failing[name])}개 항목 근거 부족({_codes(failing[name])})이나 재작업 상한({MAX_REWORK_PER_AGENT}회) 도달" for name in capped]
        if targets:
            requests: list[dict[str, Any]] = []
            reasons: list[str] = []
            for name in targets:
                attempt = statuses[name]["attempts"] + 1
                statuses[name].update(status="running", attempts=attempt)
                requests.extend({**question, "attempt": attempt} for question in failing[name])
                reasons.append(f"{_title(name)} {len(failing[name])}개 항목 근거 부족({_codes(failing[name])}) → 재작업 {attempt}회차")
            update["rework_requests"] = requests
            return decide(targets, "rework:" + ",".join(targets), "; ".join(reasons + notes))
        reason = "; ".join(notes) + " → 부족한 채로 종합 진행" if notes else "모든 관점의 근거가 충분해 종합 진행"
        return decide(["synthesis"], "synthesis", reason)

    # ── 6. synthesis → report → quality ──
    if previous == ["synthesis"]:
        return decide(["report"], "report", "종합 완료 → 보고서 작성")
    if previous == ["report"]:
        if quality.get("action") == "accept_with_limits":
            return decide(["save"], "save", "한계를 명시한 보고서 작성 완료 → 저장")
        return decide(["quality"], "quality", "보고서 작성 완료 → 품질 평가")

    # ── 7. quality verdict ──
    if previous == ["quality"]:
        action = str(quality.get("action") or ("pass" if quality.get("passed", True) else "rewrite_report"))
        threshold = int(quality.get("threshold") or QUALITY_THRESHOLD)
        # An item may carry its own pass line (bias control passes at 3).
        below = [
            name
            for name, item in (quality.get("items") or {}).items()
            if isinstance(item, Mapping) and int(item.get("score") or 0) < int(item.get("threshold") or threshold)
        ]
        summary = ", ".join(below) or "미달 항목 없음"
        if action == "pass":
            return decide(["save"], "save", f"품질 평가 통과(기준 {threshold}점) → 저장")
        if action == "accept_with_limits":
            return decide(["report"], "accept_with_limits", f"품질 평가가 한계 수용을 제안({summary}) → 한계를 명시해 보고서 마무리")
        if action == "rewrite_report":
            if quality_attempts >= MAX_QUALITY_LOOPS:
                quality["action"] = "accept_with_limits"
                update["quality_result"] = quality
                return decide(["report"], "accept_with_limits", f"품질 미달({summary})이나 품질 루프 상한({MAX_QUALITY_LOOPS}회) 도달 → 한계를 명시해 보고서 마무리")
            update["quality_attempts"] = quality_attempts + 1
            return decide(["report"], "rewrite_report", f"품질 미달({summary}) → 보고서 재작성 {quality_attempts + 1}회차")
        if action == "recollect":
            requests = [dict(item) for item in (quality.get("rework_requests") or []) if isinstance(item, Mapping)]
            wanted = list(dict.fromkeys(str(item.get("perspective")) for item in requests))
            viable = [name for name in wanted if name in PERSPECTIVES and statuses[name]["attempts"] < MAX_REWORK_PER_AGENT]
            exhausted = [name for name in wanted if name in PERSPECTIVES and name not in viable]
            rewritable = [item for item in (quality.get("instructions") or []) if isinstance(item, Mapping)]
            if not viable and rewritable and quality_attempts < MAX_QUALITY_LOOPS:
                # Nothing can be collected again, but the evaluation also pointed at sentences: rewrite those.
                quality["action"] = "rewrite_report"
                update["quality_result"] = quality
                update["quality_attempts"] = quality_attempts + 1
                return decide(
                    ["report"],
                    "rewrite_report",
                    f"품질 미달({summary}), 재수집 요청({', '.join(_title(n) for n in wanted) or '없음'})은 재작업 횟수가 남아 있지 않아 불가 → "
                    f"지적된 문장 {len(rewritable)}건을 고쳐 쓰는 보고서 재작성 {quality_attempts + 1}회차",
                )
            if quality_attempts >= MAX_QUALITY_LOOPS or not viable:
                quality["action"] = "accept_with_limits"
                update["quality_result"] = quality
                why = f"품질 루프 상한({MAX_QUALITY_LOOPS}회) 도달" if quality_attempts >= MAX_QUALITY_LOOPS else "재수집할 관점의 재작업 횟수가 남아 있지 않음"
                return decide(["report"], "accept_with_limits", f"품질 미달({summary}), 재수집 요청({', '.join(_title(n) for n in wanted) or '없음'})이나 {why} → 한계를 명시해 보고서 마무리")
            update["quality_attempts"] = quality_attempts + 1
            for name in viable:
                statuses[name].update(status="running", attempts=statuses[name]["attempts"] + 1)
            update["rework_requests"] = [
                {**item, "attempt": statuses[str(item.get("perspective"))]["attempts"]} for item in requests if item.get("perspective") in viable
            ]
            reason = f"품질 미달({summary}) → {', '.join(_title(n) for n in viable)} 관점 재수집 (품질 루프 {quality_attempts + 1}회차)"
            if exhausted:
                reason += f"; {', '.join(_title(n) for n in exhausted)} 관점은 재작업 상한 도달로 제외"
            return decide(viable, "recollect:" + ",".join(viable), reason)
        return decide(["save"], "save", f"알 수 없는 품질 평가 action({action}) → 현재 보고서로 저장")

    # ── fallback: an unexpected state (e.g. resumed mid-way); finish safely ──
    if not state.get("report"):
        return decide(["synthesis"], "synthesis", "이전 결정을 알 수 없어 종합부터 다시 진행")
    return decide(["save"], "save", "이전 결정을 알 수 없고 보고서가 있어 저장")


def build_graph(services: PipelineServices, *, output_dir: str | Path, report_name: str = "report", checkpointer: Any = None):
    """Compile the executable graph (see the module docstring for the topology)."""
    destination = Path(output_dir)
    builder = StateGraph(GraphState)

    def prepare(state: GraphState) -> dict[str, Any]:
        update = _call_service("prepare", services.prepare, state, {"sources", "evidence", "errors", "metrics"}, fatal=True, round_=0)
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

    def supervisor(state: GraphState) -> dict[str, Any]:
        return supervise(state, services.semantic_review)

    def route(state: GraphState) -> list[str | Send]:
        """Only ``state["next"]`` decides; perspectives are dispatched with ``Send``."""
        chosen: list[str | Send] = []
        for name in state.get("next") or []:
            if name in PERSPECTIVES:
                chosen.append(Send(name, send_payload(state, name)))
            elif name in ROUTES:
                chosen.append(name)
        return chosen or ["save"]

    def technical(state: GraphState) -> dict[str, Any]:
        update = _call_service("technical", services.technical, state, {"technical_findings", "evidence", "sources", "errors", "metrics"}, fatal=True, round_=0)
        if "technical-0" in (update.get("errors") or {}):
            return update
        technologies = state["run_config"]["technologies"]
        findings = update.get("technical_findings") or {}
        evidence = {**(state.get("evidence") or {}), **(update.get("evidence") or {})}
        absent = [
            technology
            for technology in technologies
            if technology not in findings or not any(item.get("technology") == technology for item in evidence.values())
        ]
        if absent:
            errors = dict(update.get("errors") or {})
            errors["technical-0-coverage"] = {
                "node": "technical",
                "reason": f"technical findings or evidence missing for: {', '.join(absent)}",
                "fatal": True,
                "recovered": False,
                "kind": "service",
            }
            update["errors"] = errors
        return update

    def perspective_node(name: str):
        def node(payload: Mapping[str, Any]) -> dict[str, Any]:
            return _call_service(name, getattr(services, name), payload, {f"{name}_analysis", *SHARED_UPDATE_KEYS})

        node.__name__ = name
        return node

    def synthesis_node(state: GraphState) -> dict[str, Any]:
        result = dict((services.synthesis_writer or synthesize)(state) or {})
        events = result.pop("metrics", []) or []
        return {"synthesis": result, "metrics": list(events)}

    def report_node(state: GraphState) -> dict[str, Any]:
        result = dict((services.report_writer or build_report)(state) or {})
        events = result.pop("metrics", []) or []
        return {"report": result, "metrics": list(events)}

    def quality_node(state: GraphState) -> dict[str, Any]:
        attempt = int(state.get("quality_attempts", 0) or 0)
        update = _call_service("quality", services.quality_evaluator or placeholder_quality, state, {"quality_result", "errors", "metrics"}, round_=attempt)
        raw = update.get("quality_result")
        try:
            if raw is None:
                raise ValueError("quality evaluator returned no quality_result")
            update["quality_result"] = QualityResult.model_validate(raw).model_dump()
        except Exception as exc:  # the verdict is unusable: record it and let the report go out with that limitation
            errors = dict(update.get("errors") or {})
            errors[f"quality-{attempt}-schema"] = {
                "node": "quality",
                "reason": f"quality_result invalid: {summarize_validation_error(exc)}"[:1000],
                "fatal": False,
                "recovered": False,
                "kind": "schema",
            }
            update["errors"] = errors
            fallback = placeholder_quality(state)["quality_result"]
            fallback.update(evaluator="fallback", fallback_reason=summarize_validation_error(exc))
            update["quality_result"] = fallback
        return update

    def save(state: GraphState) -> dict[str, Any]:
        return {"artifacts": save_outputs(state, destination, report_name=report_name)}

    builder.add_node("prepare", prepare)
    builder.add_node("supervisor", supervisor)
    builder.add_node("technical", technical)
    for name in PERSPECTIVES:
        builder.add_node(name, perspective_node(name))
    builder.add_node("synthesis", synthesis_node)
    builder.add_node("report", report_node)
    builder.add_node("quality", quality_node)
    builder.add_node("save", save)

    builder.add_edge(START, "prepare")
    builder.add_edge("prepare", "supervisor")
    builder.add_conditional_edges("supervisor", route, list(ROUTES))
    for name in ("technical", *PERSPECTIVES, "synthesis", "report", "quality"):
        builder.add_edge(name, "supervisor")
    builder.add_edge("save", END)
    return builder.compile(checkpointer=checkpointer)


def draw_mermaid(services: PipelineServices | None = None) -> str:
    """Mermaid source of the compiled graph (for the README architecture figure)."""
    if services is None:
        from .demo import create_services

        services = create_services()
    return build_graph(services, output_dir=".").get_graph().draw_mermaid()
