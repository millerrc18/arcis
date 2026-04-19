"""Regression tests for SQLite lock-contention resilience.

Background (2026-04-19): arcis.log accumulated 118 "database is locked"
errors in one session — scan, intraday bracket check, MR scan, traffic
light persistence, and render_sync sync_state updates all hit the wall.
Root contributors:
  1. External tool (MS Access) holding the file lock while inspecting data
  2. Hot-path writers opening SQLite with Python's default 5s timeout
     (insufficient when the file lock lingers)

These tests lock the 30s busy_timeout on connect_db so it can't regress.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path


def test_connect_db_sets_thirty_second_busy_timeout():
    """busy_timeout must be 30_000 ms — five-second timeout was insufficient
    to ride through external-tool locks observed in production."""
    from src.utils import db

    assert db.BUSY_TIMEOUT_MS == 30_000, (
        f"connect_db BUSY_TIMEOUT_MS regressed to {db.BUSY_TIMEOUT_MS}; "
        "must remain 30000ms to tolerate MS Access / DB Browser file locks"
    )


def test_connect_db_applies_busy_timeout_pragma(tmp_path):
    """The helper must actually apply the PRAGMA, not just import the constant."""
    from src.utils.db import BUSY_TIMEOUT_MS, connect_db

    db_file = tmp_path / "test.db"
    # Bootstrap the file so connect_db has something to open
    sqlite3.connect(db_file).close()

    with connect_db(str(db_file)) as conn:
        row = conn.execute("PRAGMA busy_timeout").fetchone()
        applied = row[0]  # sqlite3.Row supports integer indexing

    assert applied == BUSY_TIMEOUT_MS, (
        f"PRAGMA busy_timeout returned {applied}; connect_db is not applying it"
    )


def test_connect_db_returns_row_factory_connection(tmp_path):
    """Row factory must be sqlite3.Row so consumers get dict-like access."""
    from src.utils.db import connect_db

    db_file = tmp_path / "test.db"
    sqlite3.connect(db_file).close()

    with connect_db(str(db_file)) as conn:
        conn.execute("CREATE TABLE t (a INTEGER, b TEXT)")
        conn.execute("INSERT INTO t VALUES (1, 'x')")
        row = conn.execute("SELECT a, b FROM t").fetchone()
        # sqlite3.Row supports both index and column-name access
        assert row["a"] == 1
        assert row["b"] == "x"


def test_hot_path_writers_import_connect_db():
    """The specific modules that hit 'database is locked' in production
    (traffic_light, scheduler.metrics, shadow_trading.bracket_monitor/executor/reconcile)
    must import connect_db so their writes get the 30s timeout."""
    repo_root = Path(__file__).resolve().parent.parent
    required = [
        repo_root / "src/features/traffic_light.py",
        repo_root / "src/scheduler/metrics.py",
        repo_root / "src/shadow_trading/bracket_monitor.py",
        repo_root / "src/shadow_trading/executor.py",
        repo_root / "src/shadow_trading/reconcile.py",
    ]
    offenders = []
    for path in required:
        text = path.read_text(encoding="utf-8")
        if "from src.utils.db import connect_db" not in text:
            offenders.append(str(path.relative_to(repo_root)))
    assert not offenders, (
        f"These hot-path writers do not import connect_db:\n  "
        + "\n  ".join(offenders)
    )
