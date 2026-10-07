from __future__ import annotations

import json
from copy import deepcopy
from threading import Barrier

import pytest
from conftest import FIELDS, TECHS, make_services, perspective, sample_sources

from skala_rag.graph import workflow
from skala_rag.graph.schemas import DECISION_LOG_LIMIT, MAX_QUALITY_LOOPS, MAX_REWORK_PER_AGENT, MAX_SUPERVISOR_STEPS, PERSPECTIVES
from skala_rag.graph.workflow import build_graph, draw_mermaid, initial_state

CONFIG = {"recursion_limit": 50}
SUB_NODES = ("technical", *PERSPECTIVES, "synthesis", "report", "quality")


def run(services, tmp_path, **kwargs):
    return build_graph(services, output_dir=tmp_path, **kwargs).invoke(initial_state(mode="replay"), config=CONFIG)


def manifest(tmp_path):
    return json.loads((tmp_path / "run_manifest.json").read_text(encoding="utf-8"))


def decisions(result):
    return [entry["decision"] for entry in result["decision_log"]]


def quality_evaluator(*verdicts):
    """Fake quality node: returns the given actions in order, then passes."""
    queue = list(verdicts)
    calls = []

    def evaluate(state):
        calls.append(deepcopy(state.get("report")))
        verdict = queue.pop(0) if queue else {"action": "pass"}
        action = verdict.get("action", "pass")
        failing = verdict.get("failing", ["neutrality"] if action != "pass" else [])
        items = {name: {"score": 2 if name in failing else 5, "rule_score": 2 if name in failing else 5, "llm_score": None, "reasons": []} for name in ("groundedness", "neutrality", "bias", "coverage")}
        return {
            "quality_result": {
                "passed": action == "pass",
                "threshold": 4,
                "items": items,
                "action": action,
                "instructions": [{"item": name, "section": "5. 시사점", "problem": "fixture", "fix": "fixture"} for name in failing],
                "rework_requests": verdict.get("rework_requests", []),
            }
        }

    evaluate.calls = calls
    return evaluate


def recollect(name, technology="KIVI"):
    field = FIELDS[name][0]
    return {"action": "recollect", "failing": ["coverage"], "rework_requests": [{"perspective": name, "technology": technology, "field": field, "reasons": ["not_found_label"], "question": "?"}]}


# ── topology ──


def test_every_sub_node_returns_only_to_supervisor(tmp_path):
    graph = build_graph(make_services(), output_dir=tmp_path).get_graph()
    targets = {}
    for edge in graph.edges:
        targets.setdefault(edge.source, set()).add(edge.target)
    for name in SUB_NODES:
        assert targets[name] == {"supervisor"}, name
    assert targets["prepare"] == {"supervisor"} and targets["save"] == {"__end__"}
    assert targets["supervisor"] == set(SUB_NODES) | {"save"}


def test_mermaid_shows_supervisor_hub_without_direct_sub_agent_edges():
    mermaid = draw_mermaid()
    assert "evidence_check" not in mermaid and "repair" not in mermaid and "retry" not in mermaid
    for line in ("prepare --> supervisor;", "supervisor -.-> market;", "market --> supervisor;", "supervisor -.-> quality;", "quality --> supervisor;", "supervisor -.-> save;"):
        assert line in mermaid
    assert "technical -.-> market" not in mermaid and "synthesis --> report" not in mermaid


# ── happy path ──


def test_supervisor_runs_technical_perspectives_synthesis_report_quality_then_saves(tmp_path):
    result = run(make_services(), tmp_path)
    assert decisions(result) == ["technical", "run:market,stakeholder,domain,trl", "synthesis", "report", "quality", "save"]
    assert result["step_count"] == 6 and result["next"] == ["save"]
    assert all(result[f"{name}_analysis"] for name in FIELDS)
    assert result["evidence_check"]["passed"]
    assert {name: entry["status"] for name, entry in result["agent_status"].items()} == dict.fromkeys(("technical", *PERSPECTIVES), "done")
    assert all(entry["attempts"] == 0 for entry in result["agent_status"].values())
    assert result["quality_result"]["action"] == "pass" and result["quality_result"]["evaluator"] == "placeholder"
    assert result["synthesis"] and result["report"]
    assert set(result["artifacts"]) == {"markdown", "html", "pdf", "sources", "manifest"}
    assert manifest(tmp_path)["status"] == "complete"
    assert all(set(entry) == {"step", "decision", "reason"} for entry in result["decision_log"])


