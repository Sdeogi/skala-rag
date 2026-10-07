# 트랙 B 작업 이력 — 하위 에이전트 재작업

- 브랜치: `sup/agents`
- 이 파일은 트랙 B 담당만 쓴다. 다른 트랙은 읽기만 한다.
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

## 2026-10-07 14:00 · sup/agents · tmdtjr

**무엇을**: 하위 에이전트가 새 재작업 입력 계약을 소비하고, 재작업 지시마다 다른 결과를 내도록 어댑터와 검색어 생성기를 교체했다.
**왜**: 과거 실행에서 재작업을 돌려도 같은 검색어가 반복돼 라벨이 그대로였고, 검토 LLM의 거부 사유가 어디에도 반영되지 않았다. Supervisor가 새 입력 포맷을 보내도 어댑터가 못 알아듣는 문제도 있었다.
**바꾼 파일**:
- `src/skala_rag/integration/services.py` — 헬퍼 추가 `_rework_requests`/`_is_rework`/`_rework_attempt`/`_known_evidence_ids`, `_field_to_topic`, `_merge_search_log`, 상수 `_TECH_PAPER_IDS`/`_STAKEHOLDER_FIELD_TO_TOPIC`. 기존 `_missing` 제거. `_round_key`에 (perspective, tech) 추가. `_EvidenceCollector.existing`을 set으로. `make_web_perspective`/`make_domain`/`make_trl` 재작업 로직 교체: 지시받은 (tech, field)만 새 검색어로 재수집, TRL replay 강제 제거, 이미 충족된 stage 재사용, 각 perspective의 `search_log` 저장.
- `src/skala_rag/integration/rework.py` — 신규. `needs_research`/`needs_rejudge`로 reasons를 분류하고 `build_rework_queries`가 reasons·review_reason·question + paper_id로 새 검색어 2~3개를 생성(이전 쿼리는 중복 제외).
- `src/skala_rag/agents/market.py` — `collect_market_evidence`와 `evaluate_market`에 `queries_by_topic`/`topics` kwarg 추가. 기본값 유지 시 기존 `SEARCH_QUERIES` 그대로 사용.
- `src/skala_rag/agents/stakeholder.py` — `_search_topic`/`_collect_topic_evidence`에 `queries` kwarg, `collect_stakeholder_evidence`에 `topics`/`queries_by_topic` kwarg 추가. 기본값 유지 시 기존 동작 동일.
- `tests/test_integration.py` — "수집 성공한 기술은 재수집 안 함"과 "TRL 재작업은 replay 강제"를 보증하던 세 테스트(`test_web_perspective_repair_keeps_previous_judgments_without_new_searches`, `test_web_perspective_repair_recollects_only_failed_technologies`, `test_trl_repair_reads_web_pages_from_cache`)를 새 동작(지시받은 field만 재수집, live 모드 유지, 미충족 stage만 다시 검색)에 맞게 교체.
**남의 파일**: 없음. 전부 B 소유 파일.
**인터페이스 영향**: 하위 에이전트는 이제 입력으로 `rework_requests`와 `known_evidence_ids`를 우선적으로 읽는다. 옛 입력(`retry_mode`+`missing_questions`+`retry_count`)도 당분간 호환층에서 받아 변환하므로 workflow 쪽이 교체되기 전까지 양쪽 다 동작한다. 반환 형태 `{name}_analysis`에 선택적으로 `search_log: dict[tech, dict[field, list[str]]]`가 추가됐다. 반환 필드 자체는 `{name}_analysis`, `evidence`, `sources`, `errors`, `metrics`로 제한된다.
**충돌 시 지켜야 할 것**: 호환층 분기(옛 입력 → 새 입력 변환)와 `search_log`는 다음 라운드 중복 방지에 쓰이므로 지우지 말 것. `_round_key`의 (perspective, tech) 인자는 재작업 시 attempt별 error 키 격리에 필요하다.
**확인**: `.venv/bin/python -m pytest tests/test_integration.py -q` → 11/11, `.venv/bin/python -m pytest -q` → 89/89.

## 2026-10-07 15:30 · sup/agents · tmdtjr

