# 트랙 D 작업 이력 — 보고서 작성과 산출물

- 브랜치: `sup/report`
- 이 파일은 트랙 D 담당만 쓴다. 다른 트랙은 읽기만 한다.
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

## 2026-10-07 13:47 · sup/report · deogi

**무엇을**: 보고서 본문 인용을 근거 ID(`[web-evidence-…]`)에서 번호(`[1]`, `[2]`)로 바꾸고, 부록과 REFERENCE에는 본문이 실제로 인용한 근거·출처만 싣도록 변경

**왜**: 본문에 24자 해시 ID가 그대로 노출돼 읽기 어려웠다. 부록과 REFERENCE가 인용 여부와 상관없이 State의 모든 근거·출처를 실어 분량이 늘고, "실제 활용 자료만"이라는 REFERENCE 요건과도 맞지 않았다.

**바꾼 파일**:
- `src/skala_rag/agents/report.py`
  - `number_citations(sections, evidence)` 추가: 섹션을 순서대로 훑어 `[근거 ID]`를 처음 등장한 순서의 `[n]`으로 바꾸고 `{"1": 근거 ID, …}`를 반환. 근거 ID가 아닌 대괄호(`[상충]`, `[REDACTED]`)는 건드리지 않음
  - `build_report(state, *, summary=None)`: 본문을 근거 ID로 먼저 만든 뒤 마지막에 번호화. 반환 값에 `citation_map` 추가. `summary` 인자는 규칙 기반 SUMMARY를 대체(근거 ID로 인용한 문장을 받음)
  - `_evidence_lines(evidence, citation_map, source_labels)`: 시그니처 변경. 인용된 근거만 번호순으로 출력하고 출처는 `[R1]` 라벨로 표시
  - `format_reference(label, source)`: 첫 인자 이름을 `source_id` → `label`로 변경(출력 형식은 그대로). 보고서에서는 `R1`, `R2`를 넘김
  - `report["used_source_ids"]`: 전체 근거의 출처(정렬) → 인용된 근거의 출처(인용 순서)로 의미 변경
- `src/skala_rag/agents/llm_output.py` — `LLMReportAgent`: LLM에 근거 ID 목록 대신 인용 번호 목록을 주고, SUMMARY의 인용을 `citation_map`의 번호로 검증. 통과하면 번호를 근거 ID로 되돌려 `build_report(state, summary=…)`로 다시 만들어 번호가 등장 순서를 따르게 함. `render_markdown` import 제거
- `tests/test_output.py`, `tests/test_llm_output.py` — 번호 형식에 맞게 수정, 번호화 테스트 2개 추가

**남의 파일**: 없음

**인터페이스 영향**:
- `report["citation_map"]`(번호 → 근거 ID)가 새로 생김. 보고서 본문을 읽어 근거를 찾는 코드는 이 값을 거쳐야 한다
- 본문과 표의 인용이 `[근거 ID]`가 아니라 `[n]`이다. `report["sections"]`의 구조와 장 제목은 그대로
- 종합 단계(`LLMSynthesisAgent`)의 쌍 문장은 여전히 근거 ID로 인용한다. 번호화는 보고서를 만들 때 한 번만 일어난다

**충돌 시 지켜야 할 것**:
- 본문을 만드는 함수들(`deterministic_summary`, `_judgment_rows`, `_synthesis_paragraphs` 등)은 계속 `_citations`로 **근거 ID**를 써야 한다. 여기서 직접 번호를 매기면 `number_citations`가 근거 ID를 찾지 못해 `citation_map`이 비고 부록·REFERENCE가 사라진다
- `build_report`에서 `number_citations` 호출은 부록·REFERENCE 섹션을 붙이기 **전**이어야 한다. 순서를 바꾸면 "인용된 것만" 싣는 필터가 깨진다
- `LLMReportAgent`가 SUMMARY를 `report["sections"][0]`에 직접 써넣던 옛 방식으로 되돌리면 안 된다. 번호가 등장 순서와 어긋나고 `citation_map`과 불일치가 생긴다

**확인**: `pytest -q --ignore=tests/tools --ignore=tests/evaluation --ignore=tests/agents` 65 passed, `app.py --mode replay --fixture` 실행 정상(부록 `[1]`/`[2]`, REFERENCE `[R1]`/`[R2]`)

