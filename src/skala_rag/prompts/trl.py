"""기술 성숙도(TRL) 관점(PDF C.2) Rubric 프롬프트.

`notebooks/22-TRLAgent.ipynb`에서 셀별로 검증한 뒤 이관.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from schemas.state import Evidence, TRLLevel


# ---------------------------------------------------------------------------
# Rubric spec
# ---------------------------------------------------------------------------
@dataclass
class TRLStageSpec:
    stage_key: str                             # trl_1_2, trl_3, ..., trl_9
    trl_label: str                             # 표시용, 예 "TRL 1-2"
    trl_enum: TRLLevel
    description: str
    evidence_mode: Literal["rag", "web"]       # PDF C.2 표
    query_hints_by_tech: dict[str, str]        # 기술별 검색 쿼리


TRL_STAGES: list[TRLStageSpec] = [
    TRLStageSpec(
        stage_key="trl_1_2", trl_label="TRL 1-2", trl_enum=TRLLevel.L1_2,
        description="아이디어와 개념이 논문 서론과 관련 연구에 제시됨",
        evidence_mode="rag",
        query_hints_by_tech={
            "KIVI": "KIVI KV cache quantization idea concept introduction related work",
            "InfiniGen": "InfiniGen KV cache offloading concept introduction related work",
        },
    ),
    TRLStageSpec(
        stage_key="trl_3", trl_label="TRL 3", trl_enum=TRLLevel.L3,
        description="소규모 실험으로 개념이 검증됨 (논문 실험 절의 모델, GPU, 데이터셋)",
        evidence_mode="rag",
        query_hints_by_tech={
            "KIVI": "KIVI experiment Llama Falcon Mistral A100 benchmark",
            "InfiniGen": "InfiniGen experiment OPT Llama GPU CPU benchmark",
        },
    ),
    TRLStageSpec(
        stage_key="trl_4", trl_label="TRL 4", trl_enum=TRLLevel.L4,
        description="공개 코드로 실험을 재현할 수 있으나 특정 모델·GPU에 한정",
        evidence_mode="web",
        query_hints_by_tech={
            "KIVI": "KIVI github jy-yuan reproduction code repository",
            "InfiniGen": "InfiniGen github snu-comparch reproduction code repository",
        },
    ),
    TRLStageSpec(
        stage_key="trl_5", trl_label="TRL 5", trl_enum=TRLLevel.L5,
        description="vLLM/HF Transformers/TensorRT-LLM 등 주류 서빙 프레임워크에 통합되거나 통합 PR이 있음",
        evidence_mode="web",
        query_hints_by_tech={
            "KIVI": "KIVI vLLM Hugging Face Transformers TensorRT-LLM integration PR",
            "InfiniGen": "InfiniGen vLLM Hugging Face Transformers TensorRT-LLM integration PR",
        },
    ),
    TRLStageSpec(
        stage_key="trl_6", trl_label="TRL 6", trl_enum=TRLLevel.L6,
        description="실제 서비스 규모의 워크로드에서 동작이 시연됨 (기업 기술 블로그·벤치마크 발표)",
        evidence_mode="web",
        query_hints_by_tech={
            "KIVI": "KIVI production serving benchmark blog announcement enterprise",
            "InfiniGen": "InfiniGen production serving benchmark blog announcement enterprise",
        },
    ),
    TRLStageSpec(
        stage_key="trl_7_8", trl_label="TRL 7-8", trl_enum=TRLLevel.L7_8,
        description="상용 서비스에 시범 적용되거나 정식 기능으로 출시됨 (제품 발표·릴리스 공지)",
        evidence_mode="web",
        query_hints_by_tech={
            "KIVI": "KIVI commercial cloud LLM serving pilot release product announcement",
            "InfiniGen": "InfiniGen commercial cloud LLM serving pilot release product announcement",
        },
    ),
    TRLStageSpec(
        stage_key="trl_9", trl_label="TRL 9", trl_enum=TRLLevel.L9,
        description="상용 서비스 운영 실적이 공개됨 (고객 사례·실적 자료)",
        evidence_mode="web",
        query_hints_by_tech={
            "KIVI": "KIVI customer case study production cloud LLM serving deployment",
            "InfiniGen": "InfiniGen customer case study production cloud LLM serving deployment",
        },
    ),
]


# ---------------------------------------------------------------------------
# Prompt strings
# ---------------------------------------------------------------------------
TRL_SYSTEM_PROMPT = (
    "당신은 클라우드 LLM 서빙 SW 기술의 성숙도(TRL) 평가 에이전트다."
    " NASA 9단계 척도를 클라우드 서빙 SW 기술에 맞춘 표(PDF C.2) 기준으로 판정한다."
    " 자료가 직접 말한 사실만 근거로 삼고, 판정은 항상 공개 정보에 근거한 '추정'임을 명시한다."
    " 각 단계에 대해 '충족/미충족/미확인' 중 하나를 고른다."
    " 근거가 두 단계에 걸치면(예: 통합 PR 존재하나 정식 통합은 아직) 상위 판정은 '미확인'으로 두어라."
    " 임의로 우열을 가리거나 도입 추천을 하지 않는다."
)


TRL_STAGE_USER_TEMPLATE = """기술: {tech}
단계: {stage_label} ({stage_key})
단계 정의: {description}
근거 획득 방식: {mode}
검색 쿼리: {query}

아래는 이 단계 판정을 위해 수집된 근거 후보이다.
판정 라벨은 정확히 다음 중 하나: 충족 / 미충족 / 미확인
'충족'을 고르려면 근거가 반드시 하나 이상 있어야 하고, evidence_ids에 그 id를 담아라.
근거가 부족하면 '미확인'을, 근거는 있으나 이 단계 정의에 부합하지 않으면 '미충족'을 골라라.

[근거 후보]
{evidence_block}

결과 JSON:
- verdict: '충족' | '미충족' | '미확인'
- reason: 판정 이유 한두 문장
- evidence_ids: 판정 뒷받침 id (충족일 때 최소 1개)
- missing_evidence_note: 상위 단계로 올라가려면 확인이 필요한 증거를 짧게 적음 (없으면 빈 문자열)
"""


def format_evidence_block(candidates: list[Evidence], max_quote: int = 700) -> str:
    if not candidates:
        return "(근거 후보 없음)"
    lines = []
    for e in candidates:
        snippet = e.quote.strip().replace("\n", " ")
        if len(snippet) > max_quote:
            snippet = snippet[:max_quote] + " ..."
        lines.append(f"- evidence_id: {e.evidence_id} | {e.location}\n  quote: {snippet}")
    return "\n".join(lines)


__all__ = [
    "TRLStageSpec", "TRL_STAGES",
    "TRL_SYSTEM_PROMPT", "TRL_STAGE_USER_TEMPLATE",
    "format_evidence_block",
]
