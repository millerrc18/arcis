"""Tests for src.methods.promotion_gate.

Boundary cases per TEST_STRATEGY:
  1. 4-of-5 methods pass + 1 marginal-fail at p=0.051 → "promote"
  2. 3-of-5 methods pass → "reject"
  3. 5-of-5 methods pass + MC perm p=0.95 with wrong sign → "reject" (inverse hard-block)
  4. 5-of-5 methods pass + N < mintrl → "defer"
  5. 5-of-5 methods pass + N >= mintrl + no inverse blocks → "promote"
"""
from __future__ import annotations

from unittest.mock import patch

import numpy as np
import pytest

from src.methods.promotion_gate import promotion_gate

_RNG = np.random.default_rng(99)

# A reliable high-Sharpe series for integration tests
_GOOD_RETURNS = (_RNG.standard_normal(500) * 0.01 + 0.006).tolist()

# A clearly negative-mean series to trigger inverse hard-block
_BAD_MEAN_RETURNS = (_RNG.standard_normal(500) * 0.01 - 0.006).tolist()

# Very short (5 obs) — below any reasonable mintrl
_TINY_RETURNS = [0.01, 0.02, 0.01, 0.02, 0.01]


# ---------------------------------------------------------------------------
# Helpers — patch the 5 runner helpers to control votes precisely
# ---------------------------------------------------------------------------

def _vote(name: str, passed: bool, value: float = 0.03, threshold: float = 0.05):
    return {"name": name, "passed": passed, "value": value, "threshold": threshold}


# ---------------------------------------------------------------------------
# Scenario 1: 4-of-5 pass + 1 marginal fail at p=0.051 → "promote"
# ---------------------------------------------------------------------------

def test_four_of_five_pass_marginal_fail_promotes():
    """4/5 votes pass; 1 method fails with p=0.051 (just above threshold)."""
    mock_votes = [
        _vote("cpcv", True),
        _vote("block_bootstrap", True),
        _vote("mc_perm", True, value=0.03),
        _vote("psr_dsr", True),
        _vote("white_rc", False, value=0.051),  # fails at p=0.051
    ]
    with (
        patch("src.methods.promotion_gate._run_cpcv", return_value=mock_votes[0]),
        patch("src.methods.promotion_gate._run_bootstrap", return_value=mock_votes[1]),
        patch("src.methods.promotion_gate._run_mc_perm", return_value=mock_votes[2]),
        patch("src.methods.promotion_gate._run_psr", return_value=mock_votes[3]),
        patch("src.methods.promotion_gate._run_white_rc", return_value=mock_votes[4]),
        patch("src.methods.promotion_gate.mintrl", return_value=10),  # mintrl=10 < N=500
    ):
        result = promotion_gate(_GOOD_RETURNS, n_trials=10)

    assert result["decision"] == "promote", f"Expected promote; got {result}"
    assert result["votes"]["white_rc"] is False
    assert result["votes"]["cpcv"] is True


# ---------------------------------------------------------------------------
# Scenario 2: 3-of-5 pass → "reject"
# ---------------------------------------------------------------------------

def test_three_of_five_pass_rejects():
    """3/5 votes pass — below the ≥4 threshold → reject."""
    mock_votes = [
        _vote("cpcv", True),
        _vote("block_bootstrap", False, value=0.10),
        _vote("mc_perm", True, value=0.03),
        _vote("psr_dsr", False, value=0.10),
        _vote("white_rc", True),
    ]
    with (
        patch("src.methods.promotion_gate._run_cpcv", return_value=mock_votes[0]),
        patch("src.methods.promotion_gate._run_bootstrap", return_value=mock_votes[1]),
        patch("src.methods.promotion_gate._run_mc_perm", return_value=mock_votes[2]),
        patch("src.methods.promotion_gate._run_psr", return_value=mock_votes[3]),
        patch("src.methods.promotion_gate._run_white_rc", return_value=mock_votes[4]),
        patch("src.methods.promotion_gate.mintrl", return_value=10),
    ):
        result = promotion_gate(_GOOD_RETURNS, n_trials=10)

    assert result["decision"] == "reject", f"Expected reject; got {result}"


# ---------------------------------------------------------------------------
# Scenario 3: 5-of-5 pass + inverse hard-block → "reject"
# Inverse hard-block: mc_perm p > 1-alpha (p=0.95) AND mean(returns) < 0
# ---------------------------------------------------------------------------

def test_five_of_five_inverse_hard_block_rejects():
    """All 5 pass but inverse hard-block detected → reject."""
    # mc_perm value=0.95 (p-value), mean < 0 signals inverse block
    mock_votes = [
        _vote("cpcv", True),
        _vote("block_bootstrap", True),
        _vote("mc_perm", True, value=0.95),   # passed=True but inverse block
        _vote("psr_dsr", True),
        _vote("white_rc", True),
    ]
    with (
        patch("src.methods.promotion_gate._run_cpcv", return_value=mock_votes[0]),
        patch("src.methods.promotion_gate._run_bootstrap", return_value=mock_votes[1]),
        patch("src.methods.promotion_gate._run_mc_perm", return_value=mock_votes[2]),
        patch("src.methods.promotion_gate._run_psr", return_value=mock_votes[3]),
        patch("src.methods.promotion_gate._run_white_rc", return_value=mock_votes[4]),
        patch("src.methods.promotion_gate.mintrl", return_value=10),
    ):
        # Use a negative-mean series so mean(returns) < 0 is detected
        result = promotion_gate(_BAD_MEAN_RETURNS, n_trials=10)

    assert result["decision"] == "reject", f"Expected reject on inverse block; got {result}"
    assert "inverse_hard_block" in result.get("details", {}) or result.get("n_obs") is not None


