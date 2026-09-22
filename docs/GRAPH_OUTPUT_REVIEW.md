# D 역할(feat/graph-output) 작업물 검토 보고

- 검토일: 2026-09-22
- 대상: `feat/graph-output` 브랜치 커밋 `6612864` (Codex 작업 결과)
- 상태: 2026-09-22 검토 후 같은 날 **모든 개선 항목을 반영(개선완료)**. 항목별 처리와 검증은 7절에 기록.

## 0. 검토 범위와 방법

- 코드 전량 정독: `graph/state.py`, `graph/workflow.py`, `graph/evidence_check.py`, `graph/demo.py`, `agents/synthesis.py`, `agents/report.py`, `agents/llm_output.py`, `templates/report.html.j2`, `app.py`, 테스트 4개, 문서 3개.
- 기준 문서: 팀 설계계획서(Google Docs, 전문 확보), 과제 Notion 페이지(Notion 커넥터로 전문 확보. Codex 기록의 "404"와 달리 접근 가능), `ai_service/langgraph-v1` 가이드(State/Graph/Branching/Multi-Report/SelfRAG/CorrectiveRAG/Orchestrator-Workers).
- 실행 검증: `pytest` 17개 통과(0.9초), fixture smoke 실행 성공, PDF 1쪽 렌더링 확인, 시나리오 스크립트 4종(동일 ID 충돌, metrics 충돌, 관점 서비스 예외, prepare 치명 오류), mermaid 도식 출력, 리스트 반환 조건부 간선 대안 검증, `uv lock --check` 및 `uv sync --dry-run`.

## 1. 종합 판정

그래프 골격(State 키, 명시적 join, 보완 2회 상한, 조기 종료, live/replay 분기, 산출물 5종)은 설계서 D장과 대응하고 테스트로 확인된다. 다만 **통합 시 실행을 중단시키는 reducer 정책(상 1·2)**, **통합 계약이 산문으로만 존재하는 점(상 3)**, **설계서가 요구한 검토 LLM 미구현(상 4)**, **종합·보고서가 과제 요구 수준에 못 미치는 점(상 5·6)** 이 있어 그대로 합병하면 실제 자료에서 실패하거나 보고서 품질이 낮을 가능성이 크다.

잘 된 점:

- State 필드가 D.1 표와 일치하고, 관점별 독립 키와 `add_edge([...], "evidence_check")` join, 보완 상한, 치명 오류 경로가 테스트(병렬 Barrier 테스트 포함)로 검증됨.
- LLM 출력 가드(근거 ID·숫자·우열 표현 거부), 민감정보 가림, 프롬프트 주입 방어 문구, fixture의 합성 표시.
- replay 결정성, manifest `status`, PDF 한글 렌더링 정상(poppler 기준).

## 2. 문제점과 개선점

### 상 (통합 전 반드시 결정 또는 수정)

**H1. 공유 dict reducer가 ID 충돌 시 예외를 던져 실행 전체가 종료된다** (개선완료)
- 현상: `merge_by_id`는 같은 ID에 다른 내용이 오면 `ValueError`. 시나리오 A(시장성·이해관계자 노드가 같은 URL 출처를 `retrieved_at`만 다르게 반환) → `ValueError: Conflicting record ID: shared-url`로 `invoke` 전체 실패. `app.py`는 초기 State에 pipeline 오류만 붙여 저장하므로 그때까지의 관점 결과·근거가 모두 사라진다.
- 기준: 설계서 D.1 "같은 ID의 내용이 다르면 충돌로 **기록**". Codex 설계 문서는 이를 "실패시킨다"로 바꿨다.
- 실제 위험: B의 웹 도구가 같은 URL을 두 관점에서 각각 수집하면 수집 시각·해시가 달라 ID는 같고 내용은 다르다. 근거 ID를 인용구 해시로 만들어도 요약 문구가 조금 다르면 같은 문제.
- 개선안: (a) 최초 값 유지 + 충돌 기록(충돌 목록은 `operator.add` 리스트 키 또는 값 내부 필드), (b) 비교에서 `retrieved_at`·`content_hash` 같은 실행마다 바뀌는 필드 제외, (c) 계약에 "`source_id`/`evidence_id`는 URL·페이지·인용구 기반의 결정적 ID" 명시.
- 파일: `src/skala_rag/graph/state.py`, `docs/GRAPH_OUTPUT_DESIGN.md`

