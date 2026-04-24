# MarketPulse Design Spec

**Date:** 2026-04-23
**Status:** Draft (Iteration 3 — final)
**Author:** Ryan Miller + Claude

## 1. Overview

MarketPulse is a skill within the **ARCIS plugin** for pulling, caching, and analyzing minute-by-minute stock market data from Polygon.io (Massive.com). It adds a dedicated MCP server to ARCIS and exposes both a `/arcis:marketpulse` skill command and a standalone CLI.

**Primary use cases:**
- Historical event analysis (how did markets react to specific events on specific dates)
- Intraday pattern research (recurring behaviors, correlations, volatility clustering)
- Portfolio/risk modeling (feed high-frequency data into Monte Carlo, VaR, etc.)
- Reporting and visualization (charts, dashboards, Excel exports)

**Data provider:** Polygon.io Starter plan ($29/mo) — 5 years of history, unlimited API calls, 15-min delayed data. Can upgrade to Developer ($79/mo, 10yr) or Advanced ($199/mo, 20yr+) for deeper history without code changes.

**Host plugin:** ARCIS (`C:\Users\ryan.c.miller\OneDrive - General Dynamics Mission Systems\04 - Computer\Desktop\arcis`)

## 2. Architecture

MarketPulse follows the ARCIS skill pattern — `SKILL.md` + `commands/` + `agents/` — but adds a dedicated MCP server and a Python core library for data fetching, caching, and analytics.

```
┌───────────────────────────────────────────────────────┐
│  ARCIS Plugin                                         │
│                                                       │
│  ┌─────────────┐ ┌─────────────┐ ┌─────────────────┐ │
│  │ research-   │ │ coding-     │ │ marketpulse     │ │
│  │ team        │ │ team        │ │ (NEW)           │ │
│  │ SKILL.md    │ │ SKILL.md    │ │ SKILL.md        │ │
│  │ agents/     │ │ agents/     │ │ commands/       │ │
│  │ commands/   │ │ commands/   │ │ lib/            │ │
│  └──────┬──────┘ └──────┬──────┘ └──────┬──────────┘ │
│         │               │               │            │
│  ┌──────▼──────┐        │        ┌──────▼──────────┐ │
│  │ deep-       │        │        │ marketpulse     │ │
│  │ research    │        │        │ MCP server      │ │
│  │ MCP server  │        │        │ (NEW)           │ │
│  └─────────────┘        │        └──────┬──────────┘ │
│                         │               │            │
│  ┌──────────────────────┘               │            │
│  │  shared/                             │            │
│  │  (schemas, references)               │            │
│  └──────────────────────────────────────┘            │
└───────────────────────────────────────────────────────┘
                                          │
                              ┌───────────▼───────────┐
                              │   SQLite Database      │
                              │   (user data dir)      │
                              └───────────────────────┘
```

The core library is self-contained Python under `skills/marketpulse/lib/`. The MCP server at `server/marketpulse_mcp_server.py` wraps the library. The CLI entry point is `skills/marketpulse/lib/cli.py`.

## 3. Integration into ARCIS

### 3.1 File Layout within ARCIS

```
arcis/
├── .claude-plugin/
│   └── plugin.json          # (existing) — update description
├── .mcp.json                # (existing) — add marketpulse server entry
├── server/
│   ├── research_mcp_server.py  # (existing)
│   └── marketpulse_mcp_server.py  # NEW — MarketPulse MCP server
├── shared/                  # (existing)
├── skills/
│   ├── research-team/       # (existing)
│   ├── coding-team/         # (existing)
│   ├── roast-me/            # (existing)
│   └── marketpulse/         # NEW
│       ├── SKILL.md         # Skill definition + trigger description
│       ├── commands/
│       │   └── marketpulse.md   # Orchestrator command prompt
│       ├── lib/
│       │   ├── __init__.py
│       │   ├── client.py        # Polygon.io API client
│       │   ├── models.py        # SQLAlchemy models (metadata SQLite)
│       │   ├── db.py            # DuckDB + SQLite engine, session factory
│       │   ├── storage.py       # Parquet read/write, partition management
│       │   ├── cache.py         # Fetch-or-cache logic, coverage tracking
│       │   ├── indices.py       # Index constituent management
│       │   ├── analytics/
│       │   │   ├── __init__.py
│       │   │   ├── summary.py
│       │   │   ├── volatility.py
│       │   │   ├── correlation.py
│       │   │   ├── patterns.py
│       │   │   ├── sectors.py
│       │   │   └── events.py
│       │   ├── export.py        # Excel, CSV, Parquet generation
│       │   └── cli.py           # Typer CLI entry point
│       ├── indices/             # Static index constituent files
│       │   ├── sp100.json
│       │   ├── sp500.json
│       │   ├── dow30.json
│       │   ├── nasdaq100.json
│       │   └── russell2000.json
│       └── references/
│           └── polygon-api-notes.md  # API quirks, limits, field mapping
```

