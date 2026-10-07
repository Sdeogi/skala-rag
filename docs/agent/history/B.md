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