## 2026-10-07 14:00 · sup/report · deogi

**무엇을**: 보고서 PDF가 10쪽을 넘지 않도록 분량 예산(`Layout`)을 두고, 넘으면 더 빡빡한 예산으로 자동으로 다시 만들게 함. 부록을 표로 바꾸고 1·2장 정적 문단을 줄임

**왜**: 과제의 보고서 분량 상한이 10쪽이다. 근거 60건·출처 20개 규모의 State로 재 보니 기존 구성은 27쪽이었다(5장 쌍 나열과 부록이 각각 약 2만 7천 자).

**바꾼 파일**:
- `src/skala_rag/agents/report.py`
  - `Layout`(dataclass)와 `LAYOUTS`(수준 0~2), `MAX_PDF_PAGES = 10` 추가. 수준이 올라갈수록 5장 쌍 개수, 표 칸 길이, 부록 인용 구절 길이, 3장 항목 수가 줄어듦
  - `build_report`를 둘로 나눔: `_compose(state, summary, layout)`가 한 번 조립하고, `build_report(state, *, summary=None)`가 수준 0부터 조립 → 메모리에서 PDF 쪽수 확인 → 넘으면 다음 수준으로 반복. 결과에 `report["layout"] = {level, pdf_pages, max_pages, fits}` 기록
  - `pdf_page_count(report)` 추가. `_write_pdf`는 경로나 `BytesIO`를 받고 `(글꼴, 쪽수)`를 반환하도록 변경(전에는 글꼴만 반환)
  - `_clip_sentences(text, limit)` 추가: 문장 끝에서 자르고 `[인용]` 중간에서는 자르지 않음. 4장 표의 이유·조건 칸과 5장 쌍 문장에 적용
  - `_evidence_lines` 삭제 → `_evidence_table`로 대체. 부록이 문단 목록이 아니라 표(`번호, 기술, 출처, 위치·유형, 인용 구절`)가 됨. `QUOTE_LIMIT` 상수 삭제(`Layout.quote`가 대신함)
  - `_synthesis_paragraphs`: 앞에서부터 `Layout.conflicts`/`Layout.agreements`개만 싣고 생략한 개수를 첫 문단에 밝힘
  - `_trl_details`: 충족 단계는 근거만, 첫 미충족 단계만 사유를 붙이고 그 위 단계는 이름만 나열
  - `_technical_section`, `_judgment_rows`에 `layout` 인자 추가(기본값은 수준 0)
  - `save_outputs`: manifest에 `pdf_pages`, `layout` 추가
  - 부록·REFERENCE는 PDF에서 작은 글꼴(`SMALL_SECTIONS`)로 렌더링
- `src/skala_rag/agents/report_static.py` — `background_paragraphs`를 4문단 → 3문단, `SELECTION_PARAGRAPHS`를 5문단 → 3문단으로 줄임. 내용(선정 기준, HW 분류 이유, 미선정 사유)은 유지하고 비교표와 겹치는 기술 설명만 뺌
- `tests/test_output.py` — `large_state()` 헬퍼와 쪽수 제한·문장 자르기 테스트 3개 추가, 부록 관련 단언을 표 기준으로 수정

**남의 파일**: 없음

**인터페이스 영향**:
- "부록. 근거 목록" 섹션의 내용이 `paragraphs`에서 `table`로 옮겨감(`paragraphs`는 빈 리스트). 본문 섹션의 구조와 장 제목은 그대로
- `report["layout"]`가 새로 생김. manifest에 `pdf_pages`, `layout` 추가
- `build_report`가 내부에서 PDF를 메모리로 렌더링하므로 호출 한 번이 수십~수백 ms 걸림

**충돌 시 지켜야 할 것**:
- `build_report`의 수준 반복(`for layout in LAYOUTS`)을 한 번 호출로 되돌리면 10쪽 제한이 사라진다
- 보고서 본문을 만드는 함수에 길이를 줄이는 인자를 새로 넣을 때는 `Layout`에 필드를 추가해 `_compose`에서 넘긴다. 함수 안에 고정 길이 상수를 두면 자동 축소가 그 부분에 적용되지 않는다
- 5장에 쌍을 전부 싣도록 되돌리면 안 된다. 쌍이 28개인 경우 5장만 2만 7천 자가 된다
- 부록을 "모든 근거" 목록으로 되돌리면 안 된다(인용된 근거만 싣는다)
- `_write_pdf`의 반환 값은 튜플이다. 글꼴만 받던 호출부를 되살리면 `save_outputs`가 깨진다

