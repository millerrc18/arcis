"""Sprint 0 / Wave 2b — exit_reason writes in executor.py must yield in-vocab values.

Three regression sites in src/shadow_trading/executor.py:
  - line 1884 (entry_unfilled) — was f"entry_unfilled_{exit_reason}" (out of vocab)
  - line 2014 (broker_exception) — was coerce(f"broker_exception:{type(e).__name__}")
                                   which always coerced to 'unknown' losing the broker signal
  - line 2069 (partial_exit) — was f"partial_{exit_reason}" (out of vocab)

After the fix, all three must persist values that are in CONTROLLED_VOCAB.

Strategy:
  - Mock the open-trade collection, the broker calls, the price source, and the DB
    write. Then drive check_and_manage_open_trades() through each branch and inspect
    the dict that update_shadow_trade was called with.

Pre-fix verification: stash the executor.py / exit_reason.py / models.py edits and
re-run — the three vocabulary tests below FAIL (exit_reason values land outside
CONTROLLED_VOCAB).
"""
from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

from zoneinfo import ZoneInfo

import pytest

from src.shadow_trading.exit_reason import CONTROLLED_VOCAB

ET = ZoneInfo("America/New_York")


def _isoformat_days_ago(days: int) -> str:
    """Return an ET-aware ISO timestamp `days` days ago (parses cleanly via fromisoformat)."""
    return (datetime.now(ET) - timedelta(days=days)).isoformat()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _capture_exit_reason_writes(mock_update):
    """Return a list of exit_reason values written across all update_shadow_trade calls."""
    values = []
    for call in mock_update.call_args_list:
        # signature: update_shadow_trade(trade_id, fields_dict, db_path)
        if len(call.args) >= 2 and isinstance(call.args[1], dict):
            er = call.args[1].get("exit_reason")
            if er is not None:
                values.append(er)
    return values


# ---------------------------------------------------------------------------
# Bug 1a — entry_unfilled (line 1884)
# ---------------------------------------------------------------------------

def test_entry_unfilled_exit_reason_is_in_vocabulary():
    """When entry never filled and exit fires, persisted exit_reason must be in vocab.

    Pre-fix this wrote f"entry_unfilled_target_1" (etc.) — out of vocab.
    Post-fix it writes "entry_unfilled" (now a first-class vocab entry).
    """
    from src.shadow_trading import executor

    entry_ts = _isoformat_days_ago(1)
    pending_entry_trade = {
        "trade_id": "tid-pending",
        "ticker": "AAPL",
        "status": "pending_entry",
        "alpaca_order_id": "order-abc",
        "actual_entry_price": 0.0,  # never filled
        "entry_price": 100.0,
        "stop_price": 95.0,
        "target_1": 110.0,
        "target_2": 120.0,
        "planned_shares": 10,
        "actual_entry_time": entry_ts,
        "created_at": entry_ts,
        "timeout_days": 15,
    }

    with (
        patch.object(executor, "get_open_shadow_trades", return_value=[pending_entry_trade]),
        patch.object(executor, "_get_current_price_safe", return_value=111.0),  # above target_1 → exit triggers
        patch.object(executor, "update_shadow_trade") as mock_update,
        patch("src.shadow_trading.alpaca_adapter.cancel_paper_order"),
        patch.object(executor, "load_config", return_value={"shadow_trading": {"timeout_days": 15}}),
        # Pending-entry path is intercepted before _sync_exit_qty so positions don't matter,
        # but populating defensively in case the position-existence check at line ~1848 fires.
        patch("src.shadow_trading.alpaca_adapter.get_all_positions",
              return_value=[{"symbol": "AAPL", "qty": 10}]),
    ):
        executor.check_and_manage_open_trades(db_path=":memory:")

    written = _capture_exit_reason_writes(mock_update)
    assert written, "expected at least one exit_reason write"
    # Find the cancellation write specifically (status=cancelled path)
    cancellation_writes = [
        c.args[1].get("exit_reason")
        for c in mock_update.call_args_list
        if len(c.args) >= 2
        and isinstance(c.args[1], dict)
        and c.args[1].get("status") == "cancelled"
    ]
    assert cancellation_writes, "expected at least one cancellation write (status='cancelled')"
    for er in cancellation_writes:
        assert er in CONTROLLED_VOCAB, (
            f"entry-unfilled exit_reason {er!r} not in CONTROLLED_VOCAB"
        )
    # Specifically the post-fix token
    assert "entry_unfilled" in cancellation_writes


# ---------------------------------------------------------------------------
# Bug 1b — broker_exception (line 2014)
# ---------------------------------------------------------------------------

