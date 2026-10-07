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

## 2026-10-07 14:33 · sup/quality · piso

**무엇을**: (1) 보고서 본문의 근거 인용을 문장 중간의 `[번호]`에서, 문장(절) 끝에 모은 각주 표시 `(1)(2)`로 바꾸고 보고서 끝에 "각주" 절을 두었다. 평가기는 새 표기를 읽고 각주·출처가 State의 근거와 맞는지 확인한다. (2) 편향 통제 점수를 "출처 2개 이상 인용한 판정의 비율"에서 "판정별 출처 수 점수의 평균"으로 바꿔, 근거가 하나뿐인 판정이 평균 3점이 되게 했다.

**왜**:
- 본문 문장 중간에 근거 표시가 끼어 읽기 불편하다는 검토 의견이 있었다. 표시는 문장 끝으로 모으고 근거와 출처는 보고서 끝 각주에서 보게 한다
- 실제 보고서에서 시장성·이해관계자·TRL 판정의 대부분이 근거를 1개만 인용해(19개 중 18개) 기존 방식에서는 편향 통제가 1점으로 급락했다. 근거가 하나뿐인 것을 최하점으로 보는 것은 과하다

**바꾼 파일**:
- `src/skala_rag/agents/quality.py`
  - `resolve_citations(..., parens=False)`: `(1)`, `(1)(2)`, `(1, 2)`를 인용으로 읽는다(`citation_map`이 있고 `parens=True`인 장에서만). 문단 맨 앞의 `(1) 항목`(목록 번호)과 네 자리 이상 숫자(연도)는 인용으로 보지 않는다. 요약·3·4·5장만 `parens=True`라서 6장 등의 `(1) … (2) …` 열거는 영향이 없다. 기존 `[n]`, `[근거 ID]`도 그대로 읽는다
  - `parse_report`: "각주" 절(이전 이름 "부록"도 허용)과 REFERENCE 절을 본문과 따로 읽어 `parsed.footnotes`, `parsed.references`에 담는다. 두 절은 문장 평가·중립성 검사에서 빠진다. `_read_footnotes`, `_read_references` 추가
  - `footnote_findings`(신규): 본문이 인용한 각 번호에 대해 각주 행이 있는지, 각주의 기술이 근거의 기술과 같은지, 출처 라벨(`[R1]`)이 REFERENCE에 있고 그 항목이 근거의 출처(URL 또는 제목)와 맞는지, 인용 구절이 근거 원문과 맞는지 확인한다. 따라갈 수 없는 인용(각주 절·행 없음, 출처 미등록, REFERENCE 항목 없음)은 Groundedness 1점, 내용 불일치는 최대 2점(`FOOTNOTE_MISMATCH_CAP`)이다. 인용 구절 칸이 비어 있으면(쪽수 제한으로 줄인 판) 구절 대조는 건너뛴다. `citation_map`이 없는 옛 형식 보고서는 검사하지 않는다
  - `bias_rule`: `BIAS_MULTI_SOURCE_BANDS` 삭제, `SOURCE_COUNT_SCORES` 추가. 판정 하나의 점수는 서로 다른 출처 1개 3점, 2개 4점, 3개 이상 5점이고 항목 점수는 그 평균을 반올림한 값이다(3.5는 4점). 도메인 판정이 단일 출처인 것은 한계점에 밝혔으면 평균에서 빼고, 밝히지 않았으면 3점으로 세면서 최대 3점으로 제한하는 기존 규칙도 그대로다. 측정값 `multi_source_ratio`는 `mean_source_score`, `judgments_by_source_count`로 바뀌었다
  - `_plain`: Judge 인용문 대조에서 `(1)` 표시도 지운 글로 비교한다
- `tests/test_quality.py` — 각주 표시·각주 검증·편향 점수 테스트 추가(37개)
- 남의 파일(아래 참고): `src/skala_rag/agents/report.py`, `src/skala_rag/agents/llm_output.py`, `tests/test_output.py`, `tests/test_llm_output.py`

