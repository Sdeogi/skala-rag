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

## 2026-10-07 15:22 · sup/merge-quality · deogi · 충돌 해결

**병합**: `origin/sup/quality`(9888c7d, 품질 평가기) → `sup/merge-quality`(`supervisor` 6ca072a에서 분기). `sup/quality` 브랜치 자체는 건드리지 않았다.

**배경**: 품질 평가기 브랜치가 보고서 작성기(`report.py`, `llm_output.py`)의 인용 방식을 바꿨고, 같은 시기에 `supervisor`에는 보고서 조판 변경이 들어갔다. 같은 문제(문장 중간에 끼는 인용, 길게 늘어지는 인용 번호)를 양쪽이 다르게 풀었다. 품질 평가기 쪽 이유는 `docs/agent/history/C.md`의 14:34·15:12 항목, 조판 쪽 이유는 이 파일의 `sup/report-layout` 항목에 있다.

**합의한 방식** (양쪽 변경을 모두 살림):
- 표기는 `[n]`을 쓴다(공학 논문 관례). 5장 항목 번호 `(1)`과 인용 `(1)`이 겹쳐 읽는 사람이 헷갈리는 문제가 없어진다
- 인용을 문장 중간에서 빼서 절 끝(마침표 앞)에 붙이는 것, 문단 끝 `근거:` 꼬리표를 지우는 것은 품질 평가기 브랜치의 방식을 그대로 받는다
- 보고서 데이터는 번호마다 대괄호 하나(`[1] [2] [3]`)를 유지하고, 범위로 묶는 것(`[1–3]`)은 PDF·HTML을 그릴 때만 한다. 평가기가 번호를 하나씩 대응표에서 찾을 수 있다
- 근거 목록 절의 이름은 "부록. 근거 목록"을 유지한다(평가기는 "각주"와 "부록"으로 시작하는 제목을 모두 읽는다). 표의 출처 칸에 출처 이름을 함께 적는 것은 품질 평가기 브랜치의 변경을 받는다

**충돌 파일과 해결**:
- `src/skala_rag/agents/report.py` (충돌 1곳 + 자동 병합된 부분의 의미 조정)
  - 충돌: 같은 자리에 한쪽은 글꼴 상수(`BUNDLED_FONT` 등), 다른 쪽은 `TOKEN_WITH_SPACE`를 추가 → 둘 다 남김
  - `number_citations`: 품질 평가기 브랜치의 절 끝 배치(`_clauses`, `_attach`, `_DANGLING_LABEL`)를 그대로 사용. `_attach`는 표시 앞에 공백을 두고(`…했다 [1] [2].`), 인용만 있는 표 칸에서는 앞 공백을 없앰
  - `format_markers`: `(1)-(7)` 범위 대신 `[1] [2] … [7]`을 반환. 범위 묶기는 `compact_citations`(렌더링)가 맡음
  - `FOOTNOTE_MARKER`, `expand_markers`, `RANGE_MIN` 삭제: 데이터에 `(n)` 표시와 범위가 없어 읽을 대상이 없다. `plain_text`는 대괄호 토큰 제거, 문장 부호 앞 공백 정리, `근거:` 꼬리표 제거를 유지
  - `FOOTNOTE_HEADING` 상수는 유지하되 값은 "부록. 근거 목록". 4장 안내 문구와 이해관계자 관점 문구도 "부록 근거 목록"으로
  - `_evidence_table`: `sources` 인자와 출처 이름 칸, `_column_weights`의 `출처` 1.2·`인용 구절` 4.4는 품질 평가기 브랜치 것을 유지. 번호 칸은 `[n]`
  - `_covered`의 "인용만 있는 조각은 앞 문장에 속한다" 처리, `_quality_limit_lines`의 항목별 통과 기준은 품질 평가기 브랜치 것을 유지
  - 5장 항목 번호를 `(1) (2)`에서 `① ②`로 바꿈(`ENUMERATORS`). 평가기가 요약·3·4·5장에서 `(n)`을 인용으로도 읽기 때문에, 문단 중간의 `(2)`가 인용 2번으로 잘못 세어지는 것을 막는다
  - 조판 쪽 변경(Pretendard, 표 제목, 쪽 번호, `compact_citations`, 수준 3)은 그대로
