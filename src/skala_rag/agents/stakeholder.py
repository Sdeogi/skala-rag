"""이해관계자 웹 근거 수집 + Rubric 판정 Agent."""

from hashlib import sha256
from pathlib import Path
from typing import Any, Literal

from skala_rag.tools.web import (
    DEFAULT_CACHE_DIR,
    get_search_results,
    get_source,
    summarize_source,
)

StakeholderTopic = Literal["competitors", "adopters", "industry_media"]

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
        "field": "competitor_view",
        "question": (
            "상대 진영 또는 경쟁 기술의 논문/기술 주체가 이 기술의 한계를 어떻게 지적하고 "
            "어떤 대응 기술을 제시하는가? 실제 비교/평가 발언만 근거로 사용하라."
        ),
        "queries": [
            '"{canonical_name}" competing approaches LLM inference limitation',
            '"{name}" "KV cache" alternatives comparison limitation',
            '"{paper}" KV cache related work comparison',
        ],
    },
    "adopters": {
        "field": "adopter_view",
        "question": (
            "이 기술을 직접 구현·도입해 본 기업이나 개발자가 밝힌 효과와 채택 장벽은 무엇인가? "
            "실제 개발자/도입 주체의 발언만 근거로 사용하라."
        ),
        "queries": [
            '"{name}" "KV cache" implementation GitHub issue',
            '"{name}" HuggingFace Transformers KV cache quantization developer',
            '"{paper}" implementation integration issue limitation',
        ],
    },
    "industry_media": {
        "field": "investor_view",
        "question": (
            "애널리스트, 투자자, 언론/기술 미디어가 이 기술 또는 동일한 KV cache 최적화 접근을 "
            "어떻게 평가하는가? 실제 평가 문장만 근거로 사용하라."
        ),
        "queries": [
            '"{name}" "KV cache" LLM inference analysis',
            '"{canonical_name}" LLM industry media',
            '"{approach}" LLM inference industry analysis',
        ],
    },
}

STAKEHOLDER_LABELS = ("지지", "우려", "중립", "미확인")
STANCE_TO_LABEL = {
    "support": "지지",
    "concern": "우려",
    "neutral": "중립",
}


def _build_queries(technology: str, topic: StakeholderTopic) -> list[str]:
    tech = TECHNOLOGY_SEARCH_TERMS[technology]
    topic_config = STAKEHOLDER_TOPICS[topic]
    return [query.format(**tech) for query in topic_config["queries"]]


def _deduplicate_results(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen_urls: set[str] = set()
    deduplicated: list[dict[str, Any]] = []
    for result in results:
        url = result.get("url")
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)
        deduplicated.append(result)
    return deduplicated


def _search_topic(
    technology: str,
    topic: StakeholderTopic,
    mode: Literal["live", "replay"],
    max_results_per_query: int = 3,
    cache_dir: Path = DEFAULT_CACHE_DIR,
) -> tuple[list[dict[str, Any]], int]:
    all_results: list[dict[str, Any]] = []
    search_calls = 0
    for query in _build_queries(technology, topic):
        results = get_search_results(
            query=query,
            max_results=max_results_per_query,
            mode=mode,
            cache_dir=cache_dir,
        )
        search_calls += 1
        all_results.extend(results)
    return _deduplicate_results(all_results), search_calls


def _is_valid_topic_source(topic: StakeholderTopic, url: str) -> bool:
    """industry/media 축에서 원 논문·GitHub·Reddit 자체는 제외한다."""
    if topic != "industry_media":
        return True
    excluded = (
        "github.com/",
        "arxiv.org",
        "export.arxiv.org",
        "alphaxiv.org",
        "reddit.com",
    )
    lowered = url.lower()
    return not any(domain in lowered for domain in excluded)


def _source_record(source_id: str, summary: dict[str, Any]) -> dict[str, Any]:
    return {
        "source_id": source_id,
        "title": summary.get("source_title") or "제목 미상",
        "url": summary.get("source_url") or None,
        "retrieved_at": summary.get("collected_at"),
        "content_hash": summary.get("content_hash"),
        "source_type": "web",
    }


