# Deep Research Plugin

A Claude Code plugin providing `/research` — deep, multi-step research with parallel agents, citation tracing, dialectical synthesis, and council debate.

## Architecture

**Plugin type:** User-level Claude Code plugin
**MCP server:** `server/research_mcp_server.py` — Python, FastMCP, stdio transport
**Runtime:** `py` launcher on Windows, `python3` on Unix

## File Map

```
commands/research.md          — Orchestrator command (the pipeline)
agents/research-*.md          — Research phase agents (planner, searcher, etc.)
agents/council-*.md           — Council debate agents (5 total)
server/research_mcp_server.py — MCP server with 15 tools
server/session.py             — ResearchContext, source registry, provenance
server/apis/search.py         — Web search fallback chain (Tavily/Exa/Serper/Brave)
server/apis/content.py        — Content extraction chain (Firecrawl/Jina/Trafilatura/raw)
server/apis/academic.py       — Academic APIs (Semantic Scholar/OpenAlex/arXiv/PubMed)
server/apis/news.py           — News APIs (GDELT/NewsAPI)
server/apis/specialized.py    — Domain APIs (FRED/SEC EDGAR/USPTO/Wolfram)
server/apis/utility.py        — Utility APIs (Wikipedia/Internet Archive)
server/dashboard_server.py    — Live browser dashboard (HTTP+SSE)
server/dashboard/index.html   — Dashboard SPA (self-contained)
skills/research-methodology/  — SKILL.md + domain presets + depth configs
```

## Key Patterns

- All Python APIs use `httpx` async with fallback chains
- All logging goes to stderr (stdout = MCP protocol)
- Agent prompts use 5-section structure: LENS → TASK → CONSTRAINTS → CONTEXT → OUTPUT
- Agent output format: `<reasoning>` XML + `<findings>` JSON
- `ResearchContext` is session-scoped state living in MCP server lifespan
- Source quality scoring: 5-factor weighted composite (domain_tier, citation_impact, recency, author, venue)
- Confidence levels follow ICD 203 (Very Low → Very High)

## Development

```bash
# Install deps
py -m pip install -r server/requirements.txt

# Test MCP server
py server/research_mcp_server.py

# Run setup script
bash scripts/init-research-dir.sh
```