### 3.2 .mcp.json Update

Add the marketpulse MCP server alongside the existing deep-research server:

```json
{
  "mcpServers": {
    "deep-research": {
      "command": "py",
      "args": ["${CLAUDE_PLUGIN_ROOT}/server/research_mcp_server.py"],
      "env": { ... }
    },
    "marketpulse": {
      "command": "py",
      "args": ["${CLAUDE_PLUGIN_ROOT}/server/marketpulse_mcp_server.py"],
      "env": {
        "POLYGON_API_KEY": "${POLYGON_API_KEY}"
      }
    }
  }
}
```

### 3.3 Skill Trigger

The `SKILL.md` will register with this description so Claude auto-invokes it:

```yaml
---
name: marketpulse
description: Pull, cache, and analyze minute-by-minute stock market data from Polygon.io. Use when the user asks about stock prices, market data, index movements, intraday patterns, volatility, correlations, sector analysis, or market event impact.
---
```

### 3.4 Data Storage

Data does NOT live inside the ARCIS plugin directory (which is synced via OneDrive). Instead it lives in a local data directory:

- **Default:** `~/.marketpulse/`
- **Override:** `MARKETPULSE_DATA_DIR` environment variable

This keeps the large data files (potentially multi-GB) out of OneDrive sync and git.

## 4. Data Layer

### 4.1 Storage Architecture: DuckDB + Partitioned Parquet

**Why not SQLite?** At scale (Russell 2000 x 1 year = ~780M minute bars), SQLite's row-store format is catastrophically slow for columnar analytics queries. It also has database-level write locking that would serialize parallel fetches.

**Solution:** Store bar data as **partitioned Parquet files** on disk, queried via **DuckDB** (an embedded columnar OLAP engine). Metadata (tickers, jobs, indices) stays in a small **SQLite** database.

```
~/.marketpulse/
├── bars/                          # Partitioned Parquet files
│   ├── timespan=1min/
│   │   ├── ticker=AAPL/
│   │   │   ├── 2022-06.parquet    # One file per ticker per month
│   │   │   ├── 2022-07.parquet
│   │   │   └── ...
│   │   ├── ticker=MSFT/
│   │   │   └── ...
│   │   └── ...
│   ├── timespan=5min/
│   │   └── ...
│   └── timespan=1day/
│       └── ...
├── metadata.db                    # SQLite for tickers, jobs, index_members
└── custom_lists/                  # User-defined ticker lists
    └── my-watchlist.json
```

**Why this layout:**
- **Columnar (Parquet):** Analytics queries only read needed columns (e.g., `close`, `volume`), not entire rows. 10-50x faster for aggregation.
- **Partitioned by ticker+month:** Each fetcher writes its own file with no lock contention. DuckDB reads the partition tree as a single virtual table.
- **DuckDB for queries:** Embedded, zero-config, vectorized OLAP engine. Queries Parquet directly — no loading step. Orders of magnitude faster than SQLite for cross-ticker analytics.
- **SQLite for metadata:** Small tables (tickers, jobs) where row-store is fine and ACID transactions matter.

### 4.2 Parquet Schema (bars)

Each Parquet file contains bars for one ticker in one month at one timespan:

| Column | Type | Notes |
|--------|------|-------|
| timestamp | TIMESTAMP | UTC timestamp (converted from Polygon's Unix ms) |
| open | FLOAT64 | |
| high | FLOAT64 | |
| low | FLOAT64 | |
| close | FLOAT64 | |
| volume | FLOAT64 | Shares traded |
| vwap | FLOAT64 | Volume-weighted avg price |
| num_transactions | INT32 | Trade count in window |

The ticker, timespan, and month are encoded in the partition path, not repeated in every row. This reduces file size and enables partition pruning.

### 4.3 SQLite Metadata Schema (`metadata.db`)

**`tickers`** — reference data:
| Column | Type | Notes |
|--------|------|-------|
| symbol | TEXT PK | e.g. "AAPL" |
| name | TEXT | "Apple Inc." |
| sector | TEXT | GICS sector |
| industry | TEXT | GICS industry |
| market_cap | REAL | Latest market cap |
| sic_code | TEXT | SIC code |
| updated_at | TEXT | ISO timestamp |

**`index_members`** — index constituent tracking:
| Column | Type | Notes |
|--------|------|-------|
| index_name | TEXT | "SP500", "DOW30", etc. |
| ticker | TEXT | FK to tickers |
| added_date | TEXT | When added to index |
| removed_date | TEXT | NULL if current member |
| **PK** | | (index_name, ticker, added_date) |

**`fetch_jobs`** — batch job tracking for resumability:
| Column | Type | Notes |
|--------|------|-------|
| id | TEXT PK | UUID |
| created_at | TEXT | ISO timestamp |
| index_name | TEXT | NULL for custom ticker lists |
| tickers | TEXT | JSON array of tickers |
| from_date | TEXT | YYYY-MM-DD |
| to_date | TEXT | YYYY-MM-DD |
| timespan | TEXT | "1min", "5min", etc. |
| status | TEXT | "pending", "running", "paused", "completed", "failed" |
| total_tickers | INTEGER | Total tickers to fetch |
| completed_tickers | INTEGER | Tickers finished so far |
| current_ticker | TEXT | Currently fetching |
| error | TEXT | Last error message if failed |

**`coverage`** — tracks which ticker/month/timespan combinations are cached:
| Column | Type | Notes |
|--------|------|-------|
| ticker | TEXT | |
| timespan | TEXT | "1min", "5min", etc. |
| year_month | TEXT | "2022-06" |
| bar_count | INTEGER | Number of bars in the Parquet file |
| fetched_at | TEXT | ISO timestamp |
| **PK** | | (ticker, timespan, year_month) |

### 4.4 Cache Logic

Before any API call, the cache layer checks the `coverage` table:

1. For a requested (ticker, timespan, from_date, to_date), compute which year-month partitions are needed.
2. Check `coverage` table for existing partitions.
3. Only fetch missing months from Polygon.
4. Write each month's data as a new Parquet file. Insert a `coverage` row.
5. If a partition already exists and the request partially overlaps, skip it (month-level granularity — no sub-month gap detection in V1).

This means:
- First pull of "SP500 for June 2022" fetches all 500 tickers from API.
- Second pull of the same request returns instantly (all partitions exist in `coverage`).
- A pull of "SP500 for June-July 2022" only fetches July (June coverage exists).

### 4.5 Querying with DuckDB

DuckDB reads the Parquet partition tree as a virtual table:

```python
import duckdb

conn = duckdb.connect()
df = conn.execute("""
    SELECT timestamp, close, volume
    FROM read_parquet('~/.marketpulse/bars/timespan=1min/ticker=AAPL/*.parquet')
    WHERE timestamp BETWEEN '2022-06-03' AND '2022-06-03'
    ORDER BY timestamp
""").fetchdf()
```

For cross-ticker queries, DuckDB handles the glob:

```python
df = conn.execute("""
    SELECT *
    FROM read_parquet('~/.marketpulse/bars/timespan=1min/ticker=*/2022-06.parquet',
                      hive_partitioning=true)
    WHERE ticker IN ('AAPL', 'MSFT', 'GOOG')
""").fetchdf()
```

DuckDB's partition pruning automatically skips irrelevant files, making large-scale queries fast.

## 5. Polygon.io API Client

### 5.1 Core Client (`lib/client.py`)

Wraps the Polygon REST API with:

- **Token bucket rate limiting**: Uses a token bucket algorithm (via `pyrate-limiter` or custom) rather than a static sleep. Allows bursting while maintaining average rate. Default: 50 calls/second (configurable via `MARKETPULSE_RATE_LIMIT` env var). Respects `Retry-After` headers on 429 responses.
- **Retry with exponential backoff + jitter**: On 429 (rate limit) or 5xx errors, retry up to 5 times with exponential backoff plus random jitter (`base_delay * 2^attempt + random(0, 1s)`). Prevents thundering herd on retry.
- **Date chunking**: The aggregates endpoint has no pagination and a 50,000 result limit (confirmed: no `next_url` for aggregates, unlike other Polygon endpoints). For 1-minute bars, this is ~128 trading days. The client chunks by month to stay safely under the limit.
- **API key management**: Read from environment variable `POLYGON_API_KEY` (passed through `.mcp.json` env block).

**Key methods:**

```python
class PolygonClient:
    async def get_bars(
        self,
        ticker: str,
        timespan: str,       # "minute", "hour", "day"
        multiplier: int,     # 1, 5, 15 for minutes
        from_date: date,
        to_date: date,
    ) -> list[Bar]:
        """Fetch aggregate bars, auto-chunking by month."""

    async def get_ticker_details(self, ticker: str) -> TickerInfo:
        """Fetch reference data for a ticker."""

    async def search_tickers(self, query: str) -> list[TickerInfo]:
        """Search for tickers by name or symbol."""
```

### 5.2 Batch Engine (`lib/cache.py`)

Orchestrates multi-ticker, multi-date-range pulls:

```python
class BatchEngine:
    async def pull(
        self,
        tickers: list[str],
        from_date: date,
        to_date: date,
        timespan: str = "1min",
        job_id: str | None = None,
    ) -> FetchJob:
        """
        Pull bars for multiple tickers over a date range.
        - Creates/resumes a FetchJob for tracking
        - Checks cache for existing coverage per ticker
        - Fetches only gaps
        - Updates job progress after each ticker
        - Returns the completed job with stats
        """

    async def resume(self, job_id: str) -> FetchJob:
        """Resume a paused or failed job from where it left off."""

    def list_jobs(self) -> list[FetchJob]:
        """List all fetch jobs with their status."""
```

**Batch behavior:**
- Creates a `fetch_jobs` row on start.
- Iterates tickers, updating `completed_tickers` and `current_ticker` after each.
- On failure, sets status to "failed" with error message — can be resumed.
- On Ctrl+C / interruption, sets status to "paused" — can be resumed.
- Emits progress events that the MCP server / CLI can display.

**Concurrency:** Uses `asyncio.Semaphore` to run multiple ticker fetches in parallel (default: 10 concurrent). Each ticker fetch is independent, so parallelism is safe and significantly speeds up large pulls.

## 6. Index Constituent Management

### 6.1 Static Index Files

Ship with JSON files for each supported index in `skills/marketpulse/indices/`:

```json
{
  "name": "S&P 100",
  "short_name": "SP100",
  "description": "100 leading U.S. stocks with exchange-listed options",
  "source": "Wikipedia/S&P",
  "last_updated": "2026-04-23",
  "constituents": [
    {"ticker": "AAPL", "name": "Apple Inc.", "sector": "Technology"},
    {"ticker": "MSFT", "name": "Microsoft Corp.", "sector": "Technology"},
    ...
  ]
}
```

### 6.2 Index Management (`lib/indices.py`)

```python
class IndexManager:
    def get_index(self, name: str) -> Index:
        """Load index by short name: SP100, SP500, DOW30, NDX100, RUT2000."""

    def get_tickers(self, name: str) -> list[str]:
        """Return current ticker list for an index."""

    def refresh_index(self, name: str) -> None:
        """Re-scrape constituent list from Wikipedia and update JSON file."""

    def create_custom_list(self, name: str, tickers: list[str]) -> None:
        """Create a custom named ticker list (saved to data dir, not plugin dir)."""

    def list_indices(self) -> list[IndexSummary]:
        """List all available indices with ticker counts."""
```

**Constituent source:** Wikipedia tables for S&P 100, S&P 500, Dow 30, Nasdaq 100. Russell 2000 from the `fja05680/sp500` GitHub dataset. The `refresh_index` command re-scrapes and updates the local JSON files.

### 6.3 Historical Constituents

For accurate historical analysis, knowing who was IN the index on a given past date matters (survivorship bias). The `index_members` table tracks additions/removals with dates.

**V1:** Use current constituents only. The `index_members` table schema exists to support future historical tracking, but V1 does not populate `added_date` / `removed_date` — all current members are inserted with `added_date = NULL` and `removed_date = NULL`. Historical constituent tracking is listed in Future Enhancements.

## 7. Analytics Suite

All analytics functions accept a pandas DataFrame (loaded from SQLite) and return structured results. They are stateless — no side effects, easily testable.

### 7.1 Summary Statistics (`analytics/summary.py`)

```python
def daily_summary(bars_df: DataFrame) -> DailySummary:
    """
    For each ticker on each day:
    - Open, close, high, low, daily return
    - Total volume, VWAP
    - Intraday range (high-low as % of open)
    - Gap from previous close
    """

def biggest_movers(bars_df: DataFrame, n: int = 10) -> MoversReport:
    """
    Top/bottom N tickers by:
    - Daily return (% change open to close)
    - Intraday range
    - Volume vs. average
    """

def volume_analysis(bars_df: DataFrame) -> VolumeReport:
    """
    Per ticker:
    - Volume profile by time-of-day (which minutes have highest volume)
    - Volume relative to 20-day average
    - Unusual volume flags (>2 std devs from mean)
    """
```

### 7.2 Volatility (`analytics/volatility.py`)

```python
def realized_volatility(bars_df: DataFrame, window: int = 20) -> VolSeries:
    """
    Rolling realized volatility from minute returns.
    - Annualized using sqrt(252 * 390) for minute bars
    - Returns time series of vol estimates
    """

def intraday_vol_profile(bars_df: DataFrame) -> VolProfile:
    """
    Average volatility by time-of-day across all days in the dataset.
    Shows the classic U-shape (high vol at open/close, low midday).
    """

def vol_surface(bars_df: DataFrame, windows: list[int]) -> VolSurface:
    """
    Realized vol at multiple lookback windows (5, 10, 20, 60, 120 days).
    Useful for term structure analysis.
    """

def garman_klass_vol(bars_df: DataFrame) -> float:
    """
    Garman-Klass volatility estimator using OHLC data.
    More efficient than close-to-close estimator.
    """
```

### 7.3 Correlation (`analytics/correlation.py`)

```python
def pairwise_correlation(
    bars_df: DataFrame,
    tickers: list[str],
    period: str = "daily",
) -> CorrMatrix:
    """
    Correlation matrix of returns.
    - daily: correlate daily returns
    - intraday: correlate minute-by-minute returns (same-day)
    """

def sector_correlation(bars_df: DataFrame) -> SectorCorrMatrix:
    """
    Average pairwise correlation within and between GICS sectors.
    Shows which sectors move together.
    """

def rolling_correlation(
    bars_df: DataFrame,
    ticker_a: str,
    ticker_b: str,
    window: int = 20,
) -> CorrSeries:
    """
    Rolling correlation over time. Useful for detecting
    regime changes in stock relationships.
    """
```

### 7.4 Pattern Detection (`analytics/patterns.py`)

```python
def intraday_patterns(bars_df: DataFrame) -> PatternReport:
    """
    Detect recurring intraday behaviors:
    - Opening range breakout frequency
    - Mean reversion vs. momentum by time-of-day
    - Power hour (last hour) directional bias
    - Lunch lull (11:30-1:00) volume/vol compression
    """

def day_of_week_effects(bars_df: DataFrame) -> DayOfWeekReport:
    """
    Returns by day of week. Monday effect, Friday effect, etc.
    Statistical significance via t-test.
    """

def monthly_seasonality(bars_df: DataFrame) -> SeasonalityReport:
    """
    Returns by month. January effect, sell-in-May, etc.
    Requires at least 2 years of daily data for meaningful results.
    """
```

### 7.5 Sector Analysis (`analytics/sectors.py`)

```python
def sector_rotation(bars_df: DataFrame, window: int = 20) -> RotationReport:
    """
    Relative strength of each sector vs. the equal-weight market.
    Shows which sectors are leading/lagging over the window.
    """

def sector_heatmap(bars_df: DataFrame, date: date) -> HeatmapData:
    """
    For a single day: return per-ticker by sector, colored by return.
    Designed for visual rendering (Plotly treemap or heatmap).
    """

def relative_strength(
    bars_df: DataFrame,
    ticker: str,
    benchmark: str = "SPY",
) -> RSData:
    """
    Relative strength of a ticker vs. benchmark over time.
    Rising = outperforming, falling = underperforming.
    """
```

### 7.6 Event Detection (`analytics/events.py`)

```python
def volume_spikes(bars_df: DataFrame, threshold: float = 3.0) -> list[Event]:
    """
    Detect minutes where volume exceeds threshold * rolling average.
    Often corresponds to news, earnings, or institutional activity.
    """

def price_gaps(bars_df: DataFrame, min_gap_pct: float = 1.0) -> list[Event]:
    """
    Detect opening gaps (open vs. previous close) exceeding threshold.
    Classifies as gap-up or gap-down.
    """

def anomaly_detection(bars_df: DataFrame) -> list[Event]:
    """
    Statistical anomaly detection on returns:
    - Minutes with returns > 3 std devs from mean
    - Sudden volatility regime changes (via CUSUM or similar)
    - Flash crash/spike detection
    """

def event_impact(
    bars_df: DataFrame,
    event_date: date,
    event_time: time | None = None,
    window_minutes: int = 60,
) -> ImpactReport:
    """
    Given a known event time, measure:
    - Price movement in the window before/after
    - Volume surge relative to normal
    - Time to mean reversion (if any)
    """
```

## 8. Export Layer

### 8.1 Export Formats (`lib/export.py`)

```python
class Exporter:
    def to_excel(
        self,
        data: DataFrame | AnalyticsResult,
        path: str,
        sheets: dict[str, DataFrame] | None = None,
    ) -> Path:
        """
        Export to Excel workbook. For multi-sheet output:
        - "Summary" sheet with overview stats
        - Per-ticker sheets with minute data
        - "Movers" sheet with biggest movers
        Auto-formats with headers, number formatting, conditional coloring.
        """

    def to_csv(self, data: DataFrame, path: str) -> Path:
        """Single CSV file. Simple, portable."""

    def to_parquet(self, data: DataFrame, path: str) -> Path:
        """Parquet for large datasets. Columnar, compressed, fast to read."""

    def to_json(self, data: AnalyticsResult) -> dict:
        """JSON for programmatic consumption / MCP responses."""
```

### 8.2 Report Templates

Pre-built report generators that combine data pulls + analytics + export:

- **Daily Market Report**: Pull a single day, run summary + movers + sector heatmap, export to Excel
- **Period Analysis Report**: Pull a date range, run full analytics suite, export multi-sheet Excel workbook
- **Correlation Report**: Pull multiple tickers, compute correlation matrices at various timeframes, export with heatmap visualization
- **Event Study Report**: Given an event date/time, pull surrounding data, run event impact analysis, export with before/after charts

## 9. MCP Server Tools

The MCP server at `server/marketpulse_mcp_server.py` exposes these tools to Claude (prefixed `mcp__arcis__mp_*` in Claude's tool namespace):

### 9.1 Data Fetching

**`mp_pull_bars`** — Pull market data for tickers over a date range.
- Params: `tickers` (list or index name), `from_date`, `to_date`, `timespan` (default "1min")
- Returns: Job ID + summary (tickers fetched, bars cached, time elapsed)
- For large pulls, runs as background job and returns job ID for status checking.

**`mp_job_status`** — Check status of a running or completed pull job.
- Params: `job_id`
- Returns: Status, progress (N/M tickers), current ticker, ETA

**`mp_resume_job`** — Resume a paused or failed pull job.
- Params: `job_id`
- Returns: Same as mp_pull_bars

### 9.2 Data Querying

**`mp_query_bars`** — Query cached bar data from SQLite.
- Params: `tickers` (list), `from_date`, `to_date`, `timespan`, `columns` (optional subset)
- Returns: JSON array of bar records (limited to 10,000 rows; use export for larger sets)

**`mp_cache_status`** — Show what data is currently cached.
- Params: `ticker` (optional), `index` (optional)
- Returns: Date ranges cached per ticker/timespan, total row counts, DB size

**`mp_list_indices`** — List available indices and custom ticker lists.
- Returns: Index names, ticker counts, last updated dates

### 9.3 Analytics

**`mp_analyze`** — Run an analytics function on cached data.
- Params: `function` (e.g. "daily_summary", "correlation", "volatility"), `tickers`, `from_date`, `to_date`, `timespan`, plus function-specific params
- Returns: JSON analytics result

**`mp_detect_events`** — Run event detection on cached data.
- Params: `tickers`, `from_date`, `to_date`, `type` ("volume_spikes", "price_gaps", "anomalies")
- Returns: List of detected events with timestamps and details

**`mp_event_impact`** — Analyze market impact around a known event.
- Params: `tickers`, `event_date`, `event_time`, `window_minutes`
- Returns: Impact analysis with before/after metrics

### 9.4 Export

**`mp_export_data`** — Export cached data or analytics results to a file.
- Params: `format` ("excel", "csv", "parquet"), `tickers`, `from_date`, `to_date`, `timespan`, `include_analytics` (bool), `output_path` (optional)
- Returns: File path of exported file

**`mp_generate_report`** — Generate a pre-built report.
- Params: `report_type` ("daily", "period", "correlation", "event_study"), plus type-specific params
- Returns: File path of generated report

### 9.5 Index Management

**`mp_refresh_index`** — Re-scrape index constituents from Wikipedia.
- Params: `index_name`
- Returns: Updated ticker count, additions/removals since last refresh

**`mp_create_custom_list`** — Create a named custom ticker list.
- Params: `name`, `tickers`
- Returns: Confirmation

## 10. CLI Commands

The CLI is invokable standalone via `py skills/marketpulse/lib/cli.py` or as a Typer app:

```bash
# Data fetching
marketpulse pull SP500 --from 2022-06-03 --to 2022-06-03
marketpulse pull AAPL,MSFT,GOOG --from 2022-01-03 --to 2022-12-30 --timespan 5min
marketpulse pull RUT2000 --from 2023-01-03 --to 2023-06-30

# Job management
marketpulse jobs                    # list all jobs
marketpulse jobs status <job-id>    # check specific job
marketpulse jobs resume <job-id>    # resume paused/failed job

# Query cached data
marketpulse query AAPL --from 2022-06-03 --to 2022-06-03 --limit 50
marketpulse cache-status            # what's in the database
marketpulse cache-status AAPL       # coverage for specific ticker

# Analytics
marketpulse analyze summary AAPL --from 2022-06-03 --to 2022-06-03
marketpulse analyze movers SP500 --from 2022-06-03 --to 2022-06-03 --top 20
marketpulse analyze correlation AAPL,MSFT,GOOG --from 2022-01-03 --to 2022-12-30
marketpulse analyze volatility AAPL --from 2022-01-03 --to 2022-12-30
marketpulse analyze sectors SP500 --from 2022-06-03 --to 2022-06-03

# Event detection
marketpulse events volume-spikes AAPL --from 2022-06-01 --to 2022-06-30
marketpulse events gaps SP100 --from 2022-06-01 --to 2022-06-30 --min-gap 2.0
marketpulse events impact AAPL --date 2022-06-03 --time 14:30 --window 60

# Export
marketpulse export AAPL --from 2022-06-03 --format excel --output aapl-june3.xlsx
marketpulse report daily SP500 --date 2022-06-03 --output sp500-june3.xlsx
marketpulse report period SP100 --from 2022-06-01 --to 2022-06-30

# Index management
marketpulse indices list
marketpulse indices refresh SP500
marketpulse indices create "my-watchlist" AAPL,MSFT,GOOG,AMZN,NVDA
```

## 11. Configuration

### 11.1 Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `POLYGON_API_KEY` | Yes | Polygon.io / Massive.com API key |
| `MARKETPULSE_DB` | No | SQLite path (default: `~/.marketpulse/marketpulse.db`) |
| `MARKETPULSE_CONCURRENCY` | No | Parallel ticker fetches (default: 10) |
| `MARKETPULSE_RATE_LIMIT` | No | Max API calls/second (default: 50) |

The `POLYGON_API_KEY` is passed through ARCIS's `.mcp.json` env block using `${POLYGON_API_KEY}`, which resolves from the user's shell environment or a `.env` file in the ARCIS root.

## 12. Dependencies

Added to `server/requirements.txt` (or a separate `skills/marketpulse/requirements.txt`):

```
httpx            # async HTTP client for Polygon API
duckdb           # embedded OLAP engine for querying Parquet files
pyarrow          # Parquet read/write
sqlalchemy       # ORM for metadata SQLite
aiosqlite        # async SQLite driver for metadata
pandas           # DataFrames for analytics
numpy            # numerical operations
openpyxl         # Excel export
typer            # CLI framework
rich             # CLI progress bars and tables
python-dotenv    # .env file loading
mcp              # MCP server SDK (FastMCP)
beautifulsoup4   # Wikipedia scraping for index constituents
pyrate-limiter   # token bucket rate limiting for API client
```

## 13. Error Handling

- **API errors (4xx/5xx):** Retry with exponential backoff. After max retries, mark job as "failed" with error details, allowing resume.
- **Rate limiting (429):** Back off per Retry-After header, or exponential backoff if no header.
- **Network errors:** Treat as transient, retry. After max retries, pause job.
- **Invalid tickers:** Log warning, skip ticker, continue with remaining tickers. Report skipped tickers in job summary.
- **Partial data:** If a ticker has fewer bars than expected (low-liquidity stock), store what's returned. No bar = no trade in that minute, which is normal.
- **Data corruption:** Parquet files are written atomically (write to temp, rename on success). If a write fails mid-way, the temp file is discarded and no coverage row is inserted — the next pull retries that partition. SQLite metadata uses WAL mode for crash safety.
- **Stale constituent lists:** Warn if index JSON files are >90 days old. Suggest `mp_refresh_index`.

## 14. Performance Considerations

- **Columnar storage (Parquet):** Analytics queries only read needed columns. A cross-ticker volume analysis touches only the `volume` column, not OHLC data. 10-50x I/O reduction vs. row-store.
- **DuckDB partition pruning:** Queries automatically skip irrelevant Parquet files based on the partition path. A query for "AAPL in June 2021" reads one file, not the entire dataset.
- **Zero write contention:** Each parallel fetcher writes to its own Parquet file (unique ticker+month). No locking, no serialization.
- **Async I/O** for API calls — `httpx.AsyncClient` with `asyncio.Semaphore` for concurrent ticker fetches.
- **Memory management:** Each ticker-month is fetched and written to Parquet independently. Memory usage is proportional to one ticker-month (~8K-20K bars), not the total pull size.
- **DuckDB zero-copy:** DuckDB reads Parquet files directly via memory-mapped I/O. No intermediate loading step.
- **SQLite WAL mode** for the metadata database — concurrent reads while writing job progress.
- **Data location:** All data stored locally (`~/.marketpulse/`), NOT in the OneDrive-synced plugin directory, to avoid sync conflicts and performance issues.

## 15. Implementation Phasing

This project should be built in multiple plans:

**Plan 1 — Foundation & Data Layer:** ARCIS integration scaffolding (SKILL.md, .mcp.json update, MCP server stub), SQLite schema, Polygon client, cache logic, batch engine, basic CLI (`pull`, `jobs`, `cache-status`). Deliverable: can pull and cache minute bars for any ticker/date range.

**Plan 2 — Index Management & MCP Tools:** Index JSON files, Wikipedia scraping, IndexManager, MCP server data-fetching and query tools. Deliverable: Claude can pull data conversationally via `/arcis:marketpulse`.

**Plan 3 — Analytics Suite:** All 6 analytics modules (summary, volatility, correlation, patterns, sectors, events). Analytics MCP tools and CLI commands.

**Plan 4 — Export & Reports:** Excel/CSV/Parquet export, report templates, export MCP tools and CLI commands.

## 16. Future Enhancements (Out of Scope for V1)

- **Historical index constituents:** Track who was in each index on any past date to avoid survivorship bias.
- **Options data:** Polygon supports options chains — could add implied volatility surfaces.
- **Crypto / Forex:** Polygon covers these asset classes too. Same architecture, different ticker format.
- **Web dashboard:** FastAPI + Plotly frontend for interactive exploration.
- **Webhook alerts:** Notify on anomaly detection in real-time data.
- **Data quality checks:** Automated validation of fetched data (missing minutes, price outliers, volume inconsistencies).
- **Cross-skill integration:** Research-team could use MarketPulse data for financial research queries automatically.
