"""Tests for src/evaluation/statistics.py"""

import math
import numpy as np
import pytest
from scipy import stats as sp_stats

from src.evaluation.statistics import (
    bootstrap_sharpe_ci,
    calmar_ratio,
    expectancy_test,
    max_drawdown,
    minimum_track_record_length,
    probabilistic_sharpe_ratio,
    profit_factor,
    sharpe_ratio,
    sharpe_standard_error,
    sortino_ratio,
    win_rate_test,
)


# ---------------------------------------------------------------------------
# sharpe_ratio
# ---------------------------------------------------------------------------

class TestSharpeRatio:
    def test_known_value(self):
        # mean=0.01, std well-defined
        returns = np.array([0.01, 0.02, -0.005, 0.015, 0.005])
        sr = sharpe_ratio(returns)
        expected = returns.mean() / returns.std()
        assert sr == pytest.approx(expected)

    def test_with_risk_free(self):
        returns = np.array([0.05, 0.06, 0.04, 0.05])
        rf = 0.01
        excess = returns - rf
        expected = excess.mean() / excess.std()
        assert sharpe_ratio(returns, risk_free=rf) == pytest.approx(expected)

    def test_constant_returns_zero_std(self):
        # All identical returns => std=0 => should return 0.0
        returns = np.array([1.0, 1.0, 1.0, 1.0])
        assert sharpe_ratio(returns) == 0.0

    def test_empty_array(self):
        returns = np.array([])
        assert sharpe_ratio(returns) == 0.0

    def test_single_element(self):
        # Single element => std=0
        returns = np.array([0.05])
        assert sharpe_ratio(returns) == 0.0

    def test_all_negative(self):
        returns = np.array([-0.01, -0.02, -0.03, -0.04])
        sr = sharpe_ratio(returns)
        assert sr < 0

    def test_all_positive(self):
        returns = np.array([0.01, 0.02, 0.03, 0.04])
        sr = sharpe_ratio(returns)
        assert sr > 0


# ---------------------------------------------------------------------------
# sharpe_standard_error
# ---------------------------------------------------------------------------

class TestSharpeStandardError:
    def test_normal_case(self):
        # With skew=0, kurtosis=3 (normal), SE = sqrt((1 + 0 + 0.5*sr^2) / (n-1))
        sr, n = 1.0, 100
        se = sharpe_standard_error(sr, n)
        expected = math.sqrt((1 - 0 * sr + (3 - 1) / 4 * sr**2) / (n - 1))
        assert se == pytest.approx(expected)

    def test_n_equals_one(self):
        assert sharpe_standard_error(1.0, 1) == float('inf')

    def test_n_zero(self):
        assert sharpe_standard_error(1.0, 0) == float('inf')

    def test_zero_sharpe(self):
        se = sharpe_standard_error(0.0, 100)
        expected = math.sqrt(1.0 / 99)
        assert se == pytest.approx(expected)

    def test_with_skew_kurtosis(self):
        sr, n, skew, kurt = 0.5, 50, -0.3, 4.0
        se = sharpe_standard_error(sr, n, skew, kurt)
        numer = 1 - skew * sr + (kurt - 1) / 4 * sr**2
        expected = math.sqrt(numer / (n - 1))
        assert se == pytest.approx(expected)


# ---------------------------------------------------------------------------
# probabilistic_sharpe_ratio
# ---------------------------------------------------------------------------

class TestProbabilisticSharpeRatio:
    def test_observed_above_benchmark(self):
        psr = probabilistic_sharpe_ratio(1.5, 0.0, 100)
        assert 0.5 < psr <= 1.0

    def test_observed_equals_benchmark(self):
        psr = probabilistic_sharpe_ratio(1.0, 1.0, 100)
        assert psr == pytest.approx(0.5, abs=0.05)

    def test_observed_below_benchmark(self):
        psr = probabilistic_sharpe_ratio(0.0, 1.0, 100)
        assert psr < 0.5

    def test_n_one_returns_half(self):
        # n=1 => se=inf => returns 0.5
        psr = probabilistic_sharpe_ratio(2.0, 0.0, 1)
        assert psr == 0.5