- `src/skala_rag/agents/llm_output.py` (자동 병합됨, 의미 조정)
  - `bracketed` 삭제와 호출 2곳 원복: `(n)` 표시를 `[n]`으로 되돌리는 함수인데 데이터가 이미 `[n]`이다. 남겨 두면 본문의 `(2024)`가 아닌 `(12)` 같은 괄호 숫자를 인용으로 바꿀 수 있다
  - `LLMReportAgent` 시스템 메시지의 "본문에는 근거 번호가 (번호)로 표시돼 있다" 문장을 원래 문장으로 되돌림(본문이 `[번호]`를 쓰므로 맞지 않는 설명)
- `tests/test_output.py` (충돌 2곳)
  - 3장 단언: 양쪽 기대값의 차이는 표기뿐 → `…긴 문맥 미검증 [1].`
  - 파일 끝: 조판 쪽 `test_adjacent_citations_are_merged_for_display_only`와 품질 평가기 쪽 범위 테스트가 같은 자리에 추가됨 → 둘 다 남기고, 뒤쪽은 "데이터는 번호마다 대괄호 하나, 그릴 때만 묶음"을 확인하는 테스트로 바꿈
  - 그 밖의 `(1)`·"각주" 단언을 `[1]`·"부록"으로 맞춤
- `tests/test_llm_output.py`: `shown` 도우미가 아무것도 바꾸지 않게 하고(`[1]`이 그대로 남음), `bracketed` 테스트 2개 삭제

**남의 파일**:
- `tests/test_quality.py` (품질 평가 담당 소유) — 보고서 작성기의 출력 형식에 기대던 도우미와 테스트 3곳만 고침. 평가기 자체(`quality.py`)는 한 글자도 바꾸지 않았다
  - `EVIDENCE_SECTION = "부록"` 추가, `footnote_rows`·`as_evidence_ids`와 절 필터가 "각주" 대신 이 값을 씀
  - `as_evidence_ids`: `(n)` 대신 `[n]`을 근거 ID로 되돌림
  - `test_a_run_of_citations_is_written_as_a_range_…` → `test_every_number_in_a_run_of_citations_is_verified`: 데이터에 범위가 없으므로 "연속한 번호 5개가 대괄호 하나씩 있고, 가운데 번호의 근거 행을 지우면 잡힌다"를 확인
  - `test_judge_quotes_without_a_range_marker_are_still_found` → `test_judge_quotes_without_citation_numbers_are_still_found`
  - 평가기의 `(n)`·범위 해석을 직접 확인하는 단위 테스트는 그대로 두었고 모두 통과한다

**버린 변경**: 품질 평가기 브랜치의 표기 선택(`(n)`, 데이터 수준의 `(1)-(7)` 범위, 절 이름 "각주")과 그것을 위한 `bracketed`/`expand_markers`. 표기를 `[n]`으로 통일하기로 한 결정에 따른 것이며, 그 변경이 풀려던 문제(문장 중간의 인용, 긴 인용 나열)는 절 끝 배치와 렌더링 단계 묶기로 해결된다. 평가기의 `(n)` 해석 기능은 남아 있어 나중에 표기를 바꿔도 평가기는 그대로 쓸 수 있다.

**충돌 시 지켜야 할 것**:
- `format_markers`가 데이터에 범위나 `(n)`을 쓰도록 되돌리려면 5장 항목 번호와의 혼동, `compact_citations`와의 중복을 함께 해결해야 한다
- `number_citations`를 제자리 치환으로 되돌리지 않는다(인용이 다시 문장 중간에 낀다)
- 5장 항목 번호를 `(1)` 형태로 되돌리지 않는다. 평가기가 인용으로 읽는다
- 근거 목록 절의 제목은 "부록" 또는 "각주"로 시작해야 평가기가 읽는다

**확인**: `git diff --check` 통과, pytest 137 passed(tests/tools·evaluation·agents 제외), `app.py --mode replay --fixture` 정상. 근거 60건 State로 만든 보고서를 평가기에 넣어 Groundedness 5·중립성 5·커버리지 5 확인(인용과 근거 목록이 서로 맞게 읽힘). 쪽수: 근거 60건 9쪽, 근거 90건 10쪽

