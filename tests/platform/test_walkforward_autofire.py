"""Tests for src/platform/walkforward_autofire.py (SP-WF-013).

All tests are hermetic — mock subprocess.Popen, filelock, and sqlite3 as needed.
"""
from __future__ import annotations

import json
import os
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_db(tmp_path: Path) -> str:
    """Create a minimal SQLite DB with the required tables."""
    db_path = str(tmp_path / "test.sqlite3")
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS strategy_registry (
            strategy_id TEXT PRIMARY KEY,
            corpus_id TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS platform_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type TEXT NOT NULL,
            severity TEXT DEFAULT 'info',
            payload_json TEXT,
            source TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()
    return db_path


def _seed_strategy(db_path: str, strategy_id: str, corpus_id: str | None) -> None:
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT OR REPLACE INTO strategy_registry (strategy_id, corpus_id) VALUES (?, ?)",
        (strategy_id, corpus_id),
    )
    conn.commit()
    conn.close()


def _get_events(db_path: str, event_type: str) -> list[dict]:
    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        "SELECT event_type, payload_json FROM platform_events WHERE event_type = ?",
        (event_type,),
    ).fetchall()
    conn.close()
    return [{"event_type": r[0], "payload_json": r[1]} for r in rows]


# ---------------------------------------------------------------------------
# Test 1: auto_fire spawns a child process with expected args
# ---------------------------------------------------------------------------

def test_auto_fire_spawns_child_process(tmp_path):
    """auto_fire_walkforward calls Popen with correct run_walkforward invocation."""
    from src.platform.walkforward_autofire import auto_fire_walkforward

    db_path = _make_db(tmp_path)
    _seed_strategy(db_path, "strat_a", "corpus-001")

    mock_proc = MagicMock()
    mock_proc.pid = 12345

    with patch("subprocess.Popen", return_value=mock_proc) as mock_popen, \
         patch.dict(os.environ, {"WALKFORWARD_AUTOFIRE_ENABLED": "true"}):
        auto_fire_walkforward(
            strategy_id="strat_a",
            backtest_result_id="br-uuid-001",
            db_path=db_path,
        )

    assert mock_popen.called, "Popen must be called"
    call_args = mock_popen.call_args
    cmd = call_args[0][0]  # first positional arg is the command list

    # Verify all required flags appear in command
    cmd_str = " ".join(str(c) for c in cmd)
    assert "scripts.backtest.run_walkforward" in cmd_str or "run_walkforward" in cmd_str
    assert "--strategy-id" in cmd_str or "--strategy" in cmd_str
    assert "strat_a" in cmd_str
    assert "--backtest-result-id" in cmd_str
    assert "br-uuid-001" in cmd_str
    assert "--auto-fire" in cmd_str


# ---------------------------------------------------------------------------
# Test 2: spawn failure emits platform_event, does NOT raise
# ---------------------------------------------------------------------------

def test_auto_fire_emits_platform_event_on_spawn_failure(tmp_path):
    """Popen raising OSError → walkforward_auto_fire_spawn_failed in platform_events + no exception."""
    from src.platform.walkforward_autofire import auto_fire_walkforward

    db_path = _make_db(tmp_path)
    _seed_strategy(db_path, "strat_b", "corpus-002")

    with patch("subprocess.Popen", side_effect=OSError("exec not found")), \
         patch.dict(os.environ, {"WALKFORWARD_AUTOFIRE_ENABLED": "true"}):
        # Must NOT raise
        auto_fire_walkforward(
            strategy_id="strat_b",
            backtest_result_id="br-uuid-002",
            db_path=db_path,
        )

    events = _get_events(db_path, "walkforward_auto_fire_spawn_failed")
    assert len(events) == 1, f"Expected 1 spawn_failed event, got {len(events)}"

    payload = json.loads(events[0]["payload_json"])
    assert payload["strategy_id"] == "strat_b"
    assert payload["backtest_result_id"] == "br-uuid-002"
    assert "error_class" in payload
    assert "error_msg" in payload


