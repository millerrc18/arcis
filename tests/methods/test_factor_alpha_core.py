"""Tests for factor_alpha_core.py — Fama-French 3+momentum OLS regression.

Called by: pytest (diagnostic test suite).
Calls: src.methods.factor_alpha_core.factor_alpha.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.methods.factor_alpha_core import factor_alpha

_FACTOR_COLS = ["MKT", "SMB", "HML", "MOM"]


def _make_dates(n: int) -> pd.DatetimeIndex:
    return pd.date_range("2020-01-02", periods=n, freq="B")


class TestKnownAlpha:
    """Synthetic data with known coefficients; recovered values must be close."""

    def test_recovered_alpha(self):
        rng = np.random.default_rng(42)
        n = 250
        dates = _make_dates(n)
        factors = pd.DataFrame(
            rng.normal(0, 0.01, size=(n, 4)),
            index=dates,
            columns=_FACTOR_COLS,
        )
        true_alpha = 0.001
        true_betas = {"MKT": 1.2, "SMB": -0.3, "HML": 0.5, "MOM": 0.4}
        noise = rng.normal(0, 0.002, n)
        returns = pd.Series(
            true_alpha
            + true_betas["MKT"] * factors["MKT"].values
            + true_betas["SMB"] * factors["SMB"].values
            + true_betas["HML"] * factors["HML"].values
            + true_betas["MOM"] * factors["MOM"].values
            + noise,
            index=dates,
        )
        result = factor_alpha(returns, factors)
        assert abs(result["alpha"] - true_alpha) < 0.0003

    def test_recovered_beta_mkt(self):
        rng = np.random.default_rng(42)
        n = 250
        dates = _make_dates(n)
        factors = pd.DataFrame(
            rng.normal(0, 0.01, size=(n, 4)),
            index=dates,
            columns=_FACTOR_COLS,
        )
        true_betas = {"MKT": 1.2, "SMB": -0.3, "HML": 0.5, "MOM": 0.4}
        noise = rng.normal(0, 0.002, n)
        returns = pd.Series(
            0.001
            + true_betas["MKT"] * factors["MKT"].values
            + true_betas["SMB"] * factors["SMB"].values
            + true_betas["HML"] * factors["HML"].values
            + true_betas["MOM"] * factors["MOM"].values
            + noise,
            index=dates,
        )
        result = factor_alpha(returns, factors)
        assert abs(result["betas"]["MKT"] - true_betas["MKT"]) < 0.15

    def test_recovered_beta_smb(self):
        rng = np.random.default_rng(42)
        n = 250
        dates = _make_dates(n)
        factors = pd.DataFrame(
            rng.normal(0, 0.01, size=(n, 4)),
            index=dates,
            columns=_FACTOR_COLS,
        )
        true_betas = {"MKT": 1.2, "SMB": -0.3, "HML": 0.5, "MOM": 0.4}
        noise = rng.normal(0, 0.002, n)
        returns = pd.Series(
            0.001
            + true_betas["MKT"] * factors["MKT"].values
            + true_betas["SMB"] * factors["SMB"].values
            + true_betas["HML"] * factors["HML"].values
            + true_betas["MOM"] * factors["MOM"].values
            + noise,
            index=dates,
        )
        result = factor_alpha(returns, factors)
        assert abs(result["betas"]["SMB"] - true_betas["SMB"]) < 0.15

    def test_recovered_beta_hml(self):
        rng = np.random.default_rng(42)
        n = 250
        dates = _make_dates(n)
        factors = pd.DataFrame(
            rng.normal(0, 0.01, size=(n, 4)),
            index=dates,
            columns=_FACTOR_COLS,
        )
        true_betas = {"MKT": 1.2, "SMB": -0.3, "HML": 0.5, "MOM": 0.4}
        noise = rng.normal(0, 0.002, n)
        returns = pd.Series(
            0.001
            + true_betas["MKT"] * factors["MKT"].values
            + true_betas["SMB"] * factors["SMB"].values
            + true_betas["HML"] * factors["HML"].values
            + true_betas["MOM"] * factors["MOM"].values
            + noise,
            index=dates,
        )
        result = factor_alpha(returns, factors)
        assert abs(result["betas"]["HML"] - true_betas["HML"]) < 0.15

    def test_recovered_beta_mom(self):
        rng = np.random.default_rng(42)
        n = 250
        dates = _make_dates(n)
        factors = pd.DataFrame(
            rng.normal(0, 0.01, size=(n, 4)),
            index=dates,
            columns=_FACTOR_COLS,
        )
        true_betas = {"MKT": 1.2, "SMB": -0.3, "HML": 0.5, "MOM": 0.4}
        noise = rng.normal(0, 0.002, n)
        returns = pd.Series(
            0.001
            + true_betas["MKT"] * factors["MKT"].values
            + true_betas["SMB"] * factors["SMB"].values
            + true_betas["HML"] * factors["HML"].values
            + true_betas["MOM"] * factors["MOM"].values
            + noise,
            index=dates,
        )
        result = factor_alpha(returns, factors)
        assert abs(result["betas"]["MOM"] - true_betas["MOM"]) < 0.15

    def test_r_squared_high_for_strong_signal(self):
        rng = np.random.default_rng(42)
        n = 250
        dates = _make_dates(n)
        factors = pd.DataFrame(
            rng.normal(0, 0.01, size=(n, 4)),
            index=dates,
            columns=_FACTOR_COLS,
        )
        true_betas = {"MKT": 1.2, "SMB": -0.3, "HML": 0.5, "MOM": 0.4}
        # very small noise so R^2 should be high
        noise = rng.normal(0, 0.0001, n)
        returns = pd.Series(
            0.001
            + true_betas["MKT"] * factors["MKT"].values
            + true_betas["SMB"] * factors["SMB"].values
            + true_betas["HML"] * factors["HML"].values
            + true_betas["MOM"] * factors["MOM"].values
            + noise,
            index=dates,
        )
        result = factor_alpha(returns, factors)
        assert result["r_squared"] > 0.95

    def test_n_obs_matches_input(self):
        rng = np.random.default_rng(0)
        n = 120
        dates = _make_dates(n)
        factors = pd.DataFrame(
            rng.normal(0, 0.01, size=(n, 4)),
            index=dates,
            columns=_FACTOR_COLS,
        )
        returns = pd.Series(rng.normal(0, 0.01, n), index=dates)
        result = factor_alpha(returns, factors)
        assert result["n_obs"] == n

    def test_result_keys_complete(self):
        rng = np.random.default_rng(0)
        n = 50
        dates = _make_dates(n)
        factors = pd.DataFrame(
            rng.normal(0, 0.01, size=(n, 4)),
            index=dates,
            columns=_FACTOR_COLS,
        )
        returns = pd.Series(rng.normal(0, 0.01, n), index=dates)
        result = factor_alpha(returns, factors)
        assert set(result.keys()) == {"alpha", "alpha_t_stat", "betas", "r_squared", "n_obs"}
        assert set(result["betas"].keys()) == set(_FACTOR_COLS)


class TestPureNoise:
    """Zero-true-alpha returns: t-stat should be small for one fixed seed."""

    def test_t_stat_small_for_noise(self):
        rng = np.random.default_rng(7)
        n = 252
        dates = _make_dates(n)
        factors = pd.DataFrame(
            rng.normal(0, 0.01, size=(n, 4)),
            index=dates,
            columns=_FACTOR_COLS,
        )
        # pure noise: no true alpha, no exposure
        returns = pd.Series(rng.normal(0, 0.01, n), index=dates)
        result = factor_alpha(returns, factors)
        assert abs(result["alpha_t_stat"]) < 2.0


class TestInsufficientObservations:
    """N < k+1 (k=4 factors) must raise ValueError."""

    def test_raises_on_too_few_obs(self):
        rng = np.random.default_rng(0)
        # 4 factors + 1 intercept = 5 params; need > 5 obs; give exactly 5
        n = 5
        dates = _make_dates(n)
        factors = pd.DataFrame(
            rng.normal(0, 0.01, size=(n, 4)),
            index=dates,
            columns=_FACTOR_COLS,
        )
        returns = pd.Series(rng.normal(0, 0.01, n), index=dates)
        with pytest.raises(ValueError, match="n_obs"):
            factor_alpha(returns, factors)

    def test_raises_on_single_obs(self):
        rng = np.random.default_rng(0)
        n = 1
        dates = _make_dates(n)
        factors = pd.DataFrame(
            rng.normal(0, 0.01, size=(n, 4)),
            index=dates,
            columns=_FACTOR_COLS,
        )
        returns = pd.Series(rng.normal(0, 0.01, n), index=dates)
        with pytest.raises(ValueError, match="n_obs"):
            factor_alpha(returns, factors)

    def test_exactly_k_plus_2_is_valid(self):
        """k+2 = 6 observations: just enough to proceed (df_resid = 1)."""
        rng = np.random.default_rng(0)
        n = 6
        dates = _make_dates(n)
        factors = pd.DataFrame(
            rng.normal(0, 0.01, size=(n, 4)),
            index=dates,
            columns=_FACTOR_COLS,
        )
        returns = pd.Series(rng.normal(0, 0.01, n), index=dates)
        # Should not raise
        result = factor_alpha(returns, factors)
        assert result["n_obs"] == n


class TestMisalignedIndices:
    """Returns and factors with different date sets: align on intersection."""

    def test_n_obs_is_intersection(self):
        rng = np.random.default_rng(99)
        all_dates = _make_dates(100)
        returns_dates = all_dates[:80]   # first 80
        factors_dates = all_dates[20:]   # last 80
        # intersection = all_dates[20:80] = 60 dates
        factors = pd.DataFrame(
            rng.normal(0, 0.01, size=(80, 4)),
            index=factors_dates,
            columns=_FACTOR_COLS,
        )
        returns = pd.Series(rng.normal(0, 0.01, 80), index=returns_dates)
        result = factor_alpha(returns, factors)
        assert result["n_obs"] == 60

    def test_misaligned_raises_if_intersection_too_small(self):
        rng = np.random.default_rng(0)
        all_dates = _make_dates(20)
        returns_dates = all_dates[:5]   # only 5 in intersection
        factors_dates = all_dates[0:]
        factors = pd.DataFrame(
            rng.normal(0, 0.01, size=(20, 4)),
            index=factors_dates,
            columns=_FACTOR_COLS,
        )
        returns = pd.Series(rng.normal(0, 0.01, 5), index=returns_dates)
        with pytest.raises(ValueError, match="n_obs"):
            factor_alpha(returns, factors)

    def test_misaligned_values_used_correctly(self):
        """Alignment uses the correct aligned rows, not raw positional rows."""
        rng = np.random.default_rng(11)
        all_dates = _make_dates(100)
        factors = pd.DataFrame(
            rng.normal(0, 0.01, size=(100, 4)),
            index=all_dates,
            columns=_FACTOR_COLS,
        )
        # returns only cover the second 50 dates
        returns_dates = all_dates[50:]
        true_alpha = 0.002
        true_betas = {"MKT": 0.8, "SMB": 0.1, "HML": -0.2, "MOM": 0.3}
        noise = rng.normal(0, 0.001, 50)
        aligned_factors = factors.loc[returns_dates]
        returns = pd.Series(
            true_alpha
            + true_betas["MKT"] * aligned_factors["MKT"].values
            + true_betas["SMB"] * aligned_factors["SMB"].values
            + true_betas["HML"] * aligned_factors["HML"].values
            + true_betas["MOM"] * aligned_factors["MOM"].values
            + noise,
            index=returns_dates,
        )
        result = factor_alpha(returns, factors)
        assert result["n_obs"] == 50
        assert abs(result["alpha"] - true_alpha) < 0.001


class TestReturnTypes:
    """Scalar outputs have correct Python types."""

    def test_alpha_is_float(self):
        rng = np.random.default_rng(0)
        n = 60
        dates = _make_dates(n)
        factors = pd.DataFrame(rng.normal(0, 0.01, (n, 4)), index=dates, columns=_FACTOR_COLS)
        returns = pd.Series(rng.normal(0, 0.01, n), index=dates)
        result = factor_alpha(returns, factors)
        assert isinstance(result["alpha"], float)

    def test_n_obs_is_int(self):
        rng = np.random.default_rng(0)
        n = 60
        dates = _make_dates(n)
        factors = pd.DataFrame(rng.normal(0, 0.01, (n, 4)), index=dates, columns=_FACTOR_COLS)
        returns = pd.Series(rng.normal(0, 0.01, n), index=dates)
        result = factor_alpha(returns, factors)
        assert isinstance(result["n_obs"], int)

    def test_r_squared_in_unit_interval(self):
        rng = np.random.default_rng(0)
        n = 60
        dates = _make_dates(n)
        factors = pd.DataFrame(rng.normal(0, 0.01, (n, 4)), index=dates, columns=_FACTOR_COLS)
        returns = pd.Series(rng.normal(0, 0.01, n), index=dates)
        result = factor_alpha(returns, factors)
        assert 0.0 <= result["r_squared"] <= 1.0
