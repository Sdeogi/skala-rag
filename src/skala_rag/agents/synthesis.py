"""Evidence-bound cross-perspective synthesis without scores or rankings (design C.6).

The deterministic version builds agreement/conflict pairs from verified
judgments of related rubric items and writes each pair's reason and remaining
uncertainty from the judgments' own reasons and conditions. The live-mode agent
in ``llm_output`` lets the LLM rewrite those two texts under strict validation.
"""

from __future__ import annotations

import re
from itertools import combinations
from typing import Any

from skala_rag.graph.schemas import FIELD_TITLES, PERSPECTIVE_TITLES, PERSPECTIVES
from skala_rag.graph.state import GraphState

FAVORABLE = {"직접 자료 있음", "상용 서비스 적용 확인", "주류 프레임워크 통합", "활발", "지지", "적용 가능 보고", "낮음 보고"}
CAUTIOUS = {"관련 시장 자료만 있음", "연구 재현 수준", "일부 있음", "우려", "조건부 보고", "높음 보고"}
# Rubric item pairs whose judgments speak about the same question from two perspectives.
RELATED_FIELDS = {
    frozenset({("market", "adoption"), ("stakeholder", "adopter_view")}),
    frozenset({("market", "adoption"), ("domain", "integration")}),
    frozenset({("market", "adoption"), ("trl", "trl")}),
    frozenset({("market", "ecosystem"), ("stakeholder", "adopter_view")}),
    frozenset({("market", "ecosystem"), ("trl", "trl")}),
    frozenset({("domain", "memory"), ("stakeholder", "competitor_view")}),
    frozenset({("domain", "memory"), ("stakeholder", "adopter_view")}),
    frozenset({("domain", "quality"), ("stakeholder", "adopter_view")}),
    frozenset({("domain", "quality"), ("stakeholder", "competitor_view")}),
    frozenset({("domain", "latency"), ("stakeholder", "adopter_view")}),
    frozenset({("domain", "throughput"), ("market", "adoption")}),
    frozenset({("domain", "integration"), ("stakeholder", "adopter_view")}),
    frozenset({("domain", "integration"), ("trl", "trl")}),
    frozenset({("stakeholder", "adopter_view"), ("trl", "trl")}),
}
REASON_LIMIT = 160


def _stance(label: str) -> str | None:
    if label.startswith("TRL"):
        stages = [int(value) for value in re.findall(r"[1-9]", label)]
        if stages and max(stages) <= 4:
            return "cautious"
        if stages and min(stages) >= 7:
            return "favorable"
        return None
    if label in FAVORABLE:
        return "favorable"
    if label in CAUTIOUS:
        return "cautious"
    return None


def _clip(text: Any, limit: int = REASON_LIMIT) -> str:
    value = " ".join(str(text or "").split())
    return value if len(value) <= limit else value[: limit - 1] + "…"


def _title(ref: dict[str, Any]) -> str:
    return f"{PERSPECTIVE_TITLES.get(ref['perspective'], ref['perspective'])} 관점의 {FIELD_TITLES.get(ref['field'], ref['field'])}"


def describe_pair(kind: str, first: dict[str, Any], second: dict[str, Any]) -> tuple[str, str]:
    """Deterministic reason and uncertainty text built only from the judgments."""
    reason_first = _clip(first.get("reason")) or "이유 미기재"
    reason_second = _clip(second.get("reason")) or "이유 미기재"
    if kind == "conflict":
        reason = (
            f"{_title(first)}은 '{reason_first}'를 근거로 '{first['label']}'로 판정한 반면, "
            f"{_title(second)}은 '{reason_second}'를 근거로 '{second['label']}'로 판정해 방향이 엇갈린다."
        )
    else:
        reason = (
            f"{_title(first)}('{first['label']}')과 {_title(second)}('{second['label']}')이 같은 방향을 가리킨다. "
            f"전자는 '{reason_first}', 후자는 '{reason_second}'를 근거로 든다."
        )
    condition_first = _clip(first.get("conditions")) or "조건 미기재"
    condition_second = _clip(second.get("conditions")) or "조건 미기재"
    uncertainty = (
        f"두 판정의 성립 조건이 각각 '{condition_first}', '{condition_second}'이며, "
        "근거의 실험 조건과 공개 시점이 같은지는 확인되지 않아 직접 비교에는 한계가 있다."
    )
    return reason, uncertainty


def _supported_judgments(state: GraphState, technology: str) -> list[dict[str, Any]]:
    evidence = state.get("evidence") or {}
    checks = (state.get("evidence_check") or {}).get("items")
    passed = {(item["perspective"], item["technology"], item["field"]) for item in checks or [] if item.get("passed")}
    supported: list[dict[str, Any]] = []
    for name in PERSPECTIVES:
        result = state.get(f"{name}_analysis") or {}
        for field, judgment in (result.get("technologies") or {}).get(technology, {}).items():
            if not isinstance(judgment, dict):
                continue
            if checks is not None and (name, technology, field) not in passed:
                continue
            ids = [
                identifier
                for identifier in judgment.get("evidence_ids", [])
                if identifier in evidence and evidence[identifier].get("technology") in (None, technology)
            ]
            label = str(judgment.get("label", "") or "")
            stance = _stance(label)
            if ids and stance:
                supported.append(
                    {
                        "perspective": name,
                        "field": field,
                        "label": label,
                        "reason": judgment.get("reason", ""),
                        "conditions": judgment.get("conditions", ""),
                        "evidence_ids": ids,
                        "stance": stance,
                    }
                )
    return supported


def candidate_pairs(state: GraphState) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    agreements: list[dict[str, Any]] = []
    conflicts: list[dict[str, Any]] = []
    for technology in state["run_config"]["technologies"]:
        supported = _supported_judgments(state, technology)
        for first, second in combinations(supported, 2):
            if frozenset({(first["perspective"], first["field"]), (second["perspective"], second["field"])}) not in RELATED_FIELDS:
                continue
            kind = "agreement" if first["stance"] == second["stance"] else "conflict"
            ref_first = {key: value for key, value in first.items() if key != "stance"}
            ref_second = {key: value for key, value in second.items() if key != "stance"}
            reason, uncertainty = describe_pair(kind, ref_first, ref_second)
            item = {
                "technology": technology,
                "first": ref_first,
                "second": ref_second,
                "reason": reason,
                "uncertainty": uncertainty,
                "generation": "deterministic",
            }
            (agreements if kind == "agreement" else conflicts).append(item)
    return agreements, conflicts


def limitation_lines(state: GraphState) -> list[str]:
    lines = []
    for question in state.get("missing_questions", []) or []:
        reasons = ", ".join(question.get("reasons", [])) if question.get("reasons") else "근거 미확인"
        line = (
            f"{question['technology']} {PERSPECTIVE_TITLES.get(question['perspective'], question['perspective'])} 관점 "
            f"'{FIELD_TITLES.get(question['field'], question['field'])}': 근거 미확인 ({reasons})"
        )
        if question.get("review_reason"):
            line += f" — 검토 LLM: {_clip(question['review_reason'], 200)}"
        lines.append(line)
    return lines


def synthesize(state: GraphState) -> dict[str, Any]:
    """Compare supported judgments for each technology, retaining conditions."""
    agreements, conflicts = candidate_pairs(state)
    return {
        "agreements": agreements,
        "conflicts": conflicts,
        "limitations": limitation_lines(state),
        "generation_mode": "deterministic",
    }