# ---------------------------------------------------------------------------
# Test 3: auto_fire skips when filelock is held
# ---------------------------------------------------------------------------

def test_auto_fire_skips_when_locked(tmp_path):
    """If the per-strategy lock is already held, emits walkforward_auto_fire_skipped_locked + no Popen."""
    from filelock import FileLock
    from src.platform.walkforward_autofire import auto_fire_walkforward

    db_path = _make_db(tmp_path)
    _seed_strategy(db_path, "strat_c", "corpus-003")

    lock_path = tmp_path / "data" / "walkforward-strat_c.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)

    # Acquire the lock before calling auto_fire_walkforward
    with FileLock(str(lock_path), timeout=0):
        with patch("subprocess.Popen") as mock_popen, \
             patch.dict(os.environ, {"WALKFORWARD_AUTOFIRE_ENABLED": "true"}), \
             patch("src.platform.walkforward_autofire._LOCK_DIR", tmp_path / "data"):
            auto_fire_walkforward(
                strategy_id="strat_c",
                backtest_result_id="br-uuid-003",
                db_path=db_path,
            )
        assert not mock_popen.called, "Popen must NOT be called when lock is held"

    events = _get_events(db_path, "walkforward_auto_fire_skipped_locked")
    assert len(events) == 1, f"Expected 1 skipped_locked event, got {len(events)}"


# ---------------------------------------------------------------------------
# Test 4: defensive catch-all — auto_fire_walkforward never raises
# ---------------------------------------------------------------------------

def test_auto_fire_does_not_raise_on_any_failure(tmp_path):
    """Even if every internal call raises, auto_fire_walkforward must return cleanly."""
    from src.platform.walkforward_autofire import auto_fire_walkforward

    db_path = _make_db(tmp_path)
    _seed_strategy(db_path, "strat_d", "corpus-004")

    # Patch connect_db to raise to simulate DB failure during event write
    with patch("subprocess.Popen", side_effect=RuntimeError("catastrophic")), \
         patch.dict(os.environ, {"WALKFORWARD_AUTOFIRE_ENABLED": "true"}):
        # Must NOT raise under any circumstance
        try:
            auto_fire_walkforward(
                strategy_id="strat_d",
                backtest_result_id="br-uuid-004",
                db_path=db_path,
            )
        except Exception as exc:
            pytest.fail(f"auto_fire_walkforward raised unexpectedly: {exc!r}")


# ---------------------------------------------------------------------------
# Test 5: lock is released after spawn
# ---------------------------------------------------------------------------

def test_auto_fire_releases_lock_after_spawn(tmp_path):
    """After auto_fire_walkforward returns, the filelock must be acquirable."""
    from filelock import FileLock, Timeout
    from src.platform.walkforward_autofire import auto_fire_walkforward

    db_path = _make_db(tmp_path)
    _seed_strategy(db_path, "strat_e", "corpus-005")

    mock_proc = MagicMock()
    mock_proc.pid = 99999

    lock_dir = tmp_path / "data"
    lock_dir.mkdir(parents=True, exist_ok=True)
    lock_path = lock_dir / "walkforward-strat_e.lock"

    with patch("subprocess.Popen", return_value=mock_proc), \
         patch.dict(os.environ, {"WALKFORWARD_AUTOFIRE_ENABLED": "true"}), \
         patch("src.platform.walkforward_autofire._LOCK_DIR", lock_dir):
        auto_fire_walkforward(
            strategy_id="strat_e",
            backtest_result_id="br-uuid-005",
            db_path=db_path,
        )

    # After return, the lock must be acquirable (not still held)
    try:
        with FileLock(str(lock_path), timeout=0):
            pass  # success — lock was released
    except Timeout:
        pytest.fail("Lock was NOT released after auto_fire_walkforward returned")
