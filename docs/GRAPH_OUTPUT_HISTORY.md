# D 역할 작업 이력 / 다음 작업자를 위한 체크포인트

## 현재 상태

- 작업 위치: `/Users/kunwoo/Desktop/workspace/0918_RAG_Pipeline_설계_및_구현/skala-rag`
- 브랜치: `feat/graph-output` (원격 `main`을 복제해 생성)
- 담당: LangGraph State/Node/Edge, 네 관점 병렬 실행/합류, 근거 보완 루프, 종합, 보고서, CLI
- 팀원 구현 미합병. fixture만으로 완전한 그래프를 실행할 수 있다. 실제 연구 보고서는 팀 서비스 연결 전에는 생성할 수 없다.

## 참고와 결정

1. Google Docs 설계계획서 B/C/D/E 장을 읽었다. 첨부 역할 표와 사용자 최신 지시를 기준으로 D를 담당한다. 문서의 예전 E.1 담당자 배정은 이번 구현 범위를 결정하는 데 사용하지 않았다.
2. Notion URL은 연결 계정에서 `object_not_found`(404)였고 브라우징으로도 접근되지 않았다. 과제 페이지의 미확인 세부사항은 추가 구현 근거로 사용하지 않았다.
3. `ai_service/langgraph-v1`의 State, Graph, Branching, SelfRAG, Multi-Report 예제와 최신 공식 Graph API를 확인했다. `add_edge([market, stakeholder, domain, trl], evidence_check)`가 네 결과의 합류 장벽이다.
4. 종합과 보고서의 근거 기반 골격은 규칙으로 작성한다. live에서는 LLM이 종합 후보를 정렬하고 SUMMARY 문장을 작성하며, 새 숫자·근거 ID·우열 표현은 거부한다. replay는 규칙 기반으로 출력한다. 상충 쌍은 관련성이 정의된 관점 항목 조합에서만 만든다. 총점/순위/도입 추천을 계산하지 않는다. 근거 의미 검토는 `semantic_review` 주입 지점으로 남겼다.

## 구현 순서와 재현 명령

1. 저장소를 처음에는 잘못된 현재 작업공간 `0818_0820_SpringAI/skala-rag`에 복제했으나, 사용자 확인 직후 전체 저장소를 위의 `0918.../skala-rag`로 이동했다. 현재 작업은 올바른 폴더에서 수행 중이다.
2. `docs/GRAPH_OUTPUT_DESIGN.md`와 `docs/GRAPH_OUTPUT_PLAN.md`를 작성했다.
3. 테스트를 먼저 작성하고 import 실패를 확인한 뒤 State/reducer, 근거 검사, synthesis/report, workflow를 구현했다.
4. 최초 LangGraph 컴파일에서 조건부 간선의 노드 목록 매핑이 허용되지 않아 `fan_out` 노드를 명시적으로 추가했다. 수정 후 병렬 합류 테스트가 통과했다.
5. `app.py`, HTML 템플릿, PDF 저장과 fixture를 구현했다. `python app.py`가 설치 전에도 `src` 패키지를 찾게 했다.
6. 합성 fixture로 Markdown/HTML/PDF/sources/manifest를 만들고 PDF 첫 장과 마지막 장을 렌더링해 한글과 구조를 확인했다. LLM 출력의 근거 ID·숫자 제한, 민감정보 가림과 TRL 범위 라벨을 추가했다.
7. 원격 업로드 직후 README의 테스트 명령을 `PYTHONPATH` 없이 재현했을 때 `src` import가 실패했다. pytest 설정에 `pythonpath = ["src"]`를 추가해 문서의 명령을 그대로 실행 가능하게 했다.

```bash
cd '/Users/kunwoo/Desktop/workspace/0918_RAG_Pipeline_설계_및_구현/skala-rag'
uv sync --group dev
source .venv/bin/activate
python -m pytest -q
python app.py --mode replay --fixture --output-dir /tmp/skala-rag-graph-output-smoke
```

## 통합 시 가장 먼저 할 일