**남의 파일**: 트랙 D 파일을 최소한으로 고쳤다. 같은 파일을 `sup/report-insights`에서 D가 고치는 중이라 병합 때 충돌이 날 수 있다.
- `src/skala_rag/agents/report.py`
  - `number_citations`: 같은 시그니처와 반환 값(번호는 첫 등장 순서, `citation_map`)인데, 출력이 `[n]` 제자리 치환에서 "토큰을 문장에서 빼고 `(n)`을 그 절 끝(마침표 앞)에 붙이기"로 바뀌었다. `;`로 이어진 절은 절마다 표시를 붙이고, 괄호 안과 `Fig.` 같은 약어의 마침표에서는 자르지 않는다. 토큰 앞에 남는 `근거:` 꼬리표는 지우고, 문단 끝에 홀로 남은 `근거: [a] [b]`의 표시는 앞 문장에 붙인다. 근거 ID가 아닌 대괄호(`[상충]`, `[REDACTED]`)는 그대로 둔다. 도우미 `_clauses`, `_attach`와 상수 `TOKEN_WITH_SPACE`, `_DANGLING_LABEL`, `_ABBREVIATIONS` 추가
  - "부록. 근거 목록" 절을 "각주"로 개명(`FOOTNOTE_HEADING`, `SMALL_SECTIONS`). `_evidence_table`에 `sources` 인자 추가: 번호 칸이 `(n)`이 되고 출처 칸이 `[R1] 저자·사이트명`(24자까지)이 된다. 출처 칸이 좁아 쪽수가 늘어서(실제 State 10쪽 → 11쪽) `_column_weights`에서 `출처` 0.6 → 1.2, `인용 구절` 5.0 → 4.4로 조정했다
  - 4장 안내 문구와 이해관계자 관점 문구의 "부록 근거 목록"을 "각주"로 바꿨다
- `src/skala_rag/agents/llm_output.py` — `LLMReportAgent` 시스템 메시지에 "본문에는 근거 번호가 (번호)로 표시돼 있다. 문장마다 해당 근거 번호를 [번호] 형태로 인용한다."를 넣었다. LLM이 요약에서 쓰는 `[번호]`는 내부용이고 최종 표기는 `build_report`가 정한다
- `tests/test_output.py`, `tests/test_llm_output.py` — `[1]` → `(1)`, 부록 → 각주로 단언을 고치고 표시 위치 테스트 1개 추가

**인터페이스 영향**:
- 트랙 D: 본문 인용 표기가 `[n]` → `(n)`, 절 이름이 "부록. 근거 목록" → "각주", 각주 표의 출처 칸이 `[R#] 이름`이다. `report["citation_map"]`과 `sections`의 구조, 다른 장 제목은 그대로다. 5장 항목에 `(1) …`처럼 번호 목록을 쓰는 것은 문단 맨 앞이면 평가기가 각주 표시와 구분하지만, 보고서를 읽는 사람에게는 헷갈리니 `1.`이나 `①` 같은 다른 번호 형식을 권한다
- 트랙 A: 없음. 평가기의 입력(`state["report"]`)과 출력 형식은 그대로다
- 평가 기준 변경: 편향 통제는 근거가 하나뿐인 판정이 많아도 평균 3점에 머문다. 통과선은 여전히 4점이므로 이 상태에서도 `recollect`가 나온다

**충돌 시 지켜야 할 것**:
- `number_citations`를 `[n]` 제자리 치환으로 되돌리면 안 된다. 본문 인용이 문장 중간에 끼어 읽기 어려워진다
- `_evidence_table`의 `sources` 인자와 `_column_weights`의 `출처`·`인용 구절` 가중치를 되돌리면 안 된다. 출처 이름 칸이 좁으면 각주 표가 길어져 10쪽을 넘는다
- 각주 절 이름(`FOOTNOTE_HEADING`)과 각주 표의 열 이름(`번호`, `기술`, `출처`, `인용 구절`), 번호 칸의 `(n)` 형식, 출처 칸 맨 앞의 `[R#]`는 평가기의 `_read_footnotes`, `footnote_findings`가 읽는다. 바꾸면 알려 달라
- 평가기의 `LEADING_ENUMERATOR`를 지우면 `(1) 항목` 목록 번호가 존재하지 않는 인용으로 잡혀 Groundedness가 1점이 된다
- `SOURCE_COUNT_SCORES`를 비율 기준으로 되돌리지 않는다. 근거가 하나뿐인 판정이 많은 현재 수집 결과에서 편향 통제가 다시 1점으로 급락한다

