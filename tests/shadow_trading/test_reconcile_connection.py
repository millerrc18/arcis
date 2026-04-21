"""Sprint 2 H7 — regression tests for bare sqlite3.connect -> connect_db swap.

7 call sites in src/shadow_trading/reconcile.py used
`sqlite3.connect(db_path)` directly, bypassing the canonical
`src.utils.db.connect_db()` wrapper. The wrapper applies
``busy_timeout=30s`` and ``row_factory=sqlite3.Row``. Bare
``sqlite3.connect`` defaults to 5-second timeout and tuple rows,
which produced intermittent "database is locked" errors per the
2026-04-19 incident (118 lock errors during an MS Access inspection
session) and exposed the reconcile path to similar issues.

CLAUDE.md mandates connect_db() for all sqlite3 connections.

These tests verify:
  1. No bare `sqlite3.connect(` remains in reconcile.py (static scan).
  2. connect_db() returns a connection with busy_timeout >= 30000ms.
  3. connect_db() returns a connection with Row factory.

Note: connect_db does NOT set PRAGMA foreign_keys or WAL mode (Pass-1
claim corrected in Pass 2 research). Those would be separate changes.
"""
from __future__ import annotations

import pathlib
import sqlite3

import pytest


def test_reconcile_has_no_bare_sqlite3_connect():
    """Static scan: reconcile.py must route all connections through connect_db."""
    src = pathlib.Path("src/shadow_trading/reconcile.py").read_text(encoding="utf-8")
    # `sqlite3.connect(` as a call (not `sqlite3.Connection`, not `sqlite3.Row`)
    assert "sqlite3.connect(" not in src, (
        "bare sqlite3.connect() reintroduced in reconcile.py — use connect_db()"
    )


def test_connect_db_applies_busy_timeout(tmp_path):
    """connect_db must set busy_timeout to 30000ms (not the 5s default)."""
    from src.utils.db import connect_db

    db = str(tmp_path / "tb.db")
    with connect_db(db) as conn:
        busy_timeout = conn.execute("PRAGMA busy_timeout").fetchone()[0]
    assert busy_timeout >= 30000, (
        f"expected busy_timeout >= 30000ms, got {busy_timeout}ms"
    )


def test_connect_db_applies_row_factory(tmp_path):
    """connect_db must set row_factory to sqlite3.Row so callers can use
    both integer and string column access (r[0] and r['col'])."""
    from src.utils.db import connect_db

    db = str(tmp_path / "rf.db")
    with connect_db(db) as conn:
        conn.execute("CREATE TABLE x (a INTEGER, b TEXT)")
        conn.execute("INSERT INTO x VALUES (1, 'foo')")
        row = conn.execute("SELECT a, b FROM x").fetchone()
    assert isinstance(row, sqlite3.Row)
    assert row[0] == 1 and row["a"] == 1
    assert row[1] == "foo" and row["b"] == "foo"


def test_connect_db_timeout_actually_waits(tmp_path):
    """Integration: with two connections, a second writer should wait
    (not immediately fail) if the first holds an IMMEDIATE transaction.

    This is the production-relevant behavior: bare sqlite3.connect would
    raise OperationalError immediately; connect_db should wait up to
    busy_timeout before raising.
    """
    from src.utils.db import connect_db
    import threading
    import time

    db = str(tmp_path / "wait.db")
    with sqlite3.connect(db) as setup:
        setup.execute("CREATE TABLE x (a INTEGER)")

    # First connection holds an IMMEDIATE tx briefly.
    first_locked = threading.Event()
    first_done = threading.Event()

    def first_writer():
        with sqlite3.connect(db, timeout=60) as c1:
            c1.execute("BEGIN IMMEDIATE")
            c1.execute("INSERT INTO x VALUES (1)")
            first_locked.set()
            # Hold the lock briefly (shorter than the second writer's
            # busy_timeout so the second call succeeds).
            time.sleep(0.5)
            c1.commit()
        first_done.set()

    t = threading.Thread(target=first_writer)
    t.start()
    first_locked.wait(timeout=5)

    # Second writer via connect_db should wait and then succeed
    start = time.monotonic()
    with connect_db(db) as c2:
        c2.execute("INSERT INTO x VALUES (2)")
    elapsed = time.monotonic() - start
    t.join()

    # We expect `elapsed` to be at least ~0.3s (waited for the first
    # tx to release) but well under busy_timeout (30s).
    assert 0.1 < elapsed < 10.0, f"unexpected wait duration: {elapsed:.2f}s"
