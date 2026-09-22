# Subject

KV Cache의 최적화 기술을 소프트웨어와 하드웨어 진영에서 각각 선정하고 기술/시장/이해관계자/도메인 4개의 관점에서 비교 평가하는 Agentic RAG 프로젝트입니다. 논문과 웹 자료를 근거로 데이터센터/클라우드 LLM 서빙 환경의 적용 조건과 한계를 정리합니다. 이때, 각 기술의 우열을 가리는 것이 아니라 치이점에 대해 설명합니다.

## Overview

- Objective : 하나의 기술을 복수 관점에서 비교 평가하고, 관점 간 상충 지점을 성립 조건과 함께 제시 (우열·추천 없음)
- Method : Multi-Agent(병렬 fan-out/join) + Agentic RAG + 근거 검사·보완 루프(최대 2회)
- Tools : LangGraph StateGraph/Send, Pydantic, FAISS(A), Tavily Search(B), Jinja2, reportlab

## Selected Technologies

- SW : KIVI — Key는 채널 단위, Value는 토큰 단위로 2비트 양자화. 학습 없이 기존 모델에 적용 가능, 공개 구현 존재, 후속 양자화 연구의 비교 기준 (ICML 2024)
- HW : InfiniGen — KV를 CPU 메모리로 내보내고 다음 층 계산에 중요한 KV만 프리패치. 새 하드웨어 없이 기존 CPU·GPU 서버에서 동작, OSDI 2024 발표와 공개 구현 존재

## Features

- 네 관점 에이전트의 병렬 실행과 명시적 합류(join), 관점별 독립 State 키와 ID 병합 reducer(충돌은 기록, 실행 중단 없음)
- 근거 검사 노드: 규칙 검사(항목·라벨·근거 실재·출처·주장 유형) + 검토 LLM(항목별 의미 검토, 캐시·호출 예산)
- 부족한 항목만 다시 조사하는 보완 루프: 실패한 관점만 `Send`로 병렬 재호출, 최대 2회
- 평가 종합: 검증된 판정만으로 일치·상충 쌍(관점 A/B 판정, 이유, 근거 ID, 조건, 불확실성) 구성. 총점·순위·추천 없음
- 보고서: SUMMARY(½쪽 이내) → 분석 배경 → 기술 선정 → 기술 개요 → 관점별 평가(표) → 시사점 → 한계점 → 근거 목록 → REFERENCE(실제 활용 자료만, 과제 표기 형식). Markdown/HTML/PDF(한글 글꼴 임베드)
- live 모드 LLM 출력 가드: 근거 ID·숫자·우열 표현 검증, 실패 시 규칙 기반 문장으로 대체하고 사유 기록
- 실행 기록 `run_manifest.json`: 도구 호출·토큰·실행 시간·보완 횟수·ID 충돌·오류·생성 방식
- 통합 계층: A의 논문 근거·기술 조사, B의 웹 근거·시장성·이해관계자 판정, C의 도메인·TRL 판정기를 한 곳(`integration/services.py`)에서 D 계약으로 변환. 보완 루프에서는 부족한 기술·항목만 재판정
- 확증 편향 방지 전략 : 대칭 조사, 반례 질의, 주장 유형(reported_fact/inference/unverified) 표시, 미확인 라벨, 상충 쌍 형식의 종합 (설계 B.7)

## Tech Stack

- Framework : LangGraph 1.x
- LLM/Generator : gpt-5.4-mini (`RAG_MODEL_ID`로 변경)
- LLM/Judge : gpt-5.4-mini (생성과 다른 프롬프트, 별도 호출)
- Retrieval : FAISS - Hit Rate@5 65%, MRR@5 0.403 (라벨링 질의 20개, `evaluation/retrieval/report.md`)
- Embedding : intfloat/multilingual-e5-small (sentence-transformers)

## Agents

- 기술 조사 에이전트 (A, RAG): 두 논문에서 원리·실험 조건·성능 수치·한계 추출 → `technical_findings`, `evidence`
- 시장성 평가 에이전트 (B, 웹 검색): 시장 규모·채택 현황·생태계 → `market_analysis`
- 이해관계자 평가 에이전트 (B, 웹 검색): 경쟁 진영·도입 기업·투자 업계 발언 → `stakeholder_analysis`
- 도메인 평가 에이전트 (C, RAG): 클라우드 서빙 다섯 관심사에 대한 자료의 평가 → `domain_analysis`
- 기술 성숙도 평가 에이전트 (C, 웹 검색): TRL 단계별 증거 → `trl_analysis`
- 근거 검사 노드 + 검토 LLM (D): 규칙 검사와 의미 검토, 부족한 질문 생성 → `evidence_check`, `missing_questions`
- 평가 종합 에이전트 (D): 일치·상충 쌍과 조건·불확실성 → `synthesis`
- 보고서 생성 에이전트 (D): 한국어 보고서와 인용 → `report`, 산출물 5종

