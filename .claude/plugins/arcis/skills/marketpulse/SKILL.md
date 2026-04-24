---
name: marketpulse
description: Pull, cache, and analyze minute-by-minute stock market data from Polygon.io. Use when the user asks about stock prices, market data, index movements, intraday patterns, volatility, correlations, sector analysis, or market event impact.
---

# MarketPulse

Pull, cache, and analyze minute-by-minute stock market data from Polygon.io.

## When to Use

Activate this skill when the user asks about:
- Stock prices, market data, tickers, indices (S&P 500, Dow 30, Nasdaq 100, etc.)
- Historical market events and their price impact
- Intraday patterns, volatility, volume analysis
- Correlation between stocks or sectors
- Market data export (Excel, CSV, Parquet)

## MCP Tools Available

The following tools are available via the `marketpulse` MCP server (prefixed `mcp__marketpulse__`):
- `mp_pull_bars` -- Fetch and cache bar data for tickers/indices
- `mp_job_status` -- Check progress of a data pull job
- `mp_resume_job` -- Resume a paused/failed pull job
- `mp_query_bars` -- Query cached bar data
- `mp_cache_status` -- Show what data is cached

## Data Notes

- Data provider: Polygon.io Starter plan (5 years of history, 15-min delay)
- Data is cached locally in `~/.marketpulse/` as partitioned Parquet files
- First pull of a ticker/date range hits the API; subsequent pulls are instant from cache
- Large pulls (e.g., full S&P 500) are tracked as resumable jobs