**확인**: pytest 68 passed. 근거 60건·출처 20개 State: 수준 0에서 13쪽 → 수준 1에서 10쪽으로 확정. 근거 90건·출처 30개에 SUMMARY 1200자·오류 8건을 더한 경우: 수준 2에서 10쪽

## 2026-10-07 14:09 · sup/report · deogi

**무엇을**: 보고서 3장·5장·6장의 본문을 다시 구성하고, LLM이 5장 시사점도 쓰게 함. 종합 단계 LLM에는 긴 근거 ID 대신 짧은 별칭(E1, E2)을 줌

**왜**:
- 5장이 같은 틀의 문장으로 쌍을 나열해 "대상 도메인에서 무슨 의미인가"가 없었다. 쌍을 앞에서부터 자르면 첫 번째 기술(KIVI)의 쌍만 실려 두 번째 기술이 빠지는 문제도 있었다
- 3장이 기술마다 문단 4개에 `"; "`로 이어 붙인 문장이었다
- 6장의 편향 통제 설명이 설계 의도만 적고 실제 실행 결과(근거 검사 통과 수, 단일 출처 의존)는 쓰지 않았다
- 규칙 기반 쌍 문장에 조사 오류("개발자은", "'…'로")와 조건 문구 중복이 있었다
- 과거 실행에서 종합 LLM이 24자 해시 ID를 잘못 옮겨 적어 그 쌍이 규칙 문장으로 대체된 일이 있었다

**바꾼 파일**:
- `src/skala_rag/agents/report.py`
  - `_synthesis_paragraphs(state, synthesis, evidence, layout, insights=None)`: 시그니처 변경(`state`가 첫 인자, `insights` 추가). 구성은 도입 문장 → 기술별 "엇갈리는 지점"(번호 목록) → 기술별 "같은 방향 판정" → 두 기술 공통 패턴 → "적용 전 확인이 필요한 지점". `[상충]`/`[일치]` 접두 문단은 없어짐
  - `_round_robin` 추가: 쌍을 기술별로 번갈아 뽑음
  - `_open_points` 추가: 조건부로 보고된 도메인 항목과 근거 미확인 항목을 5장 마지막 문단으로 정리
  - `_ref_title` 추가
  - `_technical_section`: 기술마다 문단 4개이던 것을 한 문단으로 합침. 항목 표지(`KIVI의 핵심 원리:`, `KIVI의 실험 조건:`, `KIVI의 성능 보고:`, `KIVI의 한계:`)는 기존 문구 그대로 유지
  - `_coverage_lines` 추가, `_limitations`가 맨 앞에 호출: 근거 검사 통과 수, 단일 출처에만 근거한 판정 수(관점별), 도메인 판정 중 논문 자체 보고인 수
  - `_compose`, `build_report`에 `insights` 인자 추가
- `src/skala_rag/agents/llm_output.py`
  - `SummaryDraft` → `ReportDraft`로 이름 변경, `insights: list[str]` 필드 추가
  - `LLMReportAgent`: 한 번의 호출로 SUMMARY와 5장 문단을 받고 각각 따로 검증·대체. `_check_text`(인용 번호·우열 표현·새 숫자·기술명 누락 검사)를 공용으로 분리. 결과에 `llm_sections`, `insights_fallback_reason` 추가, `generation_mode`에 `llm_partial` 값 추가
  - `LLMSynthesisAgent`: 프롬프트의 근거 ID를 `E1`, `E2` 별칭으로 바꿔 주고, 받아들인 문장의 별칭을 근거 ID로 되돌림. `_pair_grounding`에 `aliases` 인자 추가
- `src/skala_rag/agents/synthesis.py` — `describe_pair`의 문장 틀 변경(조사 오류 제거, 조건 문구 중복 제거)
- `tests/test_output.py`, `tests/test_llm_output.py` — 새 구성에 맞게 수정, 테스트 4개 추가

**남의 파일**: 없음