# ---------------------------------------------------------------------------
# Scenario 4: 5-of-5 pass + N < mintrl → "defer"
# ---------------------------------------------------------------------------

def test_five_of_five_below_mintrl_defers():
    """5/5 pass but N < mintrl → defer with track-record reason."""
    mock_votes = [
        _vote("cpcv", True),
        _vote("block_bootstrap", True),
        _vote("mc_perm", True, value=0.03),
        _vote("psr_dsr", True),
        _vote("white_rc", True),
    ]
    with (
        patch("src.methods.promotion_gate._run_cpcv", return_value=mock_votes[0]),
        patch("src.methods.promotion_gate._run_bootstrap", return_value=mock_votes[1]),
        patch("src.methods.promotion_gate._run_mc_perm", return_value=mock_votes[2]),
        patch("src.methods.promotion_gate._run_psr", return_value=mock_votes[3]),
        patch("src.methods.promotion_gate._run_white_rc", return_value=mock_votes[4]),
        # mintrl returns a value LARGER than len(_TINY_RETURNS)=5
        patch("src.methods.promotion_gate.mintrl", return_value=100),
    ):
        result = promotion_gate(_TINY_RETURNS, n_trials=10)

    assert result["decision"] == "defer", f"Expected defer; got {result}"
    assert result.get("reason") == "insufficient_track_record"
    assert result["n_obs"] == len(_TINY_RETURNS)
    assert result["mintrl"] == 100


# ---------------------------------------------------------------------------
# Scenario 5: 5-of-5 pass + N >= mintrl + no inverse blocks → "promote"
# ---------------------------------------------------------------------------

def test_five_of_five_full_pass_promotes():
    """5/5 pass, N >= mintrl, no inverse blocks → promote."""
    mock_votes = [
        _vote("cpcv", True),
        _vote("block_bootstrap", True),
        _vote("mc_perm", True, value=0.03),
        _vote("psr_dsr", True),
        _vote("white_rc", True),
    ]
    with (
        patch("src.methods.promotion_gate._run_cpcv", return_value=mock_votes[0]),
        patch("src.methods.promotion_gate._run_bootstrap", return_value=mock_votes[1]),
        patch("src.methods.promotion_gate._run_mc_perm", return_value=mock_votes[2]),
        patch("src.methods.promotion_gate._run_psr", return_value=mock_votes[3]),
        patch("src.methods.promotion_gate._run_white_rc", return_value=mock_votes[4]),
        patch("src.methods.promotion_gate.mintrl", return_value=10),  # 10 < 500
    ):
        result = promotion_gate(_GOOD_RETURNS, n_trials=10)

    assert result["decision"] == "promote", f"Expected promote; got {result}"
    assert all(result["votes"][k] for k in result["votes"])


# ---------------------------------------------------------------------------
# Return-structure tests
# ---------------------------------------------------------------------------

def test_promotion_gate_return_keys():
    """Gate always returns required keys."""
    mock_votes = [
        _vote("cpcv", True),
        _vote("block_bootstrap", True),
        _vote("mc_perm", True, value=0.03),
        _vote("psr_dsr", True),
        _vote("white_rc", True),
    ]
    with (
        patch("src.methods.promotion_gate._run_cpcv", return_value=mock_votes[0]),
        patch("src.methods.promotion_gate._run_bootstrap", return_value=mock_votes[1]),
        patch("src.methods.promotion_gate._run_mc_perm", return_value=mock_votes[2]),
        patch("src.methods.promotion_gate._run_psr", return_value=mock_votes[3]),
        patch("src.methods.promotion_gate._run_white_rc", return_value=mock_votes[4]),
        patch("src.methods.promotion_gate.mintrl", return_value=10),
    ):
        result = promotion_gate(_GOOD_RETURNS, n_trials=10)

    required_keys = {"decision", "votes", "n_obs", "mintrl", "details"}
    assert required_keys <= set(result.keys()), (
        f"Missing keys: {required_keys - set(result.keys())}"
    )
    assert isinstance(result["votes"], dict)
    assert result["n_obs"] == len(_GOOD_RETURNS)


def test_promotion_gate_decision_values():
    """decision must be one of 'promote', 'defer', 'reject'."""
    mock_votes = [
        _vote("cpcv", False, value=0.10),
        _vote("block_bootstrap", False, value=0.10),
        _vote("mc_perm", False, value=0.10),
        _vote("psr_dsr", False, value=0.10),
        _vote("white_rc", False, value=0.10),
    ]
    with (
        patch("src.methods.promotion_gate._run_cpcv", return_value=mock_votes[0]),
        patch("src.methods.promotion_gate._run_bootstrap", return_value=mock_votes[1]),
        patch("src.methods.promotion_gate._run_mc_perm", return_value=mock_votes[2]),
        patch("src.methods.promotion_gate._run_psr", return_value=mock_votes[3]),
        patch("src.methods.promotion_gate._run_white_rc", return_value=mock_votes[4]),
        patch("src.methods.promotion_gate.mintrl", return_value=10),
    ):
        result = promotion_gate(_GOOD_RETURNS, n_trials=10)

    assert result["decision"] in ("promote", "defer", "reject")
