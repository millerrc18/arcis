"""Tests for White's Reality Check (white_rc.py).

Authority: White, H. (2000). "A Reality Check for Data Snooping."
  Econometrica, 68(5), 1097-1126.

Tests cover:
- dominant strategy → small nominal-p
- all-null strategies → approximately uniform nominal-p
- tied Sharpes → no crash, valid p returned
- reproducibility with same seed
- boundary: 1 strategy → ValueError
- boundary: T < 30 → ValueError
"""
from __future__ import annotations

import numpy as np
import pytest

from src.methods.white_rc import white_rc


_RNG_SEED = 42


class TestDominantStrategy:
    """One clearly dominant strategy should yield a small nominal-p."""

    def test_dominant_strategy_small_p(self):
        rng = np.random.default_rng(_RNG_SEED)
        T = 252
        # Dominant: very high mean relative to its vol (Sharpe > 10 per period)
        dominant = np.full(T, 0.01) + rng.normal(loc=0.0, scale=0.0005, size=T)
        # Noisy strategies with near-zero mean and higher vol
        noise = rng.normal(loc=0.0, scale=0.02, size=(T, 4))
        returns = np.column_stack([dominant, noise])

        p = white_rc(returns, n_resamples=500, seed=_RNG_SEED)

        assert 0.0 <= p <= 1.0, f"p-value out of [0,1]: {p}"
        assert p < 0.1, f"Expected small p for dominant strategy, got {p:.4f}"


class TestAllNullStrategies:
    """All zero-mean strategies → nominal-p should be roughly uniform [0,1]."""

    def test_null_fixture_p_near_half_over_seeds(self):
        T = 252
        n_strategies = 5
        p_values = []
        for seed in range(30):
            rng = np.random.default_rng(seed)
            returns = rng.normal(loc=0.0, scale=0.01, size=(T, n_strategies))
            p = white_rc(returns, n_resamples=500, seed=seed)
            assert 0.0 <= p <= 1.0, f"p-value out of [0,1] at seed {seed}: {p}"
            p_values.append(p)

        mean_p = float(np.mean(p_values))
        assert 0.2 < mean_p < 0.8, (
            f"Mean p over null seeds expected near 0.5, got {mean_p:.4f}"
        )


class TestTiedSharpes:
    """Two strategies with identical realized returns → no crash, valid p."""

    def test_tied_sharpes_returns_valid_p(self):
        rng = np.random.default_rng(_RNG_SEED)
        T = 60
        base = rng.normal(loc=0.001, scale=0.01, size=T)
        returns = np.column_stack([base, base])

        p = white_rc(returns, n_resamples=500, seed=_RNG_SEED)

        assert 0.0 <= p <= 1.0, f"p-value out of [0,1]: {p}"


class TestReproducibility:
    """Same seed → same nominal-p."""

    def test_same_seed_same_p(self):
        rng = np.random.default_rng(_RNG_SEED)
        T = 120
        returns = rng.normal(loc=0.001, scale=0.01, size=(T, 3))

        p1 = white_rc(returns, n_resamples=500, seed=77)
        p2 = white_rc(returns, n_resamples=500, seed=77)

        assert p1 == p2, f"Same seed produced different p-values: {p1} vs {p2}"

    def test_different_seeds_can_differ(self):
        rng = np.random.default_rng(_RNG_SEED)
        T = 120
        returns = rng.normal(loc=0.001, scale=0.01, size=(T, 3))

        p1 = white_rc(returns, n_resamples=500, seed=1)
        p2 = white_rc(returns, n_resamples=500, seed=2)

        # Not guaranteed to differ but with 500 resamples they almost certainly will
        # Just check both are valid
        assert 0.0 <= p1 <= 1.0
        assert 0.0 <= p2 <= 1.0


class TestBoundaryConditions:
    """ValueError cases."""

    def test_single_strategy_raises(self):
        rng = np.random.default_rng(_RNG_SEED)
        T = 60
        returns = rng.normal(size=(T, 1))

        with pytest.raises(ValueError, match="at least 2"):
            white_rc(returns, n_resamples=100, seed=_RNG_SEED)

    def test_1d_single_strategy_raises(self):
        rng = np.random.default_rng(_RNG_SEED)
        returns = rng.normal(size=60)

        with pytest.raises(ValueError):
            white_rc(returns, n_resamples=100, seed=_RNG_SEED)

    def test_insufficient_data_raises(self):
        rng = np.random.default_rng(_RNG_SEED)
        T = 20  # < 30
        returns = rng.normal(size=(T, 3))

        with pytest.raises(ValueError, match="30"):
            white_rc(returns, n_resamples=100, seed=_RNG_SEED)

    def test_exactly_30_rows_is_valid(self):
        rng = np.random.default_rng(_RNG_SEED)
        returns = rng.normal(size=(30, 2))

        p = white_rc(returns, n_resamples=100, seed=_RNG_SEED)

        assert 0.0 <= p <= 1.0
