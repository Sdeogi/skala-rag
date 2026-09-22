from typing import Any, Literal

from skala_rag.tools.web import (
    get_search_results,
    get_source,
    summarize_source,
)


TECHNOLOGY_SEARCH_TERMS = {
    "KIVI": {
        "name": "KIVI",
        "canonical_name": "KIVI KV Cache Quantization",
        "approach": "asymmetric 2bit KV cache quantization",
        "paper": "2402.02750",
        "anchor": (
            "KIVI, the LLM inference technique introduced in arXiv:2402.02750, "
            "which uses tuning-free asymmetric 2-bit quantization for KV cache"
        ),
    },
    "InfiniGen": {
        "name": "InfiniGen",
        "canonical_name": "InfiniGen KV Cache Management",
        "approach": "dynamic KV cache management and offloading",
        "paper": "2406.19707",
        "anchor": (
            "InfiniGen, the LLM inference technique introduced in arXiv:2406.19707, "
            "for dynamic KV cache management and offloading"
        ),
    },
}


STAKEHOLDER_TOPICS = {
    "competitors": {
        "question": (
            "이 기술과 경쟁하거나 대체할 수 있는 기술, "
            "접근법 또는 프로젝트가 실제로 존재하는가?"
        ),
        "queries": [
            '"{canonical_name}" competing approaches LLM inference',
            '"{name}" "KV cache" alternatives LLM',
            '"{paper}" KV cache related work',
        ],
    },

    "adopters": {
        "question": (
            "이 기술 또는 직접적으로 영향을 받은 KV cache 최적화 기법이 "
            "실제 오픈소스 프레임워크나 시스템에 구현 또는 통합되었는가?"
        ),
        "queries": [
            '"{name}" "KV cache" implementation GitHub',
            '"{name}" HuggingFace Transformers KV cache quantization',
            '"{paper}" implementation integration',
        ],
    },

    "industry_media": {
        "question": (
            "LLM inference 산업 또는 기술 커뮤니티에서 "
            "이 기술이나 동일한 KV cache 최적화 접근법을 "
            "다루고 있다는 외부 근거가 있는가?"
        ),
        "queries": [
            '"{name}" "KV cache" LLM inference',
            '"{canonical_name}" LLM industry',
            '"{approach}" LLM inference industry',
        ],
    },
}


def _build_queries(
    technology: str,
    topic: str,
) -> list[str]:
    """기술과 평가 주제를 이용해 검색어를 생성한다."""

    tech = TECHNOLOGY_SEARCH_TERMS[technology]
    topic_config = STAKEHOLDER_TOPICS[topic]

    return [
        query.format(**tech)
        for query in topic_config["queries"]
    ]


def _deduplicate_results(
    results: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """URL 기준으로 검색 결과 중복을 제거한다."""

    seen_urls: set[str] = set()
    deduplicated: list[dict[str, Any]] = []

    for result in results:
        url = result.get("url")

        if not url:
            continue

        if url in seen_urls:
            continue

        seen_urls.add(url)
        deduplicated.append(result)

    return deduplicated


def _search_topic(
    technology: str,
    topic: str,
    mode: Literal["live", "replay"],
    max_results_per_query: int = 3,
) -> list[dict[str, Any]]:
    """하나의 이해관계자 평가 주제에 대해 웹 검색을 수행한다."""

    all_results: list[dict[str, Any]] = []

    for query in _build_queries(
        technology,
        topic,
    ):
        results = get_search_results(
            query=query,
            max_results=max_results_per_query,
            mode=mode,
        )

        all_results.extend(results)

    return _deduplicate_results(all_results)


def _collect_topic_evidence(
    technology: str,
    topic: str,
    mode: Literal["live", "replay"],
    max_evidence: int = 3,
) -> list[dict[str, Any]]:
    """검색 결과에서 실제 원문 근거를 수집한다."""

    topic_config = STAKEHOLDER_TOPICS[topic]
    tech = TECHNOLOGY_SEARCH_TERMS[technology]

    question = (
        f"분석 대상 기술은 다음과 같습니다:\n"
        f"{tech['anchor']}\n\n"
        f"평가 질문:\n"
        f"{topic_config['question']}\n\n"
        f"반드시 위 기술 또는 직접적으로 관련된 KV cache / LLM inference "
        f"접근법에 대한 근거만 인정하세요. "
        f"동명이인, 다른 산업, 이름만 같은 회사나 제품은 not_found로 판정하세요."
    )

    search_results = _search_topic(
        technology=technology,
        topic=topic,
        mode=mode,
    )

    evidence: list[dict[str, Any]] = []

    for result in search_results:
        url = result.get("url")

        if not url:
            continue

        if not _is_valid_topic_source(topic, url):
            continue

        try:
            source = get_source(
                url=url,
                mode=mode,
            )

            summary = summarize_source(
                source=source,
                question=question,
                topic=topic,
                mode=mode,
            )

        except Exception:
            continue

        if summary["evidence_status"] == "not_found":
            continue

        evidence.append(
            {
                "topic": topic,
                **summary,
            }
        )

        if len(evidence) >= max_evidence:
            break

    return evidence


def collect_stakeholder_evidence(
    technology: str,
    mode: Literal["live", "replay"] = "live",
) -> dict[str, Any]:
    """
    기술에 대한 이해관계자 관점의 외부 근거를 수집한다.

    평가 축:
    - competitors
    - adopters
    - industry_media
    """

    if technology not in TECHNOLOGY_SEARCH_TERMS:
        raise ValueError(
            f"지원하지 않는 기술입니다: {technology}"
        )

    results: dict[str, Any] = {
        "technology": technology,
        "topics": {},
    }

    for topic in STAKEHOLDER_TOPICS:
        results["topics"][topic] = (
            _collect_topic_evidence(
                technology=technology,
                topic=topic,
                mode=mode,
            )
        )

    return results


def _is_valid_topic_source(
    topic: str,
    url: str,
) -> bool:
    """평가 주제에 맞지 않는 출처를 최소한으로 제거한다."""

    if topic != "industry_media":
        return True

    excluded = (
        "github.com/jy-yuan/KIVI",
        "arxiv.org",
        "reddit.com",
    )

    return not any(domain in url for domain in excluded)