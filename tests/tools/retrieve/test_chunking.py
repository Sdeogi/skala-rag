from transformers import AutoTokenizer

from skala_rag.tools.retrieve.chunking import (
    CHUNK_SIZE_TOKENS,
    EMBEDDING_MODEL_NAME,
    chunk_pages,
)
from skala_rag.tools.retrieve.parsing import extract_pdf_pages

_tokenizer = AutoTokenizer.from_pretrained(EMBEDDING_MODEL_NAME)


def test_chunks_have_required_metadata():
    blocks = extract_pdf_pages("data/papers/kivi.pdf", "KIVI")
    documents = chunk_pages(blocks, tech_name="KIVI", source_id="KIVI")

    assert len(documents) > len(blocks)  # 여러 블록이 여러 청크로 쪼개짐
    for doc in documents:
        assert doc.page_content.strip()
        for key in ("evidence_id", "source_id", "tech_name", "page", "section"):
            assert key in doc.metadata
        assert doc.metadata["tech_name"] == "KIVI"


def test_evidence_ids_are_unique_and_deterministic():
    blocks = extract_pdf_pages("data/papers/kivi.pdf", "KIVI")
    docs_a = chunk_pages(blocks, tech_name="KIVI", source_id="KIVI")
    docs_b = chunk_pages(blocks, tech_name="KIVI", source_id="KIVI")

    ids_a = [d.metadata["evidence_id"] for d in docs_a]
    assert len(ids_a) == len(set(ids_a)), "evidence_id는 청크마다 고유해야 한다"
    assert ids_a == [d.metadata["evidence_id"] for d in docs_b], "재실행해도 같은 ID가 나와야 한다"


def test_chunk_token_length_roughly_respects_budget():
    blocks = extract_pdf_pages("data/papers/kivi.pdf", "KIVI")
    documents = chunk_pages(blocks, tech_name="KIVI", source_id="KIVI")

    # 표/수식이 많은 학술 PDF 특성상 약간의 초과는 허용하되, 목표치(350)를 크게 벗어나면 안 된다.
    for doc in documents:
        token_count = len(_tokenizer.encode(doc.page_content))
        assert token_count <= CHUNK_SIZE_TOKENS * 1.5
