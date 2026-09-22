"""Shared State and collision-safe reducers.

Nodes return partial updates. Perspective results have independent keys so the
parallel superstep never writes the same key twice. ID-keyed collections merge
with ``merge_by_id``: the first record wins, differing later records are kept
as ``conflicts`` on the retained record (design D.1) instead of aborting the run.
``metrics`` is an append-only event list so counters never collide.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Annotated, Any, TypedDict

logger = logging.getLogger(__name__)

# Fields that legitimately differ between two collections of the same record.
VOLATILE_FIELDS = frozenset({"retrieved_at", "collected_at", "fetched_at", "accessed_at", "content_hash"})
CONFLICT_KEY = "conflicts"


def _stable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: item for key, item in value.items() if key not in VOLATILE_FIELDS and key != CONFLICT_KEY}
    return value


def merge_by_id(left: dict[str, Any] | None, right: dict[str, Any] | None) -> dict[str, Any]:
    """Merge an ID map. Keep the first record and record conflicting variants."""
    merged = dict(left or {})
    for identifier, value in (right or {}).items():
        if identifier not in merged:
            merged[identifier] = value
            continue
        current = merged[identifier]
        if _stable(current) == _stable(value):
            continue
        if isinstance(current, Mapping):
            record = dict(current)
            variants = list(record.get(CONFLICT_KEY, []))
            variants.append(_stable(value) if isinstance(value, Mapping) else value)
            record[CONFLICT_KEY] = variants
            merged[identifier] = record
        logger.warning("Conflicting record ID %s: kept the first value, recorded the variant", identifier)
    return merged


def add_events(left: list[Any] | None, right: list[Any] | None) -> list[Any]:
    return list(left or []) + list(right or [])


def metric_event(node: str, **fields: Any) -> dict[str, Any]:
    """Build one metrics event. Numeric fields are summed by ``aggregate_metrics``."""
    return {"node": node, **fields}


def _add_numbers(target: dict[str, Any], source: Mapping[str, Any]) -> None:
    for key, value in source.items():
        if key == "node" or isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            target[key] = target.get(key, 0) + value
        elif isinstance(value, Mapping):
            child = target.setdefault(key, {})
            if isinstance(child, dict):
                _add_numbers(child, value)


def aggregate_metrics(events: list[Any] | None) -> dict[str, Any]:
    """Sum numeric leaves per node and overall (tool calls, tokens, elapsed time)."""
    by_node: dict[str, dict[str, Any]] = {}
    totals: dict[str, Any] = {}
    count = 0
    for event in events or []:
        if not isinstance(event, Mapping):
            continue
        count += 1
        node = str(event.get("node", "unknown"))
        _add_numbers(by_node.setdefault(node, {}), event)
        _add_numbers(totals, event)
    return {"event_count": count, "by_node": by_node, "totals": totals}


def collect_conflicts(state: Mapping[str, Any]) -> list[dict[str, Any]]:
    """List records that received conflicting variants during merging."""
    found: list[dict[str, Any]] = []
    for collection in ("sources", "evidence", "errors"):
        for identifier, record in (state.get(collection) or {}).items():
            if not isinstance(record, Mapping) or not record.get(CONFLICT_KEY):
                continue
            variants = record[CONFLICT_KEY]
            fields = sorted(
                {
                    key
                    for variant in variants
                    if isinstance(variant, Mapping)
                    for key in variant
                    if record.get(key) != variant.get(key)
                }
            )
            found.append({"collection": collection, "id": identifier, "variants": len(variants), "differing_fields": fields})
    return found


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
    missing_questions: list[dict[str, Any]]
    retry_count: int
    synthesis: dict[str, Any]
    report: dict[str, Any]
    artifacts: dict[str, str]
    metrics: Annotated[list[dict[str, Any]], add_events]
    started_at: str
