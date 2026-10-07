"""Rework helpers: classify request reasons and build fresh search queries.

A rework request (as passed in ``state["rework_requests"]``) is a dict shaped like::

    {
      "perspective": "market",
      "technology": "InfiniGen",
      "field": "adoption",
      "reasons": ["unsupported_claim"],
      "review_reason": "근거가 업계 일반 평가일 뿐 ...",
      "question": "...",
      "attempt": 1,
    }

The ``reasons`` list uses the codes emitted by ``graph.evidence_check``:
``missing_item``, ``invalid_label``, ``not_found_label``, ``missing_evidence``,
``unknown_evidence``, ``wrong_technology``, ``unknown_source``,
``unverified_evidence``, ``unsupported_claim``.

Two groups:

- **research**: the previous searches did not find usable evidence, so we must
  issue new queries. Covers ``not_found_label``, ``missing_evidence``,
  ``missing_item``, ``unsupported_claim``.
- **rejudge**: the evidence is there but the label/attribution is wrong; we can
  judge again without searching. Covers ``wrong_technology``, ``unknown_evidence``,
  ``unknown_source``, ``unverified_evidence``, ``invalid_label``.

When both kinds of reasons appear on one request we treat it as research — the
rejudge pass can still happen on the collected result.
"""

from __future__ import annotations

import re
from typing import Any

RESEARCH_REASONS: frozenset[str] = frozenset(
    {"not_found_label", "missing_evidence", "missing_item", "unsupported_claim"}
)
REJUDGE_REASONS: frozenset[str] = frozenset(
    {"wrong_technology", "unknown_evidence", "unknown_source", "unverified_evidence", "invalid_label"}
)

_STOPWORDS: frozenset[str] = frozenset(
    {
        # English
        "the", "and", "that", "this", "with", "from", "have", "has", "had",
        "but", "for", "are", "was", "were", "is", "be", "an", "a", "of", "to",
        "in", "on", "or", "it", "as", "by",
        # Korean function words / vague terms
        "이", "그", "저", "것", "수", "및", "등", "에", "을", "를", "는", "의", "가",
        "이다", "있다", "없다", "않음", "없음", "있음", "하다", "하는", "되는",
        "무엇", "어떤", "어느", "있는가", "있나", "뭔가", "뭐가",
    }
)


def needs_research(request: dict[str, Any]) -> bool:
    """True when the request wants a fresh web/RAG search.

    Empty ``reasons`` is treated as research by default, since we have no signal
    that re-judging alone would help.
    """
    reasons = {str(reason) for reason in (request.get("reasons") or [])}
    return not reasons or bool(reasons & RESEARCH_REASONS)


def needs_rejudge(request: dict[str, Any]) -> bool:
    """True when the request can be satisfied by re-judging existing evidence only."""
    reasons = {str(reason) for reason in (request.get("reasons") or [])}
    return bool(reasons) and not (reasons & RESEARCH_REASONS)


def _tokenize(text: str) -> list[str]:
    """Pick content words (Korean 2+ chars, Latin/digits 2+ chars) from mixed text."""
    words = re.findall(r"[A-Za-z0-9][A-Za-z0-9_\-]*|[가-힣]{2,}", text or "")
    kept: list[str] = []
    for word in words:
        if word.lower() in _STOPWORDS:
            continue
        if word not in kept:
            kept.append(word)
    return kept


def build_rework_queries(
    request: dict[str, Any],
    prior_queries: list[str],
    *,
    paper_id: str | None = None,
    max_queries: int = 3,
) -> list[str]:
    """Produce 1~``max_queries`` fresh search queries for a research-type request.

    The variants are rule-based:

    - ``unsupported_claim``: narrow with a quoted technology name, the paper ID
      (when known) and keywords lifted from ``review_reason``.
    - ``not_found_label`` / ``missing_evidence`` / ``missing_item``: broaden by
      pairing the field name with ``limitation`` / ``issue`` counter-terms and by
      distilling the ``question`` text into a terse query.

    Queries already in ``prior_queries`` (case-insensitive) are dropped so each
    rework round genuinely issues different searches.
    """
    technology = str(request.get("technology") or "").strip()
    field = str(request.get("field") or "").strip()
    reasons = {str(reason) for reason in (request.get("reasons") or [])}
    review_reason = str(request.get("review_reason") or "").strip()
    question = str(request.get("question") or "").strip()

    seen = {str(query).strip().lower() for query in prior_queries if query}
    out: list[str] = []

    def _add(query: str) -> None:
        clean = " ".join(query.split()).strip()
        if not clean:
            return
        key = clean.lower()
        if key in seen or clean in out:
            return
        out.append(clean)
        seen.add(key)

    if "unsupported_claim" in reasons:
        if paper_id:
            _add(f'"{technology}" "{paper_id}" {field}'.strip())
        if review_reason:
            keywords = _tokenize(review_reason)[:4]
            if keywords:
                _add(f'"{technology}" {" ".join(keywords)}')
        _add(f'"{technology}" {field} limitation issue')

    if not reasons or reasons & {"not_found_label", "missing_evidence", "missing_item"}:
        if question:
            keywords = _tokenize(question)[:6]
            if keywords and technology and technology not in keywords:
                keywords.insert(0, technology)
            if keywords:
                _add(" ".join(keywords))
        _add(f"{technology} {field} report evidence")
        _add(f"{technology} {field} limitation issue criticism")

    # If none of the branches contributed (e.g. only rejudge reasons slipped in),
    # fall back to a generic broadening query so the caller always has one option.
    if not out and technology and field:
        _add(f"{technology} {field} evidence")

    return out[:max_queries]


__all__ = [
    "RESEARCH_REASONS",
    "REJUDGE_REASONS",
    "needs_research",
    "needs_rejudge",
    "build_rework_queries",
]
