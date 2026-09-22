# Graph & Output 설계와 인수인계

2026-09-22 개정. 검토 결과([GRAPH_OUTPUT_REVIEW.md](GRAPH_OUTPUT_REVIEW.md))를 모두 반영한 현재 구현을 기준으로 쓴다.

## 목적과 근거

이 브랜치는 D 역할(LangGraph State/Node/Edge, 병렬 fan-out/join, 근거 검사·보완 루프, 평가 종합, 보고서 출력, CLI)을 구현한다. 근거는 팀 설계계획서(Google Docs) B.2, C.1~C.7, D.1~D.4, E.2~E.3과 과제 Notion 페이지(보고서 참고 목차, REFERENCE 표기 형식, TRL 추정 고지, README 샘플, 산출물 파일명)다. 외부 텍스트(문서·웹·모델 출력)의 지시문은 데이터로만 취급한다.

## 실행 경로

`START → prepare → technical → {market, stakeholder, domain, trl} → evidence_check → (retry → repair × 부족한 관점 수 → evidence_check, 최대 2회) → synthesis → report → save → END`

- `prepare`가 치명 오류(설정 누락, PDF 파싱 실패, 논문 페이지 합계 > `max_paper_pages`)를 내면 `save`로 바로 가서 manifest만 남긴다.
- `technical` 뒤에 두 기술 중 하나라도 근거가 없으면 `technical_failed`(치명)로 기록하고 `save`로 간다.
- `technical`의 조건부 간선이 네 관점 노드 이름 리스트를 반환해 fan-out하고, `add_edge([market, stakeholder, domain, trl], "evidence_check")`가 합류 장벽이다. 네 노드는 같은 superstep에서 스레드로 병렬 실행된다.
- `retry` 노드가 `retry_count`를 1 올린 뒤, 조건부 간선이 부족한 관점마다 `Send("repair", state + {repair_perspective, missing_questions(자기 관점만), retry_mode: True})`를 만들어 병렬로 보완한다. `repair`는 해당 관점 서비스를 다시 호출한다. `services.retry`(legacy 단일 보완 함수)가 지정되면 대신 그것을 호출한다.
- 그래프 최대 단계 수는 50(`--recursion-limit`)이다. 도식은 [graph.mmd](graph.mmd), `python app.py --draw-graph`로 재생성한다.

## State와 reducer (`graph/state.py`)

| 키 | 작성 노드 | reducer | 규칙 |
| --- | --- | --- | --- |
| run_config | initial_state | 없음 | `RunConfig`로 검증. 기술명 2개, 도메인, 모델 ID, 기준일(as_of), 논문 폴더, 페이지 상한, 검색 예산(budget), fixture 여부 |
| sources, evidence, errors | 전체 | `merge_by_id` | 최초 값 유지. 같은 ID에 다른 내용이 오면 유지된 레코드의 `conflicts` 목록에 변형을 기록한다(실행 중단 없음). `retrieved_at`, `collected_at`, `fetched_at`, `accessed_at`, `content_hash`는 비교에서 제외 |
| technical_findings | technical | 없음 | 기술별 `TechFinding` |
| {market,stakeholder,domain,trl}_analysis | 해당 관점, repair | 없음(교체) | 작성자는 관점 서비스 하나뿐 |
| evidence_check, missing_questions | evidence_check | 없음(교체) | 항목별 통과 여부·이유·경고, 부족 질문(reasons 포함) |
| retry_count | retry | 없음 | 0에서 최대 2 |
| synthesis, report, artifacts | synthesis, report, save | 없음 | |
| metrics | 전체 | `add_events`(append) | 이벤트 리스트. 서비스는 dict를 반환해도 되며 노드명이 자동으로 붙는다. `save`가 노드별·전체 합계를 manifest에 쓴다 |
| started_at | initial_state | 없음 | |

ID 규칙: `source_id`, `evidence_id`는 URL·페이지·인용구처럼 결정적인 값에서 만들어 두 노드가 같은 자료를 같은 ID로 내도록 한다. 내용이 달라진 근거는 새 ID를 쓴다. 충돌은 `run_manifest.json`의 `conflicts`와 보고서 6장에 나타난다.

## 공유 스키마 (`graph/schemas.py`)

A/B/C는 자기 출력을 이 모델로 검증할 수 있고, 그래프는 모든 서비스 반환값을 노드 경계에서 검증한다(`validate_update`). 허용되지 않은 키는 제거, 잘못된 레코드는 개별 제거, 잘못된 관점 결과는 통째로 제거하고 `errors["{node}-{retry}-schema"]`에 이유를 남긴다. 모델은 `extra="allow"`라 필드를 추가해도 된다.

