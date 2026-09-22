import os

from skala_rag.agents.korean import josa
from skala_rag.agents.report import SUMMARY_LIMIT, build_report, format_reference, save_outputs
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
    assert "[e1]" in markdown and "[bad]" not in markdown and "미확인" in markdown
    assert "공개 정보에 근거한 추정" in markdown
    assert "InfiniGen을" in markdown and "KIVI와" in markdown  # particle handling
    assert "| 기술 | 항목 | 판정 |" in markdown


def test_reference_format_for_papers_and_web_pages():
    paper = format_reference("s1", {"title": "KIVI", "author_or_org": "Liu, Z. et al.", "published_at": "2024-02-02", "venue": "ICML 2024", "url": "https://arxiv.org/abs/2402.02750", "source_type": "paper"})
    assert paper == "[s1] Liu, Z. et al.(2024). KIVI. ICML 2024, https://arxiv.org/abs/2402.02750"
    web = format_reference("w1", {"title": "Blog", "author_or_org": "Google Research", "published_at": "2026-03-30", "venue": "Google Research Blog", "url": "https://example.org", "source_type": "web"})
    assert web == "[w1] Google Research(2026-03-30). Blog. Google Research Blog, https://example.org"
    assert format_reference("x", {}) == "[x] 저자 미상(발행일 미상). 제목 미상. (URL 미기재)"


def test_trl_stage_details_and_summary_limit():
    state = base_state()
    state["trl_analysis"] = {"technologies": {"KIVI": {"trl": {"label": "TRL 4", "reason": "공개 코드 재현", "evidence_ids": ["e1"], "highest_confirmed": "TRL 4", "stages": {"TRL 4": {"met": True, "evidence_ids": ["e1"]}, "TRL 5": {"met": False, "note": "PR 미확인"}}, "missing_evidence": ["vLLM 통합 PR"], "estimation_note": "공개 정보 기반"}}}}
    state["evidence"]["e1"]["quote"] = "q" * 1000
    report = build_report(state)
    trl_section = next(section for section in report["sections"] if section["heading"] == "4.4 기술 성숙도")
    assert any("TRL 5 미충족, PR 미확인" in p and "vLLM 통합 PR" in p for p in trl_section["paragraphs"])
    assert len(report["sections"][0]["paragraphs"][0]) <= SUMMARY_LIMIT
    appendix = next(section for section in report["sections"] if section["heading"].startswith("부록"))
    assert all(len(p) < 600 for p in appendix["paragraphs"])


def test_report_redacts_secrets_and_private_contact_details():
    state = base_state()
    state["technical_findings"] = {"KIVI": {"note": "sk-test0123456789abcdefghijkl owner@example.org"}}
    markdown = build_report(state)["markdown"]
    assert "sk-test0123456789abcdefghijkl" not in markdown and "owner@example.org" not in markdown
    assert "[REDACTED]" in markdown


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
    assert "<table>" in (tmp_path / "RAG-Output_test.html").read_text(encoding="utf-8")
