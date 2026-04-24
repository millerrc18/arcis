# Plan 1: Foundation & Data Layer

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up the MarketPulse skill within the ARCIS plugin: ARCIS integration scaffolding (SKILL.md, .mcp.json update, MCP server stub), DuckDB + Parquet data layer, SQLite metadata schema, Polygon.io API client with rate limiting and retry, cache/coverage logic, batch fetch engine with job tracking and resume, and a basic CLI (`pull`, `jobs`, `cache-status`). Deliverable: can pull and cache minute-level bars for any ticker or date range, resume interrupted jobs, and query cached coverage.

**Data provider:** Polygon.io **Starter plan ($29/mo)** -- 5 years of history (~mid-2021 onward), unlimited API calls, 15-min delayed data. Code is plan-tier agnostic; the only difference is what date ranges the API returns data for. All example dates in this plan use 2022-01-03 or later to stay safely within the 5-year window.

**Architecture:** Python core library under `skills/marketpulse/lib/`. DuckDB + partitioned Parquet files for bar data (columnar analytics). SQLite for metadata (tickers, jobs, coverage). `httpx.AsyncClient` for Polygon API with token-bucket rate limiting. Typer CLI. FastMCP server stub.

**Tech Stack:** Python 3.11+, httpx, duckdb, pyarrow, sqlalchemy 2.0 (async, aiosqlite), pandas, numpy, typer, rich, python-dotenv, mcp (FastMCP), pyrate-limiter, beautifulsoup4

**ARCIS plugin root:** `C:\Users\ryan.c.miller\OneDrive - General Dynamics Mission Systems\04 - Computer\Desktop\arcis`

---

## File Structure

### ARCIS Integration (modify existing)
- Modify: `.mcp.json` -- add `marketpulse` server entry alongside `deep-research`
- Modify: `.claude-plugin/plugin.json` -- update description to mention marketpulse skill

### Skill Scaffolding (all new)
- Create: `skills/marketpulse/SKILL.md` -- skill definition, trigger description
- Create: `skills/marketpulse/commands/marketpulse.md` -- orchestrator command prompt

### MCP Server
- Create: `server/marketpulse_mcp_server.py` -- FastMCP server with stub tools

### Core Library
- Create: `skills/marketpulse/lib/__init__.py` -- package init, version string
- Create: `skills/marketpulse/lib/client.py` -- Polygon.io API client (rate-limited, retrying)
- Create: `skills/marketpulse/lib/models.py` -- SQLAlchemy models for metadata SQLite
- Create: `skills/marketpulse/lib/db.py` -- DuckDB + SQLite engine, session factory, data-dir setup
- Create: `skills/marketpulse/lib/storage.py` -- Parquet read/write, partition management
- Create: `skills/marketpulse/lib/cache.py` -- Fetch-or-cache logic, coverage tracking, batch engine
- Create: `skills/marketpulse/lib/cli.py` -- Typer CLI entry point

### References
- Create: `skills/marketpulse/references/polygon-api-notes.md` -- API quirks, limits, field mapping

### Tests
- Create: `tests/__init__.py`
- Create: `tests/conftest.py` -- shared fixtures, temp data dir, mock client
- Create: `tests/test_client.py` -- Polygon client unit tests (mocked HTTP)
- Create: `tests/test_models.py` -- SQLAlchemy model creation tests
- Create: `tests/test_storage.py` -- Parquet read/write tests
- Create: `tests/test_cache.py` -- Coverage tracking, cache-hit logic tests
- Create: `tests/test_cli.py` -- CLI integration tests
- Create: `tests/fixtures/polygon_responses/` -- sample API response JSON files

### Root
- Create: `skills/marketpulse/requirements.txt` -- all dependencies

---

## Task 1: ARCIS Integration Scaffolding

**Files:**
- Modify: `.mcp.json`
- Create: `skills/marketpulse/SKILL.md`
- Create: `skills/marketpulse/commands/marketpulse.md`

- [ ] **Step 1: Create SKILL.md**

`skills/marketpulse/SKILL.md`:
```markdown
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
```

- [ ] **Step 2: Create orchestrator command prompt**

`skills/marketpulse/commands/marketpulse.md`:
```markdown
# MarketPulse Command

You are the MarketPulse orchestrator. When the user asks about market data, use the `mcp__marketpulse__*` tools to fetch, query, and analyze data.

## Workflow

1. **Understand the request**: What tickers, date range, and analysis does the user want?
2. **Check cache**: Use `mp_cache_status` to see if data is already cached.
3. **Pull if needed**: Use `mp_pull_bars` to fetch any missing data.
4. **Query/analyze**: Use `mp_query_bars` to retrieve data, then analyze as requested.
5. **Present results**: Format findings clearly with key metrics and observations.

## Tips

- For index names, use: SP100, SP500, DOW30, NDX100, RUT2000
- Default timespan is "1min" (minute bars). Also supports "5min", "15min", "1hour", "1day"
- The Starter plan provides ~5 years of history (back to mid-2021). Dates before that will return no data.
- Large index pulls can take minutes. Use job tracking to monitor progress.
```

