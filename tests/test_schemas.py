import pytest

from skala_rag.graph.schemas import RunConfig, is_valid_label, validate_update


def test_validate_update_drops_invalid_perspective_and_records_problem():
    clean, problems = validate_update(
        "market",
        {"market_analysis": {"perspective": "market", "technologies": {"KIVI": {"adoptionn": {"label": "미확인"}}}}},
    )
    assert "market_analysis" not in clean
    assert problems and "adoptionn" in problems[0]


def test_validate_update_rejects_perspective_name_mismatch():
    clean, problems = validate_update("market", {"market_analysis": {"perspective": "trl", "technologies": {}}})
    assert "market_analysis" not in clean and "perspective must be" in problems[0]


def test_validate_update_fills_ids_defaults_and_drops_bad_records():
    clean, problems = validate_update(
        "technical",
        {
            "sources": {"s1": {"title": "Paper"}},
            "evidence": {"e1": {"source_id": "s1", "technology": "KIVI"}, "e2": {"technology": "KIVI"}},
            "technical_findings": {"KIVI": {"principle": "p", "measurements": [{"metric": "m", "value": 2.6}]}},
            "metrics": {"retrieve_calls": 2},
        },
    )
    assert clean["sources"]["s1"]["source_id"] == "s1" and clean["sources"]["s1"]["source_type"] == "web"
    assert clean["evidence"]["e1"]["claim_type"] == "unverified" and "e2" not in clean["evidence"]
    assert clean["technical_findings"]["KIVI"]["measurements"][0]["value"] == 2.6
    assert clean["metrics"] == [{"node": "technical", "retrieve_calls": 2}]
    assert any("evidence[e2]" in problem for problem in problems)


def test_is_valid_label_accepts_unknown_labels_and_trl_ranges():
    assert is_valid_label("market", "adoption", "판단 유보")
    assert is_valid_label("domain", "memory", "보고 없음")
    assert is_valid_label("trl", "trl", "TRL 4에서 5") and is_valid_label("trl", "trl", "TRL 4-5")
    assert not is_valid_label("market", "adoption", "최고")
    assert not is_valid_label("trl", "trl", "TRL 10")


def test_run_config_requires_two_distinct_technologies_and_domain():
    with pytest.raises(ValueError, match="technologies"):
        RunConfig(mode="replay", technologies=["KIVI", "KIVI"], domain="d")
    with pytest.raises(ValueError, match="domain"):
        RunConfig(mode="replay", technologies=["KIVI", "InfiniGen"], domain=" ")
    config = RunConfig(mode="live", technologies=["KIVI", "InfiniGen"], domain="클라우드 LLM 서빙")
    assert config.budget.web_search_max == 20 and config.max_paper_pages == 200


def test_supervisor_constants_and_agent_names():
    from skala_rag.graph.schemas import (
        AGENTS,
        DECISION_LOG_LIMIT,
        MAX_QUALITY_LOOPS,
        MAX_REWORK_PER_AGENT,
        MAX_SUPERVISOR_STEPS,
        PERSPECTIVES,
        QUALITY_THRESHOLD,
    )

    assert AGENTS == ("technical", "market", "stakeholder", "domain", "trl") and AGENTS[1:] == PERSPECTIVES
    assert (MAX_REWORK_PER_AGENT, MAX_QUALITY_LOOPS, MAX_SUPERVISOR_STEPS) == (2, 2, 20)
    assert QUALITY_THRESHOLD == 4 and DECISION_LOG_LIMIT == 30


def test_agent_status_defaults_and_rejects_unknown_status():
    from skala_rag.graph.schemas import AgentStatus

    status = AgentStatus()
    assert status.model_dump() == {"status": "pending", "attempts": 0, "last_error": ""}
    assert AgentStatus(status="failed", attempts=2, last_error="RuntimeError: quota").status == "failed"
    with pytest.raises(ValueError):
        AgentStatus(status="retrying")
    with pytest.raises(ValueError):
        AgentStatus(attempts=-1)


