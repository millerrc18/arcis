"""Regression-lock for v0.36.30 — F-1: _estimate_exit_pnl phantom $0 close.

Background (W21 lifecycle audit, finding F-1, CRITICAL)
======================================================

`src/shadow_trading/reconcile.py::_estimate_exit_pnl` returned the literal
tuple `(0.0, 0.0, 0.0)` on ANY exception (yfinance rate limit, delisting,
network). Called by the stale-close paths at reconcile.py:349 (live) and
reconcile.py:863 (paper), this wrote `exit_price=$0, pnl=$0, pnl_pct=0` to
closed shadow_trades.

This is the SAME phantom-state pattern v0.36.28 fixed for the executor —
alive in a parallel code path. Smoking-gun comparison:
  v0.36.28 phantom: $440.72 entry → $440.72 exit (entry-fill-as-exit)
  F-1 phantom:      $440.72 entry → $0.00 exit  (zero-as-exit)

The sibling helper `_resolve_stuck_pnl` (reconcile.py:108-155) already does
the right thing — returns None on unknown price. F-1 mirrors that.

The fix
=======

`_estimate_exit_pnl` returns `(None, None, None)` on failure. Call sites
write NULL pnl (not 0.0) and the close is logged as UNKNOWN. NULL pnl =
"unmeasured", which the audit's `_UNMEASURABLE_EXIT_REASONS` filter (and
the `reconciled_stale` exit-reason allowlist) correctly excludes from
outcome stats — vs $0 which silently corrupts the dashboard, daily audit
aggregates, and any KPI that doesn't read the unmeasured-allowlist.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest


def test_estimate_exit_pnl_returns_none_on_fetch_failure():
    """fetch_ohlcv raises → (None, None, None), NOT (0.0, 0.0, 0.0)."""
    from src.shadow_trading.reconcile import _estimate_exit_pnl

    with patch("src.data_ingestion.market_data.fetch_ohlcv",
               side_effect=RuntimeError("yfinance rate limit")):
        result = _estimate_exit_pnl("AMD", 439.80, 2)

    assert result == (None, None, None), (
        f"Expected (None, None, None) on fetch failure, got {result!r}. "
        "Returning (0.0, 0.0, 0.0) is the phantom-$0-close bug (F-1) — "
        "indistinguishable from a genuine flat exit. NULL = 'unmeasured'."
    )


def test_estimate_exit_pnl_returns_none_on_empty_data():
    """fetch returns empty/missing ticker → (None, None, None)."""
    from src.shadow_trading.reconcile import _estimate_exit_pnl

    # fetch_ohlcv returns a dict without the ticker (delisted / no data)
    with patch("src.data_ingestion.market_data.fetch_ohlcv",
               return_value={}):
        result = _estimate_exit_pnl("DELISTED", 100.0, 5)

    assert result == (None, None, None), (
        f"Expected (None, None, None) on empty data, got {result!r}."
    )


def test_estimate_exit_pnl_computes_real_pnl_on_success():
    """Happy path: real close price → real pnl (regression-proof the fix
    didn't break the success path)."""
    import pandas as pd
    from src.shadow_trading.reconcile import _estimate_exit_pnl

    # Mock fetch_ohlcv returning a DataFrame with a Close column
    df = pd.DataFrame({"Close": [430.0, 435.0, 440.72]})
    with patch("src.data_ingestion.market_data.fetch_ohlcv",
               return_value={"AMD": df}):
        exit_price, pnl, pct = _estimate_exit_pnl("AMD", 439.80, 2)

    assert exit_price == pytest.approx(440.72, abs=0.01)
    assert pnl == pytest.approx((440.72 - 439.80) * 2, abs=0.01)  # +1.84
    assert pct == pytest.approx((440.72 - 439.80) / 439.80 * 100, abs=0.01)


def test_estimate_exit_pnl_never_returns_zero_tuple_on_failure():
    """The specific anti-pattern: the failure return must NOT be the
    all-zeros tuple that v0.36.30 eliminated."""
    from src.shadow_trading.reconcile import _estimate_exit_pnl

    with patch("src.data_ingestion.market_data.fetch_ohlcv",
               side_effect=ConnectionError("network down")):
        result = _estimate_exit_pnl("AMD", 439.80, 2)

    assert result != (0.0, 0.0, 0.0), (
        "_estimate_exit_pnl returned (0.0, 0.0, 0.0) on failure — this is the "
        "exact F-1 phantom-close anti-pattern. Must return None tuple."
    )
