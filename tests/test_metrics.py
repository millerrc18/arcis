"""S05 T6: Known-answer tests for performance metrics."""

import math

from arcis.research import metrics


class TestSharpe:
    def test_zero_returns(self):
        assert metrics.sharpe_ratio([0.0, 0.0, 0.0]) == 0.0

    def test_constant_positive(self):
        # Zero variance -> 0 (avoid div by zero)
        assert metrics.sharpe_ratio([0.01, 0.01, 0.01]) == 0.0

    def test_known_value(self):
        # Returns: +1%, -0.5%, +1%, -0.5% (4 periods)
        # Mean = 0.0025, sample std = 0.00866, sharpe = 0.2887 * sqrt(252)
        returns = [0.01, -0.005, 0.01, -0.005]
        sr = metrics.sharpe_ratio(returns)
        mean = 0.0025
        var = sum((r - mean) ** 2 for r in returns) / 3
        expected = mean / math.sqrt(var) * math.sqrt(252)
        assert abs(sr - expected) < 0.01


class TestDrawdown:
    def test_no_drawdown(self):
        assert metrics.max_drawdown([1.0, 1.1, 1.2, 1.3]) == 0.0

    def test_simple_drawdown(self):
        # Peak 1.2, trough 1.0 -> 16.67% drawdown
        dd = metrics.max_drawdown([1.0, 1.2, 1.0, 1.1])
        assert abs(dd - 0.1667) < 0.001

    def test_multiple_drawdowns(self):
        # Largest: 1.5 -> 1.0 = 33.3%
        dd = metrics.max_drawdown([1.0, 1.5, 1.2, 1.0, 1.3])
        assert abs(dd - 0.3333) < 0.001


class TestHitRate:
    def test_all_wins(self):
        assert metrics.hit_rate([0.01, 0.02, 0.03]) == 1.0

    def test_all_losses(self):
        assert metrics.hit_rate([-0.01, -0.02]) == 0.0

    def test_mixed(self):
        assert metrics.hit_rate([0.01, -0.01, 0.02, -0.02]) == 0.5

    def test_zero_excluded(self):
        # Zero returns are not wins
        assert metrics.hit_rate([0.01, 0.0, -0.01]) == 1 / 3


class TestProfitFactor:
    def test_no_losses(self):
        assert metrics.profit_factor([0.01, 0.02]) == float("inf")

    def test_no_wins(self):
        assert metrics.profit_factor([-0.01, -0.02]) == 0.0

    def test_known_value(self):
        # Wins: 0.03, Losses: 0.01 -> PF = 3.0
        pf = metrics.profit_factor([0.03, -0.01, 0.02, -0.01])
        assert abs(pf - 2.5) < 0.01  # (0.05)/(0.02) = 2.5


class TestAvgWinLoss:
    def test_basic(self):
        avg_win, avg_loss = metrics.avg_win_avg_loss([0.02, 0.04, -0.01, -0.03])
        assert abs(avg_win - 0.03) < 0.001
        assert abs(avg_loss - 0.02) < 0.001

    def test_no_losses(self):
        avg_win, avg_loss = metrics.avg_win_avg_loss([0.02, 0.04])
        assert abs(avg_win - 0.03) < 0.001
        assert avg_loss == 0.0