def test_rework_request_shape():
    from skala_rag.graph.schemas import ReworkRequest

    request = ReworkRequest(
        perspective="market",
        technology="InfiniGen",
        field="adoption",
        reasons="unsupported_claim",
        review_reason="근거가 InfiniGen을 직접 지칭하지 않음",
        question="InfiniGen의 시장성 관점 '상용화와 채택 현황' 판정을 뒷받침하는 원문 근거는 무엇인가?",
    )
    assert request.reasons == ["unsupported_claim"] and request.attempt == 0  # 0 until the supervisor assigns the round
    assert ReworkRequest(perspective="market", technology="KIVI", field="adoption", attempt=2).attempt == 2
    with pytest.raises(ValueError):
        ReworkRequest(perspective="technical", technology="KIVI", field="adoption")
    with pytest.raises(ValueError):
        ReworkRequest(perspective="market", technology="KIVI", field="adoption", attempt=-1)


def test_decision_requires_step_and_decision():
    from skala_rag.graph.schemas import Decision

    assert Decision(step=3, decision="rework:market", reason="시장성 2개 항목 근거 부족 → 재작업 1회차").step == 3
    with pytest.raises(ValueError):
        Decision(step=0, decision="save")


def test_quality_item_score_is_the_lower_of_rule_and_llm():
    from skala_rag.graph.schemas import QualityItem

    assert QualityItem(rule_score=5, llm_score=4).score == 4
    assert QualityItem(rule_score=2, llm_score=3).score == 2
    assert QualityItem(rule_score=5).score == 5 and QualityItem(rule_score=5).llm_score is None
    assert QualityItem(score=3, rule_score=5, llm_score=4).score == 3  # explicit value is kept
    with pytest.raises(ValueError):
        QualityItem(rule_score=6)


def test_quality_result_validates_items_instructions_and_rework_requests():
    from skala_rag.graph.schemas import QualityResult

    payload = {
        "passed": False,
        "threshold": 4,
        "items": {
            "groundedness": {"score": 4, "rule_score": 5, "llm_score": 4, "reasons": []},
            "neutrality": {"score": 2, "rule_score": 2, "llm_score": 3, "reasons": ["5장 2문단에 비교 우위 표현"]},
            "bias": {"rule_score": 4, "llm_score": None, "reasons": []},
            "coverage": {"rule_score": 5, "reasons": []},
        },
        "action": "recollect",
        "instructions": [{"item": "neutrality", "section": "5. 시사점", "problem": "우열 판정으로 읽힘", "quote": "…", "fix": "비교 우위 표현 삭제"}],
        "rework_requests": [{"perspective": "domain", "technology": "KIVI", "field": "latency", "reasons": ["not_found_label"]}],
    }
    result = QualityResult.model_validate(payload)
    assert result.items["bias"].score == 4 and result.items["coverage"].score == 5
    assert result.instructions[0].item == "neutrality" and result.rework_requests[0].attempt == 0
    assert QualityResult(passed=True, action="pass").threshold == 4
    with pytest.raises(ValueError):
        QualityResult(passed=False, action="retry")
    with pytest.raises(ValueError):
        QualityResult.model_validate({**payload, "rework_requests": [{"perspective": "market"}]})


def test_validate_update_clips_long_evidence_quotes():
    from skala_rag.graph.schemas import EVIDENCE_QUOTE_LIMIT

    long_quote = "가" * (EVIDENCE_QUOTE_LIMIT + 500)
    clean, problems = validate_update("market", {"evidence": {"e1": {"source_id": "s1", "technology": "KIVI", "quote": long_quote, "claim_type": "reported_fact"}}})
    assert not problems and len(clean["evidence"]["e1"]["quote"]) == EVIDENCE_QUOTE_LIMIT
    short = validate_update("market", {"evidence": {"e1": {"source_id": "s1", "technology": "KIVI", "quote": "short"}}})[0]
    assert short["evidence"]["e1"]["quote"] == "short"
