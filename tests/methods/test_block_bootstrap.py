"""Tests for stationary block bootstrap (T2.02).

Covers:
- CI coverage ≈ 95% on AR(1) synthetic series
- Block-length auto-selection: white noise → small block; slow-decay AR → larger block
- Boundary: T < 30 → ValueError
- Reproducibility: same seed → same CI
"""
from __future__ import annotations

import math

import numpy as np
import pytest

from src.methods.block_bootstrap import (
    block_bootstrap_ci,
    optimal_block_length,
)


def _ar1_series(rng: np.random.Generator, n: int, phi: float, sigma: float = 1.0) -> np.ndarray:
    """Generate an AR(1) series: x_t = phi * x_{t-1} + eps_t."""
    x = np.zeros(n)
    for t in range(1, n):
        x[t] = phi * x[t - 1] + rng.normal(0.0, sigma)
    return x


# ---------------------------------------------------------------------------
# Block-length selection
# ---------------------------------------------------------------------------

class TestOptimalBlockLength:
    def test_white_noise_gives_small_block(self):
        """IID white noise: optimal block should be small (≈ 1-3)."""
        rng = np.random.default_rng(42)
        series = rng.normal(0.0, 1.0, size=300)
        b = optimal_block_length(series)
        assert 1 <= b <= 6, f"Expected small block for white noise, got {b}"

    def test_slow_decay_ar1_gives_larger_block(self):
        """Slow AR(1) with phi=0.8: optimal block should be > 5."""
        rng = np.random.default_rng(42)
        series = _ar1_series(rng, n=300, phi=0.8)
        b = optimal_block_length(series)
        assert b > 5, f"Expected large block for slow-decay AR(1), got {b}"

    def test_returns_integer(self):
        rng = np.random.default_rng(0)
        series = rng.normal(size=100)
        b = optimal_block_length(series)
        assert isinstance(b, int)
        assert b >= 1


# ---------------------------------------------------------------------------
# Boundary / ValueError
# ---------------------------------------------------------------------------

class TestBoundaryConditions:
    def test_too_short_raises(self):
        """T < 30 should raise ValueError."""
        short = np.random.default_rng(0).normal(size=29)
        with pytest.raises(ValueError, match="[Ii]nsufficient"):
            block_bootstrap_ci(short, rf_period=0.0)

    def test_exactly_30_does_not_raise(self):
        """T == 30 should succeed without error."""
        series = np.random.default_rng(1).normal(0.001, 0.01, size=30)
        lo, hi = block_bootstrap_ci(series, rf_period=0.0, n_resamples=200, seed=7)
        assert lo <= hi


# ---------------------------------------------------------------------------
# Reproducibility
# ---------------------------------------------------------------------------

class TestReproducibility:
    def test_same_seed_same_ci(self):
        """Identical seeds must produce bit-identical CIs."""
        rng = np.random.default_rng(99)
        series = rng.normal(0.0005, 0.01, size=200)
        ci_a = block_bootstrap_ci(series, rf_period=0.0, n_resamples=500, seed=123)
        ci_b = block_bootstrap_ci(series, rf_period=0.0, n_resamples=500, seed=123)
        assert ci_a == ci_b

    def test_different_seeds_differ(self):
        """Different seeds should (almost certainly) differ for stochastic series."""
        rng = np.random.default_rng(7)
        series = rng.normal(0.0005, 0.01, size=200)
        ci_a = block_bootstrap_ci(series, rf_period=0.0, n_resamples=500, seed=1)
        ci_b = block_bootstrap_ci(series, rf_period=0.0, n_resamples=500, seed=2)
        # Not guaranteed but overwhelmingly likely for a stochastic method
        assert ci_a != ci_b


# ---------------------------------------------------------------------------
# CI structure
# ---------------------------------------------------------------------------

class TestCIStructure:
    def test_returns_tuple_of_two_floats(self):
        rng = np.random.default_rng(5)
        series = rng.normal(0.001, 0.01, size=100)
        result = block_bootstrap_ci(series, rf_period=0.0, n_resamples=200, seed=0)
        assert isinstance(result, tuple)
        assert len(result) == 2
        lo, hi = result
        assert isinstance(lo, float)
        assert isinstance(hi, float)

    def test_lower_le_upper(self):
        rng = np.random.default_rng(3)
        series = rng.normal(0.001, 0.01, size=150)
        lo, hi = block_bootstrap_ci(series, rf_period=0.0, n_resamples=300, seed=0)
        assert lo <= hi

    def test_rf_period_shifts_ci(self):
        """Subtracting a non-zero rf_period should shift the Sharpe distribution."""
        rng = np.random.default_rng(11)
        series = rng.normal(0.005, 0.01, size=200)
        lo0, hi0 = block_bootstrap_ci(series, rf_period=0.0, n_resamples=300, seed=42)
        lo1, hi1 = block_bootstrap_ci(series, rf_period=0.001, n_resamples=300, seed=42)
        # Higher rf → lower Sharpe → CI should be lower
        assert hi1 < hi0


# ---------------------------------------------------------------------------
# CI coverage (statistical — uses many runs, so keep fast)
# ---------------------------------------------------------------------------

class TestCICoverage:
    def test_95_ci_coverage_ar1(self):
        """Empirical coverage should be near 95% (tolerance ±7pp) on AR(1)."""
        phi = 0.4
        sigma = 0.01
        rf = 0.0001
        n_series = 200   # number of independent series to check coverage
        n = 200          # length of each series (kept small for speed)
        n_resamples = 500

        # True population Sharpe for this AR(1): mean/std * sqrt(252)
        true_mean = 0.0
        true_std = sigma / math.sqrt(1 - phi ** 2)
        true_sharpe = (true_mean - rf * n) / true_std * math.sqrt(252)
        # With mean=0 and rf>0 the true sharpe is negative — that's fine for
        # coverage; we just need CIs to straddle the true value ~95% of the time.
        # To make this test robust, use a positive drift series instead.
        mu = 0.0004  # intercept so true E[x_t] = mu/(1-phi) > 0
        # Stationary AR(1): x_t = mu + phi*x_{t-1} + eps
        # E[x_t] = mu/(1-phi),  Var[x_t] = sigma^2/(1-phi^2)
        true_mean = mu / (1.0 - phi)
        true_sharpe = (true_mean - rf) / (sigma / math.sqrt(1 - phi ** 2)) * math.sqrt(252)

        covered = 0
        master_rng = np.random.default_rng(2024)
        for i in range(n_series):
            seed = int(master_rng.integers(0, 2**31))
            rng = np.random.default_rng(seed)
            # AR(1) with drift
            x = np.zeros(n)
            for t in range(1, n):
                x[t] = mu + phi * x[t - 1] + rng.normal(0.0, sigma)
            lo, hi = block_bootstrap_ci(x, rf_period=rf, n_resamples=n_resamples, seed=seed)
            if lo <= true_sharpe <= hi:
                covered += 1

        empirical = covered / n_series
        assert 0.88 <= empirical <= 1.00, (
            f"Coverage {empirical:.3f} outside [0.88, 1.00] — "
            f"stationary bootstrap CI may be miscalibrated"
        )
