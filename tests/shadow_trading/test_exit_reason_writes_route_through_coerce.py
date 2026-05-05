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


# ---------------------------------------------------------------------------
# Wave 4 H4 — 3 bypass sites now wrapped with coerce_exit_reason
# ---------------------------------------------------------------------------

def test_quarantine_trade_exit_reason_passes_through_coerce():
    """executor.py:120 — quarantine_trade must coerce reason through coerce_exit_reason.

    Passing a non-vocab reason should result in 'unknown' being written to the DB,
    not the raw non-vocab string.
    """
    from src.shadow_trading import executor
    import sqlite3

    conn = sqlite3.connect(":memory:")
    conn.execute("""
        CREATE TABLE shadow_trades (
            trade_id TEXT PRIMARY KEY,
            status TEXT,
            quarantined INTEGER,
            exit_reason TEXT,
            updated_at TEXT
        )
    """)
    conn.execute(
        "INSERT INTO shadow_trades VALUES (?, ?, ?, ?, ?)",
        ("tid-q", "open", 0, None, None),
    )
    conn.commit()

    with patch("src.shadow_trading.executor.connect_db", return_value=conn):
        executor.quarantine_trade("tid-q", "non_vocab_raw_value", db_path=":memory:")

    row = conn.execute(
        "SELECT exit_reason FROM shadow_trades WHERE trade_id='tid-q'"
    ).fetchone()
    assert row is not None
    assert row[0] in CONTROLLED_VOCAB, (
        f"quarantine_trade wrote non-vocab value {row[0]!r} — must pass through coerce"
    )
    conn.close()


def test_skip_reason_from_sync_exit_qty_coerces():
    """executor.py:1489 — skip_reason written via update_shadow_trade must be coerced.

    If _sync_exit_qty returns a non-vocab skip_reason, the update must persist
    a value from CONTROLLED_VOCAB (coerce fallback = 'unknown').
    """
    from src.shadow_trading import executor

    entry_ts = _isoformat_days_ago(1)
    open_trade = {
        "trade_id": "tid-skip",
        "ticker": "AAPL",
        "status": "exit_failed",
        "alpaca_order_id": "order-skip",
        "actual_entry_price": 100.0,
        "entry_price": 100.0,
        "stop_price": 90.0,
        "target_1": 110.0,
        "target_2": 120.0,
        "planned_shares": 10,
        "shares": 10,
        "actual_entry_time": entry_ts,
        "created_at": entry_ts,
        "exit_retry_count": 0,
        "timeout_days": 15,
    }

    with (
        patch.object(executor, "get_open_shadow_trades", return_value=[open_trade]),
        patch.object(executor, "_get_current_price_safe", return_value=105.0),
        patch.object(executor, "update_shadow_trade") as mock_update,
        patch.object(executor, "load_config", return_value={"shadow_trading": {"timeout_days": 15}}),
        patch.object(executor, "_sync_exit_qty", return_value=(0, "non_vocab_skip_value")),
        patch("src.shadow_trading.alpaca_adapter.get_all_positions",
              return_value=[]),
        patch("src.shadow_trading.alpaca_adapter.get_order_status",
              return_value={"status": "pending"}),
        patch("src.shadow_trading.alpaca_adapter.cancel_paper_order",
              return_value=None),
    ):
        executor.check_and_manage_open_trades(db_path=":memory:")

    exit_pending_writes = [
        call.args[1].get("exit_reason")
        for call in mock_update.call_args_list
        if len(call.args) >= 2
        and isinstance(call.args[1], dict)
        and call.args[1].get("status") == "exit_pending"
        and call.args[1].get("exit_reason") is not None
    ]
    assert exit_pending_writes, "expected at least one exit_pending write with exit_reason"
    for er in exit_pending_writes:
        assert er in CONTROLLED_VOCAB, (
            f"skip_reason bypass write {er!r} not in CONTROLLED_VOCAB — coerce not applied"
        )


def test_retry_exit_success_reason_coerces():
    """executor.py:1516 — retry handler success path must coerce exit_reason.

    When trade.get('exit_reason') returns a non-vocab value (or None), the
    close_shadow_trade call must receive a vocab-valid exit_reason.
    """
    from src.shadow_trading import executor

    entry_ts = _isoformat_days_ago(1)
    open_trade = {
        "trade_id": "tid-retry",
        "ticker": "TSLA",
        "status": "exit_failed",
        "alpaca_order_id": "order-retry",
        "actual_entry_price": 200.0,
        "entry_price": 200.0,
        "stop_price": 180.0,
        "target_1": 220.0,
        "target_2": 240.0,
        "planned_shares": 5,
        "shares": 5,
        "actual_entry_time": entry_ts,
        "created_at": entry_ts,
        "exit_retry_count": 0,
        "timeout_days": 15,
        "exit_reason": None,
    }

    filled_result = {
        "status": "filled",
        "filled_avg_price": "210.0",
        "order_id": "ord-filled",
    }

    with (
        patch.object(executor, "get_open_shadow_trades", return_value=[open_trade]),
        patch.object(executor, "_get_current_price_safe", return_value=205.0),
        patch.object(executor, "update_shadow_trade"),
        patch.object(executor, "close_shadow_trade") as mock_close,
        patch.object(executor, "load_config", return_value={"shadow_trading": {"timeout_days": 15}}),
        patch.object(executor, "_submit_exit_order", return_value=filled_result),
        patch.object(executor, "_sync_exit_qty", return_value=(5, None)),
        patch("src.shadow_trading.alpaca_adapter.get_all_positions",
              return_value=[{"symbol": "TSLA", "qty": 5}]),
        patch("src.shadow_trading.alpaca_adapter.get_order_status",
              return_value={"status": "pending"}),
        patch("src.shadow_trading.alpaca_adapter.cancel_paper_order",
              return_value=None),
    ):
        executor.check_and_manage_open_trades(db_path=":memory:")

    assert mock_close.called, "expected close_shadow_trade to be called on retry success"
    for call in mock_close.call_args_list:
        er = call.kwargs.get("exit_reason") or (call.args[2] if len(call.args) > 2 else None)
        assert er in CONTROLLED_VOCAB, (
            f"retry-success close_shadow_trade called with non-vocab exit_reason {er!r}"
        )
