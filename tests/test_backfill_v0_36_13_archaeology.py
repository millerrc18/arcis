"""Tests for scripts/backfill_v0.36.13_archaeology.py.

TDD — tests written BEFORE implementation. Uses sqlite3 in-memory DB as
an engine-agnostic stand-in for the Postgres target.

Five test cases per TEST_STRATEGY:
  1. test_dry_run_rolls_back
  2. test_commit_zeros_sentinel_durations
  3. test_cancel_rolls_back
  4. test_regime_backfill_skipped_when_no_table
  5. test_idempotent
"""

from __future__ import annotations

import importlib
import os
import sqlite3
import sys
import types
from unittest.mock import patch

import pytest

# Make the scripts package importable.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)


# ---------------------------------------------------------------------------
# Helpers to create/seed the sqlite in-memory schema
# ---------------------------------------------------------------------------

_DDL = """
CREATE TABLE IF NOT EXISTS shadow_trades (
    trade_id          TEXT PRIMARY KEY,
    ticker            TEXT NOT NULL,
    direction         TEXT NOT NULL DEFAULT 'long',
    status            TEXT NOT NULL DEFAULT 'open',
    exit_reason       TEXT,
    duration_days     REAL,
    actual_entry_time TEXT,
    regime_at_entry   TEXT,
    created_at        TEXT NOT NULL DEFAULT '2026-05-01T00:00:00',
    updated_at        TEXT NOT NULL DEFAULT '2026-05-01T00:00:00'
)
"""


def _make_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(_DDL)
    conn.commit()
    return conn


def _seed(conn: sqlite3.Connection, rows: list[dict]) -> None:
    for row in rows:
        conn.execute(
            "INSERT INTO shadow_trades "
            "(trade_id, ticker, direction, status, exit_reason, duration_days, "
            "actual_entry_time, regime_at_entry) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                row["trade_id"],
                row.get("ticker", "AAPL"),
                row.get("direction", "long"),
                row.get("status", "closed"),
                row.get("exit_reason"),
                row.get("duration_days"),
                row.get("actual_entry_time"),
                row.get("regime_at_entry"),
            ),
        )
    conn.commit()


def _standard_fixture(conn: sqlite3.Connection) -> None:
    """Seed the canonical fixture: 11 unknown+999, 3 manual+999, 49 reconciled_stale, 5 healthy."""
    rows = []
    # 11 'unknown' + duration_days=999 (sentinels to clean)
    for i in range(11):
        rows.append({
            "trade_id": f"unknown-{i}",
            "exit_reason": "unknown",
            "duration_days": 999,
            "actual_entry_time": "2026-05-05T12:09:43.107835",
        })
    # 3 'manual' + duration_days=999 (sentinels to clean)
    for i in range(3):
        rows.append({
            "trade_id": f"manual-{i}",
            "exit_reason": "manual",
            "duration_days": 999,
            "actual_entry_time": "2026-05-05T12:09:43.107835",
        })
    # 49 'reconciled_stale' with real durations 0-7d (must NOT be touched)
    for i in range(49):
        rows.append({
            "trade_id": f"stale-{i}",
            "exit_reason": "reconciled_stale",
            "duration_days": i % 8,  # 0–7
            "actual_entry_time": f"2026-04-{(i % 28) + 1:02d}T10:00:00",
        })
    # 5 healthy rows with real durations (must NOT be touched)
    for i in range(5):
        rows.append({
            "trade_id": f"healthy-{i}",
            "exit_reason": "target_1",
            "duration_days": i + 1,
            "actual_entry_time": "2026-04-15T09:30:00",
        })
    _seed(conn, rows)


# ---------------------------------------------------------------------------
# Load the script module in a test-friendly way.
# We inject the sqlite conn so the script does NOT open a real PG connection.
# ---------------------------------------------------------------------------