def test_broker_exception_exit_reason_is_in_vocabulary():
    """When the broker raises during exit submission, persisted exit_reason must be in vocab.

    Pre-fix this passed f"broker_exception:APIError" (etc.) into coerce_exit_reason
    which always returned 'unknown' (the prefix wasn't in LEGACY_COERCIONS), losing
    the broker-vs-other-error distinction.
    Post-fix it writes "broker_exception" (now a first-class vocab entry).
    """
    from src.shadow_trading import executor

    entry_ts = _isoformat_days_ago(1)
    open_trade = {
        "trade_id": "tid-open",
        "ticker": "MSFT",
        "status": "open",
        "alpaca_order_id": "order-xyz",
        "actual_entry_price": 200.0,
        "entry_price": 200.0,
        "stop_price": 190.0,
        "target_1": 210.0,
        "target_2": 220.0,
        "planned_shares": 5,
        "actual_entry_time": entry_ts,
        "created_at": entry_ts,
        "exit_retry_count": 0,
        "timeout_days": 15,
    }

    class FakeBrokerError(Exception):
        pass

    with (
        patch.object(executor, "get_open_shadow_trades", return_value=[open_trade]),
        patch.object(executor, "_get_current_price_safe", return_value=189.0),  # below stop → exit triggers
        patch.object(executor, "update_shadow_trade") as mock_update,
        patch.object(executor, "load_config", return_value={"shadow_trading": {"timeout_days": 15}}),
        patch.object(executor, "_submit_exit_order", side_effect=FakeBrokerError("connection refused")),
        # Position must exist at broker so _sync_exit_qty doesn't intercept.
        patch("src.shadow_trading.alpaca_adapter.get_all_positions",
              return_value=[{"symbol": "MSFT", "qty": 5}]),
        patch("src.shadow_trading.broker_exception_logger.log_and_persist"),
    ):
        executor.check_and_manage_open_trades(db_path=":memory:")

    # Find the broker-exception write specifically (exit_failed path with retry count)
    exception_writes = [
        c.args[1].get("exit_reason")
        for c in mock_update.call_args_list
        if len(c.args) >= 2
        and isinstance(c.args[1], dict)
        and c.args[1].get("status") in ("exit_failed", "exit_abandoned")
    ]
    assert exception_writes, "expected at least one broker-exception exit_reason write"
    for er in exception_writes:
        assert er in CONTROLLED_VOCAB, (
            f"broker-exception exit_reason {er!r} not in CONTROLLED_VOCAB"
        )
    assert "broker_exception" in exception_writes


# ---------------------------------------------------------------------------
# Bug 1c — partial_exit (line 2069)
# ---------------------------------------------------------------------------

def test_partial_exit_reason_is_in_vocabulary():
    """When the broker fills only some shares, persisted exit_reason must be in vocab.

    Pre-fix this wrote f"partial_target_1" (etc.) — out of vocab.
    Post-fix it writes "partial_exit" (now a first-class vocab entry).
    """
    from src.shadow_trading import executor

    entry_ts = _isoformat_days_ago(1)
    open_trade = {
        "trade_id": "tid-partial",
        "ticker": "GOOG",
        "status": "open",
        "alpaca_order_id": "order-pq",
        "actual_entry_price": 150.0,
        "entry_price": 150.0,
        "stop_price": 140.0,
        "target_1": 160.0,
        "target_2": 170.0,
        "planned_shares": 10,
        "actual_entry_time": entry_ts,
        "created_at": entry_ts,
        "exit_retry_count": 0,
        "timeout_days": 15,
    }

    partial_fill_result = {
        "status": "partially_filled",
        "filled_qty": 4,
        "filled_avg_price": 161.0,
    }

    with (
        patch.object(executor, "get_open_shadow_trades", return_value=[open_trade]),
        patch.object(executor, "_get_current_price_safe", return_value=161.0),  # above target_1 → exit triggers
        patch.object(executor, "update_shadow_trade") as mock_update,
        patch.object(executor, "load_config", return_value={"shadow_trading": {"timeout_days": 15}}),
        patch.object(executor, "_submit_exit_order", return_value=partial_fill_result),
        # Broker has the position so _sync_exit_qty doesn't intercept.
        patch("src.shadow_trading.alpaca_adapter.get_all_positions",
              return_value=[{"symbol": "GOOG", "qty": 10}]),
    ):
        executor.check_and_manage_open_trades(db_path=":memory:")

    # Find partial-fill-status writes (still status='open')
    partial_writes = [
        c.args[1].get("exit_reason")
        for c in mock_update.call_args_list
        if len(c.args) >= 2
        and isinstance(c.args[1], dict)
        and c.args[1].get("status") == "open"
        and c.args[1].get("exit_reason") is not None
    ]
    assert partial_writes, "expected at least one partial-exit exit_reason write"
    for er in partial_writes:
        assert er in CONTROLLED_VOCAB, (
            f"partial-exit exit_reason {er!r} not in CONTROLLED_VOCAB"
        )
    assert "partial_exit" in partial_writes


# ---------------------------------------------------------------------------
# Vocabulary additions sanity
# ---------------------------------------------------------------------------

def test_new_vocab_entries_present():
    """The three new first-class vocab entries are present and pass coerce unchanged."""
    from src.shadow_trading.exit_reason import coerce_exit_reason
    for value in ("entry_unfilled", "partial_exit", "broker_exception"):
        assert value in CONTROLLED_VOCAB, f"{value} missing from CONTROLLED_VOCAB"
        assert coerce_exit_reason(value) == value
