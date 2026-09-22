"""파싱된 페이지 블록을 임베딩 모델 토큰 기준 청크로 분할한다.

설계서 B.4: 페이지와 절 정보를 유지한 채 약 350토큰 길이, 50토큰 겹침으로 분할.
새 스플리터를 직접 구현하지 않고 `langchain_text_splitters.RecursiveCharacterTextSplitter`를
e5-small 토크나이저 기준으로 재사용한다(ai-service의 기존 RAG 노트북들과 동일한 라이브러리 조합).
"""

from __future__ import annotations

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from transformers import AutoTokenizer

from .parsing import PageBlock

EMBEDDING_MODEL_NAME = "intfloat/multilingual-e5-small"
CHUNK_SIZE_TOKENS = 350
CHUNK_OVERLAP_TOKENS = 50

_tokenizer = None
_splitter = None


def _get_splitter() -> RecursiveCharacterTextSplitter:
    global _tokenizer, _splitter
    if _splitter is None:
        _tokenizer = AutoTokenizer.from_pretrained(EMBEDDING_MODEL_NAME)
        _splitter = RecursiveCharacterTextSplitter.from_huggingface_tokenizer(
            _tokenizer,
            chunk_size=CHUNK_SIZE_TOKENS,
            chunk_overlap=CHUNK_OVERLAP_TOKENS,
        )
    return _splitter


def chunk_pages(pages: list[PageBlock], tech_name: str, source_id: str) -> list[Document]:
    """섹션 블록 리스트를 `langchain_core.documents.Document` 청크 리스트로 변환한다.

    ``evidence_id``는 ``f"{tech_name}-p{page}-{seq}"`` 형태로 결정론적으로 부여되어,
    동일한 입력으로 재빌드해도 같은 청크는 같은 ID를 갖는다.
    """
    splitter = _get_splitter()
    documents: list[Document] = []
    page_seq: dict[int, int] = {}

    for block in pages:
        for piece in splitter.split_text(block.text):
            if not piece.strip():
                continue
            seq = page_seq.get(block.page, 0)
            page_seq[block.page] = seq + 1
            evidence_id = f"{tech_name}-p{block.page}-{seq}"
            documents.append(
                Document(
                    page_content=piece,
                    metadata={
                        "evidence_id": evidence_id,
                        "source_id": source_id,
                        "tech_name": tech_name,
                        "page": block.page,
                        "section": block.section,
                    },
                )
            )
    return documents
