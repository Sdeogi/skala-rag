"""Static report chapters (analysis background, technology selection).

The text follows the team design document (§1, A.1~A.3). It is used when the
configured technologies are KIVI and InfiniGen; other technology pairs must
supply ``run_config.background`` / ``run_config.selection_rationale``.
"""

from __future__ import annotations

from typing import Any

from .korean import josa

DESIGN_TECHNOLOGIES = ("KIVI", "InfiniGen")

CLOUD_DOMAIN_TEXT = (
    "클라우드 서빙은 한 대의 GPU 서버가 여러 사용자의 요청을 동시에 받아 처리하는 환경이다. KV cache가 커질수록 "
    "한 번에 받을 수 있는 요청 수가 줄고, 같은 트래픽을 처리하기 위해 더 많은 GPU가 필요해지므로 비용이 직접 늘어난다. "
    "따라서 메모리 절감, 생성 품질 유지, 응답 지연과 처리량이라는 요구가 동시에 걸리며, 한 가지를 얻기 위해 다른 것을 "
    "얼마나 내주는지가 평가의 핵심이 된다."
)

SELECTION_PARAGRAPHS = [
    "과제 Doc Pool의 여섯 후보(TurboQuant, DeepSeek-V2 MLA, KIVI, InfiniGen, ITME, PNM/CXL)를 도메인 적합성, "
    "근거 확보 가능성, 비교 축의 명확성 기준으로 검토해 SW 진영에서 KIVI를, HW 진영에서 InfiniGen을 선정했다. "
    "선정은 팀이 직접 수행했다(Human 기반).",
    "KIVI(SW)는 Key를 채널 단위, Value를 토큰 단위로 나누어 2비트로 양자화한다. 학습 없이 기존 모델에 바로 적용되고 "
    "공개 구현이 있으며 후속 양자화 연구의 비교 기준으로 널리 인용된다(ICML 2024).",
    "InfiniGen(HW)은 KV를 CPU 메모리로 내보내고 다음 층 계산에 중요한 KV만 미리 GPU로 가져온다. 새 하드웨어 없이 "
    "기존 CPU와 GPU 서버에서 동작하고 OSDI 2024 발표와 공개 구현이 있어 근거 확보가 쉽다. 새로운 메모리 장치가 아니라 "
    "CPU와 GPU 메모리 계층을 활용하는 KV 관리 기술이지만, 담을 공간을 넓힌다는 과제의 분류에 따라 HW 진영으로 둔다.",
    "두 기술은 같은 병목을 정반대 방향(압축과 이동)에서 풀고, 모두 기존 GPU 서버에 학습 없이 적용할 수 있어 클라우드 "
    "사업자가 지금 검토할 수 있는 선택지다. 메모리 절감을 얻는 대신 KIVI는 품질을, InfiniGen은 전송 지연을 얼마나 "
    "내주는지를 비교할 수 있다. 두 논문의 성능 수치는 모델, 하드웨어, 워크로드가 다르므로 각 수치가 성립하는 조건을 "
    "함께 제시한다.",
    "미선정 사유: TurboQuant는 2025년 발표로 채택 사례와 생태계 반응 자료가 적고, DeepSeek-V2 MLA는 학습 단계에서 "
    "구조를 바꿔야 해 서빙 중인 모델에 사후 적용할 수 없으며, ITME는 CXL 장비가 필요하고 2026년 발표로 채택 자료가 "
    "부족하고, PNM/CXL은 전용 하드웨어가 필요해 현재 클라우드 서빙 현장에서 검토 가능한 선택지가 아니다.",
]

COMPARISON_TABLE = {
    "columns": ["비교 축", "KIVI (SW)", "InfiniGen (HW)"],
    "rows": [
        ["접근", "KV 값을 2비트로 압축해 GPU 메모리 안에 더 많이 담는다", "KV 원본을 CPU 메모리로 내보내고 다음 층 계산에 중요한 KV만 미리 GPU로 가져온다"],
        ["정확도 영향", "양자화 오차가 생기므로 품질 저하 검증이 필요하다", "원본을 유지하지만 중요 KV 예측이 빗나가면 품질에 영향이 있다"],
        ["지연 영향", "양자화와 복원 연산이 추가된다", "PCIe 전송 지연이 생기며 프리패치로 이를 숨긴다"],
        ["필요 인프라", "기존 GPU만으로 동작한다", "충분한 CPU 메모리와 PCIe 대역폭이 필요하다"],
        ["적용 방법", "모델 가중치는 그대로 두고 추론 코드의 KV 저장 방식을 바꾼다", "서빙 엔진의 KV 관리 로직을 바꾼다"],
    ],
}


def background_paragraphs(config: dict[str, Any]) -> list[str]:
    if config.get("background"):
        return [line.strip() for line in str(config["background"]).split("\n\n") if line.strip()]
    domain = config.get("domain", "")
    technologies = list(config["technologies"])
    first, second = (technologies + ["", ""])[:2] if len(technologies) < 2 else technologies[:2]
    paragraphs = [
        "LLM은 토큰을 하나씩 생성하면서 앞서 계산한 Key와 Value를 KV cache에 저장해 두고 다음 토큰을 만들 때 다시 쓴다. "
        "KV cache의 크기는 문맥 길이와 동시 요청 수에 비례해 커지므로, 문맥이 수만 토큰에 이르고 요청이 몰리면 모델 "
        "가중치보다 KV cache가 먼저 가속기의 HBM을 소진한다. KV cache는 LLM 추론의 병목을 연산에서 메모리로 옮겨 놓았다.",
        "이 병목을 푸는 접근은 두 진영으로 나뉜다. SW 진영은 양자화나 압축으로 KV 데이터 자체를 작게 만들어 같은 HBM에 "
        "더 많은 KV를 담는 대신 정확도 손실을 감수한다. HW 진영은 KV를 HBM 밖의 CPU 메모리나 스토리지로 옮겨 담을 공간을 "
        "넓히는 대신 데이터 이동에 따른 전송 지연을 감수한다. 두 진영은 겉으로는 대립하지만 현장에서는 함께 쓰이는 경우도 많다.",
        f"본 보고서는 {josa(domain, '을', '를')} 평가 도메인으로 삼는다." + (f" {CLOUD_DOMAIN_TEXT}" if "클라우드" in domain else ""),
        f"본 보고서가 답하려는 질문은 다음과 같다. {domain}에서 KV cache 메모리 병목을 줄이려 할 때 "
        f"{josa(first, '과', '와')} {josa(second, '은', '는')} 기술 성숙도, 시장성, 이해관계자, 도메인 적용의 네 관점에서 각각 "
        "어떻게 평가되며, 어떤 조건에서 관점 간 평가가 엇갈리는가. 이 보고서는 두 기술의 우열을 가리지 않고, 같은 기술이 "
        "관점에 따라 어떻게 다르게 평가되는지를 조건과 함께 제시한다.",
    ]
    return paragraphs


def selection_paragraphs(config: dict[str, Any]) -> tuple[list[str], dict[str, Any] | None]:
    if config.get("selection_rationale"):
        return [line.strip() for line in str(config["selection_rationale"]).split("\n\n") if line.strip()], None
    if tuple(config["technologies"]) == DESIGN_TECHNOLOGIES:
        return list(SELECTION_PARAGRAPHS), COMPARISON_TABLE
    names = ", ".join(config["technologies"])
    return [
        f"{josa(names, '을', '를')} 비교 대상으로 설정했다. 선정 근거는 run_config.selection_rationale로 "
        "제공되지 않아 미기재이다."
    ], None
