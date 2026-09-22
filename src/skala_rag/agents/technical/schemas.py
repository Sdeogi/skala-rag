"""기술조사 Agent의 잠정 데이터 모델.

설계서 D.1 State 표의 ``technical_findings``, ``evidence`` 필드 이름을 그대로 따랐다.
**주의**: 이 스키마는 `graph/`(State 전체 설계) 담당자가 아직 만들지 않은 상태에서
`agents/technical`이 단독으로 돌아갈 수 있도록 만든 잠정본이다. 실제 LangGraph State
스키마가 정해지면 이 모델을 그대로 재사용하거나, `technical_research_node`의 반환값을
그 스키마에 맞게 얇은 어댑터로 감싸면 된다.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

ClaimType = Literal["reported_fact", "inference", "unverified"]
Category = Literal["principle", "experimental_setup", "performance", "limitations"]


class Evidence(BaseModel):
    """근거 하나. evidence_id를 키로 공유 evidence 풀에 저장된다(설계서 D.1)."""

    evidence_id: str
    source_id: str
    tech_name: str
    page: int
    section: str
    claim: str
    quote: str
    claim_type: ClaimType = "reported_fact"


class CategoryFindings(BaseModel):
    claims: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)


class TechFindings(BaseModel):
    tech_name: str
    principle: CategoryFindings = Field(default_factory=CategoryFindings)
    experimental_setup: CategoryFindings = Field(default_factory=CategoryFindings)
    performance: CategoryFindings = Field(default_factory=CategoryFindings)
    limitations: CategoryFindings = Field(default_factory=CategoryFindings)


class TechnicalResearchResult(BaseModel):
    technical_findings: dict[str, TechFindings] = Field(default_factory=dict)
    evidence: dict[str, Evidence] = Field(default_factory=dict)
    errors: list[dict] = Field(default_factory=list)
