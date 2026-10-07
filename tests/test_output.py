import os

from skala_rag.agents.korean import josa
from skala_rag.agents.report import compact_citations, LAYOUTS, MAX_PDF_PAGES, SUMMARY_LIMIT, _clip_sentences, _compose, build_report, format_reference, number_citations, pdf_page_count, save_outputs
from skala_rag.graph.schemas import LABELS
from skala_rag.agents.synthesis import synthesize
from skala_rag.graph.workflow import initial_state


def base_state():
    return {
        "run_config": {"technologies": ["KIVI", "InfiniGen"], "domain": "클라우드 LLM 서빙", "mode": "replay"},
        "technical_findings": {"KIVI": {"principle": "KV 압축"}},
        "sources": {"s1": {"title": "Paper", "url": "https://example.org/paper", "source_type": "paper", "author_or_org": "Liu, Z. et al.", "published_at": "2024-02-02", "venue": "ICML 2024"}},
        "evidence": {"e1": {"technology": "KIVI", "source_id": "s1", "location": "p.3", "quote": "evidence", "claim_type": "reported_fact"}},
        "market_analysis": {"technologies": {"KIVI": {"adoption": {"label": "연구 재현 수준", "reason": "공개 코드", "evidence_ids": ["e1", "bad"]}}}},
        "synthesis": {"agreements": [], "conflicts": [], "limitations": []},
        "missing_questions": [{"technology": "KIVI", "perspective": "market", "field": "adoption", "question": "채택 근거?", "reasons": ["unknown_evidence"]}],
        "errors": {},
    }


def test_synthesis_requires_real_evidence_and_preserves_conditions():
    state = {
        "run_config": {"technologies": ["KIVI"], "domain": "클라우드 LLM 서빙"},
        "evidence": {"e1": {"technology": "KIVI", "source_id": "s1"}, "e2": {"technology": "KIVI", "source_id": "s2"}},
        "market_analysis": {"technologies": {"KIVI": {"adoption": {"label": "상용 서비스 적용 확인", "reason": "채택 자료", "conditions": "2026년 공개 자료", "evidence_ids": ["e1"]}}}},
        "stakeholder_analysis": {"technologies": {"KIVI": {"adopter_view": {"label": "우려", "reason": "운영 부담", "conditions": "대규모 배포", "evidence_ids": ["e2"]}}}},
        "domain_analysis": {"technologies": {"KIVI": {"memory": {"label": "적용 가능 보고", "reason": "메모리 절감", "conditions": "배치 1", "evidence_ids": ["missing"]}}}},
    }
    result = synthesize(state)
    assert len(result["conflicts"]) == 1
    conflict = result["conflicts"][0]
    assert "대규모 배포" in conflict["uncertainty"] and "2026년 공개 자료" in conflict["uncertainty"]
    assert "채택 자료" in conflict["reason"] and "운영 부담" in conflict["reason"]
    assert not any("missing" in str(item) for item in result["agreements"] + result["conflicts"])
    assert "score" not in result


def test_report_follows_reference_outline_and_filters_unknown_ids():
    report = build_report(base_state())
    headings = [(section["heading"], section["level"]) for section in report["sections"]]
    assert headings[0] == ("SUMMARY", 1) and headings[-1] == ("REFERENCE", 1)
    level_one = [heading for heading, level in headings if level == 1]
    assert level_one == ["SUMMARY", "1. 분석 배경", "2. 기술 선정", "3. 기술 개요", "4. 관점별 평가", "5. 시사점", "6. 한계점", "부록. 근거 목록", "REFERENCE"]
    assert [heading for heading, level in headings if level == 2] == ["4.1 시장성", "4.2 이해관계자", "4.3 도메인 적용", "4.4 기술 성숙도"]
    markdown = report["markdown"]
    assert markdown.startswith("# SUMMARY") and "# REFERENCE" in markdown
    assert markdown.rstrip().endswith("https://example.org/paper")
    assert "[1]" in markdown and "[e1]" not in markdown and "[bad]" not in markdown and "미확인" in markdown
    assert report["citation_map"] == {"1": "e1"} and report["used_source_ids"] == ["s1"]
    assert "공개 정보에 근거한 추정" in markdown
    assert "InfiniGen을" in markdown and "KIVI와" in markdown  # particle handling
    assert "| 기술 | 항목 | 판정 |" in markdown


