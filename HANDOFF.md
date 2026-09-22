# HANDOFF: C. Evaluation & Validation (feat/evaluation)

> 이 문서는 (1) 나중에 4개 브랜치를 통합할 에이전트가 참조하고, (2) 이 작업이 토큰 초과 등으로 중단되었을 때 다음 세션이 이어받기 위한 히스토리입니다. **작업이 진행될 때마다 갱신합니다.**

담당자: 이승석 (skala 판교 10반 6조, 이미지 분담표 기준 C)
브랜치: `feat/evaluation`
기준 문서: `RAG-Design_{판교}-{10반}_{김건우+김산+서경덕+이승석}.pdf`

---

## 0. 담당 범위 (이미지 기준)

| 항목 | 파일/디렉토리 |
|---|---|
| 도메인 평가 에이전트 | `src/skala_rag/agents/domain.py` |
| 기술 성숙도(TRL) 평가 에이전트 | `src/skala_rag/agents/trl.py` |
| Pydantic 공용 결과 스키마 | `src/skala_rag/schemas/state.py` |
| 위 두 에이전트의 Rubric 프롬프트 | `src/skala_rag/prompts/domain.py`, `src/skala_rag/prompts/trl.py` |
| 근거 검사 로직 | `src/skala_rag/evidence_check.py` |
| 보완 노드 (재검색·재판정 루프) | `src/skala_rag/supplement.py` |

> **배치 규약:** 팀 통일을 위해 `src/skala_rag/` 아래 (B의 `feat/web-evidence` 브랜치와 동일). `pyproject.toml`에 hatchling build-system을 추가해 editable 설치되므로 어디서든 `from skala_rag.X import Y` 가능.

관련 PDF 명세: **B.2 표(에이전트 표)**, **C.2 (TRL)**, **C.5 (도메인)**, **C.7 (점검표)**, **D.1 (State)**, **D.4 (분기와 종료 규칙)**.

---

## 1. 팀 인터페이스 계약 (통합 시 필수)

C의 산출물이 A/B/D와 어떻게 맞물리는지:

### 1.1 A(Paper RAG)에게 의존하는 것
- **도구 시그니처(가정):**
  ```python
  # src/skala_rag/tools/retrieve.py
  @tool("retrieve_papers")
  def retrieve_papers(query: str, tech: Literal["KIVI","InfiniGen"], k: int = 5) -> list[Evidence]:
      """논문에서 근거 청크를 반환. tech로 논문 필터링."""
  ```
- C의 도메인 에이전트가 factory `make_domain_evaluator(retriever=retrieve_papers)`로 주입받아 호출.

### 1.2 B(Web Evidence)에게 의존하는 것
- **도구 시그니처(가정):**
  ```python
  # src/skala_rag/tools/web.py
  @tool("search_web")
  def search_web(query: str, tech: Literal["KIVI","InfiniGen"], purpose: str = "adoption", max_results: int = 5) -> list[Evidence]:
      """Tavily 검색 후 원문 fetch·요약해 Evidence로 반환."""
  ```
- C의 TRL 에이전트가 factory `make_trl_evaluator(retriever=..., web_search=search_web)`로 주입받아 호출.

### 1.3 D(Graph & Output)에게 넘기는 것
- `src/skala_rag/agents/domain.py::make_domain_evaluator(retriever)` → 노드 반환값 `{"domain_analysis": PerspectiveResult, "evidence": {...}}`
- `src/skala_rag/agents/trl.py::make_trl_evaluator(retriever, web_search)` → 노드 반환값 `{"trl_analysis": PerspectiveResult, "evidence": {...}}`
- `src/skala_rag/evidence_check.py::evidence_check(state)` → `{"evidence_check": CheckResult, "missing_questions": list[Question], "retry_count": int}`
- `src/skala_rag/supplement.py::make_supplement_node(retriever, web_search)` → 노드 반환값 `{"retry_count": int, "evidence": {...}, "missing_questions": [], "domain_analysis": ..., "trl_analysis": ...}`
- 조건 분기(보완 vs 평가 종합)는 D가 담당. C는 `CheckResult.needs_retry` 필드를 노출.

### 1.4 모두가 공유하는 것
- `src/skala_rag/schemas/state.py` — Pydantic 스키마. **C가 최초 소유자.** A/B/D는 이걸 `from skala_rag.schemas.state import ...` 로 import해서 사용.
- 스키마 변경 시 C가 이 문서에 diff를 남긴다.

---

## 2. 결정 사항 (Decisions)