- [ ] **Step 3: Update .mcp.json to add marketpulse server**

Add the `marketpulse` server entry to the existing `.mcp.json`. The result should be:

```json
{
  "mcpServers": {
    "deep-research": {
      "command": "py",
      "args": ["${CLAUDE_PLUGIN_ROOT}/server/research_mcp_server.py"],
      "env": {
        "TAVILY_API_KEY": "${TAVILY_API_KEY}",
        "EXA_API_KEY": "${EXA_API_KEY}",
        "FIRECRAWL_API_KEY": "${FIRECRAWL_API_KEY}",
        "SERPER_API_KEY": "${SERPER_API_KEY}",
        "BRAVE_API_KEY": "${BRAVE_API_KEY}",
        "SERPAPI_KEY": "${SERPAPI_KEY}",
        "WOLFRAM_APP_ID": "${WOLFRAM_APP_ID}",
        "NEWSAPI_KEY": "${NEWSAPI_KEY}"
      }
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

- [ ] **Step 4: Verify** -- Confirm all three files exist and the `.mcp.json` is valid JSON.

---

## Task 2: Requirements and Project Setup

**Files:**
- Create: `skills/marketpulse/requirements.txt`
- Create: `skills/marketpulse/references/polygon-api-notes.md`

- [ ] **Step 1: Create requirements.txt**

`skills/marketpulse/requirements.txt`:
```
httpx>=0.27,<1.0
duckdb>=1.1,<2.0
pyarrow>=17.0,<19.0
sqlalchemy>=2.0,<3.0
aiosqlite>=0.20,<1.0
pandas>=2.2,<3.0
numpy>=1.26,<3.0
openpyxl>=3.1,<4.0
typer>=0.12,<1.0
rich>=13.0,<14.0
python-dotenv>=1.0,<2.0
mcp>=1.0,<2.0
beautifulsoup4>=4.12,<5.0
pyrate-limiter>=3.0,<4.0
```

- [ ] **Step 2: Create Polygon API reference notes**

`skills/marketpulse/references/polygon-api-notes.md`:
```markdown
# Polygon.io API Notes

## Authentication
- API key passed as query param: `?apiKey=xxx` or header `Authorization: Bearer xxx`
- Key sourced from `POLYGON_API_KEY` environment variable

## Aggregates (Bars) Endpoint
- `GET /v2/aggs/ticker/{ticker}/range/{multiplier}/{timespan}/{from}/{to}`
- `timespan`: minute, hour, day, week, month, quarter, year
- `multiplier`: 1, 5, 15, etc.
- Date format: YYYY-MM-DD or Unix ms
- **No pagination**: Unlike other Polygon endpoints, aggregates do NOT return `next_url`
- **Result limit**: 50,000 bars per request
  - 1-min bars: ~128 trading days per request (390 min/day)
  - 5-min bars: ~640 trading days
  - Safe strategy: chunk by calendar month (max ~8,580 1-min bars per month)
- `adjusted=true` (default) returns split-adjusted prices
- `sort=asc` returns chronological order

## Response Shape
```json
{
  "ticker": "AAPL",
  "queryCount": 390,
  "resultsCount": 390,
  "adjusted": true,
  "results": [
    {
      "v": 1234567,      // volume
      "vw": 150.1234,    // VWAP
      "o": 149.50,       // open
      "c": 150.25,       // close
      "h": 150.75,       // high
      "l": 149.10,       // low
      "t": 1641220800000, // timestamp (Unix ms)
      "n": 5432          // number of transactions
    }
  ],
  "status": "OK",
  "request_id": "abc123"
}
```

## Ticker Details Endpoint
- `GET /v3/reference/tickers/{ticker}`
- Returns: name, market, locale, type, currency, sic_code, etc.
- Rate limit shared with aggregates

## Ticker Search Endpoint
- `GET /v3/reference/tickers?search={query}&active=true&limit=100`
- Search by name or symbol prefix

## Plan Tier Differences
- **Starter ($29/mo)**: 5 years history, unlimited calls, 15-min delay
- **Developer ($79/mo)**: 10 years history, unlimited calls, 15-min delay
- **Advanced ($199/mo)**: 20+ years history, unlimited calls, real-time
- Code is identical across tiers; API simply returns no data for dates outside plan window

## Rate Limits
- Unlimited API calls on all paid plans
- In practice, use token-bucket at ~50 req/s to be a good citizen
- 429 responses include `Retry-After` header (seconds)

## Gotchas
- Aggregates for non-trading hours return empty (no pre/post-market by default)
- `adjusted=true` means historical splits are reflected -- prices may differ from raw historical
- Timestamps are in UTC (Unix milliseconds)
- Weekends/holidays return no data (expected, not an error)
- Low-liquidity tickers may have sparse minute bars (missing minutes = no trades)
```

- [ ] **Step 3: Install dependencies**

```bash
cd "path/to/arcis"
pip install -r skills/marketpulse/requirements.txt
```

---

## Task 3: Data Directory and Database Setup (`lib/db.py`)

**Files:**
- Create: `skills/marketpulse/lib/__init__.py`
- Create: `skills/marketpulse/lib/db.py`

- [ ] **Step 1: Create package init**

`skills/marketpulse/lib/__init__.py`:
```python
"""MarketPulse -- stock market data caching and analytics."""