**H2. `metrics`가 누적 불가능하고 토큰·도구 호출 집계가 없다** (개선완료)
- 현상: 시나리오 B(관점 노드 `metrics: {"web_search_calls": 3}`, 보완 노드 `{"web_search_calls": 2}`) → H1과 같은 예외로 종료. 설계서 D.4가 manifest에 요구한 도구 호출 횟수·토큰 사용량은 서비스가 `metrics`에 넣어야 하는데 넣으면 충돌한다. D 자체의 LLM 호출(종합 정렬, SUMMARY)도 토큰을 기록하지 않는다.
- 개선안: `metrics`를 노드별 네임스페이스(`{"market": {...}}`) 또는 이벤트 리스트(`Annotated[list, operator.add]`)로 바꾸고 `save`에서 합산. LLM 응답의 `usage_metadata`를 기록.
- 파일: `state.py`, `workflow.py`, `agents/llm_output.py`, `agents/report.py`

**H3. 공유 Pydantic 스키마가 없어 통합 계약이 산문에만 있다** (개선완료)
- 현상: State는 전부 `dict[str, Any]`. 설계서 B.1(출력 구조 검증 Pydantic), D.1(RunConfig/Source/Evidence/PerspectiveResult/Synthesis/Report 객체), C.7(라벨 enum 검증)이 전제한 모델이 없다. 라벨 집합은 `evidence_check.RUBRICS`에만 있어 A/B/C가 import해 자기 출력을 검증할 대상이 없다. `_call_service`는 반환 키 이름만 검사한다.
- 개선안: `graph/schemas.py`에 Pydantic 모델(라벨은 `Literal`), `RUBRICS`는 스키마에서 파생, 서비스 반환값을 경계에서 `model_validate`하고 실패는 `errors`에 스키마 오류로 기록(설계서 E.3 "LLM 출력 스키마 위반" 실패 경로). 정규화 형식은 그대로 두되 모델로 고정.
- 파일: 신규 `src/skala_rag/graph/schemas.py`, `evidence_check.py`, `workflow.py`

**H4. 검토 LLM(근거 의미 검토)이 구현되지 않았다** (개선완료)
- 현상: `semantic_review` 기본값 `None`. 미연결이면 규칙 검사만 하고 manifest에 `semantic_review_enabled: false`만 남긴다. 설계서 D.4 "이어서 검토 LLM이 근거 구절이 판정을 뒷받침하는지를 항목별로 판단", B.1 "검토는 생성과 다른 프롬프트와 별도 호출". Codex는 C 브랜치 몫으로 가정했지만 근거 검사 노드는 그래프(D) 영역이고 분담표에 담당이 없어 아무도 구현하지 않을 위험이 있다.
- 개선안: D가 기본 구현 제공(gpt-5.4-mini, 구조화 출력 `supported: bool, reason: str`), (관점·기술·항목·근거 ID 집합) 단위 캐시로 루프마다 재검토 방지, C가 교체할 수 있는 주입 지점은 유지. 호출 상한(최대 24항목 × 3회)을 문서화.
- 파일: `evidence_check.py`, 신규 `agents/review.py`(또는 `graph/review.py`), `app.py`

**H5. 평가 종합이 템플릿 문장이라 종합 에이전트 역할을 하지 못한다** (개선완료)
- 현상: 모든 쌍의 `reason`이 "…판정을 서로 다른 조건에서 읽어야 한다", `uncertainty`가 "두 근거의 실험 또는 공개 시점이 다르면 직접 비교할 수 없음"으로 고정. live의 LLM은 순서만 바꾼다. 일치/상충은 라벨→favorable/cautious 휴리스틱과 고정 `RELATED_FIELDS` 조합으로만 결정된다(예: "연구 재현 수준"과 "조건부 보고"가 자동으로 '일치'). fixture 보고서의 "관점 간 종합" 4개 문단이 사실상 같은 문장이다.
- 기준: 설계서 B.2 "네 관점 결과에서 일치점과 상충점을 조건과 함께 정리", C.6 상충 쌍 6요소(상충 이유·조건·불확실성은 내용이어야 함). 과제 채점 "Output - 보고서 20점".
- 개선안: LLM이 후보 쌍별 `reason`/`conditions`/`uncertainty`를 판정의 reason·conditions·근거 인용구만으로 작성(구조화 출력), 후보에 없는 근거 ID나 새 숫자가 나오면 해당 쌍만 템플릿으로 대체, 실제 상충이 아닌 쌍은 LLM이 제외할 수 있게 허용. 총점·순위·추천 금지 가드는 유지. replay는 규칙 기반 유지하되 문장을 판정 reason으로 채운다.
- 파일: `agents/synthesis.py`, `agents/llm_output.py`