1. A/B/C 브랜치 출력과 `PipelineServices` 계약을 대조한다. 특히 기술명, 증거 ID, Source ID, 관점 항목 키와 라벨을 맞춘다.
2. C의 의미 검토를 `semantic_review`에 연결하고 검토가 통과한 항목만 종합에 사용되는지 확인한다.
3. `retry` 서비스가 `missing_questions`에 적힌 항목만 조회하고, 상태의 해당 관점 키만 교체하는지 확인한다.
4. `live`의 API 예산/재시도와 `replay`의 네트워크 미사용을 검증한다.
5. 실제 PDF에서 한국어 글꼴, 정량 수치의 조건, 출처 링크와 표 배치를 육안 검수한다.

## 미해결 사항

- A/B/C 브랜치가 현재 `main`에 없으므로 실제 논문/웹 근거를 통한 끝단 실행은 아직 검증할 수 없다.
- 의미 검토 LLM이 미연결이면 규칙 검증만 수행한다. manifest에 이 사실이 표시된다.
- PDF는 현재 텍스트 중심 A4 보고서다. 실제 데이터에 복잡한 표가 들어오면 통합 단계에서 레이아웃 검수가 필요하다.
- 모델 API 키가 없어 live 모드의 실제 LLM 호출은 실행하지 않았다. LLM 에이전트의 입력/출력 경계와 fallback은 fake 모델 테스트로 검증했다.

## 2026-09-22 2차: 검토 결과 반영

[GRAPH_OUTPUT_REVIEW.md](GRAPH_OUTPUT_REVIEW.md)의 상 6건, 중 10건, 하 8건을 모두 반영했다. 항목별 처리는 검토 문서 7절에 있다. 주요 변경:

1. `graph/schemas.py` 신설: 공유 Pydantic 계약과 라벨 집합, 노드 경계 검증(`validate_update`).
2. `graph/state.py`: `merge_by_id`가 충돌 시 최초 값을 유지하고 `conflicts`를 기록. `metrics`는 이벤트 리스트로 변경하고 집계 함수 추가.
3. `graph/evidence_check.py`: `판단 유보` 허용, `missing_questions`에 이유 포함, 검토 LLM 경고 처리, 검토 metrics 수집.
4. `agents/review.py` 신설: 검토 LLM(캐시, 예산, 토큰 기록). `app.py`가 live에서 기본 연결.
5. `agents/synthesis.py`: 판정 이유·조건 기반 문장, 관련 항목 조합 확장. `agents/llm_output.py`: 쌍별 이유·불확실성 작성, keep/순서, 쌍 단위 검증과 fallback, SUMMARY 가드 정규식 통일, fallback 사유·토큰 기록.
6. `agents/report.py`: 과제 참고 목차, 정적 장(`report_static.py`), 표, REFERENCE 형식, TRL 고지·단계 상세, 규칙 기반 SUMMARY, 인용 길이 제한, 조사 처리(`korean.py`), TTF 임베드, `--report-name`, manifest 확장.
7. `graph/workflow.py`: path_map 명시, fan_out 노드 제거, 관점별 `Send` 보완, `retry` 선택형, 200페이지 상한, `GraphBubbleUp` 재전파, 실행 시간 metrics, `draw_mermaid`.
8. `config.py`, `app.py`: `.env` 자동 로드, 설정 검증 분리, CLI 옵션(기술명·도메인·기준일·예산·검토 LLM·보고서 이름·도식), `stream(values)`로 마지막 State 보존.
9. `pyproject.toml`: `graph` 의존성 그룹, hatchling build-system. `uv lock` 재생성. `.env.template`에 `RAG_PDF_FONT`.
10. 테스트 47개(`tests/conftest.py` 공용 fixture), README를 과제 샘플 형식으로 재작성, `docs/graph.mmd` 추가.

재현 명령:

