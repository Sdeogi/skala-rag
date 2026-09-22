"""시장성 웹 근거 수집 + Rubric 판정 Agent."""

import re
from collections import deque
from hashlib import sha256
from pathlib import Path
from typing import Any, Literal
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from skala_rag.tools.web import (
    DEFAULT_CACHE_DIR,
    EvidenceValidationError,
    get_search_results,
    get_source,
    summarize_source,
)

MarketTopic = Literal["market_size", "adoption", "ecosystem"]

MARKET_QUESTIONS = {
    "market_size": (
        "{technology} 자체 또는 관련 LLM 추론/AI 인프라 시장의 규모와 성장률은 얼마인가? "
        "개별 기술의 시장과 관련 시장을 구분하고, 수치/단위/시점/발행 주체를 원문 범위에서 기록하라."
    ),
    "adoption": (
        "{technology}가 실제 제품, 서비스 또는 주요 프레임워크에 사용/통합됐다는 명시적 보고가 있는가? "
        "영향 관계, 서드파티 구현, 공식 통합, 상용 채택을 서로 바꿔 쓰지 마라. "
        "원문이 명시한 미지원/통합 제약도 기록하되, 정보 부재를 사례 부재로 해석하지 마라."
    ),
    "ecosystem": (
        "{technology}와 직접 관계가 명시된 후속 연구, 파생 구현, 프레임워크 영향 또는 구현 업데이트는 무엇인가? "
        "어떤 논문/프로젝트가 어떤 관계라고 보고하는지 하나의 구체적 사실로 답하라. "
        "Similar papers, 인용 수, 소스코드 공개 링크만으로 후속 연구/생태계 확장을 주장하지 마라."
    ),
}

MARKET_LABELS = {
    "market_size": ("직접 자료 있음", "관련 시장 자료만 있음", "미확인"),
    "adoption": ("상용 서비스 적용 확인", "주류 프레임워크 통합", "연구 재현 수준", "미확인"),
    "ecosystem": ("활발", "일부 있음", "미확인"),
}

TECHNOLOGY_SEARCH_TERMS = {
    "KIVI": {
        "approach": "KV cache quantization",
        "paper_id": "2402.02750",
        "integration_targets": "Hugging Face Transformers vLLM",
    },
    "InfiniGen": {
        "approach": "KV cache offloading dynamic KV cache management",
        "paper_id": "2406.19707",
        "integration_targets": "LLM serving GPU CPU offloading",
    },
}

SEARCH_QUERIES = {
    "market_size": (
        "{technology} {approach} LLM inference optimization AI infrastructure market size growth",
        "{technology} {approach} market report CAGR revenue forecast",
    ),
    "adoption": (
        "{technology} {approach} {integration_targets} integration adoption",
        "{technology} {approach} limitation issue unsupported integration",
    ),
    "ecosystem": (
        "{technology} {paper_id} follow-up research",
        "{technology} {approach} derived implementation GitHub",
        "{technology} {integration_targets} implementation ecosystem",
        "{technology} {approach} limitation issue criticism",
    ),
}

TECHNOLOGY_ANCHORS = {
    "KIVI": ("kv cache", "quantization", "2bit", "2 bit", "2402.02750"),
    "InfiniGen": ("kv cache", "offload", "2406.19707"),
}

TOPIC_RELATIONS = {
    "market_size": {"market_estimate"},
    "adoption": {"adoption", "adoption_limitation"},
    "ecosystem": {
        "followup_research",
        "derived_implementation",
        "framework_influence",
        "implementation_update",
    },
}


def normalize_url(url: str) -> str:
    """중복 판정용 URL 정규화."""
    p = urlsplit(url)
    if p.scheme.lower() not in ("http", "https") or not p.hostname or p.username or p.password:
        raise ValueError("인증 정보가 없는 http(s) URL이 필요합니다")
    query = [
        (k, v)
        for k, v in parse_qsl(p.query, keep_blank_values=True)
        if not k.lower().startswith("utm_") and k.lower() not in {"gclid", "fbclid"}
    ]
    return urlunsplit(
        (
            p.scheme.lower(),
            p.netloc.lower(),
            p.path.rstrip("/"),
            urlencode(sorted(query)),
            "",
        )
    )