| 결정 | 값 | 이유 |
|---|---|---|
| PDF 파서 | PyMuPDF | PDF `B.4` 스펙 |
| 청크 | 350 토큰 / 50 겹침 | PDF `B.4` 스펙 |
| 임베딩 | `intfloat/multilingual-e5-small` (sentence-transformers) | PDF `B.5` 스펙 |
| 벡터스토어 | FAISS | PDF `B.1` / `B.5` |
| LLM (생성/검토) | `gpt-5.4-mini` | PDF `B.1` 스펙. 존재하지 않는 모델이면 실제 API 오류 시점에 대응 |
| PDF 파일 위치 | `data/papers/KIVI.pdf`, `data/papers/InfiniGen.pdf` | PDF `E.2` 스펙 |
| 개발 방식 | Jupyter 노트북 셀별 실행 → 검증 후 `.py`로 이관 | 사용자 요청 |
| 노트북 위치 | `notebooks/2x-*.ipynb` | 개발용, 프로덕션 코드와 분리 |

---

## 3. 파일 인벤토리

```
skala-rag/
├── HANDOFF.md                        # 이 문서 (C 담당)
├── pyproject.toml                    # hatchling build-system + skala_rag 패키지 등록
├── data/
│   └── papers/
│       ├── KIVI.pdf
│       └── InfiniGen.pdf
├── notebooks/                        # (gitignored — 개인 개발·검증용)
│   ├── 20-Schemas.ipynb
│   ├── 21-DomainAgent.ipynb
│   ├── 22-TRLAgent.ipynb
│   └── 23-EvidenceCheck.ipynb
└── src/skala_rag/                    # editable 설치되는 파이썬 패키지
    ├── schemas/
    │   └── state.py                  # 팀 공용 계약 (C)
    ├── prompts/
    │   ├── domain.py                 # (C)
    │   └── trl.py                    # (C)
    ├── agents/
    │   ├── domain.py                 # make_domain_evaluator factory (C)
    │   └── trl.py                    # make_trl_evaluator factory (C)
    ├── evidence_check.py             # 근거 검사 노드 (C)
    ├── supplement.py                  # 보완 노드 — 재검색·재판정 루프 (C)
    ├── tools/                        # (A/B 담당 — retrieve.py, web.py)
    ├── database/                     # (초기 셋업, 미사용)
    ├── config.py, main.py            # (초기 셋업, 미사용)
    └── __init__.py
```

---

## 4. 진행 로그 (Timeline)

### 2026-09-22
- **Phase 0 완료.**
  - `feat/evaluation` 브랜치 생성.
  - `data/papers/`, `notebooks/`, `schemas/`, `agents/`, `prompts/` 디렉토리 생성.
  - `KIVI.pdf`, `InfiniGen.pdf`를 프로젝트 루트 → `data/papers/`로 이동.
  - `pyproject.toml`에 `pymupdf>=1.24.0` 추가, `uv sync`로 pymupdf 1.28.2 설치 완료.
  - `.env` 파일이 아직 없음. 사용자가 OpenAI/Tavily 키를 `.env`에 채워야 노트북 21~23 실행 가능. 노트북 20(스키마)은 API 키 없이 실행 가능.

- **Phase 1 완료.**
  - `notebooks/20-Schemas.ipynb` 작성 (26셀). 모든 셀 통과 확인.
  - `schemas/state.py` 및 `schemas/__init__.py` 생성 (노트북 검증본 이관).
  - 이관 후 `from schemas.state import ...` 임포트 성공 확인.
  - **팀 인터페이스 확정:** A/B/D는 이제 `from schemas.state import Evidence, PerspectiveResult, State, ...` 로 임포트할 수 있음. 스키마 변경 시 이 문서에 diff 기록 필요.

- **Phase 2 완료.**
  - `prompts/domain.py` (DomainRubricSpec, DOMAIN_RUBRIC 5항목, SYSTEM/USER 프롬프트, 포맷터).
  - `agents/domain.py` (`make_domain_evaluator(retriever, model_name, k)` factory + `judge_one`).
  - `agents/__init__.py`, `prompts/__init__.py`.
  - Import 검증 OK.
  - **팀 통합 인터페이스 확정:** D는 `from agents.domain import make_domain_evaluator; from tools.retrieve import retrieve_papers; graph.add_node("domain", make_domain_evaluator(retrieve_papers))` 형태로 조립. Factory 패턴을 쓴 이유: A의 `tools/retrieve.py` 없이도 py 파일이 import 가능하고 테스트 가능하도록.
  - 노트북 21은 그대로 유지 (개발·검증용 참조).

- **Phase 3 완료.**
  - `notebooks/22-TRLAgent.ipynb` (28셀). 실행 결과: KIVI/InfiniGen 모두 **TRL 4**로 판정, status=complete, 미확인 0.
  - `prompts/trl.py` (TRLStageSpec 7개, TRL_SYSTEM_PROMPT, TRL_STAGE_USER_TEMPLATE).
  - `agents/trl.py` (`make_trl_evaluator(retriever, web_search, model_name)` factory + `judge_stage` + `judge_trl_for_tech` + `_highest_reached`).
  - Import 검증 OK.
  - **MVP 결정:** tech별 RubricItem 1개. 스키마 확장 없이 진행. 단계별 세분화는 후속.

