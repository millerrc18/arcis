"""Tests for src/allocation/risk_parity.py — risk-parity capital allocator."""
import math
import pytest

from src.allocation.risk_parity import allocate_risk_parity


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _equal_vol_series(n: int = 100) -> list[float]:
    """Return a return series with known, stable std dev (~1% per period)."""
    # Alternating +0.01 / -0.01 — zero mean, predictable vol
    return [0.01 if i % 2 == 0 else -0.01 for i in range(n)]


def _double_vol_series(n: int = 100) -> list[float]:
    """Return a series with twice the vol of _equal_vol_series."""
    return [0.02 if i % 2 == 0 else -0.02 for i in range(n)]


def _zero_vol_series(n: int = 100) -> list[float]:
    """Return a flat (zero-variance) series."""
    return [0.01] * n


# ---------------------------------------------------------------------------
# Test: two strategies with identical vol → equal weights
# ---------------------------------------------------------------------------

class TestEqualVol:
    def test_equal_vol_both_weights_are_half(self):
        series = {"A": _equal_vol_series(), "B": _equal_vol_series()}
        weights = allocate_risk_parity(series)
        assert abs(weights["A"] - 0.5) < 1e-9
        assert abs(weights["B"] - 0.5) < 1e-9

    def test_equal_vol_sums_to_one(self):
        series = {"A": _equal_vol_series(), "B": _equal_vol_series()}
        weights = allocate_risk_parity(series)
        assert abs(sum(weights.values()) - 1.0) < 1e-9


# ---------------------------------------------------------------------------
# Test: two strategies, vol ratio 2:1 → inverse-vol weights 1/3 vs 2/3
# ---------------------------------------------------------------------------

class TestUnequalVol:
    def test_inverse_vol_weights(self):
        # A has vol=0.01, B has vol=0.02 → w_A = (1/0.01)/(1/0.01 + 1/0.02) = 2/3
        series = {"A": _equal_vol_series(), "B": _double_vol_series()}
        weights = allocate_risk_parity(series)
        assert abs(weights["A"] - 2 / 3) < 1e-6
        assert abs(weights["B"] - 1 / 3) < 1e-6

    def test_inverse_vol_sum_to_one(self):
        series = {"A": _equal_vol_series(), "B": _double_vol_series()}
        weights = allocate_risk_parity(series)
        assert abs(sum(weights.values()) - 1.0) < 1e-9


# ---------------------------------------------------------------------------
# Test: sum-to-target (leverage target != 1.0)
# ---------------------------------------------------------------------------

class TestLeverageTarget:
    def test_sum_to_custom_target(self):
        series = {"A": _equal_vol_series(), "B": _equal_vol_series()}
        weights = allocate_risk_parity(series, target=2.0)
        assert abs(sum(weights.values()) - 2.0) < 1e-9

    def test_sum_to_default_target_is_one(self):
        series = {"A": _equal_vol_series(), "B": _double_vol_series()}
        weights = allocate_risk_parity(series)
        assert abs(sum(weights.values()) - 1.0) < 1e-9

    def test_proportions_unchanged_with_target(self):
        series = {"A": _equal_vol_series(), "B": _double_vol_series()}
        w1 = allocate_risk_parity(series, target=1.0)
        w2 = allocate_risk_parity(series, target=3.0)
        # Relative proportions must be the same regardless of target
        ratio1 = w1["A"] / w1["B"]
        ratio2 = w2["A"] / w2["B"]
        assert abs(ratio1 - ratio2) < 1e-9


# ---------------------------------------------------------------------------
# Test: three strategies, one with zero variance
# ---------------------------------------------------------------------------

class TestZeroVarStrategy:
    def test_zero_var_raises_value_error(self):
        """A zero-variance strategy raises ValueError because its vol is undefined
        for the inverse-vol formula (1/0 = inf would dominate all others)."""
        series = {
            "A": _equal_vol_series(),
            "B": _double_vol_series(),
            "C": _zero_vol_series(),
        }
        with pytest.raises(ValueError, match="zero variance"):
            allocate_risk_parity(series)


# ---------------------------------------------------------------------------
# Test: boundary conditions
# ---------------------------------------------------------------------------

class TestBoundary:
    def test_empty_input_raises_value_error(self):
        with pytest.raises(ValueError, match="empty"):
            allocate_risk_parity({})

    def test_single_strategy_gets_full_target(self):
        weights = allocate_risk_parity({"solo": _equal_vol_series()})
        assert abs(weights["solo"] - 1.0) < 1e-9

    def test_single_strategy_custom_target(self):
        weights = allocate_risk_parity({"solo": _equal_vol_series()}, target=1.5)
        assert abs(weights["solo"] - 1.5) < 1e-9

    def test_series_with_fewer_than_two_obs_raises(self):
        with pytest.raises(ValueError, match="insufficient"):
            allocate_risk_parity({"A": [0.01], "B": [0.02]})

    def test_empty_series_raises(self):
        with pytest.raises(ValueError, match="insufficient"):
            allocate_risk_parity({"A": [], "B": []})


# ---------------------------------------------------------------------------
# Test: reproducibility
# ---------------------------------------------------------------------------

class TestReproducibility:
    def test_same_input_same_output(self):
        series = {
            "X": _equal_vol_series(),
            "Y": _double_vol_series(),
            "Z": [0.005 if i % 3 == 0 else -0.003 for i in range(120)],
        }
        w1 = allocate_risk_parity(series)
        w2 = allocate_risk_parity(series)
        for key in w1:
            assert w1[key] == w2[key]

    def test_three_strategy_weights_sum_to_one(self):
        series = {
            "X": _equal_vol_series(),
            "Y": _double_vol_series(),
            "Z": [0.005 if i % 3 == 0 else -0.003 for i in range(120)],
        }
        weights = allocate_risk_parity(series)
        assert abs(sum(weights.values()) - 1.0) < 1e-9