## Paper RAG — 논문 검색 (KIVI / InfiniGen)

PDF 파싱 → Chunk → Embedding(`intfloat/multilingual-e5-small`) → FAISS 색인 → `retrieve_papers`
검색 도구로 구성된다. 자세한 내용은 `src/skala_rag/tools/retrieve/`, `src/skala_rag/agents/technical/`,
`src/skala_rag/evaluation/retrieval/` 참고.

**검색 지표** (라벨링된 질의 20개, KIVI/InfiniGen 각 10개 기준, 설계서 E.3):

| 지표 | 값 |
|---|---|
| Hit Rate@5 | 65% |
| MRR@5 | 0.403 |

측정 방법과 문항별 결과는 `evaluation/retrieval/report.md` 참고. 재측정하려면
`python scripts/run_retrieval_eval.py` 실행(사전에 `python scripts/build_index.py`로 색인 필요).

## Architecture

```mermaid
graph TD;
	__start__([__start__]):::first
	prepare(prepare)
	technical(technical)
	technical_failed(technical_failed)
	market(market)
	stakeholder(stakeholder)
	domain(domain)
	trl(trl)
	evidence_check(evidence_check)
	retry(retry)
	repair(repair)
	synthesis(synthesis)
	report(report)
	save(save)
	__end__([__end__]):::last
	__start__ --> prepare;
	prepare -.-> technical;
	prepare -.-> save;
	technical -.-> market;
	technical -.-> stakeholder;
	technical -.-> domain;
	technical -.-> trl;
	technical -.-> technical_failed;
	technical -.-> save;
	technical_failed --> save;
	market --> evidence_check;
	stakeholder --> evidence_check;
	domain --> evidence_check;
	trl --> evidence_check;
	evidence_check -.-> retry;
	evidence_check -.-> synthesis;
	retry -.-> repair;
	retry -.-> evidence_check;
	repair --> evidence_check;
	synthesis --> report;
	report --> save;
	save --> __end__;
	classDef default fill:#f2f0ff,line-height:1.2
	classDef first fill-opacity:0
	classDef last fill:#bfb6fc
```

`python app.py --draw-graph docs/graph.mmd`로 다시 생성한다. 점선은 조건부 간선이며 `retry → repair`는 부족한 관점 수만큼 병렬 `Send`다.

## Directory Structure

```
├── app.py                        # 실행 스크립트 (live/replay, --fixture, --draw-graph)  [D]
├── scripts/                      # build_index.py, run_retrieval_eval.py, run_technical_agent.py  [A]
├── data/papers/                  # 논문 PDF와 manifest  [A]
├── data/web/                     # 웹 검색·원문 캐시 (replay용, git 제외)  [B]
├── indexes/                      # FAISS 색인  [A]
├── evaluation/retrieval/         # 검색 지표 측정 결과  [A]
├── src/skala_rag/
│   ├── config.py                 # 환경 변수 설정과 검증  [D]
│   ├── schemas/state.py          # 팀 공용 Pydantic 스키마  [C]
│   ├── evidence_check.py         # 근거 검사 노드(기계 검사 + LLM 검토)  [C]
│   ├── supplement.py             # 보완 노드(도메인·TRL 재판정)  [C]
│   ├── prompts/                  # 도메인·TRL Rubric 프롬프트  [C]
│   ├── tools/
│   │   ├── retrieve/             # PDF 파싱, 청크, 임베딩, FAISS 검색  [A]
│   │   └── web.py                # Tavily 검색, 원문 조회, 요약, 캐시  [B]
│   ├── agents/
│   │   ├── technical/            # 기술 조사 에이전트  [A]
│   │   ├── market.py, stakeholder.py   # 시장성·이해관계자 근거 수집  [B]
│   │   ├── domain.py, trl.py     # 도메인·TRL 평가 에이전트  [C]
│   │   ├── review.py             # 검토 LLM(근거 의미 검토, 캐시·예산)  [D]
│   │   ├── synthesis.py          # 규칙 기반 일치·상충 쌍  [D]
│   │   ├── llm_output.py         # live 종합·SUMMARY LLM 에이전트와 출력 가드  [D]
│   │   └── report.py, report_static.py   # 보고서 장 구성, Markdown/HTML/PDF, manifest  [D]
│   ├── integration/services.py   # A/B/C 모듈을 PipelineServices에 연결하는 어댑터  [D]
│   ├── graph/
│   │   ├── schemas.py            # 그래프 경계 계약(RunConfig, Source, Evidence, PerspectiveResult 등)  [D]
│   │   ├── state.py              # GraphState, ID 병합 reducer, metrics 이벤트  [D]
│   │   ├── evidence_check.py     # 규칙 검사 + 검토 LLM 호출  [D]
│   │   ├── workflow.py           # PipelineServices, 그래프 구성, 보완 Send  [D]
│   │   └── demo.py               # 합성 fixture (흐름 검증 전용)  [D]
│   ├── evaluation/retrieval/     # Hit Rate@K, MRR 측정 코드  [A]
│   └── templates/report.html.j2  # HTML 템플릿  [D]
├── tests/                        # D 47개 + A 테스트(tools/retrieve, agents/technical, evaluation)
├── docs/                         # D 설계·이력·검토 문서, graph.mmd, PAPER_RAG_HANDOFF.md
├── HANDOFF.md                    # C 인수인계 문서
└── outputs/                      # 보고서·출처 목록·실행 기록 (git 제외)
```

