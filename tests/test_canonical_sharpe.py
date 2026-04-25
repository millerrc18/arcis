"""Tests for src.analytics.canonical_sharpe — F-2 Sharpe consolidation.

Audit spec §F-2: a single canonical Sharpe module supplying three flavors
(raw, SPY-relative, rf-adjusted excess), all 252-scaled, replaces the
six-plus duplicated Sharpe formulas across journal/, platform/, and
evaluation/ surfaces.
"""
from __future__ import annotations

import math

import pytest


# ── canonical module ────────────────────────────────────────────────────

def test_raw_sharpe_known_inputs():
    """raw_sharpe = mean / stdev(ddof=1) * sqrt(252) for a known series."""
    from src.analytics.canonical_sharpe import raw_sharpe

    # Mean 0.001, sample stdev (ddof=1) ≈ 0.01005 → SR_d ≈ 0.0995
    # Annualized SR ≈ 0.0995 * sqrt(252) ≈ 1.579
    r = [0.011, -0.009, 0.011, -0.009] * 10
    out = raw_sharpe(r)
    assert out is not None
    # Hand-computed expected value
    arr = r
    mean = sum(arr) / len(arr)
    var = sum((x - mean) ** 2 for x in arr) / (len(arr) - 1)
    sd = var ** 0.5
    expected = (mean / sd) * math.sqrt(252)
    assert math.isclose(out, expected, rel_tol=1e-9)


def test_raw_sharpe_zero_variance_returns_none():
    from src.analytics.canonical_sharpe import raw_sharpe
    assert raw_sharpe([0.001] * 10) is None


def test_raw_sharpe_empty_returns_none():
    from src.analytics.canonical_sharpe import raw_sharpe
    assert raw_sharpe([]) is None


def test_raw_sharpe_single_trade_returns_none():
    """ddof=1 with one obs is undefined → None (not crash)."""
    from src.analytics.canonical_sharpe import raw_sharpe
    assert raw_sharpe([0.05]) is None


def test_spy_relative_sharpe_known_inputs():
    """spy_relative_sharpe = SR(returns - spy_returns) on the diff series."""
    from src.analytics.canonical_sharpe import spy_relative_sharpe

    returns = [0.02, -0.01, 0.03, -0.02, 0.01]
    spy = [0.01, -0.005, 0.015, -0.01, 0.005]
    diff = [r - s for r, s in zip(returns, spy)]
    mean = sum(diff) / len(diff)
    var = sum((x - mean) ** 2 for x in diff) / (len(diff) - 1)
    sd = var ** 0.5
    expected = (mean / sd) * math.sqrt(252)

    out = spy_relative_sharpe(returns, spy)
    assert out is not None
    assert math.isclose(out, expected, rel_tol=1e-9)


def test_spy_relative_sharpe_identical_series_returns_none():
    """If returns == spy_returns the diff has zero variance (and zero mean)."""
    from src.analytics.canonical_sharpe import spy_relative_sharpe
    series = [0.01, -0.02, 0.03, 0.0]
    assert spy_relative_sharpe(series, series) is None


def test_rf_adjusted_excess_sharpe_known_inputs():
    """rf_adjusted_excess_sharpe = SR(returns - rf_period)."""
    from src.analytics.canonical_sharpe import rf_adjusted_excess_sharpe

    returns = [0.02, -0.01, 0.03, -0.02, 0.01, 0.005]
    rf = 0.0001  # ~2.5% annual / 252
    diff = [r - rf for r in returns]
    mean = sum(diff) / len(diff)
    var = sum((x - mean) ** 2 for x in diff) / (len(diff) - 1)
    sd = var ** 0.5
    expected = (mean / sd) * math.sqrt(252)

    out = rf_adjusted_excess_sharpe(returns, rf)
    assert out is not None
    assert math.isclose(out, expected, rel_tol=1e-9)


def test_rf_adjusted_excess_sharpe_rf_above_mean():
    """When rf > mean(returns) the excess Sharpe is negative — boundary case."""
    from src.analytics.canonical_sharpe import rf_adjusted_excess_sharpe
    returns = [0.001, 0.002, -0.001, 0.0005, 0.0008]
    rf = 0.005  # well above mean
    out = rf_adjusted_excess_sharpe(returns, rf)
    assert out is not None
    assert out < 0.0


def test_rf_adjusted_excess_sharpe_zero_variance_after_subtraction():
    """If all returns are identical, subtracting a constant rf yields zero
    variance → None."""
    from src.analytics.canonical_sharpe import rf_adjusted_excess_sharpe
    assert rf_adjusted_excess_sharpe([0.01] * 10, 0.0001) is None