```bash
cd '/Users/kunwoo/Desktop/workspace/0918_RAG_Pipeline_설계_및_구현/skala-rag'
uv sync --only-group graph --only-group dev
.venv/bin/python -m pytest -q                                   # 47 passed
.venv/bin/python app.py --mode replay --fixture --output-dir outputs/demo --report-name RAG-Output_test
.venv/bin/python app.py --draw-graph docs/graph.mmd
```

검증 결과: 테스트 47개 통과, 깨끗한 환경(`UV_PROJECT_ENVIRONMENT`)에서 52개 패키지 설치 후 동일 결과, fixture 보고서 7쪽 PDF에 AppleGothic 서브셋 임베드(`pdffonts` emb=yes), OpenAI API로 `gpt-5.4-mini` 존재와 구조화 출력 호출 성공 확인. live 경로(검토 LLM·종합 LLM·SUMMARY LLM) 실행 결과는 검토 문서 7절 참고.

## 현재 상태 (2차 이후)

- 작업 트리에 변경 사항이 있으며 커밋·푸시는 하지 않았다. 원격 `feat/graph-output`은 아직 `6612864`다.
- 팀 서비스 미합병. 실제 논문·웹 근거의 끝단 실행은 A/B/C 연결 후 가능하다.
- 남은 팀 결정: 기본 의존성 목록 정리(합병 시), C의 검토 LLM 교체 여부, README Contributors·검색 지표.

## 2026-09-22 3차: main 병합과 통합 계획