def test_run_id_is_generated_and_kept(tmp_path):
    state = initial_state(mode="replay")
    assert len(state["run_id"]) == 32 and initial_state(mode="replay")["run_id"] != state["run_id"]
    assert initial_state(mode="replay", run_id="fixed")["run_id"] == "fixed"
    result = build_graph(make_services(), output_dir=tmp_path).invoke(state, config=CONFIG)
    assert result["run_id"] == state["run_id"]


def test_four_perspectives_execute_in_parallel_and_join(tmp_path):
    gate = Barrier(4, timeout=5)
    services = make_services()
    for name in FIELDS:
        original = getattr(services, name)

        def concurrent(state, original=original):
            gate.wait()
            return original(state)

        setattr(services, name, concurrent)
    result = run(services, tmp_path)
    assert not result["errors"] and result["evidence_check"]["passed"]


# ── Send payload ──


def test_perspective_receives_only_the_contract_payload(tmp_path):
    seen = []
    services = make_services()
    original = services.market

    def market(payload):
        seen.append(deepcopy(payload))
        return original(payload)

    services.market = market
    run(services, tmp_path)
    assert len(seen) == 1
    assert set(seen[0]) == {"run_config", "market_analysis", "rework_requests", "known_evidence_ids"}
    assert seen[0]["market_analysis"] is None and seen[0]["rework_requests"] == []
    assert seen[0]["known_evidence_ids"] == ["InfiniGen-1", "KIVI-1"]
    assert seen[0]["run_config"]["technologies"] == list(TECHS)


def test_control_fields_returned_by_a_sub_agent_are_dropped_and_recorded(tmp_path):
    services = make_services()
    services.market = lambda state: {"market_analysis": perspective("market"), "next": ["save"], "step_count": 99, "agent_status": {}}
    result = run(services, tmp_path)
    reason = result["errors"]["market-0-schema"]["reason"]
    assert result["errors"]["market-0-schema"]["kind"] == "schema"
    assert "agent_status" in reason and "next" in reason and "step_count" in reason
    assert decisions(result)[-1] == "save" and result["report"] and result["step_count"] == 6


# ── evidence sufficiency and rework ──


def test_only_insufficient_perspective_is_reworked_with_its_own_requests(tmp_path):
    calls = {"market": [], "stakeholder": []}
    services = make_services(missing=True)
    original_market, original_stakeholder = services.market, services.stakeholder

    def market(payload):
        calls["market"].append(deepcopy(payload))
        return original_market(payload)

    def stakeholder(payload):
        calls["stakeholder"].append(deepcopy(payload))
        return original_stakeholder(payload)

    services.market, services.stakeholder = market, stakeholder
    result = run(services, tmp_path)
    assert len(calls["market"]) == 1 + MAX_REWORK_PER_AGENT and len(calls["stakeholder"]) == 1
    assert decisions(result) == ["technical", "run:market,stakeholder,domain,trl", "rework:market", "rework:market", "synthesis", "report", "quality", "save"]
    for attempt, payload in enumerate(calls["market"][1:], start=1):
        requests = payload["rework_requests"]
        assert requests and all(r["perspective"] == "market" and r["attempt"] == attempt and r["reasons"] == ["missing_evidence"] for r in requests)
        assert {r["technology"] for r in requests} == set(TECHS) and all("시장성" in r["question"] for r in requests)
        assert payload["market_analysis"]["perspective"] == "market"
    assert result["agent_status"]["market"] == {"status": "insufficient", "attempts": 2, "last_error": ""}
    assert result["agent_status"]["stakeholder"]["status"] == "done"
    assert not result["evidence_check"]["passed"]
    synthesis_reason = next(entry["reason"] for entry in result["decision_log"] if entry["decision"] == "synthesis")
    assert "재작업 상한" in synthesis_reason and "시장성" in synthesis_reason
    assert "재작업 1회차" in result["decision_log"][2]["reason"]
    assert manifest(tmp_path)["status"] == "incomplete"


