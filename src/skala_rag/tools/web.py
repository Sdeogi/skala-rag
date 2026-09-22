import json
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any, Literal

from dotenv import load_dotenv
from langchain_tavily import TavilyExtract, TavilySearch


load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CACHE_DIR = PROJECT_ROOT / "data" / "web"


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