def _collect_topic_evidence(
    technology: str,
    topic: StakeholderTopic,
    mode: Literal["live", "replay"],
    max_evidence: int = 3,
    max_attempts: int = 8,
    max_results_per_query: int = 3,
    cache_dir: Path = DEFAULT_CACHE_DIR,
) -> dict[str, Any]:
    """하나의 이해관계자 축에서 실제 발언 근거를 수집한다."""
    topic_config = STAKEHOLDER_TOPICS[topic]
    tech = TECHNOLOGY_SEARCH_TERMS[technology]
    question = (
        f"분석 대상 기술:\n{tech['anchor']}\n\n"
        f"평가 질문:\n{topic_config['question']}\n\n"
        "동명이인, 다른 산업, 이름만 같은 회사나 제품은 not_found로 판정하세요. "
        "단순 기술 존재나 소스코드 공개가 아니라 실제 주체의 평가/발언만 direct로 인정하세요."
    )

    search_results, search_calls = _search_topic(
        technology=technology,
        topic=topic,
        mode=mode,
        max_results_per_query=max_results_per_query,
        cache_dir=cache_dir,
    )

    direct: list[dict[str, Any]] = []
    indirect: list[dict[str, Any]] = []
    sources: dict[str, dict[str, Any]] = {}
    errors: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    attempts = 0

    for result in search_results:
        if len(direct) >= max_evidence or attempts >= max_attempts:
            break

        url = result.get("url")
        if not url:
            continue
        if not _is_valid_topic_source(topic, url):
            skipped.append({"url": url, "reason": "source_type_excluded"})
            continue

        attempts += 1
        try:
            source = get_source(url=url, mode=mode, cache_dir=cache_dir)
            summary = summarize_source(
                source=source,
                question=question,
                topic=topic,
                mode=mode,
                cache_dir=cache_dir,
            )
        except Exception as exc:
            errors.append(
                {
                    "topic": topic,
                    "url": url,
                    "error_type": type(exc).__name__,
                    "error": f"stakeholder evidence 단계 실패 ({type(exc).__name__})",
                }
            )
            continue

        if summary["evidence_status"] == "not_found":
            skipped.append({"url": url, "reason": "not_found"})
            continue
        if summary.get("quote_verified") is not True:
            skipped.append({"url": url, "reason": "quote_not_verified"})
            continue

        source_key = summary.get("source_url") or url
        digest = summary.get("content_hash") or sha256(source_key.encode()).hexdigest()
        source_id = "web-source-" + sha256(
            f"{source_key}|{digest}".encode()
        ).hexdigest()[:24]
        evidence_key = (
            f"{source_id}|{technology}|{topic}|{summary['quote']}|{summary['claim']}"
        )
        entry = {
            "topic": topic,
            **summary,
            "technology": technology,
            "source_id": source_id,
            "evidence_id": "web-evidence-"
            + sha256(evidence_key.encode()).hexdigest()[:24],
            "claim_type": "reported_fact",
            "conditions": summary.get("limitation") or "",
            "search_score": result.get("score"),
        }
        sources[source_id] = _source_record(source_id, summary)

        if summary["evidence_status"] == "direct":
            direct.append(entry)
        else:
            indirect.append(entry)

    return {
        "evidence": direct,
        "indirect_evidence": indirect,
        "sources": sources,
        "errors": errors,
        "skipped": skipped,
        "search_calls": search_calls,
        "attempts": attempts,
    }