**H6. 보고서 목차·형식이 과제(Notion) 요구와 다르다** (개선완료)
- 현상: 목차가 SUMMARY / 기술 조사 / 시장성 / 이해관계자 / 도메인 적용 / 기술 성숙도 / 관점 간 종합 / 한계와 미확인 항목 / 근거 목록 / REFERENCE. Notion 참고 목차(SUMMARY ½쪽 이내, 1 분석 배경, 2 기술 선정, 3 기술 개요, 4 관점별 평가, 5 시사점, 6 한계점, REFERENCE) 중 **분석 배경·기술 선정이 없다**. REFERENCE 표기 형식(논문: 저자(YYYY). 제목. 학회명. / 웹: 기관(YYYY-MM-DD). 제목. 사이트명, URL)을 따르지 않고 `[id] 제목 — URL`로 출력한다. TRL 절에 Notion이 요구한 "공개 정보 기반 추정임을 반드시 명시"가 없다. replay의 SUMMARY는 도입 2문장뿐이라 핵심 요약이 아니다. 조사 오류("InfiniGen를", "수준와")가 본문에 보인다.
- 참고: 팀 설계서에는 보고서 목차 절이 없어 Notion 참고 목차가 유일한 기준이다. 분석 배경·기술 선정은 설계서 §1, A장의 내용을 정적 자료(템플릿 상수 또는 `run_config`)로 넣을 수 있다.
- 개선안: 목차 재구성, Source 필드(저자/기관, 발행일, 출처 유형, 학회명)로 REFERENCE 포맷터 작성, TRL 절에 추정 고지 고정 문장, replay용 규칙 기반 SUMMARY(기술별 핵심 판정 + 상충 쌍 상위 N개, 길이 상한), 받침 유무에 따른 조사 처리 함수.
- 파일: `agents/report.py`, `templates/report.html.j2`, `agents/llm_output.py`

### 중 (통합 과정에서 수정 권장)

**M1. `retry` 서비스의 소유와 구조가 불명확하다** (개선완료)
- 현상: 모든 관점의 `missing_questions`를 하나의 callable이 처리한다. 설계서 D.4는 "해당 관점의 결과를 갱신"이며 관점 결과의 작성자가 하나여야 병렬 갱신 충돌이 없다. 분담표에 보완 담당이 없어 B/C가 각자 관점의 보완을 구현해야 하는데 계약이 단일 함수라 통합 시 조정이 필요하다.
- 개선안: 보완 노드가 `missing_questions`를 관점별로 나눠 해당 관점 서비스를 다시 호출(가이드 `12-Pattern/04-Orchestrator-Workers`의 `Send` 패턴 또는 리스트 반환 조건부 간선). 서비스는 `state["missing_questions"]`에 자기 관점 항목이 있으면 그 질문만 재검색. `retry` 필드는 제거하거나 선택형으로.
- 파일: `workflow.py`, `docs/GRAPH_OUTPUT_DESIGN.md`

**M2. PDF가 설계(HTML→PDF)와 다른 경로이고 글꼴이 미포함이며 표가 없다** (개선완료)
- 현상: reportlab이 `sections`를 직접 그린다. `pdffonts` 결과 `HYSMyeongJo-Medium` emb=no(뷰어의 CJK 대체 글꼴에 의존. poppler·미리보기는 정상, CJK 글꼴이 없는 뷰어에서는 공백·깨짐 가능). 표가 없다(설계서 E.3 "표 잘림" 점검은 표를 전제). HTML과 PDF가 다른 렌더 경로라 내용이 어긋날 수 있다.
- 개선안: 최소한 TTF 임베드(Noto Sans KR 또는 NanumGothic, `TTFont`), 관점별 평가는 표(기술 × 항목 × 라벨 × 근거). 가능하면 설계대로 HTML→PDF(WeasyPrint 등) 단일 경로.
- 파일: `agents/report.py`, `templates/report.html.j2`, `pyproject.toml`

**M3. `.env`를 읽지 않는다** (개선완료)
- 현상: `load_dotenv` 호출이 없다. `.env.template`만 있고 live 모드는 환경변수를 직접 export하지 않으면 "missing configuration"으로 종료. 가이드 코드는 모두 `load_dotenv(override=True)` 관례이며 `python-dotenv`는 의존성에 있다.
- 개선안: `app.py` 시작부에서 `load_dotenv()`.