- **Phase 4 완료.**
  - `notebooks/23-EvidenceCheck.ipynb` (23셀). 실행 결과: 기계 실패 3 + LLM 실패 1 = 4개 정확히 잡음, passed 1개(정상 케이스). `retry_count=2` 도달 시 종료 로직도 확인.
  - `evidence_check.py` (프로젝트 루트): `evidence_check(state, model_name)` 노드 + `machine_check` + `llm_review` + `to_missing_question` + `allowed_labels` 매핑.
  - Import 스모크 통과.

- **Phase 2/3/4 py 파일 임포트 계층 최종:**
  ```
  skala_rag.schemas.state           (0 dep — 팀 공용 계약)
  skala_rag.prompts.{domain,trl}    ← schemas
  skala_rag.agents.{domain,trl}     ← schemas, prompts
  skala_rag.evidence_check          ← schemas
  ```
  D의 그래프 조립부만 `skala_rag.agents.*.make_*`와 A/B의 `skala_rag.tools.*`를 wire하면 됨.

- **Phase 6 추가: 보완 노드 구현.**
  - `src/skala_rag/supplement.py::make_supplement_node(retriever, web_search, model_name)` factory.
  - DOMAIN: 각 missing_question의 (tech, item_key)를 재검색·재판정해 items에서 교체.
  - TRL: 해당 tech 전체(7단계) 재판정해 items에서 교체 (item_key 무관, tech 단위).
  - MARKET/STAKEHOLDER: 재판정 로직 없어 skip (B의 확장 여지).
  - `retry_count += 1`, `missing_questions = []` 리턴 (다음 evidence_check가 재생성).
  - Status·unresolved_questions 재계산해 PerspectiveResult 갱신.
  - 스모크 검증: KIVI/memory 미확인 → "조건부 보고"로 승격, quality 유지, status insufficient→complete 확인.
  - **이로써 PDF D.3 재시도 루프 완성:** `4관점 병렬 → evidence_check → (needs_retry?) → supplement → 다시 evidence_check → ... → 최대 2회 후 종합`.

- **Phase 5 후 리팩터: `src/skala_rag/` 아래로 이관.**
  - 최초 커밋(28691a6)은 PDF `E.2` 스펙대로 프로젝트 루트에 `agents/`, `prompts/`, `schemas/`, `evidence_check.py`를 두었으나, B(`feat/web-evidence`)가 초기 프로젝트 구조인 `src/skala_rag/` 아래에 코드를 넣은 것을 확인.
  - 팀 통합 마찰을 줄이기 위해 C 산출물도 `src/skala_rag/` 아래로 이동.
  - `pyproject.toml`에 `[build-system]` (hatchling) + `[tool.hatch.build.targets.wheel] packages = ["src/skala_rag"]` 추가 → `uv sync`로 editable 설치 완료.
  - 모든 내부 import를 `from skala_rag.X import Y` 절대 경로로 갱신.
  - 노트북(gitignored)들도 로컬 사용을 위해 동일하게 갱신.
  - Import 스모크 통과.
  - 구성: 환경 → 스키마 import → 논문 로드/청크/FAISS (Phase 2와 동일 임시 파이프라인) → 임시 `retrieve_papers` (A자리) → 임시 `search_web`(Tavily 래퍼, B자리) → TRL 7단계 rubric (`TRLStageSpec`) → 프롬프트 → `judge_stage` (충족/미충족/미확인) → `judge_trl_for_tech` (최고 도달 단계 계산 + missing_evidence_note 수집) → `trl_evaluator` 노드 → 실행 + 검증.
  - **MVP 결정:** tech별 `RubricItem` 1개(`item_key="trl_level"`, `verdict=TRLLevel.value`). 단계별 상세는 `reason`(요약)/`conditions`(missing evidence)로 표현. PDF의 "단계별 충족 여부와 근거 ID" 명시적 데이터 표현은 후속 이터레이션(단계별 RubricItem 7×2=14 확장) 필요 시 추가.
  - 단계별 근거 방식(PDF C.2 표):
    - TRL 1-2, 3: RAG (논문 서론·실험 절)
    - TRL 4~9: 웹검색 (GitHub, 프레임워크 PR, 기업 블로그, 제품 발표, 고객 사례)
  - Tavily 호출 예산: 20/실행 (PDF B.6). 예상 사용: 2 tech × 5 web-stage = 10 호출.
  - **사용자 실행 대기.** `.env`에 `TAVILY_API_KEY` 필수. 예상 소요 2~5분.
  - `notebooks/21-DomainAgent.ipynb` 작성 (27셀).
  - 1차 실행 결과: gpt-5.4-mini 정상 작동, 10개 판정 완주, status=insufficient_evidence(4개 미확인).
  - **1차 튜닝 이슈:** KIVI/integration이 "높음 보고"로 오라벨. 근거는 tuning-free + HF 통합(=쉬움)인데 LLM이 라벨 방향을 반대로 해석.
  - **1차 튜닝 적용:** 셀 16, 18, 20 개정.
    - `DomainRubricSpec`에 `label_notes: str | None = None` 필드 추가.
    - integration 항목에 `label_notes` 설정: "낮음 보고 = 통합 부담 낮음(쉬움), 높음 보고 = 통합 부담 높음(어려움)" 방향성을 예시와 함께 명시.
    - `USER_TEMPLATE`에 `{label_notes_block}` 자리 추가, `format_label_notes()` 헬퍼로 있을 때만 삽입.
    - `judge_one`에 `_unclear_label_for()` 헬퍼 추출로 항목별 미확인 라벨 매핑 명료화.
    - 부가: memory/quality/latency/throughput/integration의 검색 쿼리 힌트를 논문 특유 용어(LongBench, PCIe, per-token 등)로 강화해 재검색 히트율 향상 유도.
  - **사용자 재실행 대기:** 셀 16, 18, 20, 22, 24, 25.

