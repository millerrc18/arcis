"""Tests for render sync reconcile module (src/sync/reconcile.py).

Covers: registry-driven eligibility, topo-sort guard, ghost-row health check,
periodic reconcile firing in RenderSyncThread.
"""

import sqlite3
from unittest.mock import MagicMock, patch, call

import pytest


# ── Eligibility tests ────────────────────────────────────────────────


def test_reconcile_eligibility_reads_registry_field():
    """Table with sync_reconcile=True is eligible; False is not.

    Runtime SQLite probing must be gone — eligibility comes solely from
    the registry field exposed via generate_sync_tables() entries.
    """
    from src.sync.reconcile import is_eligible

    entry_yes = {"sync_reconcile": True, "pk": "trade_id", "mode": "incremental"}
    entry_no = {"sync_reconcile": False, "pk": "trade_id", "mode": "incremental"}
    entry_missing = {"pk": "trade_id", "mode": "incremental"}

    eligible_yes, reason_yes = is_eligible("shadow_trades", entry_yes)
    assert eligible_yes is True, f"Expected True, got {eligible_yes} ({reason_yes})"

    eligible_no, reason_no = is_eligible("shadow_trades", entry_no)
    assert eligible_no is False
    assert "allowlist" in reason_no.lower() or reason_no != ""

    eligible_missing, reason_missing = is_eligible("shadow_trades", entry_missing)
    assert eligible_missing is False


# ── Topo-sort registry guard tests ───────────────────────────────────


def test_topo_sort_registry_guard_raises_on_empty():
    """Invoking the wrapper before TABLES is populated raises a clear error.

    The precondition check must fire before calling _topo_sort_tables()
    to prevent silent FK-unaware output when the registry is empty.
    """
    from src.sync.reconcile import topo_sort_reconcile_tables

    with pytest.raises(RuntimeError, match="(?i)(registry|TABLES|empty|populated)"):
        topo_sort_reconcile_tables({})


# ── Ghost-row health check tests ─────────────────────────────────────


def test_assert_no_ghost_rows_pass_when_pg_le_sqlite(tmp_path):
    """Returns (True, message) when PG count <= SQLite count (no ghost rows)."""
    from src.sync.reconcile import assert_no_ghost_rows

    db_path = str(tmp_path / "test.sqlite3")
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE shadow_trades (trade_id TEXT PRIMARY KEY, ticker TEXT)"
    )
    conn.execute("INSERT INTO shadow_trades VALUES ('t1', 'AAPL')")
    conn.execute("INSERT INTO shadow_trades VALUES ('t2', 'MSFT')")
    conn.commit()
    conn.close()

    pg_conn = MagicMock()
    cur = MagicMock()
    pg_conn.cursor.return_value.__enter__ = MagicMock(return_value=cur)
    pg_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    cur.fetchone.return_value = (1,)

    is_clean, message = assert_no_ghost_rows(pg_conn, "shadow_trades", db_path)
    assert is_clean is True


def test_assert_no_ghost_rows_fail_when_pg_gt_sqlite(tmp_path):
    """Returns (False, message) when PG count > SQLite count (ghost rows exist)."""
    from src.sync.reconcile import assert_no_ghost_rows

    db_path = str(tmp_path / "test.sqlite3")
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE shadow_trades (trade_id TEXT PRIMARY KEY, ticker TEXT)"
    )
    conn.execute("INSERT INTO shadow_trades VALUES ('t1', 'AAPL')")
    conn.commit()
    conn.close()

    pg_conn = MagicMock()
    cur = MagicMock()
    pg_conn.cursor.return_value.__enter__ = MagicMock(return_value=cur)
    pg_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    cur.fetchone.return_value = (999,)

    is_clean, message = assert_no_ghost_rows(pg_conn, "shadow_trades", db_path)
    assert is_clean is False
    assert "ghost" in message.lower() or "999" in message or "1" in message


# ── Periodic reconcile firing tests ──────────────────────────────────


def test_periodic_reconcile_fires_at_n_cycles():
    """RenderSyncThread fires reconcile on cycles 3, 6, 9 but not 1, 2, 4, 5.

    reconcile_every_n_cycles=3 means fire on every 3rd cycle.
    """
    from src.sync.render_sync import RenderSyncThread

    thread = RenderSyncThread("postgresql://test", reconcile_every_n_cycles=3)
    assert thread.reconcile_every_n_cycles == 3

    fired_at = []

    def fake_run_sync_cycle(db_url, db_path):
        return {"synced": {}, "errors": [], "timestamp": "2026-01-01T00:00:00"}

    def fake_reconcile_all(pg_conn, db_path):
        fired_at.append(thread._cycle_count)
        return {}

    with patch("src.sync.render_sync.run_sync_cycle", side_effect=fake_run_sync_cycle):
        with patch("src.sync.reconcile.reconcile_all", side_effect=fake_reconcile_all):
            for i in range(1, 10):
                thread._cycle_count = i
                if i % 3 == 0:
                    thread._maybe_run_reconcile(None)

    assert 3 in fired_at
    assert 6 in fired_at
    assert 9 in fired_at