**M4. `run_config` 누락 항목과 CLI 설정** (개선완료)
- 현상: 기준일, 검색 예산(웹 검색 20회, 원문 30건, 20초, 재시도 2회. 설계서 B.6/D.1)이 없다. 기술명·도메인이 코드 상수(설계서 B.1 "설정값으로 두 기술명과 도메인을 받아"). `--paper-dir`는 저장만 되고 사용처가 없다.
- 개선안: `--technologies`, `--domain`, `--as-of`, 예산 항목을 `run_config`에 포함해 B/C가 State에서 읽게 한다.
- 파일: `workflow.py`, `app.py`

**M5. 기술 조사 결과가 스칼라 필드만 보고서에 들어간다** (개선완료)
- 현상: `report.py`의 기술 조사 절은 `str/int/float` 값만 이어 붙인다. 검증: `principle`, `experiment_conditions`(리스트), `measurements`(dict 리스트), `limitations`(리스트)를 넣으면 `principle`만 출력된다. 설계서 B.2/C.6의 정량 수치 묶음(지표·값·단위·비교 기준·모델·하드웨어·문맥 길이·배치·정밀도·위치)이 보고서에 못 들어간다.
- 개선안: TechFindings 스키마(H3) 확정 후 항목별 렌더, 수치 묶음은 표.

**M6. 그래프 도식이 나오지 않고 불필요한 노드가 있다** (개선완료)
- 현상: `prepare`의 조건부 간선에 path_map이 없어 `draw_mermaid()` 결과가 `__start__ → prepare → __end__`뿐이다. README "Architecture(그래프 이미지)" 작성이 불가하다. `fan_out` 무동작 노드는 D.3(기술 조사 → 네 관점 직접 fan-out)과 다르다.
- 개선안: path_map 명시. 조건부 간선이 노드 이름 리스트를 반환하게 바꿔 `fan_out` 제거(검증 완료: 리스트 path_map + `add_edge([...], "evidence_check")`가 정상 동작하고 도식도 정상). mermaid/PNG 내보내기 옵션 추가.
- 파일: `workflow.py`, `app.py`

**M7. 라벨 집합과 TRL 구조** (개선완료)
- 현상: 설계서 C.1의 "판단 유보"가 허용 집합에 없어 `invalid_label` 처리. TRL은 라벨 하나로 축소되어 C.2 출력 항목(확인된 최고 단계, 단계별 충족 여부와 근거 ID, 미확인 증거 목록, 추정 근거 문구)이 State와 보고서에 없다.
- 개선안: 공통 미확인 라벨 허용, TRL PerspectiveResult 확장과 보고서 렌더.

**M8. LLM SUMMARY 숫자 가드의 오탐과 조용한 fallback** (개선완료)
- 현상: `\b\d+` 규칙이 한글이 붙은 숫자("2비트")를 입력에서 잡지 못하고 출력의 "2 비트"/"2-bit"는 잡는다(검증: 입력 `[]`, 출력 `['2']`). 정당한 요약도 "새 숫자"로 거부되어 규칙 기반으로 대체되며, manifest의 `generation_mode`만 바뀌고 사유가 남지 않는다.
- 개선안: 입력·출력에 같은 숫자 추출 규칙(`(?<![\w.])\d+(?:\.\d+)?` 등) 적용, fallback 사유를 metrics 또는 비치명 errors에 기록.

**M9. 그래프 내부 예외 시 부분 State가 유실된다** (개선완료)
- 현상: H1/H2 같은 내부 예외가 나면 `app.py`는 초기 State에 오류만 붙여 저장한다. 관점 결과·근거가 모두 사라져 재실행 비용이 크다.
- 개선안: `stream(..., stream_mode="values")`로 마지막 State를 유지하거나 checkpointer(MemorySaver)를 써서 실패 manifest에 마지막 State를 저장.

**M10. 의존성과 설치 재현성** (개선완료)
- 현상: `.venv`에는 51개 패키지만 설치되어 있다(Codex가 필요한 것만 설치). README의 `uv sync --group dev`는 315개 해석·229개 설치(torch 2.14, transformers, jupyter, faiss-cpu, psycopg2 소스 빌드 등)로 튜토리얼 의존성 전체를 상속한다. 이 머신에는 `pg_config`가 있지만 팀원 머신에서는 psycopg2 빌드가 실패할 수 있다. `uv lock --check` 통과, dry-run 해석 성공. venv는 Python 3.14.6.
- 개선안: 팀 차원에서 `pyproject.toml`을 실제 사용 패키지로 정리(합병 시), README 설치 절차를 깨끗한 환경에서 검증, `.python-version` 고정.