def test_reference_format_for_papers_and_web_pages():
    # the label is the reference number (R1, R2, ...) in a built report
    paper = format_reference("s1", {"title": "KIVI", "author_or_org": "Liu, Z. et al.", "published_at": "2024-02-02", "venue": "ICML 2024", "url": "https://arxiv.org/abs/2402.02750", "source_type": "paper"})
    assert paper == "[s1] Liu, Z. et al.(2024). KIVI. ICML 2024, https://arxiv.org/abs/2402.02750"
    web = format_reference("w1", {"title": "Blog", "author_or_org": "Google Research", "published_at": "2026-03-30", "venue": "Google Research Blog", "url": "https://example.org", "source_type": "web"})
    assert web == "[w1] Google Research(2026-03-30). Blog. Google Research Blog, https://example.org"
    assert format_reference("x", {}) == "[x] 저자 미상(발행일 미상). 제목 미상. (URL 미기재)"
    site = format_reference("s", {"title": "Kiwi Blog", "url": "https://www.kiwidata.com/blog/post", "source_type": "web"})
    assert site == "[s] kiwidata.com(발행일 미상). Kiwi Blog. https://www.kiwidata.com/blog/post"


def test_citations_are_numbered_by_first_appearance_and_only_cited_items_are_listed():
    state = base_state()
    state["sources"]["s2"] = {"title": "Blog", "url": "https://example.org/blog", "source_type": "web"}
    state["sources"]["s3"] = {"title": "Unused", "url": "https://example.org/unused", "source_type": "web"}
    state["evidence"]["e2"] = {"technology": "KIVI", "source_id": "s2", "location": "웹", "quote": "second", "claim_type": "reported_fact"}
    state["evidence"]["e3"] = {"technology": "KIVI", "source_id": "s3", "location": "웹", "quote": "retrieved but never cited", "claim_type": "reported_fact"}
    state["evidence_check"] = {"items": [{"perspective": "market", "technology": "KIVI", "field": "adoption", "passed": True}]}
    state["market_analysis"]["technologies"]["KIVI"]["adoption"]["evidence_ids"] = ["e2", "e1"]
    report = build_report(state)
    assert report["citation_map"] == {"1": "e2", "2": "e1"}  # order of first appearance (SUMMARY cites e2 first)
    assert report["used_source_ids"] == ["s2", "s1"]
    appendix = next(section for section in report["sections"] if section["heading"].startswith("부록"))["table"]["rows"]
    assert [row[:3] for row in appendix] == [["[1]", "KIVI", "[R1]"], ["[2]", "KIVI", "[R2]"]]
    references = report["sections"][-1]["paragraphs"]
    assert len(references) == 2 and references[0].startswith("[R1] ") and references[1].startswith("[R2] Liu, Z. et al.(2024)")
    assert "never cited" not in report["markdown"] and "unused" not in report["markdown"]
    market = next(section for section in report["sections"] if section["heading"] == "4.1 시장성")
    adoption = next(row for row in market["table"]["rows"] if row[0] == "KIVI" and row[1] == "상용화와 채택 현황")
    assert adoption[-1] == "[1] [2]"


def test_number_citations_leaves_non_evidence_brackets_untouched():
    sections = [{"heading": "h", "paragraphs": ["[상충] 본문 [e9] [REDACTED] [unknown]"], "table": {"columns": ["c"], "rows": [["[e1] [e9]"]]}, "level": 1}]
    numbered, citation_map = number_citations(sections, {"e1": {}, "e9": {}})
    assert numbered[0]["paragraphs"] == ["[상충] 본문 [1] [REDACTED] [unknown]"]
    assert numbered[0]["table"]["rows"] == [["[2] [1]"]] and citation_map == {"1": "e9", "2": "e1"}
    assert sections[0]["paragraphs"] == ["[상충] 본문 [e9] [REDACTED] [unknown]"]  # input is not mutated


