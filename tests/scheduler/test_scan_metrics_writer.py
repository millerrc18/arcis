"""scan_metrics writer regression tests for Wave 4 H2.

Called by: pytest
Calls: src.scheduler.watch._record_scan_metrics, src.schema.sqlite
Owns tables: none (tests scan_metrics inserts via in-memory DB)
Config keys: none
Tests: this is a test module
"""

import sqlite3
from unittest.mock import patch

import pytest

from tests.conftest import init_test_db


@pytest.fixture
def tmp_db(tmp_path):
    """Create a temp SQLite DB with scan_metrics table."""
    db = tmp_path / "test_scan_metrics.db"
    init_test_db(str(db), tables=["scan_metrics"])
    return str(db)


def _make_watch_loop(db_path: str):
    """Construct a minimal WatchLoop bypassing heavy __init__."""
    from src.scheduler.watch import WatchLoop
    wl = WatchLoop.__new__(WatchLoop)
    return wl


def test_sequential_inserts_get_distinct_auto_ids(tmp_db):
    """Three sequential _record_scan_metrics calls produce distinct auto-generated ids."""
    wl = _make_watch_loop(tmp_db)

    with patch("src.scheduler.watch.DB_PATH", tmp_db):
        wl._record_scan_metrics()
        wl._record_scan_metrics()
        wl._record_scan_metrics()

    conn = sqlite3.connect(tmp_db)
    rows = conn.execute(
        "SELECT id, scan_number FROM scan_metrics ORDER BY id"
    ).fetchall()
    conn.close()

    assert len(rows) == 3
    ids = [r[0] for r in rows]
    scan_numbers = [r[1] for r in rows]
    assert ids == [1, 2, 3], f"Expected distinct auto-ids [1,2,3], got {ids}"
    assert scan_numbers == [1, 2, 3], f"Expected scan_numbers [1,2,3], got {scan_numbers}"


def test_restart_simulation_no_unique_violation(tmp_db):
    """Two independent WatchLoop instances sharing DB do not collide on restart.

    Simulates watch-loop restart: loop_b starts with _scan_number=1 (default
    resets to 0, increments to 1 on first call) — same as loop_a's first scan.
    SQLite ROWID auto-generation ensures both get distinct ids with no IntegrityError.
    """
    loop_a = _make_watch_loop(tmp_db)
    loop_b = _make_watch_loop(tmp_db)

    with patch("src.scheduler.watch.DB_PATH", tmp_db):
        loop_a._record_scan_metrics()
        # loop_b simulates a restarted process: _scan_number will reset to 0
        # then increment to 1 on first call — same scan_number=1 as loop_a
        loop_b._record_scan_metrics()

    conn = sqlite3.connect(tmp_db)
    rows = conn.execute(
        "SELECT id, scan_number FROM scan_metrics ORDER BY id"
    ).fetchall()
    conn.close()

    assert len(rows) == 2, f"Expected 2 rows after restart simulation, got {len(rows)}"
    ids = [r[0] for r in rows]
    scan_numbers = [r[1] for r in rows]
    assert len(set(ids)) == 2, f"Expected distinct auto-ids, got {ids}"
    assert scan_numbers == [1, 1], f"Expected scan_numbers [1,1] (both restarted), got {scan_numbers}"


def test_id_not_null_after_insert(tmp_db):
    """After a single insert, the row id is auto-generated (NOT NULL and > 0)."""
    wl = _make_watch_loop(tmp_db)

    with patch("src.scheduler.watch.DB_PATH", tmp_db):
        wl._record_scan_metrics()

    conn = sqlite3.connect(tmp_db)
    row = conn.execute("SELECT id FROM scan_metrics").fetchone()
    conn.close()

    assert row is not None, "Expected one row in scan_metrics after insert"
    assert row[0] is not None, "Expected id to be NOT NULL"
    assert row[0] > 0, f"Expected id > 0, got {row[0]}"