def test_252_scaling_matches_sqrt_252():
    """The annualization factor is sqrt(252), not sqrt(150) or sqrt(N)."""
    from src.analytics.canonical_sharpe import raw_sharpe
    # Construct a series with daily SR of exactly 0.1
    # mean=0.1, stdev=1.0 (ddof=1) → SR_d = 0.1
    r = [1.05, -0.95, 1.05, -0.95, 1.05, -0.95, 1.05, -0.95, 1.05, -0.85]
    out = raw_sharpe(r)
    # Check it's annualized by sqrt(252) (~15.87) not sqrt(150) (~12.25)
    # SR_d ≈ 0.05 → SR_ann ≈ 0.05 * 15.87 = 0.79
    assert out is not None
    mean = sum(r) / len(r)
    var = sum((x - mean) ** 2 for x in r) / (len(r) - 1)
    sd = var ** 0.5
    sr_daily = mean / sd
    expected = sr_daily * math.sqrt(252)
    assert math.isclose(out, expected, rel_tol=1e-9)


# ── migration: src.journal.stats._trade_sharpe ──────────────────────────

def test_journal_trade_sharpe_uses_canonical():
    """_trade_sharpe must delegate to canonical raw_sharpe (252-scaled)."""
    from src.journal import stats
    excess = [0.02, -0.01, 0.03, -0.02, 0.01, 0.005, 0.01, -0.005, 0.015, -0.012]
    out = stats._trade_sharpe(excess)
    assert out is not None

    from src.analytics.canonical_sharpe import raw_sharpe
    expected = raw_sharpe(excess)
    assert out == expected


def test_journal_trade_sharpe_under_2_returns_none():
    from src.journal import stats
    assert stats._trade_sharpe([0.01]) is None
    assert stats._trade_sharpe([]) is None


def test_journal_trade_sharpe_zero_variance_returns_none():
    from src.journal import stats
    # Zero variance → canonical returns None
    assert stats._trade_sharpe([0.01, 0.01, 0.01, 0.01]) is None


# ── migration: src.platform.metrics ─────────────────────────────────────

def test_platform_compute_sharpe_uses_canonical_default_252():
    from src.platform.metrics import compute_sharpe
    from src.analytics.canonical_sharpe import raw_sharpe

    r = [0.011, -0.009, 0.011, -0.009] * 10
    out = compute_sharpe(r)  # default periods_per_year=252
    expected = raw_sharpe(r)
    assert out == expected


def test_platform_compute_sharpe_zero_variance_returns_none():
    from src.platform.metrics import compute_sharpe
    assert compute_sharpe([0.0] * 10) is None


def test_platform_compute_sharpe_empty_returns_none():
    from src.platform.metrics import compute_sharpe
    assert compute_sharpe([]) is None


def test_platform_compute_sharpe_preserves_periods_per_year_param():
    """Walk-forward path passes a non-default periods_per_year — must keep
    that scaling so downstream consumers get a numeric result.
    """
    from src.platform.metrics import compute_sharpe
    r = [0.011, -0.009, 0.011, -0.009] * 10
    mean = sum(r) / len(r)
    var = sum((x - mean) ** 2 for x in r) / (len(r) - 1)
    sd = var ** 0.5

    out_252 = compute_sharpe(r, periods_per_year=252)
    out_150 = compute_sharpe(r, periods_per_year=150)
    assert out_252 is not None and out_150 is not None
    # 252-scaled value matches canonical
    assert math.isclose(
        out_252, (mean / sd) * math.sqrt(252), rel_tol=1e-9,
    )
    # 150-scaled value uses sqrt(150)
    assert math.isclose(
        out_150, (mean / sd) * math.sqrt(150), rel_tol=1e-9,
    )


def test_platform_compute_excess_sharpe_uses_canonical():
    from src.platform.metrics import compute_excess_sharpe
    from src.analytics.canonical_sharpe import raw_sharpe

    r = [0.011, -0.009, 0.011, -0.009] * 10
    out = compute_excess_sharpe(r)
    expected = raw_sharpe(r)
    assert out == expected


def test_platform_compute_sharpe_walkforward_path_returns_numeric():
    """Walkforward.py:78,87 retrieves train_result.metrics.get('sharpe').
    compute_all_metrics path must still produce a numeric (or None)
    sharpe key — never crash.
    """
    from src.platform.metrics import compute_all_metrics

    class FakeTrade:
        def __init__(self, pnl_pct, excess_return):
            self.pnl_pct = pnl_pct
            self.excess_return = excess_return
            self.pnl_dollars = pnl_pct * 1000
    trades = [
        FakeTrade(0.011, 0.005),
        FakeTrade(-0.009, -0.004),
        FakeTrade(0.011, 0.005),
        FakeTrade(-0.009, -0.004),
    ]
    curve = [("2023-01-01", 100000.0), ("2024-01-01", 110000.0)]
    m = compute_all_metrics(trades, curve, survivorship_haircut_bps=75)
    assert "sharpe" in m
    # Either a finite float or None — never raises
    assert m["sharpe"] is None or isinstance(m["sharpe"], float)
