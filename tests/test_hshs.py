"""Tests for the Arcis System Health Score (HSHS) computation."""

import math
import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.evaluation.hshs import (
    compute_hshs_score,
    _weighted_geometric_mean,
    _get_phase,
    PHASE_WEIGHTS,
    DIMENSION_KEYS,
)


class TestPhaseSelection:
    def test_early_phase_month_1(self):
        assert _get_phase(1) == "early"

    def test_early_phase_month_6(self):
        assert _get_phase(6) == "early"

    def test_growth_phase_month_7(self):
        assert _get_phase(7) == "growth"

    def test_growth_phase_month_18(self):
        assert _get_phase(18) == "growth"

    def test_mature_phase_month_19(self):
        assert _get_phase(19) == "mature"

    def test_mature_phase_month_36(self):
        assert _get_phase(36) == "mature"


class TestWeightedGeometricMean:
    def test_equal_weights_equal_values(self):
        values = {"a": 50.0, "b": 50.0, "c": 50.0}
        weights = {"a": 1/3, "b": 1/3, "c": 1/3}
        result = _weighted_geometric_mean(values, weights)
        assert abs(result - 50.0) < 0.01

    def test_single_dimension(self):
        values = {"a": 80.0}
        weights = {"a": 1.0}
        result = _weighted_geometric_mean(values, weights)
        assert abs(result - 80.0) < 0.01

    def test_zero_value_returns_zero(self):
        values = {"a": 0.0, "b": 50.0}
        weights = {"a": 0.5, "b": 0.5}
        result = _weighted_geometric_mean(values, weights)
        assert result == 0.0

    def test_empty_values_returns_zero(self):
        assert _weighted_geometric_mean({}, {}) == 0.0

    def test_unequal_weights(self):
        values = {"a": 100.0, "b": 25.0}
        weights = {"a": 0.75, "b": 0.25}
        # Weighted geometric mean: 100^0.75 * 25^0.25
        expected = (100.0 ** 0.75) * (25.0 ** 0.25)
        result = _weighted_geometric_mean(values, weights)
        assert abs(result - expected) < 0.01


