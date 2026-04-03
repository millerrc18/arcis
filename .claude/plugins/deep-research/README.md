# Deep Research Plugin for Claude Code

A Claude Code plugin that enables deep, multi-step research workflows. It decomposes questions into sub-queries, searches web and academic sources in parallel via specialized agents, traces citation chains, synthesizes findings dialectically, runs structured council debates, and produces comprehensive research reports — all from a single `/research` command.

## Quick Start

```bash
# 1. Run the setup script (checks Python, installs deps, validates server)
bash scripts/init-research-dir.sh

# 2. Set at least one search API key (Tavily recommended — free tier: 1K searches/mo)
export TAVILY_API_KEY="your-key-here"

# 3. Install the plugin into Claude Code
#    Symlink this directory into your Claude plugins folder:
ln -s "$(pwd)" ~/.claude/plugins/deep-research

# 4. Start researching
/research "What are current approaches to quantum error correction?"
```

### Manual Setup (if not using the script)

```bash
py -m pip install -r server/requirements.txt
py server/research_mcp_server.py   # verify MCP server starts cleanly
```

## Usage

```
/research <query> [--depth shallow|moderate|deep|exhaustive] [--domain <domain>] [--output <path>]
```

### Depth Levels

| Depth | Agents | Time | What Happens |
|-------|--------|------|-------------|
| `shallow` | 2 | ~1-2 min | 2 search agents, synthesis, report |
| `moderate` | 4+ | ~3-5 min | 4 agents (+ lateral + contrarian), citation tracing, synthesis, 1 refinement round, report |
| `deep` | 6+ | ~8-12 min | 6 agents, tracing, synthesis, 2 refinements, 5-agent council debate, report |
| `exhaustive` | 9+ | ~15-20 min | 9 agents, tracing, synthesis, 3 refinements, council debate, report |

Default depth is `moderate`.

### Domain Presets

Domain presets tune search strategies, source priorities, recency weighting, and report templates for specific fields:

| Domain | Description |
|--------|-------------|
| `general` | Default — balanced across all source types |
| `trading` | Financial markets, quantitative strategies, SEC filings |
| `aerospace-engineering` | Materials, structures, propulsion, airworthiness |
| `defense-regulatory` | DFARS, ITAR, CMMC, DoD acquisition |
| `supply-chain` | Logistics, procurement, vendor management |
| `manufacturing-quality` | Process control, inspection, lean/six sigma |
| `cybersecurity-compliance` | NIST, CMMC, FedRAMP, threat intelligence |
| `software-ai` | Software engineering, ML/AI, architecture |
| `project-management` | Earned value, scheduling, risk management |
| `academic-scientific` | Pure research, peer-reviewed literature |
| `market-intelligence` | Competitive analysis, market sizing, trends |
| `medical-health` | Clinical research, FDA, evidence-based medicine |

### Examples

```bash
# Quick lookup
/research "What is the current CMMC Level 2 timeline?" --depth shallow --domain cybersecurity-compliance

# Standard research (default: moderate depth)
/research "Compare phased array UT vs conventional UT for titanium weld inspection"

# Deep investigation with council debate
/research "Best approaches to real-time defect prediction in aerospace manufacturing" --depth deep --domain manufacturing-quality

# Exhaustive decision-grade research
/research "Should we build a mean reversion strategy using Connors RSI(2) for US equities?" --depth exhaustive --domain trading
```

## How It Works

### Architecture

The plugin has three layers:

1. **Orchestrator** (`commands/research.md`) — the `/research` command that drives the entire pipeline
2. **Agents** (`agents/`) — specialized subagents dispatched by the orchestrator for parallel research tasks
3. **MCP Server** (`server/`) — a Python FastMCP server providing 15 tools that agents call for search, reading, and session management

### Research Pipeline

```
Query → Classification Gate → Decomposition (Planner) → Parallel Search (Searchers)
    → Citation Tracing → Synthesis → Refinement Rounds → Council Debate → Report
```

**Phase 0 — Classification:** Screens the query against ITAR/CUI/EAR keyword patterns. Blocked queries require explicit user confirmation before external API calls are made.

**Phase 1 — Decomposition:** The planner agent breaks the query into direct questions, lateral/cross-domain questions, and contrarian angles, each tagged with temporal requirements (current vs. historical vs. foundational).

