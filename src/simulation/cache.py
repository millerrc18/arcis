"""OHLCV data cache for simulation engine — avoids re-fetching from yfinance.

First run downloads all data (~20 min for 13 scenarios x 103 tickers).
Subsequent runs: <2 min reading from parquet cache.

Cache location: data/simulation_cache/
Cache key format: {ticker}_{start}_{end}.parquet
Cache invalidation: manual delete or --clear-cache CLI flag
"""

import logging
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import yfinance as yf

from src.universe.sp100 import to_yfinance_ticker

logger = logging.getLogger(__name__)
CACHE_DIR = Path("data/simulation_cache")


def _subtract_days(date_str: str, days: int) -> str:
    """Subtract calendar days from a YYYY-MM-DD string."""
    return (datetime.strptime(date_str, "%Y-%m-%d") - timedelta(days=days)).strftime("%Y-%m-%d")


def _add_days(date_str: str, days: int) -> str:
    """Add calendar days to a YYYY-MM-DD string."""
    return (datetime.strptime(date_str, "%Y-%m-%d") + timedelta(days=days)).strftime("%Y-%m-%d")


def fetch_cached_ohlcv(ticker: str, start: str, end: str,
                        cache_dir: Path = CACHE_DIR) -> pd.DataFrame | None:
    """Fetch OHLCV from cache or yfinance. Cache as parquet for speed."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    safe_ticker = ticker.replace(".", "_").replace("/", "_")
    cache_key = f"{safe_ticker}_{start}_{end}.parquet"
    cache_path = cache_dir / cache_key

    if cache_path.exists():
        return pd.read_parquet(cache_path)

    try:
        data = yf.download(to_yfinance_ticker(ticker), start=start, end=end,
                           progress=False, auto_adjust=True)
        if data is not None and not data.empty:
            if isinstance(data.columns, pd.MultiIndex):
                data.columns = data.columns.get_level_values(0)
            data.to_parquet(cache_path)
            return data
    except Exception as e:
        logger.warning("[SIM-CACHE] Failed to fetch %s: %s", ticker, e)
    return None


def warm_cache(scenarios: dict, universe: list[str],
               cache_dir: Path = CACHE_DIR) -> dict:
    """Pre-download all OHLCV data for all scenarios. Returns stats."""
    total = 0
    cached = 0
    failed = 0
    for _name, dates in scenarios.items():
        extended_start = _subtract_days(dates["start"], 60)
        extended_end = _add_days(dates["end"], 20)
        for ticker in universe:
            total += 1
            result = fetch_cached_ohlcv(ticker, extended_start, extended_end, cache_dir)
            if result is not None:
                cached += 1
            else:
                failed += 1
            if total % 50 == 0:
                print(f"  Cache warming: {total} fetched, {failed} failed")
    # Also cache SPY and VIX
    for idx_ticker in ["SPY", "^VIX"]:
        for _name, dates in scenarios.items():
            fetch_cached_ohlcv(idx_ticker, _subtract_days(dates["start"], 60),
                               _add_days(dates["end"], 20), cache_dir)
    return {"total": total, "cached": cached, "failed": failed}


def clear_cache(cache_dir: Path = CACHE_DIR):
    """Delete all cached parquet files."""
    import shutil
    if cache_dir.exists():
        shutil.rmtree(cache_dir)
        logger.info("[SIM-CACHE] Cache cleared: %s", cache_dir)