## 2026-10-07 15:27 · sup/merge-quality · deogi

**무엇을**: PDF·HTML에 그릴 때 인용 번호를 묶는 모양을 `[1–3, 5]`에서 IEEE 방식 `[1]–[3], [5]`로 변경

**왜**: 번호마다 대괄호를 따로 쓰는 것이 IEEE 공식 양식이다. 앞서 쓴 `[1–3]`은 다른 번호식 양식(ACM 등)의 표기였다.

**바꾼 파일**:
- `src/skala_rag/agents/report.py` — `compact_citations`: 연속한 번호 3개 이상은 `[a]–[b]`, 나머지는 쉼표로 구분한 `[a], [b]`
- `tests/test_output.py` — 기대값 5곳 수정

**남의 파일**: 없음

**인터페이스 영향**: 없음. 보고서 데이터(`report["sections"]`)와 Markdown은 여전히 번호마다 대괄호 하나를 공백으로 구분해 쓴다(`[1] [2] [3]`)

**충돌 시 지켜야 할 것**: 이 묶기를 보고서 데이터에 적용하지 않는다. 렌더링 단계(`_write_pdf`, HTML 템플릿의 `cite` 필터)에서만 쓴다

**확인**: pytest 137 passed, fixture 실행 정상, 근거 60건 9쪽·근거 90건 10쪽

## 2026-10-07 15:40 · sup/report-manifest · deogi

**무엇을**: 실행 기록(`run_manifest.json`)에 Supervisor 제어 필드와 품질 평가 요약을 기록하고, 보고서가 없어진 State 필드(`retry_count`, `missing_questions`) 대신 `evidence_check["items"]`를 읽게 함

**왜**: Supervisor 그래프가 합쳐진 뒤에도 실행 기록에 `run_id`, 결정 기록, 관점별 상태, 평가 점수가 남지 않아 실행이 끝난 뒤 어떤 판단이 있었는지 확인할 수 없었다. `missing_questions`가 State에서 없어져 6장의 "근거 미확인" 항목과 SUMMARY의 미확인 개수가 항상 비어 있었다.

**바꾼 파일**:
- `src/skala_rag/agents/report.py`
  - `save_outputs`: manifest에서 `retry_count` 삭제. `run_id`, `step_count`, `agent_status`, `rework_attempts`(관점별 재작업 횟수), `decision_log`, `quality`(요약), `quality_result`(전체) 추가. `generation`에 `report_llm_sections`, `report_revision` 추가
  - `_quality_summary` 추가: `status`(`passed`/`accepted_with_limits`/`below_threshold`/`not_evaluated`), `action`, `threshold`, 항목별 `scores`, `attempts`
  - `deterministic_summary`: 미확인 항목 수를 `failed_items(state)`로 셈
- `src/skala_rag/agents/synthesis.py`
  - `failed_items(state)` 추가: `evidence_check["items"]` 중 통과하지 못한 항목
  - `limitation_lines`: `missing_questions` 대신 `failed_items`를 읽고, 항목마다 한 줄이던 것을 기술·관점별 한 줄로 묶음. 사유 코드를 한국어로 표시(`REASON_TITLES`)
- `tests/test_output.py`, `tests/test_llm_output.py` — `missing_questions`에 기대던 부분을 `evidence_check`로 바꾸고 테스트 2개 추가

**남의 파일**: 없음

**인터페이스 영향**:
- manifest의 `status` 값과 의미는 그대로다(`complete`/`incomplete`/`failed`, 근거 검사 기준). 품질 평가 결과는 `quality.status`에 따로 둔다
- manifest에서 `retry_count` 키가 없어졌다. 재작업 횟수는 `rework_attempts`에서 본다
- 6장의 근거 미확인 문장이 "근거 미확인 항목 — 기술 관점: 항목(사유); …" 형태로 바뀜

**충돌 시 지켜야 할 것**:
- `limitation_lines`와 `deterministic_summary`가 `missing_questions`를 읽도록 되돌리지 않는다. 그 필드는 State에 없다
- manifest의 `status`에 품질 평가 결과를 섞지 않는다. 그래프와 CLI 테스트가 근거 검사 기준의 값을 확인한다
- `evidence_check["items"]`의 원소 형태(`perspective`, `technology`, `field`, `passed`, `reasons`, `review_reason`)에 의존한다

