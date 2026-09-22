"""Shared State and collision-safe reducers.

Nodes return partial updates. Perspective results have independent keys to make
parallel updates safe; shared dictionaries merge by stable identifier.
"""

from __future__ import annotations

from typing import Annotated, Any, TypedDict


def merge_by_id(left: dict[str, Any] | None, right: dict[str, Any] | None) -> dict[str, Any]:
    """Merge an ID map without silently replacing contradictory records."""
    merged = dict(left or {})
    for identifier, value in (right or {}).items():
        if identifier in merged and merged[identifier] != value:
            raise ValueError(f"Conflicting record ID: {identifier}")
        merged[identifier] = value
    return merged


class GraphState(TypedDict, total=False):
    run_config: dict[str, Any]
    sources: Annotated[dict[str, dict[str, Any]], merge_by_id]
    evidence: Annotated[dict[str, dict[str, Any]], merge_by_id]
    errors: Annotated[dict[str, dict[str, Any]], merge_by_id]
    technical_findings: dict[str, Any]
    market_analysis: dict[str, Any]
    stakeholder_analysis: dict[str, Any]
    domain_analysis: dict[str, Any]
    trl_analysis: dict[str, Any]
    evidence_check: dict[str, Any]
    missing_questions: list[dict[str, str]]
    retry_count: int
    synthesis: dict[str, Any]
    report: dict[str, Any]
    artifacts: dict[str, str]
    metrics: Annotated[dict[str, Any], merge_by_id]
    started_at: str