def test_trl_stage_details_and_summary_limit():
    state = base_state()
    state["trl_analysis"] = {"technologies": {"KIVI": {"trl": {"label": "TRL 4", "reason": "공개 코드 재현", "evidence_ids": ["e1"], "highest_confirmed": "TRL 4", "stages": {"TRL 4": {"met": True, "evidence_ids": ["e1"]}, "TRL 5": {"met": False, "note": "PR 미확인"}}, "missing_evidence": ["vLLM 통합 PR"], "estimation_note": "공개 정보 기반"}}}}
    state["evidence"]["e1"]["quote"] = "q" * 1000
    report = build_report(state)
    trl_section = next(section for section in report["sections"] if section["heading"] == "4.4 기술 성숙도")
    assert any("TRL 5 미충족 (PR 미확인)" in p and "vLLM 통합 PR" in p for p in trl_section["paragraphs"])
    assert len(report["sections"][0]["paragraphs"][0]) <= SUMMARY_LIMIT
    appendix = next(section for section in report["sections"] if section["heading"].startswith("부록"))
    assert all(len(row[-1]) <= LAYOUTS[0].quote for row in appendix["table"]["rows"])


def test_report_redacts_secrets_and_private_contact_details():
    state = base_state()
    state["technical_findings"] = {"KIVI": {"note": "sk-test0123456789abcdefghijkl owner@example.org"}}
    markdown = build_report(state)["markdown"]
    assert "sk-test0123456789abcdefghijkl" not in markdown and "owner@example.org" not in markdown
    assert "[REDACTED]" in markdown


def test_limitations_group_repeated_errors_and_summary_falls_back_to_any_passed_field():
    state = base_state()
    state["errors"] = {f"market-KIVI-{i}": {"node": "market", "reason": "search 단계 실패 (FileNotFoundError)", "fatal": False, "kind": "service"} for i in range(5)}
    state["errors"]["trl-0"] = {"node": "trl", "reason": "other", "fatal": False, "kind": "service"}
    state["errors"]["stakeholder-a"] = {"node": "stakeholder", "reason": "FileNotFoundError: 캐시가 없습니다: search_aaa.json", "fatal": False, "kind": "service"}
    state["errors"]["stakeholder-b"] = {"node": "stakeholder", "reason": "FileNotFoundError: 캐시가 없습니다: search_bbb.json", "fatal": False, "kind": "service"}
    state["missing_questions"][0]["review_reason"] = "근거가 채택 사실을 말하지 않음"
    state["domain_analysis"] = {"technologies": {"KIVI": {"memory": {"label": "미확인", "reason": "없음", "evidence_ids": []}, "latency": {"label": "조건부 보고", "reason": "지연 보고", "evidence_ids": ["e1"]}}}}
    report = build_report(state)
    limits = next(section for section in report["sections"] if section["heading"] == "6. 한계점")["paragraphs"]
    assert any(p.endswith("search 단계 실패 (FileNotFoundError) ×5") for p in limits)
    assert sum("실행 오류" in p for p in limits) == 3
    assert any(p.startswith("실행 오류(service) stakeholder: FileNotFoundError") and p.endswith("×2") for p in limits)
    assert any("검토 LLM: 근거가 채택 사실을 말하지 않음" in p for p in limits)
    assert "도메인 적용 관점의 응답 지연 '조건부 보고'" in report["sections"][0]["paragraphs"][0]


LONG = "이 자료는 특정 모델과 문맥 길이, 배치 크기 조건에서 측정한 결과를 보고하며 해당 조건을 벗어난 환경에서의 효과는 별도로 확인되지 않았다고 밝힌다. "
PICK = {
    "market_size": "관련 시장 자료만 있음", "adoption": "연구 재현 수준", "ecosystem": "일부 있음", "competitor_view": "우려", "adopter_view": "지지", "investor_view": "중립",
    "memory": "적용 가능 보고", "quality": "조건부 보고", "latency": "조건부 보고", "throughput": "적용 가능 보고", "integration": "낮음 보고", "trl": "TRL 4",
}