**확인**: pytest 160 passed. `app.py --mode replay --fixture`로 전체 루프 확인: Supervisor 결정 15회(기술 조사 → 4관점 실행 → 종합 → 보고서 → 품질 평가 → 편향 통제 미달로 재수집 2회 → 상한 도달로 한계 명시 후 저장), manifest에 결정 기록·평가 점수·재작업 횟수 기록, 보고서 6장에 품질 평가 미달 항목 기재, PDF 5쪽

## 2026-10-07 15:55 · sup/report-manifest · deogi

**무엇을**: (1) 모델 이름과 환경 변수를 한 곳으로 통일, (2) 재작업 테스트 4개가 병합 뒤 실패하던 것을 수정하고 예전 형식 호환 코드를 제거. 모든 PR이 `supervisor`에 합쳐진 뒤의 최종 정리 작업이라 여러 트랙의 파일을 함께 고쳤다.

**왜**:
- 모델 이름이 파일마다 따로 적혀 있었고(`gpt-5.4-mini` 9곳, `gpt-4o-mini` 1곳) 환경 변수도 셋(`RAG_MODEL_ID`, `WEB_EVIDENCE_MODEL`, `TECHNICAL_AGENT_MODEL`)이었다. `gpt-5.4-mini`가 더는 호출되지 않아 `RAG_MODEL_ID`만 바꾸면 웹 근거 요약이 계속 실패했다
- 서비스의 재작업 입력 읽기가 "`rework_requests` 필드가 있으면 그것만 본다"였는데, 그래프의 초기 State가 이 필드를 빈 목록으로 넣어 두면서 예전 형식(`retry_mode`, `missing_questions`, `retry_count`)으로 입력을 주는 테스트 4개가 "지시 없음"으로 처리돼 실패했다. 실제 그래프는 새 형식만 보내므로 실행에는 영향이 없었다

**바꾼 파일** (모델 통일):
- `src/skala_rag/config.py` — `DEFAULT_MODEL_ID = "gpt-5.6-luna"`, `MODEL_ENV_VAR`, `resolve_model_id(explicit, env)` 추가(명시 인자 → `RAG_MODEL_ID` → 기본값 순)
- `src/skala_rag/graph/workflow.py`, `graph/schemas.py`, `schemas/state.py`, `agents/domain.py`, `agents/trl.py` — 모델 이름 문자열 대신 `DEFAULT_MODEL_ID` 사용
- `src/skala_rag/integration/services.py` — `_model_id`가 `resolve_model_id` 사용
- `src/skala_rag/tools/web.py` — `WEB_EVIDENCE_MODEL` 삭제, `resolve_model_id()` 사용
- `src/skala_rag/agents/technical/agent.py` — `MODEL_ENV_VAR`(`TECHNICAL_AGENT_MODEL`), `DEFAULT_MODEL` 삭제, `resolve_model_id(model)` 사용
- `app.py` — `--model-id` 도움말이 기본값을 `DEFAULT_MODEL_ID`에서 가져옴
- `.env.template`, `README.md` — `gpt-5.6-luna`로 갱신

**바꾼 파일** (재작업 테스트):
- `src/skala_rag/integration/services.py` — `_rework_requests`와 `_round_key`에서 예전 형식 분기 삭제. `rework_requests`만 읽는다
- `tests/test_integration.py` — 재작업 테스트 5곳의 입력을 `retry_mode`/`retry_count`/`missing_questions`에서 `rework_requests`(`attempt` 포함)로 변경. 확인하는 동작은 그대로

**남의 파일**: 위 목록 중 `config.py`·`graph/*`·`app.py`(그래프 담당), `integration/services.py`·`tools/web.py`·`agents/domain.py`·`trl.py`·`technical/agent.py`·`schemas/state.py`·`tests/test_integration.py`(하위 에이전트 담당). 팀 작업이 모두 합쳐진 뒤 최종본을 정리하는 단계에서 일괄 수정했다.