def test_periodic_reconcile_failure_isolated_from_sync():
    """reconcile_all raising must not break the sync cycle's normal completion.

    Errors from reconcile_all are logged and appended to summary["errors"],
    not propagated as exceptions.
    """
    from src.sync.render_sync import run_sync_cycle

    mock_pg_conn = MagicMock()
    mock_cur = MagicMock()
    mock_pg_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cur)
    mock_pg_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    mock_cur.fetchall.return_value = []

    with patch("src.sync.render_sync._connect_pg_with_retry", return_value=mock_pg_conn):
        with patch("src.sync.render_sync._ensure_pg_connection", return_value=mock_pg_conn):
            with patch("src.sync.render_sync.sync_table", return_value=0):
                with patch("src.sync.render_sync.pull_commands", return_value=[]):
                    with patch("src.sync.render_sync.expire_stale_commands"):
                        with patch(
                            "src.sync.reconcile.reconcile_all",
                            side_effect=RuntimeError("reconcile exploded"),
                        ):
                            with patch(
                                "src.schema.postgres.create_all_tables"
                            ):
                                with patch(
                                    "src.schema.postgres.ensure_columns"
                                ):
                                    summary = run_sync_cycle(
                                        "postgresql://test",
                                        db_path=":memory:",
                                        _reconcile_cycle=True,
                                    )

    assert isinstance(summary, dict)
    errors = summary.get("errors", [])
    assert any("reconcile" in str(e).lower() for e in errors), (
        f"Expected reconcile error in summary['errors'], got: {errors}"
    )


# ── Wave 5 — Anti-re-backfill guard tests ────────────────────────────


import sqlite3 as _sqlite3
from datetime import datetime as _datetime, timedelta as _timedelta
from zoneinfo import ZoneInfo as _ZoneInfo
from unittest.mock import patch as _patch

_ET = _ZoneInfo("America/New_York")

_AAPL_ALPACA_POSITION = [
    {
        "symbol": "AAPL",
        "qty": 10.0,
        "avg_entry_price": 175.0,
        "current_price": 178.0,
        "market_value": 1780.0,
        "unrealized_pl": 30.0,
        "unrealized_plpc": 0.017,
    },
]


