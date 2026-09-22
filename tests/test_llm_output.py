from conftest import FakeModel

from skala_rag.agents.llm_output import LLMReportAgent, LLMSynthesisAgent, numbers_in, trim_to_sentences


def sample_state():
    return {
        "run_config": {"technologies": ["KIVI"], "domain": "클라우드 LLM 서빙", "mode": "live"},
        "sources": {"s1": {"title": "Paper", "url": "https://example.org", "source_type": "paper", "author_or_org": "Liu", "published_at": "2024"}},
        "evidence": {"e1": {"technology": "KIVI", "source_id": "s1", "quote": "2비트 양자화 실험 조건", "location": "p.1", "claim_type": "reported_fact"}},
        "technical_findings": {"KIVI": {"principle": "KV 2비트 압축"}},
        "market_analysis": {"technologies": {"KIVI": {"adoption": {"label": "상용 서비스 적용 확인", "reason": "서비스 도입", "conditions": "공개 발표", "evidence_ids": ["e1"]}}}},
        "stakeholder_analysis": {"technologies": {"KIVI": {"adopter_view": {"label": "우려", "reason": "운영 부담", "conditions": "대규모 배포", "evidence_ids": ["e1"]}}}},
        "missing_questions": [],
        "errors": {},
    }


def test_llm_synthesis_writes_pair_texts_and_records_metrics():
    draft = {"pairs": [{"id": "C0", "keep": True, "reason": "도입 발표와 운영 우려가 공존한다 [e1].", "uncertainty": "대규모 배포 조건에서만 확인됐다 [e1]."}]}
    result = LLMSynthesisAgent(FakeModel(draft))(sample_state())
    assert len(result["conflicts"]) == 1 and result["conflicts"][0]["generation"] == "llm"
    assert result["conflicts"][0]["reason"].startswith("도입 발표와")
    assert result["generation_mode"] == "llm_assisted" and result["llm_review"]["accepted"] == 1
    assert result["metrics"][0]["node"] == "synthesis" and result["metrics"][0]["pairs_accepted"] == 1


def test_llm_synthesis_rejects_new_numbers_and_unknown_citations_per_pair():
    draft = {"pairs": [{"id": "C0", "reason": "2029년에 검증됐다 [zzz].", "uncertainty": "불명"}]}
    result = LLMSynthesisAgent(FakeModel(draft))(sample_state())
    pair = result["conflicts"][0]
    assert pair["generation"] == "deterministic" and "운영 부담" in pair["reason"]
    assert result["llm_review"]["rejected"][0]["id"] == "C0"
    assert "unknown_citation" in result["llm_review"]["rejected"][0]["reason"]


def test_llm_synthesis_can_drop_pairs_and_falls_back_on_model_failure():
    dropped = LLMSynthesisAgent(FakeModel({"pairs": [{"id": "C0", "keep": False}]}))(sample_state())
    assert dropped["conflicts"] == [] and dropped["llm_review"]["dropped"] == ["C0"]
    failed = LLMSynthesisAgent(FakeModel(None, fail=RuntimeError("rate limit")))(sample_state())
    assert failed["generation_mode"] == "deterministic_fallback"
    assert failed["fallback_reason"].startswith("RuntimeError")
    assert len(failed["conflicts"]) == 1 and failed["metrics"][0]["llm_failures"] == 1


def test_llm_report_accepts_grounded_summary_and_rejects_fabricated_citation():
    state = sample_state()
    state["synthesis"] = LLMSynthesisAgent(FakeModel({"pairs": [{"id": "C0", "reason": "r [e1]", "uncertainty": "u [e1]"}]}))(state)
    good = LLMReportAgent(FakeModel({"summary": "KIVI의 2비트 양자화 도입 발표와 운영 우려가 함께 확인된다 [e1]. TRL 판정은 공개 정보 기반 추정이다 [e1]."}))(state)
    assert good["markdown"].startswith("# SUMMARY\n\nKIVI의 2비트")
    assert good["generation_mode"] == "llm_assisted" and good["metrics"][0]["node"] == "report"
    bad = LLMReportAgent(FakeModel({"summary": "KIVI는 2029년에 입증되었다 [invented]."}))(state)
    assert "[invented]" not in bad["markdown"]
    assert bad["generation_mode"] == "deterministic_fallback" and "unknown evidence ID" in bad["fallback_reason"]
    ranked = LLMReportAgent(FakeModel({"summary": "KIVI가 더 우수하다 [e1]."}))(state)
    assert "ranking" in ranked["fallback_reason"]


def test_number_guard_treats_korean_suffixes_consistently():
    assert numbers_in("2비트 양자화") == {"2"}
    assert numbers_in("2 비트, 2-bit, v1.2, 3.5배") == {"2", "3.5"}  # digits glued to a word (v1.2) are excluded on both sides
    state = sample_state()
    state["synthesis"] = {"agreements": [], "conflicts": [], "limitations": []}
    summary = "KIVI는 2 비트 양자화를 적용한다 [e1]."
    assert LLMReportAgent(FakeModel({"summary": summary}))(state)["generation_mode"] == "llm_assisted"


def test_overlong_summary_is_trimmed_at_a_sentence_boundary():
    sentence = "KIVI는 2 비트 양자화를 적용한다 [e1]. "
    long_summary = sentence * 60  # far beyond the half-page limit
    state = sample_state()
    state["synthesis"] = {"agreements": [], "conflicts": [], "limitations": []}
    report = LLMReportAgent(FakeModel({"summary": long_summary}))(state)
    assert report["generation_mode"] == "llm_assisted" and report.get("summary_trimmed") is True
    text = report["sections"][0]["paragraphs"][0]
    assert len(text) <= 1200 and text.endswith("[e1].")
    assert trim_to_sentences("짧은 문장이다.", 100) == "짧은 문장이다."
