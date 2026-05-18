"""Tests for src.notifications.platform_events."""
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, call

import pytest

from src.notifications.platform_events import (
    _DEDUP_CACHE,
    _already_notified_recently_db,
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


# -- Sprint 5 §J5/§J6 Phase 1 T1.7 -----------------------------------------
# Parametrized dual-engine coverage for the notifications_dedup INSERT path
# migrated from `INSERT OR IGNORE` to `engine_aware_upsert(..., action='ignore')`.
# The composite uniqueness target `(event_type, dedup_key)` is resolved via
# `notifications_dedup.sync_conflict_col` set in T0.7 (registry).
# Sibling-search confirmed: only one INSERT OR (IGNORE|REPLACE) site in
# src/notifications/platform_events.py — at :96.

def _select_dedup_row(conn, event_type, dedup_key):
    cur = conn.execute(
        "SELECT event_type, dedup_key, sent_at FROM notifications_dedup "
        "WHERE event_type=? AND dedup_key=?",
        (event_type, dedup_key),
    )
    return cur.fetchone()


def _count_dedup_rows(conn):
    cur = conn.execute("SELECT COUNT(*) AS c FROM notifications_dedup")
    row = cur.fetchone()
    if hasattr(row, "keys") and "c" in row.keys():
        return row["c"]
    return row[0]


@pytest.fixture(autouse=True)
def _load_test_database_url_from_env():
    """REMOVED v0.36.14 — DO NOT auto-construct TEST_DATABASE_URL pointing at
    127.0.0.1:5433 (the operator's production halcyon-pg).

    Sprint 5 phase 1 T1.7 introduced an auto-construction block that read
    `DOCKER_PG_PASSWORD` from `.env` and set
    `TEST_DATABASE_URL=postgresql://halcyon:<pw>@127.0.0.1:5433/halcyon`. The
    intent was "the operator's Docker PG is the local test instance," but in
    practice the operator runs the PRODUCTION halcyon database on port 5433.

    P0 incident 2026-05-17 21:28 UTC (#159): one of six dispatched coding-team
    developer agents ran a pytest invocation that collected this file. The
    autouse fixture set TEST_DATABASE_URL to the production URL. The
    pg_wrapper fixture then connected to PROD halcyon, bootstrapped its
    tables (CREATE TABLE IF NOT EXISTS — no-op since the tables existed),
    ran the test, then on teardown ran DROP TABLE IF EXISTS {name} CASCADE
    for every sync-eligible table — wiping ~80 production tables in ~3
    seconds.

    The P0 guard at conftest.py:51-110 was designed to catch DATABASE_URL
    leakage to prod but didn't check TEST_DATABASE_URL because no test was
    expected to SET that env var itself. Both layers of safety failed.

    The right home for TEST_DATABASE_URL is the operator's environment
    (e.g., a separate halcyon-pg-test container on port 5434), not a test
    fixture. This fixture body now no-ops. If TEST_DATABASE_URL is not set,
    pg_wrapper will skip cleanly; the postgres parametrize variant of any
    test in this file will be reported as SKIPPED, not silently turned into
    a prod-DROP.
    """
    # Intentionally no-op. See docstring for incident details.
    return


def test_t1_7_first_insert_lands_row(parametrized_conn):
    """T1.7 #1 — first call to _already_notified_recently_db inserts the row.

    `engine_aware_upsert(conn, 'notifications_dedup', row, action='ignore')`
    resolves the conflict target to `(event_type, dedup_key)` per the
    registry's sync_conflict_col. The first call has no prior row, so the
    INSERT lands and the function returns False (not previously notified).
    """
    conn = parametrized_conn
    now_iso = datetime.now(timezone.utc).isoformat()
    # Pre-clean the parametrized DB — fixtures bootstrap schemas but may
    # share state across the same engine variant within a test session.
    conn.execute(
        "DELETE FROM notifications_dedup WHERE event_type=? AND dedup_key=?",
        ("t1_7_evt", "t1_7_first"),
    )
    conn.commit()

    result = _already_notified_recently_db(
        "t1_7_evt", "t1_7_first", conn=conn,
    )

    assert result is False, "first call -> not previously notified"
    row = _select_dedup_row(conn, "t1_7_evt", "t1_7_first")
    assert row is not None, "engine_aware_upsert(action='ignore') must INSERT new row"
    # sent_at must be a recent ISO timestamp written by the helper, not
    # the test's `now_iso` — assert it parses and is near-current.
    sent_at = row["sent_at"] if hasattr(row, "keys") else row[2]
    parsed = datetime.fromisoformat(sent_at)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    delta = abs((datetime.now(timezone.utc) - parsed).total_seconds())
    assert delta < 60, f"sent_at {sent_at} should be within 60s of now"


def test_t1_7_duplicate_event_type_dedup_key_ignored(parametrized_conn):
    """T1.7 #2 — duplicate (event_type, dedup_key) is ignored, no exception.

    The autoincrement `id` PK is the surrogate; uniqueness lives on the
    composite `(event_type, dedup_key)` index (registry sync_conflict_col).
    Composite conflict must NOT overwrite the existing row's sent_at, and
    must NOT raise.

    Path: pre-seed a row directly (so the platform_events helper's "row
    exists" branch is bypassed), then directly call the engine_aware_upsert
    line that platform_events:96 now uses, with the same composite. Result:
    no exception, no duplicate row, sent_at preserved. Validates both
    engines route through the correct conflict target — PG path uses
    `ON CONFLICT (event_type, dedup_key) DO NOTHING`, SQLite path uses
    `INSERT OR IGNORE` natively.
    """
    conn = parametrized_conn
    # Pre-clean — fixtures may share state across same-engine variants
    conn.execute(
        "DELETE FROM notifications_dedup WHERE event_type=? AND dedup_key=?",
        ("t1_7_dup_evt", "t1_7_dup_key"),
    )
    conn.commit()

    # Use the production helper to land the first row — exercises the
    # INSERT branch which T1.7 migrates to engine_aware_upsert(action='ignore').
    first = _already_notified_recently_db(
        "t1_7_dup_evt", "t1_7_dup_key", conn=conn,
    )
    assert first is False, "first call -> not previously notified"

    # Capture the sent_at the helper wrote
    seed_row = _select_dedup_row(conn, "t1_7_dup_evt", "t1_7_dup_key")
    assert seed_row is not None
    seed_sent_at = (
        seed_row["sent_at"] if hasattr(seed_row, "keys") else seed_row[2]
    )

    # Now exercise the migrated INSERT branch a second time with the same
    # composite key. Direct engine_aware_upsert call mirrors what
    # platform_events.py:96 does after T1.7 — the duplicate must be
    # ignored (no exception, no overwrite, no new row).
    from src.utils.db import engine_aware_upsert

    later_iso = (datetime.now(timezone.utc) + timedelta(seconds=5)).isoformat()
    # Must NOT raise — duplicate composite is ignored.
    engine_aware_upsert(
        conn,
        "notifications_dedup",
        {
            "event_type": "t1_7_dup_evt",
            "dedup_key": "t1_7_dup_key",
            "sent_at": later_iso,
        },
        action="ignore",
    )
    conn.commit()

    # Row count for our key is still 1 — no duplicate inserted
    cur = conn.execute(
        "SELECT COUNT(*) AS c FROM notifications_dedup WHERE event_type=?",
        ("t1_7_dup_evt",),
    )
    row = cur.fetchone()
    count = row["c"] if hasattr(row, "keys") and "c" in row.keys() else row[0]
    assert count == 1, "duplicate composite conflict must NOT add a row"

    # Original sent_at preserved — action='ignore' must not overwrite
    final_row = _select_dedup_row(conn, "t1_7_dup_evt", "t1_7_dup_key")
    final_sent_at = (
        final_row["sent_at"] if hasattr(final_row, "keys") else final_row[2]
    )
    assert final_sent_at == seed_sent_at, (
        "action='ignore' must preserve original sent_at, "
        f"got {final_sent_at!r} expected {seed_sent_at!r}"
    )
