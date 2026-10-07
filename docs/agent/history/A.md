# 트랙 A 작업 이력 — Supervisor 그래프와 State

- 브랜치: `sup/graph`
- 이 파일은 트랙 A 담당만 쓴다. 다른 트랙은 읽기만 한다.
- 새 항목은 맨 아래에 덧붙인다. 이미 쓴 항목은 고치지 않는다(틀렸으면 새 항목으로 정정한다).
- 푸시하기 전마다 기록한다. 삭제·이름 변경, 다른 트랙 파일 수정, 병합 충돌 해결은 그 커밋마다 따로 기록한다.
- 병합 충돌이 나면 충돌한 파일 이름으로 이 폴더를 검색해(`grep -n "<파일 이름>" docs/agent/history/*.md`) 양쪽이 왜 바꿨는지 확인한 뒤에 해결한다.

항목 형식:

```markdown
## YYYY-MM-DD HH:MM · <브랜치> · <작성자>

**무엇을**: 한 줄 요약
**왜**: 고치려던 문제나 근거
**바꾼 파일**:
- `경로` — 바꾼 함수·클래스와 내용 (삭제·이름 변경은 반드시 적는다)
**남의 파일**: 다른 트랙 파일을 고쳤으면 무엇을 왜
**인터페이스 영향**: 다른 트랙이 쓰는 State 필드·함수 시그니처·반환 형태·상수가 바뀌었는지
**충돌 시 지켜야 할 것**: 지우거나 되돌리면 안 되는 것과 그 이유
**확인**: 실행한 테스트와 결과
```

<!-- 아래부터 항목을 덧붙인다 -->

## 2026-10-07 14:05 · sup/graph · San Kim

**무엇을**: Supervisor 구조로 가기 위한 공통 State 제어 필드·Pydantic 모델·상한 상수를 추가 (다른 트랙이 먼저 import할 수 있게 코드 변경 없이 모델만 합친다)

**왜**: 하위 에이전트(B)·품질 평가(C)·보고서(D) 트랙이 같은 State 필드 이름과 재작업 지시·품질 결과 형태를 보고 작업해야 한다. 그래프 본체보다 계약을 먼저 합쳐야 병렬 작업이 가능하다.

**바꾼 파일**:
- `src/skala_rag/graph/state.py` — `GraphState`에 제어 필드 추가: `run_id`, `next`, `step_count`, `agent_status`, `rework_requests`, `decision_log`, `quality_result`, `quality_attempts`. reducer 없음(Supervisor만 쓴다). 기존 `retry_count`·`missing_questions`는 아직 남겨 둠(그래프 교체 때 제거).
- `src/skala_rag/graph/schemas.py` — 상수 `AGENTS`, `QUALITY_ITEMS`, `MAX_REWORK_PER_AGENT=2`, `MAX_QUALITY_LOOPS=2`, `MAX_SUPERVISOR_STEPS=20`, `QUALITY_THRESHOLD=4`, `DECISION_LOG_LIMIT=30`, `EVIDENCE_QUOTE_LIMIT=1200`; 리터럴 `AgentState`, `QualityAction`; 모델 `AgentStatus`, `ReworkRequest`, `Decision`, `QualityItem`(score 비우면 rule/llm 중 낮은 쪽으로 채움), `QualityInstruction`, `QualityResult`. `validate_update`가 `evidence[*].quote`를 `EVIDENCE_QUOTE_LIMIT`자로 자름.
- `tests/test_schemas.py` — 새 모델·상수·quote 절단 테스트 7개 추가

**남의 파일**: 없음

**인터페이스 영향**: State 필드 추가(제거는 없음). 새 상수·모델은 `skala_rag.graph.schemas`에서 import한다. `evidence.quote`가 1200자를 넘으면 그래프 경계에서 잘린다.