`origin/main`(A/B/C 22개 커밋, PR #2까지 병합됨)을 `feat/graph-output`에 병합했다(커밋 `b68d1b2`). 충돌 8개는 모두 환경설정 파일이었다: `.gitignore`(합집합), `README.md`(과제 형식 유지 + main의 Paper RAG 절·검색 지표·전체 디렉토리 구조 반영), `pyproject.toml`(main 배치 + jinja2/reportlab + `graph` 그룹), `uv.lock`(main 것 받은 뒤 `uv lock`), 패키지 `__init__` 2개(docstring 병합), `config.py`(D 구현 유지), `database/`(main대로 삭제). 경로가 겹치는 소스 모듈은 없다.

### main에 올라온 A/B/C 계약 (통합 어댑터 작성 시 기준)

| 브랜치 | 진입점 | 반환·형식 | D 계약과의 차이 |
| --- | --- | --- | --- |
| A | `agents/technical.technical_research_node(state)` | `technical_findings{tech: {principle: {claims, evidence_ids}, experimental_setup, performance, limitations}}`, `evidence{id: {tech_name, page, section, claim, quote, claim_type, experimental_condition}}`, `errors` 리스트. `run_config.tech_names`를 읽음 | Evidence는 `technology`, `location`, `conditions`로, findings는 `TechFinding(principle 문자열, measurements, limitations)`로, errors는 dict로 변환 필요. `run_config.technologies`도 함께 넣어야 함 |
| A | `tools.retrieve.retrieve_papers(query, tech_name, k, query_en)` | `RetrievedChunk(evidence_id, source_id, tech_name, page, section, text)` | C의 평가기는 `.evidence_id`를 가진 Evidence 객체를 기대하므로 A→C 변환도 필요 |
| B | `agents.market.collect_market_evidence(technology, topics, mode, ...)`, `agents.stakeholder.collect_stakeholder_evidence(technology, mode)` | 기술별 근거 수집 결과(`evidence` 리스트, `indirect_evidence`, `errors`, `searches`). **판정 라벨(PerspectiveResult)은 아직 없음** | 시장성·이해관계자 판정 단계(라벨·이유·근거 ID)를 B 또는 공동으로 추가해야 `market_analysis`, `stakeholder_analysis`가 채워짐 |
| B | `tools.web.get_search_results/get_source/summarize_source(mode)` | live 저장·replay 재생 캐시 `data/web/` | 예산은 `run_config.budget`에서 읽도록 연결 |
| C | `agents.domain.make_domain_evaluator(retriever)`, `agents.trl.make_trl_evaluator(retriever, web_search)` | `{"domain_analysis": PerspectiveResult(items=[RubricItem(item_key, tech, verdict, reason, evidence_ids, conditions)]), "evidence": {...}}` | D 형식 `technologies{tech: {field: Judgment(label, ...)}}`로 변환. `trl_level`→`trl`, `verdict`→`label`, Evidence `tech`→`technology` |
| C | `evidence_check.evidence_check(state, model_name)`, `supplement.make_supplement_node(retriever, web_search)` | C 스키마(`schemas/state.py`)의 State 객체를 전제. 보완은 도메인·TRL만 | D 그래프는 `graph/evidence_check.py`와 관점별 Send 보완을 사용. C의 `llm_review_item`은 `semantic_review`로, `make_supplement_node`는 `services.retry`로 감쌀 수 있음 |
| C | `schemas/state.py` | 팀 공용 Pydantic 스키마(C 소유 선언), State 채널에 Pydantic 객체 | D의 `graph/schemas.py`는 dict 기반 경계 계약. 둘 중 하나로 수렴하거나 어댑터를 한 곳(`integration/services.py`)에 둔다 |

### 다음 작업 (통합 단계)

1. `src/skala_rag/integration/services.py`에 `create_services()`를 만들고 위 변환을 한 곳에 모은다. `prepare`는 `data/papers/manifest.json`으로 Source(paper, pages)를 등록하고 색인 존재를 확인한다.
2. 시장성·이해관계자 판정 단계를 정한다(B의 수집 결과에 C의 `judge_one` 방식 적용 또는 B가 구현).
3. `python app.py --mode replay --services skala_rag.integration.services:create_services`로 끝단 실행을 검증한다.
4. C의 `schemas/state.py`와 D의 `graph/schemas.py`를 하나로 수렴할지 팀이 결정한다.

## 2026-09-22 4차: 통합 계층 구현 (`feat/integration`)

PR #1~#5가 모두 `main`에 합쳐진 뒤(`fea5054`) `feat/integration` 브랜치를 만들고 A/B/C 모듈을 D 그래프에 연결했다.

### 구현

- `src/skala_rag/integration/services.py`: `create_services()`가 `PipelineServices`를 만든다. 변환 규칙은 [GRAPH_OUTPUT_DESIGN.md](GRAPH_OUTPUT_DESIGN.md)의 "통합 계층" 절 참고. 팀 함수는 `IntegrationSettings`로 교체 가능해 `tests/test_integration.py`(8개)는 스텁으로 오프라인 실행한다.
- `app.py`: `--services`를 생략하면 이 factory를 쓴다(`python app.py --mode live`). `--fixture`가 아닌 실행은 판정 LLM을 호출하므로 replay에서도 `OPENAI_API_KEY`를 요구한다(`config.missing_settings(services_need_llm=True)`).
- `graph/schemas.TechFinding`에 `performance`(성능 보고 문장) 추가, 보고서 3장에 렌더링.
- 보고서: 6장 실행 오류를 (종류, 노드, 사유)별로 묶어 건수를 표기, SUMMARY는 핵심 항목이 근거 미확인이면 같은 관점의 다른 통과 항목으로 대체, 5장 시사점의 조건 문자열 길이 제한, API 오류 메시지에 섞인 마스킹 키(`sk-proj***`)도 가림.
- TRL 어댑터: 판정 이유를 "확인된 최고 단계 + 다음 미충족 단계"로 요약하고 단계별 상세는 `stages`에, 부족 증거는 다음 단계 것만 `missing_evidence`에 둔다.
- 시장성·이해관계자 어댑터: 기술별로 따로 호출해 한 기술의 수집 실패(캐시 없음, 검색 API 오류)가 관점 전체를 비우지 않고 해당 기술만 `미확인`으로 남긴다.

### 실제 데이터 실행 (replay, 웹 캐시 없음, OpenAI 키만 사용)

`python app.py --mode replay --semantic-review on --report-name RAG-Output_replay`로 두 논문 PDF(33쪽)와 FAISS 색인을 써서 끝까지 실행했다. Tavily 키와 `data/web` 캐시가 없어 시장성·이해관계자·TRL 웹 단계는 미확인으로 남는다(정상 경로). 1차 실행에서 발견한 문제와 조치:

| 발견 | 조치 |
| --- | --- |
| 셸에서 `.env` 값을 잘라 넣자 따옴표가 섞여 OpenAI 401 | python-dotenv로 읽도록 실행 절차 변경(`app.py`는 원래 `load_dotenv` 사용) |
| 이해관계자 서비스가 캐시 부재 예외로 결과가 통째로 없음(`missing_item`) | 기술별 호출 + 미확인 대체 |
| B의 검색 실패 오류가 라운드마다 반복되어 manifest 71건, 6장에 그대로 나열 | 6장에서 묶어 건수 표기 |
| TRL 판정 이유가 7단계 문장을 이어 붙여 표와 5장을 뒤덮음 | 요약 이유 + `stages` 상세 |
| InfiniGen은 핵심 항목(도메인 memory)이 미확인이라 SUMMARY에 판정이 없음 | 같은 관점의 다른 통과 항목으로 대체 |

### 2차·3차 replay 실행에서 반영한 추가 조치

- 검토 LLM 프롬프트에 라벨의 의미(설계 C.2~C.5, `agents/review.py::LABEL_MEANINGS`)를 함께 전달한다. 2차 실행에서 TRL 라벨이 모두 `unsupported_claim`으로 거부됐는데, 검토 LLM이 "TRL 3"이라는 라벨 문자열만 보고 판단했기 때문이다. 3차 실행에서는 TRL 두 건이 통과했고, 도메인 KIVI 응답 지연만 "근거가 메모리·처리량만 보고하고 지연은 보고하지 않는다"는 사유로 거부됐다(타당한 판정).
- 검토 LLM의 거부 사유를 `evidence_check.items[].review_reason`과 `missing_questions[].review_reason`에 남기고 보고서 6장에 "검토 LLM: …"으로 표시한다.
- 근거 검사에서 A의 `unverified` 주장 유형이 붙은 청크는 도메인·TRL 판정의 근거로 인정하지 않는다(설계 B.7). 근거 풀을 공유하므로 A가 unverified로 표시한 청크 ID를 C 판정기가 인용하면 `unverified_evidence`로 남는다.
- 보완 라운드 정책: B의 시장성·이해관계자 에이전트는 고정 검색어 템플릿으로 수집하고 부족 질문 기반 재검색을 지원하지 않으므로, 보완 라운드에서는 재수집하지 않고 이전 판정을 유지한다(`metrics.repair_skipped`). TRL 웹 단계는 보완 라운드에서 1차 live 라운드가 저장한 `data/web` 캐시를 replay로 읽어 재판정만 한다. 그렇지 않으면 live 보완 2회가 같은 Tavily 검색을 세 번 반복한다.
- 어댑터는 근거 ID가 없는 TRL 단계 `충족`을 미확인으로 내린다(C 판정기와 같은 규칙).

3차 replay 실행 결과(웹 캐시 없음): 85초, LLM 호출 66회(기술 조사 16, 도메인 13, TRL 21, 검토 16), 검색 35회, 근거 검사 24항목 중 통과 11(도메인 9, TRL 2), 미확인 13(시장성 6·이해관계자 6은 캐시 없음, 도메인 1은 검토 거부). manifest 오류 56건은 6장에서 3줄로 묶였다.

### `.env`와 live 실행

사용자가 전달한 Tavily 키를 `skala-rag/.env`에 기록했고(`.gitignore` 대상), live 실행에 필요한 OpenAI 키는 `ai_service/langgraph-v1/.env`의 값을 같은 파일에 복사했다. `python app.py --mode live --report-name RAG-Output_live` 실행 결과는 아래에 추가한다.

live 실행 결과(`python app.py --mode live --report-name RAG-Output_live`, Tavily 키 적용): 151초에 끝까지 완료. 웹 검색 34회, 원문 조회 시도 약 50회, `data/web` 캐시 122개, 출처 21개(논문 2 + 웹 19). 근거 검사 24항목 중 통과 13, 미확인 11(미발견 6, 검토 LLM 거부 5). 종합 LLM이 쌍 4개(상충 2, 일치 2)를 작성해 모두 검증을 통과했고, SUMMARY LLM은 1,200자 제한을 넘겨 규칙 기반으로 대체됐다. manifest 오류 6건: B의 인용문 검증 실패 2건, Tavily 응답 형식 오류 3건(이해관계자 InfiniGen 수집 전체 실패 포함), TRL 웹 단계 1건.

live 실행 후 반영한 조치:

| 발견 | 조치 |
| --- | --- |
| SUMMARY LLM 출력이 제한 길이를 넘겨 전부 버려짐 | 문장 경계에서 잘라 검증(`trim_to_sentences`), `summary_trimmed` 기록 |
| 이해관계자 InfiniGen 수집이 Tavily 일시 오류로 실패했는데 보완 라운드가 재수집을 건너뜀 | 수집 자체가 실패한 기술만 보완 라운드에서 다시 수집 |
| 도메인 `보고 없음` 판정에 근거 ID가 붙어 검토 LLM이 당연히 거부 | `보고 없음`을 미발견 라벨로 취급(근거·검토 생략, 보완 대상 유지) |
| 웹 출처의 저자·발행일이 없어 REFERENCE가 "저자 미상" | 저자가 없으면 사이트 도메인을 기관명으로 표기 |
| 검토 LLM이 B의 `직접 자료 있음`(실제로는 관련 시장 자료) 등 5건을 거부 | 정상 동작. 거부 사유가 6장에 표시되므로 B 판정 기준(요약기의 `scope`)을 팀이 검토 |
| 시장성 근거 후보에 무관한 사이트(kiwidata.com "Kiwi Blog")가 포함 | B의 후보 필터 문제로 기록. 검토 LLM이 해당 판정을 거부해 보고서에는 통과 판정으로 실리지 않음 |

검증: `python app.py --mode replay --llm-output on --semantic-review on`으로 live 캐시를 재생하며 LLM 종합·SUMMARY를 다시 실행한 결과는 아래에 추가한다.
검증 실행 결과(`--mode replay --llm-output on --semantic-review on`, live 캐시 재생): 122초, 웹 검색 34회 모두 캐시 재생, SUMMARY LLM 979자 통과(`report_mode: llm_assisted`), 종합 LLM 쌍 4개 중 2개 채택·2개 제외(실제 일치 아님으로 판단), 검토 LLM 21회. 근거 검사 24항목 중 통과 14, 미발견 6, 검토 거부 4. live에서 검증에 실패해 캐시가 없던 페이지는 replay에서 `FileNotFoundError`로 남는다(정상). 테스트 87개 통과.

### 팀 확인 사항 (통합 후 남은 것)

1. B 시장성: 요약기의 `scope`가 관련 시장 자료를 `technology`로 표시해 `직접 자료 있음`이 붙는 사례가 있다(검토 LLM이 거부). 후보 필터가 무관한 사이트(kiwidata.com)와 원 논문의 arXiv HTML을 근거 후보로 통과시킨다.
2. B 이해관계자: `_search_topic`이 Tavily 응답 오류를 잡지 않아 기술 하나의 수집이 통째로 실패한다(어댑터가 `미확인`으로 대체하고 보완 라운드에서 재수집).
3. 설계 B.6의 실행당 검색 20회·원문 30건 상한을 B 모듈이 강제하지 않는다. live 1회에 검색 34회, 원문 조회 시도 약 50회가 발생했다.
4. C 도메인: `보고 없음` 판정에 근거 ID를 붙여 반환하는 경우가 있다. D는 미발견 라벨로 처리한다.
5. 스키마 수렴: C `schemas/state.py`와 D `graph/schemas.py`는 어댑터로 연결된 상태이며 하나로 합칠지는 팀 결정.
