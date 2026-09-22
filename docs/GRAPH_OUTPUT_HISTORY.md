# D 역할 작업 이력 / 다음 작업자를 위한 체크포인트

## 현재 상태

- 작업 위치: `/Users/kunwoo/Desktop/workspace/0918_RAG_Pipeline_설계_및_구현/skala-rag`
- 브랜치: `feat/graph-output` (원격 `main`을 복제해 생성)
- 담당: LangGraph State/Node/Edge, 네 관점 병렬 실행/합류, 근거 보완 루프, 종합, 보고서, CLI
- 팀원 구현 미합병. fixture만으로 완전한 그래프를 실행할 수 있다. 실제 연구 보고서는 팀 서비스 연결 전에는 생성할 수 없다.

## 참고와 결정

1. Google Docs 설계계획서 B/C/D/E 장을 읽었다. 첨부 역할 표와 사용자 최신 지시를 기준으로 D를 담당한다. 문서의 예전 E.1 담당자 배정은 이번 구현 범위를 결정하는 데 사용하지 않았다.
2. Notion URL은 연결 계정에서 `object_not_found`(404)였고 브라우징으로도 접근되지 않았다. 과제 페이지의 미확인 세부사항은 추가 구현 근거로 사용하지 않았다.
3. `ai_service/langgraph-v1`의 State, Graph, Branching, SelfRAG, Multi-Report 예제와 최신 공식 Graph API를 확인했다. `add_edge([market, stakeholder, domain, trl], evidence_check)`가 네 결과의 합류 장벽이다.
4. 종합과 보고서의 근거 기반 골격은 규칙으로 작성한다. live에서는 LLM이 종합 후보를 정렬하고 SUMMARY 문장을 작성하며, 새 숫자·근거 ID·우열 표현은 거부한다. replay는 규칙 기반으로 출력한다. 상충 쌍은 관련성이 정의된 관점 항목 조합에서만 만든다. 총점/순위/도입 추천을 계산하지 않는다. 근거 의미 검토는 `semantic_review` 주입 지점으로 남겼다.

## 구현 순서와 재현 명령

1. 저장소를 처음에는 잘못된 현재 작업공간 `0818_0820_SpringAI/skala-rag`에 복제했으나, 사용자 확인 직후 전체 저장소를 위의 `0918.../skala-rag`로 이동했다. 현재 작업은 올바른 폴더에서 수행 중이다.
2. `docs/GRAPH_OUTPUT_DESIGN.md`와 `docs/GRAPH_OUTPUT_PLAN.md`를 작성했다.
3. 테스트를 먼저 작성하고 import 실패를 확인한 뒤 State/reducer, 근거 검사, synthesis/report, workflow를 구현했다.
4. 최초 LangGraph 컴파일에서 조건부 간선의 노드 목록 매핑이 허용되지 않아 `fan_out` 노드를 명시적으로 추가했다. 수정 후 병렬 합류 테스트가 통과했다.
5. `app.py`, HTML 템플릿, PDF 저장과 fixture를 구현했다. `python app.py`가 설치 전에도 `src` 패키지를 찾게 했다.
6. 합성 fixture로 Markdown/HTML/PDF/sources/manifest를 만들고 PDF 첫 장과 마지막 장을 렌더링해 한글과 구조를 확인했다. LLM 출력의 근거 ID·숫자 제한, 민감정보 가림과 TRL 범위 라벨을 추가했다.
7. 원격 업로드 직후 README의 테스트 명령을 `PYTHONPATH` 없이 재현했을 때 `src` import가 실패했다. pytest 설정에 `pythonpath = ["src"]`를 추가해 문서의 명령을 그대로 실행 가능하게 했다.

```bash
cd '/Users/kunwoo/Desktop/workspace/0918_RAG_Pipeline_설계_및_구현/skala-rag'
uv sync --group dev
source .venv/bin/activate
python -m pytest -q
python app.py --mode replay --fixture --output-dir /tmp/skala-rag-graph-output-smoke
```

## 통합 시 가장 먼저 할 일

1. A/B/C 브랜치 출력과 `PipelineServices` 계약을 대조한다. 특히 기술명, 증거 ID, Source ID, 관점 항목 키와 라벨을 맞춘다.
2. C의 의미 검토를 `semantic_review`에 연결하고 검토가 통과한 항목만 종합에 사용되는지 확인한다.
3. `retry` 서비스가 `missing_questions`에 적힌 항목만 조회하고, 상태의 해당 관점 키만 교체하는지 확인한다.
4. `live`의 API 예산/재시도와 `replay`의 네트워크 미사용을 검증한다.
5. 실제 PDF에서 한국어 글꼴, 정량 수치의 조건, 출처 링크와 표 배치를 육안 검수한다.

## 미해결 사항

- A/B/C 브랜치가 현재 `main`에 없으므로 실제 논문/웹 근거를 통한 끝단 실행은 아직 검증할 수 없다.
- 의미 검토 LLM이 미연결이면 규칙 검증만 수행한다. manifest에 이 사실이 표시된다.
- PDF는 현재 텍스트 중심 A4 보고서다. 실제 데이터에 복잡한 표가 들어오면 통합 단계에서 레이아웃 검수가 필요하다.
- 모델 API 키가 없어 live 모드의 실제 LLM 호출은 실행하지 않았다. LLM 에이전트의 입력/출력 경계와 fallback은 fake 모델 테스트로 검증했다.