def test_rework_that_fills_evidence_moves_to_report_next_turn(tmp_path):
    services = make_services(missing=True)

    def market(payload):
        if payload["rework_requests"]:
            return {"market_analysis": perspective("market")}
        return {"market_analysis": perspective("market", missing=True)}

    services.market = market
    result = run(services, tmp_path)
    assert decisions(result) == ["technical", "run:market,stakeholder,domain,trl", "rework:market", "synthesis", "report", "quality", "save"]
    assert result["agent_status"]["market"] == {"status": "done", "attempts": 1, "last_error": ""}
    assert result["evidence_check"]["passed"] and result["rework_requests"] == []
    assert manifest(tmp_path)["status"] == "complete"


def test_failed_semantic_review_requests_rework_and_keeps_item_out_of_synthesis(tmp_path):
    services = make_services()
    services.semantic_review = lambda perspective, technology, field, judgment, evidence: not (perspective == "market" and field == "adoption")
    result = run(services, tmp_path)
    assert result["agent_status"]["market"]["attempts"] == MAX_REWORK_PER_AGENT
    assert result["evidence_check"]["semantic_review_enabled"]
    assert any("unsupported_claim" in item["reasons"] for item in result["evidence_check"]["items"])
    pairs = result["synthesis"]["conflicts"] + result["synthesis"]["agreements"]
    assert not any(pair["first"]["field"] == "adoption" or pair["second"]["field"] == "adoption" for pair in pairs)


def test_perspective_exception_is_recorded_as_failed_and_run_continues(tmp_path):
    services = make_services()
    calls = []

    def boom(payload):
        calls.append(payload["rework_requests"])
        raise RuntimeError("Tavily quota exceeded")

    services.stakeholder = boom
    result = run(services, tmp_path)
    assert len(calls) == 1 + MAX_REWORK_PER_AGENT
    assert result["errors"]["stakeholder-0"]["reason"].startswith("RuntimeError") and "stakeholder-2" in result["errors"]
    status = result["agent_status"]["stakeholder"]
    assert status["status"] == "failed" and status["attempts"] == 2 and status["last_error"].startswith("RuntimeError: Tavily")
    assert result["report"] and "실행 오류" in result["report"]["markdown"]
    assert manifest(tmp_path)["status"] == "incomplete"


def test_schema_violation_is_recorded_and_rework_is_requested(tmp_path):
    services = make_services()
    broken = perspective("market")
    broken["technologies"]["KIVI"]["adoptionn"] = broken["technologies"]["KIVI"].pop("adoption")
    services.market = lambda state: {"market_analysis": broken, "unexpected_key": 1}
    result = run(services, tmp_path)
    assert result["errors"]["market-0-schema"]["kind"] == "schema"
    assert "adoptionn" in result["errors"]["market-0-schema"]["reason"]
    assert result["agent_status"]["market"]["status"] == "insufficient" and result["agent_status"]["market"]["attempts"] == 2
    assert result["report"]


# ── quality loop ──


def test_quality_rewrite_report_loops_then_accepts_with_limits(tmp_path):
    services = make_services()
    reports = []
    services.report_writer = lambda state: (reports.append(deepcopy(state.get("quality_result"))), workflow.build_report(state))[1]
    services.quality_evaluator = quality_evaluator({"action": "rewrite_report"}, {"action": "rewrite_report"}, {"action": "rewrite_report"})
    result = run(services, tmp_path)
    assert decisions(result)[4:] == ["quality", "rewrite_report", "quality", "rewrite_report", "quality", "accept_with_limits", "save"]
    assert len(reports) == 2 + MAX_QUALITY_LOOPS and len(services.quality_evaluator.calls) == 1 + MAX_QUALITY_LOOPS
    assert reports[1]["action"] == "rewrite_report" and reports[1]["instructions"][0]["item"] == "neutrality"
    assert reports[-1]["action"] == "accept_with_limits"
    assert result["quality_attempts"] == MAX_QUALITY_LOOPS and result["quality_result"]["action"] == "accept_with_limits"
    assert "품질 루프 상한" in result["decision_log"][-2]["reason"]


