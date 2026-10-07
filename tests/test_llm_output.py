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
        "errors": {},
    }


def test_llm_synthesis_writes_pair_texts_and_records_metrics():
    draft = {"pairs": [{"id": "C0", "keep": True, "reason": "도입 발표와 운영 우려가 공존한다 [E1].", "uncertainty": "대규모 배포 조건에서만 확인됐다 [E1]."}]}
    class Recording(FakeModel):
        def invoke(self, messages):
            self.seen = messages
            return super().invoke(messages)

    model = Recording(draft)
    result = LLMSynthesisAgent(model)(sample_state())
    assert len(result["conflicts"]) == 1 and result["conflicts"][0]["generation"] == "llm"
    assert result["conflicts"][0]["reason"] == "도입 발표와 운영 우려가 공존한다 [e1]."  # alias mapped back to the evidence ID
    assert '"evidence_id": "E1"' in model.seen[-1].content and '"e1"' not in model.seen[-1].content
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
    state["synthesis"] = LLMSynthesisAgent(FakeModel({"pairs": [{"id": "C0", "reason": "r [E1]", "uncertainty": "u [E1]"}]}))(state)
    good = LLMReportAgent(FakeModel({"summary": "KIVI의 2비트 양자화 도입 발표와 운영 우려가 함께 확인된다 [1]. TRL 판정은 공개 정보 기반 추정이다 [1]."}))(state)
    assert good["markdown"].startswith("# SUMMARY\n\nKIVI의 2비트 양자화 도입 발표와 운영 우려가 함께 확인된다 [1].")
    assert good["generation_mode"] == "llm_assisted" and good["metrics"][0]["node"] == "report"
    assert good["citation_map"] == {"1": "e1"} and "[e1]" not in good["markdown"]
    bad = LLMReportAgent(FakeModel({"summary": "KIVI는 2029년에 입증되었다 [9]."}))(state)
    assert "2029" not in bad["markdown"]
    assert bad["generation_mode"] == "deterministic_fallback" and "unknown evidence number" in bad["fallback_reason"]
    raw_id = LLMReportAgent(FakeModel({"summary": "KIVI의 도입 발표가 확인된다 [e1]."}))(state)  # raw IDs are not valid citations any more
    assert raw_id["generation_mode"] == "deterministic_fallback"
    ranked = LLMReportAgent(FakeModel({"summary": "KIVI가 더 우수하다 [1]."}))(state)
    assert "ranking" in ranked["fallback_reason"]


def test_llm_insights_replace_chapter_five_and_fall_back_independently_of_the_summary():
    state = sample_state()
    state["synthesis"] = {"agreements": [], "conflicts": [], "limitations": []}
    summary = "KIVI의 도입 발표와 운영 우려가 함께 확인된다 [1]."
    insights = ["KIVI는 도입 발표와 운영 우려가 엇갈리며 대규모 배포 조건에서만 확인됐다 [1].", "적용 전에 운영 부담을 다시 확인해야 한다 [1]."]
    good = LLMReportAgent(FakeModel({"summary": summary, "insights": insights}))(state)
    chapter = next(section for section in good["sections"] if section["heading"] == "5. 시사점")["paragraphs"]
    assert chapter[1:] == shown_all(insights) and chapter[0].startswith("근거가 확인된 판정이 적어 관점 간 상충·일치 쌍은 구성되지 않았다.")
    assert good["generation_mode"] == "llm_assisted" and good["llm_sections"] == {"summary": True, "insights": True, "overview": False}

    ranked = LLMReportAgent(FakeModel({"summary": summary, "insights": ["KIVI가 더 우수하다 [1].", "둘째 문단 [1]."]}))(state)
    assert ranked["generation_mode"] == "llm_assisted" and ranked["llm_sections"] == {"summary": True, "insights": False, "overview": False}
    assert "ranking" in ranked["insights_fallback_reason"] and "더 우수" not in ranked["markdown"]
    assert ranked["markdown"].startswith("# SUMMARY\n\nKIVI의 도입 발표와")

    partial = LLMReportAgent(FakeModel({"summary": "KIVI는 2029년에 입증되었다 [1].", "insights": insights}))(state)
    assert partial["generation_mode"] == "llm_partial" and partial["llm_sections"] == {"summary": False, "insights": True, "overview": False}
    assert "2029" not in partial["markdown"] and shown(insights[0]) in partial["markdown"]

    long = LLMReportAgent(FakeModel({"summary": summary, "insights": [insights[0]] * 2 + ["KIVI " + "가" * 1700 + " [1]."]}))(state)
    kept = next(section for section in long["sections"] if section["heading"] == "5. 시사점")["paragraphs"]
    assert len(kept) == 3  # the overlong trailing paragraph is dropped, the rest is kept


