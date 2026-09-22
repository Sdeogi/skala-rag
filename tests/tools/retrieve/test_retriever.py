from skala_rag.tools.retrieve.retriever import DEFAULT_TOP_K, retrieve_papers


def test_retrieve_papers_filters_by_tech_and_respects_k(built_index_dir):
    results = retrieve_papers(
        "이 기술은 KV 캐시를 어떻게 압축하는가?", "KIVI", k=5, index_dir=built_index_dir
    )
    assert 0 < len(results) <= DEFAULT_TOP_K
    assert all(r.tech_name == "KIVI" for r in results)
    assert all(r.text.strip() for r in results)


def test_retrieve_papers_dedupes_by_evidence_id(built_index_dir):
    results = retrieve_papers("KV cache quantization", "KIVI", k=5, index_dir=built_index_dir)
    ids = [r.evidence_id for r in results]
    assert len(ids) == len(set(ids))


def test_retrieve_papers_korean_query_matches_english_paper(built_index_dir):
    # multilingual-e5-small은 교차언어 검색을 지원해야 한다(설계서 B.5).
    results = retrieve_papers(
        "InfiniGen은 어떻게 중요한 KV만 미리 가져오는가?",
        "InfiniGen",
        k=5,
        index_dir=built_index_dir,
    )
    assert len(results) > 0
    assert all(r.tech_name == "InfiniGen" for r in results)


def test_retrieve_papers_english_fallback_used_when_korean_finds_nothing(built_index_dir, monkeypatch):
    calls = []
    from skala_rag.tools.retrieve import retriever as retriever_module

    original_search = retriever_module._search

    def fake_search(query, tech_name, index_dir):
        calls.append(query)
        if query == "존재하지-않는-무의미한-한국어-질의-zzz":
            return []
        return original_search(query, tech_name, index_dir)

    monkeypatch.setattr(retriever_module, "_search", fake_search)

    results = retriever_module.retrieve_papers(
        "존재하지-않는-무의미한-한국어-질의-zzz",
        "KIVI",
        k=5,
        query_en="KIVI KV cache quantization",
        index_dir=built_index_dir,
    )
    assert calls == ["존재하지-않는-무의미한-한국어-질의-zzz", "KIVI KV cache quantization"]
    assert len(results) > 0
