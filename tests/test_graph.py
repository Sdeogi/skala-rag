from __future__ import annotations

from copy import deepcopy
from threading import Barrier

import pytest

from skala_rag.graph.state import merge_by_id
from skala_rag.graph.evidence_check import check_evidence
from skala_rag.graph.workflow import PipelineServices, build_graph, initial_state


TECHS = ("KIVI", "InfiniGen")
FIELDS = {
    "market": ("market_size", "adoption", "ecosystem"),
    "stakeholder": ("competitor_view", "adopter_view", "investor_view"),
    "domain": ("memory", "quality", "latency", "throughput", "integration"),
    "trl": ("trl",),
}
LABELS = {
    "market": ("직접 자료 있음", "상용 서비스 적용 확인", "활발"),
    "stakeholder": ("지지",) * 3,
    "domain": ("적용 가능 보고",) * 4 + ("낮음 보고",),
    "trl": ("TRL 4",),
}


def perspective(name, missing=False):
    return {
        "perspective": name,
        "technologies": {
            tech: {
                field: {
                    "label": label,
                    "reason": f"{tech} {field} 근거에 따른 설명",
                    "evidence_ids": [] if missing and field == FIELDS[name][0] else [f"{tech}-1"],
                    "conditions": "공개 실험 조건",
                }
                for field, label in zip(FIELDS[name], LABELS[name])
            }
            for tech in TECHS
        },
        "status": "insufficient_evidence" if missing else "complete",
    }


def services(missing=False, retry=None):
    def technical(state):
        return {
            "technical_findings": {tech: {"principle": "fixture"} for tech in TECHS},
            "evidence": {
                f"{tech}-1": {
                    "source_id": f"{tech}-paper", "technology": tech,
                    "claim": "실험 결과", "quote": "fixture quote", "location": "p.1",
                }
                for tech in TECHS
            },
        }

    return PipelineServices(
        prepare=lambda state: {
            "sources": {f"{tech}-paper": {"title": f"{tech} paper", "url": "https://example.org"} for tech in TECHS}
        },
        technical=technical,
        market=lambda state: {"market_analysis": perspective("market", missing)},
        stakeholder=lambda state: {"stakeholder_analysis": perspective("stakeholder")},
        domain=lambda state: {"domain_analysis": perspective("domain")},
        trl=lambda state: {"trl_analysis": perspective("trl")},
        retry=retry or (lambda state: {}),
    )


def test_merge_by_id_rejects_changed_duplicate():
    assert merge_by_id({"x": {"v": 1}}, {"x": {"v": 1}, "y": {"v": 2}}) == {"x": {"v": 1}, "y": {"v": 2}}
    with pytest.raises(ValueError, match="x"):
        merge_by_id({"x": {"v": 1}}, {"x": {"v": 2}})


def test_graph_joins_four_perspectives_before_check_and_finishes(tmp_path):
    graph = build_graph(services(), output_dir=tmp_path)
    result = graph.invoke(initial_state(mode="replay"), config={"recursion_limit": 50})
    assert all(result[f"{name}_analysis"] for name in FIELDS)
    assert result["retry_count"] == 0
    assert result["evidence_check"]["passed"]
    assert result["synthesis"] is not None
    assert result["report"] is not None
    assert set(result["artifacts"]) == {"markdown", "html", "pdf", "sources", "manifest"}


def test_retry_only_receives_missing_questions_and_stops_after_two(tmp_path):
    seen = []

    def retry(state):
        seen.append(deepcopy(state["missing_questions"]))
        assert all(q["perspective"] == "market" for q in seen[-1])
        return {}

    result = build_graph(services(missing=True, retry=retry), output_dir=tmp_path).invoke(initial_state(mode="replay"), config={"recursion_limit": 50})
    assert len(seen) == 2
    assert result["retry_count"] == 2
    assert not result["evidence_check"]["passed"]
    assert "미확인" in result["report"]["markdown"]


def test_technical_without_one_technology_evidence_stops_early(tmp_path):
    base = services()
    original = base.technical

    def technical(state):
        value = original(state)
        value["evidence"].pop("InfiniGen-1")
        return value

    base.technical = technical
    result = build_graph(base, output_dir=tmp_path).invoke(initial_state(mode="replay"), config={"recursion_limit": 50})
    assert result["errors"]
    assert not result.get("market_analysis")
    assert not result.get("report")


def test_invalid_mode_rejected():
    with pytest.raises(ValueError, match="mode"):
        initial_state(mode="offline")


def test_retry_can_repair_only_failing_market_items(tmp_path):
    def repair(state):
        market = deepcopy(state["market_analysis"])
        for technology in TECHS:
            market["technologies"][technology]["market_size"]["evidence_ids"] = [f"{technology}-1"]
        market["status"] = "complete"
        return {"market_analysis": market}

    result = build_graph(services(missing=True, retry=repair), output_dir=tmp_path).invoke(initial_state(mode="replay"), config={"recursion_limit": 50})
    assert result["retry_count"] == 1
    assert result["evidence_check"]["passed"]


def test_evidence_check_rejects_unknown_source_unverified_claim_and_bad_label():
    state = initial_state(mode="replay")
    state["market_analysis"] = perspective("market")
    state["market_analysis"]["technologies"]["KIVI"]["adoption"]["label"] = "최고"
    state["evidence"] = {"KIVI-1": {"technology": "KIVI", "source_id": "absent", "claim_type": "unverified"}}
    result = check_evidence(state)
    item = next(item for item in result["evidence_check"]["items"] if item["perspective"] == "market" and item["technology"] == "KIVI" and item["field"] == "adoption")
    assert "invalid_label" in item["reasons"]
    assert "unknown_source" in item["reasons"]


def test_four_perspectives_execute_in_parallel_and_join(tmp_path):
    gate = Barrier(4, timeout=5)
    base = services()
    for name in FIELDS:
        original = getattr(base, name)

        def concurrent(state, original=original):
            gate.wait()
            return original(state)

        setattr(base, name, concurrent)
    result = build_graph(base, output_dir=tmp_path).invoke(initial_state(mode="replay"), config={"recursion_limit": 50})
    assert not result["errors"]
    assert result["evidence_check"]["passed"]


def test_failed_semantic_review_prevents_synthesis_of_that_judgment(tmp_path):
    base = services()
    base.semantic_review = lambda perspective, technology, field, judgment, evidence: not (
        perspective == "market" and field == "adoption"
    )
    result = build_graph(base, output_dir=tmp_path).invoke(initial_state(mode="replay"), config={"recursion_limit": 50})
    assert result["retry_count"] == 2
    assert result["evidence_check"]["semantic_review_enabled"]
    assert any("unsupported_claim" in item["reasons"] for item in result["evidence_check"]["items"])
    assert not any(pair["first"]["field"] == "adoption" or pair["second"]["field"] == "adoption" for pair in result["synthesis"]["conflicts"] + result["synthesis"]["agreements"])


def test_trl_range_label_from_design_is_accepted():
    state = initial_state(mode="replay")
    state["sources"] = {"paper": {"title": "Paper"}}
    state["evidence"] = {"KIVI-1": {"source_id": "paper", "technology": "KIVI"}, "InfiniGen-1": {"source_id": "paper", "technology": "InfiniGen"}}
    state["trl_analysis"] = perspective("trl")
    state["trl_analysis"]["technologies"]["KIVI"]["trl"]["label"] = "TRL 4에서 5"
    item = next(item for item in check_evidence(state)["evidence_check"]["items"] if item["perspective"] == "trl" and item["technology"] == "KIVI")
    assert item["passed"]
