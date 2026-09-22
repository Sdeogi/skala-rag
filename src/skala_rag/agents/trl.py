"""기술 성숙도(TRL) 관점 평가 에이전트 (PDF C.2).

`notebooks/22-TRLAgent.ipynb`에서 검증한 로직을 이관.

## 사용 (D의 그래프 조립부에서)

```python
from skala_rag.tools.retrieve import retrieve_papers   # A(김건우) 담당
from skala_rag.tools.web import search_web             # B(서경덕) 담당
from skala_rag.agents.trl import make_trl_evaluator

trl_node = make_trl_evaluator(
    retriever=retrieve_papers,
    web_search=search_web,
    model_name="gpt-5.4-mini",
)
graph.add_node("trl", trl_node)
```
"""
from __future__ import annotations

from typing import Callable, Literal

from langchain.chat_models import init_chat_model
from pydantic import BaseModel, Field

from skala_rag.prompts.trl import (
    TRL_STAGES,
    TRL_STAGE_USER_TEMPLATE,
    TRL_SYSTEM_PROMPT,
    TRLStageSpec,
    format_evidence_block,
)
from skala_rag.schemas.state import (
    CompleteStatus,
    Evidence,
    PerspectiveName,
    PerspectiveResult,
    RubricItem,
    TechName,
    TRLLevel,
)


# ---------------------------------------------------------------------------
# 도구 타입
# ---------------------------------------------------------------------------
RetrieveFn = Callable[[str, Literal["KIVI", "InfiniGen"], int], list[Evidence]]
WebSearchFn = Callable[..., list[Evidence]]
"""B의 tools/web.py 시그니처(가정):
    search_web(query, tech, purpose='adoption', max_results=5) -> list[Evidence]
"""


# ---------------------------------------------------------------------------
# 단계별 판정 (LLM)
# ---------------------------------------------------------------------------
class _StageJudgement(BaseModel):
    verdict: Literal["충족", "미충족", "미확인"]
    reason: str
    evidence_ids: list[str] = Field(default_factory=list)
    missing_evidence_note: str = ""


def judge_stage(
    spec: TRLStageSpec,
    tech: TechName,
    candidates: list[Evidence],
    model_name: str,
) -> _StageJudgement:
    llm = init_chat_model(model_name, model_provider="openai", temperature=0)
    llm_struct = llm.with_structured_output(_StageJudgement)

    query = spec.query_hints_by_tech[tech.value]
    user_msg = TRL_STAGE_USER_TEMPLATE.format(
        tech=tech.value,
        stage_label=spec.trl_label,
        stage_key=spec.stage_key,
        description=spec.description,
        mode=spec.evidence_mode,
        query=query,
        evidence_block=format_evidence_block(candidates),
    )
    j: _StageJudgement = llm_struct.invoke([
        ("system", TRL_SYSTEM_PROMPT),
        ("user", user_msg),
    ])

    # 근거 후보에 없는 id는 삭제. 충족인데 근거 0개면 미확인 강등.
    valid_ids = {c.evidence_id for c in candidates}
    j.evidence_ids = [eid for eid in j.evidence_ids if eid in valid_ids]
    if j.verdict == "충족" and not j.evidence_ids:
        j.verdict = "미확인"
        j.reason += " (근거 후보에 매칭되는 id 없음 → 미확인 강등)"
    return j


# ---------------------------------------------------------------------------
# 최고 도달 단계 계산
# ---------------------------------------------------------------------------
def _highest_reached(stage_results: list[tuple[TRLStageSpec, _StageJudgement]]) -> TRLLevel:
    """낮은 단계부터 순회하며 마지막 '충족' stage의 TRLLevel을 반환.
    아무 단계도 충족 못 하면 UNCLEAR.
    """
    highest = TRLLevel.UNCLEAR
    for spec, j in stage_results:
        if j.verdict == "충족":
            highest = spec.trl_enum
    return highest


# ---------------------------------------------------------------------------
# tech 하나에 대한 판정 → RubricItem
# ---------------------------------------------------------------------------
def judge_trl_for_tech(
    tech: TechName,
    retriever: RetrieveFn,
    web_search: WebSearchFn,
    model_name: str,
    k_rag: int = 5,
    k_web: int = 5,
) -> tuple[RubricItem, dict[str, Evidence]]:
    used_evidence: dict[str, Evidence] = {}
    stage_results: list[tuple[TRLStageSpec, _StageJudgement]] = []

    for spec in TRL_STAGES:
        query = spec.query_hints_by_tech[tech.value]
        if spec.evidence_mode == "rag":
            candidates = retriever(query, tech.value, k_rag)
        else:
            candidates = web_search(query, tech.value, purpose="adoption", max_results=k_web)
        for c in candidates:
            used_evidence[c.evidence_id] = c
        j = judge_stage(spec, tech, candidates, model_name)
        stage_results.append((spec, j))

    highest = _highest_reached(stage_results)

    reason_lines: list[str] = []
    all_evidence_ids: list[str] = []
    top_evidence_ids: list[str] = []
    missing_notes: list[str] = []
    for spec, j in stage_results:
        reason_lines.append(f"{spec.trl_label}: {j.verdict}. {j.reason.strip()}")
        all_evidence_ids.extend(j.evidence_ids)
        if spec.trl_enum == highest:
            top_evidence_ids.extend(j.evidence_ids)
        if j.missing_evidence_note.strip():
            missing_notes.append(f"[{spec.trl_label}] {j.missing_evidence_note.strip()}")

    item = RubricItem(
        item_key="trl_level",
        tech=tech,
        verdict=highest.value,
        reason=" | ".join(reason_lines),
        evidence_ids=(
            top_evidence_ids
            if top_evidence_ids
            else list(dict.fromkeys(all_evidence_ids))[:5]
        ),
        conditions="\n".join(missing_notes) if missing_notes else None,
    )
    return item, used_evidence


# ---------------------------------------------------------------------------
# LangGraph node factory
# ---------------------------------------------------------------------------
def make_trl_evaluator(
    retriever: RetrieveFn,
    web_search: WebSearchFn,
    model_name: str = "gpt-5.4-mini",
    k_rag: int = 5,
    k_web: int = 5,
) -> Callable[[dict], dict]:
    """TRL 평가 노드 함수 생성.

    반환된 노드는 State의 `trl_analysis`, `evidence` 키에 병합될 dict를 돌려준다.
    `sources`는 A/B의 도구가 별도로 State에 채우는 것으로 가정.
    """

    def trl_evaluator(state: dict) -> dict:
        items: list[RubricItem] = []
        all_used: dict[str, Evidence] = {}
        unresolved: list[str] = []

        for tech in (TechName.KIVI, TechName.INFINIGEN):
            item, used = judge_trl_for_tech(
                tech, retriever, web_search, model_name, k_rag, k_web
            )
            items.append(item)
            all_used.update(used)
            if item.verdict == TRLLevel.UNCLEAR.value:
                unresolved.append(f"[TRL|{tech.value}] TRL 단계를 확정할 근거를 찾지 못함")

        all_complete = all(it.verdict != TRLLevel.UNCLEAR.value for it in items)
        result = PerspectiveResult(
            perspective=PerspectiveName.TRL,
            items=items,
            unresolved_questions=unresolved,
            status=CompleteStatus.COMPLETE
            if all_complete
            else CompleteStatus.INSUFFICIENT_EVIDENCE,
        )
        return {
            "trl_analysis": result,
            "evidence": all_used,
        }

    return trl_evaluator


__all__ = [
    "RetrieveFn", "WebSearchFn",
    "judge_stage", "judge_trl_for_tech",
    "make_trl_evaluator",
]
