"""SPY-matched excess return calculations — SD#41 REVISED / Sprint D1.

Converts Sharpe metrics from raw to excess by subtracting SPY's return
over the same date range. Distinguishes alpha from bull-market beta drift.

Called by: journal.store (close_shadow_trade hook), scripts.backfill_spy_excess,
           api.cloud_routes.trades (sharpe-attribution endpoint)
Calls: yfinance (SPY download), src.universe.sp100 (via GICS CSV)
Owns tables: none (writes flow through journal.store.update_shadow_trade)
Config keys: none
Tests: tests/analytics/test_spy_benchmark.py
"""

from __future__ import annotations

import csv
import datetime as dt
import logging
from functools import lru_cache
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Reference-data convention: data/ is gitignored except data/reference/**.
# Keeping the lookup there marks it as static, tracked, human-edited input.
_SECTOR_LOOKUP_PATH = Path("data/reference/sp100-gics-lookup.csv")


@lru_cache(maxsize=1)
def _load_sector_lookup() -> dict[str, str]:
    """Load the GICS ticker->sector map once; cached for the process lifetime.

    Returns an empty dict (not None) when the file is missing so callers
    don't have to null-check every lookup.
    """
    if not _SECTOR_LOOKUP_PATH.exists():
        logger.warning("[SPY_BENCH] Sector lookup missing: %s", _SECTOR_LOOKUP_PATH)
        return {}
    with _SECTOR_LOOKUP_PATH.open() as f:
        return {row["ticker"]: row["gics_sector"] for row in csv.DictReader(f)}


def get_sector(ticker: str) -> Optional[str]:
    """Return GICS sector for ticker; None if unknown."""
    return _load_sector_lookup().get(ticker.upper())


def _iso_to_date(value) -> dt.date:
    """Coerce a PG-native datetime/date OR an ISO string to a date.

    PG-cutover hardening (#132): psycopg2 returns timestamp columns as native
    datetime objects (connect_db's RealDictCursor does NOT stringify), while the
    SQLite path returns ISO strings. Calling ``.replace("Z", "+00:00")`` on a
    datetime invokes ``datetime.replace(year="Z", month="+00:00")`` → "'str'
    object cannot be interpreted as an integer", which (fail-open) silently
    disabled SPY-benchmark attribution on every PG-read close. Handle both.
    """
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    return dt.datetime.fromisoformat(str(value).replace("Z", "+00:00")).date()


def spy_return_over_range(entry_iso: str, exit_iso: str) -> Optional[float]:
    """SPY total return (fraction) from entry close to exit close.

    Returns None if data unavailable — callers must treat as "cannot attribute",
    NOT "zero return". Fail-open: never blocks exit finalization.
    """
    try:
        import yfinance as yf
        entry_date = _iso_to_date(entry_iso)
        exit_date = _iso_to_date(exit_iso)

        # Buffer on both sides to handle weekends/holidays.
        start = (entry_date - dt.timedelta(days=5)).isoformat()
        end = (exit_date + dt.timedelta(days=5)).isoformat()

        data = yf.download(
            "SPY", start=start, end=end, progress=False, auto_adjust=True
        )
        if data.empty:
            return None

        # yfinance returns a MultiIndex DataFrame for single-ticker downloads
        # in recent versions. Collapse to Series via .squeeze() so downstream
        # scalar extraction works whether the caller gets Series or 1-col DF.
        close_series = data["Close"].squeeze()

        df = data.reset_index()
        df["date"] = df["Date"].dt.date

        at_or_after_entry = df[df["date"] >= entry_date]
        at_or_after_exit = df[df["date"] >= exit_date]
        if at_or_after_entry.empty or at_or_after_exit.empty:
            return None

        entry_idx = at_or_after_entry.index[0]
        exit_idx = at_or_after_exit.index[0]
        entry_close = float(close_series.iloc[entry_idx])
        exit_close = float(close_series.iloc[exit_idx])
        return (exit_close - entry_close) / entry_close
    except Exception as exc:
        logger.warning(
            "[SPY_BENCH] spy_return_over_range(%s,%s) failed: %s",
            entry_iso, exit_iso, exc,
        )
        return None


def excess_return(
    pnl_pct: Optional[float], spy_return_fraction: Optional[float]
) -> Optional[float]:
    """Excess = pnl_pct - (spy_return * 100). Both inputs in their native units.

    pnl_pct is already in percent (e.g. 3.5 means +3.5%).
    spy_return_fraction is in fraction form (e.g. 0.02 means +2%).
    Result is in percent, directly comparable to pnl_pct.
    """
    if pnl_pct is None or spy_return_fraction is None:
        return None
    return pnl_pct - (spy_return_fraction * 100.0)