def collect_stakeholder_evidence(
    technology: str,
    mode: Literal["live", "replay"] = "live",
    *,
    max_evidence_per_topic: int = 3,
    max_attempts_per_topic: int = 8,
    max_results_per_query: int = 3,
    cache_dir: Path = DEFAULT_CACHE_DIR,
) -> dict[str, Any]:
    """기술 하나의 이해관계자 실제 발언 근거를 세 축에서 수집한다."""
    if technology not in TECHNOLOGY_SEARCH_TERMS:
        raise ValueError(f"지원하지 않는 기술입니다: {technology}")
    if mode not in ("live", "replay"):
        raise ValueError("mode는 live 또는 replay여야 합니다")

    output: dict[str, Any] = {
        "technology": technology,
        "topics": {},
        "indirect_evidence": [],
        "sources": {},
        "errors": [],
        "skipped": [],
        "metrics": {"web_search_calls": 0, "fetch_attempts": 0},
    }

    for topic in STAKEHOLDER_TOPICS:
        collected = _collect_topic_evidence(
            technology=technology,
            topic=topic,
            mode=mode,
            max_evidence=max_evidence_per_topic,
            max_attempts=max_attempts_per_topic,
            max_results_per_query=max_results_per_query,
            cache_dir=cache_dir,
        )
        output["topics"][topic] = collected["evidence"]
        output["indirect_evidence"].extend(collected["indirect_evidence"])
        output["sources"].update(collected["sources"])
        output["errors"].extend(collected["errors"])
        output["skipped"].extend(
            {"topic": topic, **item} for item in collected["skipped"]
        )
        output["metrics"]["web_search_calls"] += collected["search_calls"]
        output["metrics"]["fetch_attempts"] += collected["attempts"]

    return output


def _join_unique(values: list[str]) -> str:
    result: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in result:
            result.append(text)
    return " / ".join(result)


def _stakeholder_judgment(entries: list[dict[str, Any]]) -> dict[str, Any]:
    """실제 발언의 stance를 지지/우려/중립/미확인 Rubric으로 집계한다."""
    usable = [
        e
        for e in entries
        if e.get("evidence_status") == "direct"
        and e.get("stakeholder_stance") in STANCE_TO_LABEL
        and str(e.get("speaker") or "").strip()
    ]
    if not usable:
        return {
            "label": "미확인",
            "reason": "실제 발언 주체와 방향을 함께 확인할 수 있는 직접 근거를 확보하지 못함",
            "conditions": "",
            "evidence_ids": [],
            "speaker": "",
            "stated_at": "",
            "context": "",
        }

    stances = {e["stakeholder_stance"] for e in usable}
    if "support" in stances and "concern" in stances:
        label = "중립"
        extra = "서로 다른 직접 발언에서 지지와 우려가 함께 확인됨."
    elif "concern" in stances:
        label = "우려"
        extra = ""
    elif "support" in stances:
        label = "지지"
        extra = ""
    else:
        label = "중립"
        extra = ""

    reason = _join_unique([e.get("claim", "") for e in usable])
    if extra:
        reason = f"{extra} {reason}".strip()

    return {
        "label": label,
        "reason": reason,
        "conditions": _join_unique([e.get("limitation", "") for e in usable]),
        "evidence_ids": [e["evidence_id"] for e in usable],
        "speaker": _join_unique([e.get("speaker", "") for e in usable]),
        "stated_at": _join_unique([e.get("stated_at", "") for e in usable]),
        "context": _join_unique([e.get("context", "") for e in usable]),
    }