### 하 (여유 시)

- L1. (개선완료) 문서 정합성: HISTORY/DESIGN의 "Notion 404" 기록은 오래됐다. Notion 요구(참고 목차, REFERENCE 형식, TRL 추정 고지, README 샘플 형식, 산출물 파일명)를 문서에 반영해야 한다. 브랜치 README가 팀 README를 D 전용 내용으로 덮어써 합병 충돌이 예상된다. 최종 README는 Notion 샘플(Subject/Overview/Selected Technologies/Features/Tech Stack/Agents/Architecture/Directory Structure/Usage/Contributors) 형식이어야 한다.
- L2. (개선완료) 스켈레톤 잔재: 패키지 `__init__.py`들의 "Hello from skala-rag!" `main()`, 빈 `config.py`/`main.py`. 설정 검증이 `app.py`에 있고 `config.py`는 비어 있다(팀 합의 필요).
- L3. (개선완료) 근거 목록의 인용구 길이 제한이 없어 실제 데이터에서 부록이 폭증할 수 있다.
- L4. (개선완료) 200페이지 상한 검사(D.4)를 D에서도 수행할 수 있다(`Source.pages` 합계 > 200이면 치명 오류). 현재는 A의 `prepare`가 예외를 던지는 데 의존한다.
- L5. (개선완료) 산출물 파일명: 과제 제출명 `RAG-Output_판교_10반_이름.pdf`. `--report-name` 옵션 또는 수동 변경 안내.
- L6. (개선완료) 테스트 공백: 관점 서비스 예외 경로, prepare 치명 오류, `app.py` 실패 manifest, reducer 충돌 정책(결정 후), 보고서 목차·SUMMARY 길이 규칙.
- L7. (개선완료) 프로젝트가 패키지로 설치되지 않아(`[build-system]` 없음) `app.py`와 pytest의 `sys.path` 조정에 의존한다.
- L8. (개선완료) `_call_service`가 모든 `Exception`을 삼킨다. 서비스 내부에서 LangGraph `interrupt` 같은 제어 예외를 쓰면 오류로 기록된다(현재 HITL 없음, 참고).

## 3. 설계서·과제 요구 대비 점검표

| 항목 | 기준 | 검토 시 | 개선 후 | 비고 |
| --- | --- | --- | --- | --- |
| 병렬 fan-out / join | 설계서 D.3 | ○ | ○ | `fan_out` 노드 제거, 조건부 간선이 관점 노드 리스트 반환 |
| 보완 루프 최대 2회 | D.4 | ○ | ○ | 부족한 관점만 `Send`로 병렬 보완 |
| 규칙 검사(항목·라벨·근거 실재) | D.4 | ○ | ○ | `판단 유보` 허용, 부족 질문에 이유 포함 |
| 검토 LLM 의미 검사 | D.4, B.1 | △ | ○ | `LLMSemanticReviewer` 기본 연결(live), 캐시·호출 예산 |
| 조기 종료(설정·200p·파싱·근거 없음) | D.4 | △ | ○ | 200페이지 상한을 D에서도 검사 |
| recursion_limit 50 | D.4 | ○ | ○ | `--recursion-limit` |
| manifest(도구 호출·보완·시간·토큰) | D.4 | △ | ○ | 이벤트 집계, LLM 토큰, 충돌, 오류, 생성 방식 |
| live/replay 모드 | D.4, E.2 | ○ | ○ | |
| State 필드·reducer | D.1 | △ | ○ | 충돌 기록, 공유 Pydantic 스키마, run_config 항목 보강 |
| 종합에 총점·순위·추천 없음 | C.6, B.7 | ○ | ○ | LLM 출력 가드 유지 |
| 상충 쌍 6요소 | C.6 | △ | ○ | 판정 이유·조건 기반 문장, live에서 LLM 작성·검증 |
| SUMMARY 시작 / REFERENCE 끝 | Notion E | ○ | ○ | |
| 보고서 목차 | Notion 참고 목차 | △ | ○ | 분석 배경·기술 선정·시사점·한계점 반영 |
| REFERENCE 표기 형식 | Notion | ✗ | ○ | `format_reference` |
| TRL 추정 고지 | Notion C.1 | ✗ | ○ | SUMMARY, 4.4, 6장 |
| 문장별 인용 | B.2 | ○ | ○ | |
| 산출물 5종 | D.4 | ○ | ○ | `--report-name` |
| HTML→PDF | B.1 | △ | △ | 세 출력이 같은 섹션 모델을 사용해 단일화. HTML→PDF 변환기는 시스템 라이브러리 의존으로 미채택 |
| 한글 글꼴 | E.3 | △ | ○ | TrueType 임베드(AppleGothic 확인), 표 렌더링 |
| 지시문 데이터 취급, 키·개인정보 제외 | B.7 | ○ | ○ | |
| 설정 누락 안내 | E.2 | ○ | ○ | `.env` 자동 로드, `config.py` |
| CLI `python app.py --mode live\|replay` | E.2 | ○ | ○ | 옵션 확장, `--draw-graph` |

