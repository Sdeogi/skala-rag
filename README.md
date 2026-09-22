# skala-rag

KV cache 기술 KIVI와 InfiniGen을 네 관점에서 평가하는 팀 프로젝트다. 이 브랜치 `feat/graph-output`는 그래프 오케스트레이션과 종합·보고서 출력을 구현한다. 논문 RAG, 웹 근거, 관점 평가 서비스는 다른 팀 브랜치와 합병할 때 연결한다.

## 환경과 실행

Python 3.11 이상과 `uv`를 사용한다.

```bash
uv sync --group dev
source .venv/bin/activate
python app.py --mode replay --fixture --output-dir outputs/demo
python -m pytest -q
```

`--fixture`는 그래프 흐름 검증용 **합성 자료**다. 생성된 보고서는 실제 KIVI/InfiniGen 평가 결과가 아니다. 팀 서비스 연결 후 실제 실행은 다음 형태다.

```bash
python app.py --mode replay --services integration.services:create_services --output-dir outputs/replay
python app.py --mode live --services integration.services:create_services --paper-dir data/papers --output-dir outputs/live
```

서비스 factory는 `skala_rag.graph.workflow.PipelineServices`를 반환해야 한다. `live`는 `OPENAI_API_KEY`, `TAVILY_API_KEY`를 확인하며, 서비스 구현이 이 키와 검색 예산을 사용한다. `replay`는 같은 mode를 서비스에 전달한다. 실제 외부 검색 차단과 캐시 재생은 웹 서비스 어댑터에서 보장해야 한다. `RAG_MODEL_ID` 또는 `--model-id`로 모델 ID를 전달한다.

## D 브랜치 구현 범위

- `src/skala_rag/graph/`: State/reducer, 병렬 fan-out 및 join, 근거 검사, 최대 2회 보완 루프, 실패 분기
- `src/skala_rag/agents/synthesis.py`: 검증된 관점 판정의 일치/상충 쌍과 조건·불확실성 정리
- `src/skala_rag/agents/report.py`, `src/skala_rag/templates/`: 한국어 Markdown/HTML/PDF, `sources.json`, `run_manifest.json`
- `app.py`: live/replay CLI와 통합 서비스 로더

보고서 본문은 `SUMMARY`로 시작해 `REFERENCE`로 끝난다. `live`는 생성 LLM이 검증된 종합 쌍의 순서를 정하고 SUMMARY를 작성한다. 새 숫자·근거 ID·우열 판정이 있으면 규칙 기반 문장으로 대체한다. 나머지 장과 `replay` 출력은 검증된 State에서 규칙 기반으로 생성해 근거 추적과 재현성을 유지한다. `live`에서도 `--deterministic-output`으로 이를 선택할 수 있다. 근거 의미 검토는 C 브랜치의 `semantic_review` 연결이 필요하며, 연결 여부는 manifest의 `evidence_check.semantic_review_enabled`에 기록한다.

실제 서비스의 부분 State 반환 형식, C 브랜치 스키마 변환 위치, 예외 경로와 통합 체크리스트는 [설계 및 인수인계](docs/GRAPH_OUTPUT_DESIGN.md)에 있다. 작업 순서와 검증 결과는 [구현 계획](docs/GRAPH_OUTPUT_PLAN.md), [작업 이력](docs/GRAPH_OUTPUT_HISTORY.md)에 기록한다.

참고 자료: [팀 설계계획서](https://docs.google.com/document/d/1P98uEyi9BCwT6SU8bEPeC_GyZ_rdVa-hpG5ra2Cw0DQ/edit), [LangGraph Graph API](https://docs.langchain.com/oss/python/langgraph/graph-api).