def build_stakeholder_judgments(
    collection: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    """세 이해관계자 축의 실제 발언을 설계 Rubric 라벨로 변환한다."""
    judgments: dict[str, dict[str, Any]] = {}
    for topic, config in STAKEHOLDER_TOPICS.items():
        field = config["field"]
        judgments[field] = _stakeholder_judgment(
            list((collection.get("topics") or {}).get(topic) or [])
        )
    return judgments


def evaluate_stakeholder(
    technology: str,
    mode: Literal["live", "replay"] = "live",
    **kwargs: Any,
) -> dict[str, Any]:
    """기술 하나의 이해관계자 근거 수집과 Rubric 판정을 수행한다."""
    collection = collect_stakeholder_evidence(
        technology=technology,
        mode=mode,
        **kwargs,
    )
    judgments = build_stakeholder_judgments(collection)
    unresolved = []
    for topic, config in STAKEHOLDER_TOPICS.items():
        field = config["field"]
        judgment = judgments[field]
        if judgment["label"] == "미확인":
            unresolved.append(
                f"[{technology}|{field}] {config['question']}"
            )
        elif not judgment.get("stated_at"):
            # 시점을 찾지 못한 발언은 판정 자체는 유지하되 보완 질문에 남긴다.
            unresolved.append(
                f"[{technology}|{field}] 확인된 발언의 시점을 추가로 확인할 필요가 있음"
            )

    return {
        "technology": technology,
        "judgments": judgments,
        "unresolved_questions": unresolved,
        "status": "insufficient_evidence" if unresolved else "complete",
        "collection": collection,
    }


def build_stakeholder_analysis(
    technologies: tuple[str, ...] = ("KIVI", "InfiniGen"),
    mode: Literal["live", "replay"] = "live",
    **kwargs: Any,
) -> dict[str, Any]:
    """Graph에 넘길 수 있는 PerspectiveResult 형태의 stakeholder_analysis를 만든다."""
    tech_results = [
        evaluate_stakeholder(tech, mode=mode, **kwargs)
        for tech in technologies
    ]
    unresolved = [
        question
        for result in tech_results
        for question in result["unresolved_questions"]
    ]
    status = (
        "insufficient_evidence"
        if any(result["status"] != "complete" for result in tech_results)
        else "complete"
    )
    return {
        "perspective": "stakeholder",
        "technologies": {
            result["technology"]: result["judgments"]
            for result in tech_results
        },
        "unresolved_questions": unresolved,
        "status": status,
    }


def run_stakeholder_agent(
    technologies: tuple[str, ...] = ("KIVI", "InfiniGen"),
    mode: Literal["live", "replay"] = "live",
    **kwargs: Any,
) -> dict[str, Any]:
    """이해관계자 Agent의 전체 산출: analysis + evidence + sources + diagnostics."""
    tech_results = [
        evaluate_stakeholder(tech, mode=mode, **kwargs)
        for tech in technologies
    ]

    evidence: dict[str, dict[str, Any]] = {}
    sources: dict[str, dict[str, Any]] = {}
    errors: dict[str, dict[str, Any]] = {}
    web_search_calls = 0
    fetch_attempts = 0

    for result in tech_results:
        collection = result["collection"]
        for entries in (collection.get("topics") or {}).values():
            for entry in entries:
                evidence[entry["evidence_id"]] = entry
        sources.update(collection.get("sources") or {})
        web_search_calls += int((collection.get("metrics") or {}).get("web_search_calls") or 0)
        fetch_attempts += int((collection.get("metrics") or {}).get("fetch_attempts") or 0)
        for index, item in enumerate(collection.get("errors") or []):
            key = f"stakeholder-{result['technology']}-{index}"
            errors[key] = {
                "node": "stakeholder",
                "reason": str(item.get("error") or item),
                "fatal": False,
                "recovered": False,
                "kind": "service",
            }

    unresolved = [
        question
        for result in tech_results
        for question in result["unresolved_questions"]
    ]
    analysis_status = (
        "insufficient_evidence"
        if any(result["status"] != "complete" for result in tech_results)
        else "complete"
    )
    analysis = {
        "perspective": "stakeholder",
        "technologies": {
            result["technology"]: result["judgments"]
            for result in tech_results
        },
        "unresolved_questions": unresolved,
        "status": analysis_status,
    }

    return {
        "stakeholder_analysis": analysis,
        "evidence": evidence,
        "sources": sources,
        "errors": errors,
        "metrics": {
            "web_search_calls": web_search_calls,
            "fetch_attempts": fetch_attempts,
        },
    }


__all__ = [
    "StakeholderTopic",
    "STAKEHOLDER_TOPICS",
    "STAKEHOLDER_LABELS",
    "collect_stakeholder_evidence",
    "build_stakeholder_judgments",
    "evaluate_stakeholder",
    "build_stakeholder_analysis",
    "run_stakeholder_agent",
]
