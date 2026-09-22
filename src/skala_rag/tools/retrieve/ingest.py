"""논문 PDF -> 파싱 -> 청킹 -> 임베딩 -> FAISS 색인 파이프라인."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from langchain_community.vectorstores import FAISS

from .chunking import CHUNK_OVERLAP_TOKENS, CHUNK_SIZE_TOKENS, chunk_pages
from .embeddings import MODEL_NAME, E5Embeddings
from .parsing import extract_pdf_pages

DEFAULT_PAPERS_DIR = "data/papers"
DEFAULT_INDEX_DIR = "indexes"


def _load_manifest(papers_dir: Path) -> list[dict]:
    manifest_path = papers_dir / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(
            f"{manifest_path} 가 없습니다. data/papers/manifest.json에 논문 목록을 먼저 등록하세요."
        )
    return json.loads(manifest_path.read_text(encoding="utf-8"))["papers"]


def build_index(papers_dir: str = DEFAULT_PAPERS_DIR, index_dir: str = DEFAULT_INDEX_DIR) -> None:
    """`papers_dir`의 논문들로 FAISS 인덱스를 새로 만들어 `index_dir`에 저장한다."""
    papers_dir_path = Path(papers_dir)
    index_dir_path = Path(index_dir)
    index_dir_path.mkdir(parents=True, exist_ok=True)

    papers = _load_manifest(papers_dir_path)
    all_documents = []
    for paper in papers:
        pdf_path = papers_dir_path / paper["filename"]
        source_id = paper["tech_name"]
        page_blocks = extract_pdf_pages(str(pdf_path), tech_name=paper["tech_name"])
        documents = chunk_pages(page_blocks, tech_name=paper["tech_name"], source_id=source_id)
        if not documents:
            raise ValueError(f"{pdf_path} 에서 추출된 청크가 없습니다.")
        all_documents.extend(documents)

    embeddings = E5Embeddings()
    vectorstore = FAISS.from_documents(all_documents, embeddings)
    vectorstore.save_local(str(index_dir_path))

    build_manifest = {
        "embedding_model": MODEL_NAME,
        "chunk_size_tokens": CHUNK_SIZE_TOKENS,
        "chunk_overlap_tokens": CHUNK_OVERLAP_TOKENS,
        "num_chunks": len(all_documents),
        "num_papers": len(papers),
        "tech_names": sorted({p["tech_name"] for p in papers}),
        "built_at": datetime.now(timezone.utc).isoformat(),
    }
    (index_dir_path / "build_manifest.json").write_text(
        json.dumps(build_manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )


if __name__ == "__main__":
    build_index()