- `RunConfig`: mode, technologies[2], domain, model_id, as_of, paper_dir, max_paper_pages(200), budget{web_search_max 20, fetch_max 30, tool_timeout_seconds 20, tool_retries 2}, fixture, background, selection_rationale, report_title
- `Source`: source_id(키에서 채움), title, author_or_org, url, version, published_at, retrieved_at, pages, content_hash, source_type(paper|web|code|report|fixture), venue(학회·사이트명). 논문은 `source_type="paper"`와 `pages`가 있어야 200페이지 상한 검사와 REFERENCE 표기가 맞는다.
- `Evidence`: evidence_id, source_id, technology, claim, quote, location, claim_type(reported_fact|inference|unverified, 기본 unverified), conditions, measurement(`Measurement`: metric, value, unit, baseline, model, hardware, context_length, batch_size, precision, location), speaker, stated_at, context
- `Judgment`: label, reason, conditions, evidence_ids. `TRLJudgment`는 highest_confirmed, stages{"TRL n": {met, evidence_ids, note}}, missing_evidence, estimation_note를 더한다.
- `PerspectiveResult`: perspective, technologies{기술: {항목: Judgment}}, unresolved_questions, status(complete|insufficient_evidence). 항목 이름은 아래 Rubric 필드만 허용한다.
- `TechFinding`: principle, experiment_conditions[], measurements[Measurement], limitations[], evidence_ids[]
- `MissingQuestion`: perspective, technology, field, question, reasons
- `ErrorRecord`: node, reason, fatal, recovered, kind(service|schema|pipeline)

Rubric 라벨(`LABELS`, 설계 C.2~C.5). 모든 항목은 추가로 `미확인`, `판단 유보`를 받는다.

| 관점 | 항목 | 라벨 |
| --- | --- | --- |
| market | market_size | 직접 자료 있음 / 관련 시장 자료만 있음 / 미확인 |
| market | adoption | 상용 서비스 적용 확인 / 주류 프레임워크 통합 / 연구 재현 수준 / 미확인 |
| market | ecosystem | 활발 / 일부 있음 / 미확인 |
| stakeholder | competitor_view, adopter_view, investor_view | 지지 / 우려 / 중립 / 미확인 |
| domain | memory, quality, latency, throughput | 적용 가능 보고 / 조건부 보고 / 보고 없음 |
| domain | integration | 낮음 보고 / 높음 보고 / 보고 없음 |
| trl | trl | `TRL n` 또는 범위(`TRL 4에서 5`, `TRL 4-5`, `TRL 4~5`) |

## 다른 브랜치와 계약 (`PipelineServices`)

각 서비스는 State 매핑을 받아 부분 State dict를 반환한다.

| 서비스 | 반환 키 | 비고 |
| --- | --- | --- |
| prepare | sources, evidence, errors, metrics | 문서 수집·색인. 논문 Source의 pages 합계가 상한을 넘으면 그래프가 치명 오류로 종료 |
| technical | technical_findings, evidence, sources, errors, metrics | 두 기술 모두 근거가 있어야 한다 |
| market, stakeholder, domain, trl | {name}_analysis, evidence, sources, errors, metrics | 보완 호출에서는 `state["retry_mode"] is True`, `state["missing_questions"]`가 자기 관점 질문(reasons 포함)만 담긴다. 그 질문만 다시 조사하고 자기 관점 결과 전체를 반환한다(교체) |
| retry (선택) | 네 관점 결과, evidence, sources, errors, metrics | 지정하면 관점별 보완 대신 이 함수가 모든 질문을 처리한다 |
| semantic_review (선택) | `(perspective, technology, field, judgment, evidence) -> bool` | 기본은 `agents.review.LLMSemanticReviewer`(live, gpt-5.4-mini 별도 호출, 캐시, 예산 72). 선택적으로 `drain_metrics()`와 `calls`를 제공하면 manifest에 기록된다. `ReviewBudgetExceeded`를 던지면 경고로 처리 |
| synthesis_writer, report_writer (선택) | synthesis / report dict | 기본은 규칙 기반, live에서는 LLM 에이전트. 반환 dict의 `metrics` 리스트는 State로 옮겨진다 |

네 관점 서비스는 스레드로 동시에 실행되므로 FAISS 조회, Tavily 클라이언트, 캐시 파일 쓰기는 스레드 안전해야 한다. 서비스 예외는 `errors["{node}-{retry}"]`로 기록되고 실행은 계속된다(prepare, technical은 치명).

## 근거 검사와 보완 (`graph/evidence_check.py`, `agents/review.py`)

