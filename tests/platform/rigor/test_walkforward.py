"""Tests for src.platform.rigor.walkforward — rolling walk-forward.

Non-negotiable quality gates for Sprint 2:
  - test_walkforward_oos_efficiency_computed — IS SR 2.0 + OOS SR 1.0
    returns efficiency = 0.5 (± 0.05)
  - test_walkforward_oos_efficiency_flags_overfit — IS SR 3.0 + OOS SR
    0.5 returns efficiency = 0.167 and flags as overfit (threshold 0.3)
"""
from dataclasses import dataclass, field
from unittest.mock import patch

import pytest

from src.platform.backtest_engine import BacktestResult, BacktestConfig, BacktestTrade
from src.platform.rigor.walkforward import (
    OVERFIT_THRESHOLD,
    run_walkforward,
)
from src.platform.strategy_spec import StrategySpec


def _spec() -> StrategySpec:
    return StrategySpec(
        strategy_id="wf_test",
        display_name="WF Test",
        universe={"tickers": ["AAPL"]},
        entry={"kind": "scheduled", "day_of_week": "Monday", "time": "close"},
        exit={"kind": "mechanical", "timeout_days": 5,
              "stop": {"method": "pct", "value": 0.02},
              "target": {"method": "pct", "value": 0.03}},
        position_sizing={"method": "fixed_pct_equity", "pct": 0.15,
                         "max_concurrent": 1},
        attribution={"benchmark": "SPY_matched_window",
                     "metrics": ["sharpe"]},
        raw={},
        source="test",
    )


def _fake_result(sharpe_val: float, n_trades: int = 10) -> BacktestResult:
    """Fabricate a BacktestResult where metrics['sharpe']=sharpe_val."""
    trades = [
        BacktestTrade(
            trade_id=f"t{i}", ticker="AAPL",
            entry_date="2023-01-01", exit_date="2023-01-06",
            entry_price=100.0, exit_price=101.0, shares=10,
            pnl_dollars=10.0, pnl_pct=0.01,
            exit_reason="target", hold_days=5,
            spy_return_over_hold=0.005, excess_return=0.005,
            realized_sector=None, regime_at_entry=None,
        )
        for i in range(n_trades)
    ]
    curve = [("2023-01-01", 100_000.0), ("2023-12-31", 110_000.0)]
    return BacktestResult(
        strategy_id="wf_test",
        config=BacktestConfig(
            strategy=_spec(), start_date="2023-01-01", end_date="2023-12-31",
        ),
        trades=trades,
        equity_curve=curve,
        metrics={
            "sharpe": sharpe_val, "n_trades": n_trades,
            "total_return_pct": 0.1, "max_drawdown_pct": 0.05,
            "excess_sharpe": sharpe_val - 0.1,
        },
        reproducibility={"spec_hash": "x", "started_at": "x"},
    )


def test_walkforward_oos_efficiency_computed():
    """IS SR 2.0, OOS SR 1.0 → efficiency = 0.5 (± 0.05)."""
    # Alternating IS/OOS calls — patch run_backtest to return fakes
    call_count = {"n": 0}

    def fake_run(cfg):
        # Alternate: odd calls are IS (train window), even are OOS (test window)
        call_count["n"] += 1
        return _fake_result(sharpe_val=2.0 if call_count["n"] % 2 == 1 else 1.0)

    with patch("src.platform.rigor.walkforward.run_backtest", side_effect=fake_run):
        result = run_walkforward(
            _spec(), start_date="2018-01-01", end_date="2023-12-31",
            train_years=3, test_years=1,
        )
    assert "oos_efficiency" in result
    assert 0.45 < result["oos_efficiency"] < 0.55, \
        f"expected efficiency ≈ 0.5, got {result['oos_efficiency']}"


def test_walkforward_oos_efficiency_flags_overfit():
    """IS SR 3.0, OOS SR 0.5 → efficiency = 0.167, flagged as overfit."""
    call_count = {"n": 0}

    def fake_run(cfg):
        call_count["n"] += 1
        return _fake_result(sharpe_val=3.0 if call_count["n"] % 2 == 1 else 0.5)

    with patch("src.platform.rigor.walkforward.run_backtest", side_effect=fake_run):
        result = run_walkforward(
            _spec(), start_date="2018-01-01", end_date="2023-12-31",
            train_years=3, test_years=1,
        )
    assert 0.15 < result["oos_efficiency"] < 0.20, \
        f"expected efficiency ≈ 0.167, got {result['oos_efficiency']}"
    assert result["oos_efficiency"] < OVERFIT_THRESHOLD
    assert result["overfit_flag"] is True


def test_walkforward_stable_strategy_does_not_flag_overfit():
    """Consistent performer: IS=1.0, OOS=0.9 → efficiency=0.9, NOT overfit."""
    call_count = {"n": 0}

    def fake_run(cfg):
        call_count["n"] += 1
        return _fake_result(sharpe_val=1.0 if call_count["n"] % 2 == 1 else 0.9)

    with patch("src.platform.rigor.walkforward.run_backtest", side_effect=fake_run):
        result = run_walkforward(
            _spec(), start_date="2018-01-01", end_date="2023-12-31",
            train_years=3, test_years=1,
        )
    assert result["oos_efficiency"] > OVERFIT_THRESHOLD
    assert result["overfit_flag"] is False


def test_walkforward_concatenated_trades_correct_count():
    """With 6-year range, 3y train / 1y test, non-overlapping test
    windows, expect 3 folds and trades concatenated from all 3 OOS tests
    (each fake returns n_trades=10)."""
    call_count = {"n": 0}

    def fake_run(cfg):
        call_count["n"] += 1
        # Alternate IS / OOS; OOS is even
        return _fake_result(sharpe_val=1.5 if call_count["n"] % 2 else 1.0,
                            n_trades=10)

    with patch("src.platform.rigor.walkforward.run_backtest", side_effect=fake_run):
        result = run_walkforward(
            _spec(), start_date="2017-01-01", end_date="2023-12-31",
            train_years=3, test_years=1,
        )
    # 7 years → rolling 3y train + 1y test, step 1y → folds at
    # 2017-2020 train / 2020 test, 2018-2021/2021 test,
    # 2019-2022/2022 test, 2020-2023/2023 test → 4 folds
    assert len(result["folds"]) >= 3
    # Each fold produces 10 OOS trades
    assert len(result["aggregate_oos_trades"]) == len(result["folds"]) * 10


def test_walkforward_returns_required_fields():
    """Output dict must include folds, oos_efficiency, oos_sharpe,
    overfit_flag, aggregate_oos_trades."""
    def fake_run(cfg):
        return _fake_result(sharpe_val=1.0, n_trades=5)

    with patch("src.platform.rigor.walkforward.run_backtest", side_effect=fake_run):
        result = run_walkforward(
            _spec(), start_date="2019-01-01", end_date="2023-12-31",
            train_years=3, test_years=1,
        )
    for key in ("folds", "oos_efficiency", "oos_sharpe", "overfit_flag",
                "aggregate_oos_trades"):
        assert key in result, f"missing key: {key}"
