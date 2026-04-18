"""Trade dimension computation for regime diagnostic.

Loads closed trades from shadow_trades, backfills missing vix_at_entry
via yfinance, and computes sector/hour/holding-period buckets. All
computation is in-memory — no DB writes.

Called by: scripts/diagnostics/regime_diagnostic_v1.py
Calls: yfinance (via cache), known_events
Owns tables: none (read-only)
Config keys: none
Tests: tests/diagnostics/test_regime_diagnostic.py
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd

CACHE_DIR = Path(".tmp/regime_diagnostic_cache")

SECTOR_MAP = {
    "Technology": "Tech+Comm",
    "Communication Services": "Tech+Comm",
    "Financials": "Financials",
    "Health Care": "Defensive",
    "Consumer Staples": "Defensive",
    "Utilities": "Defensive",
    "Industrials": "Cyclical",
    "Energy": "Cyclical",
    "Materials": "Cyclical",
    "Consumer Discretionary": "Cyclical",
    "Real Estate": "Cyclical",
}


def load_closed_trades(
    db_path: str, *, exclude_quarantined: bool = False,
) -> list[dict]:
    """Load closed trades with exit and pnl from shadow_trades."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    where = "actual_exit_time IS NOT NULL AND pnl_pct IS NOT NULL"
    if exclude_quarantined:
        where += " AND quarantined = 0"
    rows = conn.execute(
        f"SELECT trade_id, ticker, actual_entry_time, actual_exit_time, "
        f"duration_days, pnl_pct, excess_return, vix_at_entry, "
        f"realized_sector, quarantined "
        f"FROM shadow_trades WHERE {where}"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def fetch_vix_daily(cache_dir: Path = CACHE_DIR) -> pd.Series:
    """Fetch ^VIX daily closes via yfinance with file cache."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file = cache_dir / "vix_daily.parquet"
    if cache_file.exists():
        df = pd.read_parquet(cache_file)
        series: pd.Series = df["Close"].squeeze()  # type: ignore[assignment]
        return series
    import yfinance as yf
    raw = yf.download(
        "^VIX", start="2025-09-01", end="2026-04-20", progress=False,
    )
    df = pd.DataFrame(raw)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df.to_parquet(cache_file)
    return pd.Series(df["Close"])


def _prev_trading_day(
    dt_str: str, index: pd.Index,
) -> Optional[pd.Timestamp]:
    """Find the trading day strictly before the entry date."""
    entry_date = pd.Timestamp(dt_str[:10])
    prior = index[index < entry_date]  # type: ignore[operator]
    if len(prior) == 0:
        return None
    return pd.Timestamp(prior[-1])  # type: ignore[arg-type]


def backfill_vix(
    trades: list[dict], vix_series: pd.Series,
) -> list[dict]:
    """Fill missing vix_at_entry using VIX close on entry_date - 1 trading day.

    Preserves existing non-None values. Mutates and returns trades list.
    """
    for t in trades:
        if t["vix_at_entry"] is not None:
            continue
        prev_day = _prev_trading_day(t["actual_entry_time"], vix_series.index)
        if prev_day is not None and prev_day in vix_series.index:
            t["vix_at_entry"] = float(vix_series.loc[prev_day])
    return trades


def crosscheck_vix(
    trades: list[dict], vix_series: pd.Series,
    threshold: float = 0.5,
) -> list[dict]:
    """Flag trades where stored vix_at_entry differs from yfinance by >threshold.

    Uses the VIX close on the entry date itself for comparison. If the entry
    date is not in the series, the trade is skipped (no flag).
    """
    flags = []
    for t in trades:
        if t["vix_at_entry"] is None:
            continue
        entry_date = pd.Timestamp(t["actual_entry_time"][:10])
        if entry_date not in vix_series.index:
            continue
        expected = float(vix_series.loc[entry_date])
        diff = abs(t["vix_at_entry"] - expected)
        if diff > threshold:
            flags.append({
                "trade_id": t["trade_id"],
                "stored": t["vix_at_entry"],
                "expected": expected,
                "diff": round(diff, 2),
            })
    return flags


def collapse_sector(sector: str) -> str:
    """Collapse GICS sector to 4-bucket scheme."""
    return SECTOR_MAP.get(sector, "Cyclical")


def entry_hour_bucket(entry_time: str) -> str:
    """Parse ISO timestamp and return intraday hour bucket."""
    dt = datetime.fromisoformat(entry_time)
    t = dt.hour * 60 + dt.minute
    if t < 630:
        return "09:30-10:30"
    if t < 720:
        return "10:30-12:00"
    if t < 840:
        return "12:00-14:00"
    return "14:00-16:00"


def holding_period_bucket(duration_days: int | str | None) -> str:
    """Categorize holding period into short/medium/long."""
    if duration_days is None:
        return "short"
    duration_days = int(duration_days)
    if duration_days <= 3:
        return "short"
    if duration_days <= 6:
        return "medium"
    return "long"


def build_analysis_df(
    db_path: str, *, exclude_quarantined: bool = False,
) -> tuple[pd.DataFrame, list[dict]]:
    """Build the complete analysis DataFrame with all dimensions.

    Returns (df, vix_flags) where vix_flags lists cross-check discrepancies.
    """
    trades = load_closed_trades(db_path, exclude_quarantined=exclude_quarantined)
    vix_series = fetch_vix_daily()

    vix_flags = crosscheck_vix(trades, vix_series)
    trades = backfill_vix(trades, vix_series)

    df = pd.DataFrame(trades)
    df["entry_date"] = df["actual_entry_time"].str[:10]
    df["sector_bucket"] = df["realized_sector"].apply(collapse_sector)
    df["hour_bucket"] = df["actual_entry_time"].apply(entry_hour_bucket)
    df["duration_bucket"] = df["duration_days"].apply(holding_period_bucket)

    return df, vix_flags
