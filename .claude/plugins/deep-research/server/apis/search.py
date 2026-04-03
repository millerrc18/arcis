"""Web search API wrappers with fallback chain.

Fallback order: Tavily → Exa → Serper → Brave
Each API is skipped if its key is not configured or it returns an error.
"""

from __future__ import annotations

import os
import json
from typing import Any

import httpx

from ..session import log

# Timeouts for search APIs
SEARCH_TIMEOUT = 30.0


async def _search_tavily(
    query: str,
    max_results: int = 10,
    freshness: str = "any",
    detail_level: str = "summaries",
    exclude_urls: list[str] | None = None,
) -> dict[str, Any] | None:
    """Search via Tavily API."""
    api_key = os.environ.get("TAVILY_API_KEY")
    if not api_key:
        return None

    payload: dict[str, Any] = {
        "api_key": api_key,
        "query": query,
        "max_results": max_results,
        "include_answer": detail_level in ("summaries", "full"),
        "include_raw_content": detail_level == "full",
        "search_depth": "advanced" if detail_level == "full" else "basic",
    }

    if freshness != "any":
        # Tavily uses days parameter for recency
        freshness_map = {"day": 1, "week": 7, "month": 30, "year": 365}
        if freshness in freshness_map:
            payload["days"] = freshness_map[freshness]

    if exclude_urls:
        payload["exclude_domains"] = [
            u.split("/")[2] if len(u.split("/")) > 2 else u for u in exclude_urls[:20]
        ]

    try:
        async with httpx.AsyncClient(timeout=SEARCH_TIMEOUT) as client:
            resp = await client.post("https://api.tavily.com/search", json=payload)
            resp.raise_for_status()
            data = resp.json()

            results = []
            for r in data.get("results", []):
                result = {
                    "title": r.get("title", ""),
                    "url": r.get("url", ""),
                    "snippet": r.get("content", "")[:500] if detail_level == "snippets" else r.get("content", ""),
                    "date": r.get("published_date", ""),
                    "relevance_score": r.get("score", 0.0),
                    "source_type": "web",
                }
                results.append(result)

            return {
                "results": results[:max_results],
                "total_count": len(data.get("results", [])),
                "api_used": "tavily",
                "answer": data.get("answer", ""),
            }
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 429:
            log(f"Tavily rate limited: {e}")
        else:
            log(f"Tavily error {e.response.status_code}: {e}")
        return None
    except Exception as e:
        log(f"Tavily error: {e}")
        return None


async def _search_exa(
    query: str,
    max_results: int = 10,
    freshness: str = "any",
    detail_level: str = "summaries",
    exclude_urls: list[str] | None = None,
) -> dict[str, Any] | None:
    """Search via Exa API (semantic/neural search)."""
    api_key = os.environ.get("EXA_API_KEY")
    if not api_key:
        return None

    payload: dict[str, Any] = {
        "query": query,
        "numResults": max_results,
        "type": "auto",
        "useAutoprompt": True,
        "contents": {
            "text": {"maxCharacters": 2000 if detail_level != "snippets" else 500},
        },
    }

    if exclude_urls:
        payload["excludeDomains"] = [
            u.split("/")[2] if len(u.split("/")) > 2 else u for u in exclude_urls[:20]
        ]

    if freshness != "any":
        from datetime import datetime, timedelta

        now = datetime.now()
        delta_map = {"day": 1, "week": 7, "month": 30, "year": 365}
        if freshness in delta_map:
            start = now - timedelta(days=delta_map[freshness])
            payload["startPublishedDate"] = start.strftime("%Y-%m-%dT%H:%M:%S.000Z")

    try:
        async with httpx.AsyncClient(timeout=SEARCH_TIMEOUT) as client:
            resp = await client.post(
                "https://api.exa.ai/search",
                json=payload,
                headers={"x-api-key": api_key, "Content-Type": "application/json"},
            )
            resp.raise_for_status()
            data = resp.json()

            results = []
            for r in data.get("results", []):
                result = {
                    "title": r.get("title", ""),
                    "url": r.get("url", ""),
                    "snippet": r.get("text", "")[:500] if detail_level == "snippets" else r.get("text", ""),
                    "date": r.get("publishedDate", ""),
                    "relevance_score": r.get("score", 0.0),
                    "source_type": "web",
                }
                results.append(result)

            return {
                "results": results[:max_results],
                "total_count": len(data.get("results", [])),
                "api_used": "exa",
            }
    except Exception as e:
        log(f"Exa error: {e}")
        return None


