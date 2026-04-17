"""Rolling walk-forward backtest wrapper.

Called by: src.platform.promotion (walk-forward gate).
Calls: src.platform.backtest_engine.run_backtest, datetime, dateutil.relativedelta.
Owns tables: none.
Config keys: none.
Tests: tests/platform/rigor/test_walkforward.py.

Authority: Pardo 2008, "The Evaluation and Optimization of Trading
Strategies". Uses annual train/test slide with overlapping training
windows and non-overlapping test windows. Output includes OOS
efficiency = OOS_SR / IS_SR — flagged as overfit if < 0.30.

Pure wrapper — calls run_backtest per fold, concatenates OOS trades.
No DB access.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from src.platform.backtest_engine import BacktestConfig, run_backtest
from src.platform.strategy_spec import StrategySpec

OVERFIT_THRESHOLD = 0.30


def _add_years(d: date, years: int) -> date:
    """Add whole years to a date, handling Feb 29 → Feb 28 on non-leap."""
    try:
        return d.replace(year=d.year + years)
    except ValueError:
        return d.replace(year=d.year + years, day=28)


def _iter_folds(
    start: date, end: date, train_years: int, test_years: int,
) -> list[dict]:
    """Generate (train_start, train_end, test_start, test_end) folds.
    Slides by test_years each step; train window is rolling (not anchored)."""
    folds = []
    test_start = _add_years(start, train_years)
    while True:
        train_start = _add_years(test_start, -train_years)
        train_end = test_start - timedelta(days=1)
        test_end = _add_years(test_start, test_years) - timedelta(days=1)
        if test_end > end:
            break
        folds.append({
            "train_start": train_start.isoformat(),
            "train_end": train_end.isoformat(),
            "test_start": test_start.isoformat(),
            "test_end": test_end.isoformat(),
        })
        test_start = _add_years(test_start, test_years)
    return folds


def run_walkforward(
    strategy_spec: StrategySpec,
    start_date: str,
    end_date: str,
    train_years: int = 3,
    test_years: int = 1,
) -> dict:
    """Rolling walk-forward per Pardo 2008. Train/test slide annually.

    Args:
        strategy_spec: loaded StrategySpec (from src.platform.strategy_spec).
        start_date, end_date: ISO yyyy-mm-dd range.
        train_years: in-sample window length (default 3).
        test_years: out-of-sample window length (default 1).

    Returns dict:
        folds: list of {train_start, train_end, test_start, test_end,
                        is_sharpe, oos_sharpe, n_oos_trades}.
        aggregate_oos_trades: concatenated list of BacktestTrade across
            all OOS windows.
        oos_equity_curve: concatenated OOS equity curve.
        oos_sharpe: aggregate Sharpe across concatenated OOS trades
            (fold-averaged — simple mean of per-fold OOS Sharpes).
        oos_efficiency: OOS_SR / IS_SR (fold-averaged). Flagged overfit
            if < OVERFIT_THRESHOLD (0.30).
        overfit_flag: True if oos_efficiency < OVERFIT_THRESHOLD.
    """
    start = date.fromisoformat(start_date)
    end = date.fromisoformat(end_date)
    fold_specs = _iter_folds(start, end, train_years, test_years)

    folds: list[dict] = []
    aggregate_oos_trades: list[Any] = []
    aggregate_oos_curve: list[tuple[str, float]] = []
    is_sharpes: list[float] = []
    oos_sharpes: list[float] = []

    for f in fold_specs:
        # Train (IS) — for mechanical strategies with no fitted params this
        # is a diagnostic backtest. Its Sharpe defines the IS baseline.
        train_cfg = BacktestConfig(
            strategy=strategy_spec,
            start_date=f["train_start"],
            end_date=f["train_end"],
        )
        train_result = run_backtest(train_cfg)
        is_sr = train_result.metrics.get("sharpe") or 0.0

        # Test (OOS)
        test_cfg = BacktestConfig(
            strategy=strategy_spec,
            start_date=f["test_start"],
            end_date=f["test_end"],
        )
        test_result = run_backtest(test_cfg)
        oos_sr = test_result.metrics.get("sharpe") or 0.0

        folds.append({
            **f,
            "is_sharpe": is_sr,
            "oos_sharpe": oos_sr,
            "n_oos_trades": len(test_result.trades),
        })
        aggregate_oos_trades.extend(test_result.trades)
        aggregate_oos_curve.extend(test_result.equity_curve)
        is_sharpes.append(is_sr)
        oos_sharpes.append(oos_sr)

    if is_sharpes and oos_sharpes:
        mean_is = sum(is_sharpes) / len(is_sharpes)
        mean_oos = sum(oos_sharpes) / len(oos_sharpes)
        efficiency = mean_oos / mean_is if mean_is != 0 else 0.0
    else:
        mean_oos = 0.0
        efficiency = 0.0

    return {
        "folds": folds,
        "aggregate_oos_trades": aggregate_oos_trades,
        "oos_equity_curve": aggregate_oos_curve,
        "oos_sharpe": mean_oos,
        "oos_efficiency": efficiency,
        "overfit_flag": efficiency < OVERFIT_THRESHOLD,
    }
