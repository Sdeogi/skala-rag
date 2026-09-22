"""기술조사 Agent 단위 테스트.

실제 OPENAI_API_KEY가 없으므로 LLM 호출 자체(`_extract_claims_for_question`)는 mock으로
대체하고, evidence_id 검증/재시도 로직과 State 어댑터(`technical_research_node`)만 검증한다.
검색(`retrieve_papers`)은 branch 1에서 이미 빌드해 커밋해 둔 실제 FAISS 인덱스를 그대로 쓴다.
"""

import pytest

from skala_rag.agents.technical import agent as agent_module
from skala_rag.agents.technical.agent import (
    _ExtractedClaim,
    _ExtractionResponse,
    run_technical_research,
    technical_research_node,
)


@pytest.fixture(autouse=True)
def _dummy_openai_key(monkeypatch):
    # ChatOpenAI 생성자는 키가 없으면 바로 예외를 던진다. 실제 API 호출은 mock으로 막으므로
    # 형식만 맞는 더미 키면 충분하다.
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-dummy")


def test_run_technical_research_uses_first_retrieved_chunk(monkeypatch):
    def fake_extract(llm, tech_name, question, chunks):
        # 항상 검색된 첫 번째 청크를 근거로 하나의 주장을 만든다(유효한 evidence_id).
        chunk = chunks[0]
        return [
            _ExtractedClaim(
                claim=f"{tech_name} 관련 주장: {question[:10]}",
                evidence_id=chunk["evidence_id"],
                claim_type="reported_fact",
            )
        ]

    monkeypatch.setattr(agent_module, "_extract_claims_for_question", fake_extract)

    result = run_technical_research(["KIVI"])

    assert "KIVI" in result.technical_findings
    findings = result.technical_findings["KIVI"]
    total_claims = (
        len(findings.principle.claims)
        + len(findings.experimental_setup.claims)
        + len(findings.performance.claims)
        + len(findings.limitations.claims)
    )
    assert total_claims > 0
    assert len(result.evidence) > 0
    # evidence 풀에 있는 모든 근거는 실제 KIVI 기술의 청크여야 한다.
    assert all(ev.tech_name == "KIVI" for ev in result.evidence.values())
    assert not result.errors


def test_invalid_evidence_id_is_dropped_after_retry(monkeypatch):
    call_count = {"n": 0}

    def fake_extract_always_invalid(llm, tech_name, question, chunks):
        call_count["n"] += 1
        return [_ExtractedClaim(claim="근거 없는 주장", evidence_id="NOT-A-REAL-ID")]

    monkeypatch.setattr(agent_module, "_extract_claims_for_question", fake_extract_always_invalid)

    result = run_technical_research(["KIVI"])

    findings = result.technical_findings["KIVI"]
    assert findings.principle.claims == []
    assert len(result.evidence) == 0
    # 카테고리 x 질문 8개 모두 재시도(2회 호출)했어야 한다.
    assert call_count["n"] == 2 * 8
    assert any(e["reason"] == "invalid_evidence_id_after_retry" for e in result.errors)


def test_technical_research_node_updates_state(monkeypatch):
    def fake_extract(llm, tech_name, question, chunks):
        if not chunks:
            return []
        chunk = chunks[0]
        return [_ExtractedClaim(claim="주장", evidence_id=chunk["evidence_id"])]

    monkeypatch.setattr(agent_module, "_extract_claims_for_question", fake_extract)

    state = {"run_config": {"tech_names": ["KIVI"]}, "evidence": {"existing-id": {"foo": "bar"}}}
    updated = technical_research_node(state)

    assert set(updated.keys()) == {"technical_findings", "evidence", "errors"}
    assert "KIVI" in updated["technical_findings"]
    assert "existing-id" in updated["evidence"]  # 기존 evidence를 지우지 않고 병합
    assert isinstance(updated["errors"], list)
