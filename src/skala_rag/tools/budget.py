"""Shared web budget for the perspective services.

A single ``WebBudget`` instance is created in ``integration.services.create_services``
and installed onto ``tools.web`` so the search/fetch helpers can refuse to call
the external Tavily API once the ``run_config["budget"]`` caps are reached. All
consumers share the same counters so the three perspective nodes running in
parallel still see one per-run total — not three independent per-node totals.

Only live mode consumes budget: replay reads the local cache and never hits the
network.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field

from skala_rag.config import DEFAULT_FETCH_MAX, DEFAULT_WEB_SEARCH_MAX


class BudgetExhausted(RuntimeError):
    """Raised when the per-run web search / fetch cap has been reached.

    Agents and the evidence collector catch this and surface it as a non-fatal
    error on the perspective's ``errors`` map, leaving the affected judgment as
    ``미확인``. The run is not aborted — subsequent (already-funded) calls still
    proceed.
    """


@dataclass
class WebBudget:
    """Thread-safe counters for web_search / fetch calls within one run."""

    search_max: int = DEFAULT_WEB_SEARCH_MAX
    fetch_max: int = DEFAULT_FETCH_MAX
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False, compare=False)
    search_used: int = 0
    fetch_used: int = 0

    def reset(self, *, search_max: int | None = None, fetch_max: int | None = None) -> None:
        """Zero the counters and optionally update caps (e.g. from ``run_config``)."""
        with self._lock:
            if search_max is not None:
                self.search_max = max(0, int(search_max))
            if fetch_max is not None:
                self.fetch_max = max(0, int(fetch_max))
            self.search_used = 0
            self.fetch_used = 0

    def try_search(self) -> bool:
        with self._lock:
            if self.search_used >= self.search_max:
                return False
            self.search_used += 1
            return True

    def try_fetch(self) -> bool:
        with self._lock:
            if self.fetch_used >= self.fetch_max:
                return False
            self.fetch_used += 1
            return True

    def report(self) -> dict[str, int]:
        with self._lock:
            return {
                "web_search_used": self.search_used,
                "web_search_max": self.search_max,
                "fetch_used": self.fetch_used,
                "fetch_max": self.fetch_max,
            }


__all__ = ["WebBudget", "BudgetExhausted"]
