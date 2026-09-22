"""기술조사 Agent의 공통 질문 목록과 추출 프롬프트.

설계서 B.2: 기술조사 에이전트는 "두 논문에서 원리, 실험 조건, 성능 수치, 한계를 같은 항목
구성으로 추출"한다. 카테고리마다 질문을 2개씩 두어 회수율을 높인다(설계서 B.7 "반례 질의의
의무"와 별개로, 같은 카테고리를 다른 각도에서 한 번 더 물어 근거 누락을 줄이는 목적).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CommonQuestion:
    category: str  # schemas.Category 값 중 하나
    query_ko: str
    query_en: str


COMMON_QUESTIONS: list[CommonQuestion] = [
    CommonQuestion(
        "principle",
        "이 기술은 KV 캐시 문제를 어떤 핵심 아이디어로 해결하는가?",
        "What is the core idea this technique uses to address the KV cache bottleneck?",
    ),
    CommonQuestion(
        "principle",
        "이 기술의 구체적인 알고리즘이나 시스템 동작 방식은 무엇인가?",
        "What is the concrete algorithm or system mechanism behind this technique?",
    ),
    CommonQuestion(
        "experimental_setup",
        "이 기술을 검증한 실험은 어떤 모델과 하드웨어, 데이터셋으로 진행되었는가?",
        "Which models, hardware, and datasets were used to evaluate this technique?",
    ),
    CommonQuestion(
        "experimental_setup",
        "실험에서 사용한 배치 크기, 문맥 길이, 비교 대상(baseline)은 무엇인가?",
        "What batch size, context length, and baselines were used in the experiments?",
    ),
    CommonQuestion(
        "performance",
        "이 기술을 적용했을 때 메모리 절감, 속도, 처리량이 얼마나 개선되는가?",
        "How much does this technique improve memory usage, latency, or throughput?",
    ),
    CommonQuestion(
        "performance",
        "정확도나 품질(perplexity 등) 측면에서 어떤 수치가 보고되는가?",
        "What accuracy or quality metrics (e.g. perplexity) are reported?",
    ),
    CommonQuestion(
        "limitations",
        "이 기술의 한계나 성능이 저하되는 조건은 무엇인가?",
        "What are the limitations or conditions under which this technique degrades?",
    ),
    CommonQuestion(
        "limitations",
        "이 기술을 적용하기 위해 추가로 필요한 조건이나 비용은 무엇인가?",
        "What additional requirements or costs does adopting this technique impose?",
    ),
]

EXTRACTION_SYSTEM_PROMPT = """\
당신은 기술 조사 에이전트입니다. 주어진 논문 발췌문(청크)만 근거로 사용해 질문에 답하세요.

규칙:
1. 발췌문에 없는 내용은 절대 지어내지 마세요. 근거가 없으면 claims를 빈 리스트로 두세요.
2. 각 주장(claim)은 반드시 그 근거가 된 청크의 evidence_id를 정확히 인용해야 합니다.
   목록에 없는 evidence_id를 만들어내면 안 됩니다.
3. 각 주장에 claim_type을 붙이세요:
   - reported_fact: 발췌문이 직접 진술한 사실
   - inference: 발췌문 여러 개를 종합해 에이전트가 추론한 내용
   - unverified: 확신할 수 없지만 참고할 만한 내용
4. 한 청크당 여러 주장을 뽑아도 되고, 관련 내용이 없으면 아무것도 뽑지 않아도 됩니다.
"""


def build_user_prompt(tech_name: str, question: str, chunks: list[dict]) -> str:
    lines = [f"기술명: {tech_name}", f"질문: {question}", "", "발췌문 목록:"]
    for chunk in chunks:
        lines.append(
            f"- evidence_id={chunk['evidence_id']} (p.{chunk['page']}, {chunk['section']}): "
            f"{chunk['text']}"
        )
    return "\n".join(lines)
