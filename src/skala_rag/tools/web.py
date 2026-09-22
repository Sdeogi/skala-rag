from typing import Any

from dotenv import load_dotenv
from langchain_tavily import TavilyExtract, TavilySearch


load_dotenv()


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