__version__ = "0.1.0"
```

- [ ] **Step 2: Implement db.py -- data directory, SQLite engine, DuckDB connection**

`skills/marketpulse/lib/db.py` must handle:

1. **Data directory resolution:**
   - Default: `~/.marketpulse/`
   - Override via `MARKETPULSE_DATA_DIR` environment variable
   - Auto-create the directory and subdirectories (`bars/`) on first use

2. **SQLite engine (metadata):**
   - Path: `{data_dir}/metadata.db`
   - Use SQLAlchemy 2.0 async engine with `aiosqlite` driver
   - WAL mode enabled via event listener (`PRAGMA journal_mode=WAL`)
   - Async session factory (`async_sessionmaker`)
   - `init_db()` coroutine that calls `metadata.create_all()`

3. **DuckDB connection (queries):**
   - Factory function `get_duckdb()` returning a `duckdb.DuckDBPyConnection`
   - In-memory connection (reads Parquet files directly from disk)
   - Helper: `bars_glob(ticker, timespan, year_month)` that returns the Parquet glob path for `read_parquet()` calls

4. **Configuration class:**
   - `MarketPulseConfig` dataclass with fields: `data_dir`, `db_url`, `concurrency` (default 10), `rate_limit` (default 50), `polygon_api_key`
   - Populated from environment variables with sensible defaults

Key interfaces:
```python
from dataclasses import dataclass, field
from pathlib import Path
import os

@dataclass
class MarketPulseConfig:
    data_dir: Path = field(default_factory=lambda: Path(
        os.environ.get("MARKETPULSE_DATA_DIR", Path.home() / ".marketpulse")
    ))
    concurrency: int = field(default_factory=lambda: int(
        os.environ.get("MARKETPULSE_CONCURRENCY", "10")
    ))
    rate_limit: int = field(default_factory=lambda: int(
        os.environ.get("MARKETPULSE_RATE_LIMIT", "50")
    ))
    polygon_api_key: str = field(default_factory=lambda:
        os.environ.get("POLYGON_API_KEY", "")
    )

    @property
    def db_url(self) -> str:
        return f"sqlite+aiosqlite:///{self.data_dir / 'metadata.db'}"

    @property
    def bars_dir(self) -> Path:
        return self.data_dir / "bars"

    def ensure_dirs(self) -> None:
        """Create data directory tree if it doesn't exist."""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.bars_dir.mkdir(parents=True, exist_ok=True)
        (self.data_dir / "custom_lists").mkdir(exist_ok=True)

# Module-level singleton (lazily initialized)
_config: MarketPulseConfig | None = None

def get_config() -> MarketPulseConfig:
    global _config
    if _config is None:
        _config = MarketPulseConfig()
        _config.ensure_dirs()
    return _config

# SQLite async engine + session
async def get_engine():
    ...

async def get_session():
    ...

async def init_db():
    """Create all tables in metadata.db."""
    ...

# DuckDB
def get_duckdb():
    ...

def bars_glob(
    ticker: str | None = None,
    timespan: str = "1min",
    year_month: str | None = None,
) -> str:
    """Return the Parquet glob path for read_parquet() calls.

    Examples:
        bars_glob("AAPL", "1min")          -> "~/.marketpulse/bars/timespan=1min/ticker=AAPL/*.parquet"
        bars_glob("AAPL", "1min", "2022-06") -> "~/.marketpulse/bars/timespan=1min/ticker=AAPL/2022-06.parquet"
        bars_glob(None, "1min", "2022-06")   -> "~/.marketpulse/bars/timespan=1min/ticker=*/2022-06.parquet"
    """
    ...