**무엇을**: 웹 수집의 신뢰도와 비용을 통제하기 위해 노이즈 필터 보강, 단일 출처 편향 명시, 공유 웹 예산 객체를 넣었다.
**왜**: 과거 실행에서 (1) 이름만 KIVI와 겹치는 블로그 등 무관한 사이트가 필터를 통과했고, (2) 요약기가 관련 LLM 추론 시장 자료를 기술 자체의 시장 자료로 올려 "직접 자료 있음"으로 잘못 분류됐으며, (3) 이해관계자 검색어 하나의 실패가 기술 전체 수집 실패로 번졌고, (4) 판정이 자기 논문 한 편만 인용해도 편향 고지가 없었으며, (5) 예산 20회가 강제되지 않아 34회가 나갔다.
**바꾼 파일**:
- `src/skala_rag/tools/budget.py` — 신규. `WebBudget`(threading.Lock + search/fetch 카운터)와 `BudgetExhausted` 예외.
- `src/skala_rag/tools/web.py` — `install_web_budget`/`clear_web_budget`/`installed_web_budget` 훅과 live 분기 전 `_consume_search`/`_consume_fetch` 호출 추가. replay 모드는 그대로.
- `src/skala_rag/agents/market.py` — `NOISE_DOMAINS` 블랙리스트, 모든 토픽에서 원 논문 제외, `_effective_scope` 헬퍼(scope="technology"지만 quote/claim에 기술명 없는 항목을 "related_market"으로 강등해 "직접 자료 있음" 오류 차단).
- `src/skala_rag/agents/stakeholder.py` — `NOISE_DOMAINS`, 모든 축에서 원 논문 제외(`_is_original_paper` 추가), `_search_topic`에서 쿼리별 예외 격리(한 쿼리 실패가 전체로 번지지 않음).
- `src/skala_rag/integration/services.py` — `IntegrationSettings.budget` 필드, 헬퍼 `_rebuild_and_install_budget`/`_ensure_budget_installed`/`_combined_evidence`/`_mark_single_source` 추가. `make_prepare`에서 run_config의 budget으로 리셋+설치, `create_services`에서 `WebBudget` 하나 생성, 각 perspective 서비스에서 `_ensure_budget_installed` + 반환 전 `_mark_single_source`로 단일 출처 판정에 "단일 출처" 마커 삽입.
- `tests/test_integration.py` — domain·trl adapter 테스트가 단일 출처 마커 포함 여부를 체크하도록 수정(기존은 정확 일치).
**남의 파일**: 없음. 전부 B 소유 파일.
**인터페이스 영향**: 각 판정의 `conditions`에 상황에 따라 ` / 단일 출처` 접미사가 붙는다. `tools/web.get_search_results`/`get_source`가 live 호출에서 `BudgetExhausted`를 던질 수 있고, agent/collector의 기존 Exception 캐치가 이걸 비치명 오류로 기록한다. `run_config["budget"]`에 `{"web_search_max": N, "fetch_max": M}`을 넣으면 그 상한으로 리셋된다(기본 20/30).
**충돌 시 지켜야 할 것**: 공유 `WebBudget`은 `create_services`에서 한 번 만들어 `IntegrationSettings.budget`에 저장되고 `tools/web`에 설치된다. `install_web_budget`/`clear_web_budget` 호출 순서를 바꿔 설치를 날리지 말 것. `_mark_single_source`는 `_combined_evidence(state["evidence"], 새로 수집한 evidence)`를 받으므로 이 입력을 잘라내지 말 것.
**확인**: `.venv/bin/python -m pytest -q` → 89/89.

## 2026-10-07 16:00 · sup/agents · tmdtjr

**무엇을**: 재작업 계약·웹 예산·쿼리 격리·반환값에 대한 테스트를 추가해 과제 요구 체크리스트를 커버했다.
**왜**: 코드가 의도대로 동작하는지 가짜 서비스로 검증하기 위함. 이전 작업에서 교체한 통합 테스트가 "지시받은 field만 재수집"을 이미 커버하므로, 나머지(쿼리 변화, review_reason 반영, 예산 소진, 쿼리 격리, 제어 필드 미유출)를 추가로 작성.
**바꾼 파일**:
- `tests/test_rework.py` — 신규. `build_rework_queries` 단위 테스트: research/rejudge 분류, review_reason 키워드가 쿼리에 반영, 사전 쿼리와 중복되는 쿼리 제외, 넓힘 변형(limitation/issue 포함), rejudge-only 요청에도 폴백 쿼리.
- `tests/tools/test_budget.py` — 신규. `WebBudget.try_search`/`try_fetch` 상한, `reset`, `tools.web.get_search_results`가 live 호출에서 `BudgetExhausted`를 던지는지, replay 모드는 예산 소비 안 하는지. autouse fixture로 모듈 레벨 budget을 테스트 간 격리.
- `tests/test_integration.py` — 3개 통합 테스트 추가:
  - `test_rework_passes_fresh_queries_to_agent` — 재작업 시 agent에 `queries_by_topic`과 `topics`가 전달되고, `unsupported_claim` 사유에 따옴표 처리된 기술명이 쿼리에 들어간다.
  - `test_stakeholder_search_topic_isolates_query_errors` — 쿼리 하나가 raise해도 나머지 쿼리 결과는 수집되고 errors에 그 쿼리 에러만 기록된다.
  - `test_services_return_only_payload_keys` — 네 perspective 서비스 반환값에 Supervisor 소유 제어 필드(`agent_status`, `next`, `decision_log` 등)가 없다.
**남의 파일**: 없음.
**인터페이스 영향**: 없음. 테스트만 추가.
**충돌 시 지켜야 할 것**: `tests/tools/test_budget.py`의 `_clear_budget` autouse fixture는 `tools.web`의 모듈 레벨 budget 설치를 매 테스트 전후로 비운다. 지우면 다른 테스트와 상태가 섞인다.
**확인**: `.venv/bin/python -m pytest -q` → 105/105.
