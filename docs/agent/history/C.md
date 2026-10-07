# 트랙 C 작업 이력 — 보고서 품질 평가 노드

- 브랜치: `sup/quality`
- 이 파일은 트랙 C 담당만 쓴다. 다른 트랙은 읽기만 한다.
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

## 2026-10-07 14:10 · sup/quality · piso

**무엇을**: 보고서 품질 평가기 `QualityEvaluator`를 추가했다. Groundedness·중립성·편향 통제·관점 커버리지를 규칙 검사로 1~5점 매기고, Groundedness와 중립성은 LLM Judge를 별도 호출로 더해 낮은 쪽을 항목 점수로 쓴다. 미달이면 보고서 작성기가 읽을 수정 지시(`instructions`)와, 재수집이 필요할 때 재작업 지시(`rework_requests`)를 만든다.

**왜**: 보고서가 만들어진 뒤 품질을 평가해 미달이면 되돌리는 루프가 과제 필수 항목이다. 되돌릴 곳을 구분하려면 점수만으로는 부족해서, 어느 절의 어느 문장을 어떻게 고칠지(보고서 재작성)와 어느 판정의 근거를 다시 모을지(재수집)를 함께 돌려준다.

**바꾼 파일**:
- `src/skala_rag/agents/quality.py` (신규)
  - `QualityEvaluator(judge_model=None, *, threshold=4, max_judge_calls=6)`. 호출은 `(state) -> {"quality_result": {...}, "metrics": [...]}`. State는 읽기만 하고 `quality_attempts`나 상한은 건드리지 않는다. `judge_model`이 `None`이면 규칙 검사만 하며 같은 입력에 항상 같은 결과가 나온다. 마지막 평가의 측정값은 `evaluator.last_measurements`와 `metrics`의 `purpose="evaluate"` 이벤트(`measurements` JSON 문자열)에 남는다
  - `parse_report`, `resolve_citations`, `split_sentences`: `report["sections"]`를 문장·표 행으로 읽는다. `report["citation_map"]`이 있으면 `[1]`을 근거 ID로 바꾸고, 없으면 `[근거 ID]`를 그대로 쓴다. `[상충]`·`[REDACTED]`·`[R1]` 같은 대괄호는 인용으로 보지 않는다. `부록`과 `REFERENCE`는 문장 평가에서 뺀다
  - `groundedness_rule`, `neutrality_rule`, `bias_rule`, `coverage_rule`: 항목별 규칙 점수. 점수 구간은 모듈 상단 상수(`GROUNDEDNESS_BANDS`, `BIAS_MULTI_SOURCE_BANDS`, `COVERAGE_BANDS`, `WEAK_COMPARATIVE_BANDS` 등)에 있다
  - LLM Judge: `JUDGE_GROUNDEDNESS_PROMPT`, `JUDGE_NEUTRALITY_PROMPT`(생성과 다른 LLM 지시문, 구조화 출력 `JudgeVerdict`). Judge가 지적한 `quote`가 실제 보고서에 있는 글인지 `QualityEvaluator._locate`로 확인하고 없으면 그 지적을 버린다. 지적이 모두 버려진 묶음의 점수는 쓰지 않는다. Judge 호출이 실패하면 그 항목은 `llm_score=None`으로 두고 `reasons`와 `metrics`(`judge_errors`)에 남긴다. 호출 수는 평가 한 번당 `max_judge_calls` 이하이고 중립성 호출 1회를 먼저 확보한다
  - `QualityResult`, `QualityItem`, `QualityInstruction`, `QualityRework`: 트랙 A가 `graph/schemas.py`에 같은 이름의 모델을 합치기 전까지 쓰는 임시 모델이다. 합쳐지면 이 파일의 정의를 지우고 import로 바꾼다
- `tests/test_quality.py` (신규) — 29개. 가짜 Judge로 점수 결합·환각 지적 폐기·예외 대체·호출 예산을 확인한다

**남의 파일**: 없음 (`llm_output.RANKING_PATTERN`, `synthesis.FAVORABLE`/`CAUTIOUS`, `llm_utils.invoke_structured`, `graph.state.metric_event`는 import만 한다)

**인터페이스 영향**: 새 모듈이라 기존 코드에 변화는 없다. 다른 트랙이 알아야 할 것:
- 트랙 A: `action`은 `pass`·`rewrite_report`·`recollect` 중 하나만 낸다. `accept_with_limits`는 상한을 본 뒤 Supervisor가 정한다. `rework_requests`의 `attempt`는 0으로 두므로 Supervisor가 채운다. 이 모듈이 쓰는 State 필드는 `quality_result`뿐이다
- 트랙 D: `instructions[*].section`은 보고서의 장 제목과 같은 문자열이다(`SUMMARY`, `3. 기술 개요`, `4.1 시장성`, `5. 시사점`, `6. 한계점`). 장 제목이나 `(근거 미확인)` 표시를 바꾸면 평가가 어긋나니 알려 달라. 도메인 판정은 기술별 논문 한 편이 근거라 구조적으로 단일 출처인데, 6장 한계점에 "단일 출처"·"논문 한 편" 같은 말로 밝히지 않으면 편향 통제가 3점으로 제한된다. 한계점에 이 문장을 기본으로 넣어 주면 불필요한 루프가 생기지 않는다
- 트랙 B: 편향 통제는 근거의 `source_id`가 정확해야 셀 수 있고, 같은 사이트의 서로 다른 페이지는 한 출처로 센다(논문은 `source_id` 기준)

