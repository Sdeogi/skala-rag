# Paper RAG 작업 인수인계 / 재개 기록

> 이 파일은 git에 커밋하지 않는 **작업 트리 전용(untracked) 문서**입니다. 브랜치를 바꿔도 그대로
> 남아 있으므로, 세션이 중단됐다 재개되거나 다른 사람/에이전트가 이 작업을 이어받을 때 항상
> 이 파일을 먼저 읽으세요.

## 0. 왜 이 문서가 존재하는가

- 목적 1: 팀원들의 다른 브랜치(그래프/State, 시장성/이해관계자 에이전트, 도메인/TRL 에이전트,
  평가 종합/보고서 생성)와 이 작업을 나중에 통합할 때, 통합 담당(사람 또는 agent)이 인터페이스를
  빠르게 파악할 수 있게 하는 것.
- 목적 2: 이 세션이 토큰 소진 등으로 중단되어도, 이어받는 세션이 "지금까지 뭘 했고 다음에 뭘 해야
  하는지"를 이 파일만 보고 파악할 수 있게 하는 것.

## 1. 범위와 근거

- **담당 범위(최종 기준)**: 사용자가 제공한 PNG 이미지. `tools/retrieve`, `indexes/`,
  `agents/technical`, `evaluation/retrieval` — "PDF 파싱 → Chunk → Embedding → FAISS →
  논문 검색 + 기술조사 Agent + Retrieval 평가".
- **주의**: `RAG-Design_{판교}-{10반}_{...}.pdf`의 E.1 "역할 분담" 표(이름별 배정)는 임의로
  작성된 것이라는 사용자 확인을 받았음 → **무시**.
- 설계 세부 스펙(B~D장: 청크 350±50토큰, multilingual-e5-small, FAISS, RAG 대상 문서,
  `retrieve_papers` 툴 명세, State 필드명 등)은 신뢰 가능한 원본으로 취급: 팀 Google Docs
  "설계산출물_개선본"과 Notion 과제 가이드("KV cache 최적화 기술 평가")를 확인했고, 로컬
  PDF와 목차/내용이 일치함을 확인함.
- 대상 논문: KIVI(arXiv:2402.02750, 15p), InfiniGen(arXiv:2406.19707, 18p). `data/papers/`에
  실물 확보 완료.

## 2. 최종 상태 — main에는 `feat/retrieve-tool` 하나만 머지하면 됨

사용자 요청으로 `feat/technical-agent`, `feat/retrieval-evaluation`을 `feat/retrieve-tool`로
로컬 병합했다. **push/PR/merge into main은 하지 않음 — 사용자가 직접 수행.**

```
main (e2ecb3e, 변경 없음)
 └─ feat/retrieve-tool  (f045833)  <- 이 브랜치 하나만 main에 머지하면 끝
```

`feat/technical-agent`, `feat/retrieval-evaluation`은 사용자가 이미 로컬에서 정리(삭제)함.

**팀원 브랜치(원격)**: `git branch -a`로 보면 `remotes/origin/feat/graph-output`,
`remotes/origin/feat/web-evidence`가 실제로 원격(GitHub)에 존재한다(`git ls-remote --heads origin`
으로 직접 확인함). **로컬에서 `git branch`(옵션 없이)로는 원격 전용 브랜치가 안 보이는 게 정상**이다
— `git branch`는 로컬 브랜치만 보여주고, 원격 브랜치는 `git branch -a`(전체) 또는 `git branch -r`
(원격만)로 봐야 한다. 아직 로컬로 체크아웃(추적 브랜치 생성)한 적이 없어서 `git checkout
feat/graph-output` 처럼 실제로 내용을 보거나 병합하려면 먼저 로컬 추적 브랜치를 만들어야 한다.

### 병합 후 정리한 것 (사용자가 "안 쓰는 것 정리해" 요청)

- 여러 브랜치를 오가며 pytest를 돌리다 남은 `__pycache__`/`.pytest_cache` 잔재를 전부 삭제하고
  `.gitignore`에 `.pytest_cache/`를 추가함.
