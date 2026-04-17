"""Tests for src.platform.metrics — Sharpe/Sortino/Calmar + survivorship."""
import math

import pytest

from src.platform.metrics import (
    compute_all_metrics,
    compute_calmar,
    compute_excess_sharpe,
    compute_max_drawdown,
    compute_profit_factor,
    compute_sharpe,
    compute_sortino,
)


def test_sharpe_zero_volatility_returns_none():
    assert compute_sharpe([0.0] * 10) is None


def test_sharpe_known_inputs():
    # Daily returns with mean 0.001, std 0.01 → SR_daily = 0.1,
    # annualized SR = 0.1 * sqrt(252) ≈ 1.587.
    r = [0.011, -0.009, 0.011, -0.009] * 10  # mean 0.001, std ≈ 0.01005
    out = compute_sharpe(r, periods_per_year=252)
    assert out is not None
    assert 1.5 < out < 1.7


def test_max_drawdown_monotone_series_returns_zero():
    curve = [("2023-01-01", 100.0), ("2023-01-02", 101.0), ("2023-01-03", 102.0)]
    dd, peak, trough = compute_max_drawdown(curve)
    assert dd == 0.0


def test_max_drawdown_known_v_shape():
    # Peak 100 → trough 80 → recover 90. Max DD = 20%.
    curve = [
        ("2023-01-01", 100.0),
        ("2023-01-02", 80.0),
        ("2023-01-03", 90.0),
    ]
    dd, peak_date, trough_date = compute_max_drawdown(curve)
    assert math.isclose(dd, 0.20, abs_tol=1e-9)
    assert peak_date == "2023-01-01"
    assert trough_date == "2023-01-02"


def test_calmar_computes_ratio():
    # 20% total return / 10% max DD = 2.0
    assert compute_calmar(total_return=0.20, max_drawdown=0.10) == 2.0


def test_profit_factor_no_losses_returns_none_or_inf():
    class T:  # stand-in for BacktestTrade
        def __init__(self, p):
            self.pnl_dollars = p
    trades = [T(10.0), T(5.0)]
    pf = compute_profit_factor(trades)
    # Accept either inf (mathematically correct) or None (sentinel for "undefined")
    assert pf is None or pf == float("inf")


def test_compute_all_metrics_applies_survivorship_haircut():
    class T:
        def __init__(self, pnl_pct, excess_return):
            self.pnl_pct = pnl_pct
            self.excess_return = excess_return
            self.pnl_dollars = pnl_pct * 1000
    trades = [T(0.05, 0.03), T(0.05, 0.03)]  # total 10%
    curve = [("2023-01-01", 100000.0), ("2024-01-01", 110000.0)]
    m = compute_all_metrics(trades, curve, survivorship_haircut_bps=75)
    assert "total_return_pct" in m
    assert math.isclose(m["total_return_pct"], 0.10, abs_tol=1e-6)
    assert m["survivorship_haircut_bps"] == 75
    # Net annualized is gross minus 75 bps
    assert math.isclose(
        m["annualized_return_net"],
        m["annualized_return_gross"] - 0.0075,
        abs_tol=1e-6,
    )


def test_compute_all_metrics_zero_haircut_default_when_passed():
    class T:
        def __init__(self, pnl_pct, excess_return):
            self.pnl_pct = pnl_pct
            self.excess_return = excess_return
            self.pnl_dollars = pnl_pct * 1000
    trades = [T(0.05, 0.03), T(0.05, 0.03)]
    curve = [("2023-01-01", 100000.0), ("2024-01-01", 110000.0)]
    m = compute_all_metrics(trades, curve, survivorship_haircut_bps=0)
    assert m["survivorship_haircut_bps"] == 0
    assert math.isclose(
        m["annualized_return_net"], m["annualized_return_gross"], abs_tol=1e-9,
    )


def test_haircut_does_not_shift_sharpe():
    """Sharpe is computed from gross per-trade returns. Haircut only
    affects annualized_return_net and calmar."""
    class T:
        def __init__(self, pnl_pct, excess_return):
            self.pnl_pct = pnl_pct
            self.excess_return = excess_return
            self.pnl_dollars = pnl_pct * 1000
    trades = [T(0.05, 0.03), T(-0.02, -0.01), T(0.04, 0.02), T(0.03, 0.01)]
    curve = [("2023-01-01", 100000.0), ("2024-01-01", 110000.0)]
    m0 = compute_all_metrics(trades, curve, survivorship_haircut_bps=0)
    m75 = compute_all_metrics(trades, curve, survivorship_haircut_bps=75)
    # Gross sharpe unchanged by haircut
    if m0["sharpe"] is not None and m75["sharpe"] is not None:
        assert math.isclose(m0["sharpe"], m75["sharpe"], abs_tol=1e-9)
    # But net annualized differs by exactly haircut
    assert math.isclose(
        m0["annualized_return_net"] - m75["annualized_return_net"],
        0.0075, abs_tol=1e-6,
    )