## 4. 통합(합병) 시 주의사항

1. `README.md`, `pyproject.toml`(dependencies 배열), `uv.lock`은 네 브랜치 모두 건드릴 가능성이 높다. `uv.lock`은 수동 병합하지 말고 합병 후 `uv lock`으로 재생성한다.
2. `sources`/`evidence` ID 규칙과 충돌 정책(H1), `metrics` 구조(H2)를 A/B/C 코드가 State에 쓰기 전에 합의한다.
3. 스키마(H3)를 먼저 확정하면 각 브랜치 어댑터 작업이 줄어든다.
4. `retry`의 소유(M1)를 정한다. 현재 계약은 B/C가 함께 구현해야 하는 단일 함수다.
5. 네 관점 노드는 스레드로 병렬 실행된다. 서비스의 스레드 안전성(FAISS 읽기, Tavily 클라이언트, 캐시 파일 쓰기)을 확인한다.
6. Codex 문서(DESIGN/HISTORY/PLAN)의 Notion 관련 기술을 갱신하고, 최종 README는 Notion 샘플 형식으로 통합 단계에서 새로 쓴다.

## 5. 검증 기록

```bash
cd skala-rag
.venv/bin/python -m pytest -q                      # 17 passed in 0.86s
.venv/bin/python app.py --mode replay --fixture --output-dir <scratch>/smoke   # exit 0, 산출물 5종
pdffonts <scratch>/smoke/report.pdf                # HYSMyeongJo-Medium CID TrueType emb=no
pdftoppm -png -r 70 -f 1 -l 1 report.pdf page      # 한글 정상 렌더링(poppler)
uv lock --check                                     # Resolved 315 packages, 최신
uv sync --dry-run --group dev                       # 229개 설치 예정(torch 2.14, psycopg2 2.9.13 등)
```

시나리오 스크립트 결과(`.venv/bin/python`, `src`를 `sys.path`에 추가):

| 시나리오 | 결과 |
| --- | --- |
| A. 두 관점 노드가 같은 `source_id`를 다른 내용으로 반환 | `ValueError: Conflicting record ID: shared-url` 로 실행 전체 실패 |
| B. 관점 노드와 보완 노드가 같은 `metrics` 키를 다른 값으로 반환 | `ValueError: Conflicting record ID: web_search_calls` 로 실행 전체 실패 |
| C. 이해관계자 서비스가 예외 발생 | 계속 진행. retry 2회, 오류 `stakeholder-0` 기록, 미확인 6항목, manifest `incomplete` |
| D. prepare가 예외 발생 | `prepare-0` 치명 오류 기록 후 `save`로 이동, `sources.json`·`run_manifest.json`만 생성 |
| E. `draw_mermaid()` | `__start__ --> prepare; prepare --> __end__` 두 간선만 출력 |
| F. 리스트 반환 조건부 간선 + 리스트 join (fan_out 노드 없이) | 정상 실행, 정상 도식 |
| G. 숫자 가드 정규식 | 입력 "2비트 양자화" → `[]`, 출력 "2 비트" → `['2']` (오탐) |

## 6. 권장 진행 순서(수정을 결정할 경우)

1. H1·H2: reducer 충돌 정책과 `metrics` 구조. 변경량이 작고 통합 전 필수.
2. H3: 공유 스키마. 팀 합의가 필요하지만 통합 효율이 가장 크다.
3. M3·M6·M4: `.env` 로딩, path_map과 fan_out 정리, run_config 항목. 각각 소규모.
4. H4: 검토 LLM 기본 구현과 캐시.
5. H5·H6: 종합 LLM 내용 생성, 보고서 목차·REFERENCE 형식·TRL 고지·replay SUMMARY·조사 처리.
6. M2: PDF 글꼴 임베드와 표.
7. M1·M5·M7·M8·M9, 하 항목, 테스트 보강, 문서 갱신.

