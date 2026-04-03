"""News search API wrappers.

GDELT is free. NewsAPI requires a key.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta
from typing import Any

import httpx

from ..session import log

# Timeouts for news APIs
NEWS_TIMEOUT = 30.0


async def _search_gdelt(
    query: str,
    max_results: int = 10,
    freshness: str = "week",
) -> dict[str, Any] | None:
    """Search via GDELT API (free, no key required)."""
    # Map freshness to GDELT timespan parameter
    timespan_map = {
        "day": "1440",      # minutes in a day
        "week": "10080",    # minutes in a week
        "month": "43200",   # minutes in 30 days
        "year": "525600",   # minutes in a year
    }
    timespan = timespan_map.get(freshness, "10080")

    params: dict[str, Any] = {
        "query": query,
        "mode": "ArtList",
        "maxrecords": max_results,
        "format": "json",
        "timespan": timespan,
    }

    try:
        async with httpx.AsyncClient(timeout=NEWS_TIMEOUT) as client:
            resp = await client.get(
                "https://api.gdeltproject.org/api/v2/doc/doc",
                params=params,
            )
            resp.raise_for_status()
            data = resp.json()

            results = []
            for article in data.get("articles", []):
                result = {
                    "title": article.get("title", ""),
                    "url": article.get("url", ""),
                    "snippet": f"{article.get('seendate', '')} - {article.get('domain', '')}",
                    "date": article.get("seendate", ""),
                    "relevance_score": 0.0,
                    "source_type": "news",
                }
                results.append(result)

            return {
                "results": results[:max_results],
                "total_count": len(results),
                "api_used": "gdelt",
            }
    except Exception as e:
        log(f"GDELT error: {e}")
        return None


async def _search_newsapi(
    query: str,
    max_results: int = 10,
    freshness: str = "week",
) -> dict[str, Any] | None:
    """Search via NewsAPI (requires NEWSAPI_KEY env var)."""
    api_key = os.environ.get("NEWSAPI_KEY")
    if not api_key:
        return None

    # Calculate from-date based on freshness
    now = datetime.now()
    delta_map = {"day": 1, "week": 7, "month": 30, "year": 365}
    days_back = delta_map.get(freshness, 7)
    from_date = (now - timedelta(days=days_back)).strftime("%Y-%m-%d")

    params: dict[str, Any] = {
        "q": query,
        "pageSize": max_results,
        "sortBy": "relevancy",
        "from": from_date,
        "apiKey": api_key,
    }

    try:
        async with httpx.AsyncClient(timeout=NEWS_TIMEOUT) as client:
            resp = await client.get(
                "https://newsapi.org/v2/everything",
                params=params,
            )
            resp.raise_for_status()
            data = resp.json()

            if data.get("status") != "ok":
                log(f"NewsAPI returned status: {data.get('status')}")
                return None

            results = []
            for article in data.get("articles", []):
                result = {
                    "title": article.get("title", ""),
                    "url": article.get("url", ""),
                    "snippet": article.get("description", "") or "",
                    "date": article.get("publishedAt", ""),
                    "relevance_score": 0.0,
                    "source_type": "news",
                }
                results.append(result)

            return {
                "results": results[:max_results],
                "total_count": data.get("totalResults", len(results)),
                "api_used": "newsapi",
            }
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 429:
            log(f"NewsAPI rate limited: {e}")
        else:
            log(f"NewsAPI error {e.response.status_code}: {e}")
        return None
    except Exception as e:
        log(f"NewsAPI error: {e}")
        return None


async def search_news(
    query: str,
    max_results: int = 10,
    freshness: str = "week",
) -> dict[str, Any]:
    """Execute news search with fallback chain: GDELT -> NewsAPI.

    Returns results dict or error dict.
    """
    for search_fn, name in [
        (_search_gdelt, "GDELT"),
        (_search_newsapi, "NewsAPI"),
    ]:
        log(f"Trying {name} for news query: {query[:80]}...")
        result = await search_fn(
            query=query,
            max_results=max_results,
            freshness=freshness,
        )
        if result and result.get("results"):
            log(f"  -> {name} returned {len(result['results'])} results")
            return result
        elif result is None:
            log(f"  -> {name} skipped (no API key or error)")
        else:
            log(f"  -> {name} returned 0 results")

    return {
        "results": [],
        "total_count": 0,
        "api_used": "none",
        "error": "No news search API returned results. GDELT is free; for NewsAPI set NEWSAPI_KEY.",
    }