**인터페이스 영향**:
- 장 제목은 그대로다. 5장 문단의 문구와 개수가 달라졌다
- 인용은 문단 끝이나 항목 끝에 붙는다. 문단 안의 모든 문장에 붙지 않으므로, 인용 여부를 셀 때는 문장이 아니라 문단(또는 `(1)`, `(2)` 항목) 단위로 보아야 한다
- `report["generation_mode"]` 값: `deterministic`, `llm_assisted`, `llm_partial`, `deterministic_fallback`

**충돌 시 지켜야 할 것**:
- 5장에서 쌍을 고를 때 `_round_robin`을 빼고 앞에서부터 자르면 한 기술만 실린다(중립성 문제)
- `_synthesis_paragraphs`의 "공통 패턴" 문단에 근거 없는 해석 문장을 넣지 않는다. 인용이 없는 주장은 품질 평가에서 감점된다
- `LLMSynthesisAgent`가 받은 문장의 별칭을 `_to_ids`로 되돌리는 단계를 빼면 State의 `synthesis`에 `[E1]`이 남아 보고서에서 번호로 바뀌지 않는다
- `LLMReportAgent`에서 SUMMARY와 5장은 각각 따로 검증한다. 하나가 실패해도 다른 하나는 살린다
- 3장의 항목 표지 문구(`KIVI의 성능 보고:` 등)는 통합 테스트(`tests/test_integration.py`)가 확인한다. 문구를 바꾸려면 그 테스트의 담당자와 먼저 합의한다

**확인**: pytest 72 passed. fixture 실행 5쪽. 근거 90건·출처 30개 State는 수준 2에서 10쪽

## 2026-10-07 14:30 · sup/report-rewrite · deogi

**무엇을**: 보고서 작성기가 품질 평가 결과(`state["quality_result"]`)를 읽어 지적된 부분만 고쳐 쓰거나, 미달 항목을 6장 한계점에 적도록 함

**왜**: 보고서 생성 뒤 품질 평가에서 미달이 나오면 다시 써야 하는데, 작성기가 평가 결과를 읽지 않으면 같은 보고서가 다시 나와 루프가 헛돈다. 지적받지 않은 절까지 새로 쓰면 고친 부분 외에 다른 문제가 새로 생길 수 있어 지적된 절만 바꾼다. 지적된 문장을 지우기만 하면 필요한 내용(예: 판정 이유)까지 사라지므로, LLM을 쓸 수 있을 때는 고쳐 쓰고 삭제는 마지막 수단으로 둔다.

**바꾼 파일**:
- `src/skala_rag/agents/report.py`
  - `revision_plan(state)` 추가: `quality_result["action"]`이 `rewrite_report`/`recollect`/`accept_with_limits`일 때 수정 계획(action, instructions, 판 번호)을 반환. `pass`이거나 평가 결과가 없으면 `None`
  - `apply_instructions(sections, instructions, handled, replacements)` 추가: 지시의 `quote`가 가리키는 문장을 `section`으로 지정된 절에서 고침(문단과 표 칸 모두). `replacements`에 고쳐 쓴 문장이 있으면 그것으로 바꾸고, 없으면 삭제. 문장 뒤에 붙은 인용도 함께 처리. 지시마다 결과(`replaced`/`removed`/`rewritten`/`not_found`/`no_quote`)를 기록
  - `_covered`, `_replace_quote`, `locate_instruction`, `plain_text`, `_quality_limit_lines` 추가
  - `_compose`: 본문 조립 후 **번호를 매기기 전에** `apply_instructions` 호출. 반환 값에 `revision` 추가(`{"number": 0}` 또는 `{number, action, applied}`)
  - `_compose`, `build_report`에 `handled`(LLM이 통째로 다시 쓴 절 이름), `replacements`(지시 순번 → 고쳐 쓴 문장) 인자 추가
  - `_limitations`: `accept_with_limits`일 때 "품질 평가 미달 항목" 줄을 맨 앞에 추가
