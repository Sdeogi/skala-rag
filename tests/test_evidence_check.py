from conftest import perspective

from skala_rag.graph.evidence_check import ReviewBudgetExceeded, check_evidence
from skala_rag.graph.workflow import initial_state


def _state():
    state = initial_state(mode="replay")
    state["sources"] = {"paper": {"title": "Paper"}}
    state["evidence"] = {
        "KIVI-1": {"source_id": "paper", "technology": "KIVI", "claim_type": "reported_fact"},
        "InfiniGen-1": {"source_id": "paper", "technology": "InfiniGen", "claim_type": "reported_fact"},
    }
    return state


def _item(result, perspective_name, technology, field):
    return next(i for i in result["evidence_check"]["items"] if (i["perspective"], i["technology"], i["field"]) == (perspective_name, technology, field))


def test_evidence_check_rejects_unknown_source_unverified_claim_and_bad_label():
    state = initial_state(mode="replay")
    state["market_analysis"] = perspective("market")
    state["market_analysis"]["technologies"]["KIVI"]["adoption"]["label"] = "최고"
    state["evidence"] = {"KIVI-1": {"technology": "KIVI", "source_id": "absent", "claim_type": "unverified"}}
    item = _item(check_evidence(state), "market", "KIVI", "adoption")
    assert "invalid_label" in item["reasons"] and "unknown_source" in item["reasons"]
    question = next(q for q in check_evidence(state)["missing_questions"] if q["field"] == "adoption" and q["technology"] == "KIVI")
    assert question["reasons"] == item["reasons"] and "시장성" in question["question"]


def test_trl_range_label_and_universal_unknown_labels_are_accepted():
    state = _state()
    state["trl_analysis"] = perspective("trl")
    state["trl_analysis"]["technologies"]["KIVI"]["trl"]["label"] = "TRL 4에서 5"
    state["market_analysis"] = perspective("market")
    state["market_analysis"]["technologies"]["KIVI"]["ecosystem"]["label"] = "판단 유보"
    result = check_evidence(state)
    assert _item(result, "trl", "KIVI", "trl")["passed"]
    assert "invalid_label" not in _item(result, "market", "KIVI", "ecosystem")["reasons"]


def test_reviewer_budget_exhaustion_and_errors_are_warnings_not_failures():
    state = _state()
    state["market_analysis"] = perspective("market")

    def exhausted(*args):
        raise ReviewBudgetExceeded("budget")

    result = check_evidence(state, exhausted)
    item = _item(result, "market", "KIVI", "adoption")
    assert item["passed"] and item["warnings"] == ["semantic_review_skipped"]
    assert result["evidence_check"]["semantic_review_skipped"] == 6

    def broken(*args):
        raise RuntimeError("api down")

    result = check_evidence(state, broken)
    assert _item(result, "market", "KIVI", "adoption")["warnings"] == ["semantic_review_error"]
    assert result["evidence_check"]["semantic_review_errors"] == 6


def test_reviewer_metrics_are_drained_into_the_update():
    state = _state()
    state["market_analysis"] = perspective("market")

    class Reviewer:
        calls = 0

        def __call__(self, *args):
            return True

        def drain_metrics(self):
            return [{"node": "evidence_check", "llm_calls": 1}]

    result = check_evidence(state, Reviewer())
    assert result["metrics"] == [{"node": "evidence_check", "llm_calls": 1}]
    assert result["evidence_check"]["semantic_review_calls"] == 0


def test_review_reason_is_recorded_for_unsupported_items():
    state = _state()
    state["market_analysis"] = perspective("market")

    class Reviewer:
        calls = 0
        last_reason = ""

        def __call__(self, perspective_name, technology, field, judgment, evidence):
            self.last_reason = "근거가 라벨의 의미와 무관"
            return field != "adoption"

    result = check_evidence(state, Reviewer())
    item = _item(result, "market", "KIVI", "adoption")
    assert item["reasons"] == ["unsupported_claim"] and item["review_reason"] == "근거가 라벨의 의미와 무관"
    question = next(q for q in result["missing_questions"] if q["field"] == "adoption" and q["technology"] == "KIVI")
    assert question["review_reason"] == "근거가 라벨의 의미와 무관"


def test_not_found_labels_skip_evidence_and_review_but_stay_open():
    state = _state()
    state["domain_analysis"] = perspective("domain")
    state["domain_analysis"]["technologies"]["KIVI"]["latency"]["label"] = "보고 없음"
    state["market_analysis"] = perspective("market")
    state["market_analysis"]["technologies"]["KIVI"]["adoption"].update(label="미확인", evidence_ids=[])
    reviewed = []

    def reviewer(perspective_name, technology, field, judgment, evidence):
        reviewed.append((perspective_name, technology, field))
        return True

    result = check_evidence(state, reviewer)
    assert _item(result, "domain", "KIVI", "latency")["reasons"] == ["not_found_label"]
    assert _item(result, "market", "KIVI", "adoption")["reasons"] == ["not_found_label"]
    assert ("domain", "KIVI", "latency") not in reviewed and ("market", "KIVI", "adoption") not in reviewed
    assert any(q["field"] == "latency" and q["reasons"] == ["not_found_label"] for q in result["missing_questions"])
