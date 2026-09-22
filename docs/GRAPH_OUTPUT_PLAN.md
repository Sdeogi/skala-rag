# Graph & Output 구현 계획

**목표:** D 역할의 그래프, 근거 검사/보완 루프, 종합, 보고서, CLI를 독립적인 테스트 주입 경계와 함께 제공한다.

**구조:** `src/skala_rag/graph`는 State/reducer/서비스 계약/흐름, `agents/synthesis`와 `agents/report`는 검증된 State만 소비, `templates/`는 HTML 레이아웃, 루트 `app.py`는 실행 진입점이다.

1. [x] State/reducer와 서비스 계약의 실패 테스트를 작성하고 구현한다.
2. [x] 병렬 합류, 두 번 보완, 조기 종료의 그래프 통합 테스트를 작성하고 구현한다.
3. [x] 종합에서 근거 없는 상충 제거와 조건/불확실성 보존을 테스트하고 구현한다.
4. [x] 보고서 목차, 인용, 다섯 산출물, CLI 설정 오류를 테스트하고 구현한다.
5. [x] 전체 테스트 및 fixture smoke run을 검증하고 본 문서와 설계 문서에 최종 결과와 통합 유의사항을 기록한다.

검증 명령: `.venv/bin/python -m pytest -q`, `PYTHONPATH=src .venv/bin/python app.py --mode replay --fixture --output-dir /tmp/skala-rag-graph-output-smoke`.

2026-09-22 검증: 병렬 동시 실행, 두 번 제한과 한 번 성공 보완, 치명적 조기 종료, 유효하지 않은 출처/라벨/TRL 범위, 의미 검토 콜백, LLM 출력 가드, 민감정보 가림, 직접 CLI 실행을 테스트했다. 합성 PDF의 한글과 마지막 REFERENCE를 렌더링하여 확인했다. 실제 논문·웹 근거로 전체 보고서를 실행하는 검증은 A/B/C 통합 후 가능하다.

6. [x] 2026-09-22 검토 결과(`GRAPH_OUTPUT_REVIEW.md`) 24개 항목을 모두 반영하고 테스트 47개, fixture·live 경로 실행, 깨끗한 환경 설치로 검증한다. 항목별 처리는 검토 문서 7절, 변경 내역은 이력 문서 2차 절에 기록했다.