def _text(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _normalized_text(text: str) -> str:
    return re.sub(r"[\s_\-–—]+", " ", text.casefold())


def _is_original_paper(url: str, technology: str) -> bool:
    p = urlsplit(url)
    host = (p.hostname or "").lower().removeprefix("www.")
    paper_id = re.escape(TECHNOLOGY_SEARCH_TERMS[technology]["paper_id"])
    if host in {"arxiv.org", "export.arxiv.org", "alphaxiv.org"}:
        return bool(
            re.fullmatch(
                rf"/(?:abs|pdf|html|overview)/{paper_id}(?:v\d+)?(?:\.pdf)?/?",
                p.path,
            )
        )
    if host == "huggingface.co" and re.fullmatch(rf"/papers/{paper_id}/?", p.path):
        return True
    return (
        technology == "KIVI"
        and host == "proceedings.mlr.press"
        and p.path.rstrip("/") == "/v235/liu24bz.html"
    )


def is_search_result_relevant(
    result: dict,
    technology: str,
    topic: MarketTopic,
) -> bool:
    """검색 스니펫 단계의 저비용 후보 필터."""
    if technology not in TECHNOLOGY_SEARCH_TERMS or topic not in MARKET_QUESTIONS:
        return False

    url = _text(result.get("url"))
    try:
        normalize_url(url)
    except (ValueError, TypeError):
        return False

    text = _normalized_text(
        " ".join(_text(result.get(k)) for k in ("title", "content", "url"))
    )

    if topic == "market_size":
        domain = any(
            t in text
            for t in (
                "llm",
                "inference",
                "artificial intelligence",
                "ai infrastructure",
                "인공지능",
                "추론",
            )
        )
        market = any(
            t in text
            for t in ("market", "cagr", "growth", "revenue", "forecast", "시장", "성장률")
        )
        return domain and market

    if not re.search(rf"\b{re.escape(technology.casefold())}\b", text):
        return False
    if not any(_normalized_text(a) in text for a in TECHNOLOGY_ANCHORS[technology]):
        return False
    return not (topic == "ecosystem" and _is_original_paper(url, technology))


def _round_robin_candidates(groups: list[list[tuple]]) -> list[tuple]:
    """검색어마다 하나씩 번갈아 선택하며 URL 중복을 제거한다."""
    queues = [deque(group) for group in groups]
    seen: set[str] = set()
    ordered = []
    while any(queues):
        for queue in queues:
            while queue:
                candidate = queue.popleft()
                key = normalize_url(candidate[2]["url"])
                if key in seen:
                    continue
                seen.add(key)
                ordered.append(candidate)
                break
    return ordered


def _error(stage: str, topic: str, exc: Exception, **context: Any) -> dict:
    return {
        "stage": stage,
        "topic": topic,
        "error_type": type(exc).__name__,
        "error": (
            str(exc)
            if isinstance(exc, EvidenceValidationError)
            else f"{stage} 단계 실패 ({type(exc).__name__})"
        ),
        **context,
    }


def _source_record(source_id: str, summary: dict[str, Any]) -> dict[str, Any]:
    return {
        "source_id": source_id,
        "title": summary.get("source_title") or "제목 미상",
        "url": summary.get("source_url") or None,
        "retrieved_at": summary.get("collected_at"),
        "content_hash": summary.get("content_hash"),
        "source_type": "web",
    }


def collect_market_evidence(
    technology: str,
    topics: tuple[MarketTopic, ...] = ("market_size", "adoption", "ecosystem"),
    mode: Literal["live", "replay"] = "live",
    max_results: int = 3,
    sources_per_topic: int = 2,
    *,
    max_attempts_per_topic: int = 6,
    cache_dir: Path = DEFAULT_CACHE_DIR,
) -> dict[str, Any]:
    """시장성 평가에 필요한 웹 근거를 제한된 횟수 안에서 수집한다."""
    if technology not in TECHNOLOGY_SEARCH_TERMS:
        raise ValueError(f"지원하지 않는 technology: {technology}")
    if not topics or any(t not in MARKET_QUESTIONS for t in topics):
        raise ValueError("topics를 확인하세요")
    if mode not in ("live", "replay"):
        raise ValueError("mode는 live 또는 replay여야 합니다")
    if type(max_results) is not int or not 1 <= max_results <= 20:
        raise ValueError("max_results는 1~20 정수여야 합니다")
    if type(sources_per_topic) is not int or sources_per_topic < 1:
        raise ValueError("sources_per_topic는 양의 정수여야 합니다")
    if (
        type(max_attempts_per_topic) is not int
        or not sources_per_topic <= max_attempts_per_topic <= 30
    ):
        raise ValueError("max_attempts_per_topic는 sources_per_topic 이상, 30 이하여야 합니다")

    output: dict[str, Any] = {
        "technology": technology,
        "evidence": [],
        "indirect_evidence": [],
        "sources": {},
        "skipped": [],
        "errors": [],
        "searches": [],
        "topic_status": {},
    }
    source_memo: dict[str, dict] = {}
    terms = TECHNOLOGY_SEARCH_TERMS[technology]

    for topic in dict.fromkeys(topics):
        question = MARKET_QUESTIONS[topic].format(technology=technology)
        groups = []
        topic_error_start = len(output["errors"])

        for template in SEARCH_QUERIES[topic]:
            query = template.format(technology=technology, **terms)
            candidates = []
            try:
                hits = get_search_results(
                    query,
                    max_results=max_results,
                    mode=mode,
                    cache_dir=cache_dir,
                )
                if not isinstance(hits, list) or not all(isinstance(h, dict) for h in hits):
                    raise TypeError("검색 결과는 list[dict]여야 합니다")
                for rank, hit in enumerate(hits, start=1):
                    if is_search_result_relevant(hit, technology, topic):
                        candidates.append((query, rank, hit))
                    else:
                        output["skipped"].append(
                            {
                                "stage": "candidate_filter",
                                "topic": topic,
                                "url": hit.get("url"),
                                "reason": "irrelevant_or_original_paper",
                            }
                        )
                output["searches"].append(
                    {
                        "topic": topic,
                        "query": query,
                        "returned": len(hits),
                        "relevant": len(candidates),
                    }
                )
            except Exception as exc:
                output["errors"].append(_error("search", topic, exc, query=query))
            groups.append(candidates)

        ordered = _round_robin_candidates(groups)
        accepted = attempted = 0
        seen_contents: set[str] = set()

        for query, rank, hit in ordered:
            if accepted >= sources_per_topic or attempted >= max_attempts_per_topic:
                break
            url = hit["url"]
            attempted += 1
            stage = "fetch"

            try:
                if url not in source_memo:
                    source_memo[url] = get_source(url, mode=mode, cache_dir=cache_dir)
                source = source_memo[url]
                raw = source.get("raw_content")
                if not isinstance(raw, str) or not raw.strip():
                    raise ValueError("원문이 비어 있습니다")

                if not is_search_result_relevant(
                    {
                        "url": source.get("url", url),
                        "title": source.get("title"),
                        "content": raw,
                    },
                    technology,
                    topic,
                ):
                    output["skipped"].append(
                        {
                            "stage": "source_filter",
                            "topic": topic,
                            "url": url,
                            "reason": "source_not_relevant",
                        }
                    )
                    continue

                digest = sha256(raw.encode("utf-8")).hexdigest()
                if digest in seen_contents:
                    output["skipped"].append(
                        {
                            "stage": "content_dedupe",
                            "topic": topic,
                            "url": url,
                            "reason": "duplicate_content",
                        }
                    )
                    continue

                stage = "summarize"
                summary = summarize_source(
                    source,
                    question=question,
                    topic=topic,
                    mode=mode,
                    cache_dir=cache_dir,
                )
                seen_contents.add(digest)

                if summary["evidence_status"] == "not_found":
                    output["skipped"].append(
                        {
                            "stage": "evidence_filter",
                            "topic": topic,
                            "url": url,
                            "reason": "not_found",
                            "detail": summary["reason"],
                        }
                    )
                    continue

                if summary.get("quote_verified") is not True:
                    raise ValueError("인용문 검증을 통과하지 못했습니다")

                source_key = normalize_url(summary["source_url"])
                source_id = "web-source-" + sha256(
                    f"{source_key}|{digest}".encode()
                ).hexdigest()[:24]
                evidence_key = (
                    f"{source_id}|{technology}|{topic}|{summary['quote']}|{summary['claim']}"
                )
                entry = {
                    **summary,
                    "technology": technology,
                    "topic": topic,
                    "source_id": source_id,
                    "evidence_id": "web-evidence-"
                    + sha256(evidence_key.encode()).hexdigest()[:24],
                    "claim_type": "reported_fact",
                    "conditions": summary.get("limitation") or "",
                    "search_query": query,
                    "search_rank": rank,
                    "search_score": hit.get("score"),
                }
                output["sources"][source_id] = _source_record(source_id, summary)

                if (
                    summary["evidence_status"] == "indirect"
                    or summary["relation_kind"] not in TOPIC_RELATIONS[topic]
                ):
                    entry["evidence_status"] = "indirect"
                    output["indirect_evidence"].append(entry)
                    continue

                if topic == "market_size" and (
                    summary["scope"] == "unspecified"
                    or not re.search(r"\d", summary["quote"])
                ):
                    output["skipped"].append(
                        {
                            "stage": "evidence_filter",
                            "topic": topic,
                            "url": url,
                            "reason": "market_scope_or_numeric_evidence_missing",
                        }
                    )
                    continue

                output["evidence"].append(entry)
                accepted += 1

            except Exception as exc:
                output["errors"].append(_error(stage, topic, exc, url=url))

        output["topic_status"][topic] = {
            "status": "has_evidence" if accepted else "insufficient_evidence",
            "accepted": accepted,
            "attempted": attempted,
            "candidate_count": len(ordered),
            "error_count": len(output["errors"]) - topic_error_start,
            "attempt_limit_reached": (
                attempted >= max_attempts_per_topic and accepted < sources_per_topic
            ),
        }

    output["missing_topics"] = [
        t for t, info in output["topic_status"].items() if not info["accepted"]
    ]
    output["status"] = (
        "insufficient_evidence" if output["missing_topics"] else "has_evidence"
    )
    return output


def _join_claims(entries: list[dict[str, Any]]) -> str:
    claims = []
    for entry in entries:
        claim = str(entry.get("claim") or "").strip()
        if claim and claim not in claims:
            claims.append(claim)
    return " / ".join(claims)


def _join_limitations(entries: list[dict[str, Any]]) -> str:
    values = []
    for entry in entries:
        value = str(entry.get("limitation") or "").strip()
        if value and value not in values:
            values.append(value)
    return " / ".join(values)


def _judgment(
    label: str,
    entries: list[dict[str, Any]],
    *,
    fallback_reason: str,
) -> dict[str, Any]:
    if label not in {value for labels in MARKET_LABELS.values() for value in labels}:
        raise ValueError(f"허용되지 않은 시장성 라벨: {label}")
    if not entries:
        return {
            "label": "미확인",
            "reason": fallback_reason,
            "conditions": "",
            "evidence_ids": [],
        }
    return {
        "label": label,
        "reason": _join_claims(entries) or fallback_reason,
        "conditions": _join_limitations(entries),
        "evidence_ids": [entry["evidence_id"] for entry in entries if entry.get("evidence_id")],
    }


def build_market_judgments(collection: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """수집된 직접 근거를 설계 Rubric 라벨로 결정론적으로 변환한다."""
    evidence = list(collection.get("evidence") or [])

    market_entries = [e for e in evidence if e.get("topic") == "market_size"]
    direct_market = [e for e in market_entries if e.get("scope") == "technology"]
    related_market = [e for e in market_entries if e.get("scope") == "related_market"]
    if direct_market:
        market_size = _judgment(
            "직접 자료 있음",
            direct_market,
            fallback_reason="기술 자체 시장을 직접 다룬 자료가 확인됨",
        )
    elif related_market:
        market_size = _judgment(
            "관련 시장 자료만 있음",
            related_market,
            fallback_reason="관련 LLM 추론/AI 인프라 시장 자료만 확인됨",
        )
    else:
        market_size = _judgment(
            "미확인",
            [],
            fallback_reason="기술 자체 또는 관련 시장의 검증 가능한 수치 근거를 확보하지 못함",
        )

    adoption_entries = [e for e in evidence if e.get("topic") == "adoption"]
    commercial = [e for e in adoption_entries if e.get("adoption_level") == "commercial_service"]
    framework = [e for e in adoption_entries if e.get("adoption_level") == "mainstream_framework"]
    reproduction = [e for e in adoption_entries if e.get("adoption_level") == "research_reproduction"]
    if commercial:
        adoption = _judgment(
            "상용 서비스 적용 확인",
            commercial,
            fallback_reason="상용 서비스 적용을 직접 명시한 근거가 확인됨",
        )
    elif framework:
        adoption = _judgment(
            "주류 프레임워크 통합",
            framework,
            fallback_reason="주류 프레임워크 공식 통합 근거가 확인됨",
        )
    elif reproduction:
        adoption = _judgment(
            "연구 재현 수준",
            reproduction,
            fallback_reason="공개 재현/서드파티 구현 수준의 근거가 확인됨",
        )
    else:
        adoption = _judgment(
            "미확인",
            [],
            fallback_reason="상용 서비스, 주류 프레임워크 통합, 연구 재현 수준을 직접 뒷받침하는 근거를 확보하지 못함",
        )

    ecosystem_entries = [e for e in evidence if e.get("topic") == "ecosystem"]
    source_ids = {e.get("source_id") for e in ecosystem_entries if e.get("source_id")}
    relation_kinds = {
        e.get("relation_kind")
        for e in ecosystem_entries
        if e.get("relation_kind") in TOPIC_RELATIONS["ecosystem"]
    }
    if len(source_ids) >= 2 and len(relation_kinds) >= 2:
        ecosystem = _judgment(
            "활발",
            ecosystem_entries,
            fallback_reason="서로 다른 출처와 두 종류 이상의 생태계 활동이 직접 확인됨",
        )
    elif ecosystem_entries:
        ecosystem = _judgment(
            "일부 있음",
            ecosystem_entries,
            fallback_reason="후속 연구/파생 구현/프레임워크 영향 중 일부 직접 근거가 확인됨",
        )
    else:
        ecosystem = _judgment(
            "미확인",
            [],
            fallback_reason="후속 연구, 파생 구현, 프레임워크 영향의 직접 근거를 확보하지 못함",
        )

    return {
        "market_size": market_size,
        "adoption": adoption,
        "ecosystem": ecosystem,
    }


def evaluate_market(
    technology: str,
    mode: Literal["live", "replay"] = "live",
    *,
    max_results: int = 3,
    sources_per_topic: int = 2,
    max_attempts_per_topic: int = 6,
    cache_dir: Path = DEFAULT_CACHE_DIR,
) -> dict[str, Any]:
    """기술 하나의 시장성 근거 수집과 Rubric 판정을 한 번에 수행한다."""
    collection = collect_market_evidence(
        technology=technology,
        mode=mode,
        max_results=max_results,
        sources_per_topic=sources_per_topic,
        max_attempts_per_topic=max_attempts_per_topic,
        cache_dir=cache_dir,
    )
    judgments = build_market_judgments(collection)
    unresolved = [
        MARKET_QUESTIONS[field].format(technology=technology)
        for field, judgment in judgments.items()
        if judgment["label"] == "미확인"
    ]
    return {
        "technology": technology,
        "judgments": judgments,
        "unresolved_questions": unresolved,
        "status": "insufficient_evidence" if unresolved else "complete",
        "collection": collection,
    }


def build_market_analysis(
    technologies: tuple[str, ...] = ("KIVI", "InfiniGen"),
    mode: Literal["live", "replay"] = "live",
    **kwargs: Any,
) -> dict[str, Any]:
    """Graph에 넘길 수 있는 PerspectiveResult 형태의 market_analysis를 만든다."""
    tech_results = [evaluate_market(tech, mode=mode, **kwargs) for tech in technologies]
    unresolved = [
        question
        for result in tech_results
        for question in result["unresolved_questions"]
    ]
    return {
        "perspective": "market",
        "technologies": {
            result["technology"]: result["judgments"]
            for result in tech_results
        },
        "unresolved_questions": unresolved,
        "status": "insufficient_evidence" if unresolved else "complete",
    }


def run_market_agent(
    technologies: tuple[str, ...] = ("KIVI", "InfiniGen"),
    mode: Literal["live", "replay"] = "live",
    **kwargs: Any,
) -> dict[str, Any]:
    """시장성 Agent의 전체 산출: analysis + evidence + sources + diagnostics."""
    tech_results = [evaluate_market(tech, mode=mode, **kwargs) for tech in technologies]

    evidence: dict[str, dict[str, Any]] = {}
    sources: dict[str, dict[str, Any]] = {}
    errors: dict[str, dict[str, Any]] = {}
    searches = 0
    fetch_attempts = 0

    for result in tech_results:
        collection = result["collection"]
        for entry in collection.get("evidence", []):
            evidence[entry["evidence_id"]] = entry
        sources.update(collection.get("sources") or {})
        searches += len(collection.get("searches") or [])
        fetch_attempts += sum(
            int(info.get("attempted") or 0)
            for info in (collection.get("topic_status") or {}).values()
        )
        for index, item in enumerate(collection.get("errors") or []):
            key = f"market-{result['technology']}-{index}"
            errors[key] = {
                "node": "market",
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
    analysis = {
        "perspective": "market",
        "technologies": {
            result["technology"]: result["judgments"]
            for result in tech_results
        },
        "unresolved_questions": unresolved,
        "status": "insufficient_evidence" if unresolved else "complete",
    }

    return {
        "market_analysis": analysis,
        "evidence": evidence,
        "sources": sources,
        "errors": errors,
        "metrics": {
            "web_search_calls": searches,
            "fetch_attempts": fetch_attempts,
        },
    }


__all__ = [
    "MarketTopic",
    "MARKET_QUESTIONS",
    "MARKET_LABELS",
    "collect_market_evidence",
    "build_market_judgments",
    "evaluate_market",
    "build_market_analysis",
    "run_market_agent",
]
