"""Regression-lock tests for the walk-forward end-to-end pipeline (T11).

Four deterministic hermetic tests pin the three outcome states and the
pooled-Sharpe determinism invariant. No DB access, no network, no corpus FS.
"""
from __future__ import annotations
import random
from tests.platform.rigor.test_walkforward_runner import FakeTrade, _generate_trades, _minimal_spec
from src.platform.rigor.walkforward_config import DEFAULT_WINDOWS, WalkForwardConfig
from src.platform.rigor.walkforward_runner import run_walkforward

_SPEC = _minimal_spec(None)
_PASS_CFG = WalkForwardConfig(strategy_id="lock_pass", mde_max=100.0, pooled_sharpe_min=0.1, min_window_duration_days=0)


def _pass_window_trades():
    wt = {}
    for i, w in enumerate(DEFAULT_WINDOWS):
        wt[i] = {"is": [], "oos": _generate_trades(w.test_start, w.test_end, n=15, sharpe_target=3.0, seed=i + 20, vix=12.0 if i % 2 == 0 else 28.0)}
    return wt


def test_regression_lock_pass_outcome():
    random.seed(42)
    result = run_walkforward(strategy_spec_raw=_SPEC, config=_PASS_CFG, window_trades=_pass_window_trades())
    assert result.outcome.outcome_state == "PASS"


def test_regression_lock_fail_outcome():
    random.seed(42)
    cfg = WalkForwardConfig(strategy_id="lock_fail", mde_max=100.0, min_window_duration_days=0)
    _FAIL = [("2019-06-15", "2019-06-20"), ("2020-09-15", "2020-09-20")]
    wt = {}
    for i, w in enumerate(DEFAULT_WINDOWS):
        if i < 2:
            ed, xd = _FAIL[i]
            wt[i] = {"is": [], "oos": [FakeTrade(trade_id=f"x{i}_{j}", ticker="AAPL", entry_date=ed, exit_date=xd, entry_price=100.0, exit_price=50.0, pnl_pct=-0.5, vix_at_entry=15.0) for j in range(15)]}
        else:
            wt[i] = {"is": [], "oos": _generate_trades(w.test_start, w.test_end, n=15, sharpe_target=3.0, seed=i + 20, vix=10.0 if i % 2 == 0 else 30.0)}
    result = run_walkforward(strategy_spec_raw=_SPEC, config=cfg, window_trades=wt)
    assert result.outcome.outcome_state == "FAIL"


def test_regression_lock_inconclusive_outcome():
    random.seed(42)
    cfg = WalkForwardConfig(strategy_id="lock_incon", min_window_duration_days=0)
    wt = {}
    for i, w in enumerate(DEFAULT_WINDOWS):
        wt[i] = {"is": [], "oos": _generate_trades(w.test_start, w.test_end, n=6 if i < 2 else 15, sharpe_target=1.0, seed=i + 7)}
    result = run_walkforward(strategy_spec_raw=_SPEC, config=cfg, window_trades=wt)
    assert result.outcome.outcome_state == "INCONCLUSIVE"


def test_regression_lock_pooled_sharpe_stable():
    random.seed(42)
    wt = _pass_window_trades()
    r1 = run_walkforward(strategy_spec_raw=_SPEC, config=_PASS_CFG, window_trades=wt)
    random.seed(42)
    r2 = run_walkforward(strategy_spec_raw=_SPEC, config=_PASS_CFG, window_trades=wt)
    assert abs(r1.pooled_sharpe - r2.pooled_sharpe) < 0.01
