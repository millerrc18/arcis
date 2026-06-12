"""Regression: reconcile pnl helpers must never return NaN/inf.

Root cause (2026-06-12 incident): during the 2026-06-10 PG/data outage the
market-data fetch returned a NaN close price. ``_estimate_exit_pnl`` and
``_resolve_stuck_pnl`` only guarded ``None`` / ``<= 0`` — but ``float('nan')``
raises nothing and ``nan <= 0`` is ``False``, so the NaN flowed straight into
``pnl_dollars`` / ``actual_exit_price`` and was persisted to shadow_trades
(trade b9c0255d AAPL). NaN poisons every naive ``SUM(pnl_dollars)`` aggregate.

The fix treats a non-finite price exactly like an unknown price: return the
None sentinel so the caller writes NULL ("unmeasured"), never NaN.

These tests are written to FAIL on the pre-fix code (the helpers returned
nan) and PASS once the finite-guard is added — verify-by-mutation.
"""
from __future__ import annotations

import math

import pandas as pd

from src.shadow_trading.reconcile import _estimate_exit_pnl, _resolve_stuck_pnl


def test_resolve_stuck_pnl_returns_none_on_nan_price():
    """A price provider that returns NaN must yield None, not a NaN pnl."""
    trade = {"actual_entry_price": 290.55, "planned_shares": 10, "ticker": "AAPL"}
    out = _resolve_stuck_pnl(
        trade, exit_reason="reconciled_stale",
        current_price_provider=lambda _t: float("nan"),
    )
    assert out is None, f"expected None for NaN price, got {out!r}"


def test_resolve_stuck_pnl_returns_none_on_inf_price():
    trade = {"actual_entry_price": 290.55, "planned_shares": 10, "ticker": "AAPL"}
    out = _resolve_stuck_pnl(
        trade, exit_reason="reconciled_stale",
        current_price_provider=lambda _t: float("inf"),
    )
    assert out is None, f"expected None for inf price, got {out!r}"


def test_resolve_stuck_pnl_returns_none_on_nan_entry():
    """A NaN entry price (corrupt row) must not produce a NaN pnl either."""
    trade = {"actual_entry_price": float("nan"), "planned_shares": 10, "ticker": "AAPL"}
    out = _resolve_stuck_pnl(
        trade, exit_reason="reconciled_stale",
        current_price_provider=lambda _t: 300.0,
    )
    assert out is None, f"expected None for NaN entry, got {out!r}"


def test_resolve_stuck_pnl_still_computes_normal_case():
    """Guard must not break the happy path."""
    trade = {"actual_entry_price": 100.0, "planned_shares": 10, "ticker": "AAPL"}
    out = _resolve_stuck_pnl(
        trade, exit_reason="reconciled_stale",
        current_price_provider=lambda _t: 110.0,
    )
    assert out == 100.0, f"expected 100.0 ((110-100)*10), got {out!r}"


def test_estimate_exit_pnl_returns_none_triple_on_nan_close(monkeypatch):
    """A NaN last-bar close must yield (None, None, None), not (nan, nan, nan)."""
    def fake_fetch(_tickers, period="5d"):
        return {"AAPL": pd.DataFrame({"Close": [float("nan")]})}

    monkeypatch.setattr("src.data_ingestion.market_data.fetch_ohlcv", fake_fetch)
    exit_price, pnl, pct = _estimate_exit_pnl("AAPL", 290.55, 10)
    assert exit_price is None and pnl is None and pct is None, (
        f"expected (None,None,None) for NaN close, got {(exit_price, pnl, pct)!r}"
    )
    # belt-and-suspenders: none of the outputs may be NaN
    for v in (exit_price, pnl, pct):
        assert v is None or math.isfinite(v)


def test_estimate_exit_pnl_still_computes_normal_case(monkeypatch):
    def fake_fetch(_tickers, period="5d"):
        return {"AAPL": pd.DataFrame({"Close": [300.0]})}

    monkeypatch.setattr("src.data_ingestion.market_data.fetch_ohlcv", fake_fetch)
    exit_price, pnl, pct = _estimate_exit_pnl("AAPL", 290.0, 10)
    assert exit_price == 300.0
    assert pnl == 100.0  # (300-290)*10
