"""Tests for WatchLoop._run_walkforward_reconciler (SP-WF-013).

All tests are hermetic — no real DB, no real subprocess, no network.
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from pathlib import Path
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_db(tmp_path: Path) -> str:
    """Create a minimal SQLite DB with backtest_results, walkforward_results,
    platform_events, and strategy_registry tables."""
    db_path = str(tmp_path / "reconciler_test.sqlite3")
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS strategy_registry (
            strategy_id TEXT PRIMARY KEY,
            corpus_id TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS backtest_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            result_id TEXT UNIQUE NOT NULL,
            strategy_id TEXT NOT NULL,
            code_git_sha TEXT DEFAULT 'unknown',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            provenance_kind TEXT NOT NULL CHECK (provenance_kind IN ('quick_in_sample', 'wf_is_window', 'wf_is_window_orphan_partial_run'))
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS walkforward_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT UNIQUE NOT NULL,
            strategy_id TEXT NOT NULL,
            derived_from_backtest_id TEXT
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


def _insert_backtest(db_path: str, strategy_id: str = "strat_x",
                     git_sha: str = "abc123") -> str:
    result_id = str(uuid.uuid4())
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO backtest_results (result_id, strategy_id, code_git_sha, created_at, provenance_kind) "
        "VALUES (?, ?, ?, datetime('now', '-1 day'), 'quick_in_sample')",
        (result_id, strategy_id, git_sha),
    )
    conn.commit()
    conn.close()
    return result_id


def _insert_walkforward(db_path: str, derived_from: str, strategy_id: str = "strat_x") -> None:
    run_id = str(uuid.uuid4())
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO walkforward_results (run_id, strategy_id, derived_from_backtest_id) "
        "VALUES (?, ?, ?)",
        (run_id, strategy_id, derived_from),
    )
    conn.commit()
    conn.close()


def _insert_platform_event(db_path: str, event_type: str,
                            strategy_id: str, git_sha: str) -> None:
    payload = json.dumps({"strategy_id": strategy_id, "code_git_sha": git_sha})
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO platform_events (event_type, payload_json, created_at) "
        "VALUES (?, ?, datetime('now', '-1 hour'))",
        (event_type, payload),
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
# Test 1: reconciler finds and fires auto_fire for orphan backtest
# ---------------------------------------------------------------------------

def test_reconciler_finds_orphan_backtest(tmp_path):
    """An orphan backtest_results row (no matching walkforward_results) triggers auto_fire."""
    db_path = _make_db(tmp_path)
    result_id = _insert_backtest(db_path, strategy_id="strat_orphan", git_sha="sha001")

    from src.scheduler.watch import WatchLoop

    config = {"automation": {}, "bootcamp": {}, "training": {}}
    watch = WatchLoop(config)

    with patch("src.platform.walkforward_autofire.auto_fire_walkforward") as mock_fire, \
         patch.object(watch, "_db_path", db_path, create=True):
        watch._run_walkforward_reconciler(db_path=db_path)

    assert mock_fire.called, "auto_fire_walkforward must be called for orphan backtest"
    kwargs = mock_fire.call_args[1] if mock_fire.call_args[1] else {}
    positional = mock_fire.call_args[0] if mock_fire.call_args[0] else ()
    # Accept either positional or keyword call
    called_strategy = kwargs.get("strategy_id") or (positional[0] if positional else None)
    called_backtest = kwargs.get("backtest_result_id") or (positional[1] if len(positional) > 1 else None)
    assert called_strategy == "strat_orphan"
    assert called_backtest == result_id


# ---------------------------------------------------------------------------
# Test 2: reconciler does NOT fire for a paired backtest
# ---------------------------------------------------------------------------

def test_reconciler_skips_paired_backtest(tmp_path):
    """A backtest with a matching walkforward_results row must NOT trigger auto_fire."""
    db_path = _make_db(tmp_path)
    result_id = _insert_backtest(db_path, strategy_id="strat_paired", git_sha="sha002")
    _insert_walkforward(db_path, derived_from=result_id, strategy_id="strat_paired")

    from src.scheduler.watch import WatchLoop

    config = {"automation": {}, "bootcamp": {}, "training": {}}
    watch = WatchLoop(config)

    with patch("src.platform.walkforward_autofire.auto_fire_walkforward") as mock_fire:
        watch._run_walkforward_reconciler(db_path=db_path)

    assert not mock_fire.called, "auto_fire must NOT be called for a paired backtest"


# ---------------------------------------------------------------------------
# Test 3: reconciler caps at 3 spawn_failed attempts within 24h
# ---------------------------------------------------------------------------

def test_reconciler_caps_at_three_attempts(tmp_path):
    """After 3 spawn_failed events for (strategy_id, code_git_sha) in 24h → giveup event, no fire."""
    db_path = _make_db(tmp_path)
    git_sha = "sha003"
    result_id = _insert_backtest(db_path, strategy_id="strat_cap", git_sha=git_sha)

    # Seed 3 spawn_failed events within 24h
    for _ in range(3):
        _insert_platform_event(
            db_path,
            "walkforward_auto_fire_spawn_failed",
            strategy_id="strat_cap",
            git_sha=git_sha,
        )

    from src.scheduler.watch import WatchLoop

    config = {"automation": {}, "bootcamp": {}, "training": {}}
    watch = WatchLoop(config)

    with patch("src.platform.walkforward_autofire.auto_fire_walkforward") as mock_fire:
        watch._run_walkforward_reconciler(db_path=db_path)

    assert not mock_fire.called, "auto_fire must NOT be called after 3 failed attempts"
    giveup_events = _get_events(db_path, "walkforward_auto_fire_giveup")
    assert len(giveup_events) >= 1, "Must emit walkforward_auto_fire_giveup event"


# ---------------------------------------------------------------------------
# Test DA-2: caps at three no_corpus attempts (IN-list covers all 3 event types)
# ---------------------------------------------------------------------------

def test_reconciler_caps_at_three_no_corpus_attempts(tmp_path):
    """After 3 skipped_no_corpus events for (strategy_id, code_git_sha) in 24h → giveup, no fire."""
    db_path = _make_db(tmp_path)
    git_sha = "sha004"
    result_id = _insert_backtest(db_path, strategy_id="strat_nocorpus", git_sha=git_sha)

    # Seed 3 skipped_no_corpus events within 24h
    for _ in range(3):
        _insert_platform_event(
            db_path,
            "walkforward_auto_fire_skipped_no_corpus",
            strategy_id="strat_nocorpus",
            git_sha=git_sha,
        )

    from src.scheduler.watch import WatchLoop

    config = {"automation": {}, "bootcamp": {}, "training": {}}
    watch = WatchLoop(config)

    with patch("src.platform.walkforward_autofire.auto_fire_walkforward") as mock_fire:
        watch._run_walkforward_reconciler(db_path=db_path)

    assert not mock_fire.called, "auto_fire must NOT be called after 3 no_corpus skips"
    giveup_events = _get_events(db_path, "walkforward_auto_fire_giveup")
    assert len(giveup_events) >= 1, "Must emit walkforward_auto_fire_giveup event"
