"""Tests for the pollution-cleanup operator script (#650).

The cleanup script removes historical kill_switch_halt and kill_switch_resume
rows that were written to the prod activity_log via the test pollution leak
fixed in #647. Three safety properties under test:

  1. The script's signature matcher only deletes rows that match KNOWN test
     fixture signatures — never real production rows.
  2. Default mode is --dry-run; --apply must be explicit.
  3. The cutoff timestamp filter prevents deletion of any rows created
     after the #647 fix landed (so post-fix legitimate halts are preserved).
"""
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "cleanup_test_pollution_647.py"


def _make_test_db(tmp_path):
    """Create an activity_log table with a mix of pollution + real rows."""
    db_path = tmp_path / "test_activity.sqlite3"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "CREATE TABLE activity_log ("
            "id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT, "
            "event_type TEXT NOT NULL, "
            "detail TEXT, "
            "created_at TEXT NOT NULL"
            ")"
        )
        rows = [
            # Pollution signatures (must be deleted)
            ("kill_switch_halt", "source=unknown, reason=", "2026-04-15T10:00:00"),
            ("kill_switch_halt", "source=test, reason=unit test", "2026-04-15T10:01:00"),
            ("kill_switch_halt", "source=test, reason=", "2026-04-15T10:02:00"),
            ("kill_switch_halt", "source=telegram, reason=manual halt", "2026-04-15T10:03:00"),
            ("kill_switch_halt", "source=auditor, reason=Halt command ignored", "2026-04-15T10:04:00"),
            ("kill_switch_halt", "source=auditor, reason=Governor check bypassed", "2026-04-15T10:05:00"),
            ("kill_switch_halt", "source=auditor, reason=Catastrophic loss detected", "2026-04-15T10:06:00"),
            ("kill_switch_resume", "source=unknown, reason=", "2026-04-15T10:07:00"),

            # Real production rows (must NOT be deleted)
            ("kill_switch_halt", "source=cli, reason=manual halt via halt-trading command", "2026-04-15T11:00:00"),
            ("trade_opened", "ticker=AAPL", "2026-04-15T12:00:00"),
            ("scan_complete", "scanned=50", "2026-04-15T13:00:00"),

            # Post-cutoff row (legitimate test signature but after fix landed)
            ("kill_switch_halt", "source=test, reason=", "2026-04-25T10:00:00"),
        ]
        for r in rows:
            conn.execute(
                "INSERT INTO activity_log (event_type, detail, created_at) VALUES (?, ?, ?)",
                r,
            )
        conn.commit()
    return db_path


def _run_script(*args, db_path=None):
    """Invoke the cleanup script as a subprocess so it tests the real CLI."""
    cmd = [sys.executable, str(SCRIPT)]
    if db_path:
        cmd.extend(["--db-path", str(db_path)])
    cmd.extend(args)
    return subprocess.run(cmd, capture_output=True, text=True, timeout=30)


def _count_all(db_path):
    with sqlite3.connect(db_path) as conn:
        return conn.execute("SELECT COUNT(*) FROM activity_log").fetchone()[0]


def test_dry_run_is_default(tmp_path):
    """No flag => dry run, no rows deleted."""
    db_path = _make_test_db(tmp_path)
    before = _count_all(db_path)
    result = _run_script(db_path=db_path)
    after = _count_all(db_path)
    assert before == after, "dry-run must not delete rows"
    assert result.returncode == 0
    assert "DRY RUN" in result.stdout


def test_apply_deletes_pollution_only(tmp_path):
    """--apply removes pollution signatures, preserves real rows."""
    db_path = _make_test_db(tmp_path)
    result = _run_script("--apply", "--cutoff", "2026-04-24T00:00:00", db_path=db_path)
    assert result.returncode == 0, result.stderr

    with sqlite3.connect(db_path) as conn:
        # 7 pollution kill_switch_halt rows pre-cutoff should be gone
        polluted_remaining = conn.execute(
            "SELECT COUNT(*) FROM activity_log WHERE event_type='kill_switch_halt' "
            "AND detail IN ('source=unknown, reason=', 'source=test, reason=unit test', "
            "'source=test, reason=', 'source=telegram, reason=manual halt', "
            "'source=auditor, reason=Halt command ignored', "
            "'source=auditor, reason=Governor check bypassed', "
            "'source=auditor, reason=Catastrophic loss detected') "
            "AND created_at < '2026-04-24T00:00:00'"
        ).fetchone()[0]
        assert polluted_remaining == 0

        # Real production row preserved
        real_halt = conn.execute(
            "SELECT COUNT(*) FROM activity_log WHERE detail LIKE 'source=cli%'"
        ).fetchone()[0]
        assert real_halt == 1

        # Non-kill_switch events untouched
        other = conn.execute(
            "SELECT COUNT(*) FROM activity_log WHERE event_type IN ('trade_opened','scan_complete')"
        ).fetchone()[0]
        assert other == 2

        # Post-cutoff pollution-shaped row preserved (cutoff filter works)
        post_cutoff = conn.execute(
            "SELECT COUNT(*) FROM activity_log WHERE created_at >= '2026-04-24T00:00:00'"
        ).fetchone()[0]
        assert post_cutoff == 1


def test_unknown_signature_never_deleted(tmp_path):
    """A halt with a NEW source string we haven't whitelisted must survive."""
    db_path = _make_test_db(tmp_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO activity_log (event_type, detail, created_at) VALUES "
            "('kill_switch_halt', 'source=newfeature, reason=novel reason', '2026-04-20T10:00:00')"
        )
        conn.commit()

    _run_script("--apply", "--cutoff", "2026-04-24T00:00:00", db_path=db_path)

    with sqlite3.connect(db_path) as conn:
        novel = conn.execute(
            "SELECT COUNT(*) FROM activity_log WHERE detail LIKE 'source=newfeature%'"
        ).fetchone()[0]
    assert novel == 1, "Unknown signature must NEVER be deleted (deny-by-default)"
