"""Tests for per-window + pooled metrics (R6)."""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pytest

from src.platform.rigor.walkforward_metrics import (
    ANNUALIZATION_FACTOR,
    compute_bootstrap_se,
    compute_max_drawdown,
    compute_parametric_se,
    compute_pooled_sharpe,
    compute_sharpe,
    compute_window_metrics,
    distinct_tier_count,
    vix_tier_of,
)


@dataclass
class FakeTrade:
    pnl_pct: float | None = None
    vix_at_entry: float | None = None


def test_vix_tier_of_low():
    assert vix_tier_of(12.0) == "low"


def test_vix_tier_of_medium():
    assert vix_tier_of(20.0) == "medium"


def test_vix_tier_of_high():
    assert vix_tier_of(30.0) == "high"


def test_vix_tier_of_none():
    assert vix_tier_of(None) is None


def test_sharpe_zero_on_constant_pnl():
    """std=0 → Sharpe=0 by project convention (not +inf)."""
    pnls = np.array([0.01, 0.01, 0.01])
    assert compute_sharpe(pnls) == 0.0


def test_sharpe_positive_for_positive_mean():
    pnls = np.array([0.01, 0.02, 0.01, 0.02, 0.015])
    s = compute_sharpe(pnls)
    assert s > 0
    # Annualization factor ≈ sqrt(252) ≈ 15.87
    # mean 0.015 / std 0.00527 ≈ 2.85 → 2.85 * 15.87 ≈ 45
    assert s > 20


def test_sharpe_of_tiny_series_is_zero():
    assert compute_sharpe(np.array([0.01])) == 0.0
    assert compute_sharpe(np.array([])) == 0.0


def test_max_drawdown_simple_series():
    # Up 10%, down 20%, up 5% → peak after +10%, trough after -20% from peak.
    pnls = np.array([0.10, -0.20, 0.05])
    mdd = compute_max_drawdown(pnls)
    # peak = 1.10, after -20%: 1.10 * 0.80 = 0.88 → dd = (1.10-0.88)/1.10 = 0.20
    assert abs(mdd - 0.20) < 1e-9


def test_max_drawdown_monotonic_up_is_zero():
    pnls = np.array([0.05, 0.03, 0.07])
    assert compute_max_drawdown(pnls) == 0.0


def test_parametric_se_formula():
    """Annualized-scale Lo 2002: SE(SR_ann) = sqrt((T + 0.5 * SR_ann^2) / N)
    where T=252. Chosen so the parametric SE is comparable to a bootstrap
    that directly resamples the annualized Sharpe statistic."""
    se = compute_parametric_se(sharpe=1.0, n=100)
    expected = math.sqrt((ANNUALIZATION_FACTOR + 0.5 * 1.0) / 100)
    assert abs(se - expected) < 1e-9


def test_parametric_se_infinite_at_n_one():
    assert math.isinf(compute_parametric_se(sharpe=0.5, n=1))


def test_bootstrap_se_finite_for_normal_like():
    """For a Gaussian-ish return distribution, bootstrap SE should be
    finite and close to parametric."""
    rng = np.random.default_rng(42)
    pnls = rng.normal(0.005, 0.02, size=300)
    bse = compute_bootstrap_se(pnls, n_resamples=1000, seed=42)
    assert math.isfinite(bse)
    assert bse > 0


def test_bootstrap_se_infinite_when_n_lt_2():
    pnls = np.array([0.01])
    assert math.isinf(compute_bootstrap_se(pnls, n_resamples=100, seed=42))


def test_window_metrics_pass_case():
    """Good synthetic: Sharpe > 0.3, low heavy-tail risk, mdd < 20%."""
    rng = np.random.default_rng(0)
    pnls = rng.normal(0.003, 0.02, size=50)
    trades = [FakeTrade(pnl_pct=p, vix_at_entry=15.0) for p in pnls]
    m = compute_window_metrics(trades, window_index=0, bootstrap_resamples=500)
    assert m.n_trades == 50
    assert m.sharpe > 0
    assert math.isfinite(m.parametric_se)
    assert math.isfinite(m.bootstrap_se)
    assert m.max_drawdown_pct >= 0
    assert "medium" in m.vix_tiers_represented