def test_number_guard_treats_korean_suffixes_consistently():
    assert numbers_in("2비트 양자화") == {"2"}
    assert numbers_in("2 비트, 2-bit, v1.2, 3.5배") == {"2", "3.5"}  # digits glued to a word (v1.2) are excluded on both sides
    state = sample_state()
    state["synthesis"] = {"agreements": [], "conflicts": [], "limitations": []}
    summary = "KIVI는 2 비트 양자화를 적용한다 [1]."
    assert LLMReportAgent(FakeModel({"summary": summary}))(state)["generation_mode"] == "llm_assisted"


def test_overlong_summary_is_trimmed_at_a_sentence_boundary():
    sentence = "KIVI는 2 비트 양자화를 적용한다 [1]. "
    long_summary = sentence * 60  # far beyond the half-page limit
    state = sample_state()
    state["synthesis"] = {"agreements": [], "conflicts": [], "limitations": []}
    report = LLMReportAgent(FakeModel({"summary": long_summary}))(state)
    assert report["generation_mode"] == "llm_assisted" and report.get("summary_trimmed") is True
    text = report["sections"][0]["paragraphs"][0]
    assert len(text) <= 1200 and text.endswith("[1].")
    assert trim_to_sentences("짧은 문장이다.", 100) == "짧은 문장이다."


SUMMARY_V1 = "KIVI의 도입 발표와 운영 우려가 함께 확인된다 [1]."
INSIGHTS_V1 = ["KIVI는 도입 발표가 있어 다른 선택지보다 유리하다 [1].", "적용 전에 운영 부담을 다시 확인해야 한다 [1]."]
INSIGHTS_V2 = ["KIVI는 도입 발표와 운영 우려가 엇갈리며 대규모 배포 조건에서만 확인됐다 [1].", "적용 전에 운영 부담을 다시 확인해야 한다 [1]."]


def reviewed_state(action, instructions):
    state = sample_state()
    state["synthesis"] = {"agreements": [], "conflicts": [], "limitations": []}
    state["report"] = LLMReportAgent(FakeModel({"summary": SUMMARY_V1, "insights": INSIGHTS_V1}))(state)
    assert state["report"]["llm_sections"] == {"summary": True, "insights": True, "overview": False}
    state["quality_result"] = {"passed": False, "threshold": 4, "items": {"neutrality": {"score": 2, "reasons": ["비교 우위 표현"]}}, "action": action, "instructions": instructions, "rework_requests": []}
    return state


def shown(text):
    """LLM text cites ``[1]`` before the closing period; the finished report keeps the number at the end of the clause."""
    return text


def shown_all(texts):
    return [shown(text) for text in texts]


def chapter(report, heading):
    return next(section for section in report["sections"] if section["heading"] == heading)["paragraphs"]


def test_llm_rewrites_only_the_instructed_section_and_keeps_the_other_llm_text():
    instruction = {"item": "neutrality", "section": "5. 시사점", "problem": "비교 우위 표현", "quote": "KIVI는 도입 발표가 있어 다른 선택지보다 유리하다 [1].", "fix": "조건을 나란히 서술"}
    state = reviewed_state("rewrite_report", [instruction])
    model = FakeModel({"summary": "KIVI 요약을 새로 썼다 [1].", "insights": INSIGHTS_V2})
    report = LLMReportAgent(model)(state)
    assert model.calls == 1
    assert chapter(report, "SUMMARY") == [shown(SUMMARY_V1)]  # not instructed: the previous LLM text stays
    assert chapter(report, "5. 시사점")[1:] == shown_all(INSIGHTS_V2) and "유리하다" not in report["markdown"]
    assert report["revision"]["number"] == 1 and report["revision"]["applied"][0]["result"] == "rewritten"
    assert report["llm_sections"] == {"summary": True, "insights": True, "overview": False} and report["generation_mode"] == "llm_assisted"


class SchemaModel(FakeModel):
    """Answers by requested schema, so the report call and the sentence-fix call get their own responses."""

    def __init__(self, responses):
        super().__init__(None)
        self.responses = responses
        self.schemas = []

    def with_structured_output(self, schema, **kwargs):
        self.schemas.append(schema.__name__)
        self.response = self.responses[schema.__name__]
        return self


TABLE_INSTRUCTION = {"item": "groundedness", "section": "4.1 시장성", "problem": "근거보다 넓게 일반화", "quote": "서비스 도입", "fix": "근거가 말하는 범위로 좁힌다"}


