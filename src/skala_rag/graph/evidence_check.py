"""Deterministic rubric and evidence reference checks.

Semantic entailment can be supplied by the evaluation branch through a callback.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from typing import Any

from .state import GraphState


RUBRICS: dict[str, dict[str, set[str] | None]] = {
    "market": {
        "market_size": {"직접 자료 있음", "관련 시장 자료만 있음", "미확인"},
        "adoption": {"상용 서비스 적용 확인", "주류 프레임워크 통합", "연구 재현 수준", "미확인"},
        "ecosystem": {"활발", "일부 있음", "미확인"},
    },
    "stakeholder": {
        "competitor_view": {"지지", "우려", "중립", "미확인"},
        "adopter_view": {"지지", "우려", "중립", "미확인"},
        "investor_view": {"지지", "우려", "중립", "미확인"},
    },
    "domain": {
        "memory": {"적용 가능 보고", "조건부 보고", "보고 없음"},
        "quality": {"적용 가능 보고", "조건부 보고", "보고 없음"},
        "latency": {"적용 가능 보고", "조건부 보고", "보고 없음"},
        "throughput": {"적용 가능 보고", "조건부 보고", "보고 없음"},
        "integration": {"낮음 보고", "높음 보고", "보고 없음"},
    },
    "trl": {"trl": None},
}

SemanticReview = Callable[[str, str, str, Mapping[str, Any], list[Mapping[str, Any]]], bool]


def check_evidence(state: GraphState, semantic_review: SemanticReview | None = None) -> dict[str, Any]:
    evidence = state.get("evidence", {})
    missing: list[dict[str, str]] = []
    checks: list[dict[str, Any]] = []
    technologies = state["run_config"]["technologies"]
    for perspective, fields in RUBRICS.items():
        result = state.get(f"{perspective}_analysis") or {}
        by_technology = result.get("technologies", {})
        for technology in technologies:
            judgments = by_technology.get(technology, {})
            for field, allowed in fields.items():
                judgment = judgments.get(field)
                problems: list[str] = []
                if not isinstance(judgment, Mapping):
                    problems.append("missing_item")
                    judgment = {}
                label = judgment.get("label", "")
                if allowed is None:
                    if not (re.fullmatch(r"TRL\s*[1-9](?:\s*(?:-|~|에서)\s*(?:TRL\s*)?[1-9])?", str(label)) or label == "미확인"):
                        problems.append("invalid_label")
                elif label not in allowed:
                    problems.append("invalid_label")
                ids = judgment.get("evidence_ids", [])
                if not isinstance(ids, list) or not ids:
                    problems.append("missing_evidence")
                    ids = []
                valid = []
                for identifier in ids:
                    item = evidence.get(identifier)
                    if item is None:
                        problems.append("unknown_evidence")
                    elif item.get("technology") not in (None, technology):
                        problems.append("wrong_technology")
                    elif item.get("source_id") not in state.get("sources", {}):
                        problems.append("unknown_source")
                    elif item.get("claim_type") == "unverified":
                        problems.append("unverified_evidence")
                    else:
                        valid.append(item)
                if valid and semantic_review is not None:
                    try:
                        if not semantic_review(perspective, technology, field, judgment, valid):
                            problems.append("unsupported_claim")
                    except Exception:
                        problems.append("semantic_review_error")
                passed = not problems
                checks.append({"perspective": perspective, "technology": technology, "field": field, "passed": passed, "reasons": sorted(set(problems))})
                if not passed:
                    missing.append({"perspective": perspective, "technology": technology, "field": field, "question": f"{technology}의 {perspective}/{field} 판정을 뒷받침하는 원문 근거는 무엇인가?"})
    return {
        "evidence_check": {"passed": not missing, "items": checks, "semantic_review_enabled": semantic_review is not None},
        "missing_questions": missing,
    }