async def _search_serper(
    query: str,
    max_results: int = 10,
    freshness: str = "any",
    detail_level: str = "summaries",
    exclude_urls: list[str] | None = None,
) -> dict[str, Any] | None:
    """Search via Serper API (Google results)."""
    api_key = os.environ.get("SERPER_API_KEY")
    if not api_key:
        return None

    payload: dict[str, Any] = {
        "q": query,
        "num": max_results,
    }

    if freshness != "any":
        tbs_map = {"day": "qdr:d", "week": "qdr:w", "month": "qdr:m", "year": "qdr:y"}
        if freshness in tbs_map:
            payload["tbs"] = tbs_map[freshness]

    try:
        async with httpx.AsyncClient(timeout=SEARCH_TIMEOUT) as client:
            resp = await client.post(
                "https://google.serper.dev/search",
                json=payload,
                headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
            )
            resp.raise_for_status()
            data = resp.json()

            results = []
            for r in data.get("organic", []):
                url = r.get("link", "")
                if exclude_urls and url in exclude_urls:
                    continue
                result = {
                    "title": r.get("title", ""),
                    "url": url,
                    "snippet": r.get("snippet", ""),
                    "date": r.get("date", ""),
                    "relevance_score": r.get("position", max_results) / max_results,
                    "source_type": "web",
                }
                results.append(result)

            return {
                "results": results[:max_results],
                "total_count": len(data.get("organic", [])),
                "api_used": "serper",
            }
    except Exception as e:
        log(f"Serper error: {e}")
        return None


async def _search_brave(
    query: str,
    max_results: int = 10,
    freshness: str = "any",
    detail_level: str = "summaries",
    exclude_urls: list[str] | None = None,
) -> dict[str, Any] | None:
    """Search via Brave Search API."""
    api_key = os.environ.get("BRAVE_API_KEY")
    if not api_key:
        return None

    params: dict[str, Any] = {
        "q": query,
        "count": max_results,
    }

    if freshness != "any":
        freshness_map = {"day": "pd", "week": "pw", "month": "pm", "year": "py"}
        if freshness in freshness_map:
            params["freshness"] = freshness_map[freshness]

    try:
        async with httpx.AsyncClient(timeout=SEARCH_TIMEOUT) as client:
            resp = await client.get(
                "https://api.search.brave.com/res/v1/web/search",
                params=params,
                headers={"Accept": "application/json", "X-Subscription-Token": api_key},
            )
            resp.raise_for_status()
            data = resp.json()

            results = []
            for r in data.get("web", {}).get("results", []):
                url = r.get("url", "")
                if exclude_urls and url in exclude_urls:
                    continue
                result = {
                    "title": r.get("title", ""),
                    "url": url,
                    "snippet": r.get("description", ""),
                    "date": r.get("page_age", ""),
                    "relevance_score": 0.5,
                    "source_type": "web",
                }
                results.append(result)

            return {
                "results": results[:max_results],
                "total_count": len(results),
                "api_used": "brave",
            }
    except Exception as e:
        log(f"Brave error: {e}")
        return None


async def search_web(
    query: str,
    max_results: int = 10,
    freshness: str = "any",
    detail_level: str = "summaries",
    exclude_urls: list[str] | None = None,
) -> dict[str, Any]:
    """Execute web search with fallback chain: Tavily → Exa → Serper → Brave.

    Returns results dict or error dict.
    """
    # Try each API in priority order
    for search_fn, name in [
        (_search_tavily, "Tavily"),
        (_search_exa, "Exa"),
        (_search_serper, "Serper"),
        (_search_brave, "Brave"),
    ]:
        log(f"Trying {name} for query: {query[:80]}...")
        result = await search_fn(
            query=query,
            max_results=max_results,
            freshness=freshness,
            detail_level=detail_level,
            exclude_urls=exclude_urls,
        )
        if result and result.get("results"):
            log(f"  → {name} returned {len(result['results'])} results")
            return result
        elif result is None:
            log(f"  → {name} skipped (no API key or error)")
        else:
            log(f"  → {name} returned 0 results")

    return {
        "results": [],
        "total_count": 0,
        "api_used": "none",
        "error": "No search API returned results. Check that at least one API key is configured: TAVILY_API_KEY, EXA_API_KEY, SERPER_API_KEY, or BRAVE_API_KEY.",
    }
