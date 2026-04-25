"""T1.01 — pre-#651 sweep script tests.

Tests scripts/quarantine_pre_651.py for:
  (1) Positive: pre-cutoff entry row gets quarantined=1
  (2) Negative: post-cutoff entry stays quarantined=0
  (3) Boundary: row exactly at 2026-04-22T20:00:00-04:00 is treated as pre-cutoff
  (4) In-flight: entry pre-cutoff but exit post-cutoff -> quarantine
  (5) Idempotency: re-run changes 0 rows
  (6) Integration: post-task SELECT returns zero unquarantined pre-cutoff rows
  (7) Batch sizing constant >=50 (per backfill memory pattern)
  (8) Defaults align with backfill memory pattern ('{}' not NULL via DEFAULT 0)
"""

from __future__ import annotations

import sqlite3

import pytest

from scripts.quarantine_pre_651 import (
    BATCH_SIZE,
    CUTOFF_ISO,
    apply_quarantine,
    find_quarantine_candidates,
)


def _create_minimal_schema(conn: sqlite3.Connection) -> None:
    """Faithful-but-minimal shadow_trades shape covering the columns this script uses."""
    conn.execute(
        """
        CREATE TABLE shadow_trades (
            trade_id TEXT PRIMARY KEY,
            recommendation_id TEXT,
            ticker TEXT,
            actual_entry_time TEXT,
            actual_exit_time TEXT,
            quarantined INTEGER DEFAULT 0
        )
        """
    )
    conn.commit()


def _seed(conn, **kwargs) -> None:
    cols = ",".join(kwargs.keys())
    placeholders = ",".join("?" * len(kwargs))
    conn.execute(
        f"INSERT INTO shadow_trades ({cols}) VALUES ({placeholders})",
        tuple(kwargs.values()),
    )


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    _create_minimal_schema(c)
    yield c
    c.close()


@pytest.fixture
def seeded_conn(conn):
    """Seed 10 pre-cutoff + 10 post-cutoff + 5 in-flight (entry pre, exit post)."""
    pre_iso = "2026-04-20T10:00:00-04:00"           # well before cutoff
    post_iso = "2026-04-23T10:00:00-04:00"          # well after cutoff
    inflight_entry = "2026-04-21T10:00:00-04:00"
    inflight_exit = "2026-04-24T10:00:00-04:00"

    for i in range(10):
        _seed(
            conn,
            trade_id=f"pre-{i}",
            recommendation_id=f"rec-pre-{i}",
            ticker="AAPL",
            actual_entry_time=pre_iso,
            actual_exit_time=pre_iso,
            quarantined=0,
        )
    for i in range(10):
        _seed(
            conn,
            trade_id=f"post-{i}",
            recommendation_id=f"rec-post-{i}",
            ticker="MSFT",
            actual_entry_time=post_iso,
            actual_exit_time=post_iso,
            quarantined=0,
        )
    for i in range(5):
        _seed(
            conn,
            trade_id=f"inflight-{i}",
            recommendation_id=f"rec-inflight-{i}",
            ticker="GOOG",
            actual_entry_time=inflight_entry,
            actual_exit_time=inflight_exit,
            quarantined=0,
        )
    conn.commit()
    return conn


def test_positive_pre_cutoff_row_quarantined(conn):
    _seed(
        conn,
        trade_id="t-pre",
        recommendation_id="r1",
        ticker="AAPL",
        actual_entry_time="2026-04-20T10:00:00-04:00",
        actual_exit_time="2026-04-20T15:00:00-04:00",
        quarantined=0,
    )
    conn.commit()

    candidates = find_quarantine_candidates(conn)
    assert candidates == ["t-pre"]

    updated = apply_quarantine(conn, ["t-pre"])
    assert updated == 1

    row = conn.execute(
        "SELECT quarantined FROM shadow_trades WHERE trade_id=?", ("t-pre",)
    ).fetchone()
    assert row["quarantined"] == 1


def test_negative_post_cutoff_row_unaffected(conn):
    _seed(
        conn,
        trade_id="t-post",
        recommendation_id="r1",
        ticker="AAPL",
        actual_entry_time="2026-04-23T10:00:00-04:00",
        actual_exit_time="2026-04-23T15:00:00-04:00",
        quarantined=0,
    )
    conn.commit()

    assert find_quarantine_candidates(conn) == []