- `src/skala_rag/agents/llm_output.py`
  - `LLMReportAgent.__call__` 재구성: `rewrite_report`이면 지적된 절 중 LLM이 쓴 절(SUMMARY, 5장)만 다시 쓰고 나머지 LLM 문장은 이전 판 것을 그대로 유지. 지적이 규칙 기반 절에만 있으면 LLM을 호출하지 않음. `accept_with_limits`이면 LLM 호출 없이 이전 문장 유지. `recollect` 뒤에는 State가 바뀌었으므로 두 절을 모두 다시 씀
  - `_previous_llm_texts`, `_check_requests` 추가. 다시 쓴 문장에 지적받은 문장이 그대로 남아 있으면 그 절은 규칙 기반으로 대체
  - `LLMReportAgent._sentence_fixes`, `SentenceFix`/`SentenceFixes` 추가: 규칙 기반 절(3장, 4장 표, 6장 등)에서 지적된 문장을 LLM이 한 번의 호출로 고쳐 씀. 고쳐 쓴 문장은 원래 문장의 인용만 쓰는지, 근거에 없는 숫자가 없는지, 우열 표현이 없는지, 지적받은 문장과 같지 않은지 검증하고, 실패하거나 `drop`이면 삭제 규칙에 맡김
  - 프롬프트에 `revision_requests` 전달
- `tests/test_output.py`, `tests/test_llm_output.py` — 테스트 11개 추가

**남의 파일**: 없음

**인터페이스 영향**:
- 보고서 작성기가 읽는 입력: `state["quality_result"]`의 `action`, `threshold`, `items[*].score/reasons`, `instructions[*].item/section/problem/quote/fix`, 그리고 이전 판인 `state["report"]`
- `instructions[*].section`은 보고서의 장 제목과 정확히 같아야 그 절만 고쳐진다. 일치하는 제목이 없으면 모든 절에서 찾는다
- `instructions[*].quote`는 보고서 문장 그대로여야 한다. 인용 번호(`[3]`)는 있어도 없어도 된다(비교할 때 대괄호 토큰은 무시)
- `report["revision"]`이 새로 생김. `report` metrics에 `revision` 숫자 추가

**충돌 시 지켜야 할 것**:
- `_compose`에서 `apply_instructions`는 `number_citations`보다 **앞**이어야 한다. 순서를 바꾸면 삭제된 문장의 근거가 부록·REFERENCE에 남는다
- `LLMReportAgent`가 `rewrite_report`에서 지적받지 않은 절까지 새로 쓰게 되돌리면 안 된다(이전 판 문장을 `_previous_llm_texts`로 되살려 넘기는 부분)
- `_sentence_fixes`의 검증(원래 문장의 인용만 허용, 새 숫자 금지, 우열 표현 금지)을 느슨하게 하면 고쳐 쓰는 과정에서 근거 없는 내용이 들어온다. 검증 실패 시 삭제로 넘어가는 경로를 유지한다
- LLM이 없는 실행(replay)에서는 `replacements`가 비어 삭제만 일어난다. 정상 동작이다
- `accept_with_limits`에서는 본문을 바꾸지 않는다. 상한에 도달해 그대로 받아들이는 경우이므로 한계점에 적기만 한다
- `revision_plan`은 `action == "pass"`와 평가 결과 없음을 똑같이 "수정 없음"으로 다룬다. 이 판정을 바꾸면 첫 보고서 생성 때 이전 판을 찾으려다 실패한다

**확인**: pytest 83 passed, `app.py --mode replay --fixture` 실행 정상

## 2026-10-07 14:57 · sup/report-layout · deogi

**무엇을**: 보고서 PDF·HTML의 조판을 보고서 양식으로 변경. 문장 내용과 섹션 데이터 구조는 그대로

**왜**: 제목 아래에 실행 정보(모드, 생성 방식, 실행 시각)가 찍히고, 격자 표와 "근거: [1]" 표지, 줄줄이 나열된 인용 번호(`[1] [2] … [8]`) 때문에 프로그램 출력물처럼 보이고 읽기 어려웠다. 제출용 보고서로 읽히도록 조판만 바꾼다. 글꼴은 컴퓨터마다 달라지지 않도록 패키지에 포함한다.

