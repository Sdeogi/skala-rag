"""Deterministic rubric and evidence reference checks (design D.4).

Rule checks: every rubric item exists for both technologies, labels come from
the defined sets, evidence IDs exist, refer to the right technology and to a
known source, and are not ``unverified``. Semantic support is judged by the
review LLM supplied as ``semantic_review`` (``agents.review.LLMSemanticReviewer``
by default in live mode); C branch may inject its own reviewer.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from .schemas import FIELD_TITLES, LABELS, PERSPECTIVE_TITLES, is_valid_label
from .state import GraphState

RUBRICS = LABELS

SemanticReview = Callable[[str, str, str, Mapping[str, Any], list[Mapping[str, Any]]], bool]


class ReviewBudgetExceeded(RuntimeError):
    """Raised by a reviewer when its call budget is exhausted; treated as a warning."""


def check_evidence(state: GraphState, semantic_review: SemanticReview | None = None) -> dict[str, Any]:
    evidence = state.get("evidence") or {}
    sources = state.get("sources") or {}
    technologies = state["run_config"]["technologies"]
    missing: list[dict[str, Any]] = []
    checks: list[dict[str, Any]] = []
    review_errors = 0
    review_skipped = 0
    for perspective, fields in RUBRICS.items():
        result = state.get(f"{perspective}_analysis") or {}
        by_technology = result.get("technologies") or {}
        for technology in technologies:
            judgments = by_technology.get(technology) or {}
            for field in fields:
                judgment = judgments.get(field)
                problems: list[str] = []
                warnings: list[str] = []
                if not isinstance(judgment, Mapping):
                    problems.append("missing_item")
                    judgment = {}
                label = str(judgment.get("label", "") or "").strip()
                if not is_valid_label(perspective, field, label):
                    problems.append("invalid_label")
                ids = judgment.get("evidence_ids") or []
                if not isinstance(ids, list) or not ids:
                    problems.append("missing_evidence")
                    ids = []
                valid: list[Mapping[str, Any]] = []
                for identifier in ids:
                    item = evidence.get(identifier)
                    if item is None:
                        problems.append("unknown_evidence")
                    elif item.get("technology") not in (None, technology):
                        problems.append("wrong_technology")
                    elif item.get("source_id") not in sources:
                        problems.append("unknown_source")
                    elif item.get("claim_type") == "unverified":
                        problems.append("unverified_evidence")
                    else:
                        valid.append(item)
                if valid and semantic_review is not None and not problems:
                    try:
                        supported = semantic_review(perspective, technology, field, judgment, valid)
                    except ReviewBudgetExceeded:
                        warnings.append("semantic_review_skipped")
                        review_skipped += 1
                    except Exception:
                        warnings.append("semantic_review_error")
                        review_errors += 1
                    else:
                        if not supported:
                            problems.append("unsupported_claim")
                passed = not problems
                reasons = sorted(set(problems))
                checks.append(
                    {
                        "perspective": perspective,
                        "technology": technology,
                        "field": field,
                        "passed": passed,
                        "reasons": reasons,
                        "warnings": sorted(set(warnings)),
                    }
                )
                if not passed:
                    missing.append(
                        {
                            "perspective": perspective,
                            "technology": technology,
                            "field": field,
                            "question": (
                                f"{technology}의 {PERSPECTIVE_TITLES[perspective]} 관점 "
                                f"'{FIELD_TITLES[field]}' 판정을 뒷받침하는 원문 근거는 무엇인가?"
                            ),
                            "reasons": reasons,
                        }
                    )
    events: list[dict[str, Any]] = []
    drain = getattr(semantic_review, "drain_metrics", None)
    if callable(drain):
        events = list(drain())
    return {
        "evidence_check": {
            "passed": not missing,
            "items": checks,
            "semantic_review_enabled": semantic_review is not None,
            "semantic_review_errors": review_errors,
            "semantic_review_skipped": review_skipped,
            "semantic_review_calls": getattr(semantic_review, "calls", None),
        },
        "missing_questions": missing,
        "metrics": events,
    }