**인터페이스 영향**:
- 환경 변수는 `RAG_MODEL_ID` 하나만 읽는다. `WEB_EVIDENCE_MODEL`, `TECHNICAL_AGENT_MODEL`은 더 이상 읽지 않으므로 `.env`에 있어도 효과가 없다
- 웹 근거 요약의 캐시 키에 모델 이름이 들어가므로, 모델을 바꾸면 이전 모델로 만든 요약 캐시는 재사용되지 않는다
- 서비스는 예전 형식의 재작업 입력을 더 이상 받지 않는다

**충돌 시 지켜야 할 것**:
- 모델 이름 문자열을 다른 파일에 다시 적지 않는다. `config.DEFAULT_MODEL_ID`나 `resolve_model_id`를 쓴다
- `_rework_requests`에 예전 형식 분기를 되살리지 않는다. 그래프는 `rework_requests`만 보낸다

**확인**: pytest 171 passed(이전 4 failed), `app.py --mode replay --fixture` 정상

## 2026-10-07 17:05 · sup/live-fixes · deogi

**무엇을**: 실제 자료(live) 실행 네 번에서 드러난 문제를 고침. 웹 근거 요약 호출 방식, 웹 예산, 품질 루프 경로, 평가기의 오인식, 보고서 3장 작성과 수식 표기가 대상이다.

**왜** (실행에서 확인한 현상 → 원인):
- 시장성·이해관계자·TRL의 웹 근거가 하나도 모이지 않음 → 웹 요약만 함수 도구 방식(`create_agent` + `ToolStrategy`)을 썼는데 `gpt-5.6-luna`가 chat completions에서 이를 거부("Function tools with reasoning_effort are not supported")
- 검색 예산이 첫 수집에서 바닥남 → 기본 20회인데 첫 수집에만 약 40회 필요. 원문 조회도 60건으로는 이해관계자 수집이 45회 실패
- 품질 루프가 0회로 끝남 → 평가가 재수집을 제안했는데 모든 관점의 재작업 횟수가 소진돼 있으면 곧바로 한계 수용으로 감. 고쳐 쓸 수 있는 지적이 있어도 재작성을 시도하지 않음
- Groundedness 규칙 점수 1점 → 논문 표기 `[l-r:]`를 "없는 근거 인용"으로 읽음. 부록 인용 칸의 "발언 주체 …: " 접두가 원문 대조에 걸림
- Groundedness Judge 점수가 재작성 뒤 더 낮아짐 → 재작성이 검증에 걸리면 이전 LLM 글을 버리고 규칙 기반 문장으로 돌아갔고, 판정 라벨 나열과 "…을 검증해야 한다" 같은 제언 문장이 사실 주장으로 채점됨. 작성 LLM이 각 번호의 내용을 모른 채 인용 번호를 붙임
- 3장이 원문 주장을 세미콜론으로 이어 붙인 한 덩어리이고 LaTeX(`\\(\\tilde{Q}=…\\)`)가 그대로 찍힘

**바꾼 파일**:
- `src/skala_rag/tools/web.py` — `_call_summary_model`: 에이전트 + 함수 도구 대신 `with_structured_output(WebEvidenceSummary)`. 프로젝트의 다른 LLM 호출과 같은 방식
- `src/skala_rag/config.py`, `tools/budget.py`, `graph/schemas.py`, `app.py` — 웹 예산 기본값을 `config.DEFAULT_WEB_SEARCH_MAX = 100`, `DEFAULT_FETCH_MAX = 150` 한 곳에 둠(이전 20/30)
- `src/skala_rag/graph/workflow.py` — 품질 평가가 재수집을 제안했지만 재수집할 관점이 없고 지적된 문장(`instructions`)이 있으면 `rewrite_report`로 내려감(품질 루프 상한 안에서). 미달 항목 표시가 항목별 통과 기준(`item["threshold"]`)을 따름
- `src/skala_rag/agents/quality.py` — `UNKNOWN_ID_SHAPE` 추가: State에 없는 대괄호 토큰은 근거 ID 모양일 때만 "없는 근거"로 셈(`[l-r:]`, `[i:j]`, `[n]` 제외). `META_PATTERN`에 "확인해야/검증해야/확인이 필요" 등 추가(제언 문장은 사실 주장이 아님). 3장은 보고서가 LLM 작성으로 표시했을 때만 Judge 점수에 포함(`_Context.scored_chapters`)
- `src/skala_rag/agents/report.py`
  - `_technical_section(state, layout, overview)`: 기술당 세 문단(원리 / 실험 조건과 성능 / 한계), 세미콜론 대신 문장, 문단마다 그 범주의 근거만 인용. `overview`(LLM 문단)가 있으면 그것을 씀
  - `clean_math`: LaTeX 표기 제거
  - `_evidence_table`: 인용 구절 칸에는 구절만, 발언 주체는 위치 칸으로
  - `_synthesis_paragraphs`: 쌍이 없으면 "상충 쌍 0개" 대신 쌍이 구성되지 않았다는 문장
  - `_compose`·`build_report`에 `overview` 인자
