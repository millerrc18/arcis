"""MarketPulse MCP Server -- stock market data caching and analytics.

Exposes thirteen tools for pulling, querying, analysing, and inspecting
cached Polygon.io bar data through the Model Context Protocol:

- ``mp_pull_bars``          -- Pull market data for tickers over a date range.
- ``mp_job_status``         -- Check status of a running or completed pull job.
- ``mp_resume_job``         -- Resume a paused or failed pull job.
- ``mp_query_bars``         -- Query cached bar data via DuckDB.
- ``mp_cache_status``       -- Show what data is currently cached.
- ``mp_list_indices``       -- List available stock indices and custom lists.
- ``mp_refresh_index``      -- Re-scrape index constituents from Wikipedia.
- ``mp_create_custom_list`` -- Create a named custom ticker list.
- ``mp_analyze``            -- Run analytics functions (summary, volatility, etc.).
- ``mp_detect_events``      -- Detect volume spikes, price gaps, or anomalies.
- ``mp_event_impact``       -- Analyse price/volume impact around an event date.
- ``mp_export_data``        -- Export cached bar data to Excel, CSV, or Parquet.
- ``mp_generate_report``    -- Generate a pre-built analysis report.

Transport: stdio (one server process per Claude Code session).
All logging goes to stderr (stdout is reserved for MCP protocol).
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from datetime import date
from pathlib import Path

# ---------------------------------------------------------------------------
# Path setup -- ensure ARCIS root is importable
# ---------------------------------------------------------------------------

_project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_project_root))

from dotenv import load_dotenv

load_dotenv(_project_root / ".env")

from mcp.server.fastmcp import FastMCP

# ---------------------------------------------------------------------------
# Logging -- stderr only (stdout is MCP protocol)
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("marketpulse-mcp")


def log(msg: str) -> None:
    """Write a log message to stderr."""
    logger.info(msg)


# ---------------------------------------------------------------------------
# Lazy imports -- avoid importing heavy libs until first tool call
# ---------------------------------------------------------------------------

_lib_imported = False
_db_mod = None
_client_mod = None
_cache_mod = None
_models_mod = None


def _import_lib() -> None:
    """Import the MarketPulse library modules lazily."""
    global _lib_imported, _db_mod, _client_mod, _cache_mod, _models_mod
    if _lib_imported:
        return
    from skills.marketpulse.lib import db as db_mod
    from skills.marketpulse.lib import client as client_mod
    from skills.marketpulse.lib import cache as cache_mod
    from skills.marketpulse.lib import models as models_mod

    _db_mod = db_mod
    _client_mod = client_mod
    _cache_mod = cache_mod
    _models_mod = models_mod
    _lib_imported = True


# ---------------------------------------------------------------------------
# Lazy initialization -- build the full stack on first tool call
# ---------------------------------------------------------------------------

_initialized = False
_config = None
_session_factory = None
_polygon_client = None
_cache_manager = None
_batch_engine = None


async def _ensure_init() -> str | None:
    """Initialize the MarketPulse stack.  Returns an error string on failure."""
    global _initialized, _config, _session_factory
    global _polygon_client, _cache_manager, _batch_engine

    if _initialized:
        return None

    # Check for API key
    api_key = os.environ.get("POLYGON_API_KEY", "")
    if not api_key:
        return (
            "POLYGON_API_KEY is not set. "
            "Set it in your environment, in a .env file at the project root, "
            "or in the MCP server env block in .mcp.json."
        )

    _import_lib()

    # Reset singletons to avoid stale state from previous runs
    _db_mod.reset_config()

    _config = _db_mod.get_config()
    _config.ensure_dirs()
    _session_factory = _db_mod.get_session_factory(_config)

    # Create all tables
    await _db_mod.init_db(_db_mod.Base.metadata)

    # Stand up the Polygon client (as a context-managed session)
    _polygon_client = _client_mod.PolygonClient(api_key)
    await _polygon_client.__aenter__()

    _cache_manager = _cache_mod.CacheManager(_config, _polygon_client, _session_factory)
    _batch_engine = _cache_mod.BatchEngine(_cache_manager, _session_factory)

    _initialized = True
    log("MarketPulse stack initialized successfully.")
    return None



# ---------------------------------------------------------------------------
# FastMCP server
# ---------------------------------------------------------------------------

mcp = FastMCP(
    "MarketPulse",
    instructions="Stock market data caching and analytics via Polygon.io",
)


# ---------------------------------------------------------------------------
# Tool 1: mp_pull_bars
# ---------------------------------------------------------------------------

@mcp.tool()
async def mp_pull_bars(
    tickers: str,
    from_date: str,
    to_date: str,
    timespan: str = "1min",
) -> str:
    """Pull market data for tickers over a date range from Polygon.io.

    Fetches OHLCV bar data and caches it locally in Parquet format.
    Already-cached months are skipped automatically.

    Args:
        tickers: Comma-separated ticker symbols (e.g. "AAPL,MSFT,GOOG")
                 or an index name (SP500, DOW30, etc.).
        from_date: Start date in YYYY-MM-DD format.
        to_date: End date in YYYY-MM-DD format.
        timespan: Bar size -- 1min, 5min, 15min, 1hour, or 1day (default: 1min).
    """
    # Resolve index names to ticker lists
    _import_lib()
    from skills.marketpulse.lib.indices import IndexManager, IndexNotFoundError

    idx_mgr = IndexManager()
    if idx_mgr.is_index(tickers.strip()):
        try:
            index = idx_mgr.get_index(tickers.strip())
        except IndexNotFoundError as e:
            return json.dumps({"error": str(e)})
        if not index.tickers:
            return json.dumps({"error": f"Index '{tickers.strip().upper()}' has no tickers. Refresh it or use specific tickers."})
        ticker_list = index.tickers
        # Skip the ticker parsing below since we already have the list
    else:
        ticker_list = None  # Will be parsed below

    # Initialize stack
    err = await _ensure_init()
    if err:
        return json.dumps({"error": err})

    # Validate timespan
    if timespan not in _cache_mod.TIMESPAN_MAP:
        valid = ", ".join(_cache_mod.TIMESPAN_MAP.keys())
        return json.dumps({
            "error": f"Invalid timespan '{timespan}'. Valid options: {valid}",
        })

    # Parse dates
    try:
        start_dt = date.fromisoformat(from_date)
    except (ValueError, TypeError):
        return json.dumps({"error": f"Invalid from_date '{from_date}'. Use YYYY-MM-DD format."})

    try:
        end_dt = date.fromisoformat(to_date)
    except (ValueError, TypeError):
        return json.dumps({"error": f"Invalid to_date '{to_date}'. Use YYYY-MM-DD format."})

    if start_dt > end_dt:
        return json.dumps({"error": "from_date must be before or equal to to_date."})

    # Parse ticker list (only if not already resolved from an index)
    if ticker_list is None:
        ticker_list = [t.strip().upper() for t in tickers.split(",") if t.strip()]
    if not ticker_list:
        return json.dumps({"error": "No tickers provided."})

    # NOTE: For V1, all pulls run synchronously regardless of ticker count.
    # Future enhancement: for >20 tickers, run the batch in a background task
    # and return immediately with job_id and status "running".
    t0 = time.monotonic()

    try:
        job = await _batch_engine.pull(
            tickers=ticker_list,
            from_date=start_dt,
            to_date=end_dt,
            timespan=timespan,
        )
    except Exception as exc:
        return json.dumps({"error": f"Pull failed: {exc}"})

    elapsed = round(time.monotonic() - t0, 2)

    # Count total bars cached across all tickers for this job
    total_bars = 0
    try:
        status_info = await _cache_manager.get_cache_status()
        total_bars = status_info.get("total_bars", 0)
    except Exception:
        pass

    return json.dumps({
        "job_id": job.id,
        "status": job.status,
        "tickers_fetched": job.completed_tickers,
        "bars_cached": total_bars,
        "elapsed_seconds": elapsed,
    })


# ---------------------------------------------------------------------------
# Tool 2: mp_job_status
# ---------------------------------------------------------------------------

@mcp.tool()
async def mp_job_status(job_id: str) -> str:
    """Check status of a running or completed pull job.

    Args:
        job_id: The job ID returned by mp_pull_bars.
    """
    err = await _ensure_init()
    if err:
        return json.dumps({"error": err})

    from sqlalchemy import select

    try:
        async with _session_factory() as session:
            result = await session.execute(
                select(_models_mod.FetchJob).where(_models_mod.FetchJob.id == job_id)
            )
            job = result.scalar_one_or_none()
    except Exception as exc:
        return json.dumps({"error": f"Database error: {exc}"})

    if job is None:
        return json.dumps({"error": f"Job '{job_id}' not found."})

    return json.dumps({
        "job_id": job.id,
        "status": job.status,
        "progress": f"{job.completed_tickers}/{job.total_tickers}",
        "current_ticker": job.current_ticker,
        "timespan": job.timespan,
        "from_date": job.from_date,
        "to_date": job.to_date,
        "error": job.error,
    })


# ---------------------------------------------------------------------------
# Tool 3: mp_resume_job
# ---------------------------------------------------------------------------

@mcp.tool()
async def mp_resume_job(job_id: str) -> str:
    """Resume a paused or failed pull job from where it left off.

    Args:
        job_id: The job ID to resume.
    """
    err = await _ensure_init()
    if err:
        return json.dumps({"error": err})

    # Verify the job exists and is resumable
    from sqlalchemy import select

    try:
        async with _session_factory() as session:
            result = await session.execute(
                select(_models_mod.FetchJob).where(_models_mod.FetchJob.id == job_id)
            )
            job = result.scalar_one_or_none()
    except Exception as exc:
        return json.dumps({"error": f"Database error: {exc}"})

    if job is None:
        return json.dumps({"error": f"Job '{job_id}' not found."})

    if job.status not in ("paused", "failed"):
        return json.dumps({
            "error": (
                f"Job '{job_id}' has status '{job.status}'. "
                "Only paused or failed jobs can be resumed."
            ),
        })

    t0 = time.monotonic()

    try:
        resumed_job = await _batch_engine.resume(job_id)
    except Exception as exc:
        return json.dumps({"error": f"Resume failed: {exc}"})

    elapsed = round(time.monotonic() - t0, 2)

    total_bars = 0
    try:
        status_info = await _cache_manager.get_cache_status()
        total_bars = status_info.get("total_bars", 0)
    except Exception:
        pass

    return json.dumps({
        "job_id": resumed_job.id,
        "status": resumed_job.status,
        "tickers_fetched": resumed_job.completed_tickers,
        "bars_cached": total_bars,
        "elapsed_seconds": elapsed,
    })


# ---------------------------------------------------------------------------
# Tool 4: mp_query_bars
# ---------------------------------------------------------------------------

@mcp.tool()
async def mp_query_bars(
    tickers: str,
    from_date: str,
    to_date: str,
    timespan: str = "1min",
    columns: str = "",
    limit: int = 10000,
) -> str:
    """Query cached bar data from the local Parquet cache.

    Returns OHLCV records as a JSON array. Only returns data that has
    been previously pulled with mp_pull_bars.

    Args:
        tickers: Comma-separated ticker symbols (e.g. "AAPL,MSFT").
        from_date: Start date in YYYY-MM-DD format.
        to_date: End date in YYYY-MM-DD format.
        timespan: Bar size -- 1min, 5min, 15min, 1hour, or 1day (default: 1min).
        columns: Optional comma-separated column names to return
                 (e.g. "timestamp,close,volume"). Empty = all columns.
        limit: Maximum rows to return (default: 10000).
    """
    err = await _ensure_init()
    if err:
        return json.dumps({"error": err})

    # Parse dates
    try:
        start_dt = date.fromisoformat(from_date)
    except (ValueError, TypeError):
        return json.dumps({"error": f"Invalid from_date '{from_date}'. Use YYYY-MM-DD format."})

    try:
        end_dt = date.fromisoformat(to_date)
    except (ValueError, TypeError):
        return json.dumps({"error": f"Invalid to_date '{to_date}'. Use YYYY-MM-DD format."})

    if start_dt > end_dt:
        return json.dumps({"error": "from_date must be before or equal to to_date."})

    # Validate timespan
    if timespan not in _cache_mod.TIMESPAN_MAP:
        valid = ", ".join(_cache_mod.TIMESPAN_MAP.keys())
        return json.dumps({"error": f"Invalid timespan '{timespan}'. Valid options: {valid}"})

    # Resolve index names to ticker lists
    _import_lib()
    from skills.marketpulse.lib.indices import IndexManager

    idx_mgr = IndexManager()
    if idx_mgr.is_index(tickers.strip()):
        index = idx_mgr.get_index(tickers.strip())
        if not index.tickers:
            return json.dumps({"error": f"Index '{tickers.strip().upper()}' has no tickers."})
        ticker_list = index.tickers
    else:
        ticker_list = [t.strip().upper() for t in tickers.split(",") if t.strip()]
    if not ticker_list:
        return json.dumps({"error": "No tickers provided."})

    col_list = [c.strip() for c in columns.split(",") if c.strip()] if columns else None

    try:
        df = await _cache_manager.get_bars_df(
            tickers=ticker_list,
            timespan=timespan,
            from_date=start_dt,
            to_date=end_dt,
            columns=col_list,
            max_rows=limit,
        )
    except Exception as exc:
        return json.dumps({"error": f"Query failed: {exc}"})

    truncated = len(df) >= limit

    # Convert DataFrame to list of dicts, handling NaN -> None
    # and Timestamp -> ISO string for JSON serialization
    records = df.where(df.notna(), None).to_dict(orient="records")

    # Convert any remaining non-serializable types (Timestamps, etc.)
    for record in records:
        for key, val in record.items():
            if hasattr(val, "isoformat"):
                record[key] = val.isoformat()

    return json.dumps({
        "tickers": ticker_list,
        "from_date": from_date,
        "to_date": to_date,
        "timespan": timespan,
        "row_count": len(records),
        "truncated": truncated,
        "bars": records,
    })


# ---------------------------------------------------------------------------
# Tool 5: mp_cache_status
# ---------------------------------------------------------------------------

@mcp.tool()
async def mp_cache_status(ticker: str = "") -> str:
    """Show what bar data is currently cached in the local Parquet store.

    Without a ticker, returns a summary (total tickers, bars, partitions).
    With a ticker, returns detailed coverage per timespan.

    Args:
        ticker: Optional ticker symbol for detailed coverage.
                Empty string = summary across all tickers.
    """
    err = await _ensure_init()
    if err:
        return json.dumps({"error": err})

    ticker_arg = ticker.strip().upper() if ticker.strip() else None

    try:
        status = await _cache_manager.get_cache_status(ticker=ticker_arg)
    except Exception as exc:
        return json.dumps({"error": f"Cache status query failed: {exc}"})

    return json.dumps(status)


# ---------------------------------------------------------------------------
# Tool 6: mp_list_indices
# ---------------------------------------------------------------------------

@mcp.tool()
async def mp_list_indices() -> str:
    """List all available stock indices and custom ticker lists.

    Returns index names, ticker counts, and last-updated dates.
    """
    _import_lib()
    from skills.marketpulse.lib.indices import IndexManager
    idx_mgr = IndexManager()
    indices = idx_mgr.list_indices()
    return json.dumps({
        "indices": [
            {
                "short_name": idx.short_name,
                "name": idx.name,
                "description": idx.description,
                "ticker_count": idx.ticker_count,
                "last_updated": idx.last_updated,
                "source": idx.source,
            }
            for idx in indices
        ],
    })


# ---------------------------------------------------------------------------
# Tool 7: mp_refresh_index
# ---------------------------------------------------------------------------

@mcp.tool()
async def mp_refresh_index(index_name: str) -> str:
    """Re-scrape index constituents from Wikipedia to update the local data.

    Supported indices: SP100, SP500, DOW30, NDX100.

    Args:
        index_name: Short name of the index to refresh (e.g. "SP500").
    """
    _import_lib()
    from skills.marketpulse.lib.indices import IndexManager
    idx_mgr = IndexManager()
    try:
        index = idx_mgr.refresh_index(index_name)
        return json.dumps({
            "index": index.short_name,
            "name": index.name,
            "ticker_count": len(index.constituents),
            "last_updated": index.last_updated,
        })
    except ValueError as e:
        return json.dumps({"error": str(e)})
    except Exception as e:
        return json.dumps({"error": f"Refresh failed: {e}"})


# ---------------------------------------------------------------------------
# Tool 8: mp_create_custom_list
# ---------------------------------------------------------------------------

@mcp.tool()
async def mp_create_custom_list(name: str, tickers: str) -> str:
    """Create a named custom ticker list for use in pull and query commands.

    Args:
        name: Name for the custom list (e.g. "my-watchlist").
        tickers: Comma-separated ticker symbols (e.g. "AAPL,MSFT,GOOG").
    """
    _import_lib()
    from skills.marketpulse.lib.indices import IndexManager
    ticker_list = [t.strip().upper() for t in tickers.split(",") if t.strip()]
    if not ticker_list:
        return json.dumps({"error": "No tickers provided."})
    idx_mgr = IndexManager()
    try:
        index = idx_mgr.create_custom_list(name, ticker_list)
    except ValueError as e:
        return json.dumps({"error": str(e)})
    return json.dumps({
        "name": index.short_name,
        "ticker_count": len(index.constituents),
        "tickers": index.tickers,
    })


# ---------------------------------------------------------------------------
# Tool 9: mp_analyze
# ---------------------------------------------------------------------------

# Dispatch map for analytics functions.  Sector functions and garman_klass_vol
# are handled specially (see below).
_ANALYTICS_FUNCTIONS = {
    "daily_summary": lambda df, p: _ana().daily_summary(df, tickers=p.get("tickers")),
    "biggest_movers": lambda df, p: _ana().biggest_movers(df, date_str=p["date_str"], n=p.get("n", 10)),
    "volume_analysis": lambda df, p: _ana().volume_analysis(df, tickers=p.get("tickers")),
    "realized_volatility": lambda df, p: _ana().realized_volatility(df, window=p.get("window", "1d"), tickers=p.get("tickers")),
    "intraday_vol_profile": lambda df, p: _ana().intraday_vol_profile(df, ticker=p["ticker"], bucket_minutes=p.get("bucket_minutes", 30)),
    "vol_surface": lambda df, p: _ana().vol_surface(df, windows=p.get("windows"), tickers=p.get("tickers")),
    "garman_klass_vol": None,  # returns list[GarmanKlassResult], handled specially
    "pairwise_correlation": lambda df, p: _ana().pairwise_correlation(df, tickers=p.get("tickers")),
    "sector_correlation": None,  # sector function -- handled specially
    "rolling_correlation": lambda df, p: _ana().rolling_correlation(df, ticker_a=p["ticker_a"], ticker_b=p["ticker_b"], window=p.get("window", 21)),
    "intraday_patterns": lambda df, p: _ana().intraday_patterns(df, ticker=p["ticker"], bucket_minutes=p.get("bucket_minutes", 30)),
    "day_of_week_effects": lambda df, p: _ana().day_of_week_effects(df, ticker=p["ticker"]),
    "monthly_seasonality": lambda df, p: _ana().monthly_seasonality(df, ticker=p["ticker"]),
    "sector_rotation": None,  # sector function -- handled specially
    "sector_heatmap": None,  # sector function -- handled specially
    "relative_strength": None,  # sector function -- handled specially
}

_SECTOR_FUNCTIONS = {"sector_rotation", "sector_heatmap", "relative_strength", "sector_correlation"}
_SINGLE_TICKER_FUNCTIONS = {"intraday_patterns", "intraday_vol_profile", "day_of_week_effects", "monthly_seasonality"}


class _AnalyticsProxy:
    """Lazy proxy that imports analytics functions on first access."""

    def __getattr__(self, name: str):
        _import_lib()
        from skills.marketpulse.lib import analytics as _analytics_mod
        return getattr(_analytics_mod, name)


_analytics_proxy: _AnalyticsProxy | None = None


def _ana() -> _AnalyticsProxy:
    global _analytics_proxy
    if _analytics_proxy is None:
        _analytics_proxy = _AnalyticsProxy()
    return _analytics_proxy


@mcp.tool()
async def mp_analyze(
    function: str,
    tickers: str,
    from_date: str,
    to_date: str,
    timespan: str = "1min",
    params: str = "{}",
) -> str:
    """Run an analytics function against cached bar data.

    Args:
        function: Analytics function name. Options:
            daily_summary, biggest_movers, volume_analysis,
            realized_volatility, intraday_vol_profile, vol_surface, garman_klass_vol,
            pairwise_correlation, sector_correlation, rolling_correlation,
            intraday_patterns, day_of_week_effects, monthly_seasonality,
            sector_rotation, sector_heatmap, relative_strength
        tickers: Comma-separated ticker symbols or index name (e.g. "AAPL,MSFT" or "SP500").
        from_date: Start date in YYYY-MM-DD format.
        to_date: End date in YYYY-MM-DD format.
        timespan: Bar size -- 1min, 5min, 15min, 1hour, or 1day (default: 1min).
        params: JSON string of additional function parameters
                (e.g. '{"n": 5}' for biggest_movers, '{"date_str": "2022-01-03"}' for biggest_movers,
                '{"ticker": "AAPL"}' for single-ticker functions like intraday_patterns).
    """
    # Validate function name
    if function not in _ANALYTICS_FUNCTIONS:
        valid = ", ".join(sorted(_ANALYTICS_FUNCTIONS.keys()))
        return json.dumps({"error": f"Unknown function '{function}'. Valid options: {valid}"})

    # Initialize stack
    err = await _ensure_init()
    if err:
        return json.dumps({"error": err})

    # Validate timespan
    if timespan not in _cache_mod.TIMESPAN_MAP:
        valid = ", ".join(_cache_mod.TIMESPAN_MAP.keys())
        return json.dumps({"error": f"Invalid timespan '{timespan}'. Valid options: {valid}"})

    # Parse dates
    try:
        start_dt = date.fromisoformat(from_date)
    except (ValueError, TypeError):
        return json.dumps({"error": f"Invalid from_date '{from_date}'. Use YYYY-MM-DD format."})

    try:
        end_dt = date.fromisoformat(to_date)
    except (ValueError, TypeError):
        return json.dumps({"error": f"Invalid to_date '{to_date}'. Use YYYY-MM-DD format."})

    if start_dt > end_dt:
        return json.dumps({"error": "from_date must be before or equal to to_date."})

    # Resolve tickers (index name or comma-separated list)
    _import_lib()
    from skills.marketpulse.lib.indices import IndexManager, IndexNotFoundError

    idx_mgr = IndexManager()
    index_name_used: str | None = None
    if idx_mgr.is_index(tickers.strip()):
        try:
            index = idx_mgr.get_index(tickers.strip())
        except IndexNotFoundError as e:
            return json.dumps({"error": str(e)})
        if not index.tickers:
            return json.dumps({"error": f"Index '{tickers.strip().upper()}' has no tickers."})
        ticker_list = index.tickers
        index_name_used = tickers.strip()
    else:
        ticker_list = [t.strip().upper() for t in tickers.split(",") if t.strip()]
    if not ticker_list:
        return json.dumps({"error": "No tickers provided."})

    # Load bars
    try:
        df = await _cache_manager.get_bars_df(
            tickers=ticker_list,
            timespan=timespan,
            from_date=start_dt,
            to_date=end_dt,
        )
    except Exception as exc:
        return json.dumps({"error": f"Failed to load bars: {exc}"})

    if df.empty:
        return json.dumps({"error": "No bar data found for the given tickers and date range. Pull data first with mp_pull_bars."})

    # Parse extra params
    try:
        p = json.loads(params) if isinstance(params, str) else params
    except json.JSONDecodeError as exc:
        return json.dumps({"error": f"Invalid params JSON: {exc}"})

    # Validate required params for specific functions
    if function in _SINGLE_TICKER_FUNCTIONS and "ticker" not in p:
        return json.dumps({"error": f"Function '{function}' requires 'ticker' in params (e.g. params='{{\"ticker\": \"AAPL\"}}')."})
    if function == "rolling_correlation":
        if "ticker_a" not in p or "ticker_b" not in p:
            return json.dumps({"error": "Function 'rolling_correlation' requires 'ticker_a' and 'ticker_b' in params."})
    if function == "biggest_movers" and "date_str" not in p:
        return json.dumps({"error": "Function 'biggest_movers' requires 'date_str' in params (e.g. params='{{\"date_str\": \"2022-01-03\"}}')."})

    # Dispatch
    try:
        if function == "garman_klass_vol":
            # Returns list[GarmanKlassResult], not a single AnalyticsResult
            result_list = _ana().garman_klass_vol(df, tickers=p.get("tickers"))
            return json.dumps({"results": [r.to_dict() for r in result_list]})

        if function in _SECTOR_FUNCTIONS:
            # Load sector map
            from skills.marketpulse.lib.analytics.types import load_sector_map

            if index_name_used:
                sector_map = load_sector_map(index_name_used)
            else:
                sector_map = load_sector_map()  # all indices

            if function == "sector_rotation":
                result = _ana().sector_rotation(df, sector_map)
            elif function == "sector_heatmap":
                result = _ana().sector_heatmap(df, sector_map)
            elif function == "sector_correlation":
                result = _ana().sector_correlation(df, sector_map)
            elif function == "relative_strength":
                result = _ana().relative_strength(df, sector_map, benchmark_tickers=p.get("benchmark_tickers"))
            return json.dumps(result.to_dict())

        # Standard dispatch
        handler = _ANALYTICS_FUNCTIONS[function]
        result = handler(df, p)
        return json.dumps(result.to_dict())

    except KeyError as exc:
        return json.dumps({"error": f"Missing required parameter: {exc}"})
    except Exception as exc:
        return json.dumps({"error": f"Analytics function '{function}' failed: {exc}"})


# ---------------------------------------------------------------------------
# Tool 10: mp_detect_events
# ---------------------------------------------------------------------------

_EVENT_FUNCTIONS = {
    "volume_spikes": "volume_spikes",
    "price_gaps": "price_gaps",
    "anomaly_detection": "anomaly_detection",
}


@mcp.tool()
async def mp_detect_events(
    event_type: str,
    tickers: str,
    from_date: str,
    to_date: str,
    timespan: str = "1min",
    threshold: float = 3.0,
) -> str:
    """Detect market events in cached bar data.

    Args:
        event_type: Type of event: volume_spikes, price_gaps, or anomaly_detection.
        tickers: Comma-separated tickers or index name.
        from_date: Start date (YYYY-MM-DD).
        to_date: End date (YYYY-MM-DD).
        timespan: Bar size (default: 1min).
        threshold: Detection threshold (default: 3.0).
    """
    # Validate event type
    if event_type not in _EVENT_FUNCTIONS:
        valid = ", ".join(sorted(_EVENT_FUNCTIONS.keys()))
        return json.dumps({"error": f"Unknown event_type '{event_type}'. Valid options: {valid}"})

    # Initialize stack
    err = await _ensure_init()
    if err:
        return json.dumps({"error": err})

    # Validate timespan
    if timespan not in _cache_mod.TIMESPAN_MAP:
        valid = ", ".join(_cache_mod.TIMESPAN_MAP.keys())
        return json.dumps({"error": f"Invalid timespan '{timespan}'. Valid options: {valid}"})

    # Parse dates
    try:
        start_dt = date.fromisoformat(from_date)
    except (ValueError, TypeError):
        return json.dumps({"error": f"Invalid from_date '{from_date}'. Use YYYY-MM-DD format."})

    try:
        end_dt = date.fromisoformat(to_date)
    except (ValueError, TypeError):
        return json.dumps({"error": f"Invalid to_date '{to_date}'. Use YYYY-MM-DD format."})

    if start_dt > end_dt:
        return json.dumps({"error": "from_date must be before or equal to to_date."})

    # Resolve tickers
    _import_lib()
    from skills.marketpulse.lib.indices import IndexManager, IndexNotFoundError

    idx_mgr = IndexManager()
    if idx_mgr.is_index(tickers.strip()):
        try:
            index = idx_mgr.get_index(tickers.strip())
        except IndexNotFoundError as e:
            return json.dumps({"error": str(e)})
        if not index.tickers:
            return json.dumps({"error": f"Index '{tickers.strip().upper()}' has no tickers."})
        ticker_list = index.tickers
    else:
        ticker_list = [t.strip().upper() for t in tickers.split(",") if t.strip()]
    if not ticker_list:
        return json.dumps({"error": "No tickers provided."})

    # Load bars
    try:
        df = await _cache_manager.get_bars_df(
            tickers=ticker_list,
            timespan=timespan,
            from_date=start_dt,
            to_date=end_dt,
        )
    except Exception as exc:
        return json.dumps({"error": f"Failed to load bars: {exc}"})

    if df.empty:
        return json.dumps({"error": "No bar data found for the given tickers and date range. Pull data first with mp_pull_bars."})

    # Dispatch to the correct event function
    try:
        func = getattr(_ana(), _EVENT_FUNCTIONS[event_type])
        if event_type == "anomaly_detection":
            result = func(df, z_threshold=threshold, tickers=ticker_list)
        elif event_type == "volume_spikes":
            result = func(df, threshold=threshold, tickers=ticker_list)
        elif event_type == "price_gaps":
            result = func(df, threshold=threshold, tickers=ticker_list)
        return json.dumps(result.to_dict())
    except Exception as exc:
        return json.dumps({"error": f"Event detection '{event_type}' failed: {exc}"})


# ---------------------------------------------------------------------------
# Tool 11: mp_event_impact
# ---------------------------------------------------------------------------

@mcp.tool()
async def mp_event_impact(
    ticker: str,
    event_date: str,
    from_date: str,
    to_date: str,
    pre_days: int = 5,
    post_days: int = 5,
    timespan: str = "1min",
) -> str:
    """Analyze impact of a specific event on a ticker's price and volume.

    Args:
        ticker: Single ticker symbol.
        event_date: Date of the event (YYYY-MM-DD).
        from_date: Start of data range.
        to_date: End of data range.
        pre_days: Trading days before event (default: 5).
        post_days: Trading days after event (default: 5).
        timespan: Bar size (default: 1min).
    """
    # Initialize stack
    err = await _ensure_init()
    if err:
        return json.dumps({"error": err})

    # Validate timespan
    if timespan not in _cache_mod.TIMESPAN_MAP:
        valid = ", ".join(_cache_mod.TIMESPAN_MAP.keys())
        return json.dumps({"error": f"Invalid timespan '{timespan}'. Valid options: {valid}"})

    # Parse dates
    try:
        start_dt = date.fromisoformat(from_date)
    except (ValueError, TypeError):
        return json.dumps({"error": f"Invalid from_date '{from_date}'. Use YYYY-MM-DD format."})

    try:
        end_dt = date.fromisoformat(to_date)
    except (ValueError, TypeError):
        return json.dumps({"error": f"Invalid to_date '{to_date}'. Use YYYY-MM-DD format."})

    if start_dt > end_dt:
        return json.dumps({"error": "from_date must be before or equal to to_date."})

    # Validate event_date format
    try:
        date.fromisoformat(event_date)
    except (ValueError, TypeError):
        return json.dumps({"error": f"Invalid event_date '{event_date}'. Use YYYY-MM-DD format."})

    ticker = ticker.strip().upper()
    if not ticker:
        return json.dumps({"error": "No ticker provided."})

    # Load bars
    try:
        df = await _cache_manager.get_bars_df(
            tickers=[ticker],
            timespan=timespan,
            from_date=start_dt,
            to_date=end_dt,
        )
    except Exception as exc:
        return json.dumps({"error": f"Failed to load bars: {exc}"})

    if df.empty:
        return json.dumps({"error": f"No bar data found for '{ticker}' in the given date range. Pull data first with mp_pull_bars."})

    # Run event impact analysis
    try:
        result = _ana().event_impact(
            df,
            ticker=ticker,
            event_date=event_date,
            pre_days=pre_days,
            post_days=post_days,
        )
        return json.dumps(result.to_dict())
    except Exception as exc:
        return json.dumps({"error": f"Event impact analysis failed: {exc}"})


# ---------------------------------------------------------------------------
# Tool 12: mp_export_data
# ---------------------------------------------------------------------------

@mcp.tool()
async def mp_export_data(
    tickers: str,
    from_date: str,
    to_date: str,
    format: str = "excel",
    timespan: str = "1min",
    output_path: str = "",
) -> str:
    """Export cached bar data or analytics results to a file.

    Supports Excel (.xlsx with formatting), CSV, and Parquet formats.
    Default output location is the user's Desktop.

    Args:
        tickers: Comma-separated tickers or index name (e.g. "AAPL,MSFT" or "SP500").
        from_date: Start date (YYYY-MM-DD).
        to_date: End date (YYYY-MM-DD).
        format: Output format -- "excel", "csv", or "parquet" (default: "excel").
        timespan: Bar size -- 1min, 5min, 15min, 1hour, or 1day (default: 1min).
        output_path: Optional file path. Empty = auto-generate on Desktop.
    """
    # Initialize stack
    err = await _ensure_init()
    if err:
        return json.dumps({"error": err})

    # Validate format
    valid_formats = ("excel", "csv", "parquet")
    if format not in valid_formats:
        return json.dumps({"error": f"Invalid format '{format}'. Valid options: {', '.join(valid_formats)}"})

    # Validate timespan
    if timespan not in _cache_mod.TIMESPAN_MAP:
        valid = ", ".join(_cache_mod.TIMESPAN_MAP.keys())
        return json.dumps({"error": f"Invalid timespan '{timespan}'. Valid options: {valid}"})

    # Parse dates
    try:
        start_dt = date.fromisoformat(from_date)
    except (ValueError, TypeError):
        return json.dumps({"error": f"Invalid from_date '{from_date}'. Use YYYY-MM-DD format."})

    try:
        end_dt = date.fromisoformat(to_date)
    except (ValueError, TypeError):
        return json.dumps({"error": f"Invalid to_date '{to_date}'. Use YYYY-MM-DD format."})

    if start_dt > end_dt:
        return json.dumps({"error": "from_date must be before or equal to to_date."})

    # Resolve tickers
    _import_lib()
    from skills.marketpulse.lib.indices import IndexManager, IndexNotFoundError

    idx_mgr = IndexManager()
    if idx_mgr.is_index(tickers.strip()):
        try:
            index = idx_mgr.get_index(tickers.strip())
        except IndexNotFoundError as e:
            return json.dumps({"error": str(e)})
        if not index.tickers:
            return json.dumps({"error": f"Index '{tickers.strip().upper()}' has no tickers."})
        ticker_list = index.tickers
    else:
        ticker_list = [t.strip().upper() for t in tickers.split(",") if t.strip()]
    if not ticker_list:
        return json.dumps({"error": "No tickers provided."})

    # Load bars with higher limit for exports
    try:
        df = await _cache_manager.get_bars_df(
            tickers=ticker_list,
            timespan=timespan,
            from_date=start_dt,
            to_date=end_dt,
            max_rows=500_000,
        )
    except Exception as exc:
        return json.dumps({"error": f"Failed to load bars: {exc}"})

    if df.empty:
        return json.dumps({"error": "No bar data found. Pull data first with mp_pull_bars."})

    # Export
    try:
        from skills.marketpulse.lib.export import to_excel, to_csv, to_parquet

        out_path = output_path if output_path.strip() else None

        if format == "excel":
            result_path = to_excel(df, path=out_path)
        elif format == "csv":
            result_path = to_csv(df, path=out_path)
        elif format == "parquet":
            result_path = to_parquet(df, path=out_path)

        return json.dumps({
            "file_path": str(result_path),
            "format": format,
            "row_count": len(df),
            "tickers": len(ticker_list),
        })
    except Exception as exc:
        return json.dumps({"error": f"Export failed: {exc}"})


# ---------------------------------------------------------------------------
# Tool 13: mp_generate_report
# ---------------------------------------------------------------------------

_REPORT_TYPES = {"daily", "period", "correlation", "event_study"}


@mcp.tool()
async def mp_generate_report(
    report_type: str,
    tickers: str,
    from_date: str,
    to_date: str,
    timespan: str = "1min",
    params: str = "{}",
    output_path: str = "",
) -> str:
    """Generate a pre-built analysis report as a formatted Excel workbook.

    Report types:
    - "daily": Single-day market report (summary + movers + sector heatmap).
              Requires params: {"date": "2022-06-03"} (or uses from_date).
    - "period": Full analytics suite over a date range (multi-sheet workbook).
    - "correlation": Correlation analysis (requires >1 ticker).
    - "event_study": Event impact study for a single ticker.
              Requires params: {"ticker": "AAPL", "event_date": "2022-06-03"}.

    Args:
        report_type: Report type -- "daily", "period", "correlation", or "event_study".
        tickers: Comma-separated tickers or index name.
        from_date: Start date (YYYY-MM-DD).
        to_date: End date (YYYY-MM-DD).
        timespan: Bar size (default: 1min).
        params: JSON string of report-specific parameters.
                Daily: {"index": "SP500"} for sector mapping.
                Event: {"ticker": "AAPL", "event_date": "2022-06-03", "pre_days": 5, "post_days": 5}.
        output_path: Optional file path. Empty = auto-generate on Desktop.
    """
    # Validate report type
    if report_type not in _REPORT_TYPES:
        valid = ", ".join(sorted(_REPORT_TYPES))
        return json.dumps({"error": f"Unknown report_type '{report_type}'. Valid options: {valid}"})

    # Initialize stack
    err = await _ensure_init()
    if err:
        return json.dumps({"error": err})

    # Validate timespan
    if timespan not in _cache_mod.TIMESPAN_MAP:
        valid = ", ".join(_cache_mod.TIMESPAN_MAP.keys())
        return json.dumps({"error": f"Invalid timespan '{timespan}'. Valid options: {valid}"})

    # Parse dates
    try:
        start_dt = date.fromisoformat(from_date)
    except (ValueError, TypeError):
        return json.dumps({"error": f"Invalid from_date '{from_date}'. Use YYYY-MM-DD format."})

    try:
        end_dt = date.fromisoformat(to_date)
    except (ValueError, TypeError):
        return json.dumps({"error": f"Invalid to_date '{to_date}'. Use YYYY-MM-DD format."})

    if start_dt > end_dt:
        return json.dumps({"error": "from_date must be before or equal to to_date."})

    # Parse extra params
    try:
        p = json.loads(params) if isinstance(params, str) else params
    except json.JSONDecodeError as exc:
        return json.dumps({"error": f"Invalid params JSON: {exc}"})

    # Resolve tickers
    _import_lib()
    from skills.marketpulse.lib.indices import IndexManager, IndexNotFoundError

    idx_mgr = IndexManager()
    index_name_used: str | None = None
    if idx_mgr.is_index(tickers.strip()):
        try:
            index = idx_mgr.get_index(tickers.strip())
        except IndexNotFoundError as e:
            return json.dumps({"error": str(e)})
        if not index.tickers:
            return json.dumps({"error": f"Index '{tickers.strip().upper()}' has no tickers."})
        ticker_list = index.tickers
        index_name_used = tickers.strip()
    else:
        ticker_list = [t.strip().upper() for t in tickers.split(",") if t.strip()]
    if not ticker_list:
        return json.dumps({"error": "No tickers provided."})

    out_path = output_path if output_path.strip() else None
    idx_param = p.get("index", index_name_used)

    # Dispatch to report template
    try:
        from skills.marketpulse.lib import reports as _reports_mod

        if report_type == "daily":
            report_date = date.fromisoformat(p.get("date", from_date))
            result_path = await _reports_mod.daily_market_report(
                _cache_manager, ticker_list, report_date,
                timespan=timespan, index_name=idx_param, output=out_path,
            )

        elif report_type == "period":
            result_path = await _reports_mod.period_analysis_report(
                _cache_manager, ticker_list, start_dt, end_dt,
                timespan=timespan, index_name=idx_param, output=out_path,
            )

        elif report_type == "correlation":
            result_path = await _reports_mod.correlation_report(
                _cache_manager, ticker_list, start_dt, end_dt,
                timespan=timespan, index_name=idx_param, output=out_path,
            )

        elif report_type == "event_study":
            event_ticker = p.get("ticker", ticker_list[0] if ticker_list else "")
            event_date_str = p.get("event_date", from_date)
            event_dt = date.fromisoformat(event_date_str)
            pre_days = int(p.get("pre_days", 5))
            post_days = int(p.get("post_days", 5))

            result_path = await _reports_mod.event_study_report(
                _cache_manager, event_ticker, event_dt, start_dt, end_dt,
                pre_days=pre_days, post_days=post_days,
                timespan=timespan, output=out_path,
            )

        return json.dumps({
            "file_path": str(result_path),
            "report_type": report_type,
        })

    except ValueError as exc:
        return json.dumps({"error": str(exc)})
    except Exception as exc:
        return json.dumps({"error": f"Report generation failed: {exc}"})


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    log("Launching MarketPulse MCP server on stdio transport")
    mcp.run(transport="stdio")
