"""Per-trade VIX-at-entry lookup for walk-forward enrichment (#535).

Called by: src.platform.backtest_engine._build_trade
Calls: src.simulation.cache.fetch_cached_ohlcv (yfinance ^VIX)
Owns tables: none.
Config keys: none.
Tests: tests/platform/rigor/test_vix_enrichment.py.

Single responsibility: given an entry ISO date, return the VIX close on
that date (or the most-recent prior trading day if entry is a non-trading
day). Returns None on data unavailability — the engine still constructs
the trade, the runner persists vix_at_entry NULL, and downstream tier
bucketing degrades gracefully.

Lives outside `src/platform/rigor/` because VIX I/O is a data operation,
not a statistical-validation operation. Symmetric with src.platform.data_loader
(thin wrapper over the OHLCV cache).

Lookup window: pulls a 7-day window ending at entry_iso so the cache key
is deterministic and we always get at least one bar back even when entry
is a Monday following a long weekend (max gap in US market calendar is
~4 trading days for Thanksgiving / Christmas + weekend).

Why yfinance ^VIX (Pass 1 decision A1):
- Already wired through `fetch_cached_ohlcv` (parquet auto-cache)
- Daily ^VIX bars cover 2019-2024 100% (verified Pass 2 A1)
- Zero auth (no FRED API key required)
- Same mock surface as stock data — see test_vix_enrichment.py
"""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

from src.simulation.cache import fetch_cached_ohlcv

VIX_SYMBOL = "^VIX"
LOOKBACK_DAYS = 7  # widest US trading-day gap is ~4; 7 is safely past it


def lookup_vix_at_entry(entry_iso: str) -> float | None:
    """Return the VIX Close on or immediately before `entry_iso`.

    Returns None on cache miss, empty frame, or no bar at-or-before
    entry_iso. Never raises — the engine treats None as "VIX unavailable
    for this entry" and persists NULL.
    """
    entry_dt = date.fromisoformat(entry_iso)
    start_iso = (entry_dt - timedelta(days=LOOKBACK_DAYS)).isoformat()
    # +1 day on the end so the cache fetch is inclusive of entry_iso for
    # yfinance's exclusive-end convention (yfinance returns bars in
    # [start, end)).
    end_iso = (entry_dt + timedelta(days=1)).isoformat()

    df = fetch_cached_ohlcv(VIX_SYMBOL, start_iso, end_iso)
    if df is None or df.empty or "Close" not in df.columns:
        return None

    entry_ts = pd.Timestamp(entry_iso)
    on_or_before = df[df.index <= entry_ts]
    if on_or_before.empty:
        return None

    return float(on_or_before.iloc[-1]["Close"])