def market_reason(report):
    table = next(section for section in report["sections"] if section["heading"] == "4.1 시장성")["table"]
    return next(row for row in table["rows"] if row[0] == "KIVI" and row[1] == "상용화와 채택 현황")[3]


def test_flagged_sentence_in_a_rule_based_section_is_rewritten_not_deleted():
    state = reviewed_state("rewrite_report", [TABLE_INSTRUCTION])
    model = SchemaModel({"SentenceFixes": {"fixes": [{"index": 0, "replacement": "공개 발표에서 도입이 보고됐다"}]}, "ReportDraft": {"summary": "쓰이지 않는다 [1].", "insights": INSIGHTS_V2}})
    report = LLMReportAgent(model)(state)
    assert model.schemas == ["SentenceFixes"]  # SUMMARY and chapter 5 were not instructed: no report call
    assert market_reason(report) == "공개 발표에서 도입이 보고됐다"
    assert report["revision"]["applied"] == [{"item": "groundedness", "section": "4.1 시장성", "quote": "서비스 도입", "result": "replaced"}]
    assert chapter(report, "SUMMARY") == [shown(SUMMARY_V1)] and chapter(report, "5. 시사점")[1:] == shown_all(INSIGHTS_V1)
    assert report["metrics"][0]["purpose"] == "sentence_fix" and report["metrics"][0]["fixes_accepted"] == 1
    assert report["generation_mode"] == "llm_assisted"


def test_rejected_or_dropped_sentence_fix_falls_back_to_removal():
    for fix in (
        {"index": 0, "replacement": "KIVI가 더 우수하다"},  # ranking language
        {"index": 0, "replacement": "2029년에 도입이 보고됐다"},  # number absent from the sentence and its evidence
        {"index": 0, "replacement": "도입이 보고됐다 [1]"},  # the original sentence carried no citation
        {"index": 0, "replacement": "서비스 도입"},  # repeats the flagged sentence
        {"index": 0, "drop": True},
        {"index": 7, "replacement": "다른 항목"},  # not one of the requested items
    ):
        state = reviewed_state("rewrite_report", [TABLE_INSTRUCTION])
        report = LLMReportAgent(SchemaModel({"SentenceFixes": {"fixes": [fix]}}))(state)
        assert report["revision"]["applied"][0]["result"] == "removed", fix
        assert "서비스 도입" not in market_reason(report) and "더 우수" not in report["markdown"] and "2029" not in report["markdown"]
    failing = reviewed_state("rewrite_report", [TABLE_INSTRUCTION])
    report = LLMReportAgent(FakeModel(None, fail=RuntimeError("rate limit")))(failing)
    assert report["revision"]["applied"][0]["result"] == "removed" and report["metrics"][0]["llm_failures"] == 1


def test_whole_section_rewrite_and_sentence_fix_are_combined_in_one_revision():
    chapter_instruction = {"item": "neutrality", "section": "5. 시사점", "quote": "KIVI는 도입 발표가 있어 다른 선택지보다 유리하다", "fix": "조건을 나란히 서술"}
    state = reviewed_state("rewrite_report", [chapter_instruction, TABLE_INSTRUCTION])
    model = SchemaModel({"SentenceFixes": {"fixes": [{"index": 1, "replacement": "공개 발표에서 도입이 보고됐다"}]}, "ReportDraft": {"summary": "쓰이지 않는다 [1].", "insights": INSIGHTS_V2}})
    report = LLMReportAgent(model)(state)
    assert model.schemas == ["SentenceFixes", "ReportDraft"]
    assert [record["result"] for record in report["revision"]["applied"]] == ["rewritten", "replaced"]
    assert chapter(report, "5. 시사점")[1:] == shown_all(INSIGHTS_V2) and market_reason(report) == "공개 발표에서 도입이 보고됐다"
    assert chapter(report, "SUMMARY") == [shown(SUMMARY_V1)]


def test_accept_with_limits_keeps_llm_texts_without_calling_the_model():
    state = reviewed_state("accept_with_limits", [])
    model = FakeModel({"summary": "KIVI 요약을 새로 썼다 [1].", "insights": INSIGHTS_V2})
    report = LLMReportAgent(model)(state)
    assert model.calls == 0 and chapter(report, "SUMMARY") == [shown(SUMMARY_V1)] and chapter(report, "5. 시사점")[1:] == shown_all(INSIGHTS_V1)
    assert any(p.startswith("품질 평가 미달 항목") and "중립성 2점" in p for p in chapter(report, "6. 한계점"))


