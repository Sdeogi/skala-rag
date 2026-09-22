from skala_rag.agents.synthesis import synthesize
from skala_rag.agents.report import build_report


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
    assert "대규모 배포" in str(result["conflicts"][0])
    assert not any("missing" in str(item) for item in result["agreements"] + result["conflicts"])
    assert "score" not in result


def test_report_starts_with_summary_ends_with_reference_and_filters_unknown_ids():
    state = {
        "run_config": {"technologies": ["KIVI"], "domain": "클라우드 LLM 서빙"},
        "technical_findings": {"KIVI": {"principle": "KV 압축"}},
        "sources": {"s1": {"title": "Paper", "url": "https://example.org/paper"}},
        "evidence": {"e1": {"technology": "KIVI", "source_id": "s1", "location": "p.3", "quote": "evidence"}},
        "market_analysis": {"technologies": {"KIVI": {"adoption": {"label": "연구 재현 수준", "reason": "공개 코드", "evidence_ids": ["e1", "bad"]}}}},
        "synthesis": {"agreements": [], "conflicts": [], "limitations": []},
        "missing_questions": [{"technology": "KIVI", "perspective": "market", "field": "adoption", "question": "채택 근거?"}],
        "errors": {},
    }
    report = build_report(state)
    assert report["markdown"].startswith("# SUMMARY")
    assert report["markdown"].rstrip().endswith("https://example.org/paper")
    assert "# REFERENCE" in report["markdown"]
    assert "[e1]" in report["markdown"]
    assert "[bad]" not in report["markdown"]
    assert "미확인" in report["markdown"]


def test_report_redacts_secrets_and_private_contact_details():
    state = {
        "run_config": {"technologies": ["KIVI"], "domain": "클라우드 LLM 서빙"},
        "technical_findings": {"KIVI": {"note": "sk-test0123456789abcdefghijkl owner@example.org"}},
        "sources": {}, "evidence": {}, "synthesis": {}, "errors": {},
    }
    markdown = build_report(state)["markdown"]
    assert "sk-test0123456789abcdefghijkl" not in markdown
    assert "owner@example.org" not in markdown
    assert "[REDACTED]" in markdown
