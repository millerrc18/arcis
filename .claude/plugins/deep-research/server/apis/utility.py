"""Utility API wrappers -- Wikipedia, Internet Archive.

All APIs are free and require no API keys.
"""

from __future__ import annotations

from typing import Any

import httpx

from ..session import log

# Timeouts for utility APIs
UTILITY_TIMEOUT = 30.0


async def search_wikipedia(
    query: str,
    max_results: int = 5,
) -> dict[str, Any]:
    """Search Wikipedia articles.

    Returns results dict matching the standard search format.
    """
    params: dict[str, Any] = {
        "action": "query",
        "list": "search",
        "srsearch": query,
        "format": "json",
        "srlimit": max_results,
        "srprop": "snippet|timestamp|wordcount",
    }

    try:
        async with httpx.AsyncClient(timeout=UTILITY_TIMEOUT) as client:
            resp = await client.get(
                "https://en.wikipedia.org/w/api.php",
                params=params,
            )
            resp.raise_for_status()
            data = resp.json()

            search_results = data.get("query", {}).get("search", [])
            total_hits = data.get("query", {}).get("searchinfo", {}).get("totalhits", 0)

            results = []
            for r in search_results:
                title = r.get("title", "")
                # Strip HTML from snippet
                snippet = r.get("snippet", "")
                import re
                snippet = re.sub(r"<[^>]+>", "", snippet)

                page_url = f"https://en.wikipedia.org/wiki/{title.replace(' ', '_')}"

                result = {
                    "title": title,
                    "url": page_url,
                    "snippet": snippet,
                    "date": r.get("timestamp", ""),
                    "relevance_score": 0.0,
                    "source_type": "encyclopedia",
                }
                results.append(result)

            return {
                "results": results[:max_results],
                "total_count": total_hits,
                "api_used": "wikipedia",
            }
    except Exception as e:
        log(f"Wikipedia error: {e}")
        return {
            "results": [],
            "total_count": 0,
            "api_used": "wikipedia",
            "error": f"Wikipedia search failed: {e}",
        }


async def get_wayback_url(url: str) -> str | None:
    """Get the most recent Wayback Machine archived snapshot URL.

    Args:
        url: The original URL to look up.

    Returns:
        The archived snapshot URL, or None if not available.
    """
    try:
        async with httpx.AsyncClient(timeout=UTILITY_TIMEOUT) as client:
            resp = await client.get(
                "https://archive.org/wayback/available",
                params={"url": url},
            )
            resp.raise_for_status()
            data = resp.json()

            snapshot = data.get("archived_snapshots", {}).get("closest")
            if snapshot and snapshot.get("available"):
                return snapshot.get("url")

    except Exception as e:
        log(f"Wayback Machine error for {url}: {e}")

    return None
