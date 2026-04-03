"""Content extraction API wrappers with fallback chain.

Fallback order: Firecrawl → Jina Reader → Trafilatura → raw HTTP
Each API is skipped if its key is not configured or it returns an error.
"""

from __future__ import annotations

import os
from typing import Any

import httpx

from ..session import log

CONTENT_TIMEOUT = 45.0
MAX_CONTENT_LENGTH = 50_000  # characters


async def _read_firecrawl(url: str, max_length: int = 5000) -> dict[str, Any] | None:
    """Extract content via Firecrawl API."""
    api_key = os.environ.get("FIRECRAWL_API_KEY")
    if not api_key:
        return None

    try:
        async with httpx.AsyncClient(timeout=CONTENT_TIMEOUT) as client:
            resp = await client.post(
                "https://api.firecrawl.dev/v1/scrape",
                json={
                    "url": url,
                    "formats": ["markdown"],
                    "onlyMainContent": True,
                },
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
            )
            resp.raise_for_status()
            data = resp.json()

            if data.get("success"):
                content = data.get("data", {}).get("markdown", "")
                metadata = data.get("data", {}).get("metadata", {})
                return {
                    "content": content[:max_length],
                    "title": metadata.get("title", ""),
                    "description": metadata.get("description", ""),
                    "full_length": len(content),
                    "truncated": len(content) > max_length,
                    "api_used": "firecrawl",
                }
    except Exception as e:
        log(f"Firecrawl error for {url}: {e}")
    return None


async def _read_jina(url: str, max_length: int = 5000) -> dict[str, Any] | None:
    """Extract content via Jina Reader API (free tier)."""
    try:
        async with httpx.AsyncClient(timeout=CONTENT_TIMEOUT, follow_redirects=True) as client:
            resp = await client.get(
                f"https://r.jina.ai/{url}",
                headers={"Accept": "text/plain", "X-Return-Format": "markdown"},
            )
            resp.raise_for_status()
            content = resp.text

            if content and len(content) > 50:
                return {
                    "content": content[:max_length],
                    "title": "",
                    "description": "",
                    "full_length": len(content),
                    "truncated": len(content) > max_length,
                    "api_used": "jina",
                }
    except Exception as e:
        log(f"Jina error for {url}: {e}")
    return None


async def _read_trafilatura(url: str, max_length: int = 5000) -> dict[str, Any] | None:
    """Extract content via Trafilatura (local, no API key needed)."""
    try:
        import trafilatura

        # Fetch the page
        async with httpx.AsyncClient(timeout=CONTENT_TIMEOUT, follow_redirects=True) as client:
            resp = await client.get(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
                },
            )
            resp.raise_for_status()
            html = resp.text

        # Extract with trafilatura
        content = trafilatura.extract(
            html,
            include_links=True,
            include_tables=True,
            output_format="txt",
            favor_recall=True,
        )

        if content and len(content) > 50:
            # Try to get title
            title = ""
            metadata = trafilatura.extract_metadata(html)
            if metadata:
                title = metadata.title or ""

            return {
                "content": content[:max_length],
                "title": title,
                "description": "",
                "full_length": len(content),
                "truncated": len(content) > max_length,
                "api_used": "trafilatura",
            }
    except ImportError:
        log("Trafilatura not installed, skipping")
    except Exception as e:
        log(f"Trafilatura error for {url}: {e}")
    return None


async def _read_raw_http(url: str, max_length: int = 5000) -> dict[str, Any] | None:
    """Last-resort raw HTTP fetch."""
    try:
        async with httpx.AsyncClient(timeout=CONTENT_TIMEOUT, follow_redirects=True) as client:
            resp = await client.get(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
                },
            )
            resp.raise_for_status()
            content = resp.text

            # Basic HTML tag stripping for readability
            import re

            # Remove script and style blocks
            content = re.sub(r"<script[^>]*>.*?</script>", "", content, flags=re.DOTALL | re.IGNORECASE)
            content = re.sub(r"<style[^>]*>.*?</style>", "", content, flags=re.DOTALL | re.IGNORECASE)
            # Remove tags
            content = re.sub(r"<[^>]+>", " ", content)
            # Collapse whitespace
            content = re.sub(r"\s+", " ", content).strip()

            if content and len(content) > 50:
                return {
                    "content": content[:max_length],
                    "title": "",
                    "description": "",
                    "full_length": len(content),
                    "truncated": len(content) > max_length,
                    "api_used": "raw_http",
                }
    except Exception as e:
        log(f"Raw HTTP error for {url}: {e}")
    return None


async def read_url(
    url: str,
    max_length: int = 5000,
    start_index: int = 0,
    extract_mode: str = "article",
) -> dict[str, Any]:
    """Read content from a URL with fallback chain: Firecrawl → Jina → Trafilatura → raw HTTP.

    Args:
        url: The URL to read.
        max_length: Maximum content length in characters.
        start_index: Character offset to start from (for pagination).
        extract_mode: article (main content), full (everything), raw (no processing).

    Returns:
        Content dict or error dict.
    """
    effective_max = min(max_length, MAX_CONTENT_LENGTH)

    for read_fn, name in [
        (_read_firecrawl, "Firecrawl"),
        (_read_jina, "Jina"),
        (_read_trafilatura, "Trafilatura"),
        (_read_raw_http, "raw HTTP"),
    ]:
        log(f"Trying {name} for URL: {url[:80]}...")
        result = await read_fn(url, effective_max + start_index)
        if result and result.get("content"):
            # Apply start_index offset
            if start_index > 0:
                full_content = result["content"]
                result["content"] = full_content[start_index : start_index + effective_max]
                result["start_index"] = start_index

            log(f"  → {name} extracted {len(result['content'])} chars")
            return result

    return {
        "content": "",
        "error": f"Failed to extract content from {url}. All extraction methods failed (Firecrawl, Jina, Trafilatura, raw HTTP).",
        "api_used": "none",
    }