- `src/skala_rag/agents/llm_output.py`
  - `ReportDraft.overview`(`TechOverview`): 작성 LLM이 3장을 기술마다 2문단으로 다시 씀. 기술별로 검증(인용 번호, 새 숫자, 우열 표현, 수식 표기, 길이)하고 실패한 기술만 규칙 문단 유지
  - `report["llm_texts"]["overview"]`에 3장 원문(근거 ID 인용)을 보관해 이후 재작성에서 지적받지 않으면 그대로 재사용. `llm_sections`에 `overview` 추가
  - 재작성이 검증에 걸리면 이전 LLM 글을 유지(그 뒤 지적 문장은 삭제 규칙이 처리)
  - 작성 LLM 입력에 `evidence`(번호별 claim·quote) 추가, 프롬프트에 "번호는 그 사실을 직접 담은 근거만", "판정 라벨은 판정임을 드러내기", "제언·미확인 문장에는 번호를 붙이지 않기" 추가
  - 부록·REFERENCE를 가리키는 지시는 문장 고쳐 쓰기 대상에서 제외
- `src/skala_rag/integration/services.py` — 기술 조사 결과에 `evidence_by_category`(원리/실험 조건/성능/한계별 근거 ID) 추가
- `src/skala_rag/agents/technical/prompts.py` — 수식을 LaTeX로 쓰지 말라는 규칙 추가
- 테스트: `tests/test_output.py`, `test_llm_output.py`, `test_quality.py`, `test_graph.py`, `test_schemas.py`

**남의 파일**: 최종 정리 단계라 여러 트랙 파일을 함께 고쳤다(위 목록의 `tools/`, `graph/`, `integration/`, `agents/quality.py`, `agents/technical/`).

**인터페이스 영향**:
- `technical_findings[기술]["evidence_by_category"]` 추가. `report["llm_sections"]`에 `overview` 키, `report["llm_texts"]` 추가
- 웹 예산 기본값이 바뀜(검색 100, 조회 150)
- 품질 평가의 재수집 제안이 재작성으로 바뀔 수 있음(결정 기록의 사유에 표시)

**충돌 시 지켜야 할 것**:
- 웹 요약을 함수 도구 방식으로 되돌리지 않는다. 추론 모델이 chat completions에서 거부한다
- `DEFAULT_FETCH_MAX`를 60 이하로 내리지 않는다. 실행 기록의 `fetch_calls`는 TRL 관점만 세므로 실제 사용량보다 작게 보인다
- 재작성 실패 시 이전 LLM 글을 유지하는 부분(`kept.get(...)`)을 `None`으로 되돌리면 규칙 기반 요약이 Judge에게 낮은 점수를 받는다
- `UNKNOWN_ID_SHAPE`를 없애면 논문 표기의 대괄호가 Groundedness를 1점으로 만든다

**확인**: pytest 204 passed. live 4회: 근거 검사 통과 9 → 11 → 13 → 17/24, 커버리지 2 → 4, 편향 통제 2 → 3(통과선 3), 중립성 5 유지, Groundedness 규칙 점수 1 → 5·Judge 점수 2, PDF 9쪽, 오류 89 → 2건

## 2026-10-07 17:11 · sup/live-fixes · deogi

**무엇을**: 제출 전 정리. README를 Supervisor 구조로 다시 쓰고, 쓰지 않는 코드와 의존성을 제거

