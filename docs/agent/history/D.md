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