**충돌 시 지켜야 할 것**:
- `GraphState`의 제어 필드 블록과 `schemas.py`의 상수·모델은 그대로 둔다. B·C·D가 이 이름으로 import한다.
- `QualityItem.score`가 `None`일 때 채우는 `_fill_score`를 지우면 C가 score를 생략한 결과가 검증에 실패한다.
- `validate_update`의 quote 절단은 `continue` 분기 뒤에 있어야 한다(유효하지 않은 레코드는 여전히 버려야 한다).

**확인**: `pytest -q --ignore=tests/tools --ignore=tests/evaluation --ignore=tests/agents` 70 passed

## 2026-10-07 14:40 · sup/graph · San Kim

**무엇을**: 고정 병렬 파이프라인을 Supervisor 허브 그래프로 교체. `supervisor` 노드가 State를 보고 다음 노드를 고르고, 관점 에이전트는 `Send`로 네 키만 받으며, 근거 충분성 평가·재작업·품질 루프를 Supervisor가 결정한다.

**왜**: 과제 필수 항목(하위 에이전트 간 직접 간선 금지, 순서·스텝 수 하드코딩 금지, 근거 평가 후 보고서, 부족 시 재작업, 품질 평가 루프). 기존 그래프는 `technical → 4관점`, `repair → evidence_check`, `report → save`가 직접 간선이었고 품질 루프와 제어 필드가 없었다.

**바꾼 파일**:
- `src/skala_rag/graph/workflow.py`
  - 추가: `supervise(state, semantic_review)` — 결정 순서: 치명 오류→`save`; 결정 횟수 상한→보고서가 없으면 `report` 한 번 뒤 `save`(사유 `step_limit`); `technical_findings` 없음→`technical`; `pending` 관점→실행; 돌아온 관점이 있으면 `check_evidence`를 호출해 `evidence_check`에 넣고 통과 못 한 항목을 관점별 `rework_requests`(`attempt` 포함)로 만들어 그 관점만 재실행(상한 `MAX_REWORK_PER_AGENT`), 아니면 `synthesis`→`report`→`quality`; 품질 결과 `pass`→`save`, `rewrite_report`→`quality_attempts+1` 후 `report`, `recollect`→`quality_result["rework_requests"]`로 해당 관점 재실행, 상한이면 `action`을 `accept_with_limits`로 바꿔 `report` 한 번 더 뒤 `save`. 결정마다 `next`, `step_count`, `agent_status`, `rework_requests`, `decision_log`(최근 `DECISION_LOG_LIMIT`개, `reason`은 한국어 문장) 갱신.
  - 추가: `send_payload(state, name)` — `run_config`, `{name}_analysis`, `rework_requests`(그 관점 것만), `known_evidence_ids`만 넘긴다. `placeholder_quality` — 항상 통과하는 임시 품질 평가기. `new_agent_status`. `ROUTES`, `SEND_PAYLOAD_KEYS`.
  - `PipelineServices`: `quality_evaluator: Service | None = None` 추가, `retry` 필드 삭제.
  - `build_graph`: `checkpointer` 인자 추가. 노드 `supervisor`, `quality` 추가. `evidence_check`, `retry`, `repair`, `technical_failed` 노드 삭제(기술 결과 누락 검사는 `technical` 노드 안에서 `technical-0-coverage` 치명 오류로 기록). `prepare`와 `save`를 뺀 모든 노드가 `supervisor`로 돌아온다. `route`는 `state["next"]`만 읽고 관점은 `Send`로 보낸다.
  - `_call_service`: 오류 키의 회차를 `retry_count` 대신 페이로드 `rework_requests[*].attempt`(`_round`)로 정하고, `round_` 인자로 직접 줄 수 있다. 허용 키 검사·스키마 검증은 그대로. `quality` 노드는 `QualityResult`로 검증하고 실패하면 `quality-{n}-schema` 오류와 통과 대체값(`evaluator: "fallback"`)을 넣는다.
  - `initial_state`: `run_id`(uuid4, 인자로 지정 가능), 제어 필드 초기값 추가. `retry_count`, `missing_questions` 삭제. `MAX_RETRIES` 상수 삭제.