def test_quality_recollect_reinvokes_only_the_named_perspective(tmp_path):
    calls = {name: [] for name in PERSPECTIVES}
    services = make_services()
    for name in PERSPECTIVES:
        original = getattr(services, name)

        def spy(payload, name=name, original=original):
            calls[name].append(deepcopy(payload["rework_requests"]))
            return original(payload)

        setattr(services, name, spy)
    services.quality_evaluator = quality_evaluator(recollect("domain"))
    result = run(services, tmp_path)
    assert decisions(result)[4:] == ["quality", "recollect:domain", "synthesis", "report", "quality", "save"]
    assert [len(calls[name]) for name in PERSPECTIVES] == [1, 1, 2, 1]
    assert calls["domain"][1] == [{"perspective": "domain", "technology": "KIVI", "field": "memory", "reasons": ["not_found_label"], "review_reason": "", "question": "?", "attempt": 1}]
    assert result["agent_status"]["domain"] == {"status": "done", "attempts": 1, "last_error": ""}
    assert result["quality_attempts"] == 1 and result["quality_result"]["action"] == "pass"


def test_quality_recollect_without_remaining_attempts_accepts_with_limits(tmp_path):
    services = make_services(missing=True)  # market exhausts its rework budget during the evidence phase
    services.quality_evaluator = quality_evaluator(recollect("market"))
    result = run(services, tmp_path)
    assert decisions(result)[-3:] == ["quality", "accept_with_limits", "save"]
    assert "재작업 횟수가 남아 있지 않음" in result["decision_log"][-2]["reason"]
    assert result["agent_status"]["market"]["attempts"] == MAX_REWORK_PER_AGENT and result["quality_attempts"] == 0
    assert result["quality_result"]["action"] == "accept_with_limits"


def test_invalid_quality_result_is_recorded_and_report_is_saved(tmp_path):
    services = make_services()
    services.quality_evaluator = lambda state: {"quality_result": {"passed": False, "action": "retry"}}
    result = run(services, tmp_path)
    assert result["errors"]["quality-0-schema"]["kind"] == "schema" and "action" in result["errors"]["quality-0-schema"]["reason"]
    assert result["quality_result"]["evaluator"] == "fallback" and decisions(result)[-1] == "save"


# ── termination ──


def test_longest_path_stays_within_the_decision_budget(tmp_path):
    """Worst case: 2 evidence reworks for one perspective, then two quality recollects that each trigger one more evidence rework, then a final rewrite that is turned into accept_with_limits."""
    services = make_services(missing=True)

    def flaky(name):
        def service(payload):
            requests = payload["rework_requests"]
            if requests and requests[0]["attempt"] == 1:
                return {f"{name}_analysis": perspective(name, missing=True)}
            return {f"{name}_analysis": perspective(name)}

        return service

    services.stakeholder, services.domain = flaky("stakeholder"), flaky("domain")
    services.quality_evaluator = quality_evaluator(recollect("stakeholder"), recollect("domain"), {"action": "rewrite_report"})
    result = run(services, tmp_path)
    assert decisions(result) == [
        "technical", "run:market,stakeholder,domain,trl", "rework:market", "rework:market", "synthesis", "report", "quality",
        "recollect:stakeholder", "rework:stakeholder", "synthesis", "report", "quality",
        "recollect:domain", "rework:domain", "synthesis", "report", "quality",
        "accept_with_limits", "save",
    ]
    assert result["step_count"] == 19 <= MAX_SUPERVISOR_STEPS
    assert not any(entry["decision"].startswith("step_limit") for entry in result["decision_log"])
    assert {name: entry["attempts"] for name, entry in result["agent_status"].items()} == {"technical": 0, "market": 2, "stakeholder": 2, "domain": 2, "trl": 0}