def _load_script():
    """Import (or reload) the archaeology script, returning its module."""
    spec = importlib.util.spec_from_file_location(
        "backfill_v0_36_13_archaeology",
        os.path.join(_REPO_ROOT, "scripts", "backfill_v0.36.13_archaeology.py"),
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# Test 1: --dry-run forces rollback; sentinel rows remain unchanged
# ---------------------------------------------------------------------------

def test_dry_run_rolls_back():
    conn = _make_conn()
    _standard_fixture(conn)

    mod = _load_script()
    rc = mod.main(["--dry-run"], conn=conn)

    assert rc == 0, f"Expected exit 0, got {rc}"

    # Sentinel rows must still have duration_days=999
    sentinel_rows = conn.execute(
        "SELECT COUNT(*) FROM shadow_trades "
        "WHERE exit_reason IN ('unknown', 'manual') AND duration_days = 999"
    ).fetchone()[0]
    assert sentinel_rows == 14, (
        f"Expected 14 sentinel rows still present, got {sentinel_rows}"
    )


# ---------------------------------------------------------------------------
# Test 2: COMMIT zeros sentinel durations; other rows untouched
# ---------------------------------------------------------------------------

def test_commit_zeros_sentinel_durations():
    conn = _make_conn()
    _standard_fixture(conn)

    mod = _load_script()
    with patch("builtins.input", return_value="COMMIT"):
        rc = mod.main([], conn=conn)

    assert rc == 0

    # Sentinel rows must have duration_days=NULL and actual_entry_time=NULL
    remaining = conn.execute(
        "SELECT COUNT(*) FROM shadow_trades "
        "WHERE exit_reason IN ('unknown', 'manual') AND duration_days = 999"
    ).fetchone()[0]
    assert remaining == 0, (
        f"Expected 0 sentinel rows with duration_days=999 after commit, got {remaining}"
    )

    # exit_reason='unknown' must NOT have been rewritten
    unknown_count = conn.execute(
        "SELECT COUNT(*) FROM shadow_trades WHERE exit_reason = 'unknown'"
    ).fetchone()[0]
    assert unknown_count == 11, (
        f"exit_reason='unknown' must not be rewritten; expected 11, got {unknown_count}"
    )

    # reconciled_stale rows must be untouched
    stale = conn.execute(
        "SELECT COUNT(*) FROM shadow_trades "
        "WHERE exit_reason = 'reconciled_stale' AND duration_days BETWEEN 0 AND 7"
    ).fetchone()[0]
    assert stale == 49, f"reconciled_stale rows should be untouched, got {stale}"

    # healthy rows must be untouched
    healthy = conn.execute(
        "SELECT COUNT(*) FROM shadow_trades "
        "WHERE exit_reason = 'target_1' AND duration_days BETWEEN 1 AND 5"
    ).fetchone()[0]
    assert healthy == 5, f"healthy rows should be untouched, got {healthy}"


# ---------------------------------------------------------------------------
# Test 3: Non-COMMIT input → rollback; DB unchanged
# ---------------------------------------------------------------------------

def test_cancel_rolls_back():
    conn = _make_conn()
    _standard_fixture(conn)

    mod = _load_script()
    with patch("builtins.input", return_value="no"):
        rc = mod.main([], conn=conn)

    assert rc == 0

    sentinel_rows = conn.execute(
        "SELECT COUNT(*) FROM shadow_trades "
        "WHERE exit_reason IN ('unknown', 'manual') AND duration_days = 999"
    ).fetchone()[0]
    assert sentinel_rows == 14, (
        f"Rollback expected; sentinel rows must remain 14, got {sentinel_rows}"
    )


# ---------------------------------------------------------------------------
# Test 4: No regime table → script doesn't raise; prints skip; UPDATEs commit
# ---------------------------------------------------------------------------

def test_regime_backfill_skipped_when_no_table(capsys):
    conn = _make_conn()
    _standard_fixture(conn)
    # No regime table created — script must tolerate absence gracefully.

    mod = _load_script()
    with patch("builtins.input", return_value="COMMIT"):
        rc = mod.main([], conn=conn)

    assert rc == 0

    captured = capsys.readouterr()
    assert "REGIME" in captured.out, (
        "Expected a [REGIME] skip message in stdout"
    )

    # Main updates must still have committed
    remaining = conn.execute(
        "SELECT COUNT(*) FROM shadow_trades "
        "WHERE exit_reason IN ('unknown', 'manual') AND duration_days = 999"
    ).fetchone()[0]
    assert remaining == 0


# ---------------------------------------------------------------------------
# Test 5: Idempotent — second run is a no-op and exits 0
# ---------------------------------------------------------------------------

def test_idempotent():
    conn = _make_conn()
    _standard_fixture(conn)

    mod = _load_script()

    with patch("builtins.input", return_value="COMMIT"):
        rc1 = mod.main([], conn=conn)
    assert rc1 == 0

    # Second run: no sentinel rows left, updates touch 0 rows
    with patch("builtins.input", return_value="COMMIT"):
        rc2 = mod.main([], conn=conn)
    assert rc2 == 0

    # Still 0 sentinel rows
    remaining = conn.execute(
        "SELECT COUNT(*) FROM shadow_trades "
        "WHERE exit_reason IN ('unknown', 'manual') AND duration_days = 999"
    ).fetchone()[0]
    assert remaining == 0