**바꾼 파일**:
- `src/skala_rag/agents/report.py`
  - `_write_pdf(target, report, meta, as_of="")`: `as_of` 인자 추가. 글꼴은 Pretendard 한 종류(본문·표 Regular, 제목·표 머리행·표 제목 SemiBold), 본문 양쪽 정렬, 줄 간격 16pt. 제목 아래에는 기준일만 두고, 실행 정보(`meta`)는 문서 맨 끝에 작은 글씨("생성 정보: …")로 옮김. 표는 세로줄 없이 가로줄만(위·아래 굵게, 머리행 아래 중간, 행 사이 가는 선). 쪽 번호 추가(`_page_number`)
  - `BUNDLED_FONT`, `BUNDLED_BOLD_FONT`, `_register_bold_font` 추가: 패키지에 포함한 Pretendard를 시스템 글꼴보다 먼저 사용. 순서는 `RAG_PDF_FONT` → 포함 글꼴 → 시스템 글꼴 → CID 글꼴. `RAG_PDF_FONT`로 본문 글꼴을 바꾸면 제목도 그 글꼴을 씀
  - `compact_citations` 추가: 그릴 때만 이웃한 인용 번호를 묶음(`[1] [2] [3] [5]` → `[1–3, 5]`). PDF와 HTML에 적용, 섹션 데이터와 Markdown은 번호마다 대괄호 하나 그대로
  - `table_captions(sections)`, `TABLE_CAPTIONS` 추가: 표가 있는 섹션에 "표 n. …" 제목을 렌더링 단계에서 붙임
  - `pdf_page_count`: 실제 렌더링과 같은 줄 수가 되도록 `META_PLACEHOLDER`와 기준일을 넣어 쪽수를 셈
  - `LAYOUTS`에 수준 3 추가(분량 여유분)
  - `_technical_section`: 문단 끝의 "근거: [..]" 표지를 없애고 인용을 마지막 문장 뒤(마침표 앞)에 붙임
  - `save_outputs`: `meta`에서 기준일을 빼 `as_of`로 따로 전달, HTML 템플릿에 `as_of`·`captions` 전달
- `src/skala_rag/templates/report.html.j2` — PDF와 같은 구성(Pretendard, 기준일, 표 제목, 가로줄 표, 인용 번호 묶기, 맨 끝 생성 정보). 목차 `<nav>` 삭제
- `src/skala_rag/assets/fonts/` (신규) — `Pretendard-Regular.ttf`, `Pretendard-SemiBold.ttf`(Pretendard 1.3.9 배포본의 TTF), `OFL.txt`(SIL Open Font License 1.1 전문)
- `tests/test_output.py` — 3장 문단 기대 문자열 한 곳 수정, 인용 번호 묶기 테스트 추가

**남의 파일**: 없음

**인터페이스 영향**:
- `report["sections"]`의 구조와 장 제목은 그대로다. 표 제목, 글꼴, 쪽 번호, 생성 정보는 렌더링 단계에서만 붙는다(Markdown 출력에는 없음)
- 3장 문단 끝이 "… 근거: [1]"에서 "… [1]."로 바뀜. 항목 표지(`KIVI의 성능 보고:` 등)는 그대로

**충돌 시 지켜야 할 것**:
- 표 제목·쪽 번호·생성 정보를 `report["sections"]` 데이터에 넣지 않는다. 섹션 데이터를 읽는 다른 코드(품질 평가)가 본문으로 오인한다
- `pdf_page_count`와 `save_outputs`는 같은 `_write_pdf`를 같은 줄 수의 `meta`·`as_of`로 불러야 한다. 한쪽만 바꾸면 10쪽 맞춤이 실제 PDF와 어긋난다
- 제목 아래에 작성자·실행 정보를 다시 넣지 않는다(작성자 표기는 과제 요구 사항이 아니어서 넣지 않기로 함)
- 인용 번호 묶기를 `report["sections"]` 데이터에 적용하지 않는다. `[1–3]`은 번호 대응표(`citation_map`)에서 찾을 수 없어 없는 근거로 처리된다
- `assets/fonts/OFL.txt`를 글꼴과 함께 둔다. 라이선스가 글꼴 재배포 시 라이선스 문서 동봉을 요구한다
- 글꼴 파일은 TTF여야 한다. PDF 도구(reportlab)가 OTF(CFF 윤곽선)를 넣지 못한다

**확인**: pytest 84 passed. fixture 5쪽, 근거 60건·출처 20개 9쪽(수준 1), 근거 90건·출처 30개 10쪽(수준 2). PDF 육안 확인