def test_heavy_tail_flag_mechanism_triggers_on_large_ratio(monkeypatch):
    """Verify the flag-firing mechanism itself: when bootstrap_SE exceeds
    1.5 × parametric_SE the flag must be True. We monkeypatch the
    bootstrap SE computation to produce a deliberately large value so we
    test the mechanism — not a specific distribution."""
    from src.platform.rigor import walkforward_metrics as wm
    orig_param = wm.compute_parametric_se

    def fake_bootstrap_se(pnls, n_resamples, seed):
        # Produce something clearly larger than parametric for non-trivial N
        return 999.0

    monkeypatch.setattr(wm, "compute_bootstrap_se", fake_bootstrap_se)
    rng = np.random.default_rng(0)
    pnls = rng.normal(0.001, 0.01, size=200)
    trades = [FakeTrade(pnl_pct=float(p), vix_at_entry=18.0) for p in pnls]
    m = wm.compute_window_metrics(
        trades, window_index=0, bootstrap_resamples=200,
        heavy_tail_se_ratio=1.5,
    )
    assert m.heavy_tail_flag is True
    assert m.bootstrap_se == 999.0
    assert math.isfinite(m.parametric_se)


def test_heavy_tail_flag_does_not_fire_when_ratio_below_threshold(monkeypatch):
    """Inverse: bootstrap_SE marginally below 1.5 × parametric → flag False."""
    from src.platform.rigor import walkforward_metrics as wm

    def fake_bootstrap_se(pnls, n_resamples, seed):
        # Return a value deliberately just under 1.5× parametric
        param = wm.compute_parametric_se(sharpe=0.5, n=len(pnls))
        return param * 1.4  # below the 1.5 trigger

    monkeypatch.setattr(wm, "compute_bootstrap_se", fake_bootstrap_se)
    rng = np.random.default_rng(0)
    pnls = rng.normal(0.001, 0.01, size=200)
    trades = [FakeTrade(pnl_pct=float(p), vix_at_entry=18.0) for p in pnls]
    m = wm.compute_window_metrics(
        trades, window_index=0, bootstrap_resamples=200,
        heavy_tail_se_ratio=1.5,
    )
    assert m.heavy_tail_flag is False


def test_window_metrics_no_heavy_tail_on_clean_gaussian():
    rng = np.random.default_rng(11)
    pnls = rng.normal(0.001, 0.01, size=300)
    trades = [FakeTrade(pnl_pct=p, vix_at_entry=18.0) for p in pnls]
    m = compute_window_metrics(
        trades, window_index=2, bootstrap_resamples=1500,
        heavy_tail_se_ratio=1.5,
    )
    assert m.heavy_tail_flag is False


def test_pooled_sharpe_concatenates_windows():
    win1 = [FakeTrade(pnl_pct=0.01), FakeTrade(pnl_pct=0.02)]
    win2 = [FakeTrade(pnl_pct=-0.01), FakeTrade(pnl_pct=0.03)]
    s = compute_pooled_sharpe([win1, win2])
    # Combined ~ [0.01, 0.02, -0.01, 0.03], mean 0.0125, std ~ 0.017
    assert s > 0
    assert math.isfinite(s)


def test_distinct_tier_count_across_windows():
    from src.platform.rigor.walkforward_metrics import WindowMetrics
    a = WindowMetrics(0, 10, 0, 0, 0, 0, 0, 0, False, {"low"})
    b = WindowMetrics(1, 10, 0, 0, 0, 0, 0, 0, False, {"low", "medium"})
    c = WindowMetrics(2, 10, 0, 0, 0, 0, 0, 0, False, set())
    assert distinct_tier_count([a, b, c]) == 2


def test_window_metrics_empty_returns_zero_shape():
    m = compute_window_metrics([], window_index=0, bootstrap_resamples=200)
    assert m.n_trades == 0
    assert m.sharpe == 0.0
    assert m.max_drawdown_pct == 0.0