통합: `src/skala_rag/integration/services.py`의 `create_services()`가 A/B/C 모듈을 D 그래프의 `PipelineServices`에 연결한다. `app.py`는 이 factory를 기본으로 쓰며, `--fixture`는 합성 자료로 흐름만 검증한다.

## Usage

```bash
uv sync --only-group graph --only-group dev   # 이 브랜치 최소 환경 (팀 전체 환경: uv sync --group dev)
source .venv/bin/activate
cp .env.template .env                          # OPENAI_API_KEY, TAVILY_API_KEY 입력 (app.py가 자동 로드)
python app.py --mode replay --fixture --output-dir outputs/demo   # 합성 자료로 그래프·보고서 흐름 검증
python -m pytest -q
```

실제 실행(A/B/C 통합 서비스, 기본 factory):

```bash
python app.py --mode live --output-dir outputs/live --report-name RAG-Output_판교_10반_이름1+이름2+이름3+이름4
python app.py --mode replay --output-dir outputs/replay      # data/web 캐시 재생, 웹 호출 없음
```

`live`는 `OPENAI_API_KEY`와 `TAVILY_API_KEY`가 필요하다. `replay`는 웹 검색·원문을 `data/web/` 캐시에서 읽지만 판정 LLM(기술 조사, 도메인, TRL, 검토)은 호출하므로 `OPENAI_API_KEY`가 필요하다. 캐시가 없는 웹 항목은 미확인으로 남는다. FAISS 색인(`indexes/`)이 없으면 `prepare`가 자동으로 만든다.

주요 옵션: `--technologies SW HW`, `--domain`, `--as-of YYYY-MM-DD`, `--web-search-max 20 --fetch-max 30 --tool-timeout 20 --tool-retries 2`, `--max-paper-pages 200`, `--semantic-review auto|on|off`, `--max-review-calls 72`, `--llm-output auto|on|off`, `--deterministic-output`, `--report-name`, `--draw-graph [PATH]`.

`--fixture` 출력은 합성 자료이며 실제 KIVI/InfiniGen 평가 결과가 아니다. `live`는 검토 LLM과 종합·SUMMARY LLM을 켜고, `replay`는 규칙 기반으로 재현 가능한 출력을 만든다(`--llm-output on`으로 replay에서도 LLM 작성 가능). 검증 환경: Python 3.14.6, macOS.

## Contributors

- (합병 시 개인별 수행 역할 기재. PM/PL 역할은 제외)
- A `feat/paper-rag` : PDF 처리, 청크 분할, 임베딩·FAISS 색인, 논문 검색 도구
- B `feat/web-evidence` : 시장성·이해관계자 에이전트, Tavily 검색·원문 조회 도구, replay 캐시
- C `feat/evaluation` : 도메인·기술 성숙도 에이전트, 관점 Rubric 프롬프트
- D `feat/graph-output` : LangGraph State/Node/Edge, 병렬 fan-out/join, 근거 검사·검토 LLM, 보완 루프, 평가 종합, 보고서·PDF, CLI
