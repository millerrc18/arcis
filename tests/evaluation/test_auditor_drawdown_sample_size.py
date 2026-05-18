"""Regression-lock for _check_drawdown sample-size guard (v0.36.22).

Pre-fix: `_check_drawdown` flagged CRITICAL on any `max_drawdown_pct >= 25`
regardless of sample size. On a small `days=1` audit window with N=16
trades, one outsized loser hitting after the cumulative-P&L peak trivially
trips 25% — the metric becomes order-dependent and stops measuring
strategy risk. Empirical trigger: 2026-05-18 daily audit alerted CRITICAL
at 32.6% off a single NEE -$207 stop, on a day with win rate 50%,
expectancy +$30/trade, Sharpe 2.35, profit factor 3.0.

Post-fix: when `trades_closed < _DRAWDOWN_MIN_SAMPLE` (50), the check is
suppressed regardless of drawdown value. Above 50, the 25% ceiling
applies as before.

The proper long-term fix is switching to a 30-day rolling window, queued
for post-W21-freeze.
"""
from __future__ import annotations

from src.evaluation.auditor import _check_drawdown, _DRAWDOWN_MIN_SAMPLE


def _build_cto_data(trades_closed: int, max_drawdown_pct: float) -> dict:
    """Minimal cto_data shape sufficient for _check_drawdown."""
    return {
        "trade_summary": {
            "trades_closed": trades_closed,
            "max_drawdown_pct": max_drawdown_pct,
        }
    }


def test_drawdown_suppressed_below_sample_threshold():
    """Empirical case: 16 trades + 32.6% DD = no flag (today's false positive)."""
    flags: list[dict] = []
    _check_drawdown(flags, _build_cto_data(trades_closed=16, max_drawdown_pct=32.6))
    assert flags == [], (
        "Drawdown check fired on a 16-trade sample — should be suppressed. "
        f"trade_count={16} drawdown=32.6%. This is the exact 2026-05-18 "
        "false-positive case that motivated v0.36.22."
    )


def test_drawdown_suppressed_below_sample_threshold_extreme_value():
    """Even 99% drawdown on a small sample shouldn't fire — order-dependent noise."""
    flags: list[dict] = []
    _check_drawdown(flags, _build_cto_data(trades_closed=20, max_drawdown_pct=99.0))
    assert flags == [], (
        "Drawdown check fired on a 20-trade sample with 99% DD. Sample-size guard "
        "should suppress regardless of value — small-N max_dd is dominated by "
        "trade ordering, not strategy risk."
    )


def test_drawdown_fires_above_sample_threshold():
    """50+ trades + 25%+ DD = flag (the threshold still applies on adequate samples)."""
    flags: list[dict] = []
    _check_drawdown(flags, _build_cto_data(trades_closed=60, max_drawdown_pct=30.0))
    assert len(flags) == 1, (
        f"Expected 1 CRITICAL flag for 60 trades + 30% DD, got {len(flags)}"
    )
    assert flags[0]["severity"] == "critical"
    assert flags[0]["metric"] == "max_drawdown_pct"
    assert flags[0]["value"] == 30.0


def test_drawdown_below_ceiling_above_sample_threshold():
    """50+ trades + <25% DD = no flag (the value-ceiling still applies)."""
    flags: list[dict] = []
    _check_drawdown(flags, _build_cto_data(trades_closed=60, max_drawdown_pct=20.0))
    assert flags == [], "Drawdown 20% on 60 trades should be below ceiling — no flag."


def test_drawdown_at_exact_threshold_boundary():
    """Exactly _DRAWDOWN_MIN_SAMPLE trades with high DD should still fire."""
    flags: list[dict] = []
    _check_drawdown(flags, _build_cto_data(
        trades_closed=_DRAWDOWN_MIN_SAMPLE,
        max_drawdown_pct=30.0,
    ))
    assert len(flags) == 1, (
        f"At trades_closed={_DRAWDOWN_MIN_SAMPLE} (the threshold) with 30% DD, "
        "expected 1 flag (>= comparison, not >)."
    )


def test_drawdown_one_below_threshold_suppressed():
    """One below threshold = suppressed."""
    flags: list[dict] = []
    _check_drawdown(flags, _build_cto_data(
        trades_closed=_DRAWDOWN_MIN_SAMPLE - 1,
        max_drawdown_pct=30.0,
    ))
    assert flags == [], (
        f"At trades_closed={_DRAWDOWN_MIN_SAMPLE - 1} (one below threshold) "
        "the check should be suppressed."
    )


def test_drawdown_missing_data_no_crash():
    """Empty / missing trade_summary fields must not crash the check."""
    flags: list[dict] = []
    _check_drawdown(flags, {})  # no trade_summary key at all
    assert flags == []

    flags = []
    _check_drawdown(flags, {"trade_summary": {}})  # empty trade_summary
    assert flags == []
