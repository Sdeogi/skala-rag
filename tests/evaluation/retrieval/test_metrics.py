from skala_rag.evaluation.retrieval.metrics import (
    hit_at_k,
    hit_rate_at_k,
    mean_reciprocal_rank,
    reciprocal_rank_at_k,
)


def test_hit_at_k_true_when_expected_present():
    assert hit_at_k(["a", "b", "c"], {"c"}, k=5) is True


def test_hit_at_k_false_when_not_present_or_outside_k():
    assert hit_at_k(["a", "b", "c"], {"z"}, k=5) is False
    assert hit_at_k(["a", "b", "c", "d", "e", "f"], {"f"}, k=5) is False


def test_reciprocal_rank_at_k():
    assert reciprocal_rank_at_k(["a", "b", "c"], {"b"}, k=5) == 0.5
    assert reciprocal_rank_at_k(["a", "b", "c"], {"a"}, k=5) == 1.0
    assert reciprocal_rank_at_k(["a", "b", "c"], {"z"}, k=5) == 0.0


def test_hit_rate_at_k_aggregate():
    assert hit_rate_at_k([True, True, False, False]) == 0.5
    assert hit_rate_at_k([]) == 0.0


def test_mean_reciprocal_rank_aggregate():
    assert mean_reciprocal_rank([1.0, 0.5, 0.0, 0.0]) == 0.375
    assert mean_reciprocal_rank([]) == 0.0
