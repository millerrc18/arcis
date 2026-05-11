"""Tests for src/utils/db.configure_sqlite_for_production + re-exported _sqlite_only_connect.

Covers Sprint 5 §J5/§J6 Phase 0 T0.8 — SQLite runtime-tuning helper that
factors out the PRAGMA block currently inlined at src/scheduler/watch.py
:1107-1132 and re-exports the SQLite-only connect helper so a future
direct-sqlite-only call site can import it from src.utils.db without
reaching into src.schema.sqlite.
"""

import logging
import sqlite3
from unittest.mock import MagicMock

import pytest


def test_configure_sqlite_for_production_applies_all_four_pragmas(tmp_path):
    """SQLite connection receives all 4 runtime-tuning PRAGMAs.

    Verifies busy_timeout=30000, journal_mode=WAL, synchronous=NORMAL,
    and integrity_check validation (returns 'ok' on a fresh DB so no
    RuntimeError is raised).
    """
    from src.utils.db import configure_sqlite_for_production

    db_path = tmp_path / "tune.sqlite3"
    conn = sqlite3.connect(str(db_path), timeout=5.0)
    try:
        configure_sqlite_for_production(conn)

        busy = conn.execute("PRAGMA busy_timeout").fetchone()[0]
        assert busy == 30000, f"busy_timeout should be 30000, got {busy}"

        journal = conn.execute("PRAGMA journal_mode").fetchone()[0]
        assert str(journal).lower() == "wal", f"journal_mode should be wal, got {journal}"

        sync = conn.execute("PRAGMA synchronous").fetchone()[0]
        # 1 == NORMAL per SQLite docs
        assert int(sync) == 1, f"synchronous should be 1 (NORMAL), got {sync}"
    finally:
        conn.close()


def test_configure_sqlite_for_production_noop_on_postgres_wrapper(caplog):
    """PG-wrapped connection: no PRAGMAs executed, warning emitted."""
    from src.utils.db import PostgresConnectionWrapper, configure_sqlite_for_production

    raw_pg = MagicMock(name="pg_raw_conn")
    wrapper = PostgresConnectionWrapper(raw_pg)

    # Track any execute calls on the wrapper to assert no PRAGMA was sent
    spy_execute = MagicMock(wraps=wrapper.execute)
    wrapper.execute = spy_execute  # type: ignore[method-assign]

    with caplog.at_level(logging.WARNING, logger="src.utils.db"):
        result = configure_sqlite_for_production(wrapper)

    assert result is None
    spy_execute.assert_not_called()
    raw_pg.cursor.assert_not_called()
    assert any(
        "PRAGMA runtime tuning is SQLite-only" in record.message
        and "skipping on PG-backed connection" in record.message
        for record in caplog.records
    ), f"Expected warning about PG no-op, got: {[r.message for r in caplog.records]}"


def test_sqlite_only_connect_reexported_from_utils_db():
    """`from src.utils.db import _sqlite_only_connect` is the importable surface.

    Tests that the re-export resolves to a callable that returns a real
    sqlite3.Connection for an in-memory database.
    """
    from src.utils.db import _sqlite_only_connect

    conn = _sqlite_only_connect(":memory:")
    try:
        assert isinstance(conn, sqlite3.Connection)
    finally:
        conn.close()


def test_sqlite_only_connect_sets_busy_timeout_and_row_factory():
    """Re-exported _sqlite_only_connect applies the same defaults as the
    underlying src.schema.sqlite._sqlite_only_connect (busy_timeout=30000,
    row_factory=sqlite3.Row)."""
    from src.utils.db import _sqlite_only_connect

    conn = _sqlite_only_connect(":memory:")
    try:
        assert conn.row_factory is sqlite3.Row
        busy = conn.execute("PRAGMA busy_timeout").fetchone()[0]
        assert busy == 30000, f"busy_timeout should be 30000, got {busy}"
    finally:
        conn.close()
