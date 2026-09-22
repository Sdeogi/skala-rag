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