**왜**: README가 예전 구조(고정 병렬 파이프라인)를 설명하고 있었고 State 스키마 설계와 품질 평가 기준이 없었다. README의 설치 명령(최소 환경)대로 하면 논문 검색 패키지가 없어 `pytest`가 수집 단계에서 멈췄다. 의존성 목록에 이 프로젝트가 import하지 않는 패키지가 20여 개 있었고, 그중 `psycopg2`는 PostgreSQL이 없는 컴퓨터에서 설치가 실패한다.

**바꾼 파일**:
- `README.md` — 전면 재작성: 패턴 선택 이유와 trade-off, Agents 표, Architecture(새 그래프 도식과 Supervisor의 판단 순서), State Schema(제어/페이로드 구분과 7개 설계 항목), Quality Evaluation(4개 항목의 규칙 검사·LLM Judge·통과 기준·미달 시 처리), Directory Structure, Usage, Contributors
- `pyproject.toml` — `dependencies`를 실제 import하는 패키지 15개로 축소(이전 36개). `graph` 의존성 그룹 삭제(전체 설치가 가벼워져 최소 환경이 따로 필요 없음). `description` 작성
- `uv.lock` — 다시 생성(약 3,700줄 감소)
- `src/skala_rag/evidence_check.py`, `src/skala_rag/supplement.py` — 삭제. 어디서도 import하지 않는 이전 과제의 근거 검사·보완 구현이다(현재는 `graph/evidence_check.py`와 Supervisor의 재작업이 그 역할)
- `.env.template` — LangSmith 변수를 `LANGSMITH_*` 이름으로, 글꼴 설명 갱신
- `docs/graph.mmd` — 다시 생성

**남의 파일**: 삭제한 두 파일은 이전 과제에서 다른 담당이 만든 것이다. `grep`으로 import가 없음을 확인하고 삭제했다.

**인터페이스 영향**:
- 설치 명령이 `uv sync --group dev` 하나로 바뀜(`--only-group graph`는 더 이상 없음)
- 삭제된 패키지를 쓰는 코드는 없다. `HANDOFF.md`와 `docs/PAPER_RAG_HANDOFF.md`, `docs/GRAPH_OUTPUT_*.md`는 이전 과제의 기록이며 삭제된 두 파일을 언급한다

**충돌 시 지켜야 할 것**:
- `pyproject.toml`에 패키지를 다시 넣을 때는 실제로 import하는 것만 넣는다. `psycopg2`, `jupyter`, `ragas` 등은 이 저장소 코드가 쓰지 않는다
- `uv.lock` 충돌은 손으로 풀지 말고 `uv lock`으로 다시 만든다

**확인**: 별도의 깨끗한 환경에 `uv sync --group dev`로 설치(패키지 약 200개) → `pytest -q` 204 passed, `app.py --mode replay --fixture` 정상

## 2026-10-07 17:14 · sup/live-fixes · deogi

**무엇을**: 이전 과제(RAG)의 인수인계·설계·검토 문서 다섯 개 삭제

**왜**: 고정 병렬 파이프라인 시절의 구조와 지금은 없는 파일(`evidence_check.py`, `supplement.py`)을 설명하고 있어 현재 코드와 맞지 않는다. 같은 문서가 이전 과제 브랜치(`rag`)에 그대로 남아 있어 비교가 필요하면 거기서 볼 수 있다.

**바꾼 파일**:
- 삭제: `HANDOFF.md`, `docs/GRAPH_OUTPUT_DESIGN.md`, `docs/GRAPH_OUTPUT_HISTORY.md`, `docs/GRAPH_OUTPUT_REVIEW.md`, `docs/PAPER_RAG_HANDOFF.md`
- `src/skala_rag/tools/retrieve/parsing.py`, `src/skala_rag/schemas/__init__.py`, `src/skala_rag/schemas/state.py` — 삭제한 문서를 가리키던 docstring 문구 수정(코드 변경 없음)

**남의 파일**: 삭제한 문서와 docstring은 이전 과제에서 다른 담당이 쓴 것이다.

**인터페이스 영향**: 없음

**충돌 시 지켜야 할 것**: 이 문서들을 되살리지 않는다. 내용이 필요하면 `rag` 브랜치를 본다.

