"""Deep Research MCP Server.

Provides research tools to Claude Code agents for web search, academic search,
content extraction, citation tracing, source registration, and session context management.

Transport: stdio (one server process per Claude Code session).
All logging goes to stderr (stdout is reserved for MCP protocol).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from contextlib import asynccontextmanager
from typing import Any

# Ensure the server package is importable
_project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_project_root))

# Load .env file from project root if present
from dotenv import load_dotenv
load_dotenv(_project_root / ".env")

from mcp.server.fastmcp import FastMCP

from server.session import ResearchContext, log
from server.apis import search as search_api
from server.apis import content as content_api

# Lazy imports for optional API modules
_academic_api = None
_news_api = None
_specialized_api = None
_dashboard_server = None


def _get_academic():
    global _academic_api
    if _academic_api is None:
        from server.apis import academic as _mod
        _academic_api = _mod
    return _academic_api


def _get_news():
    global _news_api
    if _news_api is None:
        from server.apis import news as _mod
        _news_api = _mod
    return _news_api


def _get_specialized():
    global _specialized_api
    if _specialized_api is None:
        from server.apis import specialized as _mod
        _specialized_api = _mod
    return _specialized_api


# Dashboard state
_dashboard = None


@asynccontextmanager
async def lifespan(server: FastMCP):
    """Initialize ResearchContext as session-scoped state."""
    log("Starting deep-research MCP server...")
    ctx = ResearchContext()

    # Try to start the dashboard server
    global _dashboard
    try:
        from server.dashboard_server import start_dashboard
        _dashboard = await start_dashboard(ctx)
        log(f"Dashboard available at {_dashboard.url}")
    except Exception as e:
        log(f"Dashboard not available: {e}")
        _dashboard = None

    try:
        yield ctx
    finally:
        source_count = len(ctx.source_registry)
        search_count = len(ctx.search_history)
        log(f"Shutting down. Session stats: {source_count} sources, {search_count} searches")


mcp = FastMCP("deep-research", lifespan=lifespan)


def _get_state(ctx) -> ResearchContext:
    """Extract ResearchContext from MCP context."""
    return ctx.request_context.lifespan_context


# ╔══════════════════════════════════════════════════════════════════╗
# ║  Core Tools (10)                                                ║
# ╚══════════════════════════════════════════════════════════════════╝

# --- Tool 1: search_web ---

@mcp.tool()
async def search_web(
    ctx,
    query: str,
    max_results: int = 10,
    freshness: str = "any",
    detail_level: str = "summaries",
    exclude_urls: str = "",
) -> str:
    """Search the web using AI-optimized search engines with automatic fallback.

    Uses Tavily → Exa → Serper → Brave fallback chain.

    Args:
        query: Search query string.
        max_results: Maximum results to return (default 10, max 20).
        freshness: Time filter — any/day/week/month/year.
        detail_level: snippets (brief), summaries (default), or full (complete content).
        exclude_urls: Comma-separated URLs to exclude from results.
    """
    state = _get_state(ctx)
    max_results = min(max_results, 20)

    exclude_list = [u.strip() for u in exclude_urls.split(",") if u.strip()] if exclude_urls else []
    exclude_list.extend(state.get_registered_urls())

    result = await search_api.search_web(
        query=query,
        max_results=max_results,
        freshness=freshness,
        detail_level=detail_level,
        exclude_urls=exclude_list,
    )

    top_urls = [r["url"] for r in result.get("results", [])[:5]]
    state.record_search(
        query=query,
        engine=result.get("api_used", "unknown"),
        result_count=result.get("total_count", 0),
        top_urls=top_urls,
    )

    return json.dumps(result, indent=2)


# --- Tool 2: search_academic ---

@mcp.tool()
async def search_academic(
    ctx,
    query: str,
    max_results: int = 10,
    year_range: str = "",
    fields_of_study: str = "",
    min_citations: int = 0,
    detail_level: str = "summaries",
) -> str:
    """Search academic databases for papers, preprints, and scholarly articles.

    Uses Semantic Scholar → OpenAlex → arXiv → PubMed fallback chain. All free APIs.

    Args:
        query: Academic search query.
        max_results: Maximum results (default 10, max 20).
        year_range: Filter by year range, e.g. "2020-2024" or "2020-" for 2020+.
        fields_of_study: Comma-separated fields, e.g. "Computer Science,Medicine".
        min_citations: Minimum citation count filter.
        detail_level: snippets/summaries/full.
    """
    state = _get_state(ctx)
    max_results = min(max_results, 20)

    yr = None
    if year_range:
        yr = year_range

    fos = None
    if fields_of_study:
        fos = [f.strip() for f in fields_of_study.split(",") if f.strip()]

    academic = _get_academic()
    result = await academic.search_academic(
        query=query,
        max_results=max_results,
        year_range=yr,
        fields_of_study=fos,
        min_citations=min_citations,
        detail_level=detail_level,
    )

    top_urls = [r["url"] for r in result.get("results", [])[:5]]
    state.record_search(
        query=query,
        engine=result.get("api_used", "unknown"),
        result_count=result.get("total_count", 0),
        top_urls=top_urls,
    )

    return json.dumps(result, indent=2)


# --- Tool 3: read_url ---

@mcp.tool()
async def read_url(
    ctx,
    url: str,
    max_length: int = 5000,
    start_index: int = 0,
    extract_mode: str = "article",
) -> str:
    """Read and extract content from a URL.

    Uses Firecrawl → Jina → Trafilatura → raw HTTP fallback chain.

    Args:
        url: The URL to read.
        max_length: Maximum content length in characters (default 5000, max 50000).
        start_index: Character offset for pagination (default 0).
        extract_mode: article (main content only), full (everything), raw (minimal processing).
    """
    state = _get_state(ctx)

    # Check cache first
    cached = state.get_cached_content(url)
    if cached:
        content = cached[start_index:start_index + max_length]
        return json.dumps({
            "content": content,
            "full_length": len(cached),
            "truncated": len(cached) > start_index + max_length,
            "api_used": "cache",
        }, indent=2)

    max_length = min(max_length, 50000)
    result = await content_api.read_url(
        url=url,
        max_length=max_length,
        start_index=start_index,
        extract_mode=extract_mode,
    )

    # Cache the content
    if result.get("content"):
        state.content_cache[url.rstrip("/")] = result["content"]

    return json.dumps(result, indent=2)


# --- Tool 4: search_and_read ---

@mcp.tool()
async def search_and_read(
    ctx,
    query: str,
    num_results_to_read: int = 3,
    search_source: str = "web",
    detail_level: str = "summaries",
) -> str:
    """Search and automatically read the top results. Saves tool-call round-trips.

    Combines search + read in a single call.

    Args:
        query: Search query string.
        num_results_to_read: How many top results to read (default 3, max 5).
        search_source: web, academic, or both (default: web).
        detail_level: snippets/summaries/full for search results.
    """
    state = _get_state(ctx)
    num_results_to_read = min(num_results_to_read, 5)

    exclude_list = state.get_registered_urls()

    # Search
    if search_source == "academic":
        academic = _get_academic()
        search_result = await academic.search_academic(
            query=query,
            max_results=num_results_to_read + 2,
            detail_level=detail_level,
        )
    else:
        search_result = await search_api.search_web(
            query=query,
            max_results=num_results_to_read + 2,
            detail_level=detail_level,
            exclude_urls=exclude_list,
        )

    state.record_search(
        query=query,
        engine=search_result.get("api_used", "unknown"),
        result_count=search_result.get("total_count", 0),
        top_urls=[r["url"] for r in search_result.get("results", [])[:5]],
    )

    # Read top results
    combined_results = []
    for sr in search_result.get("results", [])[:num_results_to_read]:
        url = sr.get("url", "")
        if not url:
            continue

        content_result = await content_api.read_url(url=url, max_length=3000)
        combined = {
            **sr,
            "content": content_result.get("content", ""),
            "content_api": content_result.get("api_used", ""),
            "content_length": len(content_result.get("content", "")),
        }
        combined_results.append(combined)

        # Cache content
        if content_result.get("content"):
            state.content_cache[url.rstrip("/")] = content_result["content"]

    output = {
        "query": query,
        "search_api": search_result.get("api_used", "unknown"),
        "results_found": search_result.get("total_count", 0),
        "results_read": len(combined_results),
        "results": combined_results,
    }

    return json.dumps(output, indent=2)


# --- Tool 5: register_source ---

@mcp.tool()
async def register_source(
    ctx,
    url: str,
    title: str,
    source_type: str = "web",
    relevance_note: str = "",
    quality_rating: int = 3,
    author: str = "",
    date: str = "",
    citation_count: int = 0,
) -> str:
    """Register a discovered source in the research session's source registry.

    Deduplicates by URL. Returns quality score and duplicate status.
    Register every valuable source you find — these form the citation list.

    Args:
        url: Source URL (required).
        title: Source title (required).
        source_type: web, academic, report, spec, or news (default: web).
        relevance_note: Brief note on why this source matters.
        quality_rating: Your assessment of quality, 1-5 (default: 3).
        author: Author name(s) if known.
        date: Publication date (YYYY-MM-DD or YYYY) if known.
        citation_count: Academic citation count if known.
    """
    state = _get_state(ctx)
    result = state.register_source(
        url=url,
        title=title,
        source_type=source_type,
        relevance_note=relevance_note,
        quality_rating=quality_rating,
        author=author,
        date=date,
        citation_count=citation_count,
    )
    return json.dumps(result, indent=2)


# --- Tool 6: get_research_context ---

@mcp.tool()
async def get_research_context(
    ctx,
    section: str = "all",
) -> str:
    """Get the current research session context — sources, searches, citations, and stats.

    Use this to understand what has been found so far before synthesizing.

    Args:
        section: Which part — sources, searches, citations, provenance, findings, or all (default).
    """
    state = _get_state(ctx)
    result = state.get_context(section=section)
    return json.dumps(result, indent=2)


# --- Tool 7: set_domain ---

@mcp.tool()
async def set_domain(
    ctx,
    domain: str,
    custom_preferred_domains: str = "",
) -> str:
    """Set the research domain preset for this session.

    Controls source ranking preferences and search term expansion.

    Args:
        domain: Domain preset name — general, trading, aerospace-engineering,
                software-ai, manufacturing-quality, defense-regulatory, supply-chain,
                cybersecurity-compliance, project-management, academic-scientific,
                market-intelligence, or medical-health.
        custom_preferred_domains: Optional comma-separated preferred web domains.
    """
    state = _get_state(ctx)
    preferred = [d.strip() for d in custom_preferred_domains.split(",") if d.strip()] if custom_preferred_domains else []
    result = state.set_domain(domain=domain, preferred_sources=preferred)
    return json.dumps(result, indent=2)


# --- Tool 8: follow_citations ---

@mcp.tool()
async def follow_citations(
    ctx,
    paper_id: str,
    direction: str = "both",
    max_depth: int = 1,
    max_results: int = 20,
) -> str:
    """Follow citation chains from a paper to discover related works.

    Uses Semantic Scholar citation graph. The paper_id can be a DOI,
    arXiv ID, or Semantic Scholar paper ID.

    Args:
        paper_id: Paper identifier (DOI, arXiv ID, or Semantic Scholar ID).
        direction: cited_by (who cites this), references (what this cites), or both.
        max_depth: How many hops to follow (1 or 2, default 1).
        max_results: Maximum papers per direction (default 20).
    """
    state = _get_state(ctx)
    max_depth = min(max_depth, 2)
    max_results = min(max_results, 50)

    academic = _get_academic()
    result = await academic.get_paper_citations(
        paper_id=paper_id,
        direction=direction,
        max_results=max_results,
    )

    # Update citation graph
    if result.get("cited_by"):
        state.update_citation_graph(paper_id, cited_by=[p.get("paperId", "") for p in result["cited_by"]])
    if result.get("references"):
        state.update_citation_graph(paper_id, references=[p.get("paperId", "") for p in result["references"]])

    # Add provenance
    state.add_provenance(
        event_type="follow_citation",
        metadata={"paper_id": paper_id, "direction": direction, "depth": max_depth},
        outputs=[p.get("paperId", "") for p in result.get("cited_by", []) + result.get("references", [])],
    )

    return json.dumps(result, indent=2)


# --- Tool 9: find_related ---

@mcp.tool()
async def find_related(
    ctx,
    source_ids: str,
    relationship: str = "similar",
    max_results: int = 10,
) -> str:
    """Find papers or sources related to a set of known sources.

    Uses Semantic Scholar recommendations and Exa find_similar.

    Args:
        source_ids: Comma-separated list of DOIs, URLs, or paper IDs.
        relationship: similar, contrasting, or building_on (default: similar).
        max_results: Maximum results (default 10).
    """
    state = _get_state(ctx)
    ids = [s.strip() for s in source_ids.split(",") if s.strip()]

    # Use Semantic Scholar recommendations for the first ID
    academic = _get_academic()
    all_results = []

    for sid in ids[:3]:  # Limit to first 3 to avoid rate limits
        try:
            result = await academic.get_paper_citations(
                paper_id=sid,
                direction="references",
                max_results=max_results,
            )
            if result.get("references"):
                all_results.extend(result["references"][:max_results])
        except Exception as e:
            log(f"find_related error for {sid}: {e}")

    # Deduplicate by paperId
    seen = set()
    unique = []
    for r in all_results:
        pid = r.get("paperId", r.get("url", ""))
        if pid and pid not in seen:
            seen.add(pid)
            unique.append(r)

    return json.dumps({
        "source_ids": ids,
        "relationship": relationship,
        "related": unique[:max_results],
        "count": len(unique[:max_results]),
    }, indent=2)


# --- Tool 10: resolve_doi ---

@mcp.tool()
async def resolve_doi(
    ctx,
    doi: str,
) -> str:
    """Resolve a DOI to full metadata and open access PDF link.

    Uses CrossRef for metadata and Unpaywall for open access resolution.

    Args:
        doi: The DOI to resolve (e.g., "10.1038/s41586-024-07421-0").
    """
    academic = _get_academic()
    result = await academic.resolve_doi(doi)
    return json.dumps(result, indent=2)


# ╔══════════════════════════════════════════════════════════════════╗
# ║  Extended Tools (5)                                             ║
# ╚══════════════════════════════════════════════════════════════════╝

# --- Tool 11: search_news ---

@mcp.tool()
async def search_news(
    ctx,
    query: str,
    max_results: int = 10,
    freshness: str = "week",
) -> str:
    """Search for recent news articles on a topic.

    Uses GDELT (free) → NewsAPI (key required) fallback.

    Args:
        query: News search query.
        max_results: Maximum results (default 10).
        freshness: Time range — day/week/month (default: week).
    """
    state = _get_state(ctx)
    news = _get_news()
    result = await news.search_news(
        query=query,
        max_results=max_results,
        freshness=freshness,
    )

    top_urls = [r["url"] for r in result.get("results", [])[:5]]
    state.record_search(
        query=query,
        engine=result.get("api_used", "news"),
        result_count=result.get("total_count", 0),
        top_urls=top_urls,
    )

    return json.dumps(result, indent=2)


# --- Tool 12: batch_read ---

@mcp.tool()
async def batch_read(
    ctx,
    urls: str,
    max_length_per_url: int = 3000,
) -> str:
    """Read content from multiple URLs in parallel.

    Extracts content from each URL concurrently for efficiency.

    Args:
        urls: Comma-separated list of URLs to read.
        max_length_per_url: Max characters per URL (default 3000).
    """
    import asyncio

    state = _get_state(ctx)
    url_list = [u.strip() for u in urls.split(",") if u.strip()][:10]  # Max 10

    async def read_one(url: str) -> dict[str, Any]:
        # Check cache first
        cached = state.get_cached_content(url)
        if cached:
            return {"url": url, "content": cached[:max_length_per_url], "api_used": "cache"}
        result = await content_api.read_url(url=url, max_length=max_length_per_url)
        if result.get("content"):
            state.content_cache[url.rstrip("/")] = result["content"]
        return {"url": url, **result}

    results = await asyncio.gather(*[read_one(u) for u in url_list], return_exceptions=True)

    output = []
    for r in results:
        if isinstance(r, Exception):
            output.append({"url": "unknown", "error": str(r)})
        else:
            output.append(r)

    return json.dumps({"results": output, "count": len(output)}, indent=2)


# --- Tool 13: search_patents ---

@mcp.tool()
async def search_patents(
    ctx,
    query: str,
    max_results: int = 10,
) -> str:
    """Search for patents by query using USPTO PatentsView API.

    Args:
        query: Patent search query.
        max_results: Maximum results (default 10).
    """
    state = _get_state(ctx)
    specialized = _get_specialized()
    result = await specialized.search_patents(query=query, max_results=max_results)

    state.record_search(
        query=query,
        engine="uspto",
        result_count=len(result.get("results", [])),
    )

    return json.dumps(result, indent=2)


# --- Tool 14: get_cached_content ---

@mcp.tool()
async def get_cached_content(
    ctx,
    url: str,
) -> str:
    """Retrieve previously cached content for a URL without re-fetching.

    Use this to re-read content from a source that was already fetched.

    Args:
        url: The URL to retrieve cached content for.
    """
    state = _get_state(ctx)
    content = state.get_cached_content(url)
    if content:
        return json.dumps({"url": url, "content": content, "cached": True}, indent=2)
    return json.dumps({"url": url, "error": "No cached content for this URL. Use read_url to fetch it.", "cached": False}, indent=2)


# --- Tool 15: get_dashboard_url ---

@mcp.tool()
async def get_dashboard_url(ctx) -> str:
    """Get the URL where the live research dashboard is running.

    Open this URL in a browser to see real-time research progress.
    """
    if _dashboard and hasattr(_dashboard, "url"):
        return json.dumps({"url": _dashboard.url, "available": True}, indent=2)
    return json.dumps({"available": False, "message": "Dashboard is not running."}, indent=2)


if __name__ == "__main__":
    log("Launching deep-research MCP server on stdio transport")
    mcp.run(transport="stdio")
