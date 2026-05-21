"""v0.36.46 — max_drawdown_pct must be % of CAPITAL, not % of peak cumulative P&L,
and the drawdown curve must exclude synthetic/orphan closes.

Pre-fix, cto_report._compute_trade_summary divided peak-to-trough dollars by the
peak *cumulative P&L* (a tiny, volatile denominator) and included synthetic
closes (reconciled_stale etc.). On 2026-05-21 that produced a 112% "drawdown"
that tripped a CRITICAL audit false-positive while the real drawdown was ~1% of
the $100k capital.
"""

from unittest.mock import patch

from src.evaluation.cto_report import _compute_trade_summary


def _t(pnl, reason="stop_loss"):
    return {"pnl_dollars": pnl, "pnl_pct": 0.0, "exit_reason": reason}


@patch("src.config.load_config", return_value={"risk": {"starting_capital": 100000}})
def test_drawdown_is_pct_of_capital_not_peak(_cfg):
    # cumulative: +100 then -300 → peak=100, trough=-200, max drawdown = $300
    closed = [_t(100), _t(-300)]
    s = _compute_trade_summary(closed, [], closed)
    assert s["max_drawdown_dollars"] == 300.0
    # $300 / $100k capital = 0.3% — NOT 300% (the old peak-relative denominator)
    assert s["max_drawdown_pct"] == 0.3


@patch("src.config.load_config", return_value={"risk": {"starting_capital": 100000}})
def test_synthetic_closes_excluded_from_drawdown_curve(_cfg):
    # the -$5000 reconciled_stale (synthetic bookkeeping close) must NOT inflate
    # the drawdown — only real strategy exits count toward the equity curve.
    closed = [_t(100, "target_1"), _t(-5000, "reconciled_stale"), _t(-100, "stop_loss")]
    s = _compute_trade_summary(closed, [], closed)
    # real curve: +100 then 0 → max drawdown = $100 (not $5100)
    assert s["max_drawdown_dollars"] == 100.0
    assert s["max_drawdown_pct"] == 0.1


@patch("src.config.load_config", return_value={"risk": {"starting_capital": 100000}})
def test_no_drawdown_when_monotonic_gains(_cfg):
    closed = [_t(50, "target_1"), _t(75, "target_1")]
    s = _compute_trade_summary(closed, [], closed)
    assert s["max_drawdown_dollars"] == 0.0
    assert s["max_drawdown_pct"] == 0.0


@patch("src.config.load_config", return_value={"risk": {"starting_capital": 100000}})
def test_real_drawdown_well_under_audit_ceiling(_cfg):
    # Reproduce the shape of the 2026-05-21 book: a real ~$1.3k peak-to-trough on
    # $100k capital is ~1.3%, far under the 25% deterministic audit ceiling — even
    # though the same curve is >100% when measured against peak cumulative P&L.
    closed = [_t(500, "target_1"), _t(-1300, "stop_loss"), _t(700, "target_1")]
    s = _compute_trade_summary(closed, [], closed)
    assert s["max_drawdown_pct"] < 25.0
    assert s["max_drawdown_dollars"] == 1300.0
