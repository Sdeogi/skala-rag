"""근거 검사 노드 (PDF D.4).

4개 관점 에이전트(시장성·이해관계자·도메인·TRL)의 `PerspectiveResult`를 State에서 읽어:
1. 라벨이 관점/항목별 허용 집합 안에 있는가
2. 확정 판정이면 evidence_ids가 있는가
3. evidence_id가 State.evidence에 실존하는가
4. (LLM) 근거 quote가 판정을 실제로 뒷받침하는가

실패 항목은 관점+기술명 붙은 `missing_questions`로 만들어 보완 노드로 넘긴다.
재시도는 최대 2회(PDF D.4).

`notebooks/23-EvidenceCheck.ipynb`에서 검증한 로직을 이관.

## 사용 (D의 그래프 조립부에서)

```python
from skala_rag.evidence_check import evidence_check

graph.add_node("evidence_check", evidence_check)
graph.add_conditional_edges(
    "evidence_check",
    lambda s: "retry" if s["evidence_check"].needs_retry else "synthesize",
    {"retry": "supplement", "synthesize": "synthesis_node"},
)
```
"""
from __future__ import annotations

from langchain.chat_models import init_chat_model
from pydantic import BaseModel, Field

from skala_rag.schemas.state import (
    CheckResult,
    Evidence,
    FailedItem,
    IntegrationVerdict,
    MarketVerdict,
    PerspectiveName,
    PerspectiveResult,
    Question,
    RubricItem,
    StakeholderVerdict,
    StandardVerdict,
    TRLLevel,
    TechName,
)


# ---------------------------------------------------------------------------
# 관점별 허용 라벨 매핑
# ---------------------------------------------------------------------------
DEFAULT_LABELS: dict[PerspectiveName, set[str]] = {
    PerspectiveName.MARKET: {v.value for v in MarketVerdict},
    PerspectiveName.STAKEHOLDER: {v.value for v in StakeholderVerdict},
    PerspectiveName.DOMAIN: {v.value for v in StandardVerdict},
    PerspectiveName.TRL: {v.value for v in TRLLevel},
}

SPECIAL_LABELS: dict[tuple[PerspectiveName, str], set[str]] = {
    (PerspectiveName.DOMAIN, "integration"): {v.value for v in IntegrationVerdict},
}


def allowed_labels(perspective: PerspectiveName, item_key: str) -> set[str]:
    return SPECIAL_LABELS.get((perspective, item_key), DEFAULT_LABELS[perspective])


UNCLEAR_LABELS: set[str] = {"미확인"}


def is_unclear(verdict: str) -> bool:
    return verdict in UNCLEAR_LABELS


# ---------------------------------------------------------------------------
# 기계 검사
# ---------------------------------------------------------------------------
def machine_check_item(
    perspective: PerspectiveName,
    item: RubricItem,
    evidence_dict: dict[str, Evidence],
) -> str | None:
    """실패 사유 문자열 반환, 통과면 None."""
    allowed = allowed_labels(perspective, item.item_key)

    if item.verdict not in allowed:
        return f"라벨 '{item.verdict}'이 허용 집합 {sorted(allowed)}에 없음"

    if is_unclear(item.verdict):
        return None

    if not item.evidence_ids:
        return "확정 판정인데 evidence_ids가 비어있음"

    missing_ids = [eid for eid in item.evidence_ids if eid not in evidence_dict]
    if missing_ids:
        return f"State.evidence에 없는 id: {missing_ids}"

    return None


def machine_check(
    results: list[PerspectiveResult],
    evidence_dict: dict[str, Evidence],
) -> list[FailedItem]:
    failures: list[FailedItem] = []
    for res in results:
        for item in res.items:
            reason = machine_check_item(res.perspective, item, evidence_dict)
            if reason:
                failures.append(FailedItem(
                    perspective=res.perspective,
                    tech=item.tech,
                    item_key=item.item_key,
                    reason=f"[기계] {reason}",
                ))
    return failures


# ---------------------------------------------------------------------------
# LLM 검토
# ---------------------------------------------------------------------------
class _EvidenceReview(BaseModel):
    supports: bool = Field(..., description="근거 구절이 판정을 실제로 뒷받침하는가")
    reason: str = Field(..., description="판단 이유 한 문장")


REVIEW_SYSTEM = (
    "당신은 근거 검토자다. 주어진 판정 라벨과 근거 인용문들을 보고,"
    " 그 근거들이 판정을 실제로 뒷받침하는지 판단한다."
    " 근거가 단순히 관련 주제를 언급했다는 것만으로는 '뒷받침한다'고 하지 마라."
    " 판정 라벨의 의미(예: '적용 가능 보고' = 자료가 효과를 직접 보고)에"
    " 정확히 맞아야 supports=true다. 애매하거나 방향이 반대면 false."
)


REVIEW_USER_TEMPLATE = """관점: {perspective}
기술: {tech}
항목: {item_key}
판정 라벨: {verdict}
판정 이유: {reason}

근거 인용문:
{quotes}

이 근거들이 위 판정을 실제로 뒷받침하는가? supports/reason JSON으로 답하라.
"""


