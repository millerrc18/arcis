"""Tests for src.methods.pbo (Probability of Backtest Overfitting).

Authority: Bailey, Borwein, López de Prado & Zhu (2014),
"The Probability of Backtest Overfitting", Journal of Computational Finance.

PBO is diagnostic only — these tests verify the math, not gating.
"""

from __future__ import annotations

import numpy as np
import pytest

from src.methods.pbo import pbo


class TestPBOBoundary:
    """Boundary conditions: T<8 or N<2 must raise ValueError."""

    def test_T_too_small_raises(self):
        rng = np.random.default_rng(0)
        returns = rng.standard_normal((7, 4))
        with pytest.raises(ValueError):
            pbo(returns)

    def test_N_too_small_raises(self):
        rng = np.random.default_rng(0)
        returns = rng.standard_normal((100, 1))
        with pytest.raises(ValueError):
            pbo(returns)

    def test_zero_T_raises(self):
        returns = np.zeros((0, 4))
        with pytest.raises(ValueError):
            pbo(returns)

    def test_one_dim_raises(self):
        with pytest.raises(ValueError):
            pbo(np.zeros(100))

    def test_minimum_valid_shape_runs(self):
        # T=8, N=2 — minimum allowed
        rng = np.random.default_rng(0)
        returns = rng.standard_normal((8, 2))
        result = pbo(returns)
        assert isinstance(result, float)
        assert 0.0 <= result <= 1.0


class TestPBORange:
    """Output is always in [0, 1]."""

    def test_returns_scalar_in_unit_interval(self):
        rng = np.random.default_rng(42)
        returns = rng.standard_normal((200, 8))
        result = pbo(returns, S=8)
        assert isinstance(result, float)
        assert 0.0 <= result <= 1.0


class TestPBONoise:
    """Synthetic random returns (no overfitting): PBO ~ 0.5 within ±0.1
    averaged over many trials."""

    def test_random_returns_pbo_near_half(self):
        # Use S=8 (C(8,4)=70 splits/trial) for tractable runtime over
        # 100 trials. Spec allows S=8 or S=16; both should center on 0.5.
        n_trials = 100
        T, N = 200, 16
        pbos = np.empty(n_trials)
        rng = np.random.default_rng(2024)
        for i in range(n_trials):
            returns = rng.standard_normal((T, N))
            pbos[i] = pbo(returns, S=8)
        mean_pbo = float(np.mean(pbos))
        assert abs(mean_pbo - 0.5) < 0.1, (
            f"random returns should average ~0.5; got {mean_pbo:.3f}"
        )


class TestPBORiggedBestAlwaysWins:
    """If one strategy is best both IS and OOS in every split,
    PBO should be close to 0 (no overfitting signature)."""

    def test_dominant_strategy_low_pbo(self):
        # Build returns where strategy 0 dominates uniformly:
        # constant high mean, low noise; others have zero mean.
        rng = np.random.default_rng(7)
        T, N = 200, 8
        returns = rng.standard_normal((T, N)) * 0.01
        returns[:, 0] += 0.05  # strategy 0 always wins
        result = pbo(returns)
        assert result < 0.1, f"dominant strategy should yield PBO < 0.1; got {result:.3f}"


class TestPBORiggedBestBecomesWorst:
    """If the IS-best is always the OOS-worst, PBO should be close to 1."""

    def test_anti_correlated_high_pbo(self):
        # Construct a returns matrix where the IS winner is forced to be
        # the OOS loser via per-block specialists.
        #
        # Setup with S=8 blocks and N=8 strategies (one per block).
        # In block b, strategy b receives a large positive return and all
        # other strategies receive a large negative return. Outside its
        # specialist block, strategy b is the worst.
        # For any IS subset of S/2=4 blocks {b_1..b_4}, the IS-best
        # strategy is one of those four specialists (say b*). In OOS
        # (the other 4 blocks), strategy b* is forced to last place
        # (it's the only strategy that's negative in all 4 OOS blocks).
        # So the IS-best becomes OOS-worst on every split → PBO = 1.
        T = 256
        S = 8
        N = 8
        block_size = T // S
        rng = np.random.default_rng(11)
        # Tiny noise so std is non-zero.
        returns = rng.standard_normal((T, N)) * 1e-6
        for b in range(S):
            start = b * block_size
            end = start + block_size
            # All strategies very negative in this block...
            returns[start:end, :] += -1.0
            # ...except strategy b which is very positive.
            returns[start:end, b] += 2.0
        result = pbo(returns, S=S)
        assert result > 0.9, f"per-block specialists should yield PBO > 0.9; got {result:.3f}"


class TestPBOPartitionsOption:
    """S parameter must be even; default S=16. Reject odd S."""

    def test_default_runs(self):
        rng = np.random.default_rng(0)
        returns = rng.standard_normal((200, 4))
        result = pbo(returns)
        assert 0.0 <= result <= 1.0

    def test_S_8_runs(self):
        rng = np.random.default_rng(0)
        returns = rng.standard_normal((200, 4))
        result = pbo(returns, S=8)
        assert 0.0 <= result <= 1.0

    def test_odd_S_raises(self):
        rng = np.random.default_rng(0)
        returns = rng.standard_normal((200, 4))
        with pytest.raises(ValueError):
            pbo(returns, S=7)

    def test_S_zero_raises(self):
        rng = np.random.default_rng(0)
        returns = rng.standard_normal((200, 4))
        with pytest.raises(ValueError):
            pbo(returns, S=0)
