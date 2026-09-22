from typing import Any

from dotenv import load_dotenv
from langchain_tavily import TavilySearch


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