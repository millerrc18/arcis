"""Performance metrics with known-answer tests.

All metrics are pure functions on return series. Tests in
tests/test_metrics.py verify against hand-computed values.
"""

from __future__ import annotations

import math


def sharpe_ratio(returns: list[float], periods_per_year: int = 252) -> float:
    """Annualized Sharpe ratio (risk-free = 0).

    Uses sample standard deviation (ddof=1).
    """
    if len(returns) < 2:
        return 0.0
    n = len(returns)
    mean = sum(returns) / n
    var = sum((r - mean) ** 2 for r in returns) / (n - 1)
    if var <= 0:
        return 0.0
    return mean / math.sqrt(var) * math.sqrt(periods_per_year)


def max_drawdown(equity: list[float]) -> float:
    """Maximum drawdown as a positive fraction (e.g., 0.15 = 15%).

    Equity is a cumulative wealth series starting at 1.0 (or any base).
    """
    if len(equity) < 2:
        return 0.0
    peak = equity[0]
    max_dd = 0.0
    for value in equity[1:]:
        if value > peak:
            peak = value
        dd = (peak - value) / peak if peak > 0 else 0.0
        max_dd = max(max_dd, dd)
    return max_dd


def hit_rate(returns: list[float]) -> float:
    """Fraction of returns > 0."""
    if not returns:
        return 0.0
    wins = sum(1 for r in returns if r > 0)
    return wins / len(returns)


def profit_factor(returns: list[float]) -> float:
    """Sum of wins / abs(sum of losses). Inf if no losses."""
    gross_win = sum(r for r in returns if r > 0)
    gross_loss = abs(sum(r for r in returns if r < 0))
    if gross_loss == 0:
        return float("inf") if gross_win > 0 else 0.0
    return gross_win / gross_loss


def avg_win_avg_loss(returns: list[float]) -> tuple[float, float]:
    """(average win, average loss as positive value)."""
    wins = [r for r in returns if r > 0]
    losses = [r for r in returns if r < 0]
    avg_win = sum(wins) / len(wins) if wins else 0.0
    avg_loss = abs(sum(losses) / len(losses)) if losses else 0.0
    return (avg_win, avg_loss)
