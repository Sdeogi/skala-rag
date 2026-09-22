from skala_rag.graph.state import aggregate_metrics, collect_conflicts, merge_by_id


def test_merge_by_id_keeps_first_and_records_conflict():
    merged = merge_by_id({"x": {"v": 1}}, {"x": {"v": 2}, "y": {"v": 3}})
    assert merged["x"]["v"] == 1
    assert merged["x"]["conflicts"] == [{"v": 2}]
    assert merged["y"] == {"v": 3}


def test_merge_by_id_ignores_volatile_fields_and_identical_records():
    first = {"title": "T", "retrieved_at": "t1", "content_hash": "a"}
    second = {"title": "T", "retrieved_at": "t2", "content_hash": "b"}
    merged = merge_by_id({"s": first}, {"s": second})
    assert "conflicts" not in merged["s"]
    assert merge_by_id({"s": first}, {"s": dict(first)})["s"] == first


def test_collect_conflicts_lists_differing_fields():
    state = {"sources": merge_by_id({"s": {"title": "A", "url": "u"}}, {"s": {"title": "B", "url": "u"}}), "evidence": {}, "errors": {}}
    assert collect_conflicts(state) == [{"collection": "sources", "id": "s", "variants": 1, "differing_fields": ["title"]}]


def test_aggregate_metrics_sums_numbers_per_node_and_overall():
    events = [
        {"node": "market", "web_search_calls": 3, "tokens": {"input_tokens": 10}},
        {"node": "retry", "repairs": 2},
        {"node": "market", "web_search_calls": 2, "tokens": {"input_tokens": 5}, "purpose": "text is ignored"},
    ]
    summary = aggregate_metrics(events)
    assert summary["event_count"] == 3
    assert summary["by_node"]["market"] == {"web_search_calls": 5, "tokens": {"input_tokens": 15}}
    assert summary["totals"]["web_search_calls"] == 5 and summary["totals"]["repairs"] == 2
