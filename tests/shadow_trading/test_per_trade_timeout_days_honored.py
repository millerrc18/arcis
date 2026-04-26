"""Sprint 0 / Wave 2b — exit-monitor must honor the per-trade timeout_days field.

Track 1.5 / B8 stamped each trade row with `timeout_days` carrying the LLM's
Expected Holding Period (executor.py line 1126). Before this fix, the exit
loop's timeout comparison (formerly executor.py line ~1865) compared against
the *config global* timeout_days only — the per-trade value was dead data.

Post-fix: trade.get('timeout_days') overrides config when > 0; otherwise
falls back to the config global. Verify both behaviors by driving
check_and_manage_open_trades through a mocked open-trade collection.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

from zoneinfo import ZoneInfo


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

ET = ZoneInfo("America/New_York")


def _open_trade(*, days_old: int, timeout_days):
    """Build a minimal open trade row whose entry was `days_old` days ago.

    `timeout_days` is the per-trade override (None to simulate pre-B8 rows).
    """
    entry_ts = (datetime.now(ET) - timedelta(days=days_old)).isoformat()
    trade = {
        "trade_id": f"tid-{days_old}d-to-{timeout_days}",
        "ticker": "AAPL",
        "status": "open",
        "alpaca_order_id": "order-abc",
        "actual_entry_price": 100.0,
        "entry_price": 100.0,
        "stop_price": 95.0,
        "target_1": 110.0,
        "target_2": 120.0,
        "planned_shares": 5,
        "actual_entry_time": entry_ts,
        "created_at": entry_ts,
        "exit_retry_count": 0,
    }
    if timeout_days is not None:
        trade["timeout_days"] = timeout_days
    return trade


def _captures_timeout_exit(mock_update, mock_close=None) -> bool:
    """Inspect update_shadow_trade and close_shadow_trade calls for timeout exit_reason."""
    for call in mock_update.call_args_list:
        if len(call.args) >= 2 and isinstance(call.args[1], dict):
            er = call.args[1].get("exit_reason")
            if er == "timeout":
                return True
    if mock_close is not None:
        for call in mock_close.call_args_list:
            er = call.kwargs.get("exit_reason")
            if er is None and len(call.args) >= 4:
                er = call.args[3]
            if er == "timeout":
                return True
    return False


def _captures_any_exit(mock_update, mock_close=None) -> bool:
    for call in mock_update.call_args_list:
        if len(call.args) >= 2 and isinstance(call.args[1], dict):
            if call.args[1].get("exit_reason") is not None:
                return True
    if mock_close is not None and mock_close.call_args_list:
        # close_shadow_trade is the terminal exit path; any call counts as an exit
        return True
    return False


# ---------------------------------------------------------------------------
# Per-trade override (the headline regression)
# ---------------------------------------------------------------------------

def test_exit_timeout_uses_per_trade_value_when_present():
    """Trade with timeout_days=3 must time out after 4 days even with config=30.

    Pre-fix: executor compared days_open against config global (30 days), so
    the trade did NOT time out at 4 days. Post-fix: per-trade timeout_days=3
    is honored, the timeout fires.
    """
    from src.shadow_trading import executor

    trade = _open_trade(days_old=4, timeout_days=3)

    with (
        patch.object(executor, "get_open_shadow_trades", return_value=[trade]),
        patch.object(executor, "_get_current_price_safe", return_value=100.0),  # no stop/target hit
        patch.object(executor, "update_shadow_trade") as mock_update,
        patch.object(executor, "close_shadow_trade") as mock_close,
        patch.object(executor, "load_config", return_value={"shadow_trading": {"timeout_days": 30}}),
        patch.object(executor, "_submit_exit_order", return_value={"status": "filled", "filled_avg_price": 100.0}),
        patch("src.shadow_trading.alpaca_adapter.get_all_positions",
              return_value=[{"symbol": trade["ticker"], "qty": trade["planned_shares"]}]),
    ):
        executor.check_and_manage_open_trades(db_path=":memory:")

    assert _captures_timeout_exit(mock_update, mock_close), (
        "Expected timeout exit at days_open=4 with per-trade timeout_days=3 "
        "(config global is 30, but per-trade override should win)."
    )


def test_exit_timeout_falls_back_to_config_when_per_trade_missing():
    """Trade with timeout_days=None must use config global.

    Pre-B8 rows have no per-trade timeout_days. With config=10 and days_old=12,
    the timeout must still fire via config-global fallback.
    """
    from src.shadow_trading import executor

    trade = _open_trade(days_old=12, timeout_days=None)

    with (
        patch.object(executor, "get_open_shadow_trades", return_value=[trade]),
        patch.object(executor, "_get_current_price_safe", return_value=100.0),  # no stop/target hit
        patch.object(executor, "update_shadow_trade") as mock_update,
        patch.object(executor, "close_shadow_trade") as mock_close,
        patch.object(executor, "load_config", return_value={"shadow_trading": {"timeout_days": 10}}),
        patch.object(executor, "_submit_exit_order", return_value={"status": "filled", "filled_avg_price": 100.0}),
        patch("src.shadow_trading.alpaca_adapter.get_all_positions",
              return_value=[{"symbol": trade["ticker"], "qty": trade["planned_shares"]}]),
    ):
        executor.check_and_manage_open_trades(db_path=":memory:")

    assert _captures_timeout_exit(mock_update, mock_close), (
        "Expected timeout exit at days_old=12 via config fallback (config=10) "
        "when per-trade timeout_days is None."
    )


def test_exit_timeout_does_not_fire_within_per_trade_window():
    """Trade with timeout_days=30 must NOT time out at days_old=4 even if config=3.

    Confirms the per-trade value extends as well as shortens — the comparison
    is genuinely against the per-trade override, not just a min().
    """
    from src.shadow_trading import executor

    trade = _open_trade(days_old=4, timeout_days=30)

    with (
        patch.object(executor, "get_open_shadow_trades", return_value=[trade]),
        patch.object(executor, "_get_current_price_safe", return_value=100.0),  # no stop/target hit
        patch.object(executor, "update_shadow_trade") as mock_update,
        patch.object(executor, "close_shadow_trade") as mock_close,
        patch.object(executor, "load_config", return_value={"shadow_trading": {"timeout_days": 3}}),
        patch.object(executor, "_submit_exit_order", return_value={"status": "filled", "filled_avg_price": 100.0}),
        patch("src.shadow_trading.alpaca_adapter.get_all_positions",
              return_value=[{"symbol": trade["ticker"], "qty": trade["planned_shares"]}]),
    ):
        executor.check_and_manage_open_trades(db_path=":memory:")

    # Note: only the MFE/MAE update should have fired, no exit_reason write
    assert not _captures_any_exit(mock_update, mock_close), (
        "Did not expect any exit at days_old=4 when per-trade timeout_days=30 "
        "(config=3 should not override)."
    )