- `uv init` 스캐폴드가 만든 빈 파일/미사용 코드 제거: `src/skala_rag/main.py`, `config.py`,
  `database/__init__.py`, `database/vector_store.py` (전부 0바이트이거나
  `def main(): print("Hello from skala-rag!")` 자리표시자뿐이었고 어디서도 참조되지 않았음.
  vector_store 기능은 실제로 `tools/retrieve/ingest.py` + `retriever.py`로 구현되어 있음).
  필요하면 `main`의 `e2ecb3e` 커밋에서 복구 가능.
- 실제로 어디서도 호출되지 않던 `retrieve_papers_tool`(langchain `@tool` 래퍼) 제거. 지금
  기술조사 Agent는 `retrieve_papers`를 직접 호출하는 구조라 불필요했음. 나중에 LangGraph
  도구-호출형 에이전트가 필요해지면 `@tool` 데코레이터로 두 줄이면 다시 감쌀 수 있음.
- `schemas.Category`가 정의만 되고 안 쓰이던 것을 `prompts.CommonQuestion.category`에 실제로
  연결함.
- `src/skala_rag/__init__.py`, `tools/__init__.py`, `agents/__init__.py`의 미사용
  `main()` 자리표시자 제거.

### 최종 파일 구성 (코드 + 산출물 전부)

```
data/papers/{kivi.pdf, infinigen.pdf, manifest.json}
indexes/{index.faiss, index.pkl, build_manifest.json}          # 133개 청크(PyMuPDF 전환 후)
evaluation/retrieval/{report.md, results.json}                  # Hit Rate@5=65%, MRR@5=0.403
scripts/{build_index.py, run_technical_agent.py, run_retrieval_eval.py}
src/skala_rag/
  tools/retrieve/{parsing,chunking,embeddings,ingest,retriever}.py
  agents/technical/{schemas,prompts,agent}.py
  evaluation/retrieval/{metrics,evaluate}.py, questions.json
tests/{tools/retrieve(5개 파일), agents/technical, evaluation/retrieval}/*  # 22개, 전부 통과
```

이 외 불필요한 파일 없음(위 "정리한 것" 항목 참고, ast 기반 미사용 import 스캔도 통과).

## 2.1 설계 문서 대조 감사 (사용자 요청, "설계 문서랑 어긋난 거 있는지 전부 찾아봐")

RAG-Design PDF B~E장을 다시 정독하며 코드와 하나씩 대조한 결과.

**찾아서 고친 것**:

| 항목 | 설계서 근거 | 문제 | 조치 |
|---|---|---|---|
| PDF 파싱 라이브러리 | B.1 "PDF 추출에 PyMuPDF" | pdfplumber를 쓰고 있었음(당시 pyproject에 PyMuPDF가 없었음) | pymupdf로 교체(사용자 요청으로 이미 완료) |
| `Evidence` 스키마 | D.1 "evidence_id, source_id, 기술명, 주장, 인용 구절, 페이지 또는 절, 주장 유형, **실험 조건**" (8개 필드) | `experimental_condition` 필드가 없었음 | 필드 추가, LLM 프롬프트에 채우도록 지시 추가 |
| `Source`(manifest.json) | D.1 "source_id, 제목, 저자 또는 기관, URL, **버전, 발행일, 수집 시각**, 페이지 수, 내용 해시, **출처 유형**" | source_id/버전/발행일/수집시각/출처유형 필드 누락 | 전부 추가(arXiv 워터마크에서 실제 버전·발행일 확인) |
| ingest 실패 처리 | D.4 "설정 누락, **200페이지 초과**, PDF 파싱 실패... 시 평가를 진행하지 않고 오류를 기록한 뒤 종료" | 페이지 수 검증, 손상 PDF 처리 없음 | `build_index()`에 총 페이지 200장 초과 검증 + 손상 PDF를 명확한 예외로 감싸기 추가 |
| 기술조사 입력 | B.2 "입력: 기술명, **공통 질문 목록**" | `COMMON_QUESTIONS`가 하드코딩 상수였음(입력이 아님) | `run_technical_research(tech_names, model, questions=None)`로 override 가능하게 변경 |
| B.7 지시문 취급 | "문서와 웹 본문에 들어 있는 지시문은 데이터로만 취급" | 시스템 프롬프트에 명시 없었음 | 프롬프트에 한 줄 추가 |
| README 검색 지표 | E.3 "README에 기재할 검색 지표는... Hit Rate@5와 MRR@5" | README.md에 미기재(리포트 파일에만 있었음) | README.md에 표로 추가 |