**Phase 2 — Parallel Search:** Multiple searcher agents run simultaneously, each handling a subset of sub-questions. They search web, academic, news, and specialized sources, read and extract content, and register quality-scored sources into the shared session.

**Phase 3 — Citation Tracing:** The tracer agent follows citation chains from high-value papers — finding references, related works, and seminal sources that search alone wouldn't surface.

**Phase 4 — Synthesis:** The synthesizer agent produces a dialectical analysis (Thesis/Antithesis/Synthesis) with ICD 203 confidence calibration (Very Low through Very High).

**Phase 5 — Refinement:** Refiner agents identify gaps in coverage and run targeted searches to fill them. Adaptive stopping kicks in when novelty drops below threshold.

**Phase 6 — Council Debate** (deep/exhaustive only): Five agents with assigned roles (Synthesizer, Skeptic, Practitioner, Contrarian, Arbiter) conduct a 3-round Modified Delphi debate with structural anti-sycophancy interventions. The Arbiter produces a BLUF assessment with minority reports.

### MCP Tools (15 total)

| Tool | Purpose |
|------|---------|
| `search_web` | Web search with 4-engine fallback (Tavily → Exa → Serper → Brave) |
| `search_academic` | Academic search with 4-source fallback (Semantic Scholar → OpenAlex → arXiv → PubMed) |
| `read_url` | Content extraction with 4-method fallback (Firecrawl → Jina → Trafilatura → raw HTTP) |
| `search_and_read` | Combined search + read of top results |
| `search_news` | News search (GDELT → NewsAPI) |
| `search_patents` | USPTO PatentsView patent search |
| `resolve_doi` | DOI resolution via CrossRef + Unpaywall open access lookup |
| `follow_citations` | Get papers citing a given paper |
| `find_related` | Find related papers by content similarity |
| `batch_read` | Read multiple URLs in parallel |
| `register_source` | Register a source with quality scoring into the session |
| `get_research_context` | Retrieve session state (sources, searches, provenance) |
| `get_cached_content` | Retrieve previously-read content from cache |
| `set_domain` | Set domain preset for the session |
| `get_dashboard_url` | Get the live dashboard URL |

### Source Quality Scoring

Every registered source gets a composite quality score (0.0–1.0) from five weighted factors:

| Factor | Weight | Description |
|--------|--------|-------------|
| Domain tier | 0.30 | URL-based credibility (authoritative → general) |
| Citation impact | 0.25 | Normalized citation count (log scale) |
| Recency | 0.20 | Age decay with domain-specific half-lives |
| Author credibility | 0.15 | Author reputation score (when available) |
| Venue tier | 0.10 | Publication venue prestige |

### Live Dashboard

At `deep` and `exhaustive` depth, a live browser dashboard opens automatically showing:
- Research phase progression
- Source discovery feed with quality scores
- Findings stream
- Force-directed citation graph
- API usage statistics

The dashboard uses Server-Sent Events for real-time updates and runs on a random localhost port.

## API Keys

The plugin uses multiple search and content APIs with automatic fallback chains. If one API is unavailable or rate-limited, the next one is tried.

### Tier 1: Core (free tiers available)
- `TAVILY_API_KEY` — AI-optimized web search (free 1K/mo, **recommended**)
- `EXA_API_KEY` — Semantic/neural search (free 1K/mo)
- `FIRECRAWL_API_KEY` — Content extraction with JS rendering (free 500/mo)

### Tier 2: Complements
- `SERPER_API_KEY` — Google search results
- `BRAVE_API_KEY` — Independent search index (free 2K/mo)
- `NEWSAPI_KEY` — News search

### Tier 3: Specialized
- `WOLFRAM_APP_ID` — Computational answers
- `SERPAPI_KEY` — Google Scholar

### Always Free (no key needed)
Semantic Scholar, OpenAlex, CrossRef, Unpaywall, arXiv, PubMed, GDELT, FRED, SEC EDGAR, USPTO PatentsView, Wikipedia, Internet Archive Wayback Machine

**Minimum cost:** $0/month — free tiers and keyless APIs are sufficient for light use.
**Recommended:** Tavily + Exa + Firecrawl paid tiers (~$70-90/month) for regular use.