## 7. 개선 결과 (2026-09-22, 개선완료)

모든 항목을 같은 날 반영했다. 코드는 커밋하지 않은 작업 트리 상태이며 원격 `feat/graph-output`은 `6612864` 그대로다.

| 항목 | 처리 | 확인 |
| --- | --- | --- |
| H1 | `merge_by_id`가 최초 값을 유지하고 다른 내용은 `conflicts`로 기록. 수집 시각·해시 등 가변 필드는 비교 제외. `collect_conflicts`가 manifest와 6장에 기록 | `test_state.py`, `test_graph.py::test_conflicting_source_ids_do_not_abort_the_run` |
| H2 | `metrics`를 append 이벤트 리스트로 변경, `metric_event`/`aggregate_metrics`, 노드별 실행 시간·실패 자동 기록, LLM `usage_metadata` 토큰 기록(`invoke_structured`) | `test_state.py`, `test_graph.py::test_metrics_events_are_aggregated_in_manifest`, live 실행 manifest |
| H3 | `graph/schemas.py`(RunConfig, Source, Evidence, Judgment/TRLJudgment, PerspectiveResult, TechFinding, MissingQuestion, ErrorRecord, Synthesis, Report), `validate_update`로 노드 경계 검증, `errors[*-schema]` | `test_schemas.py`, `test_graph.py::test_schema_violation_is_recorded_and_repair_is_requested` |
| H4 | `agents/review.py` `LLMSemanticReviewer`(별도 프롬프트·호출, 캐시, 예산, verdict·토큰 기록). `app.py --semantic-review auto\|on\|off`, `--max-review-calls`. 예산 초과·호출 실패는 경고 | `test_review.py`, `test_evidence_check.py`, gpt-5.4-mini 실제 호출 |
| H5 | 규칙 문장을 판정 이유·조건으로 생성(`describe_pair`), 관련 항목 조합 확장. `LLMSynthesisAgent`가 쌍별 이유·불확실성 작성, keep/순서, 쌍 단위 검증(근거 ID·숫자·우열)과 fallback, `llm_review`·`fallback_reason` 기록 | `test_output.py`, `test_llm_output.py`, live 실행 |
| H6 | 목차 SUMMARY→1 분석 배경→2 기술 선정(비교 축 표)→3 기술 개요→4 관점별 평가(표)→5 시사점→6 한계점→부록→REFERENCE. `format_reference`(논문/웹 형식), TRL 고지와 단계 상세, 규칙 기반 SUMMARY(1200자 이내), 조사 처리 | `test_output.py::test_report_follows_reference_outline_and_filters_unknown_ids`, `test_reference_format_for_papers_and_web_pages` |
| M1 | `retry`를 선택형으로 바꾸고 기본은 부족한 관점만 `Send`로 재호출(`retry_mode`, 자기 관점 질문만). retry_count는 `retry` 노드에서 한 번 증가 | `test_graph.py::test_default_repair_reinvokes_only_failing_perspective_with_its_questions` |
| M2 | TrueType 글꼴 탐색·임베드(`RAG_PDF_FONT` → AppleGothic → NanumGothic → malgun → CID 대체), 표를 Markdown/HTML/PDF에 렌더, 세 출력이 같은 섹션 모델 사용. HTML→PDF 변환기는 시스템 라이브러리 의존으로 미채택 | `pdffonts`: AppleGothic emb=yes, `test_output.py::test_save_outputs_uses_report_name_and_reports_pdf_font` |
| M3 | `app.py`가 `load_dotenv()` 호출 | `test_cli.py` |
| M4 | `RunConfig`에 as_of, budget, max_paper_pages, background, selection_rationale, report_title 추가. CLI `--technologies --domain --as-of --web-search-max --fetch-max --tool-timeout --tool-retries --max-paper-pages` | `test_cli.py::test_cli_report_name_and_options` |
| M5 | `TechFinding` 렌더링(원리·실험 조건·한계·추가 항목·수치 표) | fixture 보고서 3장 |
| M6 | path_map 명시, `fan_out` 제거, `draw_mermaid`, `--draw-graph`, `docs/graph.mmd`, README Architecture | `test_graph.py::test_mermaid_shows_fan_out_join_and_repair_loop` |
| M7 | `UNKNOWN_LABELS`(미확인·판단 유보) 공통 허용, `TRLJudgment`와 보고서 단계 상세 | `test_schemas.py`, `test_output.py::test_trl_stage_details_and_summary_limit` |
| M8 | 숫자 추출 규칙 통일(`NUMBER_PATTERN`), fallback 사유와 실패 횟수를 manifest에 기록 | `test_llm_output.py::test_number_guard_treats_korean_suffixes_consistently` |
| M9 | `stream(values)`로 마지막 State를 유지해 실패 manifest에 저장 | `test_cli.py::test_cli_failing_services_module_writes_failure_manifest` |
| M10 | `graph` 의존성 그룹(`uv sync --only-group graph --only-group dev`), hatchling build-system, 깨끗한 환경에서 설치·테스트 검증(52개 패키지). 기본 의존성 목록 정리는 팀 결정이라 합병 체크리스트로 이관, `.python-version`은 .gitignore 대상이라 README에 검증 버전 기재 | `UV_PROJECT_ENVIRONMENT` 검증 |
| L1 | README를 과제 샘플 형식으로 재작성, DESIGN 전면 개정, HISTORY/PLAN 갱신(Notion 요구 반영) | 문서 |
| L2 | `__init__.py` 정리, `config.py` 구현(설정 로드·검증). `main.py`는 팀 스켈레톤이라 유지 | |
| L3 | 인용 300자, 조건 200자 제한 | `test_output.py::test_trl_stage_details_and_summary_limit` |
| L4 | `prepare` 뒤 논문 페이지 합계 검사(치명) | `test_graph.py::test_paper_page_limit_is_fatal` |
| L5 | `--report-name` | `test_cli.py` |
| L6 | 테스트 17 → 47개 | `pytest -q` |
| L7 | `[build-system]` hatchling, `packages = ["src/skala_rag"]` | `uv lock` |
| L8 | `_call_service`가 `GraphBubbleUp`을 재전파 | 코드 |

