import pytest
from conftest import FakeModel

from skala_rag.agents.review import LLMSemanticReviewer
from skala_rag.graph.evidence_check import ReviewBudgetExceeded

JUDGMENT = {"label": "우려", "reason": "운영 부담", "conditions": "대규모 배포"}
EVIDENCE = [{"evidence_id": "e1", "quote": "operators report overhead", "claim_type": "reported_fact"}]


def test_reviewer_returns_verdict_caches_and_records_metrics():
    model = FakeModel({"supported": False, "reason": "근거가 판정과 무관"})
    reviewer = LLMSemanticReviewer(model)
    assert reviewer("stakeholder", "KIVI", "adopter_view", JUDGMENT, EVIDENCE) is False
    assert reviewer("stakeholder", "KIVI", "adopter_view", JUDGMENT, EVIDENCE) is False
    assert model.calls == 1 and reviewer.calls == 1
    events = reviewer.drain_metrics()
    assert len(events) == 1 and events[0]["node"] == "evidence_check" and events[0]["llm_calls"] == 1
    assert reviewer.drain_metrics() == []
    assert reviewer.verdicts[0]["reason"] == "근거가 판정과 무관"


def test_reviewer_respects_call_budget():
    reviewer = LLMSemanticReviewer(FakeModel({"supported": True}), max_calls=1)
    assert reviewer("market", "KIVI", "adoption", JUDGMENT, EVIDENCE) is True
    with pytest.raises(ReviewBudgetExceeded):
        reviewer("market", "InfiniGen", "adoption", JUDGMENT, EVIDENCE)
