"""Tests for regime diagnostic v1.

Tests organized by module: dimensions, bootstrap, fdr, power, analyses.
Each test is self-contained with synthetic data — no DB dependency.
"""

import numpy as np
import pytest
from datetime import datetime, timezone, timedelta


# ── dimensions tests ──────────────────────────────────────────────


def test_vix_backfill_no_nulls():
    """VIX backfill produces no NULLs for trades within yfinance range."""
    from src.diagnostics.dimensions import backfill_vix
    import pandas as pd

    trades = [
        {"trade_id": "t1", "actual_entry_time": "2026-03-24T10:00:00-04:00",
         "vix_at_entry": None},
        {"trade_id": "t2", "actual_entry_time": "2026-04-01T10:00:00-04:00",
         "vix_at_entry": 21.5},
    ]
    dates = pd.bdate_range("2026-03-01", "2026-04-18")
    vix_series = pd.Series(
        np.linspace(18.0, 25.0, len(dates)), index=dates, name="Close"
    )
    result = backfill_vix(trades, vix_series)
    assert all(t["vix_at_entry"] is not None for t in result)
    assert result[1]["vix_at_entry"] == 21.5


def test_vix_crosscheck_flags_discrepancy():
    """Cross-check flags vix_at_entry values differing >0.5 from yfinance."""
    from src.diagnostics.dimensions import crosscheck_vix
    import pandas as pd

    trades = [
        {"trade_id": "t1", "actual_entry_time": "2026-03-24T10:00:00-04:00",
         "vix_at_entry": 20.0},
        {"trade_id": "t2", "actual_entry_time": "2026-03-25T10:00:00-04:00",
         "vix_at_entry": 22.0},
    ]
    dates = pd.bdate_range("2026-03-20", "2026-03-28")
    vix_series = pd.Series(
        [19.0, 19.0, 20.1, 20.2, 25.0, 25.0, 25.0, 25.0, 25.0][:len(dates)],
        index=dates, name="Close",
    )
    flags = crosscheck_vix(trades, vix_series)
    assert len(flags) == 1
    assert flags[0]["trade_id"] == "t2"


def test_sector_collapse_maps_all_gics():
    """All 11 GICS sectors map to exactly 4 buckets."""
    from src.diagnostics.dimensions import collapse_sector

    all_gics = [
        "Technology", "Communication Services",
        "Financials",
        "Health Care", "Consumer Staples", "Utilities",
        "Industrials", "Energy", "Materials",
        "Consumer Discretionary", "Real Estate",
    ]
    buckets = {collapse_sector(s) for s in all_gics}
    assert buckets == {"Tech+Comm", "Financials", "Defensive", "Cyclical"}


def test_entry_hour_bucket_handles_timezone():
    """Entry hour bucketing parses timezone-aware ISO timestamps."""
    from src.diagnostics.dimensions import entry_hour_bucket

    assert entry_hour_bucket("2026-03-24T09:58:34.137074-04:00") == "09:30-10:30"
    assert entry_hour_bucket("2026-04-13T14:46:48.351956-04:00") == "14:00-16:00"
    assert entry_hour_bucket("2026-04-01T10:38:07.650905-04:00") == "10:30-12:00"
    assert entry_hour_bucket("2026-04-02T12:30:00.000000-04:00") == "12:00-14:00"


def test_holding_period_bucket_edge_cases():
    """Holding period bucketing handles edge cases."""
    from src.diagnostics.dimensions import holding_period_bucket

    assert holding_period_bucket(0) == "short"
    assert holding_period_bucket(1) == "short"
    assert holding_period_bucket(3) == "short"
    assert holding_period_bucket(4) == "medium"
    assert holding_period_bucket(6) == "medium"
    assert holding_period_bucket(7) == "long"
    assert holding_period_bucket(15) == "long"
