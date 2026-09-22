from __future__ import annotations

import json
from copy import deepcopy
from threading import Barrier

import pytest
from conftest import FIELDS, TECHS, make_services, perspective, sample_sources

from skala_rag.graph.workflow import build_graph, draw_mermaid, initial_state

CONFIG = {"recursion_limit": 50}


def run(services, tmp_path, **kwargs):
    return build_graph(services, output_dir=tmp_path, **kwargs).invoke(initial_state(mode="replay"), config=CONFIG)


def manifest(tmp_path):
    return json.loads((tmp_path / "run_manifest.json").read_text(encoding="utf-8"))


def test_graph_joins_four_perspectives_before_check_and_finishes(tmp_path):
    result = run(make_services(), tmp_path)
    assert all(result[f"{name}_analysis"] for name in FIELDS)
    assert result["retry_count"] == 0
    assert result["evidence_check"]["passed"]
    assert result["synthesis"] and result["report"]
    assert set(result["artifacts"]) == {"markdown", "html", "pdf", "sources", "manifest"}
    assert manifest(tmp_path)["status"] == "complete"


def test_legacy_retry_service_receives_missing_questions_and_stops_after_two(tmp_path):
    seen = []

    def retry(state):
        seen.append(deepcopy(state["missing_questions"]))
        assert all(q["perspective"] == "market" for q in seen[-1])
        return {}

    result = run(make_services(missing=True, retry=retry), tmp_path)
    assert len(seen) == 2 and result["retry_count"] == 2
    assert not result["evidence_check"]["passed"]
    assert "미확인" in result["report"]["markdown"]


def test_default_repair_reinvokes_only_failing_perspective_with_its_questions(tmp_path):
    calls = {"market": [], "stakeholder": []}
    services = make_services(missing=True)
    original_market, original_stakeholder = services.market, services.stakeholder

    def market(state):
        calls["market"].append((state.get("retry_mode", False), deepcopy(state.get("missing_questions", []))))
        return original_market(state)

    def stakeholder(state):
        calls["stakeholder"].append(state.get("retry_mode", False))
        return original_stakeholder(state)

    services.market, services.stakeholder = market, stakeholder
    result = run(services, tmp_path)
    assert result["retry_count"] == 2
    assert [mode for mode, _ in calls["market"]] == [False, True, True]
    assert all(q["perspective"] == "market" and q["reasons"] == ["missing_evidence"] for _, questions in calls["market"][1:] for q in questions)
    assert calls["stakeholder"] == [False]


def test_repair_can_fix_market_items_in_one_round(tmp_path):
    services = make_services(missing=True)

    def market(state):
        if state.get("retry_mode"):
            return {"market_analysis": perspective("market")}
        return {"market_analysis": perspective("market", missing=True)}

    services.market = market
    result = run(services, tmp_path)
    assert result["retry_count"] == 1 and result["evidence_check"]["passed"]


def test_technical_without_one_technology_evidence_stops_early(tmp_path):
    services = make_services()
    original = services.technical

    def technical(state):
        value = original(state)
        value["evidence"].pop("InfiniGen-1")
        return value

    services.technical = technical
    result = run(services, tmp_path)
    assert any(item["fatal"] for item in result["errors"].values())
    assert not result.get("market_analysis") and not result.get("report")
    assert manifest(tmp_path)["status"] == "failed"


def test_invalid_mode_rejected():
    with pytest.raises(ValueError, match="mode"):
        initial_state(mode="offline")


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


def test_failed_semantic_review_prevents_synthesis_of_that_judgment(tmp_path):
    services = make_services()
    services.semantic_review = lambda perspective, technology, field, judgment, evidence: not (perspective == "market" and field == "adoption")
    result = run(services, tmp_path)
    assert result["retry_count"] == 2
    assert result["evidence_check"]["semantic_review_enabled"]
    assert any("unsupported_claim" in item["reasons"] for item in result["evidence_check"]["items"])
    pairs = result["synthesis"]["conflicts"] + result["synthesis"]["agreements"]
    assert not any(pair["first"]["field"] == "adoption" or pair["second"]["field"] == "adoption" for pair in pairs)


def test_perspective_service_exception_records_error_and_run_continues(tmp_path):
    services = make_services()

    def boom(state):
        raise RuntimeError("Tavily quota exceeded")

    services.stakeholder = boom
    result = run(services, tmp_path)
    assert result["errors"]["stakeholder-0"]["reason"].startswith("RuntimeError")
    assert result["report"] and "실행 오류" in result["report"]["markdown"]
    assert manifest(tmp_path)["status"] == "incomplete"


def test_prepare_fatal_error_writes_manifest_without_report(tmp_path):
    services = make_services()

    def prepare(state):
        raise ValueError("PDF parsing failed")

    services.prepare = prepare
    result = run(services, tmp_path)
    assert result["errors"]["prepare-0"]["fatal"] and "report" not in result
    assert set(result["artifacts"]) == {"sources", "manifest"}


def test_paper_page_limit_is_fatal(tmp_path):
    services = make_services()
    sources = sample_sources()
    sources["KIVI-paper"]["pages"], sources["InfiniGen-paper"]["pages"] = 150, 80
    services.prepare = lambda state: {"sources": sources}
    result = run(services, tmp_path)
    assert "exceed the limit" in result["errors"]["prepare-0-pages"]["reason"]
    assert not result.get("technical_findings")


def test_schema_violation_is_recorded_and_repair_is_requested(tmp_path):
    services = make_services()
    broken = perspective("market")
    broken["technologies"]["KIVI"]["adoptionn"] = broken["technologies"]["KIVI"].pop("adoption")
    services.market = lambda state: {"market_analysis": broken, "unexpected_key": 1}
    result = run(services, tmp_path)
    assert result["errors"]["market-0-schema"]["kind"] == "schema"
    assert "adoptionn" in result["errors"]["market-0-schema"]["reason"]
    assert result["retry_count"] == 2 and result["report"]


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
    assert metrics["totals"]["web_search_calls"] == 9  # initial call + two repairs
    assert metrics["by_node"]["retry"]["repair_rounds"] == 2
    assert metrics["totals"]["elapsed_seconds"] >= 0


def test_mermaid_shows_fan_out_join_and_repair_loop():
    mermaid = draw_mermaid()
    assert "fan_out" not in mermaid
    for line in ("technical -.-> market;", "trl --> evidence_check;", "repair --> evidence_check;", "retry -.-> repair;", "evidence_check -.-> synthesis;"):
        assert line in mermaid
