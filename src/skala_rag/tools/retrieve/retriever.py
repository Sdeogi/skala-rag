"""`retrieve_papers` 검색 도구 (설계서 B.6).

기술명으로 필터링해 FAISS에서 상위 8개를 가져온 뒤 evidence_id 기준 중복을 제거하고
상위 5개를 반환한다. 결과가 비어 있고 `query_en`이 주어지면 그 질의로 한 번 더 검색한다
(설계서 B.4: "한국어 질문으로 근거가 잡히지 않으면 기술명과 핵심 용어를 살린 영어 질문으로
한 번 다시 검색").
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from langchain_community.vectorstores import FAISS
from langchain_core.tools import tool

from .embeddings import E5Embeddings
from .ingest import DEFAULT_INDEX_DIR

CANDIDATE_K = 8
DEFAULT_TOP_K = 5


@dataclass
class RetrievedChunk:
    evidence_id: str
    source_id: str
    tech_name: str
    page: int
    section: str
    text: str = field(repr=False)


@lru_cache(maxsize=1)
def _load_vectorstore(index_dir: str = DEFAULT_INDEX_DIR) -> FAISS:
    index_path = Path(index_dir)
    if not (index_path / "index.faiss").exists():
        raise FileNotFoundError(
            f"{index_dir} 에 FAISS 인덱스가 없습니다. "
            "먼저 `python scripts/build_index.py` (또는 "
            "`skala_rag.tools.retrieve.ingest.build_index()`)를 실행하세요."
        )
    return FAISS.load_local(
        str(index_path), E5Embeddings(), allow_dangerous_deserialization=True
    )


def _search(query: str, tech_name: str, index_dir: str) -> list[RetrievedChunk]:
    vectorstore = _load_vectorstore(index_dir)
    hits = vectorstore.similarity_search(query, k=CANDIDATE_K, filter={"tech_name": tech_name})
    seen: set[str] = set()
    results: list[RetrievedChunk] = []
    for doc in hits:
        evidence_id = doc.metadata["evidence_id"]
        if evidence_id in seen:
            continue
        seen.add(evidence_id)
        results.append(
            RetrievedChunk(
                evidence_id=evidence_id,
                source_id=doc.metadata["source_id"],
                tech_name=doc.metadata["tech_name"],
                page=doc.metadata["page"],
                section=doc.metadata["section"],
                text=doc.page_content,
            )
        )
    return results


def retrieve_papers(
    query: str,
    tech_name: str,
    k: int = DEFAULT_TOP_K,
    query_en: str | None = None,
    index_dir: str = DEFAULT_INDEX_DIR,
) -> list[RetrievedChunk]:
    """`query` + `tech_name` 필터로 논문 청크를 검색해 상위 `k`개를 반환한다."""
    results = _search(query, tech_name, index_dir)
    if not results and query_en:
        results = _search(query_en, tech_name, index_dir)
    return results[:k]


@tool
def retrieve_papers_tool(query: str, tech_name: str, k: int = DEFAULT_TOP_K) -> list[dict]:
    """두 기술(KIVI, InfiniGen) 논문에서 질의와 관련된 근거 청크를 검색한다.

    Args:
        query: 검색할 질문(한국어 또는 영어).
        tech_name: "KIVI" 또는 "InfiniGen".
        k: 반환할 최대 청크 수(기본 5).
    """
    chunks = retrieve_papers(query, tech_name, k=k)
    return [
        {
            "evidence_id": c.evidence_id,
            "source_id": c.source_id,
            "tech_name": c.tech_name,
            "page": c.page,
            "section": c.section,
            "text": c.text,
        }
        for c in chunks
    ]