```

- [ ] **Step 3: Verify** -- Write a quick smoke test that:
  - Creates a `MarketPulseConfig` with a temp directory
  - Calls `ensure_dirs()` and checks directory structure exists
  - Creates the async engine and calls `init_db()`
  - Confirms `metadata.db` was created
  - Gets a DuckDB connection and runs `SELECT 1`

---

## Task 4: SQLAlchemy Metadata Models (`lib/models.py`)

**Files:**
- Create: `skills/marketpulse/lib/models.py`

- [ ] **Step 1: Implement all four metadata tables as SQLAlchemy models**

`skills/marketpulse/lib/models.py` must define:

1. **`Ticker`** -- reference data for each stock symbol
   - Columns: `symbol` (TEXT PK), `name` (TEXT), `sector` (TEXT), `industry` (TEXT), `market_cap` (REAL), `sic_code` (TEXT), `updated_at` (TEXT, ISO timestamp)
   - `__tablename__ = "tickers"`

2. **`IndexMember`** -- index constituent tracking
   - Columns: `index_name` (TEXT), `ticker` (TEXT, FK to tickers.symbol), `added_date` (TEXT, nullable), `removed_date` (TEXT, nullable)
   - Composite PK: `(index_name, ticker, added_date)`
   - `__tablename__ = "index_members"`

3. **`FetchJob`** -- batch job tracking for resumability
   - Columns: `id` (TEXT PK, UUID), `created_at` (TEXT), `index_name` (TEXT nullable), `tickers` (TEXT, JSON array), `from_date` (TEXT), `to_date` (TEXT), `timespan` (TEXT), `status` (TEXT: pending/running/paused/completed/failed), `total_tickers` (INTEGER), `completed_tickers` (INTEGER default 0), `current_ticker` (TEXT nullable), `error` (TEXT nullable)
   - `__tablename__ = "fetch_jobs"`

4. **`Coverage`** -- tracks which ticker/month/timespan combinations are cached
   - Columns: `ticker` (TEXT), `timespan` (TEXT), `year_month` (TEXT, "YYYY-MM"), `bar_count` (INTEGER), `fetched_at` (TEXT, ISO timestamp)
   - Composite PK: `(ticker, timespan, year_month)`
   - `__tablename__ = "coverage"`

All models inherit from a shared `Base = declarative_base()` (or `DeclarativeBase` for SQLAlchemy 2.0 style).

- [ ] **Step 2: Verify** -- Write tests in `tests/test_models.py` that:
  - Create all tables in an in-memory SQLite database
  - Insert a sample row into each table
  - Query it back and assert field values
  - Test composite PK uniqueness constraint on `Coverage` and `IndexMember`

---

## Task 5: Parquet Storage Layer (`lib/storage.py`)

**Files:**
- Create: `skills/marketpulse/lib/storage.py`

- [ ] **Step 1: Implement Parquet read/write with Hive-style partitioning**

`skills/marketpulse/lib/storage.py` must provide:

1. **`write_bars(ticker, timespan, year_month, bars)`**
   - Takes a list of bar dicts (or a DataFrame) for a single ticker+month
   - Writes to `{bars_dir}/timespan={timespan}/ticker={ticker}/{year_month}.parquet`
   - Creates parent directories as needed
   - **Atomic write**: write to a `.tmp` file first, then rename on success
   - Uses pyarrow to write with the schema: timestamp (TIMESTAMP), open (FLOAT64), high (FLOAT64), low (FLOAT64), close (FLOAT64), volume (FLOAT64), vwap (FLOAT64), num_transactions (INT32)
   - The ticker, timespan, and year_month are NOT columns in the Parquet file (they're encoded in the partition path)

2. **`read_bars(ticker, timespan, year_month)`**
   - Reads a single Parquet partition file and returns a pandas DataFrame
   - Returns empty DataFrame if the file doesn't exist

3. **`delete_bars(ticker, timespan, year_month)`**
   - Removes a single partition file (for re-fetching)

4. **`partition_path(ticker, timespan, year_month)`**
   - Returns the full `Path` to a Parquet partition file

5. **`list_partitions(ticker=None, timespan=None)`**
   - Walks the partition tree and returns a list of `(ticker, timespan, year_month)` tuples for existing files

6. **`compute_year_months(from_date, to_date)`**
   - Given a date range, return the list of "YYYY-MM" strings that cover it
   - Example: `compute_year_months(date(2022, 1, 15), date(2022, 3, 10))` -> `["2022-01", "2022-02", "2022-03"]`

- [ ] **Step 2: Verify** -- Write tests in `tests/test_storage.py` that:
  - Write a small DataFrame of bars to a temp directory
  - Read it back and assert values match
  - Verify the file path follows the partition convention
  - Test atomic write (interrupt mid-write should leave no partial file)
  - Test `compute_year_months` with various date ranges (same month, cross-year, single day)
  - Test `list_partitions` returns correct tuples after writing several files

---

## Task 6: Polygon.io API Client (`lib/client.py`)

**Files:**
- Create: `skills/marketpulse/lib/client.py`
- Create: `tests/fixtures/polygon_responses/aggs_aapl_2022_01_03.json`

- [ ] **Step 1: Implement the PolygonClient class**

`skills/marketpulse/lib/client.py` must implement:

1. **`PolygonClient` class** with constructor taking `api_key` and optional `rate_limit` (calls/sec, default 50).

2. **Rate limiting** using `pyrate-limiter`:
   - Token bucket algorithm: allows bursting while maintaining average rate
   - Default: 50 calls/second (configurable via constructor or `MARKETPULSE_RATE_LIMIT`)

3. **`async get_bars(ticker, timespan, multiplier, from_date, to_date)`**:
   - Calls `GET /v2/aggs/ticker/{ticker}/range/{multiplier}/{timespan}/{from_date}/{to_date}`
   - Query params: `adjusted=true`, `sort=asc`, `limit=50000`
   - Parses response `results` array into a list of `Bar` dataclass instances
   - Converts Unix ms timestamps to `datetime` (UTC)
   - Maps Polygon field names (`v` -> `volume`, `vw` -> `vwap`, `o` -> `open`, `c` -> `close`, `h` -> `high`, `l` -> `low`, `t` -> `timestamp`, `n` -> `num_transactions`)

4. **`async get_bars_chunked(ticker, timespan, multiplier, from_date, to_date)`**:
   - Chunks the date range by calendar month
   - Calls `get_bars()` for each chunk sequentially
   - Returns concatenated results
   - This is the primary entry point for fetching -- callers don't need to worry about chunking

5. **`async get_ticker_details(ticker)`**:
   - Calls `GET /v3/reference/tickers/{ticker}`
   - Returns a `TickerInfo` dataclass with fields: symbol, name, sector, industry, market_cap, sic_code

6. **`async search_tickers(query, limit=20)`**:
   - Calls `GET /v3/reference/tickers?search={query}&active=true&limit={limit}`
   - Returns a list of `TickerInfo`

7. **Retry with exponential backoff + jitter**:
   - On 429 or 5xx responses, retry up to 5 times
   - Delay: `min(base_delay * 2^attempt + random(0, 1.0), 60)` seconds
   - `base_delay` = 1.0 second
   - On 429 with `Retry-After` header, use that value instead
   - Log each retry attempt

8. **Error handling**:
   - Raise `PolygonAPIError` (custom exception) on non-retryable errors (400, 401, 403, 404)
   - Raise `PolygonRateLimitError` (subclass) when retries exhausted on 429
   - Return empty list for 200 responses with `resultsCount: 0` (normal for non-trading days)

9. **Context manager** for proper `httpx.AsyncClient` lifecycle:
   ```python
   async with PolygonClient(api_key="...") as client:
       bars = await client.get_bars_chunked(...)
   ```

Data classes:
```python
from dataclasses import dataclass
from datetime import datetime

