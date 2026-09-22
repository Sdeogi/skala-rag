"""보완 노드 (PDF D.4).

`evidence_check`가 만든 `missing_questions`만 재검색해 해당 관점 결과를 갱신한다.
네 관점 전체를 다시 실행하지 않으므로 비용이 작고, 관점 결과의 작성자가 하나로 유지되어
병렬 갱신 충돌이 없다. 재시도는 evidence_check 쪽에서 최대 2회로 제한.

## 그래프 흐름 (PDF D.3)

```
evidence_check → needs_retry?
                ├── 예 → supplement → 다시 evidence_check
                └── 아니오 → synthesis
```

## 사용 (D의 그래프 조립부에서)

```python
from skala_rag.tools.retrieve import retrieve_papers      # A
from skala_rag.tools.web import search_web                # B
from skala_rag.supplement import make_supplement_node

supplement_node = make_supplement_node(
    retriever=retrieve_papers,
    web_search=search_web,
    model_name="gpt-5.4-mini",
)
graph.add_node("supplement", supplement_node)
```

## 담당 범위
- **DOMAIN** 관점 항목은 재판정 (RAG)
- **TRL** 관점 항목은 해당 tech 전체(7단계) 재판정 (RAG+웹)
- **MARKET/STAKEHOLDER** 관점 항목은 B의 판정 로직이 없어 여기선 건드리지 않음.
  통합 이후 B가 별도로 확장하거나 여기 로직을 이식.
"""
from __future__ import annotations

from typing import Callable

from skala_rag.agents.domain import RetrieveFn, judge_one
from skala_rag.agents.trl import WebSearchFn, judge_trl_for_tech
from skala_rag.prompts.domain import DOMAIN_RUBRIC, DomainRubricSpec
from skala_rag.schemas.state import (
    CompleteStatus,
    Evidence,
    PerspectiveName,
    PerspectiveResult,
    Question,
    RubricItem,
    TechName,
)


UNCLEAR_LABELS: set[str] = {"미확인"}


def _domain_spec_by_key(item_key: str) -> DomainRubricSpec | None:
    for s in DOMAIN_RUBRIC:
        if s.item_key == item_key:
            return s
    return None


def _refresh_domain(
    q: Question,
    prev: PerspectiveResult,
    retriever: RetrieveFn,
    model_name: str,
    k: int,
    used_evidence: dict[str, Evidence],
) -> PerspectiveResult:
    """DOMAIN의 (tech, item_key) 하나를 재검색·재판정해 items에서 교체."""
    spec = _domain_spec_by_key(q.item_key)
    if spec is None:
        return prev
    candidates = retriever(q.query, q.tech.value, k)
    for c in candidates:
        used_evidence[c.evidence_id] = c
    new_item = judge_one(spec, q.tech, candidates, model_name)
    new_items: list[RubricItem] = [
        new_item if (it.tech == q.tech and it.item_key == q.item_key) else it
        for it in prev.items
    ]
    return prev.model_copy(update={"items": new_items})


def _refresh_trl_tech(
    tech: TechName,
    prev: PerspectiveResult,
    retriever: RetrieveFn,
    web_search: WebSearchFn,
    model_name: str,
    k_rag: int,
    k_web: int,
    used_evidence: dict[str, Evidence],
) -> PerspectiveResult:
    """TRL의 한 tech 전체(7단계)를 다시 판정해 items에서 교체.

    TRL은 tech별 1개 RubricItem(item_key="trl_level")이라 단계별 세분 재판정 대신
    tech 통째로 재계산이 자연스럽다.
    """
    new_item, used = judge_trl_for_tech(
        tech, retriever, web_search, model_name, k_rag, k_web
    )
    used_evidence.update(used)
    new_items: list[RubricItem] = [
        new_item if it.tech == tech else it for it in prev.items
    ]
    return prev.model_copy(update={"items": new_items})


def _recompute_status(prev: PerspectiveResult) -> PerspectiveResult:
    """items의 verdict를 보고 status·unresolved_questions 재계산."""
    all_complete = all(it.verdict not in UNCLEAR_LABELS for it in prev.items)
    status = (
        CompleteStatus.COMPLETE if all_complete else CompleteStatus.INSUFFICIENT_EVIDENCE
    )
    unresolved = [
        f"[{prev.perspective.value}|{it.tech.value}|{it.item_key}] 미확인 상태"
        for it in prev.items
        if it.verdict in UNCLEAR_LABELS
    ]
    return prev.model_copy(
        update={"status": status, "unresolved_questions": unresolved}
    )


def make_supplement_node(
    retriever: RetrieveFn,
    web_search: WebSearchFn | None = None,
    model_name: str = "gpt-5.4-mini",
    k_rag: int = 5,
    k_web: int = 5,
) -> Callable[[dict], dict]:
    """보완 노드 factory. LangGraph node로 등록해 `evidence_check` 뒤에 붙인다."""

    def supplement(state: dict) -> dict:
        missing: list[Question] = state.get("missing_questions", []) or []
        retry_count = int(state.get("retry_count", 0) or 0)
        used_evidence: dict[str, Evidence] = {}

        domain_analysis: PerspectiveResult | None = state.get("domain_analysis")
        trl_analysis: PerspectiveResult | None = state.get("trl_analysis")

        # DOMAIN — 항목별 재판정
        for q in [m for m in missing if m.perspective == PerspectiveName.DOMAIN]:
            if domain_analysis is None:
                continue
            domain_analysis = _refresh_domain(
                q, domain_analysis, retriever, model_name, k_rag, used_evidence,
            )

        # TRL — tech별로 통째 재판정 (item_key 무관, tech 중복 제거)
        trl_techs = {
            m.tech for m in missing if m.perspective == PerspectiveName.TRL
        }
        if trl_analysis is not None and web_search is not None:
            for tech in trl_techs:
                trl_analysis = _refresh_trl_tech(
                    tech, trl_analysis, retriever, web_search,
                    model_name, k_rag, k_web, used_evidence,
                )

        out: dict = {
            "retry_count": retry_count + 1,   # evidence_check가 이 값을 보고 상한 판단
            "evidence": used_evidence,         # State reducer(merge_by_id)가 병합
            "missing_questions": [],           # 다음 evidence_check가 다시 만든다
        }
        if domain_analysis is not None:
            out["domain_analysis"] = _recompute_status(domain_analysis)
        if trl_analysis is not None:
            out["trl_analysis"] = _recompute_status(trl_analysis)
        return out

    return supplement


__all__ = [
    "make_supplement_node",
    "_refresh_domain",
    "_refresh_trl_tech",
    "_recompute_status",
]
