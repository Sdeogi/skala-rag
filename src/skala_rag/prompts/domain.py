"""도메인 적용 관점(PDF C.5) Rubric 프롬프트.

`notebooks/21-DomainAgent.ipynb`에서 셀별로 검증한 뒤 이관.
"""
from __future__ import annotations

from dataclasses import dataclass

from skala_rag.schemas.state import Evidence, IntegrationVerdict, StandardVerdict


# ---------------------------------------------------------------------------
# Rubric spec
# ---------------------------------------------------------------------------
@dataclass
class DomainRubricSpec:
    item_key: str
    question: str
    allowed_verdicts: list[str]        # Enum(.value) 문자열들
    query_hints_by_tech: dict[str, str]  # 기술별 검색 쿼리
    label_notes: str | None = None       # 라벨 방향성 등 추가 설명 (선택)


STANDARD: list[str] = [v.value for v in StandardVerdict]
INTEGRATION: list[str] = [v.value for v in IntegrationVerdict]


DOMAIN_RUBRIC: list[DomainRubricSpec] = [
    DomainRubricSpec(
        item_key="memory",
        question=(
            "대규모 서빙 환경에서 이 기술의 메모리 절감 효과를 논문·프레임워크 자료는 어떻게 보고하는가."
            " 어떤 모델·GPU·문맥 길이·배치 조건에서 측정된 수치인가."
        ),
        allowed_verdicts=STANDARD,
        query_hints_by_tech={
            "KIVI": "KIVI 2-bit KV cache quantization memory reduction batch context Llama",
            "InfiniGen": "InfiniGen KV cache offloading CPU memory GPU HBM reduction throughput",
        },
    ),
    DomainRubricSpec(
        item_key="quality",
        question=(
            "품질 저하 정도를 논문 또는 재현 자료는 어떻게 보고하는가."
            " 어떤 벤치마크·모델에서 측정했는가."
        ),
        allowed_verdicts=STANDARD,
        query_hints_by_tech={
            "KIVI": "KIVI accuracy perplexity benchmark quality loss LongBench",
            "InfiniGen": "InfiniGen accuracy perplexity benchmark quality loss",
        },
    ),
    DomainRubricSpec(
        item_key="latency",
        question=(
            "응답 지연의 증가 또는 감소를 논문·프레임워크 자료는 어떻게 보고하는가."
            " TTFT/decoding latency 등 어떤 지표에서 측정했는가."
        ),
        allowed_verdicts=STANDARD,
        query_hints_by_tech={
            "KIVI": "KIVI decoding latency per-token inference speed A100",
            "InfiniGen": "InfiniGen prefetch latency TTFT decoding inference speed",
        },
    ),
    DomainRubricSpec(
        item_key="throughput",
        question=(
            "같은 GPU에서 동시 처리 요청 수 또는 처리량 향상을 어떻게 보고하는가."
            " 비용 효과 관련 언급이 있는가."
        ),
        allowed_verdicts=STANDARD,
        query_hints_by_tech={
            "KIVI": "KIVI throughput batch size larger batch memory savings",
            "InfiniGen": "InfiniGen throughput serving batch requests per second",
        },
    ),
    DomainRubricSpec(
        item_key="integration",
        question=(
            "클라우드 운영자와 서빙 프레임워크 개발자는 기존 서빙 엔진에"
            " 이 기술을 넣는 부담을 어떻게 평가하는가. 학습 필요 여부, 프레임워크 통합 상태, 하드웨어 요구사항."
        ),
        allowed_verdicts=INTEGRATION,
        query_hints_by_tech={
            "KIVI": "KIVI vLLM Hugging Face integration tuning-free training-free plug-in",
            "InfiniGen": "InfiniGen serving framework integration CPU memory PCIe hardware requirement",
        },
        label_notes=(
            "라벨 방향성 주의(중요): "
            "'낮음 보고' = 자료가 통합 부담이 낮다/쉽다고 보고 "
            "(예: tuning-free, 기존 서빙 엔진에 바로 얹힘, 새 하드웨어 불필요, 코드 몇 줄로 적용). "
            "'높음 보고' = 자료가 통합 부담이 높다/어렵다고 보고 "
            "(예: 재학습 필요, 서빙 엔진 대규모 수정, CPU 메모리·PCIe 대역폭 등 추가 하드웨어 조건 요구, 전용 커널 필요). "
            "근거가 통합의 '쉬움/plug-in/tuning-free/기존 프레임워크 지원'을 뒷받침하면 반드시 '낮음 보고'를 고른다. "
            "근거가 '별도 하드웨어·대규모 코드 변경·재학습'을 요구하면 '높음 보고'를 고른다."
        ),
    ),
]


# ---------------------------------------------------------------------------
# Prompt strings
# ---------------------------------------------------------------------------
SYSTEM_PROMPT = (
    "당신은 클라우드 LLM 서빙 도메인 평가 에이전트다."
    " 자료가 직접 말한 사실만 근거로 삼아 각 항목의 판정을 옮긴다."
    " 우열을 가리지 않고, 총점·순위·우승·도입 추천을 만들지 않는다."
    " 판정 라벨은 반드시 '허용 판정 라벨' 안에서만 고르며,"
    " '라벨 의미' 블록이 있으면 그 방향성을 그대로 따른다."
    " 근거를 찾지 못한 항목은 반드시 '미확인'을 고른다."
)


USER_TEMPLATE = """평가 항목: {item_key}
기술: {tech}
평가 질문: {question}
허용 판정 라벨(정확히 이 문자열 중 하나만 사용): {allowed}
{label_notes_block}

아래는 이 (기술, 항목)에 대해 검색된 근거 후보 목록이다. 각 후보에는 evidence_id, 페이지, 원문 인용이 함께 있다.
판정을 뒷받침하는 후보의 evidence_id만 결과에 남기고, 실제 인용된 조건(모델·GPU·문맥·배치 등)은 conditions에 그대로 옮긴다.
충분한 근거가 없다면 verdict는 '미확인'으로 고르고 evidence_ids는 빈 배열로 둔다.

[검색된 근거 후보]
{evidence_block}

결과는 JSON 스키마에 맞춰 반환한다.
"""


def format_label_notes(notes: str | None) -> str:
    """label_notes가 있으면 프롬프트의 자체 블록으로 삽입, 없으면 빈 문자열."""
    if not notes:
        return ""
    return f"[라벨 의미] {notes}"


def format_evidence_block(candidates: list[Evidence]) -> str:
    if not candidates:
        return "(근거 후보 없음)"
    lines = []
    for e in candidates:
        snippet = e.quote.strip().replace("\n", " ")
        if len(snippet) > 700:
            snippet = snippet[:700] + " ..."
        lines.append(f"- evidence_id: {e.evidence_id} | {e.location}\n  quote: {snippet}")
    return "\n".join(lines)


__all__ = [
    "DomainRubricSpec", "STANDARD", "INTEGRATION", "DOMAIN_RUBRIC",
    "SYSTEM_PROMPT", "USER_TEMPLATE",
    "format_label_notes", "format_evidence_block",
]
