"""Tests for shadow trading metrics."""

import pytest
from src.shadow_trading.metrics import compute_shadow_metrics


def _make_trade(pnl, duration=5, mfe=None, mae=None, exit_reason="target_1_hit", earnings=False):
    return {
        "pnl_dollars": pnl,
        "duration_days": duration,
        "max_favorable_excursion": mfe if mfe is not None else max(pnl, 0),
        "max_adverse_excursion": mae if mae is not None else min(pnl, 0),
        "exit_reason": exit_reason,
        "earnings_adjacent": 1 if earnings else 0,
    }


def test_empty_trades():
    result = compute_shadow_metrics([])
    assert result["total_trades"] == 0
    assert result["win_rate"] == 0.0
    assert result["expectancy"] == 0.0


def test_all_wins():
    trades = [_make_trade(10), _make_trade(20), _make_trade(5)]
    result = compute_shadow_metrics(trades)
    assert result["total_trades"] == 3
    assert result["wins"] == 3
    assert result["losses"] == 0
    assert result["win_rate"] == 100.0
    assert result["avg_gain"] == pytest.approx(11.67, abs=0.01)
    assert result["avg_loss"] == 0.0
    assert result["total_pnl"] == 35.0
    assert result["expectancy"] == pytest.approx(11.67, abs=0.01)


def test_all_losses():
    trades = [_make_trade(-5), _make_trade(-10), _make_trade(-3)]
    result = compute_shadow_metrics(trades)
    assert result["total_trades"] == 3
    assert result["wins"] == 0
    assert result["losses"] == 3
    assert result["win_rate"] == 0.0
    assert result["avg_gain"] == 0.0
    assert result["avg_loss"] == pytest.approx(-6.0, abs=0.01)
    assert result["total_pnl"] == -18.0


def test_mixed_trades():
    trades = [
        _make_trade(10, duration=3, mfe=12, mae=-1),
        _make_trade(-5, duration=7, mfe=2, mae=-6, exit_reason="stop_hit"),
        _make_trade(15, duration=5, mfe=18, mae=-2),
        _make_trade(-3, duration=10, mfe=1, mae=-4, exit_reason="timeout"),
    ]
    result = compute_shadow_metrics(trades)
    assert result["total_trades"] == 4
    assert result["wins"] == 2
    assert result["losses"] == 2
    assert result["win_rate"] == 50.0
    assert result["total_pnl"] == 17.0
    assert result["expectancy"] == pytest.approx(4.25, abs=0.01)
    assert result["avg_duration_days"] == pytest.approx(6.25, abs=0.1)


def test_earnings_adjacent_breakdown():
    trades = [
        _make_trade(10, earnings=True),
        _make_trade(-5, earnings=True),
        _make_trade(20, earnings=False),
        _make_trade(-3, earnings=False),
    ]
    result = compute_shadow_metrics(trades)
    assert result["earnings_adjacent_trades"] == 2
    assert result["earnings_adjacent_pnl"] == 5.0
    assert result["normal_trades_pnl"] == 17.0


def test_max_drawdown():
    trades = [
        _make_trade(10),
        _make_trade(-15),
        _make_trade(-5),
        _make_trade(20),
    ]
    result = compute_shadow_metrics(trades)
    # Peak after first: 10. Then drops to -5 (drawdown of 15), then -10 (drawdown of 20), then 10 (recovered).
    assert result["max_drawdown"] == 20.0


def test_single_trade():
    result = compute_shadow_metrics([_make_trade(7.5)])
    assert result["total_trades"] == 1
    assert result["wins"] == 1
    assert result["win_rate"] == 100.0
    assert result["expectancy"] == 7.5


def test_expectancy_fallback_logs_warning_on_import_error(caplog):
    """#744 — bare except must log a WARNING when evaluation.metrics is unavailable."""
    import logging
    import sys

    saved = sys.modules.pop("src.evaluation.metrics", None)
    sys.modules["src.evaluation.metrics"] = None  # block the import

    try:
        import importlib
        import src.shadow_trading.metrics as _m
        importlib.reload(_m)

        with caplog.at_level(logging.WARNING, logger="src.shadow_trading.metrics"):
            result = _m.compute_shadow_metrics([_make_trade(10), _make_trade(-5)])

        assert result["expectancy"] is not None
        assert any("unavailable" in r.message or "expectancy" in r.message.lower()
                   for r in caplog.records
                   if r.levelno >= logging.WARNING), (
            "Expected a WARNING log when evaluation.metrics is unavailable"
        )
    finally:
        sys.modules.pop("src.evaluation.metrics", None)
        if saved is not None:
            sys.modules["src.evaluation.metrics"] = saved
        import importlib
        import src.shadow_trading.metrics as _m2
        importlib.reload(_m2)
