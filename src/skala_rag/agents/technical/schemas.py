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
    """근거 하나. evidence_id를 키로 공유 evidence 풀에 저장된다.

    설계서 D.1: "Evidence는 출처에서 뽑은 근거 하나이며 evidence_id, source_id, 기술명,
    주장, 인용 구절, 페이지 또는 절, 주장 유형, 실험 조건을 갖는다." 8개 필드 그대로 반영.
    """

    evidence_id: str
    source_id: str
    tech_name: str
    page: int
    section: str
    claim: str
    quote: str
    claim_type: ClaimType = "reported_fact"
    experimental_condition: str | None = None
    """모델/GPU/배치 크기/문맥 길이 등, 주장이 성립하는 실험 조건(발췌문에 명시된 경우만).
    성능·한계 관련 주장에는 채워지고, 원리 설명처럼 조건이 없는 주장은 null로 둔다."""


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