def test_step_limit_forces_a_report_and_terminates(tmp_path, monkeypatch):
    monkeypatch.setattr(workflow, "MAX_SUPERVISOR_STEPS", 3)
    services = make_services(missing=True)
    result = run(services, tmp_path)
    assert decisions(result) == ["technical", "run:market,stakeholder,domain,trl", "rework:market", "step_limit:report", "step_limit:save"]
    assert result["step_count"] == 5 and result["report"]
    assert "결정 횟수 상한" in result["decision_log"][3]["reason"]
    assert set(result["artifacts"]) == {"markdown", "html", "pdf", "sources", "manifest"}


def test_always_insufficient_services_still_terminate(tmp_path, monkeypatch):
    monkeypatch.setattr(workflow, "MAX_REWORK_PER_AGENT", 10**6)
    monkeypatch.setattr(workflow, "MAX_QUALITY_LOOPS", 10**6)
    services = make_services(missing=True)
    services.quality_evaluator = quality_evaluator(*[{"action": "rewrite_report"}] * 100)
    result = build_graph(services, output_dir=tmp_path).invoke(initial_state(mode="replay"), config={"recursion_limit": 200})
    assert result["step_count"] == MAX_SUPERVISOR_STEPS + 2
    assert decisions(result)[-2:] == ["step_limit:report", "step_limit:save"]
    assert decisions(result).count("rework:market") == MAX_SUPERVISOR_STEPS - 2
    assert result["artifacts"]["manifest"]


def test_decision_log_keeps_only_the_most_recent_entries(tmp_path, monkeypatch):
    monkeypatch.setattr(workflow, "DECISION_LOG_LIMIT", 4)
    result = run(make_services(missing=True), tmp_path)
    assert result["step_count"] == 8 and len(result["decision_log"]) == 4
    assert decisions(result) == ["synthesis", "report", "quality", "save"] and result["decision_log"][-1]["step"] == 8
    assert DECISION_LOG_LIMIT == 30


# ── fatal errors ──


def test_prepare_fatal_error_goes_straight_to_save(tmp_path):
    services = make_services()

    def prepare(state):
        raise ValueError("PDF parsing failed")

    services.prepare = prepare
    result = run(services, tmp_path)
    assert result["errors"]["prepare-0"]["fatal"] and "report" not in result
    assert decisions(result) == ["save"] and result["agent_status"]["technical"]["status"] == "pending"
    assert set(result["artifacts"]) == {"sources", "manifest"}


def test_technical_without_one_technology_evidence_stops_early(tmp_path):
    services = make_services()
    original = services.technical

    def technical(state):
        value = original(state)
        value["evidence"].pop("InfiniGen-1")
        return value

    services.technical = technical
    result = run(services, tmp_path)
    assert result["errors"]["technical-0-coverage"]["fatal"] and "InfiniGen" in result["errors"]["technical-0-coverage"]["reason"]
    assert decisions(result) == ["technical", "save"]
    assert not result.get("market_analysis") and not result.get("report")
    assert manifest(tmp_path)["status"] == "failed"


def test_technical_exception_is_fatal_and_marked_failed(tmp_path):
    services = make_services()

    def technical(state):
        raise RuntimeError("index missing")

    services.technical = technical
    result = run(services, tmp_path)
    assert decisions(result) == ["technical", "save"]
    assert result["agent_status"]["technical"] == {"status": "failed", "attempts": 0, "last_error": "RuntimeError: index missing"}


def test_paper_page_limit_is_fatal(tmp_path):
    services = make_services()
    sources = sample_sources()
    sources["KIVI-paper"]["pages"], sources["InfiniGen-paper"]["pages"] = 150, 80
    services.prepare = lambda state: {"sources": sources}
    result = run(services, tmp_path)
    assert "exceed the limit" in result["errors"]["prepare-0-pages"]["reason"]
    assert not result.get("technical_findings")