class TestComputeHshsScore:
    def test_all_perfect_scores(self):
        dims = {k: 100.0 for k in DIMENSION_KEYS}
        result = compute_hshs_score(dims, months_active=3)
        assert result["overall"] == 100.0
        assert result["phase"] == "early"

    def test_all_fifty_scores(self):
        dims = {k: 50.0 for k in DIMENSION_KEYS}
        result = compute_hshs_score(dims, months_active=10)
        assert result["phase"] == "growth"
        # With equal weights (growth phase) and equal values,
        # geometric mean should be 50
        assert abs(result["overall"] - 50.0) < 0.01

    def test_zero_dimension_gives_zero_overall_geometric(self):
        dims = {k: 80.0 for k in DIMENSION_KEYS}
        dims["performance"] = 0.0
        result = compute_hshs_score(dims, months_active=3)
        assert result["overall_geometric"] == 0.0
        assert result["overall"] > 0.0

    def test_missing_dimension_gives_zero_overall_geometric(self):
        dims = {"performance": 80.0, "model_quality": 70.0}
        # Missing data_asset, flywheel_velocity, defensibility => default 0
        result = compute_hshs_score(dims, months_active=3)
        assert result["overall_geometric"] == 0.0
        assert result["overall"] > 0.0

    def test_early_phase_weights(self):
        result = compute_hshs_score({k: 50.0 for k in DIMENSION_KEYS}, months_active=3)
        assert result["weights"] == PHASE_WEIGHTS["early"]
        assert result["weights"]["data_asset"] == 0.35

    def test_growth_phase_weights(self):
        result = compute_hshs_score({k: 50.0 for k in DIMENSION_KEYS}, months_active=12)
        assert result["weights"] == PHASE_WEIGHTS["growth"]
        # All 0.20 in growth phase
        for w in result["weights"].values():
            assert w == 0.20

    def test_mature_phase_weights(self):
        result = compute_hshs_score({k: 50.0 for k in DIMENSION_KEYS}, months_active=24)
        assert result["weights"] == PHASE_WEIGHTS["mature"]
        assert result["weights"]["performance"] == 0.30
        assert result["weights"]["defensibility"] == 0.25

    def test_dimensions_clamped_to_100(self):
        dims = {k: 150.0 for k in DIMENSION_KEYS}
        result = compute_hshs_score(dims, months_active=3)
        for v in result["dimensions"].values():
            assert v <= 100.0

    def test_dimensions_clamped_to_zero(self):
        dims = {k: -10.0 for k in DIMENSION_KEYS}
        result = compute_hshs_score(dims, months_active=3)
        for v in result["dimensions"].values():
            assert v == 0.0
        assert result["overall"] == 0.0

    def test_return_structure(self):
        dims = {k: 60.0 for k in DIMENSION_KEYS}
        result = compute_hshs_score(dims, months_active=6)
        assert "overall" in result
        assert "dimensions" in result
        assert "weights" in result
        assert "phase" in result
        assert isinstance(result["overall"], float)
        assert isinstance(result["dimensions"], dict)
        assert isinstance(result["weights"], dict)
        assert isinstance(result["phase"], str)

    def test_weights_sum_to_one(self):
        for phase_name, weights in PHASE_WEIGHTS.items():
            total = sum(weights.values())
            assert abs(total - 1.0) < 1e-9, f"Phase {phase_name} weights sum to {total}"

    def test_asymmetric_scores_early_phase(self):
        """Early phase heavily weights data_asset."""
        dims_high_data = {k: 50.0 for k in DIMENSION_KEYS}
        dims_high_data["data_asset"] = 90.0

        dims_high_perf = {k: 50.0 for k in DIMENSION_KEYS}
        dims_high_perf["performance"] = 90.0

        result_data = compute_hshs_score(dims_high_data, months_active=3)
        result_perf = compute_hshs_score(dims_high_perf, months_active=3)

        # In early phase, data_asset weight (0.35) > performance weight (0.10),
        # so high data_asset should yield higher overall
        assert result_data["overall"] > result_perf["overall"]

    def test_default_months_active(self):
        dims = {k: 50.0 for k in DIMENSION_KEYS}
        result = compute_hshs_score(dims)
        assert result["phase"] == "early"


class TestWeightedArithmeticOverall:
    def test_spec_example_zero_flywheel(self):
        dims = {
            "performance": 79.0,
            "model_quality": 71.0,
            "data_asset": 74.0,
            "flywheel_velocity": 0.0,
            "defensibility": 73.0,
        }
        result = compute_hshs_score(dims, months_active=3)
        assert abs(result["overall"] - 58.85) < 0.01

    def test_all_positive_overall_is_weighted_average(self):
        dims = {k: 80.0 for k in DIMENSION_KEYS}
        result = compute_hshs_score(dims, months_active=3)
        assert abs(result["overall"] - 80.0) < 0.01

    def test_backward_compat_overall_geometric_zero_when_dim_zero(self):
        dims = {k: 80.0 for k in DIMENSION_KEYS}
        dims["performance"] = 0.0
        result = compute_hshs_score(dims, months_active=3)
        assert result["overall_geometric"] == 0.0

    def test_all_zeros_overall_is_zero(self):
        dims = {k: 0.0 for k in DIMENSION_KEYS}
        result = compute_hshs_score(dims, months_active=3)
        assert result["overall"] == 0.0

    def test_all_100_overall_is_100(self):
        dims = {k: 100.0 for k in DIMENSION_KEYS}
        result = compute_hshs_score(dims, months_active=3)
        assert result["overall"] == 100.0

    def test_missing_keys_default_zero_degrades_gracefully(self):
        dims = {"performance": 80.0, "model_quality": 70.0}
        result = compute_hshs_score(dims, months_active=3)
        assert result["overall"] < 80.0
        assert result["overall"] >= 0.0

    def test_overall_geometric_present_in_result(self):
        dims = {k: 60.0 for k in DIMENSION_KEYS}
        result = compute_hshs_score(dims, months_active=3)
        assert "overall_geometric" in result

    def test_overall_geometric_positive_when_all_positive(self):
        dims = {k: 60.0 for k in DIMENSION_KEYS}
        result = compute_hshs_score(dims, months_active=3)
        assert result["overall_geometric"] > 0.0
