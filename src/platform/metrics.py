"""Basic backtest metrics + survivorship haircut plumbing.

Called by: src.platform.backtest_engine, scripts.run_backtest.
Calls: numpy, math.
Owns tables: none.
Tests: tests/platform/test_metrics.py.

Survivorship haircut defaults per deep research (backtest-rigor-retrofit-plan):
  75 bps/yr for short-hold strategies (default)
  200 bps/yr for momentum strategies
  100 bps/yr for everything else
Applied to annualized total return before downstream Sharpe-family metrics.
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any

import numpy as np


def _std(values: list[float], ddof: int = 1) -> float:
    arr = np.asarray(values, dtype=float)
    if arr.size <= ddof:
        return 0.0
    return float(arr.std(ddof=ddof))


def compute_sharpe(
    returns: list[float], periods_per_year: int = 252
) -> float | None:
    """Annualized Sharpe from per-observation returns. None if vol is zero."""
    if not returns:
        return None
    arr = np.asarray(returns, dtype=float)
    s = _std(list(arr))
    if s == 0.0:
        return None
    return float(arr.mean() / s * math.sqrt(periods_per_year))


def compute_excess_sharpe(
    excess_returns: list[float], periods_per_year: int = 252
) -> float | None:
    return compute_sharpe(excess_returns, periods_per_year=periods_per_year)


def compute_sortino(
    returns: list[float], periods_per_year: int = 252
) -> float | None:
    if not returns:
        return None
    arr = np.asarray(returns, dtype=float)
    downside = arr[arr < 0]
    if downside.size == 0:
        return None
    d = float(downside.std(ddof=1)) if downside.size > 1 else 0.0
    if d == 0.0:
        return None
    return float(arr.mean() / d * math.sqrt(periods_per_year))


def compute_calmar(total_return: float, max_drawdown: float) -> float:
    if max_drawdown == 0.0:
        return float("inf")
    return float(total_return / max_drawdown)


def compute_max_drawdown(
    equity_curve: list[tuple[str, float]],
) -> tuple[float, str, str]:
    """Returns (max_dd_pct, peak_date, trough_date)."""
    if not equity_curve:
        return 0.0, "", ""
    peak_value = equity_curve[0][1]
    peak_date = equity_curve[0][0]
    best_peak_date = peak_date
    best_trough_date = peak_date
    max_dd = 0.0
    for date_, val in equity_curve:
        if val > peak_value:
            peak_value = val
            peak_date = date_
        dd = (peak_value - val) / peak_value if peak_value > 0 else 0.0
        if dd > max_dd:
            max_dd = dd
            best_peak_date = peak_date
            best_trough_date = date_
    return float(max_dd), best_peak_date, best_trough_date


def compute_profit_factor(trades: list[Any]) -> float | None:
    if not trades:
        return None
    wins = sum(t.pnl_dollars for t in trades if t.pnl_dollars > 0)
    losses = sum(-t.pnl_dollars for t in trades if t.pnl_dollars < 0)
    if losses == 0:
        return float("inf") if wins > 0 else None
    return float(wins / losses)


def _year_fraction(equity_curve: list[tuple[str, float]]) -> float:
    if len(equity_curve) < 2:
        return 1.0
    d0 = datetime.fromisoformat(equity_curve[0][0])
    d1 = datetime.fromisoformat(equity_curve[-1][0])
    days = (d1 - d0).days
    return max(days, 1) / 365.0


def compute_all_metrics(
    trades: list[Any],
    equity_curve: list[tuple[str, float]],
    survivorship_haircut_bps: int = 75,
) -> dict:
    """All metrics as a dict. Used by BacktestResult.metrics.

    Survivorship haircut is applied to annualized return before Sharpe /
    Sortino / Calmar. See module docstring for default guidance.
    """
    per_trade_pnl = [t.pnl_pct for t in trades]
    per_trade_excess = [t.excess_return for t in trades if t.excess_return is not None]
    start_val = equity_curve[0][1] if equity_curve else 0.0
    end_val = equity_curve[-1][1] if equity_curve else 0.0
    total_return = (end_val - start_val) / start_val if start_val > 0 else 0.0
    years = _year_fraction(equity_curve)
    annualized_return = (1 + total_return) ** (1 / years) - 1 if years > 0 else 0.0
    haircut = survivorship_haircut_bps / 10_000.0
    net_annualized = annualized_return - haircut

    # Sharpe family uses per-trade returns; haircut shifts the mean.
    per_trade_haircut = haircut / max(len(per_trade_pnl), 1)
    net_per_trade = [r - per_trade_haircut for r in per_trade_pnl]

    dd, peak_date, trough_date = compute_max_drawdown(equity_curve)

    return {
        "total_return_pct": total_return,
        "annualized_return_gross": annualized_return,
        "annualized_return_net": net_annualized,
        "survivorship_haircut_bps": survivorship_haircut_bps,
        "sharpe": compute_sharpe(net_per_trade),
        "excess_sharpe": compute_excess_sharpe(per_trade_excess) if per_trade_excess else None,
        "sortino": compute_sortino(net_per_trade),
        "calmar": compute_calmar(net_annualized, dd) if dd else None,
        "max_drawdown_pct": dd,
        "max_drawdown_peak_date": peak_date,
        "max_drawdown_trough_date": trough_date,
        "win_rate": sum(1 for t in trades if t.pnl_dollars > 0) / len(trades) if trades else 0.0,
        "profit_factor": compute_profit_factor(trades),
        "n_trades": len(trades),
    }