---

## 4a. 통합 담당자용: A/B의 도구가 도착했을 때 무엇을 바꿔야 하는가

### py 파일 (agents/, prompts/, schemas/): 손대지 않음
`agents/domain.py`, `agents/trl.py` 는 factory 패턴이라 retriever/web_search를 인자로 받는다. A/B의 도구 시그니처가 우리 계약(1.1, 1.2)과 맞으면 코드 변경 없이 wiring만 하면 됨.

### D의 그래프 조립부
```python
from skala_rag.tools.retrieve import retrieve_papers      # A
from skala_rag.tools.web import search_web                # B
from skala_rag.agents.domain import make_domain_evaluator
from skala_rag.agents.trl import make_trl_evaluator
from skala_rag.evidence_check import evidence_check
from skala_rag.supplement import make_supplement_node

graph.add_node("domain",         make_domain_evaluator(retriever=retrieve_papers))
graph.add_node("trl",            make_trl_evaluator(retriever=retrieve_papers, web_search=search_web))
graph.add_node("evidence_check", evidence_check)
graph.add_node("supplement",     make_supplement_node(retriever=retrieve_papers, web_search=search_web))

# 조건 분기 (D)
graph.add_conditional_edges(
    "evidence_check",
    lambda s: "retry" if s["evidence_check"].needs_retry else "synthesize",
    {"retry": "supplement", "synthesize": "synthesis"},
)
graph.add_edge("supplement", "evidence_check")   # 다시 검사로
```

### C의 노트북 21, 22 (선택)
계속 검증용으로 유지하려면 셀 6~13 즈음(임시 파이프라인)을 A/B의 import 두 줄로 축약. 사용 안 하면 그대로 둬도 무방.

### `@tool` 시그니처 이슈
A/B가 `@tool` 데코레이터로 감쌌으면 순수 함수 호출이 안 됨. 두 가지 대응:
- A/B에 순수 함수도 함께 export 요청 (권장)
- C 쪽에서 어댑터 한 줄:
  ```python
  from tools.retrieve import retrieve_papers as _rp_tool
  def retrieve_papers(query, tech, k=5):
      return _rp_tool.invoke({"query": query, "tech": tech, "k": k})
  ```

## 5. 다음 세션 이어받기 체크리스트

이 프로젝트를 다른 Claude 세션이 이어받는 경우 아래 순서로 컨텍스트 복원:

1. 이 `HANDOFF.md` 전체 정독
2. `RAG-Design_*.pdf` 6~15페이지 (B/C/D 섹션)
3. `git log feat/evaluation --oneline` 로 커밋 흐름 확인
4. TaskList 확인 (있으면)
5. 마지막 완료된 노트북의 마지막 셀 확인 → 그 다음 셀부터 이어서 작성

---

## 6. 미결/보류 (Open Questions)

- **[해결 대기]** `evidence_check`가 C 파일인지 D 파일인지: 이미지에는 C, PDF `D.4`에는 그래프 노드로 기술. 우선 C가 `evidence_check.py`로 구현하고, 통합 시 D의 그래프에서 import하는 방식으로 진행.
- **[해결됨]** `gpt-5.4-mini` 모델 실존: 2026-09-22 도메인 에이전트 실행 시 정상 응답 확인. 이후 모든 노트북/코드에서 그대로 사용.
- **[해결 대기]** A/B의 도구 정확한 시그니처: C가 임시 stub으로 진행, 통합 단계에서 맞춤.
