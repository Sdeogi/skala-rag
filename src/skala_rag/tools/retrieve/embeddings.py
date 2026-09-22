"""`intfloat/multilingual-e5-small` 임베딩 래퍼.

e5 계열 모델은 문서/질의에 각각 ``passage: ``/``query: `` 접두어를 붙여야 검색 품질이
나온다는 규약이 있다(설계서 B.5). `langchain_community.embeddings.HuggingFaceEmbeddings`는
이 접두어를 자동으로 붙여주지 않으므로, `sentence-transformers`를 직접 감싸는 얇은
`Embeddings` 구현을 둔다.
"""

from __future__ import annotations

from functools import lru_cache

from langchain_core.embeddings import Embeddings
from sentence_transformers import SentenceTransformer

MODEL_NAME = "intfloat/multilingual-e5-small"


@lru_cache(maxsize=1)
def _load_model(model_name: str = MODEL_NAME) -> SentenceTransformer:
    return SentenceTransformer(model_name)


class E5Embeddings(Embeddings):
    """`passage:`/`query:` 접두어 규약을 적용하는 multilingual-e5-small 임베딩."""

    def __init__(self, model_name: str = MODEL_NAME):
        self.model_name = model_name
        self._model = _load_model(model_name)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        prefixed = [f"passage: {text}" for text in texts]
        vectors = self._model.encode(prefixed, normalize_embeddings=True, show_progress_bar=False)
        return vectors.tolist()

    def embed_query(self, text: str) -> list[float]:
        vector = self._model.encode(
            f"query: {text}", normalize_embeddings=True, show_progress_bar=False
        )
        return vector.tolist()