# ---------------------------------------------------------------------------
# minimum_track_record_length
# ---------------------------------------------------------------------------

class TestMinimumTrackRecordLength:
    def test_basic(self):
        mtrl = minimum_track_record_length(1.5, 0.0)
        assert isinstance(mtrl, int)
        assert mtrl > 1

    def test_equal_sr_benchmark(self):
        mtrl = minimum_track_record_length(1.0, 1.0)
        assert mtrl == 999999

    def test_higher_sr_needs_fewer_obs(self):
        mtrl_high = minimum_track_record_length(3.0, 0.0)
        mtrl_low = minimum_track_record_length(1.0, 0.0)
        assert mtrl_high < mtrl_low


# ---------------------------------------------------------------------------
# bootstrap_sharpe_ci
# ---------------------------------------------------------------------------

class TestBootstrapSharpeCi:
    def test_reproducibility_seed42(self):
        rng = np.random.default_rng(99)
        returns = rng.normal(0.01, 0.02, 200)
        lo1, obs1, hi1 = bootstrap_sharpe_ci(returns)
        lo2, obs2, hi2 = bootstrap_sharpe_ci(returns)
        # Same seed internally => identical results
        assert lo1 == lo2
        assert obs1 == obs2
        assert hi1 == hi2

    def test_ci_contains_observed(self):
        returns = np.random.default_rng(7).normal(0.01, 0.03, 100)
        lo, obs, hi = bootstrap_sharpe_ci(returns)
        assert lo <= obs <= hi

    def test_short_array_returns_zeros(self):
        returns = np.array([0.01, 0.02])
        lo, obs, hi = bootstrap_sharpe_ci(returns)
        assert lo == 0.0
        assert hi == 0.0

    def test_empty_array(self):
        lo, obs, hi = bootstrap_sharpe_ci(np.array([]))
        assert obs == 0.0


# ---------------------------------------------------------------------------
# win_rate_test
# ---------------------------------------------------------------------------

class TestWinRateTest:
    def test_high_win_rate(self):
        result = win_rate_test(90, 100)
        assert result["win_rate"] == pytest.approx(0.9)
        assert result["p_value"] < 0.05
        assert result["significant_at_05"] is True

    def test_fifty_fifty(self):
        result = win_rate_test(50, 100)
        assert result["win_rate"] == pytest.approx(0.5)
        assert result["p_value"] > 0.05

    def test_zero_total(self):
        result = win_rate_test(0, 0)
        assert result["win_rate"] == 0
        assert result["p_value"] == 1.0
        assert result["n"] == 0

    def test_custom_null_rate(self):
        result = win_rate_test(70, 100, null_rate=0.6)
        assert result["null_rate"] == 0.6


# ---------------------------------------------------------------------------
# expectancy_test
# ---------------------------------------------------------------------------

class TestExpectancyTest:
    def test_positive_pnl(self):
        pnl = np.array([10, 20, 15, 30, 25, 10, 5, 20, 15, 10])
        result = expectancy_test(pnl)
        assert result["mean_pnl"] > 0
        assert result["t_pvalue"] < 0.05
        assert result["significant_at_05"] == True
        assert result["n"] == 10

    def test_zero_pnl(self):
        pnl = np.array([1.0, -1.0, 1.0, -1.0, 1.0, -1.0])
        result = expectancy_test(pnl)
        assert result["mean_pnl"] == pytest.approx(0.0)

    def test_too_few_trades(self):
        pnl = np.array([10.0, 20.0])
        result = expectancy_test(pnl)
        assert result["mean_pnl"] == 0
        assert result["t_pvalue"] == 1.0
        assert result["n"] == 2

    def test_empty(self):
        result = expectancy_test(np.array([]))
        assert result["n"] == 0
        assert result["t_pvalue"] == 1.0


# ---------------------------------------------------------------------------
# profit_factor
# ---------------------------------------------------------------------------

