"""Unit tests for the shared web budget and its wiring into tools.web."""

from __future__ import annotations

import pytest

from skala_rag.tools import web
from skala_rag.tools.budget import BudgetExhausted, WebBudget


@pytest.fixture(autouse=True)
def _clear_budget():
    """Each test gets a clean budget slate (the module-level install is global)."""
    web.clear_web_budget()
    yield
    web.clear_web_budget()


def test_webbudget_counts_search_until_cap_then_refuses():
    budget = WebBudget(search_max=3, fetch_max=10)
    assert budget.try_search() is True
    assert budget.try_search() is True
    assert budget.try_search() is True
    assert budget.try_search() is False
    assert budget.report()["web_search_used"] == 3


def test_webbudget_counts_fetch_until_cap_then_refuses():
    budget = WebBudget(search_max=10, fetch_max=2)
    assert budget.try_fetch() is True
    assert budget.try_fetch() is True
    assert budget.try_fetch() is False


def test_webbudget_reset_zeroes_counts_and_optionally_updates_caps():
    budget = WebBudget(search_max=1, fetch_max=1)
    budget.try_search()
    budget.try_fetch()
    assert budget.report()["web_search_used"] == 1
    budget.reset(search_max=5, fetch_max=7)
    report = budget.report()
    assert report == {"web_search_used": 0, "web_search_max": 5, "fetch_used": 0, "fetch_max": 7}


def test_get_search_results_raises_budget_exhausted_when_cap_hit(monkeypatch):
    """When live search is called over the budget cap, BudgetExhausted is raised
    before any network traffic. We stub ``search_web`` so the test needs no
    external services; the stub should never be reached because the budget
    check runs first on the exhausted call."""
    budget = WebBudget(search_max=1, fetch_max=10)
    web.install_web_budget(budget)

    call_count = {"n": 0}

    def _fake_search_web(query, max_results):
        call_count["n"] += 1
        return [{"url": "https://example.org/x", "title": "x", "content": "..."}]

    monkeypatch.setattr(web, "search_web", _fake_search_web)
    monkeypatch.setattr(web, "save_search_cache", lambda query, hits, max_results, cache_dir: hits)

    web.get_search_results("first", max_results=1, mode="live")
    with pytest.raises(BudgetExhausted):
        web.get_search_results("second", max_results=1, mode="live")
    # The second call never reached the network stub.
    assert call_count["n"] == 1


def test_replay_mode_does_not_consume_budget(monkeypatch, tmp_path):
    """Replay reads a local cache; it must not count against the live budget."""
    budget = WebBudget(search_max=0, fetch_max=0)
    web.install_web_budget(budget)

    monkeypatch.setattr(
        web,
        "load_search_cache",
        lambda query, max_results, cache_dir: [{"url": "https://cached", "title": "c", "content": "..."}],
    )

    results = web.get_search_results("cached query", max_results=1, mode="replay", cache_dir=tmp_path)
    assert results and results[0]["url"] == "https://cached"
    assert budget.report()["web_search_used"] == 0