- `src/skala_rag/graph/state.py` — `GraphState`에서 `missing_questions`, `retry_count` 삭제.
- `tests/conftest.py` — `make_services`의 `retry` 인자 삭제.
- `tests/test_graph.py` — 새 구조로 전면 재작성(27개): 모든 하위 노드의 다음 노드가 `supervisor`뿐인지(컴파일된 간선), `Send` 페이로드가 네 키뿐인지, 부족한 관점만 자기 지시로 재호출, 재작업으로 채워지면 다음 턴에 보고서, 2회 후에도 부족하면 사유 남기고 진행, `rewrite_report` 2회 뒤 `accept_with_limits`, `recollect`는 해당 관점만, 재작업 횟수 없으면 `accept_with_limits`, 잘못된 품질 결과 기록, 최악 경로 19회 ≤ 상한, 항상 미달 서비스에서도 상한 종료, 결정 로그 상한, 예외는 `failed`로 기록 후 계속, `prepare` 치명 오류는 바로 `save`, 하위 에이전트가 제어 필드를 반환하면 버리고 스키마 오류로 기록.
- `tests/test_cli.py` — `--draw-graph` 검사 간선을 `market --> supervisor;`, `supervisor -.-> quality;`로 변경.

**남의 파일**: `tests/test_integration.py`(B) — `test_full_graph_with_stubbed_branches_completes`의 `result["retry_count"] == 0` 한 줄을 `result["agent_status"]["market"]["attempts"] == 0`으로 바꿈. `retry_count`가 State에서 없어져 KeyError가 나기 때문. 그 밖의 변경 없음.

**인터페이스 영향**:
- State에서 `retry_count`, `missing_questions` 제거(보고서의 한계점 문장과 manifest의 `retry_count`는 `agent_status`·`evidence_check["items"]`로 옮겨야 한다 — D).
- 관점 서비스 입력이 State 전체에서 `run_config`, `{name}_analysis`, `rework_requests`, `known_evidence_ids` 네 키로 바뀜. `retry_mode`·`missing_questions`·`evidence`는 더 이상 넘어오지 않는다 — B.
- `PipelineServices.retry` 삭제, `quality_evaluator` 추가 — C가 합쳐지면 `app.py`에서 조립.
- `evidence_check`의 형태(`passed`, `items`)는 그대로.
- 최악 경로 결정 횟수는 19회(재작업 2회 + 재수집 2회가 각각 재작업 1회를 더 부르는 경우)로 `MAX_SUPERVISOR_STEPS=20`을 유지한다.

**충돌 시 지켜야 할 것**:
- `supervise`의 결정 순서(치명→상한→technical→pending→근거 평가→synthesis/report/quality→품질 결과)를 바꾸지 않는다. 테스트가 결정 로그 순서를 그대로 검사한다.
- `send_payload`의 네 키 이외를 추가하지 않는다. B의 서비스가 이 키만 받는 것을 전제로 한다.
- 하위 노드에서 `supervisor` 이외로 가는 간선을 되살리지 않는다(과제 필수 항목).
- `_call_service`의 허용 키 검사와 `validate_update` 호출을 지우지 않는다. 하위 에이전트가 제어 필드를 덮어쓰는 것을 막는 유일한 장치다.

**확인**: `pytest -q --ignore=tests/tools --ignore=tests/evaluation --ignore=tests/agents` 82 passed; `app.py --mode replay --fixture --output-dir outputs/demo` 정상(Supervisor 결정 6회, manifest `complete`)

## 2026-10-07 15:10 · sup/graph · San Kim

**무엇을**: 실행 기반(run_id·체크포인터·LangSmith 메타데이터·fixture 재작업 대응·도식 재생성)과 그에 대한 테스트 추가