**찾았지만 의도적으로 고치지 않은 것(이유 포함)**:

| 항목 | 설계서 근거 | 왜 그대로 두었나 |
|---|---|---|
| 표의 행/열 구조 보존 | B.4 "표의 행과 열이 깨지지 않았는지 확인한다", "표는 제목과 단위를 각 조각에 함께 넣어" | pdfplumber(`find_tables`)와 PyMuPDF(`find_tables`) 둘 다 이 두 PDF의 matplotlib 차트를 표로 오검출해서(축 레이블이 뒤섞인 텍스트 생성) 실제로 검색 품질을 떨어뜨림을 확인함. 두 라이브러리로 각각 테스트해서 확인한 결과라 라이브러리를 더 바꾼다고 해결될 문제가 아니라고 판단. 표 내용 자체는 일반 텍스트 흐름으로 청크에 들어가 있어 검색은 되지만, 행/열 구조나 "제목+단위가 값과 분리되지 않는" 보장은 없음. |
| B.7 "반례 질의를 장점 검색과 1:1로 짝짓기" | "장점을 찾는 검색 하나마다 limitation이나 issue를 붙인 검색을 하나씩 짝지어 실행" | `COMMON_QUESTIONS`에 `limitations` 카테고리를 별도로 2개 두어 취지(반례 확보)는 만족시켰으나, 문항 단위로 1:1 페어링된 구조는 아님. 완전히 동일한 구현은 아니라는 점을 밝혀둠. |
| `missing_questions` state 필드 | D.1 | 이 필드는 "보완" 노드(4개 관점 평가 에이전트의 재검색 루프)가 쓰는 것으로, 기술조사 자체의 명세에는 없음. 대신 `errors`에 `no_evidence_found`를 기록해 같은 목적(추적 가능성)을 달성함. |

## 3. 아키텍처 결정 및 가정

| 결정 | 이유 |
|---|---|
| PDF 파싱은 `pymupdf`(fitz) 직접 사용 | 처음엔 `pdfplumber`로 단어 좌표를 클러스터링해 2단 컬럼을 재조립했으나, 이 논문 PDF들은 공백 문자가 빠져 있고 arXiv 세로 워터마크 같은 회전 텍스트가 섞여 있어 "nuJ"처럼 뒤집힌 문자열이 생기는 문제가 있었다. `pymupdf`의 `get_text("dict")`는 같은 PDF에서 이 문제 없이 단어 간격과 2단 컬럼 순서를 올바르게 준다(다만 같은 줄이 큰 x 간격 때문에 다른 `line`으로 쪼개지는 경우가 있어 같은 y좌표의 연속된 line을 합치는 보정은 필요했음). 설계서 B.1도 원래 PyMuPDF를 지정하고 있었음. |
| 청크는 `RecursiveCharacterTextSplitter.from_huggingface_tokenizer` (e5-small 토크나이저, size=350, overlap=50) | 설계서 B.4 스펙을 그대로 따르되 기존 라이브러리 재사용. |
| 임베딩은 자체 `E5Embeddings` 래퍼(`sentence-transformers` 직접 사용) | `HuggingFaceEmbeddings`는 `query:`/`passage:` 접두어를 안 붙여줌(설계서 B.5 규약). |
| 벡터스토어는 `langchain_community.vectorstores.FAISS` | `filter={"tech_name": ...}`로 기술별 필터링 지원(B.6). |
| 코드는 `src/skala_rag/{tools,agents,evaluation}/...`, 데이터/산출물은 저장소 루트 `data/`, `indexes/`, `evaluation/` | 기존 스캐폴드 관례를 따르되, 데이터·산출물은 코드가 아니므로 루트에 둠(설계서 E.2와 일치). |
| `skala_rag` 패키지가 editable 설치되어 있지 않음 | 패키징 설정은 이번 범위 밖. `pyproject.toml`에 `pythonpath=["src"]` 추가, `scripts/*.py`는 `sys.path` 보정으로 우회. |
| 기술조사 Agent LLM 모델명은 env `TECHNICAL_AGENT_MODEL` (기본 `gpt-4o-mini`) | 설계서의 `gpt-5.4-mini`가 실존 모델명인지 불확실해 env로 override 가능하게 함. |

