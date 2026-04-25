"""Tests for src/methods/cpcv.py — Combinatorial Purged Cross-Validation.

Covers:
- Positive-edge fixture: constant +0.5 daily return yields positive OOS Sharpe in every fold.
- Null fixture: zero-mean random walk mean OOS Sharpe across folds ≈ 0.
- Embargo invariant: no train index within 10 sessions of any test index per fold.
- Anchored walk-forward: each fold's train window starts at index 0.
- ValueError on bad inputs.
"""

from __future__ import annotations

import numpy as np
import pytest

from src.methods.cpcv import cpcv, cpcv_anchored


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SEED = 42
T = 300  # long enough for K=5 folds + embargo=10


def _constant_returns(t: int, val: float = 0.5) -> np.ndarray:
    """Strong-positive-edge return series: high mean, tiny noise so std > 0."""
    rng = np.random.default_rng(SEED)
    noise = rng.normal(0.0, 1e-6, size=t)
    return np.full(t, val, dtype=float) + noise


def _random_returns(t: int, seed: int = SEED) -> np.ndarray:
    """Zero-mean random walk returns."""
    rng = np.random.default_rng(seed)
    return rng.normal(0.0, 1.0, size=t)


# ---------------------------------------------------------------------------
# cpcv — positive-edge fixture
# ---------------------------------------------------------------------------

def test_cpcv_positive_edge_all_folds_positive():
    """Constant +0.5 return must yield positive rf-adjusted Sharpe in every fold."""
    returns = _constant_returns(T, val=0.5)
    result = cpcv(returns, k=5, embargo=10, rf_period=0.0)
    assert isinstance(result, dict)
    assert "fold_sharpes" in result
    sharpes = result["fold_sharpes"]
    assert len(sharpes) == 5
    for i, s in enumerate(sharpes):
        assert s is not None, f"fold {i} Sharpe is None"
        assert s > 0.0, f"fold {i} Sharpe {s!r} is not positive"


# ---------------------------------------------------------------------------
# cpcv — null fixture (zero-mean random walk)
# ---------------------------------------------------------------------------

def test_cpcv_null_fixture_mean_near_zero():
    """Zero-mean random walk mean OOS Sharpe across folds should be near zero.

    We use a tolerance of 2.5 annualised units — with 300 observations and
    symmetric noise the per-fold OOS Sharpe expectation is 0; individual
    folds will fluctuate but the mean should be well within +/-2.5.
    """
    returns = _random_returns(T)
    result = cpcv(returns, k=5, embargo=10, rf_period=0.0)
    sharpes = [s for s in result["fold_sharpes"] if s is not None]
    assert len(sharpes) > 0
    mean_sharpe = float(np.mean(sharpes))
    assert abs(mean_sharpe) < 2.5, f"mean OOS Sharpe {mean_sharpe:.4f} too far from 0"


# ---------------------------------------------------------------------------
# cpcv — embargo invariant
# ---------------------------------------------------------------------------

def test_cpcv_embargo_invariant():
    """No train index may fall within `embargo` sessions of any test index."""
    returns = _constant_returns(T)
    embargo = 10
    result = cpcv(returns, k=5, embargo=embargo, rf_period=0.0)
    assert "fold_indices" in result
    for fold_idx, (train_idx, test_idx) in enumerate(result["fold_indices"]):
        train_set = set(train_idx)
        test_set = set(test_idx)
        for ti in test_set:
            buffer = set(range(ti - embargo, ti + embargo + 1))
            overlap = train_set & buffer
            assert len(overlap) == 0, (
                f"fold {fold_idx}: train indices {sorted(overlap)} fall within "
                f"embargo={embargo} of test index {ti}"
            )


# ---------------------------------------------------------------------------
# cpcv_anchored — train window always starts at index 0
# ---------------------------------------------------------------------------

def test_cpcv_anchored_train_starts_at_zero():
    """Each fold's training window must start at index 0 (anchored walk-forward)."""
    returns = _constant_returns(T)
    result = cpcv_anchored(returns, k=5, embargo=10, rf_period=0.0)
    assert "fold_indices" in result
    for fold_idx, (train_idx, test_idx) in enumerate(result["fold_indices"]):
        assert len(train_idx) > 0, f"fold {fold_idx} has empty training set"
        assert int(np.min(train_idx)) == 0, (
            f"fold {fold_idx} training window does not start at 0 "
            f"(min index = {int(np.min(train_idx))})"
        )


def test_cpcv_anchored_positive_edge():
    """Anchored variant also returns positive Sharpe on positive-edge fixture."""
    returns = _constant_returns(T, val=0.5)
    result = cpcv_anchored(returns, k=5, embargo=10, rf_period=0.0)
    sharpes = result["fold_sharpes"]
    assert len(sharpes) == 5
    for i, s in enumerate(sharpes):
        assert s is not None, f"fold {i} Sharpe is None"
        assert s > 0.0, f"fold {i} Sharpe {s!r} is not positive"


# ---------------------------------------------------------------------------
# ValueError on bad inputs
# ---------------------------------------------------------------------------

def test_cpcv_raises_on_short_series():
    """Series too short for the requested folds + embargo must raise ValueError."""
    with pytest.raises(ValueError):
        cpcv(np.ones(5), k=5, embargo=10, rf_period=0.0)


def test_cpcv_raises_on_bad_k():
    """k < 2 must raise ValueError."""
    with pytest.raises(ValueError):
        cpcv(_constant_returns(T), k=1, embargo=10, rf_period=0.0)


def test_cpcv_raises_on_negative_embargo():
    """Negative embargo must raise ValueError."""
    with pytest.raises(ValueError):
        cpcv(_constant_returns(T), k=5, embargo=-1, rf_period=0.0)


def test_cpcv_raises_on_1d_required():
    """2-D input must raise ValueError (function expects 1-D returns)."""
    with pytest.raises(ValueError):
        cpcv(np.ones((T, 3)), k=5, embargo=10, rf_period=0.0)
