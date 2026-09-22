# skala-rag
RAG 에이전트 제작 실습

## Paper RAG — 논문 검색 (KIVI / InfiniGen)

PDF 파싱 → Chunk → Embedding(`intfloat/multilingual-e5-small`) → FAISS 색인 → `retrieve_papers`
검색 도구로 구성된다. 자세한 내용은 `src/skala_rag/tools/retrieve/`, `src/skala_rag/agents/technical/`,
`src/skala_rag/evaluation/retrieval/` 참고.

**검색 지표** (라벨링된 질의 20개, KIVI/InfiniGen 각 10개 기준, 설계서 E.3):

| 지표 | 값 |
|---|---|
| Hit Rate@5 | 65% |
| MRR@5 | 0.403 |

측정 방법과 문항별 결과는 `evaluation/retrieval/report.md` 참고. 재측정하려면
`python scripts/run_retrieval_eval.py` 실행(사전에 `python scripts/build_index.py`로 색인 필요).