def large_state(evidence_count=60, source_count=20):
    """A run about as large as a real one: every rubric item judged with long texts, many sources."""
    techs = ("KIVI", "InfiniGen")
    state = initial_state(mode="replay")
    sources = {
        f"src-{i:02d}": {"title": f"Source title number {i} about KV cache optimization for LLM serving", "url": f"https://example.org/articles/kv-cache-{i}", "source_type": "paper" if i < 2 else "web", "author_or_org": f"Org {i}", "published_at": "2025-03-01"}
        for i in range(source_count)
    }
    evidence = {
        f"web-evidence-{i:024d}": {"source_id": f"src-{i % source_count:02d}", "technology": techs[i % 2], "claim": LONG, "quote": LONG * 8, "location": f"p.{i % 16 + 1} Experiments", "claim_type": "reported_fact", "conditions": LONG}
        for i in range(evidence_count)
    }
    pools = {tech: [key for key, item in evidence.items() if item["technology"] == tech] for tech in techs}
    cursor = dict.fromkeys(techs, 0)

    def take(tech, count):
        picked = [pools[tech][(cursor[tech] + offset) % len(pools[tech])] for offset in range(count)]
        cursor[tech] += count
        return picked

    checks = []
    for perspective, fields in LABELS.items():
        judged = {}
        for tech in techs:
            judged[tech] = {}
            for field in fields:
                judgment = {"label": PICK[field], "reason": LONG * 2, "conditions": LONG, "evidence_ids": take(tech, 2)}
                if field == "trl":
                    stages = {
                        f"TRL {name}": {"met": order < 3, "verdict": "충족" if order < 3 else "미충족", "evidence_ids": take(tech, 1) if order < 3 else [], "note": LONG}
                        for order, name in enumerate(("1-2", "3", "4", "5", "6", "7-8", "9"))
                    }
                    judgment.update(highest_confirmed="TRL 4", missing_evidence=["[TRL 5] " + LONG], estimation_note="공개 정보 기반 추정", stages=stages)
                judged[tech][field] = judgment
                checks.append({"perspective": perspective, "technology": tech, "field": field, "passed": True, "reasons": []})
        state[f"{perspective}_analysis"] = {"perspective": perspective, "technologies": judged, "status": "complete"}
    state["technical_findings"] = {
        tech: {"principle": LONG * 2, "experiment_conditions": [LONG] * 3, "performance": [LONG] * 4, "limitations": [LONG] * 3, "evidence_ids": take(tech, 8), "measurements": [{"metric": "peak memory", "value": "2.6", "unit": "x", "baseline": "FP16", "model": "Llama-2-7B", "hardware": "A100", "location": "Table 3"}] * 3}
        for tech in techs
    }
    state.update(sources=sources, evidence=evidence, errors={}, evidence_check={"passed": True, "items": checks, "semantic_review_enabled": True})
    state["synthesis"] = synthesize(state)
    return state


def test_large_report_is_tightened_until_it_fits_the_page_limit():
    state = large_state()
    assert len(state["synthesis"]["conflicts"]) + len(state["synthesis"]["agreements"]) > 20
    roomy = _compose(state, None, LAYOUTS[0])
    assert pdf_page_count(roomy) > MAX_PDF_PAGES  # the roomiest budget is not enough for a run this large
    report = build_report(state)
    assert report["layout"]["fits"] and report["layout"]["pdf_pages"] <= MAX_PDF_PAGES and report["layout"]["level"] > 0
    assert pdf_page_count(report) == report["layout"]["pdf_pages"]
    insights = next(section for section in report["sections"] if section["heading"] == "5. 시사점")["paragraphs"]
    assert "생략했다" in insights[0]
    assert all(heading in report["markdown"] for heading in ("## 4.1 시장성", "## 4.2 이해관계자", "## 4.3 도메인 적용", "## 4.4 기술 성숙도"))