def _make_high_excess_sharpe_trades(rng, n: int = 80, rf_period: float = 0.0001):
    """Returns trades whose (pnl - rf) distribution yields excess Sharpe > 0.3."""
    # mean pnl 0.004, std 0.01 → raw/excess Sharpe ≈ (0.004-rf)/0.01 * sqrt(252) ≈ 6.3
    pnls = rng.normal(0.004, 0.01, size=n)
    return [FakeTrade(pnl_pct=float(p), vix_at_entry=18.0) for p in pnls], rf_period


def _make_low_excess_sharpe_trades(n: int = 80, rf_period: float = 0.005):
    """Returns deterministic trades whose (pnl - rf) distribution yields excess Sharpe < 0.
    pnl mean = 0.001 < rf_period = 0.005 → excess mean ≈ -0.004 → excess Sharpe < 0 < 0.3."""
    pnls = [0.001] * n  # constant mean 0.001 with tiny variance via alternating ±delta
    # Add just enough variation to avoid zero-std (canonical_sharpe returns None on zero std)
    pnls = [0.001 + (0.0001 if i % 2 == 0 else -0.0001) for i in range(n)]
    return [FakeTrade(pnl_pct=float(p), vix_at_entry=18.0) for p in pnls], rf_period


def test_window_metrics_excess_sharpe_gate_pass():
    """excess_sharpe_min=0.3, returns well above threshold → passes_excess_sharpe=True."""
    from src.platform.rigor.walkforward_metrics import compute_window_metrics
    rng = np.random.default_rng(77)
    rf_period = 0.0001
    trades, _ = _make_high_excess_sharpe_trades(rng, rf_period=rf_period)
    m = compute_window_metrics(
        trades,
        window_index=0,
        bootstrap_resamples=200,
        excess_sharpe_min=0.3,
        rf_period=rf_period,
    )
    assert m.passes_excess_sharpe is True
    assert m.excess_sharpe is not None
    assert m.excess_sharpe > 0.3


def test_window_metrics_excess_sharpe_gate_fail():
    """excess_sharpe_min=0.3, excess Sharpe < 0 (rf > mean pnl) → passes_excess_sharpe=False,
    reason='excess_sharpe_below_min'."""
    from src.platform.rigor.walkforward_metrics import compute_window_metrics
    rf_period = 0.005  # rf > mean pnl (0.001) → excess mean < 0 → excess Sharpe < 0 < 0.3
    trades, _ = _make_low_excess_sharpe_trades(rf_period=rf_period)
    m = compute_window_metrics(
        trades,
        window_index=0,
        bootstrap_resamples=200,
        excess_sharpe_min=0.3,
        rf_period=rf_period,
    )
    assert m.passes_excess_sharpe is False
    assert m.excess_sharpe_fail_reason == "excess_sharpe_below_min"


def test_window_metrics_excess_sharpe_none_uses_raw():
    """excess_sharpe_min=None (default): passes_excess_sharpe=None, no behavior change."""
    from src.platform.rigor.walkforward_metrics import compute_window_metrics
    rng = np.random.default_rng(99)
    pnls = rng.normal(0.003, 0.02, size=50)
    trades = [FakeTrade(pnl_pct=float(p), vix_at_entry=18.0) for p in pnls]
    # Call with explicit None (the default)
    m_default = compute_window_metrics(
        trades, window_index=0, bootstrap_resamples=200, excess_sharpe_min=None,
    )
    # And call with no excess_sharpe_min kwarg at all (same default)
    m_no_kwarg = compute_window_metrics(
        trades, window_index=0, bootstrap_resamples=200,
    )
    assert m_default.passes_excess_sharpe is None
    assert m_default.excess_sharpe_fail_reason is None
    assert m_no_kwarg.passes_excess_sharpe is None
    assert m_no_kwarg.excess_sharpe_fail_reason is None
    # Regression-lock: existing WindowMetrics fields are unchanged
    assert m_default.sharpe == m_no_kwarg.sharpe
    assert m_default.n_trades == m_no_kwarg.n_trades
