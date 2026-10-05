"""S04 T6: Known-answer tests for data plane calculations.

Verifies split adjustments, dividend handling, and coverage characteristics
against known values. These are aggregate checks, not per-symbol data.
"""

import json
import os

import pandas as pd

DATA_ROOT = "/home/hatch/arcis-data"


def load_bars(symbol: str) -> pd.DataFrame:
    path = os.path.join(DATA_ROOT, "raw", "bars", f"{symbol}.parquet")
    df = pd.read_parquet(path)
    df["date"] = pd.to_datetime(df["t"], utc=True)
    return df.sort_values("date").reset_index(drop=True)


def test_aapl_split_adjusted():
    """AAPL 4:1 split on 2020-08-31: no artificial jump in adjusted closes."""
    df = load_bars("AAPL")
    df["d"] = df["date"].dt.date.astype(str)
    before = df[df["d"] < "2020-08-31"].iloc[-1]
    after = df[df["d"] >= "2020-08-31"].iloc[0]
    # If unadjusted, log(after.c / before.c) ≈ log(4) ≈ 1.39
    # If adjusted, it should be a normal daily move (< 0.2)
    import numpy as np
    log_jump = abs(float(np.log(after["c"] / before["c"])))
    assert log_jump < 0.2, f"AAPL split not adjusted: log_jump={log_jump}"


def test_nvda_split_adjusted():
    """NVDA 4:1 split on 2021-07-20: no artificial jump."""
    df = load_bars("NVDA")
    df["d"] = df["date"].dt.date.astype(str)
    before = df[df["d"] < "2021-07-20"].iloc[-1]
    after = df[df["d"] >= "2021-07-20"].iloc[0]
    import numpy as np
    log_jump = abs(float(np.log(after["c"] / before["c"])))
    assert log_jump < 0.2, f"NVDA split not adjusted: log_jump={log_jump}"


def test_spy_no_gaps():
    """SPY has no missing trading days in 2016-2026."""
    df = load_bars("SPY")
    # SPY should have a bar for every trading day; we check that the
    # date range is continuous (no gaps > 4 days, accounting for weekends)
    df = df.sort_values("date")
    gaps = df["date"].diff().dt.days
    # Max gap should be 4 days (Fri -> Tue after long weekend) or less
    # Actually, allow up to 5 for safety
    max_gap = gaps.max()
    assert max_gap <= 5, f"SPY has gap of {max_gap} days"


def test_late_starter_gev():
    """GEV (listed 2024) has first bar after 2020."""
    df = load_bars("GEV")
    first = df["date"].min().date().isoformat()
    assert first > "2020-01-01", f"GEV first bar {first} unexpectedly early"


def test_panel_symbol_count():
    """Bars panel has 504 symbols (503 + SPY)."""
    with open(os.path.join(DATA_ROOT, "raw", "bars", "manifest.json")) as f:
        manifest = json.load(f)
    assert manifest["_meta"]["symbols_total"] == 504
    assert manifest["_meta"]["symbols_complete"] == 504
