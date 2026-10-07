"""Unit tests for integration.rework: reason classification and query builder."""

from __future__ import annotations

from skala_rag.integration.rework import (
    REJUDGE_REASONS,
    RESEARCH_REASONS,
    build_rework_queries,
    needs_rejudge,
    needs_research,
)


def test_research_reasons_trigger_research():
    for reason in RESEARCH_REASONS:
        assert needs_research({"reasons": [reason]}) is True
        assert needs_rejudge({"reasons": [reason]}) is False


def test_rejudge_only_reasons():
    for reason in REJUDGE_REASONS:
        assert needs_research({"reasons": [reason]}) is False
        assert needs_rejudge({"reasons": [reason]}) is True


def test_empty_reasons_defaults_to_research():
    assert needs_research({"reasons": []}) is True
    assert needs_rejudge({"reasons": []}) is False


def test_mixed_reasons_prefer_research():
    request = {"reasons": ["invalid_label", "missing_evidence"]}
    assert needs_research(request) is True
    assert needs_rejudge(request) is False


def test_unsupported_claim_pulls_review_reason_keywords_into_query():
    request = {
        "technology": "InfiniGen",
        "field": "adoption",
        "reasons": ["unsupported_claim"],
        "review_reason": "근거가 업계 일반 평가일 뿐 InfiniGen을 직접 지칭하지 않음",
        "question": "InfiniGen의 상용화와 채택 현황을 뒷받침하는 원문 근거는?",
    }
    queries = build_rework_queries(request, prior_queries=[], paper_id="2406.19707")
    assert queries
    combined = " ".join(queries)
    # Paper id and quoted technology name are preserved in the narrowing variant.
    assert "2406.19707" in combined and '"InfiniGen"' in combined
    # At least one review_reason keyword lands in a query (ignoring stopwords).
    assert any(keyword in combined for keyword in ("근거", "업계", "일반", "평가"))


def test_build_rework_queries_drops_duplicates_from_prior():
    request = {
        "technology": "KIVI",
        "field": "memory",
        "reasons": ["missing_evidence"],
        "question": "KIVI memory report",
    }
    # Pretend the broadening query was tried last round.
    prior = ["KIVI memory report evidence"]
    queries = build_rework_queries(request, prior_queries=prior)
    for query in queries:
        assert query.lower() not in {prior_query.lower() for prior_query in prior}


def test_build_rework_queries_broadens_with_limitation_term():
    request = {
        "technology": "KIVI",
        "field": "adoption",
        "reasons": ["not_found_label"],
        "question": "Where is KIVI adopted?",
    }
    queries = build_rework_queries(request, prior_queries=[])
    assert any("limitation" in query.lower() or "issue" in query.lower() for query in queries)


def test_build_rework_queries_falls_back_when_only_rejudge_reasons():
    """Even for a rejudge-only request, the builder returns a generic query so
    the caller never gets an empty list."""
    request = {
        "technology": "KIVI",
        "field": "memory",
        "reasons": ["invalid_label"],
    }
    queries = build_rework_queries(request, prior_queries=[])
    assert queries, "builder should always return at least one query"