def test_invalid_mode_rejected():
    with pytest.raises(ValueError, match="mode"):
        initial_state(mode="offline")


# ── merging and metrics ──


def test_conflicting_source_ids_do_not_abort_the_run(tmp_path):
    services = make_services()
    original_market, original_domain = services.market, services.domain
    services.market = lambda state: {**original_market(state), "sources": {"shared": {"title": "A", "retrieved_at": "t1"}}}
    services.domain = lambda state: {**original_domain(state), "sources": {"shared": {"title": "B", "retrieved_at": "t2"}}}
    result = run(services, tmp_path)
    assert result["sources"]["shared"]["title"] in {"A", "B"}
    conflicts = manifest(tmp_path)["conflicts"]
    assert conflicts == [{"collection": "sources", "id": "shared", "variants": 1, "differing_fields": ["title"]}]
    assert "동일 ID 충돌" in result["report"]["markdown"]


def test_metrics_events_are_aggregated_in_manifest(tmp_path):
    services = make_services(missing=True)
    original_market = services.market
    services.market = lambda state: {**original_market(state), "metrics": {"web_search_calls": 3}}
    run(services, tmp_path)
    metrics = manifest(tmp_path)["metrics"]
    assert metrics["totals"]["web_search_calls"] == 9  # initial call + two reworks
    assert metrics["by_node"]["supervisor"]["decisions"] == 8
    assert metrics["totals"]["elapsed_seconds"] >= 0


# ── checkpoints and fixture services ──


def test_checkpointer_persists_every_supervisor_decision_and_resumes(tmp_path):
    from langgraph.checkpoint.memory import InMemorySaver

    saver = InMemorySaver()
    graph = build_graph(make_services(missing=True), output_dir=tmp_path, checkpointer=saver)
    state = initial_state(mode="replay")
    config = {**CONFIG, "configurable": {"thread_id": state["run_id"]}}
    first = graph.invoke(state, config=config, interrupt_after=["technical"])
    assert decisions(first) == ["technical"] and first["technical_findings"] and "market_analysis" not in first
    assert graph.get_state(config).values["step_count"] == 1
    resumed = graph.invoke(None, config=config)
    assert decisions(resumed) == ["technical", "run:market,stakeholder,domain,trl", "rework:market", "rework:market", "synthesis", "report", "quality", "save"]
    assert resumed["run_id"] == state["run_id"] and resumed["artifacts"]["manifest"]
    steps = [snapshot.values.get("step_count") for snapshot in graph.get_state_history(config) if snapshot.values.get("step_count") is not None]
    assert max(steps) == 8 and len(set(steps)) == 9  # one checkpoint per decision plus the initial state


def test_fixture_services_reemit_only_the_requested_items_on_rework():
    from skala_rag.graph.demo import create_services

    services = create_services()
    state = initial_state(mode="replay")
    first = services.market({"run_config": state["run_config"], "market_analysis": None, "rework_requests": [], "known_evidence_ids": []})
    judgments = first["market_analysis"]["technologies"]
    assert set(judgments) == set(TECHS) and first["metrics"]["rework_items"] == 0
    judgments["KIVI"]["adoption"]["label"] = "미확인"
    request = {"perspective": "market", "technology": "KIVI", "field": "adoption", "reasons": ["not_found_label"], "question": "?", "attempt": 1}
    second = services.market({"run_config": state["run_config"], "market_analysis": first["market_analysis"], "rework_requests": [request], "known_evidence_ids": ["sample-KIVI"]})
    assert second["market_analysis"]["technologies"]["KIVI"]["adoption"]["label"] == "연구 재현 수준"
    assert second["market_analysis"]["technologies"]["InfiniGen"] == judgments["InfiniGen"]
    assert second["metrics"] == {"web_search_calls": 2, "retrieve_calls": 0, "rework_items": 1, "known_evidence": 1}