## Output

Reports are written to `docs/research/YYYY-MM-DD-<slug>.md` by default (override with `--output`). Each report includes:

- **Executive Summary** with ICD 203 confidence level
- **Dialectical Analysis:** Thesis → Antithesis → Synthesis
- **Cross-Domain Connections** from lateral search
- **Counter-Evidence and Risks** from contrarian analysis
- **Source Chain** — primary sources traced through citations
- **Decision Implications** — concrete recommended actions
- **Council Debate Transcript** (deep/exhaustive only) with minority reports
- **Source List** with quality scores and provenance
- **Research Metadata** — APIs used, timing, token costs

## Project Structure

```
deep-research/
├── .claude-plugin/
│   └── plugin.json              # Plugin manifest
├── .mcp.json                    # MCP server configuration
├── commands/
│   └── research.md              # /research orchestrator command
├── agents/
│   ├── research-planner.md      # Question decomposition (opus)
│   ├── research-searcher.md     # Parallel search execution (sonnet)
│   ├── research-synthesizer.md  # Dialectical synthesis (opus)
│   ├── research-lateral.md      # Cross-domain connections (sonnet)
│   ├── research-contrarian.md   # Devil's advocate analysis (sonnet)
│   ├── research-tracer.md       # Citation chain following (sonnet)
│   ├── research-refiner.md      # Gap-filling refinement (sonnet)
│   ├── council-synthesizer.md   # Council: integrator (sonnet)
│   ├── council-skeptic.md       # Council: epistemologist (sonnet)
│   ├── council-practitioner.md  # Council: implementer (sonnet)
│   ├── council-contrarian.md    # Council: adversary (sonnet)
│   └── council-arbiter.md       # Council: meta-cognizer (opus)
├── skills/
│   └── research-methodology/
│       ├── SKILL.md             # Auto-triggered methodology knowledge
│       └── references/
│           ├── depth-configs/   # Depth level configurations
│           ├── domains/         # 12 domain preset files
│           ├── report-templates/# Report format templates
│           └── classification-blocklist.md
├── server/
│   ├── research_mcp_server.py   # FastMCP server (15 tools)
│   ├── session.py               # ResearchContext, quality scoring, provenance
│   ├── dashboard_server.py      # Live SSE dashboard server
│   ├── dashboard/
│   │   └── index.html           # Dashboard SPA (self-contained)
│   ├── apis/
│   │   ├── search.py            # Web search fallback chain
│   │   ├── content.py           # Content extraction fallback chain
│   │   ├── academic.py          # Academic API integrations
│   │   ├── news.py              # News API integrations
│   │   ├── specialized.py       # FRED, SEC, USPTO, Wolfram
│   │   └── utility.py           # Wikipedia, Wayback Machine
│   ├── tests/
│   │   ├── test_session.py      # 63 tests: quality scoring, provenance, events
│   │   ├── test_api_search.py   # 11 tests: search fallback chain
│   │   ├── test_api_content.py  # 11 tests: content extraction chain
│   │   ├── test_api_academic.py #  8 tests: academic APIs
│   │   └── test_mcp_tools.py    # 11 tests: imports and tool registration
│   └── requirements.txt
├── scripts/
│   └── init-research-dir.sh     # Setup and validation script
├── pytest.ini
├── CLAUDE.md                    # Developer context
└── README.md                    # This file
```

## Development

### Running Tests

```bash
cd deep-research
py -m pytest -v                  # run all 103 tests
py -m pytest server/tests/test_session.py -v   # just session tests
py -m pytest -k "fallback" -v    # tests matching a pattern
```

### Testing the MCP Server

```bash
py server/research_mcp_server.py   # should start without errors on stdio
```

### Dependencies

```bash
py -m pip install -r server/requirements.txt
```

Core dependencies: `mcp`, `httpx`, `trafilatura`, `starlette`, `uvicorn`
Test dependencies: `pytest`, `pytest-asyncio`

## Data Classification

The plugin includes an ITAR/CUI/EAR classification gate that screens queries before making external API calls. Queries touching controlled technical data (specific weapons systems, export-controlled specifications, classified program names) are blocked and require explicit user confirmation before any external search is executed.

## License

Internal tool — not for distribution.
