"""Instrumentation-version filter for analytics queries (Track 1.5 / B5).

Shelf module — not wired into any production query path yet. Ships as a
building block for downstream analytics tasks (Stage 2 / Stage 3 evaluation).

Distinct from src.analytics.instrumentation_filter, which owns the pre-v3
era four-column completeness check (pnl_pct, actual_entry_time, etc.). This
module owns the integer-version filter introduced in Track 1.5.

One export:

  filter_to_version(trades, min_version=3) -> same type as input

Called by: nothing (shelf — operator-invoked or future analytics tasks).
Calls: nothing (pure filter; pandas optional import inside function body).
Owns tables: none.
Config keys: none.
Tests: tests/test_instrumentation_version.py (T3 group).
"""
from __future__ import annotations

from typing import Union


def filter_to_version(
    trades: "Union[list[dict], object]",
    min_version: int = 3,
) -> "Union[list[dict], object]":
    """Return the subset of rows where instrumentation_version >= min_version.

    Accepts either a pandas DataFrame or a list of dicts (caller-friendly).
    Returns the same type as the input.
    Missing or NULL instrumentation_version is treated as version 0 (excluded
    by default).

    Default min_version=3: Stage-2 onward analytics demand full instrumentation.
    Pass min_version=2 for conviction-stratified analysis that accepts missing
    exit_slippage_bps.
    """
    try:
        import pandas as pd
        if isinstance(trades, pd.DataFrame):
            if "instrumentation_version" not in trades.columns:
                return trades.iloc[0:0]
            filled = trades["instrumentation_version"].fillna(0)
            return trades[filled >= min_version]
    except ImportError:
        pass

    return [
        row for row in trades
        if (row.get("instrumentation_version") or 0) >= min_version
    ]
