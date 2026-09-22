from skala_rag.agents.llm_output import LLMSynthesisAgent, LLMReportAgent


class FakeModel:
    def __init__(self, response):
        self.response = response

    def with_structured_output(self, schema):
        return self

    def invoke(self, messages):
        return self.response


def sample_state():
    return {
        "run_config": {"technologies": ["KIVI"], "domain": "클라우드 LLM 서빙"},
        "sources": {"s1": {"title": "Paper", "url": "https://example.org"}},
        "evidence": {"e1": {"technology": "KIVI", "source_id": "s1", "quote": "실험 조건", "location": "p.1"}},
        "technical_findings": {"KIVI": {"principle": "KV 압축"}},
        "market_analysis": {"technologies": {"KIVI": {"adoption": {"label": "상용 서비스 적용 확인", "reason": "서비스 도입", "conditions": "공개 발표", "evidence_ids": ["e1"]}}}},
        "stakeholder_analysis": {"technologies": {"KIVI": {"adopter_view": {"label": "우려", "reason": "운영 부담", "conditions": "대규모 배포", "evidence_ids": ["e1"]}}}},
        "missing_questions": [], "errors": {},
    }


def test_llm_synthesis_orders_only_verified_candidate_pairs():
    agent = LLMSynthesisAgent(FakeModel({"agreement_order": [], "conflict_order": [0, 999]}))
    result = agent(sample_state())
    assert len(result["conflicts"]) == 1
    assert result["conflicts"][0]["first"]["evidence_ids"] == ["e1"]
    assert result["generation_mode"] == "llm_assisted"


def test_llm_report_accepts_grounded_summary_and_rejects_fabricated_citation():
    state = sample_state()
    state["synthesis"] = LLMSynthesisAgent(FakeModel({"agreement_order": [], "conflict_order": [0]}))(state)
    good = LLMReportAgent(FakeModel({"summary": "KIVI에 관한 공개 자료와 운영 우려가 함께 확인된다 [e1]."}))(state)
    assert good["markdown"].startswith("# SUMMARY\n\nKIVI에 관한")
    assert good["generation_mode"] == "llm_assisted"
    bad = LLMReportAgent(FakeModel({"summary": "2029년에 입증되었다 [invented]."}))(state)
    assert "[invented]" not in bad["markdown"]
    assert bad["generation_mode"] == "deterministic_fallback"