def test_recollect_regenerates_both_llm_sections_with_the_instructions():
    instruction = {"item": "neutrality", "section": "5. 시사점", "quote": "KIVI는 도입 발표가 있어 다른 선택지보다 유리하다", "fix": "삭제"}
    state = reviewed_state("recollect", [instruction])
    model = FakeModel({"summary": "KIVI 요약을 새로 썼다 [1].", "insights": INSIGHTS_V2})
    report = LLMReportAgent(model)(state)
    assert model.calls == 1 and chapter(report, "SUMMARY") == [shown("KIVI 요약을 새로 썼다 [1].")] and chapter(report, "5. 시사점")[1:] == shown_all(INSIGHTS_V2)


OVERVIEW_GOOD = {"technology": "KIVI", "paragraphs": ["KIVI는 KV 캐시를 2비트로 압축해 같은 메모리에 더 많은 문맥을 담는다 [1].", "KIVI는 공개 발표 기준으로 서비스 도입이 보고됐지만 대규모 배포의 운영 부담은 확인이 필요하다 [1]."]}


def overview_state():
    state = sample_state()
    state["synthesis"] = {"agreements": [], "conflicts": [], "limitations": []}
    state["technical_findings"] = {"KIVI": {"principle": "KV를 2비트로 압축한다", "limitations": ["긴 문맥은 검증되지 않았다"], "evidence_ids": ["e1"]}}
    return state


def test_llm_rewrites_the_technical_overview_and_keeps_it_through_a_later_revision():
    state = overview_state()
    first = LLMReportAgent(FakeModel({"summary": SUMMARY_V1, "insights": INSIGHTS_V1, "overview": [OVERVIEW_GOOD]}))(state)
    assert chapter(first, "3. 기술 개요") == OVERVIEW_GOOD["paragraphs"]
    assert first["llm_sections"]["overview"] is True and first["llm_texts"]["overview"]["KIVI"][0].endswith("[e1].")
    # a later revision that points at chapter 5 only leaves chapter 3 as the LLM wrote it
    state["report"] = first
    state["quality_result"] = {"passed": False, "threshold": 4, "items": {}, "action": "rewrite_report", "rework_requests": [], "instructions": [
        {"item": "neutrality", "section": "5. 시사점", "quote": "KIVI는 도입 발표가 있어 다른 선택지보다 유리하다", "fix": "삭제"}]}
    second = LLMReportAgent(FakeModel({"summary": "KIVI 요약을 새로 썼다 [1].", "insights": INSIGHTS_V2, "overview": [{"technology": "KIVI", "paragraphs": ["KIVI를 다르게 썼다 [1]."]}]}))(state)
    assert chapter(second, "3. 기술 개요") == OVERVIEW_GOOD["paragraphs"] and chapter(second, "5. 시사점")[1:] == INSIGHTS_V2
    assert second["llm_sections"] == {"summary": True, "insights": True, "overview": True}


def test_rejected_technical_overview_falls_back_to_the_rule_based_paragraphs():
    for paragraphs, reason in (
        (["KIVI가 더 우수하다 [1]."], "ranking"),
        ([r"KIVI는 \\(Q=XW\\)로 계산한다 [1]."], "formula"),
        (["KIVI는 2029년에 검증됐다 [1]."], "number"),
        (["KIVI 설명에 인용이 없다."], "citations"),
        (["압축 기법이다 [1]."], "mention"),
    ):
        report = LLMReportAgent(FakeModel({"summary": SUMMARY_V1, "insights": INSIGHTS_V1, "overview": [{"technology": "KIVI", "paragraphs": paragraphs}]}))(overview_state())
        assert reason in report["overview_fallback_reason"], (paragraphs, report["overview_fallback_reason"])
        assert chapter(report, "3. 기술 개요")[0].startswith("KIVI의 핵심 원리: KV를 2비트로 압축한다") and report["llm_sections"]["overview"] is False
        assert report["generation_mode"] == "llm_assisted"  # the summary and chapter 5 are still used


def test_rejected_rewrite_keeps_the_previous_llm_text_and_removes_only_the_flagged_sentence():
    flagged = "KIVI는 도입 발표가 있어 다른 선택지보다 유리하다"
    state = reviewed_state("rewrite_report", [{"item": "neutrality", "section": "5. 시사점", "quote": flagged, "fix": "삭제"}])
    # the rewrite repeats the flagged sentence, so it is rejected
    report = LLMReportAgent(FakeModel({"summary": SUMMARY_V1, "insights": INSIGHTS_V1}))(state)
    kept = chapter(report, "5. 시사점")[1:]
    assert kept == [INSIGHTS_V1[1]]  # the previous LLM chapter stays, minus the flagged sentence
    assert "repeats a sentence flagged" in report["insights_fallback_reason"] and report["llm_sections"]["insights"] is True
    assert report["revision"]["applied"][0]["result"] == "removed" and flagged not in report["markdown"]