@dataclass
class Bar:
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    vwap: float
    num_transactions: int

@dataclass
class TickerInfo:
    symbol: str
    name: str
    sector: str | None = None
    industry: str | None = None
    market_cap: float | None = None
    sic_code: str | None = None
```

- [ ] **Step 2: Create test fixture**

`tests/fixtures/polygon_responses/aggs_aapl_2022_01_03.json` -- a sample Polygon aggregates response for AAPL on 2022-01-03 (a Monday, market open). Include ~10 bars (not all 390) to keep the fixture small:

```json
{
  "ticker": "AAPL",
  "queryCount": 10,
  "resultsCount": 10,
  "adjusted": true,
  "results": [
    {"v": 2345678, "vw": 182.0123, "o": 182.63, "c": 182.21, "h": 182.88, "l": 182.01, "t": 1641220200000, "n": 15432},
    {"v": 1876543, "vw": 182.1534, "o": 182.21, "c": 182.35, "h": 182.50, "l": 182.10, "t": 1641220260000, "n": 12876}
  ],
  "status": "OK",
  "request_id": "test_fixture_001"
}
```

(Include 8-10 bars with realistic-looking values. Timestamps should be Unix ms for 2022-01-03 starting at 9:30 AM ET = 14:30 UTC.)

- [ ] **Step 3: Write tests** in `tests/test_client.py`:
  - Mock `httpx.AsyncClient` responses using the fixture JSON
  - Test `get_bars()` parses response correctly (field mapping, timestamp conversion)
  - Test `get_bars()` returns empty list for empty results (non-trading day)
  - Test retry on 429 (mock 429 -> 429 -> 200 sequence, verify 3 calls made)
  - Test retry on 500 (mock 500 -> 200 sequence)
  - Test `PolygonAPIError` raised on 401
  - Test `get_bars_chunked()` chunks a multi-month range correctly (mock and verify N calls for N months)
  - Test rate limiter is used (verify `pyrate-limiter` acquire is called)

---

## Task 7: Cache and Coverage Logic (`lib/cache.py`)

**Files:**
- Create: `skills/marketpulse/lib/cache.py`

- [ ] **Step 1: Implement the CacheManager class**

`skills/marketpulse/lib/cache.py` must implement:

1. **`CacheManager` class** -- coordinates between the Polygon client, Parquet storage, and SQLite coverage table.

Constructor takes: `config: MarketPulseConfig`, `client: PolygonClient`, and the SQLAlchemy async session factory.

2. **`async check_coverage(ticker, timespan, from_date, to_date)`**:
   - Compute the list of year_months needed (via `storage.compute_year_months()`)
   - Query the `coverage` table for existing entries matching (ticker, timespan, year_month)
   - Return a `CoverageReport` with `cached` (list of year_months already present) and `missing` (list of year_months to fetch)

3. **`async fetch_and_cache(ticker, timespan, multiplier, from_date, to_date)`**:
   - Check coverage to find missing months
   - For each missing month:
     a. Call `client.get_bars()` for that month
     b. Call `storage.write_bars()` to write the Parquet file
     c. Insert a `coverage` row with bar_count and fetched_at
   - Return the total number of new bars cached

4. **`async get_bars_df(tickers, timespan, from_date, to_date, columns=None)`**:
   - Use DuckDB to query the Parquet partition tree
   - Build the `read_parquet()` glob paths for the requested tickers/timespan
   - Optionally select only specific columns
   - Return a pandas DataFrame
   - Limit to 10,000 rows by default (configurable) with a warning if truncated

5. **`async get_cache_status(ticker=None)`**:
   - Query the `coverage` table to show what's cached
   - If ticker given, show date ranges for that ticker
   - If no ticker, show summary (total tickers, total bars, disk usage estimate)

Key data class:
```python
@dataclass
class CoverageReport:
    ticker: str
    timespan: str
    from_date: date
    to_date: date
    cached: list[str]      # year_months already in cache
    missing: list[str]     # year_months that need fetching
    fully_cached: bool     # True if missing is empty