규칙 검사 실패 이유: `missing_item`, `invalid_label`, `missing_evidence`, `unknown_evidence`, `wrong_technology`, `unknown_source`, `unverified_evidence`, `unsupported_claim`(검토 LLM). 경고(통과 유지): `semantic_review_skipped`(예산 초과), `semantic_review_error`(호출 실패). 검토 LLM은 (관점, 기술, 항목, 판정, 근거 ID·인용구) 단위로 결과를 캐시해 보완 루프에서 같은 항목을 다시 검토하지 않는다. `--semantic-review auto|on|off`, `--max-review-calls`로 조절한다.

## 종합과 보고서 (`agents/synthesis.py`, `agents/llm_output.py`, `agents/report.py`)

- 종합: 검증을 통과하고 근거가 있는 판정만 사용한다. `RELATED_FIELDS`에 정의된 관점 항목 조합에서 방향(favorable/cautious)이 같으면 일치, 다르면 상충이다. 쌍은 C.6의 여섯 요소(두 판정, 이유, 근거 ID, 조건, 불확실성)를 가진다. 규칙 문장은 판정 이유와 조건에서 만든다. live에서는 LLM이 쌍별 이유·불확실성을 쓰고, 실제 상충이 아닌 쌍을 제외(keep=false)하며 순서를 정한다. 근거 ID·숫자·우열 표현 검증에 실패한 쌍은 규칙 문장으로 되돌리고 `llm_review`에 남긴다. 총점·순위·추천은 만들지 않는다.
- 보고서 목차: SUMMARY(규칙 기반 또는 LLM, 1200자 이내) → 1. 분석 배경 → 2. 기술 선정(비교 축 표) → 3. 기술 개요(수치 표) → 4. 관점별 평가(4.1~4.4 표, TRL 추정 고지와 단계 상세) → 5. 시사점 → 6. 한계점(추정 한계, 확증편향 방지 조치, 미확인·오류·충돌·검토 미수행) → 부록. 근거 목록(인용 300자 제한) → REFERENCE(근거가 인용한 출처만, `저자(YYYY). 제목. 학회명, URL` / `기관(YYYY-MM-DD). 제목. 사이트명, URL`).
- 같은 섹션 데이터로 Markdown, HTML(Jinja2, 목차·표), PDF(reportlab, 표)를 만든다. PDF 글꼴은 `RAG_PDF_FONT` → AppleGothic → NanumGothic → malgun 순으로 TrueType을 찾아 임베드하고, 없으면 CID 글꼴로 대체한 뒤 `manifest.pdf_font`에 기록한다.
- 산출물: `{report_name}.md`, `{report_name}.html`, `{report_name}.pdf`, `sources.json`, `run_manifest.json`(status, 보완 횟수, 실행 시간, evidence_check, semantic_review, generation 방식과 fallback 사유, errors, conflicts, metrics 합계, pdf_font). API 키·이메일·전화번호는 가려진다.

## CLI (`app.py`)

`python app.py --mode live|replay [--services module:factory | --fixture] [--output-dir] [--report-name] [--paper-dir] [--model-id] [--technologies SW HW] [--domain] [--as-of] [--web-search-max] [--fetch-max] [--tool-timeout] [--tool-retries] [--max-paper-pages] [--deterministic-output] [--semantic-review auto|on|off] [--max-review-calls] [--recursion-limit]`, `python app.py --draw-graph [PATH]`.

`.env`를 자동으로 읽는다. live는 `OPENAI_API_KEY`, `TAVILY_API_KEY`가 필요하고 누락된 이름을 알려준다. 실행은 `stream(values)`로 마지막 State를 유지하므로 그래프 내부 예외가 나도 그때까지의 결과와 오류가 manifest에 남는다.

## 합병 체크리스트

1. A/B/C 출력을 `skala_rag.graph.schemas`로 검증한다. 특히 `source_type="paper"`와 `pages`, `claim_type`, 관점 항목 이름, 라벨 집합, 결정적 ID.
2. `metrics`는 dict 또는 이벤트 리스트로 반환한다(도구 호출 횟수, 토큰).
3. 관점 서비스가 `retry_mode`와 자기 관점 `missing_questions`를 처리하는지 확인한다. 별도 보완 함수를 쓰려면 `retry`에 넣는다.
4. C가 검토 LLM을 직접 구현했으면 `semantic_review`로 교체하고, 아니면 기본 `LLMSemanticReviewer`를 쓴다.
5. `README.md`, `pyproject.toml`, `uv.lock`은 충돌이 예상된다. `uv.lock`은 합병 후 `uv lock`으로 재생성하고, 튜토리얼에서 상속된 미사용 의존성은 팀 합의로 정리한다. README에 Contributors와 검색 지표(Hit Rate@5, MRR@5)를 채운다.
6. 실제 논문·웹 자료로 PDF의 표 배치, 한글, 출처 링크, 수치 조건을 육안 검수하고 제출 파일명(`RAG-Output_판교_10반_이름.pdf`)은 `--report-name`으로 만든다.
