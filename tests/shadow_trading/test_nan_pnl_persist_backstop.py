"""Regression: the NaN-pnl persist class is closed on BOTH sides.

Sibling of `test_reconcile_nan_pnl_guard.py`. The 2026-06-12 incident showed a
NaN close price can reach a persisted pnl via more than the reconcile path:

1. SOURCE — `risk.price_utils._get_current_price_safe` returned `float(Close)`
   unguarded (and `if price:` lets a NaN through, since `nan` is truthy),
   feeding the live mr-timeout exit pnl in `order_lifecycle.py`.
2. BOUNDARY — `journal.store.close_shadow_trade` is the single choke point every
   close routes through; a structural backstop there makes a persisted NaN pnl
   impossible regardless of which upstream path produced it.

verify-by-mutation: each NaN assertion fails on pre-fix code.
"""
from __future__ import annotations

import math

import pandas as pd

from src.risk.price_utils import _get_current_price_safe


# ── SOURCE guard: _get_current_price_safe ───────────────────────────────────

def test_price_safe_rejects_nan_from_alpaca(monkeypatch):
    """A NaN from the Alpaca branch must not be returned (nan is truthy)."""
    monkeypatch.setattr(
        "src.shadow_trading.alpaca_adapter.get_current_price",
        lambda _t: float("nan"),
    )
    # yfinance fallback returns nothing → overall None (proves NaN wasn't returned)
    monkeypatch.setattr("src.data_ingestion.market_data.fetch_ohlcv", lambda *_a, **_k: {})
    assert _get_current_price_safe("AAPL") is None


def test_price_safe_rejects_nan_from_yfinance(monkeypatch):
    """A NaN last-bar close in the yfinance fallback must not be returned."""
    monkeypatch.setattr(
        "src.shadow_trading.alpaca_adapter.get_current_price", lambda _t: None
    )
    monkeypatch.setattr(
        "src.data_ingestion.market_data.fetch_ohlcv",
        lambda *_a, **_k: {"AAPL": pd.DataFrame({"Close": [float("nan")]})},
    )
    assert _get_current_price_safe("AAPL") is None


def test_price_safe_returns_finite_price(monkeypatch):
    monkeypatch.setattr(
        "src.shadow_trading.alpaca_adapter.get_current_price", lambda _t: 191.23
    )
    assert _get_current_price_safe("AAPL") == 191.23


# ── BOUNDARY backstop: close_shadow_trade ───────────────────────────────────

def _patch_store(monkeypatch, captured):
    monkeypatch.setattr(
        "src.journal.store._populate_exit_metadata",
        lambda *_a, **_k: ({}, {"ticker": "AAPL"}),
    )
    monkeypatch.setattr("src.journal.store._build_spy_excess_fields", lambda *_a, **_k: {})
    monkeypatch.setattr("src.journal.store._broadcast_and_log_close", lambda *_a, **_k: None)
    monkeypatch.setattr(
        "src.journal.store.update_shadow_trade",
        lambda _tid, fields, *_a, **_k: captured.update(fields),
    )


def test_close_shadow_trade_coerces_nan_pnl_to_null(monkeypatch):
    """NaN exit metadata must persist as NULL (None), never NaN."""
    from src.journal import store

    captured: dict = {}
    _patch_store(monkeypatch, captured)
    store.close_shadow_trade(
        "t-nan", exit_price=float("nan"), exit_time="2026-06-12T10:00:00-04:00",
        exit_reason="reconciled_stale", pnl_dollars=float("nan"), pnl_pct=float("nan"),
    )
    assert captured["pnl_dollars"] is None
    assert captured["pnl_pct"] is None
    assert captured["actual_exit_price"] is None
    # none of the persisted numerics may be NaN
    for k in ("pnl_dollars", "pnl_pct", "actual_exit_price"):
        v = captured[k]
        assert v is None or math.isfinite(v)


def test_close_shadow_trade_preserves_finite_values(monkeypatch):
    """Finite values pass through the backstop unchanged."""
    from src.journal import store

    captured: dict = {}
    _patch_store(monkeypatch, captured)
    store.close_shadow_trade(
        "t-ok", exit_price=361.0, exit_time="2026-06-12T10:00:00-04:00",
        exit_reason="reconciled", pnl_dollars=-173.36, pnl_pct=-5.66,
    )
    assert captured["pnl_dollars"] == -173.36
    assert captured["pnl_pct"] == -5.66
    assert captured["actual_exit_price"] == 361.0
