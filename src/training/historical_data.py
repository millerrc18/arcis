"""Historical data fetcher with point-in-time slicing for backfill engine.

Called by: training.backfill, training.historical_scanner, scripts.export_backfill_prompts
Calls: universe.sp100, data_collection.macro_collector
Owns tables: none
Config keys: none
Tests: tests/test_backfill.py, tests/test_leakage_detector.py, tests/test_fred_history.py

Downloads bulk OHLCV data and provides point-in-time slicing to prevent
lookahead bias in historical feature computation. Also fetches FRED
macro history for point-in-time macro context in backfill prompts.
"""

import logging
import os
import pickle
import time
from datetime import datetime, timedelta

import pandas as pd

from src.universe.pit import get_sp100_at

logger = logging.getLogger(__name__)

CACHE_DIR = "training_data"
CACHE_FILE = os.path.join(CACHE_DIR, "historical_ohlcv.pkl")
FRED_CACHE_FILE = os.path.join(CACHE_DIR, "fred_history.pkl")

# Core FRED series for backfill macro context
FRED_BACKFILL_SERIES = ["VIXCLS", "T10Y2Y", "UNRATE", "FEDFUNDS"]


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

    end_date = datetime.now()
    start_date = end_date - timedelta(days=lookback_years * 365)
    start_str = start_date.strftime("%Y-%m-%d")
    end_str = end_date.strftime("%Y-%m-%d")

    universe = get_sp100_at(start_date.date().isoformat())  # T10: as_of source: start_date at historical_data.py:64
    all_tickers = universe + ["SPY"]
    n = len(all_tickers)

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
    if spy_full.empty:
        # An empty DataFrame has a RangeIndex (Int64), not a DatetimeIndex,
        # so `spy_full.index <= cutoff` raises TypeError ('numpy.ndarray' vs
        # 'Timestamp'). Surface a useful error instead of the cryptic comparison
        # crash. The most common cause is fetch_spy_benchmark hitting a yfinance
        # timeout — the caller should retry or fail loudly rather than slicing
        # an empty benchmark.
        raise ValueError(
            f"slice_to_date: SPY benchmark DataFrame is empty (as_of={as_of_date}). "
            "This typically means fetch_spy_benchmark hit a yfinance timeout. "
            "Retry the fetch or surface the failure — slicing empty benchmark "
            "data is meaningless for the downstream feature pipeline."
        )
    spy_sliced = spy_full[spy_full.index <= cutoff]

    # Slice each ticker
    ohlcv_dict = {}
    for ticker, df in data["tickers"].items():
        sliced = df[df.index <= cutoff]
        if len(sliced) < 200:
            continue
        ohlcv_dict[ticker] = sliced

    return ohlcv_dict, spy_sliced


def fetch_fred_history(
    start_year: int = 2021,
    end_year: int = 2025,
) -> dict[str, pd.Series]:
    """Fetch full FRED time series for backfill macro context.

    Downloads daily/monthly observations for VIXCLS, T10Y2Y, UNRATE,
    FEDFUNDS from 2021-01-01 through end_year-12-31. Caches to
    training_data/fred_history.pkl (reuses if <7 days old).

    Returns:
        {"VIXCLS": pd.Series(index=DatetimeIndex, values=float), ...}
    """
    if os.path.exists(FRED_CACHE_FILE):
        cache_age = time.time() - os.path.getmtime(FRED_CACHE_FILE)
        if cache_age < 7 * 86400:  # 7 days
            logger.info("[FRED] Loading cached FRED history from %s", FRED_CACHE_FILE)
            with open(FRED_CACHE_FILE, "rb") as f:
                return pickle.load(f)

    import requests

    from src.data_collection.macro_collector import _get_fred_api_key

    api_key = _get_fred_api_key()
    if not api_key:
        logger.warning("[FRED] No FRED API key — returning empty history")
        return {}

    fred_base = "https://api.stlouisfed.org/fred/series/observations"
    start_str = f"{start_year}-01-01"
    end_str = f"{end_year}-12-31"
    result = {}

    for series_id in FRED_BACKFILL_SERIES:
        try:
            resp = requests.get(
                fred_base,
                params={
                    "series_id": series_id,
                    "api_key": api_key,
                    "observation_start": start_str,
                    "observation_end": end_str,
                    "file_type": "json",
                },
                timeout=30,
            )
            resp.raise_for_status()
            observations = resp.json().get("observations", [])

            dates = []
            values = []
            for obs in observations:
                if obs.get("value", ".") != ".":
                    dates.append(pd.Timestamp(obs["date"]))
                    values.append(float(obs["value"]))

            if dates:
                series = pd.Series(values, index=pd.DatetimeIndex(dates), name=series_id)
                result[series_id] = series
                logger.info("[FRED] Fetched %s: %d observations", series_id, len(series))
            else:
                logger.warning("[FRED] No data for %s", series_id)

        except Exception as e:
            logger.warning("[FRED] Failed to fetch %s: %s", series_id, e)
            continue

    # Cache to disk
    os.makedirs(CACHE_DIR, exist_ok=True)
    with open(FRED_CACHE_FILE, "wb") as f:
        pickle.dump(result, f)
    logger.info("[FRED] Cached %d series to %s", len(result), FRED_CACHE_FILE)

    return result


def get_fred_value_as_of(
    fred_data: dict[str, pd.Series],
    series_id: str,
    as_of_date: str,
) -> float | None:
    """Look up the most recent FRED value on or before a given date.

    Point-in-time lookup: returns the latest observation whose date is
    <= as_of_date. This prevents lookahead bias — a Feb 15 lookup
    returns the Feb value (or Jan if Feb hasn't published yet), never March.

    Args:
        fred_data: Output of fetch_fred_history().
        series_id: E.g. "VIXCLS".
        as_of_date: ISO date string.

    Returns:
        The float value, or None if no observation exists before that date.
    """
    series = fred_data.get(series_id)
    if series is None or series.empty:
        return None

    cutoff = pd.Timestamp(as_of_date)
    available = series[series.index <= cutoff]
    if available.empty:
        return None

    return float(available.iloc[-1])
