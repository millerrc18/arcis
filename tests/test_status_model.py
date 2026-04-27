"""Tests for shadow trade status model."""
import sqlite3
import uuid
from unittest.mock import patch

from src.shadow_trading.models import TERMINAL_STATUSES, ACTIVE_STATUSES


def test_terminal_statuses_defined():
    assert "closed" in TERMINAL_STATUSES
    assert "rejected" in TERMINAL_STATUSES
    assert "exit_abandoned" in TERMINAL_STATUSES


def test_active_statuses_defined():
    assert "open" in ACTIVE_STATUSES
    assert "pending" in ACTIVE_STATUSES
    assert "exit_pending" in ACTIVE_STATUSES
    assert "exit_failed" in ACTIVE_STATUSES


def test_no_overlap():
    assert TERMINAL_STATUSES.isdisjoint(ACTIVE_STATUSES)


def test_failed_is_terminal():
    assert "failed" in TERMINAL_STATUSES
    assert "rejected" in TERMINAL_STATUSES


def test_quarantined_is_terminal():
    """#626 — 'quarantined' must be in TERMINAL_STATUSES so position counters exclude it."""
    assert "quarantined" in TERMINAL_STATUSES


def _make_mem_db():
    conn = sqlite3.connect(":memory:")
    conn.execute("""
        CREATE TABLE shadow_trades (
            trade_id TEXT PRIMARY KEY,
            ticker TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            quarantined INTEGER NOT NULL DEFAULT 0,
            exit_reason TEXT,
            updated_at TEXT,
            created_at TEXT NOT NULL DEFAULT '2026-04-21T09:00:00'
        )
    """)
    conn.commit()
    return conn


def test_quarantine_trade_sets_terminal_fields():
    """#626 — quarantine_trade() sets status='quarantined', quarantined=1, exit_reason atomically."""
    from src.shadow_trading.executor import quarantine_trade

    conn = _make_mem_db()
    trade_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO shadow_trades (trade_id, ticker, status) VALUES (?, 'CVS', 'open')",
        (trade_id,),
    )
    conn.commit()

    with patch("src.shadow_trading.executor.connect_db") as mock_connect:
        mock_connect.return_value.__enter__ = lambda s: conn
        mock_connect.return_value.__exit__ = lambda s, *a: None
        quarantine_trade(trade_id, reason="manual_operator_halt", db_path=":memory:")

    row = conn.execute(
        "SELECT status, quarantined, exit_reason FROM shadow_trades WHERE trade_id=?",
        (trade_id,),
    ).fetchone()
    assert row is not None
    status, quarantined_flag, exit_reason = row
    assert status == "quarantined", f"Expected status='quarantined', got '{status}'"
    assert quarantined_flag == 1, "Expected quarantined=1"
    assert exit_reason == "manual_operator_halt"


def test_quarantine_trade_at_most_one_open_per_ticker():
    """#626 — operator replay: two open CVS rows, quarantining one leaves at most one open."""
    from src.shadow_trading.executor import quarantine_trade

    conn = _make_mem_db()
    tid1 = str(uuid.uuid4())
    tid2 = str(uuid.uuid4())
    conn.executemany(
        "INSERT INTO shadow_trades (trade_id, ticker, status) VALUES (?, 'CVS', 'open')",
        [(tid1,), (tid2,)],
    )
    conn.commit()

    with patch("src.shadow_trading.executor.connect_db") as mock_connect:
        mock_connect.return_value.__enter__ = lambda s: conn
        mock_connect.return_value.__exit__ = lambda s, *a: None
        quarantine_trade(tid1, reason="2026-04-21_cvs_retry_loop_manual_quarantine", db_path=":memory:")

    open_rows = conn.execute(
        "SELECT COUNT(*) FROM shadow_trades WHERE ticker='CVS' AND status='open'"
    ).fetchone()[0]
    assert open_rows == 1, f"Expected exactly 1 open CVS row after quarantine, got {open_rows}"

    quarantined_rows = conn.execute(
        "SELECT COUNT(*) FROM shadow_trades WHERE ticker='CVS' AND status='quarantined' AND quarantined=1"
    ).fetchone()[0]
    assert quarantined_rows == 1, f"Expected exactly 1 quarantined CVS row, got {quarantined_rows}"
