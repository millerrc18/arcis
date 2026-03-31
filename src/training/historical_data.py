"""Historical data fetcher with point-in-time slicing for backfill engine.

Called by: training.backfill, training.historical_scanner
Calls: universe.sp100
Owns tables: none
Config keys: none
Tests: tests/test_backfill.py, tests/test_leakage_detector.py

Downloads bulk OHLCV data and provides point-in-time slicing to prevent
lookahead bias in historical feature computation.
"""

import logging
import os
import pickle
import time
from datetime import datetime, timedelta

import pandas as pd

from src.universe.sp100 import get_sp100_universe

logger = logging.getLogger(__name__)

CACHE_DIR = "training_data"
CACHE_FILE = os.path.join(CACHE_DIR, "historical_ohlcv.pkl")


def fetch_historical_universe(lookback_years: int = 2) -> dict:
    """Download historical daily OHLCV data for the S&P 100 + SPY.

    Uses yfinance for batch download. Caches to disk as pickle; reuses
    cache if it's less than 24 hours old.

    Returns:
        {
            "spy": pd.DataFrame,
            "tickers": { "AAPL": pd.DataFrame, ... },
            "start_date": "2024-03-24",
            "end_date": "2026-03-24",
        }
    """
    # Check cache
    if os.path.exists(CACHE_FILE):
        cache_age = time.time() - os.path.getmtime(CACHE_FILE)
        if cache_age < 86400:  # 24 hours
            logger.info("[BACKFILL] Loading cached data from %s", CACHE_FILE)
            logger.info("[BACKFILL] Loading cached data (age: %.1fh)", cache_age / 3600)
            with open(CACHE_FILE, "rb") as f:
                return pickle.load(f)

    import yfinance as yf

    universe = get_sp100_universe()
    all_tickers = universe + ["SPY"]
    n = len(all_tickers)

    end_date = datetime.now()
    start_date = end_date - timedelta(days=lookback_years * 365)
    start_str = start_date.strftime("%Y-%m-%d")
    end_str = end_date.strftime("%Y-%m-%d")

    logger.info("[BACKFILL] Downloading %d years of data for %d tickers...", lookback_years, n)
    logger.info("[BACKFILL] Downloading %d tickers, %s to %s", n, start_str, end_str)

    raw = yf.download(
        all_tickers,
        start=start_str,
        end=end_str,
        group_by="ticker",
        auto_adjust=True,
        threads=True,
        progress=False,
    )

    # Parse the multi-level columns into per-ticker DataFrames
    tickers_data = {}
    spy_df = pd.DataFrame()

    for ticker in all_tickers:
        try:
            if len(all_tickers) == 1:
                df = raw.copy()
            else:
                df = raw[ticker].copy()

            # Drop rows where Close is NaN
            df = df.dropna(subset=["Close"])
            if df.empty:
                continue

            if ticker == "SPY":
                spy_df = df
            else:
                tickers_data[ticker] = df
        except (KeyError, TypeError):
            logger.warning("[BACKFILL] Failed to parse data for %s", ticker)
            continue

    # Determine actual date range
    if not spy_df.empty:
        actual_start = spy_df.index.min().strftime("%Y-%m-%d")
        actual_end = spy_df.index.max().strftime("%Y-%m-%d")
    else:
        actual_start = start_str
        actual_end = end_str

    result = {
        "spy": spy_df,
        "tickers": tickers_data,
        "start_date": actual_start,
        "end_date": actual_end,
    }

    logger.info("[BACKFILL] Downloaded %d tickers, %s to %s", len(tickers_data), actual_start, actual_end)
    logger.info("[BACKFILL] Downloaded %d tickers, %s to %s",
                len(tickers_data), actual_start, actual_end)

    # Cache to disk
    os.makedirs(CACHE_DIR, exist_ok=True)
    with open(CACHE_FILE, "wb") as f:
        pickle.dump(result, f)
    logger.info("[BACKFILL] Cached data to %s", CACHE_FILE)

    return result


def slice_to_date(data: dict, as_of_date: str) -> tuple[dict, pd.DataFrame]:
    """Slice all historical data to simulate what was available on a given date.

    This is the critical anti-lookahead function. For each ticker DataFrame,
    only rows with index <= as_of_date are returned.

    Args:
        data: Output of fetch_historical_universe().
        as_of_date: ISO date string, e.g. "2025-06-15".

    Returns:
        (ohlcv_dict, spy_df) where both are truncated to <= as_of_date.
        Tickers with fewer than 200 rows as-of that date are skipped.
    """
    cutoff = pd.Timestamp(as_of_date)

    # Slice SPY
    spy_full = data["spy"]
    spy_sliced = spy_full[spy_full.index <= cutoff]

    # Slice each ticker
    ohlcv_dict = {}
    for ticker, df in data["tickers"].items():
        sliced = df[df.index <= cutoff]
        if len(sliced) < 200:
            continue
        ohlcv_dict[ticker] = sliced

    return ohlcv_dict, spy_sliced