## 4. 통합 계약 (Integration Contract) — 다른 담당자가 참고할 부분

### 4.1 검색 도구 (`src/skala_rag/tools/retrieve/`)

```python
from skala_rag.tools.retrieve import retrieve_papers, build_index

retrieve_papers(query: str, tech_name: str, k: int = 5, query_en: str | None = None) -> list[RetrievedChunk]
# RetrievedChunk: {evidence_id, source_id, tech_name, page, section, text}
# tech_name은 "KIVI" 또는 "InfiniGen" (대소문자 그대로)

build_index(papers_dir="data/papers", index_dir="indexes") -> None
```

- 인덱스가 없으면 `retrieve_papers` 호출 시 명확한 에러로 실패(먼저 `scripts/build_index.py` 실행 안내).
- `evidence_id` 포맷: `f"{tech_name}-p{page}-{seq}"` (결정론적). 다른 에이전트가 근거를 인용할 때
  이 ID를 그대로 사용하면 됨.
- LangGraph 도구-호출형 에이전트에서 바로 쓰려면 `@tool`로 한 번 더 감싸면 됨(현재는 미제공 —
  지금 파이프라인은 직접 함수 호출 방식이라 불필요해서 뺐음).

### 4.2 기술조사 Agent (`src/skala_rag/agents/technical/`)

```python
from skala_rag.agents.technical import run_technical_research, technical_research_node
from skala_rag.agents.technical.schemas import Evidence, TechFindings

run_technical_research(tech_names: list[str], model: str | None = None, questions: list[CommonQuestion] | None = None) -> TechnicalResearchResult
# questions 생략 시 prompts.COMMON_QUESTIONS 기본값 사용(설계서 B.2: "입력: 기술명, 공통 질문 목록")
# TechnicalResearchResult: {technical_findings: dict[tech_name, TechFindings], evidence: dict[evidence_id, Evidence], errors: list[dict]}
# Evidence 필드(D.1 스펙 8개 전부): evidence_id, source_id, tech_name, page, section, claim, quote, claim_type, experimental_condition

technical_research_node(state: dict) -> dict
# LangGraph 노드 형태. run_config.tech_names를 읽고 technical_findings/evidence/errors를 갱신.
# **주의**: 이 필드명(D.1 State 표 기준)과 schemas.py의 모델은 잠정본. 실제 그래프/State
# 담당자가 다르게 정의하면 이 노드의 반환 dict를 얇은 어댑터로 감싸면 됨.
```