@_patch("src.shadow_trading.reconcile.get_all_positions", return_value=_AAPL_ALPACA_POSITION)
@_patch("src.shadow_trading.reconcile.cancel_orders_for_ticker", return_value=0)
def test_phantom_orphan_skipped_when_recent_reconciled_stale(mock_cancel, mock_positions, tmp_path):
    """Wave 5 guard: skip backfill when ticker had reconciled_stale within last 6 hours.

    Seed: shadow_trades row for AAPL with order_type='reconciled',
    exit_reason='reconciled_stale', actual_exit_time = now - 1 hour (within guard window).
    Alpaca returns AAPL as an open position (the phantom).
    Expected: AAPL is NOT backfilled; result['skipped'] contains AAPL;
    a WARNING is logged matching 'Phantom orphan skipped — AAPL'.
    """
    from src.journal.store import initialize_database
    from src.shadow_trading.reconcile import reconcile_paper_trades

    db_path = str(tmp_path / "test.sqlite3")
    initialize_database(db_path)

    recent_exit_time = (_datetime.now(_ET) - _timedelta(hours=1)).isoformat()
    now_str = _datetime.now(_ET).isoformat()
    with _sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO shadow_trades
                (trade_id, ticker, status, source, direction, order_type,
                 exit_reason, actual_exit_time, entry_price, planned_shares,
                 desk, created_at, updated_at)
            VALUES (?, 'AAPL', 'closed', 'paper', 'long', 'reconciled',
                    'reconciled_stale', ?, 175.0, 10, 'swing', ?, ?)
            """,
            ("test-stale-001", recent_exit_time, now_str, now_str),
        )

    import logging
    with _patch("src.shadow_trading.reconcile.logger") as mock_logger:
        result = reconcile_paper_trades(db_path=db_path, dry_run=False)

    assert "AAPL" not in result["backfilled"], (
        f"AAPL should have been skipped but was backfilled: {result['backfilled']}"
    )
    assert "AAPL" in result.get("skipped", []), (
        f"AAPL should appear in result['skipped'] but got: {result.get('skipped')}"
    )

    warning_calls = [str(call) for call in mock_logger.warning.call_args_list]
    assert any("Phantom orphan skipped" in c and "AAPL" in c for c in warning_calls), (
        f"Expected warning 'Phantom orphan skipped — AAPL'; got calls: {warning_calls}"
    )


@_patch("src.shadow_trading.reconcile.get_all_positions", return_value=_AAPL_ALPACA_POSITION)
@_patch("src.shadow_trading.reconcile.cancel_orders_for_ticker", return_value=0)
def test_genuine_orphan_backfilled_when_no_recent_reconciled_stale(mock_cancel, mock_positions, tmp_path):
    """Wave 5 guard: genuine orphan (stale > 6h ago) should still be backfilled normally.

    Seed: shadow_trades row for AAPL with order_type='reconciled',
    exit_reason='reconciled_stale', actual_exit_time = now - 8 hours (outside window).
    Alpaca returns AAPL as a position.
    Expected: AAPL IS backfilled (guard does not fire for old stale rows).
    """
    from src.journal.store import initialize_database
    from src.shadow_trading.reconcile import reconcile_paper_trades

    db_path = str(tmp_path / "test.sqlite3")
    initialize_database(db_path)

    old_exit_time = (_datetime.now(_ET) - _timedelta(hours=8)).isoformat()
    now_str = _datetime.now(_ET).isoformat()
    with _sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO shadow_trades
                (trade_id, ticker, status, source, direction, order_type,
                 exit_reason, actual_exit_time, entry_price, planned_shares,
                 desk, created_at, updated_at)
            VALUES (?, 'AAPL', 'closed', 'paper', 'long', 'reconciled',
                    'reconciled_stale', ?, 175.0, 10, 'swing', ?, ?)
            """,
            ("test-old-stale-001", old_exit_time, now_str, now_str),
        )

    result = reconcile_paper_trades(db_path=db_path, dry_run=False)

    assert "AAPL" in result["backfilled"], (
        f"AAPL should have been backfilled (old stale row) but was not: {result['backfilled']}"
    )
    assert "AAPL" not in result.get("skipped", []), (
        f"AAPL should NOT appear in skipped for old stale row: {result.get('skipped')}"
    )


@_patch("src.shadow_trading.reconcile.get_all_positions", return_value=_AAPL_ALPACA_POSITION)
@_patch("src.shadow_trading.reconcile.cancel_orders_for_ticker", return_value=0)
def test_original_bracket_path_not_skipped_by_guard(mock_cancel, mock_positions, tmp_path):
    """Wave 5 guard: guard must NOT skip when prior row is order_type='bracket'.

    The guard targets only 'reconciled'-type rows that were closed stale.
    A 'bracket' trade that was closed as reconciled_stale (normal signal-flow
    trade, not a phantom backfill) should NOT trigger the guard — the new
    orphan should be backfilled normally.

    Seed: shadow_trades row for AAPL with order_type='bracket',
    exit_reason='reconciled_stale', actual_exit_time = now - 1 hour.
    Alpaca returns AAPL as a position.
    Expected: AAPL IS backfilled (guard only fires for order_type='reconciled').
    """
    from src.journal.store import initialize_database
    from src.shadow_trading.reconcile import reconcile_paper_trades

    db_path = str(tmp_path / "test.sqlite3")
    initialize_database(db_path)

    recent_exit_time = (_datetime.now(_ET) - _timedelta(hours=1)).isoformat()
    now_str = _datetime.now(_ET).isoformat()
    with _sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO shadow_trades
                (trade_id, ticker, status, source, direction, order_type,
                 exit_reason, actual_exit_time, entry_price, planned_shares,
                 desk, created_at, updated_at)
            VALUES (?, 'AAPL', 'closed', 'paper', 'long', 'bracket',
                    'reconciled_stale', ?, 175.0, 10, 'swing', ?, ?)
            """,
            ("test-bracket-stale-001", recent_exit_time, now_str, now_str),
        )

    result = reconcile_paper_trades(db_path=db_path, dry_run=False)

    assert "AAPL" in result["backfilled"], (
        f"AAPL should be backfilled (bracket order_type, not phantom) but was not: {result['backfilled']}"
    )
    assert "AAPL" not in result.get("skipped", []), (
        f"AAPL should NOT be in skipped (bracket order_type): {result.get('skipped')}"
    )