**확인**: `pytest -q --ignore=tests/tools --ignore=tests/evaluation --ignore=tests/agents` 106 passed, `pytest -q` 130 passed, `app.py --mode replay --fixture` 정상. 변이 검사: 각주 검증, `(n)` 해석, 목록 번호 제외를 각각 끄면 해당 테스트가 실패한다. 저장해 둔 실제 replay State로 실제 LLM 요약(`gpt-5.4-mini`)을 켜 보고서를 만들었다: 요약이 새 표기를 보고도 정상 생성(`llm_assisted`), PDF 10쪽(수준 1, 변경 전과 같음), 본문 인용 48개 모두 각주에 있고 각주 문제 0건, 서술 단위 68개 모두 인용에 닿음. 평가 결과(규칙): Groundedness 5, 중립성 5, 편향 통제 3(판정 19개 중 출처 1개 18개, 2개 1개, 평균 3.05), 관점 커버리지 4. 실제 Judge 호출 6회에서 지적한 문장 20건이 모두 보고서 원문과 연결됐다

## 2026-10-07 14:34 · sup/quality · piso

**무엇을**: 각주 표기 변경이 D의 `sup/report-insights`(3·5·6장 개편)와 합쳐질 때 어디서 부딪히는지 미리 시험하고, 그 결과를 남긴다. 병합은 하지 않았다. 테스트 도우미도 고쳤다.

**왜**: 같은 파일(`report.py`, `llm_output.py`, `tests/test_output.py`, `tests/test_llm_output.py`)을 양쪽이 고쳐서, 먼저 합쳐지는 쪽의 상대가 충돌을 풀어야 한다. 이유를 모른 채 풀면 한쪽 변경이 지워지므로 시험한 결과를 적는다.

**바꾼 파일**:
- `tests/test_quality.py` — `make_state`가 6장 내용을 인자(`domain_disclosed`)로만 정하게 했다. 보고서 작성기가 6장에 "단일 출처" 같은 문구를 자동으로 넣어도(D의 새 6장이 그렇다) 도메인 단일 출처 밝힘 여부 테스트가 흔들리지 않는다

**남의 파일**: 없음

**인터페이스 영향**: 없음

**충돌 시 지켜야 할 것**: `sup/report-insights`와 이 브랜치를 합친 결과를 임시 작업 트리에서 시험했다.
- 충돌은 `src/skala_rag/agents/llm_output.py` 한 곳이다. `LLMReportAgent` 시스템 메시지에서 이 브랜치가 넣은 한 문장("본문에는 근거 번호가 (번호)로 표시돼 있다. 문장마다 해당 근거 번호를 [번호] 형태로 인용한다.")과 D의 재작성(SUMMARY와 5장을 함께 쓰는 메시지)이 겹친다. D의 메시지를 그대로 두고 "공통 규칙: 문장마다 본문에 쓰인 근거 번호를 [번호]로 인용한다." 부분만 위 문장으로 바꾸면 된다. 이 문장을 빼면 LLM이 본문에 보이는 `(번호)`를 따라 써서 요약의 인용을 못 읽고 규칙 기반 요약으로 대체될 수 있다
- `report.py`, `tests/test_output.py`, `tests/test_llm_output.py`는 자동으로 합쳐지지만 D의 새 테스트 3개가 옛 `[1]` 표기를 단언해서 실패한다. `test_technical_overview_is_one_paragraph_per_technology`는 `근거: [1]` → `미검증(1).`, `test_llm_insights_replace_chapter_five_and_fall_back_independently_of_the_summary`는 `insights`의 ` [1].` → `(1).`(LLM이 쓴 문장은 `[번호]`이고 보고서에는 `(번호)`로 나온다)로 단언을 고치면 통과한다. 이 시험에서 평가기 쪽 테스트는 모두 통과했다
- D의 새 5장은 번호 목록을 `(1) …`로 쓴다. 평가기는 문단 맨 앞의 `(n)`을 목록 번호로 읽어 인용으로 세지 않는다. 다만 읽는 사람에게는 각주 표시와 헷갈리니 목록 번호는 `1.`이나 `①`이 낫다
- D의 새 6장은 단일 출처 판정 수를 자동으로 밝히므로 도메인 단일 출처가 밝혀진 것으로 평가돼(`domain_disclosed=True`) 편향 통제의 도메인 감점이 사라진다

**확인**: 합친 트리에서 실제 replay State로 보고서를 만들어 평가: PDF 10쪽(수준 0), 본문 인용 48개 모두 각주에 있고 각주 문제 0건, Groundedness 5, 중립성 4, 편향 통제 3(출처 1개 판정 9개, 2개 1개), 관점 커버리지 4. 이 브랜치에서 `pytest -q tests/test_quality.py` 37 passed.
