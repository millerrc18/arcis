"""Tests for src/methods/mc_permutation.py.

TEST_STRATEGY:
  - Edge fixture: returns with consistent positive sign and significant Sharpe → p < 0.05.
  - Null fixture: zero-mean random returns → empirical p ≈ uniform on [0, 1] (mean ≈ 0.5 over many seeds).
  - Reproducibility: same seed → same p.
  - Boundary: ≤ 1 trade → ValueError.
"""
from __future__ import annotations

import math
import random

import pytest

from src.methods.mc_permutation import mc_permutation_pvalue


# ---------------------------------------------------------------------------
# Edge fixture: significant positive edge
# ---------------------------------------------------------------------------
def _make_edge_returns(n: int = 60, seed: int = 0) -> tuple[list[float], list[int]]:
    """Returns where long (+1) trades reliably gain ~1% and short (-1) reliably lose.
    Sufficient to produce a clearly significant Sharpe."""
    rng = random.Random(seed)
    returns = []
    directions = []
    for _ in range(n):
        d = 1 if rng.random() < 0.6 else -1
        # Long: +0.01 + small noise; short: +0.008 + small noise
        # Edge: direction correctly calls the sign most of the time
        pnl = d * (0.01 + rng.gauss(0, 0.002))
        returns.append(pnl)
        directions.append(d)
    return returns, directions


def test_edge_pvalue_significant():
    """Strong directional edge → empirical p-value < 0.05.

    Fixture: direction correctly predicts sign of return every time.
    Half longs (positive returns) and half shorts (negative raw returns),
    so signed returns = |r| * sign(d) * sign(r) are all positive.
    Shuffling directions destroys the alignment.
    """
    n = 80
    rng = random.Random(42)
    raw_magnitudes = [abs(rng.gauss(0.01, 0.002)) for _ in range(n)]
    # First half: long (+1) with positive raw returns
    # Second half: short (-1) with negative raw returns
    # So returns * directions are all positive — strong edge
    returns = raw_magnitudes[:n // 2] + [-m for m in raw_magnitudes[n // 2:]]
    directions = [1] * (n // 2) + [-1] * (n // 2)
    p = mc_permutation_pvalue(returns, directions, n_permutations=1000, seed=42)
    assert p < 0.05, f"Expected p < 0.05 for clear edge; got {p}"


# ---------------------------------------------------------------------------
# Null fixture: zero-mean returns → p uniform over many seeds
# ---------------------------------------------------------------------------
def test_null_pvalue_uniform_mean():
    """Zero-mean random returns → mean empirical p ≈ 0.5 over 100 seeds."""
    n = 40
    n_seeds = 100
    pvals = []
    for seed in range(n_seeds):
        rng = random.Random(seed)
        returns = [rng.gauss(0.0, 0.01) for _ in range(n)]
        directions = [1 if rng.random() < 0.5 else -1 for _ in range(n)]
        p = mc_permutation_pvalue(returns, directions, n_permutations=200, seed=seed)
        pvals.append(p)
    mean_p = sum(pvals) / len(pvals)
    assert 0.30 <= mean_p <= 0.70, (
        f"Under null, mean p-value should be ≈ 0.5; got {mean_p:.3f}"
    )


# ---------------------------------------------------------------------------
# Reproducibility: same seed → same result
# ---------------------------------------------------------------------------
def test_reproducibility():
    """Same inputs and seed must produce identical p-values."""
    n = 50
    rng = random.Random(7)
    returns = [rng.gauss(0.005, 0.01) for _ in range(n)]
    directions = [1 if rng.random() < 0.5 else -1 for _ in range(n)]

    p1 = mc_permutation_pvalue(returns, directions, n_permutations=500, seed=99)
    p2 = mc_permutation_pvalue(returns, directions, n_permutations=500, seed=99)
    assert p1 == p2, f"Same seed must give same result; got {p1} vs {p2}"


def test_different_seeds_differ():
    """Different seeds should produce different p-values (with very high probability)."""
    n = 50
    rng = random.Random(7)
    returns = [rng.gauss(0.005, 0.01) for _ in range(n)]
    directions = [1 if rng.random() < 0.5 else -1 for _ in range(n)]

    p1 = mc_permutation_pvalue(returns, directions, n_permutations=200, seed=1)
    p2 = mc_permutation_pvalue(returns, directions, n_permutations=200, seed=2)
    # They should differ; extremely unlikely to collide at float precision
    assert p1 != p2, "Different seeds should produce different p-values"


# ---------------------------------------------------------------------------
# Boundary: ≤ 1 trade → ValueError
# ---------------------------------------------------------------------------
def test_single_trade_raises():
    """Exactly one trade must raise ValueError."""
    with pytest.raises(ValueError):
        mc_permutation_pvalue([0.01], [1], n_permutations=100, seed=0)


def test_zero_trades_raises():
    """Empty inputs must raise ValueError."""
    with pytest.raises(ValueError):
        mc_permutation_pvalue([], [], n_permutations=100, seed=0)


# ---------------------------------------------------------------------------
# Default n_permutations = 1000
# ---------------------------------------------------------------------------
def test_default_n_permutations():
    """Calling without n_permutations uses 1000 permutations (result is a float in [0,1])."""
    rng = random.Random(3)
    n = 30
    returns = [rng.gauss(0.005, 0.01) for _ in range(n)]
    directions = [1 if rng.random() < 0.5 else -1 for _ in range(n)]
    p = mc_permutation_pvalue(returns, directions, seed=3)
    assert isinstance(p, float)
    assert 0.0 <= p <= 1.0


# ---------------------------------------------------------------------------
# Return type and range
# ---------------------------------------------------------------------------
def test_pvalue_in_unit_interval():
    """p-value must always be in [0, 1]."""
    rng = random.Random(5)
    n = 40
    returns = [rng.gauss(0.0, 0.01) for _ in range(n)]
    directions = [1 if rng.random() < 0.5 else -1 for _ in range(n)]
    p = mc_permutation_pvalue(returns, directions, n_permutations=200, seed=5)
    assert 0.0 <= p <= 1.0, f"p-value {p} out of [0,1]"


# ---------------------------------------------------------------------------
# Mismatched lengths
# ---------------------------------------------------------------------------
def test_mismatched_lengths_raises():
    """Mismatched returns/directions lengths must raise ValueError."""
    with pytest.raises(ValueError):
        mc_permutation_pvalue([0.01, 0.02], [1], n_permutations=100, seed=0)
