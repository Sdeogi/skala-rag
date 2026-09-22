"""Evidence-bound cross-perspective synthesis without scores or rankings."""

from __future__ import annotations

from itertools import combinations
import re
from typing import Any

from skala_rag.graph.state import GraphState


FAVORABLE = {"직접 자료 있음", "상용 서비스 적용 확인", "주류 프레임워크 통합", "활발", "지지", "적용 가능 보고", "낮음 보고"}
CAUTIOUS = {"관련 시장 자료만 있음", "연구 재현 수준", "일부 있음", "우려", "조건부 보고", "높음 보고"}
RELATED_FIELDS = {
    frozenset({("market", "adoption"), ("stakeholder", "adopter_view")}),
    frozenset({("market", "adoption"), ("domain", "integration")}),
    frozenset({("market", "adoption"), ("trl", "trl")}),
    frozenset({("market", "ecosystem"), ("stakeholder", "adopter_view")}),
    frozenset({("domain", "memory"), ("stakeholder", "competitor_view")}),
    frozenset({("domain", "memory"), ("stakeholder", "adopter_view")}),
    frozenset({("domain", "quality"), ("stakeholder", "adopter_view")}),
    frozenset({("domain", "latency"), ("stakeholder", "adopter_view")}),
    frozenset({("domain", "throughput"), ("market", "adoption")}),
    frozenset({("domain", "integration"), ("stakeholder", "adopter_view")}),
}


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


def synthesize(state: GraphState) -> dict[str, Any]:
    """Compare supported judgments for each technology, retaining conditions."""
    evidence = state.get("evidence", {})
    agreements: list[dict[str, Any]] = []
    conflicts: list[dict[str, Any]] = []
    checks = state.get("evidence_check", {}).get("items")
    passed_items = {(item["perspective"], item["technology"], item["field"]) for item in checks or [] if item.get("passed")}
    for technology in state["run_config"]["technologies"]:
        supported = []
        for name in ("market", "stakeholder", "domain", "trl"):
            result = state.get(f"{name}_analysis") or {}
            for field, judgment in result.get("technologies", {}).get(technology, {}).items():
                if not isinstance(judgment, dict):
                    continue
                if checks is not None and (name, technology, field) not in passed_items:
                    continue
                ids = [i for i in judgment.get("evidence_ids", []) if i in evidence and evidence[i].get("technology") in (None, technology)]
                stance = _stance(str(judgment.get("label", "")))
                if ids and stance:
                    supported.append({"perspective": name, "field": field, "label": judgment["label"], "reason": judgment.get("reason", ""), "conditions": judgment.get("conditions", ""), "evidence_ids": ids, "stance": stance})
        for first, second in combinations(supported, 2):
            if frozenset({(first["perspective"], first["field"]), (second["perspective"], second["field"])}) not in RELATED_FIELDS:
                continue
            item = {
                "technology": technology,
                "first": {k: v for k, v in first.items() if k != "stance"},
                "second": {k: v for k, v in second.items() if k != "stance"},
                "reason": f"{first['perspective']}의 {first['label']}와 {second['perspective']}의 {second['label']} 판정을 서로 다른 조건에서 읽어야 한다.",
                "uncertainty": "두 근거의 실험 또는 공개 시점이 다르면 직접 비교할 수 없음",
            }
            (agreements if first["stance"] == second["stance"] else conflicts).append(item)
    limitations = [f"{q['technology']} {q['perspective']}/{q['field']}: 근거 미확인" for q in state.get("missing_questions", [])]
    return {"agreements": agreements, "conflicts": conflicts, "limitations": limitations, "generation_mode": "deterministic"}
