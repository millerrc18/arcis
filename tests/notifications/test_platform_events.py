"""Tests for src.notifications.platform_events."""
from unittest.mock import patch

from src.notifications.platform_events import (
    _DEDUP_CACHE,
    notify_backtest_complete,
    notify_shadow_gate_ready,
    notify_strategy_demoted,
    notify_strategy_promoted,
)


def _clear_dedup():
    _DEDUP_CACHE.clear()


def test_backtest_complete_prefixed_with_RESEARCH():
    _clear_dedup()
    with patch("src.notifications.telegram.send_telegram") as mock_send:
        notify_backtest_complete("strat_a", "r1234567890", True)
    assert mock_send.called
    msg = mock_send.call_args.args[0]
    assert "[RESEARCH]" in msg
    assert "strat_a" in msg


def test_gate_ready_deduplicated_within_24h():
    """Two calls with same strategy_id -> only one send."""
    _clear_dedup()
    with patch("src.notifications.telegram.send_telegram") as mock_send:
        notify_shadow_gate_ready(
            "strat_b",
            {"dsr": 0.96, "pbo": 0.3, "oos_efficiency": 0.5},
        )
        notify_shadow_gate_ready(
            "strat_b",
            {"dsr": 0.96, "pbo": 0.3, "oos_efficiency": 0.5},
        )
    assert mock_send.call_count == 1


def test_gate_ready_not_deduplicated_across_strategies():
    _clear_dedup()
    with patch("src.notifications.telegram.send_telegram") as mock_send:
        notify_shadow_gate_ready("a", {"dsr": 0.96, "pbo": 0.3, "oos_efficiency": 0.5})
        notify_shadow_gate_ready("b", {"dsr": 0.96, "pbo": 0.3, "oos_efficiency": 0.5})
    assert mock_send.call_count == 2


def test_gate_ready_handles_partial_evidence():
    """If some evidence fields are None, the message still sends
    with only the available fields shown (no crash)."""
    _clear_dedup()
    with patch("src.notifications.telegram.send_telegram") as mock_send:
        notify_shadow_gate_ready(
            "strat_c",
            {"dsr": 0.96, "pbo": None, "oos_efficiency": None},
        )
    assert mock_send.called
    msg = mock_send.call_args.args[0]
    assert "DSR=0.960" in msg
    # PBO and OOS_eff fields absent -- not crashed
    assert "None" not in msg  # don't render literal 'None'


def test_strategy_promoted_includes_state_transition():
    _clear_dedup()
    with patch("src.notifications.telegram.send_telegram") as mock_send:
        notify_strategy_promoted("s", "backtested", "shadow_trading")
    msg = mock_send.call_args.args[0]
    assert "backtested" in msg
    assert "shadow_trading" in msg


def test_strategy_demoted_includes_reason():
    _clear_dedup()
    with patch("src.notifications.telegram.send_telegram") as mock_send:
        notify_strategy_demoted("s", "drawdown breach exceeded 8% threshold")
    msg = mock_send.call_args.args[0]
    assert "drawdown" in msg.lower()


def test_notify_failure_does_not_raise():
    """Telegram send failures must be logged, not propagated."""
    _clear_dedup()
    with patch(
        "src.notifications.telegram.send_telegram",
        side_effect=RuntimeError("network down"),
    ):
        # Must NOT raise
        notify_strategy_promoted("x", None, "proposed")
