"""Tests for diagnostic_runs stale-job watchdog (#56).

Covers sweep_stale_diagnostic_runs() in src/scheduler/watch.py:
  - Transitions old queued rows to 'failed'
  - Transitions old running rows to 'failed'
  - Returns 0 when there are no stale rows
  - Is idempotent (second call returns 0)
"""

import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from tests.conftest import init_test_db


@pytest.fixture
def db_path(tmp_path):
    path = str(tmp_path / "test.db")
    init_test_db(path, ["diagnostic_runs"])
    return path


def _insert_run(db_path: str, run_id: str, status: str, created_at: datetime) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """INSERT INTO diagnostic_runs
               (run_id, diagnostic_type, status, trigger_source, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                run_id,
                "regime",
                status,
                "dashboard",
                created_at.isoformat(),
                created_at.isoformat(),
            ),
        )
        conn.commit()


def _get_row(db_path: str, run_id: str) -> dict:
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM diagnostic_runs WHERE run_id = ?", (run_id,)
        ).fetchone()
    return dict(row) if row else {}


def test_sweep_stale_marks_old_queued_runs(db_path):
    from src.scheduler.watch import sweep_stale_diagnostic_runs

    now = datetime.now(timezone.utc)
    old_time = now - timedelta(hours=25)
    fresh_time = now - timedelta(hours=1)

    _insert_run(db_path, "old-queued", "queued", old_time)
    _insert_run(db_path, "fresh-queued", "queued", fresh_time)

    count = sweep_stale_diagnostic_runs(db_path, stale_after_hours=24)

    assert count == 1, f"Expected 1 transitioned row, got {count}"

    old_row = _get_row(db_path, "old-queued")
    assert old_row["status"] == "failed", f"Expected 'failed', got {old_row['status']}"
    assert old_row["completed_at"] is not None
    assert "Watchdog" in (old_row["stderr_tail"] or ""), "Expected watchdog message in stderr_tail"

    fresh_row = _get_row(db_path, "fresh-queued")
    assert fresh_row["status"] == "queued", "Fresh row should remain queued"


def test_sweep_stale_marks_old_running_runs(db_path):
    from src.scheduler.watch import sweep_stale_diagnostic_runs

    now = datetime.now(timezone.utc)
    old_time = now - timedelta(hours=26)
    fresh_time = now - timedelta(hours=2)

    _insert_run(db_path, "old-running", "running", old_time)
    _insert_run(db_path, "fresh-running", "running", fresh_time)

    count = sweep_stale_diagnostic_runs(db_path, stale_after_hours=24)

    assert count == 1, f"Expected 1 transitioned row, got {count}"

    old_row = _get_row(db_path, "old-running")
    assert old_row["status"] == "failed", f"Expected 'failed', got {old_row['status']}"
    assert old_row["completed_at"] is not None
    assert "Watchdog" in (old_row["stderr_tail"] or "")

    fresh_row = _get_row(db_path, "fresh-running")
    assert fresh_row["status"] == "running", "Fresh row should remain running"


def test_sweep_stale_zero_when_clean(db_path):
    from src.scheduler.watch import sweep_stale_diagnostic_runs

    now = datetime.now(timezone.utc)
    fresh_time = now - timedelta(hours=1)

    _insert_run(db_path, "fresh-1", "queued", fresh_time)
    _insert_run(db_path, "fresh-2", "running", fresh_time)

    count = sweep_stale_diagnostic_runs(db_path, stale_after_hours=24)
    assert count == 0, f"Expected 0 transitions on clean DB, got {count}"


def test_sweep_stale_idempotent(db_path):
    from src.scheduler.watch import sweep_stale_diagnostic_runs

    now = datetime.now(timezone.utc)
    old_time = now - timedelta(hours=30)

    _insert_run(db_path, "old-run", "queued", old_time)

    first = sweep_stale_diagnostic_runs(db_path, stale_after_hours=24)
    assert first == 1

    second = sweep_stale_diagnostic_runs(db_path, stale_after_hours=24)
    assert second == 0, f"Second sweep should return 0, got {second}"

    row = _get_row(db_path, "old-run")
    assert row["status"] == "failed"