class TestProfitFactor:
    def test_normal(self):
        assert profit_factor(300, 100) == pytest.approx(3.0)

    def test_negative_losses_input(self):
        # losses_total might be negative (gross loss); abs is taken
        assert profit_factor(200, -100) == pytest.approx(2.0)

    def test_zero_losses_positive_wins(self):
        assert profit_factor(100, 0) == float('inf')

    def test_zero_losses_zero_wins(self):
        assert profit_factor(0, 0) == 0.0

    def test_zero_wins_nonzero_losses(self):
        assert profit_factor(0, 100) == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# calmar_ratio
# ---------------------------------------------------------------------------

class TestCalmarRatio:
    def test_normal(self):
        assert calmar_ratio(0.20, 0.10) == pytest.approx(2.0)

    def test_zero_drawdown(self):
        assert calmar_ratio(0.15, 0.0) == 0.0

    def test_negative_return(self):
        cr = calmar_ratio(-0.10, 0.20)
        assert cr == pytest.approx(-0.5)

    def test_negative_drawdown_uses_abs(self):
        assert calmar_ratio(0.20, -0.10) == pytest.approx(2.0)


# ---------------------------------------------------------------------------
# sortino_ratio
# ---------------------------------------------------------------------------

class TestSortinoRatio:
    def test_mixed_returns(self):
        returns = np.array([0.05, -0.02, 0.03, -0.01, 0.04])
        sr = sortino_ratio(returns)
        excess = returns
        downside = excess[excess < 0]
        expected = excess.mean() / downside.std()
        assert sr == pytest.approx(expected)

    def test_all_positive_returns(self):
        # No downside => 0
        returns = np.array([0.01, 0.02, 0.03])
        assert sortino_ratio(returns) == 0.0

    def test_all_negative_returns(self):
        returns = np.array([-0.01, -0.02, -0.03, -0.04])
        sr = sortino_ratio(returns)
        assert sr < 0

    def test_empty_returns(self):
        assert sortino_ratio(np.array([])) == 0.0

    def test_with_risk_free(self):
        returns = np.array([0.05, 0.06, 0.02, 0.03])
        sr = sortino_ratio(returns, risk_free=0.04)
        excess = returns - 0.04
        downside = excess[excess < 0]
        expected = excess.mean() / downside.std()
        assert sr == pytest.approx(expected)


# ---------------------------------------------------------------------------
# max_drawdown
# ---------------------------------------------------------------------------

class TestMaxDrawdown:
    def test_v_shape(self):
        # Peak at 100, drop to 80, recover to 110
        curve = np.array([100, 95, 90, 80, 85, 95, 100, 110])
        dd, peak_idx, trough_idx = max_drawdown(curve)
        assert dd == pytest.approx(0.20)  # (100-80)/100
        assert peak_idx == 0
        assert trough_idx == 3

    def test_monotonic_up(self):
        curve = np.array([100, 110, 120, 130, 140])
        dd, peak_idx, trough_idx = max_drawdown(curve)
        assert dd == pytest.approx(0.0)

    def test_monotonic_down(self):
        curve = np.array([100, 80, 60, 40, 20])
        dd, peak_idx, trough_idx = max_drawdown(curve)
        assert dd == pytest.approx(0.80)  # (100-20)/100
        assert peak_idx == 0
        assert trough_idx == 4

    def test_empty_curve(self):
        dd, p, t = max_drawdown(np.array([]))
        assert dd == 0.0
        assert p == 0
        assert t == 0

    def test_single_element(self):
        dd, p, t = max_drawdown(np.array([100.0]))
        assert dd == 0.0

    def test_drawdown_after_new_high(self):
        # New high at 200, then drop to 150 => dd = 50/200 = 0.25
        # Old dd was 100->80 = 0.20, new dd is larger
        curve = np.array([100, 80, 100, 200, 150])
        dd, peak_idx, trough_idx = max_drawdown(curve)
        assert dd == pytest.approx(0.25)
        assert peak_idx == 3
        assert trough_idx == 4
