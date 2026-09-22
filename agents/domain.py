"""도메인 적용 관점 평가 에이전트 (PDF C.5).

`notebooks/21-DomainAgent.ipynb`에서 검증한 로직을 이관.

## 사용 (D의 그래프 조립부에서)

```python
from tools.retrieve import retrieve_papers   # A(김건우) 담당
from agents.domain import make_domain_evaluator

domain_node = make_domain_evaluator(retriever=retrieve_papers, model_name="gpt-5.4-mini")
graph.add_node("domain", domain_node)
```

`retriever(query, tech, k)` 시그니처만 지키면 어떤 retriever도 주입 가능.
"""
from __future__ import annotations

from typing import Callable, Literal

from langchain.chat_models import init_chat_model
from pydantic import BaseModel, Field

from prompts.domain import (
    DOMAIN_RUBRIC,
    DomainRubricSpec,
    SYSTEM_PROMPT,
    USER_TEMPLATE,
    format_evidence_block,
    format_label_notes,
)
from schemas.state import (
    CompleteStatus,
    Evidence,
    IntegrationVerdict,
    PerspectiveName,
    PerspectiveResult,
    RubricItem,
    StandardVerdict,
    TechName,
)


# ---------------------------------------------------------------------------
# 검색 도구 타입
# ---------------------------------------------------------------------------
RetrieveFn = Callable[[str, Literal["KIVI", "InfiniGen"], int], list[Evidence]]


# ---------------------------------------------------------------------------
# LLM 판정
# ---------------------------------------------------------------------------
class _ItemJudgement(BaseModel):
    """LLM의 raw 출력. RubricItem으로 변환 전 임시 구조."""
    verdict: str = Field(..., description="허용 라벨 집합 안에서만 선택")
    reason: str
    evidence_ids: list[str] = Field(default_factory=list)
    conditions: str | None = None


def _unclear_label_for(item_key: str) -> str:
    """항목별 '미확인' 라벨 매핑. integration만 IntegrationVerdict, 나머지는 StandardVerdict."""
    return (
        IntegrationVerdict.UNCLEAR.value
        if item_key == "integration"
        else StandardVerdict.UNCLEAR.value
    )


def judge_one(
    spec: DomainRubricSpec,
    tech: TechName,
    candidates: list[Evidence],
    model_name: str,
) -> RubricItem:
    """한 (기술, rubric 항목) 조합에 대해 판정 하나를 낸다."""
    llm = init_chat_model(model_name, model_provider="openai", temperature=0)
    llm_struct = llm.with_structured_output(_ItemJudgement)

    user_msg = USER_TEMPLATE.format(
        item_key=spec.item_key,
        tech=tech.value,
        question=spec.question,
        allowed=" / ".join(spec.allowed_verdicts),
        label_notes_block=format_label_notes(spec.label_notes),
        evidence_block=format_evidence_block(candidates),
    )
    j: _ItemJudgement = llm_struct.invoke([
        ("system", SYSTEM_PROMPT),
        ("user", user_msg),
    ])

    unclear = _unclear_label_for(spec.item_key)
    verdict = j.verdict if j.verdict in spec.allowed_verdicts else unclear
    valid_ids = {c.evidence_id for c in candidates}
    ev_ids = [eid for eid in j.evidence_ids if eid in valid_ids]

    if verdict != unclear and not ev_ids:
        verdict = unclear

    return RubricItem(
        item_key=spec.item_key,
        tech=tech,
        verdict=verdict,
        reason=j.reason,
        evidence_ids=ev_ids,
        conditions=j.conditions,
    )


# ---------------------------------------------------------------------------
# LangGraph node factory
# ---------------------------------------------------------------------------
def make_domain_evaluator(
    retriever: RetrieveFn,
    model_name: str = "gpt-5.4-mini",
    k_per_query: int = 5,
) -> Callable[[dict], dict]:
    """도메인 평가 노드 함수를 생성한다.

    노드 반환값은 State의 `domain_analysis`, `evidence` 키에 병합된다.
    """

    def domain_evaluator(state: dict) -> dict:
        items: list[RubricItem] = []
        used_evidence: dict[str, Evidence] = {}
        unresolved: list[str] = []

        for tech in (TechName.KIVI, TechName.INFINIGEN):
            for spec in DOMAIN_RUBRIC:
                query = spec.query_hints_by_tech[tech.value]
                candidates = retriever(query, tech.value, k_per_query)
                for c in candidates:
                    used_evidence[c.evidence_id] = c
                ri = judge_one(spec, tech, candidates, model_name)
                items.append(ri)
                if ri.verdict in {
                    StandardVerdict.UNCLEAR.value,
                    IntegrationVerdict.UNCLEAR.value,
                }:
                    unresolved.append(
                        f"[도메인|{tech.value}|{spec.item_key}] {spec.question}"
                    )

        all_complete = all(
            it.verdict not in {
                StandardVerdict.UNCLEAR.value,
                IntegrationVerdict.UNCLEAR.value,
            }
            for it in items
        )
        result = PerspectiveResult(
            perspective=PerspectiveName.DOMAIN,
            items=items,
            unresolved_questions=unresolved,
            status=CompleteStatus.COMPLETE
            if all_complete
            else CompleteStatus.INSUFFICIENT_EVIDENCE,
        )
        return {
            "domain_analysis": result,
            "evidence": used_evidence,
        }

    return domain_evaluator


__all__ = [
    "RetrieveFn",
    "judge_one",
    "make_domain_evaluator",
]