def llm_review_item(
    perspective: PerspectiveName,
    item: RubricItem,
    evidence_dict: dict[str, Evidence],
    model_name: str,
) -> str | None:
    llm = init_chat_model(model_name, model_provider="openai", temperature=0)
    llm_struct = llm.with_structured_output(_EvidenceReview)

    quotes_block = "\n".join(
        f"- ({evidence_dict[eid].location}) {evidence_dict[eid].quote[:600]}"
        for eid in item.evidence_ids if eid in evidence_dict
    ) or "(없음)"

    user_msg = REVIEW_USER_TEMPLATE.format(
        perspective=perspective.value,
        tech=item.tech.value,
        item_key=item.item_key,
        verdict=item.verdict,
        reason=item.reason,
        quotes=quotes_block,
    )
    review: _EvidenceReview = llm_struct.invoke([
        ("system", REVIEW_SYSTEM),
        ("user", user_msg),
    ])
    if not review.supports:
        return f"[LLM] 근거가 판정을 뒷받침 안 함: {review.reason}"
    return None


def llm_review(
    results: list[PerspectiveResult],
    evidence_dict: dict[str, Evidence],
    already_failed_keys: set[tuple[PerspectiveName, TechName, str]],
    model_name: str,
) -> list[FailedItem]:
    """기계 검사 통과 + 확정 판정 항목만 LLM 검토."""
    failures: list[FailedItem] = []
    for res in results:
        for item in res.items:
            key = (res.perspective, item.tech, item.item_key)
            if key in already_failed_keys:
                continue
            if is_unclear(item.verdict):
                continue
            reason = llm_review_item(res.perspective, item, evidence_dict, model_name)
            if reason:
                failures.append(FailedItem(
                    perspective=res.perspective,
                    tech=item.tech,
                    item_key=item.item_key,
                    reason=reason,
                ))
    return failures


# ---------------------------------------------------------------------------
# missing_questions
# ---------------------------------------------------------------------------
_PERSPECTIVE_KO: dict[PerspectiveName, str] = {
    PerspectiveName.MARKET: "시장성",
    PerspectiveName.STAKEHOLDER: "이해관계자",
    PerspectiveName.DOMAIN: "도메인",
    PerspectiveName.TRL: "기술 성숙도",
}


def to_missing_question(f: FailedItem) -> Question:
    """PDF D.4: '관점과 기술명이 붙은 missing_questions로 만들어진다.'"""
    query = (
        f"[{_PERSPECTIVE_KO[f.perspective]}|{f.tech.value}|{f.item_key}] "
        f"{f.reason}. 이 항목의 판정을 뒷받침할 새로운 근거를 찾는다."
    )
    return Question(
        perspective=f.perspective,
        tech=f.tech,
        item_key=f.item_key,
        query=query,
    )


# ---------------------------------------------------------------------------
# LangGraph node
# ---------------------------------------------------------------------------
MAX_RETRIES = 2  # PDF D.4


def evidence_check(state: dict, model_name: str = "gpt-5.4-mini") -> dict:
    """근거 검사 노드.

    State의 4개 관점 결과 중 존재하는 것만 검사한다(부분 실행 지원).
    반환값은 State reducer가 병합할 수 있는 dict.
    """
    results: list[PerspectiveResult] = []
    for key in (
        "market_analysis",
        "stakeholder_analysis",
        "domain_analysis",
        "trl_analysis",
    ):
        r = state.get(key)
        if r is not None:
            results.append(r)

    evidence_dict: dict[str, Evidence] = state.get("evidence", {}) or {}
    retry_count = int(state.get("retry_count", 0) or 0)

    # 1) 기계 검사
    machine_failures = machine_check(results, evidence_dict)
    machine_failed_keys = {
        (f.perspective, f.tech, f.item_key) for f in machine_failures
    }

    # 2) LLM 검토
    llm_failures = llm_review(
        results, evidence_dict, machine_failed_keys, model_name
    )

    all_failures = machine_failures + llm_failures
    failed_set = {(f.perspective, f.tech, f.item_key) for f in all_failures}

    passed_keys: list[str] = []
    for res in results:
        for item in res.items:
            key = (res.perspective, item.tech, item.item_key)
            if key not in failed_set:
                passed_keys.append(
                    f"{res.perspective.value}|{item.tech.value}|{item.item_key}"
                )

    needs_retry = bool(all_failures) and (retry_count < MAX_RETRIES)
    missing_questions = (
        [to_missing_question(f) for f in all_failures] if needs_retry else []
    )

    check = CheckResult(
        passed_keys=passed_keys,
        failed_items=all_failures,
        needs_retry=needs_retry,
        notes=(
            f"기계 실패 {len(machine_failures)} · LLM 실패 {len(llm_failures)}"
            f" · 재시도 {retry_count}/{MAX_RETRIES}"
        ),
    )
    return {
        "evidence_check": check,
        "missing_questions": missing_questions,
        "retry_count": retry_count,  # 실제 +1은 보완 노드가 담당
    }


__all__ = [
    "MAX_RETRIES",
    "DEFAULT_LABELS", "SPECIAL_LABELS", "allowed_labels", "is_unclear",
    "machine_check_item", "machine_check",
    "llm_review_item", "llm_review",
    "to_missing_question",
    "evidence_check",
]
