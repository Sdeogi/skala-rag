"""기술조사 Agent.

`retrieve_papers` 도구로 두 기술 논문에서 원리/실험조건/성능수치/한계를 공통 질문
목록(prompts.COMMON_QUESTIONS) 기준으로 뽑아 `TechnicalResearchResult`를 만든다.

LLM이 존재하지 않는 evidence_id를 인용하면(설계서 D.4 가드레일) 해당 질문에 한해 1회
재시도하고, 그래도 실패하면 `errors`에 기록하고 그 주장은 버린다.
"""

from __future__ import annotations

import os

from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from skala_rag.tools.retrieve import retrieve_papers

from .prompts import COMMON_QUESTIONS, EXTRACTION_SYSTEM_PROMPT, build_user_prompt
from .schemas import CategoryFindings, ClaimType, Evidence, TechFindings, TechnicalResearchResult

MODEL_ENV_VAR = "TECHNICAL_AGENT_MODEL"
DEFAULT_MODEL = "gpt-4o-mini"  # 설계서는 gpt-5.4-mini를 지정하나 실존 모델명이 불확실해 env로 override 가능하게 함


class _ExtractedClaim(BaseModel):
    claim: str
    evidence_id: str
    claim_type: ClaimType = "reported_fact"


class _ExtractionResponse(BaseModel):
    claims: list[_ExtractedClaim] = Field(default_factory=list)


def _resolve_model(model: str | None) -> str:
    return model or os.getenv(MODEL_ENV_VAR, DEFAULT_MODEL)


def _build_llm(model: str | None = None) -> ChatOpenAI:
    return ChatOpenAI(model=_resolve_model(model), temperature=0)


def _chunks_to_dicts(chunks) -> list[dict]:
    return [
        {
            "evidence_id": c.evidence_id,
            "source_id": c.source_id,
            "tech_name": c.tech_name,
            "page": c.page,
            "section": c.section,
            "text": c.text,
        }
        for c in chunks
    ]


def _extract_claims_for_question(
    llm: ChatOpenAI, tech_name: str, question: str, chunks: list[dict]
) -> list[_ExtractedClaim]:
    """LLM 호출 1회. 순수하게 이 함수만 테스트에서 mock 처리하면 나머지 로직을 검증할 수 있다."""
    structured_llm = llm.with_structured_output(_ExtractionResponse)
    user_prompt = build_user_prompt(tech_name, question, chunks)
    response = structured_llm.invoke(
        [
            {"role": "system", "content": EXTRACTION_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]
    )
    return response.claims


def _validate_claims(
    claims: list[_ExtractedClaim], chunk_by_id: dict[str, dict]
) -> tuple[list[_ExtractedClaim], list[_ExtractedClaim]]:
    """존재하지 않는 evidence_id를 인용한 주장을 걸러낸다(설계서 D.4)."""
    valid, invalid = [], []
    for claim in claims:
        (valid if claim.evidence_id in chunk_by_id else invalid).append(claim)
    return valid, invalid


def run_technical_research(
    tech_names: list[str], model: str | None = None
) -> TechnicalResearchResult:
    llm = _build_llm(model)
    result = TechnicalResearchResult()

    for tech_name in tech_names:
        findings = TechFindings(tech_name=tech_name)
        for question in COMMON_QUESTIONS:
            chunks = retrieve_papers(question.query_ko, tech_name, k=5, query_en=question.query_en)
            chunk_dicts = _chunks_to_dicts(chunks)
            chunk_by_id = {c["evidence_id"]: c for c in chunk_dicts}

            if not chunk_dicts:
                result.errors.append(
                    {
                        "node": "technical_research",
                        "tech_name": tech_name,
                        "question": question.query_ko,
                        "reason": "no_evidence_found",
                    }
                )
                continue

            claims = _extract_claims_for_question(llm, tech_name, question.query_ko, chunk_dicts)
            valid, invalid = _validate_claims(claims, chunk_by_id)

            if invalid:
                retry_claims = _extract_claims_for_question(
                    llm, tech_name, question.query_ko, chunk_dicts
                )
                valid, invalid = _validate_claims(retry_claims, chunk_by_id)
                if invalid:
                    result.errors.append(
                        {
                            "node": "technical_research",
                            "tech_name": tech_name,
                            "question": question.query_ko,
                            "reason": "invalid_evidence_id_after_retry",
                            "invalid_ids": [c.evidence_id for c in invalid],
                        }
                    )

            category_findings: CategoryFindings = getattr(findings, question.category)
            for claim in valid:
                chunk = chunk_by_id[claim.evidence_id]
                evidence = Evidence(
                    evidence_id=claim.evidence_id,
                    source_id=chunk["source_id"],
                    tech_name=chunk["tech_name"],
                    page=chunk["page"],
                    section=chunk["section"],
                    claim=claim.claim,
                    quote=chunk["text"],
                    claim_type=claim.claim_type,
                )
                result.evidence[evidence.evidence_id] = evidence
                category_findings.claims.append(claim.claim)
                if claim.evidence_id not in category_findings.evidence_ids:
                    category_findings.evidence_ids.append(claim.evidence_id)

        result.technical_findings[tech_name] = findings

    return result


def technical_research_node(state: dict) -> dict:
    """LangGraph 노드 형태 래퍼.

    `graph/` 담당자가 실제 State 스키마를 만들면, 이 함수가 반환하는
    technical_findings/evidence/errors 딕셔너리를 그대로 쓰거나 얇은 어댑터로 감싸면 된다.
    """
    run_config = state.get("run_config") or {}
    tech_names = run_config.get("tech_names") or ["KIVI", "InfiniGen"]
    model = run_config.get("technical_agent_model")

    result = run_technical_research(tech_names, model=model)

    return {
        "technical_findings": {
            name: findings.model_dump() for name, findings in result.technical_findings.items()
        },
        "evidence": {
            **state.get("evidence", {}),
            **{eid: ev.model_dump() for eid, ev in result.evidence.items()},
        },
        "errors": [*state.get("errors", []), *result.errors],
    }