def test_boundary_row_exactly_at_cutoff_is_pre(conn):
    """Row whose entry is *exactly* the cutoff timestamp must be treated as pre."""
    _seed(
        conn,
        trade_id="t-boundary",
        recommendation_id="r1",
        ticker="AAPL",
        actual_entry_time=CUTOFF_ISO,           # exactly the cutoff
        actual_exit_time=CUTOFF_ISO,
        quarantined=0,
    )
    conn.commit()

    candidates = find_quarantine_candidates(conn)
    assert candidates == ["t-boundary"]


def test_inflight_entry_pre_exit_post_is_quarantined(conn):
    _seed(
        conn,
        trade_id="t-inflight",
        recommendation_id="r1",
        ticker="AAPL",
        actual_entry_time="2026-04-21T10:00:00-04:00",
        actual_exit_time="2026-04-24T10:00:00-04:00",
        quarantined=0,
    )
    conn.commit()

    candidates = find_quarantine_candidates(conn)
    assert candidates == ["t-inflight"]


def test_idempotency_second_run_zero_changes(seeded_conn):
    candidates = find_quarantine_candidates(seeded_conn)
    apply_quarantine(seeded_conn, candidates)
    assert find_quarantine_candidates(seeded_conn) == []


def test_already_quarantined_pre_cutoff_skipped(conn):
    """Re-running on already-flagged rows must change zero rows (idempotent)."""
    _seed(
        conn,
        trade_id="t-already",
        recommendation_id="r1",
        ticker="AAPL",
        actual_entry_time="2026-04-20T10:00:00-04:00",
        actual_exit_time="2026-04-20T15:00:00-04:00",
        quarantined=1,
    )
    conn.commit()

    assert find_quarantine_candidates(conn) == []


def test_seeded_fixture_counts_correct(seeded_conn):
    """Sanity: 10 pre-cutoff + 5 in-flight = 15 candidates; 10 post-cutoff untouched."""
    candidates = find_quarantine_candidates(seeded_conn)
    assert len(candidates) == 15

    updated = apply_quarantine(seeded_conn, candidates)
    assert updated == 15

    pre_count = seeded_conn.execute(
        "SELECT COUNT(*) AS c FROM shadow_trades "
        "WHERE actual_entry_time <= ? AND COALESCE(quarantined, 0) = 1",
        (CUTOFF_ISO,),
    ).fetchone()["c"]
    assert pre_count == 15

    post_count = seeded_conn.execute(
        "SELECT COUNT(*) AS c FROM shadow_trades "
        "WHERE actual_entry_time > ? AND COALESCE(quarantined, 0) = 1",
        (CUTOFF_ISO,),
    ).fetchone()["c"]
    assert post_count == 0


def test_post_task_select_zero_unquarantined_pre_cutoff(seeded_conn):
    """Integration: after sweep, the assertion query returns zero residual candidates."""
    candidates = find_quarantine_candidates(seeded_conn)
    apply_quarantine(seeded_conn, candidates)

    residual = find_quarantine_candidates(seeded_conn)
    assert residual == []


def test_batch_size_constant_is_at_least_50():
    """Per backfill memory pattern: batch commits >=50 rows."""
    assert BATCH_SIZE >= 50


def test_large_batch_processes_all(conn):
    """Smoke test for batched UPDATE: seed >BATCH_SIZE candidates, verify all updated."""
    n = BATCH_SIZE + 7
    for i in range(n):
        _seed(
            conn,
            trade_id=f"t{i}",
            recommendation_id=f"r{i}",
            ticker="AAPL",
            actual_entry_time="2026-04-20T10:00:00-04:00",
            actual_exit_time="2026-04-20T15:00:00-04:00",
            quarantined=0,
        )
    conn.commit()

    candidates = find_quarantine_candidates(conn)
    assert len(candidates) == n

    updated = apply_quarantine(conn, candidates)
    assert updated == n
    assert find_quarantine_candidates(conn) == []


def test_null_entry_time_is_not_swept(conn):
    """Defensive: rows with NULL actual_entry_time (orphans) must not be quarantined.
    They have no provable pre-cutoff entry — manual triage required."""
    _seed(
        conn,
        trade_id="t-null",
        recommendation_id="r1",
        ticker="AAPL",
        actual_entry_time=None,
        actual_exit_time=None,
        quarantined=0,
    )
    conn.commit()

    assert find_quarantine_candidates(conn) == []


def test_cutoff_iso_matches_spec():
    """The CUTOFF_ISO constant must match the spec: 2026-04-22T20:00:00-04:00."""
    assert CUTOFF_ISO == "2026-04-22T20:00:00-04:00"
