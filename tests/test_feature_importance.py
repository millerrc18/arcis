"""Tests for feature importance tracking."""

import pytest


class TestPearsonCorrelation:
    def test_perfect_positive_correlation(self):
        from src.evaluation.feature_importance import _pearson_correlation
        x = [1, 2, 3, 4, 5]
        y = [2, 4, 6, 8, 10]
        corr = _pearson_correlation(x, y)
        assert abs(corr - 1.0) < 0.001

    def test_perfect_negative_correlation(self):
        from src.evaluation.feature_importance import _pearson_correlation
        x = [1, 2, 3, 4, 5]
        y = [10, 8, 6, 4, 2]
        corr = _pearson_correlation(x, y)
        assert abs(corr - (-1.0)) < 0.001

    def test_no_correlation(self):
        from src.evaluation.feature_importance import _pearson_correlation
        x = [1, 2, 3, 4, 5]
        y = [3, 1, 4, 1, 5]  # Random-ish
        corr = _pearson_correlation(x, y)
        assert abs(corr) < 0.5  # Should be weak

    def test_insufficient_data(self):
        from src.evaluation.feature_importance import _pearson_correlation
        assert _pearson_correlation([1], [2]) == 0.0
        assert _pearson_correlation([], []) == 0.0


class TestPredictivePowerClassification:
    def test_strong_correlation(self):
        # Correlation > 0.3 = strong
        from src.evaluation.feature_importance import _pearson_correlation
        x = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
        y = [1.1, 2.2, 2.8, 4.1, 5.0, 5.9, 7.1, 8.0, 8.9, 10.1]
        corr = abs(_pearson_correlation(x, y))
        assert corr > 0.3

    def test_weak_correlation(self):
        from src.evaluation.feature_importance import _pearson_correlation
        x = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
        y = [5, 3, 7, 2, 8, 4, 6, 1, 9, 5]
        corr = abs(_pearson_correlation(x, y))
        assert corr < 0.3


class TestOptimalRangeDetection:
    def test_finds_range(self):
        from src.evaluation.feature_importance import _find_optimal_range
        values = [-10, -8, -7, -6, -5, -4, -3, -2, -1, 0]
        wins = [0, 0, 1, 1, 1, 1, 1, 0, 0, 0]
        result = _find_optimal_range(values, wins)
        assert result is not None
        assert "min" in result
        assert "max" in result

    def test_insufficient_data(self):
        from src.evaluation.feature_importance import _find_optimal_range
        result = _find_optimal_range([1, 2], [1, 0])
        assert result is None