```

- [ ] **Step 2: Implement the BatchEngine class** (also in `cache.py`)

The `BatchEngine` orchestrates multi-ticker pulls with job tracking:

1. **`async pull(tickers, from_date, to_date, timespan, job_id=None)`**:
   - Create a new `FetchJob` row (or load existing if `job_id` provided)
   - Set status to "running"
   - Iterate tickers with `asyncio.Semaphore` for concurrency control (default 10)
   - For each ticker:
     a. Call `cache_manager.fetch_and_cache(ticker, ...)`
     b. Update `completed_tickers` and `current_ticker` in the FetchJob row
   - On completion, set status to "completed"
   - On exception, set status to "failed" with error message
   - On `KeyboardInterrupt` / `asyncio.CancelledError`, set status to "paused"
   - Return the FetchJob with final stats

2. **`async resume(job_id)`**:
   - Load the FetchJob by ID
   - Parse the `tickers` JSON array, skip the first `completed_tickers` entries
   - Call `pull()` with the remaining tickers and the existing job_id

3. **`async list_jobs()`**:
   - Return all FetchJob rows ordered by created_at desc

4. **Progress callback**:
   - Accept an optional `on_progress` callback: `Callable[[str, int, int], None]` (current_ticker, completed, total)
   - Called after each ticker completes
   - The CLI and MCP server will use this for progress display

- [ ] **Step 3: Write tests** in `tests/test_cache.py`:
  - Test `check_coverage` returns correct cached/missing split
  - Test `fetch_and_cache` writes Parquet files and inserts coverage rows
  - Test `fetch_and_cache` skips already-cached months (mock client not called for cached months)
  - Test `BatchEngine.pull` creates a job, processes tickers, updates progress
  - Test `BatchEngine.resume` skips already-completed tickers
  - Test job status transitions (pending -> running -> completed, running -> failed, running -> paused)
  - Use mock PolygonClient that returns fixture data
  - Use temp directory for Parquet storage

---

## Task 8: Typer CLI (`lib/cli.py`)

**Files:**
- Create: `skills/marketpulse/lib/cli.py`

- [ ] **Step 1: Implement the CLI with Typer**

`skills/marketpulse/lib/cli.py` must implement a Typer app with these commands:

1. **`pull`** -- Pull bar data for tickers or an index
   ```
   marketpulse pull AAPL,MSFT --from 2022-01-03 --to 2022-01-31 --timespan 1min
   marketpulse pull SP100 --from 2022-06-01 --to 2022-06-30
   ```
   - First argument: comma-separated tickers OR an index name (SP100, SP500, DOW30, NDX100, RUT2000)
   - `--from` / `--to`: date range (YYYY-MM-DD format)
   - `--timespan`: bar size (default "1min", options: 1min, 5min, 15min, 1hour, 1day)
   - Displays a Rich progress bar showing ticker-by-ticker progress
   - On completion, prints summary: tickers fetched, bars cached, time elapsed
   - On Ctrl+C, pauses job and prints job ID for resume

2. **`jobs`** subcommand group:
   - `jobs list` -- List all fetch jobs with status, progress, dates
   - `jobs status <job-id>` -- Show detailed status of a specific job
   - `jobs resume <job-id>` -- Resume a paused/failed job

3. **`cache-status`** -- Show what data is cached
   ```
   marketpulse cache-status
   marketpulse cache-status AAPL
   ```
   - Without args: summary table (total tickers, total bars, total disk size, oldest/newest data)
   - With ticker: detailed coverage for that ticker (which months are cached, bar counts)
   - Use Rich tables for output

4. **Configuration:**
   - Load `.env` file from the ARCIS root (or current directory) using `python-dotenv`
   - All commands need `POLYGON_API_KEY` set (check at startup, print helpful error if missing)

5. **Entry point:**
   - Runnable as `python -m skills.marketpulse.lib.cli` or `py skills/marketpulse/lib/cli.py`
   - The `if __name__ == "__main__"` block runs the Typer app

Example session:
```
$ py skills/marketpulse/lib/cli.py pull AAPL,MSFT --from 2022-01-03 --to 2022-01-31

