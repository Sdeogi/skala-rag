"""Retrieval 품질 지표: Hit Rate@k, MRR@k (설계서 E.3)."""

from __future__ import annotations


def hit_at_k(retrieved_ids: list[str], expected_ids: set[str], k: int = 5) -> bool:
    """상위 k개 안에 정답 근거가 하나라도 있으면 True."""
    return any(rid in expected_ids for rid in retrieved_ids[:k])


def reciprocal_rank_at_k(retrieved_ids: list[str], expected_ids: set[str], k: int = 5) -> float:
    """정답 근거가 처음 등장하는 순위의 역수. 없으면 0."""
    for rank, rid in enumerate(retrieved_ids[:k], start=1):
        if rid in expected_ids:
            return 1.0 / rank
    return 0.0


def hit_rate_at_k(per_question_hits: list[bool]) -> float:
    if not per_question_hits:
        return 0.0
    return sum(per_question_hits) / len(per_question_hits)


def mean_reciprocal_rank(per_question_rr: list[float]) -> float:
    if not per_question_rr:
        return 0.0
    return sum(per_question_rr) / len(per_question_rr)
