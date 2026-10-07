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