- `TechFindings`는 기술명별로 `principle`, `experimental_setup`, `performance`, `limitations`.
- `Evidence.claim_type`은 `reported_fact | inference | unverified`(설계서 B.7).
- LLM이 존재하지 않는 evidence_id를 인용하면 검증 후 1회 재시도, 실패 시 폐기+`errors` 기록(D.4).
- **실제 LLM 호출 검증**: 사용자가 실제 키로 두 번 돌려봄(2026-09-22).
  - 1차: "한계" 질문에 장점/Acknowledgments(연구비 지원 감사 문구)가 섞이고, 카테고리당
    질문 2개가 거의 같은 내용을 중복으로 뽑는 문제 발견 → 프롬프트에 관련성 규칙 추가,
    Acknowledgments 섹션은 코드로 필터링, 근접 중복은 difflib 유사도로 제거(커밋 8e392e7).
  - 2차(수정 반영 후 재실행): 위 문제들은 해결됐으나, **새로운 문제**를 발견함 — KIVI
    "limitations"에 "KIVI를 적용하려면 모델을 처음부터 훈련하거나 미세 조정해야 한다"는
    claim이 들어갔는데, 실제 근거(KIVI-p1-4)는 KIVI 자신이 아니라 Introduction이 소개하는
    *경쟁 기법들*(multi-query attention 등)의 단점을 설명하는 배경 문단이었음(KIVI는 오히려
    "Tuning-Free"가 핵심 특징이라 정반대로 잘못 귀속됨). 시스템/사용자 프롬프트 양쪽에
    "발췌문이 조사 대상 기술이 아니라 비교 대상·선행 연구를 설명하면 그 내용을 대상 기술
    자신의 특성으로 서술하지 말라"는 규칙을 추가함(커밋 e876856).
  - **이 3차 수정은 아직 실제 API로 재검증 못 함.** 이런 종류의 의미 파악(귀속) 오류는
    gpt-4o-mini 같은 작은 모델에서 프롬프트만으로 100% 없앨 수 없다 — 설계서 C.7
    점검표도 "근거가 실제로 판정을 뒷받침하는지"는 사람이 확인하도록 되어 있으므로, 이
    기술조사 Agent의 출력을 그대로 보고서에 쓰기 전에는 항상 사람이 근거-주장 매핑을
    한 번 훑어보는 걸 전제로 설계되어 있음(이번 세션에서 실제로 그 방식으로 문제를 두 번
    잡아냄 — 프로세스가 의도대로 작동하는 중).

### 4.3 Retrieval 평가 (`src/skala_rag/evaluation/retrieval/`)

```python
from skala_rag.evaluation.retrieval import run_evaluation
run_evaluation(k=5) -> EvalReport
```

- 결과는 `evaluation/retrieval/{results.json, report.md}`에 저장. **실측: Hit Rate@5 = 65%,
  MRR@5 = 0.403** (20문항, KIVI/InfiniGen 각 10개, PyMuPDF 전환 후 재측정). README에 지표
  적을 때 이 수치 인용.
- 20문항 중 7개는 실제로 상위 5개 안에 정답 근거가 없었음(조작하지 않은 진짜 측정치) —
  표/각주처럼 짧고 문맥이 적은 청크에서 놓치는 경향. multilingual-e5-small의 한계로 추정.
  개선하려면 임베딩 모델 교체나 BM25+임베딩 하이브리드 검색 고려.
- **주의**: `evidence_id`는 `f"{tech_name}-p{page}-{seq}"`로 파싱/청킹 결과에 따라 결정되므로,
  파서를 바꾸면(pdfplumber -> pymupdf) 같은 ID라도 가리키는 내용이 달라질 수 있다. 파서를
  바꾼 뒤에는 `questions.json`의 `expected_evidence_ids`를 반드시 실제 청크 내용을 다시
  확인하고 갱신해야 한다(이번에 실제로 다시 다 확인하고 고쳤음).

## 5. 실행/검증 커맨드

```bash
cd /Users/deogi/Desktop/skala-rag
./.venv/bin/python scripts/build_index.py
./.venv/bin/pytest tests/ -v                      # 20개 전부 통과 확인됨
./.venv/bin/python scripts/run_retrieval_eval.py
```

## 6. 미해결 이슈 / 사용자 확인 필요

- `OPENAI_API_KEY`가 비어 있어 기술조사 Agent의 실제 LLM 호출을 검증하지 못함. 키를 채운 뒤
  `scripts/run_technical_agent.py`로 직접 확인 필요.
- `TECHNICAL_AGENT_MODEL` 기본값 `gpt-4o-mini`. 설계서의 `gpt-5.4-mini`를 쓰려면
  `.env`에 `TECHNICAL_AGENT_MODEL=gpt-5.4-mini` 지정(실존 모델명인지 확인 필요).