def test_chapter_five_covers_both_technologies_shared_patterns_and_open_points():
    state = large_state()
    state["domain_analysis"]["technologies"]["InfiniGen"]["memory"] = {"label": "보고 없음", "reason": "자료 없음", "evidence_ids": []}
    for item in state["evidence_check"]["items"]:
        if (item["perspective"], item["technology"], item["field"]) == ("domain", "InfiniGen", "memory"):
            item["passed"] = False
    state["synthesis"] = synthesize(state)
    paragraphs = next(section for section in _compose(state, None, LAYOUTS[0])["sections"] if section["heading"] == "5. 시사점")["paragraphs"]
    conflicts = [p for p in paragraphs if "관점 간 평가가 엇갈리는 지점" in p]
    assert [p.split("에서")[0] for p in conflicts] == ["KIVI", "InfiniGen"]  # neither technology fills the chapter alone
    assert all("(2) " in p and "(3) " not in p and p.count("성립 조건은 각각") == LAYOUTS[0].conflicts // 2 for p in conflicts)
    assert any(p.startswith("두 기술에 공통으로 나타나는 패턴") for p in paragraphs)
    closing = paragraphs[-1]
    assert closing.startswith("클라우드 LLM 서빙에 적용하기 전에 확인이 필요한 지점")
    assert "KIVI 응답 지연(조건부 보고" in closing and "InfiniGen 도메인 적용(메모리 절감)" in closing
    assert not any(p.startswith("[상충]") or p.startswith("[일치]") for p in paragraphs)


def test_technical_overview_is_one_paragraph_per_technology():
    state = base_state()
    state["technical_findings"] = {"KIVI": {"principle": "KV를 2비트로 양자화한다.", "experiment_conditions": ["Llama-2-7B.", "A100"], "performance": ["2.6x memory"], "limitations": ["긴 문맥 미검증"], "evidence_ids": ["e1"]}}
    section = next(section for section in build_report(state)["sections"] if section["heading"] == "3. 기술 개요")
    assert section["paragraphs"][0] == "KIVI의 핵심 원리: KV를 2비트로 양자화한다. KIVI의 실험 조건: Llama-2-7B; A100. KIVI의 성능 보고: 2.6x memory. KIVI의 한계: 긴 문맥 미검증 [1]."
    assert section["paragraphs"][1] == "InfiniGen: 기술 조사 결과 미확인"


def test_limitations_report_evidence_check_coverage_and_single_source_dependence():
    state = base_state()
    state["evidence_check"] = {"items": [
        {"perspective": "market", "technology": "KIVI", "field": "adoption", "passed": True},
        {"perspective": "domain", "technology": "KIVI", "field": "memory", "passed": True},
        {"perspective": "domain", "technology": "KIVI", "field": "quality", "passed": False},
    ]}
    state["domain_analysis"] = {"technologies": {"KIVI": {"memory": {"label": "적용 가능 보고", "reason": "절감", "evidence_ids": ["e1"]}}}}
    limits = next(section for section in build_report(state)["sections"] if section["heading"] == "6. 한계점")["paragraphs"]
    assert any(p.startswith("근거 검사: 판정 항목 3개 중 2개가 근거 확인을 통과했다.") for p in limits)
    single = next(p for p in limits if p.startswith("단일 출처 의존"))
    assert "판정 2개 중 2개" in single and "도메인 적용 판정 1개는 해당 기술 논문의 자체 보고" in single


def test_small_report_keeps_the_roomiest_layout():
    report = build_report(base_state())
    assert report["layout"] == {"level": 0, "pdf_pages": report["layout"]["pdf_pages"], "max_pages": MAX_PDF_PAGES, "fits": True}


def test_clip_sentences_cuts_at_sentence_ends_and_never_inside_a_citation():
    text = "첫 문장이다. 둘째 문장은 조금 더 길게 이어진다. 셋째 문장이다."
    assert _clip_sentences(text, 100) == text
    assert _clip_sentences(text, 34) == "첫 문장이다. 둘째 문장은 조금 더 길게 이어진다."
    clipped = _clip_sentences("근거가 긴 문장 하나로만 이루어져 있고 끝에 인용이 붙는다 [web-evidence-000000000000000000000001]", 50)
    assert clipped.endswith("…") and "[" not in clipped


def test_josa_handles_hangul_digits_and_latin():
    assert josa("KIVI", "을", "를") == "KIVI를" and josa("InfiniGen", "을", "를") == "InfiniGen을"
    assert josa("서빙", "을", "를") == "서빙을" and josa("메모리", "은", "는") == "메모리는"
    assert josa("TRL 3", "은", "는") == "TRL 3은"


def test_save_outputs_uses_report_name_and_reports_pdf_font(tmp_path):
    state = initial_state(mode="replay")
    state.update(base_state())
    state["run_config"] = initial_state(mode="replay")["run_config"]
    state["report"] = build_report(state)
    artifacts = save_outputs(state, tmp_path, report_name="RAG-Output_test")
    assert artifacts["pdf"].endswith("RAG-Output_test.pdf") and (tmp_path / "RAG-Output_test.html").exists()
    manifest = (tmp_path / "run_manifest.json").read_text(encoding="utf-8")
    expected_font = "KoreanBody" if os.path.exists("/System/Library/Fonts/Supplemental/AppleGothic.ttf") else "HYSMyeongJo-Medium"
    assert f'"pdf_font": "{expected_font}"' in manifest
    assert '"pdf_pages": ' in manifest and '"layout": {' in manifest
    assert "<table>" in (tmp_path / "RAG-Output_test.html").read_text(encoding="utf-8")


def quality(action, instructions=(), **items):
    scores = {"groundedness": 5, "neutrality": 5, "bias": 5, "coverage": 5, **items}
    return {
        "passed": False,
        "threshold": 4,
        "items": {key: {"score": score, "rule_score": score, "llm_score": None, "reasons": [f"{key} 사유"] if score < 4 else []} for key, score in scores.items()},
        "action": action,
        "instructions": list(instructions),
        "rework_requests": [],
    }


def revisable_state():
    state = base_state()
    state["sources"]["s2"] = {"title": "Blog", "url": "https://example.org/blog", "source_type": "web"}
    state["evidence"]["e2"] = {"technology": "KIVI", "source_id": "s2", "location": "웹", "quote": "second", "claim_type": "reported_fact"}
    state["evidence_check"] = {"items": [{"perspective": "market", "technology": "KIVI", "field": "adoption", "passed": True}]}
    state["market_analysis"]["technologies"]["KIVI"]["adoption"] = {"label": "연구 재현 수준", "reason": "공개 코드가 있다. KIVI가 더 우수하다.", "evidence_ids": ["e1"]}
    state["technical_findings"] = {"KIVI": {"principle": "KV를 2비트로 양자화한다", "limitations": ["긴 문맥은 검증되지 않았다"], "evidence_ids": ["e2"]}}
    return state


def sections_by_heading(report):
    return {section["heading"]: section for section in report["sections"]}


def test_rewrite_removes_only_the_instructed_sentence_from_the_named_section():
    state = revisable_state()
    first = build_report(state)
    assert "더 우수하다" in first["markdown"] and first["revision"] == {"number": 0}
    instruction = {"item": "neutrality", "section": "4.1 시장성", "problem": "우열 표현", "quote": "KIVI가 더 우수하다.", "fix": "삭제"}
    state["report"] = first
    state["quality_result"] = quality("rewrite_report", [instruction], neutrality=1)
    second = build_report(state)
    assert "더 우수하다" not in second["markdown"] and "공개 코드가 있다." in second["markdown"]
    assert second["revision"] == {"number": 1, "action": "rewrite_report", "applied": [{"item": "neutrality", "section": "4.1 시장성", "quote": "KIVI가 더 우수하다.", "result": "removed"}]}
    before, after = sections_by_heading(first), sections_by_heading(second)
    assert all(before[heading] == after[heading] for heading in before if heading != "4.1 시장성")  # other sections are untouched
    state["report"] = second
    assert build_report(state)["revision"]["number"] == 2


def test_removed_sentence_takes_its_citation_out_of_the_appendix():
    state = revisable_state()
    first = build_report(state)
    assert set(first["citation_map"].values()) == {"e1", "e2"}
    quote = sections_by_heading(first)["3. 기술 개요"]["paragraphs"][0]  # quoted with citation numbers, as the evaluator sees it
    state["report"] = first
    state["quality_result"] = quality("rewrite_report", [{"item": "groundedness", "section": "3. 기술 개요", "problem": "근거 불일치", "quote": quote, "fix": "삭제"}], groundedness=2)
    second = build_report(state)
    assert set(second["citation_map"].values()) == {"e1"} and second["used_source_ids"] == ["s1"]
    assert sections_by_heading(second)["3. 기술 개요"]["paragraphs"][0] != quote
    assert "second" not in second["markdown"]


def test_instruction_records_for_missing_quotes_and_unknown_sections():
    state = revisable_state()
    state["report"] = build_report(state)
    state["quality_result"] = quality(
        "recollect",
        [
            {"item": "neutrality", "section": "없는 절", "quote": "KIVI가 더 우수하다"},  # unknown section: searched everywhere
            {"item": "groundedness", "section": "5. 시사점", "quote": "보고서에 없는 문장"},
            {"item": "coverage", "section": "4.2 이해관계자", "quote": ""},
        ],
        coverage=2,
    )
    report = build_report(state)
    assert [record["result"] for record in report["revision"]["applied"]] == ["removed", "not_found", "no_quote"]
    assert report["revision"]["action"] == "recollect" and "더 우수하다" not in report["markdown"]


def test_accept_with_limits_lists_failed_quality_items_and_leaves_the_body_alone():
    state = revisable_state()
    first = build_report(state)
    state["report"] = first
    state["quality_result"] = quality("accept_with_limits", [{"item": "neutrality", "section": "4.1 시장성", "quote": "KIVI가 더 우수하다."}], neutrality=2, bias=3)
    second = build_report(state)
    limits = sections_by_heading(second)["6. 한계점"]["paragraphs"]
    line = next(p for p in limits if p.startswith("품질 평가 미달 항목"))
    assert "통과 기준(4점)" in line and "중립성 2점(neutrality 사유)" in line and "편향 통제 3점" in line and "Groundedness" not in line
    assert "더 우수하다" in second["markdown"] and second["revision"] == {"number": 1, "action": "accept_with_limits", "applied": []}
    before, after = sections_by_heading(first), sections_by_heading(second)
    assert all(before[heading] == after[heading] for heading in before if heading != "6. 한계점")
    state["quality_result"] = {**quality("pass"), "passed": True}
    assert build_report(state)["revision"] == {"number": 0}


def test_adjacent_citations_are_merged_for_display_only(tmp_path):
    assert compact_citations("보고됐다 [1] [2] [3] [4] [5] [6] [7] [8].") == "보고됐다 [1–8]."
    assert compact_citations("[1] [3] [5] [6] [7]") == "[1, 3, 5–7]"
    assert compact_citations("[2][9] 그리고 [4] [5]") == "[2, 9] 그리고 [4, 5]"
    assert compact_citations("단독 [3], 근거 ID [e1] [e2], 표지 [R1] [R2]") == "단독 [3], 근거 ID [e1] [e2], 표지 [R1] [R2]"
    state = revisable_state()
    state["market_analysis"]["technologies"]["KIVI"]["adoption"]["evidence_ids"] = ["e1", "e2"]
    full = initial_state(mode="replay")
    full.update(state)
    full["run_config"] = initial_state(mode="replay")["run_config"]
    full["report"] = build_report(full)
    adoption = next(row for row in sections_by_heading(full["report"])["4.1 시장성"]["table"]["rows"] if row[1] == "상용화와 채택 현황")
    assert adoption[-1] == "[1] [2]"  # the data keeps one bracket per citation
    save_outputs(full, tmp_path)
    assert "[1, 2]" in (tmp_path / "report.html").read_text(encoding="utf-8") and "[1] [2]" in (tmp_path / "report.md").read_text(encoding="utf-8")
