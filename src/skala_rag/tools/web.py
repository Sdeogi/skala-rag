import json
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any, Literal

from dotenv import load_dotenv
from langchain_tavily import TavilyExtract, TavilySearch

from langchain.agents import create_agent
from langchain.chat_models import init_chat_model
from pydantic import BaseModel, Field


load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CACHE_DIR = PROJECT_ROOT / "data" / "web"


class WebEvidenceSummary(BaseModel):
    """웹 원문에서 추출한 근거 요약."""

    claim: str = Field(
        description="질문과 관련하여 출처가 직접 주장하거나 보고하는 핵심 내용"
    )
    quote: str = Field(
        description="claim을 직접 뒷받침하는 원문의 짧은 근거 구절"
    )
    location: str = Field(
        description="근거가 있는 위치. 섹션 제목이나 문단 위치"
    )
    limitation: str = Field(
        description="이 근거를 해석할 때의 조건이나 한계. 없으면 빈 문자열"
    )


def search_web(
    query: str,
    max_results: int = 3,
) -> list[dict[str, Any]]:
    """Tavily로 웹을 검색하고 검색 결과 목록을 반환한다."""

    search = TavilySearch(max_results=max_results)

    response = search.invoke(
        {
            "query": query,
        }
    )

    return response.get("results", [])


def _search_cache_file(
    query: str,
    max_results: int,
    cache_dir: Path = DEFAULT_CACHE_DIR,
) -> Path:
    """검색 조건을 안정적인 캐시 파일명으로 변환한다."""

    cache_key = sha256(
        f"{query}|{max_results}".encode("utf-8")
    ).hexdigest()

    return cache_dir / f"search_{cache_key}.json"


def save_search_cache(
    query: str,
    results: list[dict[str, Any]],
    max_results: int,
    cache_dir: Path = DEFAULT_CACHE_DIR,
) -> list[dict[str, Any]]:
    """웹 검색 결과를 JSON 캐시에 저장한다."""

    cache_path = _search_cache_file(
        query,
        max_results,
        cache_dir,
    )
    cache_path.parent.mkdir(parents=True, exist_ok=True)

    payload = {
        "query": query,
        "max_results": max_results,
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "results": results,
    }

    cache_path.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    return results


def load_search_cache(
    query: str,
    max_results: int,
    cache_dir: Path = DEFAULT_CACHE_DIR,
) -> list[dict[str, Any]]:
    """저장된 웹 검색 결과를 읽는다."""

    cache_path = _search_cache_file(
        query,
        max_results,
        cache_dir,
    )

    if not cache_path.exists():
        raise FileNotFoundError(
            f"저장된 웹 검색 캐시가 없습니다: {query}"
        )

    payload = json.loads(
        cache_path.read_text(encoding="utf-8")
    )

    return payload["results"]


def get_search_results(
    query: str,
    max_results: int = 3,
    mode: Literal["live", "replay"] = "live",
    cache_dir: Path = DEFAULT_CACHE_DIR,
) -> list[dict[str, Any]]:
    """live에서는 검색 후 저장하고, replay에서는 캐시를 읽는다."""

    if mode == "live":
        results = search_web(
            query,
            max_results=max_results,
        )

        return save_search_cache(
            query,
            results,
            max_results,
            cache_dir,
        )

    if mode == "replay":
        return load_search_cache(
            query,
            max_results,
            cache_dir,
        )

    raise ValueError(
        f"지원하지 않는 mode입니다: {mode}"
    )


def fetch_source(url: str) -> dict[str, Any]:
    """URL의 실제 원문을 가져온다."""

    extractor = TavilyExtract(
        extract_depth="basic",
        include_images=False,
        format="markdown",
    )

    response = extractor.invoke(
        {
            "urls": [url],
        }
    )

    if isinstance(response, str):
        raise RuntimeError(
            f"원문을 가져오지 못했습니다: {url}, "
            f"reason={response}"
        )

    results = response.get("results", [])

    if not results:
        failed_results = response.get("failed_results", [])
        raise RuntimeError(
            f"원문을 가져오지 못했습니다: {url}, "
            f"failed_results={failed_results}"
        )

    return results[0]


def _cache_file(
    url: str,
    cache_dir: Path = DEFAULT_CACHE_DIR,
) -> Path:
    """URL을 안정적인 캐시 파일명으로 변환한다."""

    cache_key = sha256(url.encode("utf-8")).hexdigest()
    return cache_dir / f"{cache_key}.json"


def save_source_cache(
    source: dict[str, Any],
    cache_dir: Path = DEFAULT_CACHE_DIR,
) -> dict[str, Any]:
    """가져온 원문을 JSON 캐시에 저장한다."""

    url = source.get("url")

    if not url:
        raise ValueError("캐시할 source에 url이 없습니다.")

    raw_content = source.get("raw_content", "")

    cached_source = {
        **source,
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "content_hash": sha256(
            raw_content.encode("utf-8")
        ).hexdigest(),
    }

    cache_path = _cache_file(url, cache_dir)
    cache_path.parent.mkdir(parents=True, exist_ok=True)

    cache_path.write_text(
        json.dumps(
            cached_source,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    return cached_source


def load_source_cache(
    url: str,
    cache_dir: Path = DEFAULT_CACHE_DIR,
) -> dict[str, Any]:
    """저장된 원문 캐시를 읽는다."""

    cache_path = _cache_file(url, cache_dir)

    if not cache_path.exists():
        raise FileNotFoundError(
            f"저장된 웹 원문 캐시가 없습니다: {url}"
        )

    return json.loads(
        cache_path.read_text(encoding="utf-8")
    )


def get_source(
    url: str,
    mode: Literal["live", "replay"] = "live",
    cache_dir: Path = DEFAULT_CACHE_DIR,
) -> dict[str, Any]:
    """live에서는 웹에서 수집하고, replay에서는 캐시를 읽는다."""

    if mode == "live":
        source = fetch_source(url)
        return save_source_cache(source, cache_dir)

    if mode == "replay":
        return load_source_cache(url, cache_dir)

    raise ValueError(
        f"지원하지 않는 mode입니다: {mode}"
    )


def summarize_source(
    source: dict[str, Any],
    question: str,
) -> dict[str, Any]:
    """웹 원문에서 질문과 관련된 근거를 구조화한다."""

    raw_content = source.get("raw_content", "")

    if not raw_content:
        raise ValueError("source에 raw_content가 없습니다.")

    model = init_chat_model(
        "gpt-5.4-mini",
        model_provider="openai",
    )

    agent = create_agent(
        model=model,
        tools=[],
        response_format=WebEvidenceSummary,
        system_prompt=(
            "당신은 웹 원문에서 검증 가능한 근거만 추출하는 분석기입니다. "
            "반드시 제공된 원문에 직접 근거해서 답하세요. "
            "원문에 없는 내용을 추론하거나 보완하지 마세요. "
            "quote는 claim을 실제로 뒷받침하는 원문 구절이어야 합니다."
        ),
    )

    result = agent.invoke(
        {
            "messages": [
                {
                    "role": "user",
                    "content": (
                        f"질문:\n{question}\n\n"
                        f"출처 URL:\n{source.get('url', '')}\n\n"
                        f"원문:\n{raw_content}"
                    ),
                }
            ]
        }
    )

    summary = result["structured_response"]

    return {
        **summary.model_dump(),
        "source_url": source.get("url", ""),
        "source_title": source.get("title", ""),
    }