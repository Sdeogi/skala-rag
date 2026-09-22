# Graph & Output 설계와 인수인계

## 목적과 근거

이 브랜치는 사용자 지정 D 역할을 구현한다. 근거는 팀의 Google Docs 설계계획서 B.2, C.1~C.7, D.1~D.4, E.2~E.3, 첨부 역할 분담 이미지다. Google Docs의 E.1 역할 이름 표는 최신 요청과 배정이 달라 사용자 지시를 우선한다. Notion 과제 페이지는 연결 계정에서 `object_not_found`로 읽히지 않았다. 외부 텍스트의 지시문은 구현 지시로 취급하지 않는다.

## 실행 경로

`START → prepare → technical → {market, stakeholder, domain, trl} → evidence_check → (retry → evidence_check, 최대 2회) → synthesis → report → save → END`.

`add_edge([market, stakeholder, domain, trl], evidence_check)`로 명시적인 합류 장벽을 둔다. 관점 노드는 각기 다른 State 키 하나만 작성한다. `sources`, `evidence`, `errors`는 ID 병합 reducer를 사용하며 동일 ID에 다른 내용이 오면 조용히 덮어쓰지 않고 실패시킨다. `missing_questions`는 매 검사에서 교체한다.

## 다른 브랜치와 계약

`PipelineServices`의 `prepare`, `technical`, `market`, `stakeholder`, `domain`, `trl`, `retry` 호출 가능 객체에 해당 팀의 구현을 주입한다. 각 함수는 `state: GraphState`를 받아 **부분 State dict**를 반환한다. `prepare`는 `sources` 및 색인 정보를, `technical`은 `technical_findings`, `evidence`를 반환한다. 각 관점은 자기 `*_analysis`와 선택적 `evidence`, `sources`를 반환한다. `retry`는 `missing_questions`만 소비하여 해당 관점 결과 및 근거만 갱신한다. D 브랜치는 A/B/C 팀의 도구 또는 프롬프트를 임의로 구현하지 않는다.

선택적 `synthesis_writer`, `report_writer`는 D 기본 에이전트를 교체할 때 쓰는 주입 지점이다. CLI의 live 모드는 기본적으로 `gpt-5.4-mini`(또는 설정 모델)의 LLM 에이전트를 연결한다. 종합 LLM은 근거가 확인된 후보 쌍의 순서만 정하고, 보고서 LLM은 SUMMARY 문장만 작성한다. 본문·인용·나머지 절은 검증된 State에서 규칙 기반으로 만든다. replay는 이 LLM 단계를 비활성화해 재현 가능한 출력을 생성한다.

정규화된 관점 결과는 `{"perspective": "market", "technologies": {"KIVI": {"market_size": {"label": "...", "reason": "...", "evidence_ids": ["..."]}}, "InfiniGen": {...}}, "status": "complete|insufficient_evidence"}` 형태다. `stakeholder`는 `competitor_view`, `adopter_view`, `investor_view`; `domain`은 `memory`, `quality`, `latency`, `throughput`, `integration`; `trl`은 `trl` 항목을 쓴다. C 브랜치 스키마가 다르면 합병 시 **어댑터 경계**에서 변환한다. 근거 ID는 `state.evidence`의 키와 일치해야 한다. 각 Evidence에는 `source_id`, `technology`, `claim`, `quote`, `location`, `claim_type`, `conditions`를 권장한다. Source에는 `title`, `url`, `source_type`을 권장한다.

## 검증 및 출력

규칙 검사는 기술별 필수 항목, 라벨 집합, 근거 ID의 실재성, 근거의 기술 일치를 확인한다. 의미적 지지 여부는 `semantic_review` 콜백을 연결해야 검증한다. 연결되지 않은 경우 규칙 검증만 수행했음을 manifest에 적는다. 근거 없는 항목은 두 번 보완한 후에도 `insufficient_evidence`로 남기고 보고서 한계점에 넣는다. 종합은 검증된 근거가 달린 판정만 사용하며 총점과 우승/추천을 계산하지 않는다. LLM SUMMARY가 새 숫자·근거 ID·우열 표현을 포함하면 규칙 기반 문장으로 대체한다. 보고서는 한국어, `SUMMARY` 시작, `REFERENCE` 종료다. 산출물은 `report.md`, `report.html`, `report.pdf`, `sources.json`, `run_manifest.json`이다.

CLI `python app.py --mode live|replay`는 통합된 서비스 모듈을 `--services package.module:factory`로 로드한다. replay에서 외부 웹 호출이 없는지는 B 브랜치의 어댑터 구현 책임이며 이 브랜치는 mode를 전달한다. `--fixture`는 통합 전 흐름 점검 전용 예제다. 실제 논문 분석 결과로 사용하면 안 된다.

## 합병 체크리스트

1. A/B/C 각 브랜치의 실제 출력 형태를 위 계약에 맞추는 어댑터를 만든다. C의 Pydantic 스키마와 D의 정규화 형식 사이 변환을 한 곳에 둔다.
2. 실제 `prepare`에서 PDF 페이지 합계 200 초과와 파싱 실패를 구조화된 오류로 보고한다. `technical`에서 각 기술의 근거가 하나 이상 있는지 확인한다.
3. B의 live/replay 웹 캐시, 검색/원문 조회 예산, A의 논문 검색을 `retry`에 연결한다. `missing_questions` 외 재검색을 하지 않는다.
4. C의 근거 검사/검토 LLM을 `semantic_review`에 연결한다. 스키마 오류, 근거 없음, 근거가 주장을 지지하지 않는 경우를 구분한다.
5. 실제 자료로 PDF 한글, 표/목차, 출처 링크와 수치 조건을 육안 검수한다. 이 브랜치의 PDF는 텍스트 중심이며 복잡한 표 배치는 통합 검수 대상이다.

## 작업 기록

- 2026-09-22: `main`을 복제하고 `feat/graph-output` 생성. 초기 저장소는 패키지 뼈대만 있고 서비스 구현은 없다.
- 2026-09-22: 설계계획서와 `langgraph-v1`의 State, Graph, Branching, SelfRAG, Multi-Report 예제를 검토. LangGraph 공식 Graph API의 reducer와 명시적 합류 사용법을 확인.
