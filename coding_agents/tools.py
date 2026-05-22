"""Custom tools available to the development-agent team."""

from __future__ import annotations

import os
from typing import Any, Literal

from langchain_core.tools import BaseTool, tool
from tavily import TavilyClient


SearchDepth = Literal["basic", "advanced", "fast", "ultra-fast"]
SearchTopic = Literal["general", "news", "finance"]
ExtractDepth = Literal["basic", "advanced"]
ExtractFormat = Literal["markdown", "text"]

_MAX_RESULTS_LIMIT = 10
_CONTENT_LIMIT = 4_000
_RAW_CONTENT_LIMIT = 12_000


def default_tools() -> list[BaseTool]:
    """Return the custom tools shared by the main agent and subagents."""

    return [web_search, fetch_url]


@tool
def web_search(
    query: str,
    max_results: int = 5,
    topic: SearchTopic = "general",
    search_depth: SearchDepth = "basic",
    include_raw_content: bool = False,
) -> dict[str, Any]:
    """Search the web for current information using Tavily.

    Args:
        query: Search query to run.
        max_results: Number of results to return, capped at 10.
        topic: Search topic: general, news, or finance.
        search_depth: Tavily search depth: basic, advanced, fast, or ultra-fast.
        include_raw_content: Whether to include truncated extracted page content.
    """

    client = _tavily_client()
    bounded_max_results = _bounded_max_results(max_results)
    result = client.search(
        query=query,
        max_results=bounded_max_results,
        topic=topic,
        search_depth=search_depth,
        include_answer=True,
        include_raw_content="markdown" if include_raw_content else False,
    )
    return _compact_search_result(result, include_raw_content=include_raw_content)


@tool
def fetch_url(
    url: str,
    query: str | None = None,
    extract_depth: ExtractDepth = "basic",
    format: ExtractFormat = "markdown",
) -> dict[str, Any]:
    """Extract readable content from a web page URL using Tavily.

    Args:
        url: URL to fetch and extract.
        query: Optional extraction focus or question.
        extract_depth: Extraction depth: basic or advanced.
        format: Returned content format: markdown or text.
    """

    result = _tavily_client().extract(
        urls=url,
        query=query,
        extract_depth=extract_depth,
        format=format,
    )
    return _compact_extract_result(result)


def _tavily_client() -> TavilyClient:
    api_key = os.environ.get("TAVILY_API_KEY")
    if not api_key:
        raise RuntimeError("TAVILY_API_KEY is required to use web tools.")
    return TavilyClient(api_key=api_key, client_source="coding-agents")


def _bounded_max_results(max_results: int) -> int:
    return max(1, min(max_results, _MAX_RESULTS_LIMIT))


def _compact_search_result(result: dict[str, Any], *, include_raw_content: bool) -> dict[str, Any]:
    compact_results: list[dict[str, Any]] = []
    for item in result.get("results", []):
        compact_item = {
            "title": item.get("title"),
            "url": item.get("url"),
            "content": _truncate(item.get("content"), _CONTENT_LIMIT),
            "score": item.get("score"),
            "published_date": item.get("published_date"),
        }
        if include_raw_content:
            compact_item["raw_content"] = _truncate(item.get("raw_content"), _RAW_CONTENT_LIMIT)
        compact_results.append(compact_item)

    return {
        "query": result.get("query"),
        "answer": result.get("answer"),
        "results": compact_results,
    }


def _compact_extract_result(result: dict[str, Any]) -> dict[str, Any]:
    compact_results: list[dict[str, Any]] = []
    for item in result.get("results", []):
        compact_results.append(
            {
                "url": item.get("url"),
                "raw_content": _truncate(item.get("raw_content"), _RAW_CONTENT_LIMIT),
                "images": item.get("images") or [],
            }
        )

    return {
        "results": compact_results,
        "failed_results": result.get("failed_results", []),
    }


def _truncate(value: Any, limit: int) -> Any:
    if not isinstance(value, str) or len(value) <= limit:
        return value
    return value[:limit].rstrip() + "\n...[truncated]"
