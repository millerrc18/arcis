"""Tests for regime diagnostic v1.

Tests organized by module: dimensions, bootstrap, fdr, power, analyses.
Each test is self-contained with synthetic data — no DB dependency.
"""

import numpy as np


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


# ── bootstrap tests ───────────────────────────────────────────────


def test_bootstrap_ci_coverage():
    """Bootstrap CI from N(0,1) should contain 0 ~95% of the time."""
    from src.diagnostics.bootstrap import bootstrap_ci

    rng = np.random.default_rng(42)
    contains_zero = 0
    trials = 200
    for _ in range(trials):
        data = rng.normal(0, 1, size=30)
        result = bootstrap_ci(data, n_resamples=2000, seed=None)
        if result["ci_lower"] <= 0 <= result["ci_upper"]:
            contains_zero += 1
    coverage = contains_zero / trials
    assert 0.88 <= coverage <= 1.00, f"Coverage {coverage:.2f} outside [0.88, 1.00]"


def test_bootstrap_ci_shifted_excludes_zero():
    """Bootstrap CI from N(2, 0.5) with n=50 should NOT contain 0."""
    from src.diagnostics.bootstrap import bootstrap_ci

    rng = np.random.default_rng(42)
    data = rng.normal(2.0, 0.5, size=50)
    result = bootstrap_ci(data, n_resamples=10000, seed=42)
    assert result["ci_lower"] > 0, f"CI lower {result['ci_lower']:.3f} should be > 0"


def test_fdr_controls_false_discoveries():
    """BH under complete null rejects very few (FDR control)."""
    from src.diagnostics.fdr import benjamini_hochberg

    rng = np.random.default_rng(42)
    # Under complete null, BH at q=0.10 should reject few or none
    pvals = rng.uniform(0, 1, size=100)
    _adjusted, survived = benjamini_hochberg(pvals, q=0.10)
    n_survived = sum(survived)
    assert n_survived <= 15, f"Too many survivals under null: {n_survived}"


def test_fdr_strong_signal_survives():
    """A very small p-value always survives FDR correction."""
    from src.diagnostics.fdr import benjamini_hochberg

    rng = np.random.default_rng(42)
    pvals = list(rng.uniform(0.3, 1.0, size=19))
    pvals.append(0.001)
    adjusted, survived = benjamini_hochberg(np.array(pvals), q=0.10)
    assert survived[-1] is True, "p=0.001 should survive FDR"


def test_power_mde_matches_scipy():
    """MDE calculation matches expected range for known params."""
    from src.diagnostics.power import cell_mde

    mde = cell_mde(n=20, std=1.0, alpha=0.05, power=0.80)
    assert 0.55 <= mde <= 0.75, f"MDE {mde:.3f} outside expected range"


def test_regression_power_mde():
    """Regression slope MDE is computed in correct units."""
    from src.diagnostics.power import regression_slope_mde

    mde = regression_slope_mde(
        n=88, x_std=1.5, y_std=3.0, alpha=0.05, power=0.80,
    )
    assert mde > 0, "MDE must be positive"
    assert 0.2 <= mde <= 3.0, f"MDE {mde:.3f} outside plausible range"


# ── analyses tests ────────────────────────────────────────────────


def test_cells_with_insufficient_data():
    """Cells with n < 5 produce no computed stats."""
    from src.diagnostics.analyses import _cell_stats

    data = np.array([1.0, 2.0, 3.0])  # n=3 < 5
    result = _cell_stats(data, label="tiny_cell")
    assert result["n"] == 3
    assert result["status"] == "insufficient_data"
    assert result["point_estimate"] is None
    assert result["ci_lower"] is None
    assert result["p_value"] is None


def test_cells_with_sufficient_data():
    """Cells with n >= 5 produce full stats."""
    from src.diagnostics.analyses import _cell_stats

    rng = np.random.default_rng(42)
    data = rng.normal(1.0, 2.0, size=20)
    result = _cell_stats(data, label="good_cell")
    assert result["n"] == 20
    assert result["status"] == "computed"
    assert result["point_estimate"] is not None
    assert result["ci_lower"] is not None
    assert result["ci_upper"] is not None
    assert result["p_value"] is not None
    assert result["ci_lower"] <= result["point_estimate"] <= result["ci_upper"]


def test_vix_regression_returns_required_fields():
    """VIX regression result has all required fields including slope MDE."""
    from src.diagnostics.analyses import vix_regression
    import pandas as pd

    rng = np.random.default_rng(42)
    df = pd.DataFrame({
        "vix_at_entry": rng.uniform(19, 25, size=50),
        "excess_return": rng.normal(0, 3, size=50),
    })
    result = vix_regression(df)
    required = ["r", "p_value", "slope", "slope_ci_lower", "slope_ci_upper",
                "intercept", "mde_slope", "mde_benchmark", "is_underpowered"]
    for key in required:
        assert key in result, f"Missing key: {key}"
