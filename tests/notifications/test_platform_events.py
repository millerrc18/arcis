"""Tests for src.notifications.platform_events."""
import sqlite3
from datetime import datetime, timezone
from unittest.mock import patch, call

from src.notifications.platform_events import (
    _DEDUP_CACHE,
    notify_backtest_complete,
    notify_shadow_gate_ready,
    notify_strategy_demoted,
    notify_strategy_promoted,
)


def _clear_dedup():
    _DEDUP_CACHE.clear()


def _make_dedup_db():
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE notifications_dedup ("
        "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "  event_type TEXT NOT NULL,"
        "  dedup_key TEXT NOT NULL,"
        "  sent_at TEXT NOT NULL,"
        "  UNIQUE(event_type, dedup_key)"
        ")"
    )
    conn.commit()
    return conn


def test_backtest_complete_prefixed_with_RESEARCH():
    _clear_dedup()
    conn = _make_dedup_db()
    with patch("src.notifications.telegram.send_telegram") as mock_send:
        notify_backtest_complete("strat_a", "r1234567890", True, _conn=conn)
    assert mock_send.called
    msg = mock_send.call_args.args[0]
    assert "[RESEARCH]" in msg
    assert "strat_a" in msg


def test_gate_ready_deduplicated_within_24h():
    """Two calls with same strategy_id -> only one send."""
    _clear_dedup()
    conn = _make_dedup_db()
    with patch("src.notifications.telegram.send_telegram") as mock_send:
        notify_shadow_gate_ready(
            "strat_b",
            {"dsr": 0.96, "pbo": 0.3, "oos_efficiency": 0.5},
            _conn=conn,
        )
        notify_shadow_gate_ready(
            "strat_b",
            {"dsr": 0.96, "pbo": 0.3, "oos_efficiency": 0.5},
            _conn=conn,
        )
    assert mock_send.call_count == 1


def test_gate_ready_not_deduplicated_across_strategies():
    _clear_dedup()
    conn = _make_dedup_db()
    with patch("src.notifications.telegram.send_telegram") as mock_send:
        notify_shadow_gate_ready("a", {"dsr": 0.96, "pbo": 0.3, "oos_efficiency": 0.5}, _conn=conn)
        notify_shadow_gate_ready("b", {"dsr": 0.96, "pbo": 0.3, "oos_efficiency": 0.5}, _conn=conn)
    assert mock_send.call_count == 2


def test_gate_ready_handles_partial_evidence():
    """If some evidence fields are None, the message still sends
    with only the available fields shown (no crash)."""
    _clear_dedup()
    conn = _make_dedup_db()
    with patch("src.notifications.telegram.send_telegram") as mock_send:
        notify_shadow_gate_ready(
            "strat_c",
            {"dsr": 0.96, "pbo": None, "oos_efficiency": None},
            _conn=conn,
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


# ── MUST_FIX 1: DB-backed dedup wired into production paths ──────────────────

def test_notify_backtest_complete_calls_db_dedup():
    """notify_backtest_complete uses _already_notified_recently_db, not in-memory cache."""
    conn = _make_dedup_db()
    with patch("src.notifications.telegram.send_telegram") as mock_send:
        notify_backtest_complete("s1", "r_abcdefgh", True, _conn=conn)
        notify_backtest_complete("s1", "r_abcdefgh", True, _conn=conn)
    # Second call should be deduped via DB — only one send
    assert mock_send.call_count == 1
    rows = conn.execute("SELECT * FROM notifications_dedup").fetchall()
    assert len(rows) == 1


def test_notify_backtest_complete_db_dedup_survives_cache_clear():
    """After clearing in-memory _DEDUP_CACHE, DB dedup still suppresses duplicate."""
    conn = _make_dedup_db()
    with patch("src.notifications.telegram.send_telegram"):
        notify_backtest_complete("s2", "r_xyz12345", False, _conn=conn)
    # Simulate NSSM restart: clear in-memory cache
    _clear_dedup()
    with patch("src.notifications.telegram.send_telegram") as mock_send2:
        notify_backtest_complete("s2", "r_xyz12345", False, _conn=conn)
    assert mock_send2.call_count == 0, "DB dedup must suppress after cache clear"


def test_notify_shadow_gate_ready_calls_db_dedup():
    """notify_shadow_gate_ready uses _already_notified_recently_db, not in-memory cache."""
    conn = _make_dedup_db()
    evidence = {"dsr": 0.96, "pbo": 0.3, "oos_efficiency": 0.5}
    with patch("src.notifications.telegram.send_telegram") as mock_send:
        notify_shadow_gate_ready("strat_db_1", evidence, _conn=conn)
        notify_shadow_gate_ready("strat_db_1", evidence, _conn=conn)
    assert mock_send.call_count == 1
    rows = conn.execute("SELECT * FROM notifications_dedup").fetchall()
    assert len(rows) == 1


def test_notify_shadow_gate_ready_db_dedup_survives_cache_clear():
    """After clearing in-memory _DEDUP_CACHE, DB dedup still suppresses duplicate."""
    conn = _make_dedup_db()
    evidence = {"dsr": 0.96}
    with patch("src.notifications.telegram.send_telegram"):
        notify_shadow_gate_ready("strat_db_2", evidence, _conn=conn)
    _clear_dedup()
    with patch("src.notifications.telegram.send_telegram") as mock_send2:
        notify_shadow_gate_ready("strat_db_2", evidence, _conn=conn)
    assert mock_send2.call_count == 0, "DB dedup must suppress after cache clear"