- `skala_rag` 패키지가 정식 editable 설치되어 있지 않음(빌드 시스템 미설정). 그래프/State
  담당자가 패키징을 정리하면 `scripts/*.py`의 sys.path 보정 코드는 필요 없어짐.
- `langchain_community`가 sunset 예정이라는 deprecation 경고가 뜸 — 이번 범위에서는 손대지
  않음. 나중에 `langchain-huggingface` 등으로 교체 고려 가능.
- `pdfplumber` 의존성 제거함(커밋 814705e). PyMuPDF로 전환한 뒤 아무 코드도 안 써서(원격
  `feat/web-evidence`, `feat/graph-output`의 `.py` 파일까지 `git grep`으로 확인 — pyproject.toml
  에만 상속되어 남아있던 선언이었음) `uv remove pdfplumber`로 정리. `pypdf`는 계속 씀(다른 용도).

## 7. PNG 항목별 완료 점검 (처음부터 재점검, 사용자 요청)

| PNG 항목 | 대응 코드 | 상태 | 검증 방식 |
|---|---|---|---|
| PDF 파싱 → Chunk → Embedding → FAISS | `tools/retrieve/{parsing,chunking,embeddings,ingest}.py`, `indexes/` | ✅ 완료 | 실제 논문 2편으로 133개 청크 색인, `tests/tools/retrieve/{test_parsing,test_chunking,test_ingest}.py` 9개 통과 |
| 논문 검색 (`retrieve_papers`) | `tools/retrieve/retriever.py` | ✅ 완료 | 한국어 질의 교차언어 검색 확인, 기술별 필터/중복제거/top-5 확인, `test_retriever.py` 4개 통과 |
| 기술조사 Agent | `agents/technical/{schemas,prompts,agent}.py` | ⚠️ 코드/로직 완료, **실제 LLM 호출 미검증** | 로직은 mock으로 3개 테스트 통과. `OPENAI_API_KEY` 없어 실제 호출은 사용자가 직접 확인 필요 |
| Retrieval 평가 | `evaluation/retrieval/{metrics,evaluate}.py`, `questions.json` | ✅ 완료 | 실측 Hit Rate@5=65%, MRR@5=0.403 (20문항), `test_metrics.py`+`test_evaluate.py` 6개 통과 |

**결론: 기술조사 Agent의 실제 OpenAI 호출 확인 한 가지를 빼고 전부 완료.** 그 한 가지는 API 키가
있어야 하는 작업이라 이 세션에서는 대신 해줄 수 없음(6장 참고).

## 8. 테스트 진행 순서

```bash
cd /Users/deogi/Desktop/skala-rag

# 1) 단위/통합 테스트 전체 (약 20초, 네트워크 불필요 — 임베딩 모델은 로컬 캐시 사용)
./.venv/bin/pytest tests/ -v

# 2) FAISS 인덱스가 최신인지 확인하고 싶으면 재생성 (약 10~15초)
./.venv/bin/python scripts/build_index.py

# 3) Retrieval 품질 지표 확인 (Hit Rate@5 / MRR@5 콘솔 출력 + evaluation/retrieval/report.md 갱신)
./.venv/bin/python scripts/run_retrieval_eval.py

# 4) (선택, OPENAI_API_KEY 필요) 기술조사 Agent 실제 실행
#    .env에 OPENAI_API_KEY=sk-... 채운 뒤:
./.venv/bin/python scripts/run_technical_agent.py --tech KIVI --tech InfiniGen
```

1~3번은 키 없이 지금 바로 돌려볼 수 있고, 이번 세션에서 이미 다 통과/측정 확인함. 4번만 사용자가
키를 넣고 직접 실행해서 결과가 말이 되는지(원리/실험조건/성능수치/한계가 근거와 함께 잘 나오는지,
`experimental_condition`이 채워지는지) 눈으로 확인하면 된다.