**확인**: 다섯 파일 모두 `origin/rag`에 있음을 확인한 뒤 삭제. 코드·README·설정에 남은 참조 없음

## 2026-10-07 17:24 · sup/live-fixes · deogi

**무엇을**: 품질 평가 Judge가 보는 근거 범위를 넓히고, Judge 기준 두 가지를 명확히 함

**왜**: 다섯 번째 실제 실행에서 Groundedness Judge가 "인용 구절에 A100, 4배 배치 같은 수치가 없다"고 지적했는데, Judge는 근거 구절의 앞 300자만 받고 있었다(논문 청크는 1,200자까지, 작성 LLM은 400자). 수치가 구절 뒤쪽에 있으면 실제로는 근거가 있어도 "없음"으로 판정된다. 같은 실행에서 중립성 Judge는 두 기술의 TRL 단계가 다르게 나온 것(TRL 4와 TRL 3)을 "순위화"로 보고 1점을 줬다. 판정 결과를 전하는 것은 보고서의 목적이지 우열 판정이 아니다.

**바꾼 파일**:
- `src/skala_rag/agents/quality.py`
  - `JUDGE_QUOTE_LIMIT = 800` 추가, Groundedness Judge에 넘기는 근거 구절을 300자 → 800자로. `EVIDENCE_PER_UNIT` 4 → 5
  - `JUDGE_GROUNDEDNESS_PROMPT`: 근거를 찾지 못했다는 진술과 "…로 판정됐다" 문장은 구절이 그 말을 담지 않아도 문제로 보지 않음
  - `JUDGE_NEUTRALITY_PROMPT`: 판정 라벨·TRL 단계를 그대로 전하는 것은 값이 달라도 우열이 아님. 비교 우위를 말하거나 한쪽을 권할 때만 우열
- `src/skala_rag/agents/llm_output.py` — 작성 LLM에 주는 근거 구절도 800자로 맞춤(작성자와 평가자가 같은 범위를 봄)

**남의 파일**: `agents/quality.py`(품질 평가 담당)

**인터페이스 영향**: 없음. Judge 호출의 입력 토큰이 늘어난다

**충돌 시 지켜야 할 것**:
- 작성 LLM과 Judge가 보는 근거 구절 길이를 다르게 두지 않는다. 한쪽만 짧으면 작성자가 근거에서 가져온 수치를 평가자가 못 본다
- 중립성 Judge 프롬프트에서 "판정 결과 전달은 우열이 아님" 문장을 빼면 두 기술의 TRL이 다를 때마다 중립성이 1점이 된다

**확인**: pytest 175 passed(논문 검색 테스트 제외). 실제 실행으로는 아직 확인하지 않음

## 2026-10-07 17:30 · sup/live-fixes · deogi

**무엇을**: 테스트 실행이 개발자의 `.env`를 읽지 않고 트레이스도 보내지 않도록 함

**왜**: `.env`에 LangSmith 키와 추적 설정이 있으면, `pytest`를 돌릴 때마다 테스트용 가짜 그래프 실행 수십 개가 실제 트레이스 프로젝트에 올라갔다. 제출용 트레이스를 찾기 어렵게 만든다.

**바꾼 파일**:
- `tests/conftest.py` — 맨 위에서 `RAG_DISABLE_DOTENV=1`과 추적 변수 네 개(`LANGSMITH_TRACING`, `LANGSMITH_TRACING_V2`, `LANGCHAIN_TRACING`, `LANGCHAIN_TRACING_V2`)를 `false`로 설정

**남의 파일**: `tests/conftest.py`(그래프 담당의 공용 테스트 설정)

**인터페이스 영향**: 없음. 실제 실행(`app.py`)의 추적은 그대로다

**충돌 시 지켜야 할 것**: 이 설정은 다른 import보다 먼저 실행돼야 한다. 파일 아래쪽으로 옮기면 `app.py`가 먼저 `.env`를 읽는다

**확인**: pytest 204 passed. 테스트 실행 뒤 트레이스 프로젝트에 새 실행이 0건인 것을 LangSmith API로 확인. 실제 실행 여섯 건은 `skala-rag-live` 이름과 `run_id` 메타데이터로 기록돼 있음