### 검증 (개선 후)

```bash
.venv/bin/python -m pytest -q                                            # 47 passed
.venv/bin/python app.py --mode replay --fixture --report-name RAG-Output_판교_10반_test --output-dir <scratch>   # exit 0, 7쪽 PDF
pdffonts <scratch>/RAG-Output_판교_10반_test.pdf                           # AppleGothic TrueType emb=yes
UV_PROJECT_ENVIRONMENT=<clean> uv sync --only-group graph --only-group dev && <clean>/bin/python -m pytest -q   # 52 packages, 47 passed
.venv/bin/python app.py --draw-graph -                                     # 전 노드·간선 출력
```

OpenAI API 확인(가이드 폴더 `.env`의 키 사용, 값 미출력): `gpt-5.4-mini`, `gpt-5.4`, `gpt-5-mini`, `gpt-4.1`, `gpt-5.6-luna` 모두 존재. D 코드 경로(`invoke_structured`, `ReviewVerdict`)로 구조화 출력 호출 성공, 토큰 163. live 경로 전체 실행 결과는 아래에 추가한다.
live 경로 전체 실행(fixture 서비스 + 검토 LLM + 종합 LLM + SUMMARY LLM, `gpt-5.4-mini`, 2026-09-22):

| 항목 | 결과 |
| --- | --- |
| 실행 시간 | 27.7초, 오류 0건, status `incomplete`(합성 근거가 판정을 뒷받침하지 않으므로 정상) |
| 검토 LLM | 24항목 호출 24회, 모두 unsupported 판정. 보완 2회(관점별 Send 8회)에서 캐시로 추가 호출 0회 |
| 종합 LLM | 검증 통과 판정이 없어 후보 쌍 0개 → 호출 생략(규칙 기반) |
| SUMMARY LLM | 생성·검증 통과(`report_mode: llm_assisted`), 두 기술 언급, 근거 ID 인용, 새 숫자 없음 |
| 토큰 | LLM 호출 25회, 입력 12,215 / 출력 1,663 / 합계 13,878 (manifest `metrics.totals.tokens`) |

모델 ID 우려에 대한 답: 설계서의 `gpt-5.4-mini`는 이 키로 조회되는 실제 모델이며(`gpt-5.4-mini-2026-03-17` 스냅샷 존재), 구조화 출력과 live 경로 호출이 모두 성공했다. replay·fixture 실행은 LLM을 호출하지 않으므로 모델 ID와 무관하다.