Pulling 2 tickers from 2022-01-03 to 2022-01-31 (1min bars)
[################] AAPL  1/2  8,190 bars cached
[########........] MSFT  2/2  fetching...
Done! 2 tickers, 16,380 bars cached in 4.2s

$ py skills/marketpulse/lib/cli.py cache-status

MarketPulse Cache Status
┌────────┬──────────┬────────────┬────────────┬───────┐
│ Ticker │ Timespan │ From       │ To         │ Bars  │
├────────┼──────────┼────────────┼────────────┼───────┤
│ AAPL   │ 1min     │ 2022-01    │ 2022-01    │ 8,190 │
│ MSFT   │ 1min     │ 2022-01    │ 2022-01    │ 8,190 │
├────────┼──────────┼────────────┼────────────┼───────┤
│ Total  │          │            │            │16,380 │
└────────┴──────────┴────────────┴────────────┴───────┘
```

- [ ] **Step 2: Write tests** in `tests/test_cli.py`:
  - Use Typer's `CliRunner` for testing
  - Test `pull` command with mocked client (verify bars written, job created)
  - Test `cache-status` output format
  - Test `jobs list` shows created jobs
  - Test error when `POLYGON_API_KEY` is not set
  - Test invalid ticker format / date format gives helpful error

---

## Task 9: MCP Server Stub (`server/marketpulse_mcp_server.py`)

**Files:**
- Create: `server/marketpulse_mcp_server.py`

- [ ] **Step 1: Implement the FastMCP server with Plan 1 tools**

`server/marketpulse_mcp_server.py` must implement a FastMCP server with these tools:

1. **`mp_pull_bars`** -- Pull market data for tickers over a date range
   - Params: `tickers` (str -- comma-separated tickers or index name), `from_date` (str, YYYY-MM-DD), `to_date` (str, YYYY-MM-DD), `timespan` (str, default "1min")
   - Resolves index names to ticker lists
   - Calls `BatchEngine.pull()`
   - Returns JSON: `{"job_id": "...", "status": "completed", "tickers_fetched": N, "bars_cached": N, "elapsed_seconds": N}`
   - For large pulls (>20 tickers), returns immediately with job_id and status "running"

2. **`mp_job_status`** -- Check status of a running or completed pull job
   - Params: `job_id` (str)
   - Returns JSON: `{"job_id": "...", "status": "...", "progress": "N/M", "current_ticker": "...", "elapsed_seconds": N}`

3. **`mp_resume_job`** -- Resume a paused or failed pull job
   - Params: `job_id` (str)
   - Returns same as `mp_pull_bars`

4. **`mp_query_bars`** -- Query cached bar data
   - Params: `tickers` (str, comma-separated), `from_date` (str), `to_date` (str), `timespan` (str, default "1min"), `columns` (str, optional comma-separated column names), `limit` (int, default 10000)
   - Returns JSON array of bar records
   - Includes a `truncated` flag if limit was hit

5. **`mp_cache_status`** -- Show what data is currently cached
   - Params: `ticker` (str, optional)
   - Returns JSON: coverage summary or per-ticker details

Server boilerplate:
```python
from mcp.server.fastmcp import FastMCP

mcp = FastMCP(
    "MarketPulse",
    description="Stock market data caching and analytics via Polygon.io"
)

# Tools registered via @mcp.tool() decorator

if __name__ == "__main__":
    mcp.run()
```

The server imports and uses the core library classes (`PolygonClient`, `CacheManager`, `BatchEngine`, etc.) from `skills.marketpulse.lib`.

**Important:** The server must handle the `POLYGON_API_KEY` from environment (passed via `.mcp.json` env block). If the key is missing, tools should return a helpful error message rather than crashing.

- [ ] **Step 2: Verify** -- Start the MCP server and confirm it initializes without errors:
```bash
cd "path/to/arcis"
POLYGON_API_KEY=test py server/marketpulse_mcp_server.py
```
(It should start up and listen for MCP connections. Ctrl+C to stop.)

---

## Task 10: Test Infrastructure (`tests/conftest.py`)

**Files:**
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`
- Create: `tests/fixtures/polygon_responses/` (directory)

- [ ] **Step 1: Create shared test fixtures and conftest**

`tests/conftest.py` must provide:

1. **`tmp_data_dir` fixture** (function scope):
   - Creates a temporary directory for `~/.marketpulse/`
   - Sets `MARKETPULSE_DATA_DIR` environment variable
   - Yields the Path
   - Cleans up after the test

2. **`test_config` fixture**:
   - Returns a `MarketPulseConfig` pointing to the temp data dir
   - Sets `POLYGON_API_KEY` to a test value

3. **`mock_polygon_client` fixture**:
   - Returns a `PolygonClient` instance with a mocked `httpx.AsyncClient`
   - Pre-loaded with fixture responses from `tests/fixtures/polygon_responses/`

4. **`db_session` fixture** (async, function scope):
   - Creates an in-memory SQLite database
   - Runs `init_db()` to create tables
   - Yields an async session
   - Rolls back after each test

5. **Helper: `load_fixture(name)`**:
   - Loads a JSON file from `tests/fixtures/polygon_responses/{name}.json`
   - Returns parsed dict

- [ ] **Step 2: Create fixture directory structure**

```
tests/
├── __init__.py
├── conftest.py
└── fixtures/
    └── polygon_responses/
        ├── aggs_aapl_2022_01_03.json     # (created in Task 6)
        ├── ticker_details_aapl.json       # sample ticker details response
        └── empty_results.json             # 200 OK with resultsCount: 0
```

Create `ticker_details_aapl.json`:
```json
{
  "results": {
    "ticker": "AAPL",
    "name": "Apple Inc.",
    "market": "stocks",
    "locale": "us",
    "primary_exchange": "XNAS",
    "type": "CS",
    "active": true,
    "currency_name": "usd",
    "sic_code": "3571",
    "sic_description": "Electronic Computers"
  },
  "status": "OK",
  "request_id": "test_fixture_002"
}
```

Create `empty_results.json`:
```json
{
  "ticker": "AAPL",
  "queryCount": 0,
  "resultsCount": 0,
  "adjusted": true,
  "results": [],
  "status": "OK",
  "request_id": "test_fixture_003"
}
```

---

## Task 11: Integration Test -- End-to-End Pull and Query

**Files:**
- Create: `tests/test_integration.py`

- [ ] **Step 1: Write an end-to-end test** that exercises the full pipeline with mocked HTTP:

1. Create a mock Polygon client that returns fixture bar data for AAPL and MSFT
2. Initialize the full stack (config -> db -> cache_manager -> batch_engine)
3. Pull 2 tickers for January 2022 (`2022-01-03` to `2022-01-31`)
4. Assert:
   - Parquet files were written at correct partition paths
   - Coverage rows were inserted in SQLite
   - FetchJob was created with status "completed"
   - `completed_tickers` == 2
5. Pull the same tickers again and assert NO API calls were made (fully cached)
6. Query bars via DuckDB and assert data matches what was written
7. Test `cache-status` returns correct summary

- [ ] **Step 2: Write a resume test:**

1. Mock a client that fails on the 2nd ticker
2. Pull 3 tickers, expect job status "failed" after ticker 2
3. Fix the mock, resume the job
4. Assert only ticker 3 is fetched (1 and 2 already done)
5. Job status should be "completed"

---

## Task 12: Design Spec Date Cleanup

**Files:**
- Modify: `skills/marketpulse/references/polygon-api-notes.md` (already created in Task 2 with safe dates)

- [ ] **Step 1: Review all date references in the codebase**

Scan all files for dates before 2022-01-01 and update them to 2022 or later. The Starter plan ($29/mo) only provides ~5 years of history, so dates before mid-2021 will return no data from the API.

Safe example dates to use:
- Single day: `2022-01-03` (first trading day of 2022, a Monday)
- Date range: `2022-01-03` to `2022-01-31`
- Multi-month: `2022-06-01` to `2022-06-30`
- Full year: `2022-01-03` to `2022-12-30`

The design spec (`docs/superpowers/specs/2026-04-23-marketpulse-design.md`) previously had example dates using `2021-06-03` and `2021-01-01`. These have been updated to `2022-*` equivalents in both the marketpulse and ARCIS copies of the spec.

**Note:** The code itself is plan-tier agnostic. It does not enforce any date restrictions. The only difference between Starter and Advanced is what dates the Polygon API returns data for. The date changes here are about documentation accuracy, not code behavior.

---

## Verification Checklist

After all tasks are complete, verify:

- [ ] `skills/marketpulse/SKILL.md` exists with correct trigger description
- [ ] `skills/marketpulse/commands/marketpulse.md` exists with orchestrator prompt
- [ ] `.mcp.json` has both `deep-research` and `marketpulse` server entries
- [ ] `skills/marketpulse/requirements.txt` lists all dependencies
- [ ] `skills/marketpulse/lib/__init__.py` has version string
- [ ] `skills/marketpulse/lib/db.py` creates data directory tree, SQLite engine, DuckDB connection
- [ ] `skills/marketpulse/lib/models.py` defines all 4 metadata tables
- [ ] `skills/marketpulse/lib/storage.py` handles Parquet read/write with atomic writes
- [ ] `skills/marketpulse/lib/client.py` fetches from Polygon with rate limiting and retry
- [ ] `skills/marketpulse/lib/cache.py` has CacheManager + BatchEngine with job tracking
- [ ] `skills/marketpulse/lib/cli.py` has `pull`, `jobs`, `cache-status` commands
- [ ] `server/marketpulse_mcp_server.py` exposes 5 MCP tools (mp_pull_bars, mp_job_status, mp_resume_job, mp_query_bars, mp_cache_status)
- [ ] All tests pass: `pytest tests/ -v`
- [ ] Can run: `py skills/marketpulse/lib/cli.py cache-status` without errors
- [ ] Data directory (`~/.marketpulse/`) is created with correct structure
- [ ] No example dates reference before 2022-01-01