**왜**: 중단 후 재개와 트레이스 추적이 안 됐다. run_id 하나로 State, manifest, LangSmith 트레이스를 찾을 수 있어야 하고, fixture 서비스가 새 입력(네 키 페이로드와 `rework_requests`)으로도 재작업 흐름을 흉내 내야 전체 루프를 키 없이 검증할 수 있다.

**바꾼 파일**:
- `app.py` — `main`: `build_graph(..., checkpointer=InMemorySaver())`; `graph.stream` config에 `run_name`, `tags`(`skala-rag`, 모드, fixture), `metadata.run_id`, `configurable.thread_id=run_id` 추가; 실행 시작 때 `run_id:` 출력. `--checkpoint-db`·`--resume`는 SQLite 체크포인터 의존성이 없어 보류(필요하면 D에게 `langgraph-checkpoint-sqlite` 추가 요청).
- `src/skala_rag/graph/demo.py` — `_perspective`: 페이로드의 `rework_requests`와 `{name}_analysis`를 읽어 재작업이면 이전 판정을 유지하고 요청 항목만 다시 만든다. metrics에 `rework_items`, `known_evidence` 추가.
- `docs/graph.mmd` — `app.py --draw-graph`로 재생성(Supervisor 허브).
- `tests/test_graph.py` — 체크포인터로 `technical` 뒤에서 멈췄다가 같은 `thread_id`로 재개하면 결정이 이어지고 결정마다 체크포인트가 남는지, fixture 서비스가 재작업 항목만 다시 내는지 추가.
- `tests/test_cli.py` — fixture 실행 출력에 32자 `run_id`가 있는지 추가.

**남의 파일**: 없음

**인터페이스 영향**: 없음. manifest에 넣을 제어 필드(`run_id`, `step_count`, `agent_status`, `decision_log`, `quality_result`, `quality_attempts`)는 State에 모두 있으며 D가 `save_outputs`에서 읽으면 된다.

**충돌 시 지켜야 할 것**:
- `app.py`의 stream config에서 `configurable.thread_id`를 지우면 체크포인터가 있는 그래프가 실행되지 않는다(LangGraph가 thread_id를 요구한다).
- `demo.py`의 `_perspective`가 `state["evidence"]`를 읽도록 되돌리면 안 된다. 페이로드에는 `known_evidence_ids`만 있다.
- `docs/graph.mmd`는 손으로 합치지 말고 `app.py --draw-graph docs/graph.mmd`로 다시 만든다.

**확인**: `pytest -q --ignore=tests/tools --ignore=tests/evaluation --ignore=tests/agents` 84 passed; `app.py --mode replay --fixture --output-dir outputs/demo` 정상

## 2026-10-07 15:40 · sup/graph-contract · San Kim

**무엇을**: `ReworkRequest.attempt`가 0을 받도록 수정(기본값 0, 0 이상)

**왜**: 품질 평가 노드(C)는 재수집 요청의 `attempt`를 0으로 두고 Supervisor가 채우기로 돼 있는데, 모델이 1 이상만 받아 C의 `recollect` 결과가 검증에서 통째로 버려질 뻔했다. Supervisor는 재수집을 보낼 때 `attempt`를 덮어쓰므로 0을 받아도 문제없다.

**바꾼 파일**:
- `src/skala_rag/graph/schemas.py` — `ReworkRequest.attempt`: `Field(default=1, ge=1)` → `Field(default=0, ge=0)`
- `tests/test_schemas.py` — 기본값 0, 음수 거부로 기대값 수정

**남의 파일**: 없음

**인터페이스 영향**: `ReworkRequest.attempt`가 0을 허용한다. Supervisor가 보내는 요청에서는 여전히 1부터 시작한다.

**충돌 시 지켜야 할 것**: `attempt`의 하한을 다시 1로 올리면 C의 재수집 요청이 버려진다.

**확인**: `pytest -q tests/test_schemas.py` 12 passed