**충돌 시 지켜야 할 것**:
- `QualityResult` 등 임시 모델을 A의 모델로 바꿀 때 필드 이름(`score`, `rule_score`, `llm_score`, `reasons`, `instructions`, `rework_requests`)을 그대로 유지해야 한다. 이 이름을 A의 Supervisor와 D의 보고서 작성기가 읽는다
- `_locate`를 느슨하게 하거나 없애지 않는다. Judge가 보고서에 없는 문장을 지적하면 보고서 작성기가 존재하지 않는 문장을 고치려 한다
- 중립성 규칙에서 부정문 처리(`NEGATION`)를 빼면 정적 문구("총점이나 순위 대신…", "도입 추천을 제시하지 않는다")가 모두 감점된다
- 도메인 단일 출처를 한계점에 밝힌 경우 편향 통제의 다중 출처 비율 계산에서 빼는 처리(`bias_rule`)를 되돌리지 않는다. 구조적으로 단일 출처인 판정에 항상 재수집을 요청하게 된다

**확인**: `pytest -q --ignore=tests/tools --ignore=tests/evaluation --ignore=tests/agents` 92 passed, `pytest -q` 116 passed, `app.py --mode replay --fixture` 정상. 핵심 규칙(부정문 처리, 존재하지 않는 인용, 도메인 단일 출처 밝힘, 인용문 확인)을 하나씩 꺼 보고 해당 테스트가 실패하는지 확인했다.

첫 실제 측정(캐시된 웹 자료로 `--mode replay`, LLM 종합·보고서 켬, 보고서는 `[근거 ID]` 인용 형식):
- Groundedness: 서술 단위 116개 모두 인용에 닿음(규칙 5점). Judge는 근거 구절보다 넓게 쓴 문장을 지적해 2~4점대(묶음마다 다름, 3장 기술 개요 묶음이 가장 낮음)
- 중립성: 약한 비교 표현 2건("더 유리하다" 조건 서술, 논문이 보고한 baseline 대비 "더 나은 정확도")이 있었고 둘 다 우열 서술이 아니었다. 처음 구간(1건 4점, 2건 3점)에서는 미달이 됐으므로 1~2건은 4점, 3~4건 3점, 5건 이상 2점으로 조정했다
- 편향 통제: 서로 다른 출처 2개 이상을 인용한 판정 비율이 5%(1/19). 시장성·이해관계자·TRL 판정이 대부분 근거 1개만 인용하기 때문이다. 구간은 그대로 두었다. 이 값은 수집 쪽 특성이라 구간을 낮춰 맞추면 지표가 의미를 잃는다. 이 상태에서는 편향 통제가 1점이라 `recollect`가 나온다. 한 출처 최대 비중 48%, 기술별 인용 근거 수 27/26, 긍정 판정 비율 차이 0.23은 모두 기준 안이다
- 관점 커버리지: 24개 중 근거 확인 19개(79%), 모든 (관점, 기술) 조합에 통과 판정이 있어 4점
- 실제 Judge(`gpt-5.4-mini`) 호출 6회, 약 3.8만 토큰. 처음 쓴 Judge 지시문은 점수 기준이 5·3·1점뿐이라 대부분 묶음에 1점을 줘서 4점·2점 기준과 "구절을 풀어 쓴 문장은 뒷받침으로 본다"는 규칙을 더했고, 인용문 대조는 칸·문단·인용 표기를 건너뛴 인용까지 허용하도록 넓혔다. 이후 3회 실행에서 지적한 문장이 모두 보고서 원문과 연결됐다

## 2026-10-07 14:35 · sup/quality · piso

**무엇을**: `supervisor`(보고서 인용 번호화, PDF 10쪽 제한)를 병합하고, 번호 인용 형식의 실제 보고서로 평가기를 다시 확인했다. 평가기 코드는 바꾸지 않았고 테스트 도우미만 고쳤다.

**왜**: 병합 뒤 `build_report`가 본문 인용을 `[n]`과 `report["citation_map"]`으로 만들어서, 인용 형식 비교 테스트가 쓰던 "근거 ID → 번호" 변환 도우미가 이미 번호인 보고서의 `citation_map`을 지워 실패했다.

**바꾼 파일**:
- `tests/test_quality.py` — `numbered`를 `as_evidence_ids`(번호 → 근거 ID, `citation_map` 제거)로 바꿨다. `make_state`가 만드는 보고서가 이미 번호 형식이므로, 번호 형식(기본)과 옛 형식(`[근거 ID]`)이 같은 결과를 내는지와 `[ghost]`·`[99]` 인용이 두 형식 모두 Groundedness 1점인지 확인한다

**남의 파일**: 없음. 병합에서 충돌은 없었다

**인터페이스 영향**: 없음

**충돌 시 지켜야 할 것**: `resolve_citations`는 `citation_map`이 있을 때 `[n]`을 번호로, 없을 때 `[근거 ID]`를 그대로 읽는다. 본문 인용 형식이나 `citation_map` 키 형태(문자열 번호 → 근거 ID)를 바꾸면 평가기가 존재하지 않는 인용으로 보고 Groundedness를 1점으로 준다

**확인**: `pytest -q --ignore=tests/tools --ignore=tests/evaluation --ignore=tests/agents` 97 passed, `pytest -q` 121 passed. 저장해 둔 replay State로 새 `build_report`를 다시 만들어 평가: 번호 인용 48개를 모두 해석했고, 서술 단위 67개가 모두 인용에 닿으며(규칙 5점) 중립성 5점이다(D가 문장을 줄이면서 약한 비교 표현이 사라짐). 편향 통제는 다중 출처 판정 비율 5%로 1점, 커버리지 79%로 4점이다. 실제 Judge 호출 6회에서 지적한 문장 18건이 모두 보고서 원문과 연결됐고 Groundedness 3점, 중립성 5점이 나왔다
