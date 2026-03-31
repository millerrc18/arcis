"""Tests for scripts/migrate_production_db.py — Sprint 4E Task 1."""

import sqlite3
import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def tmp_db(tmp_path):
    """Create a minimal DB with base tables but missing the new columns."""
    db_path = str(tmp_path / "test.sqlite3")
    conn = sqlite3.connect(db_path)
    conn.execute("""CREATE TABLE shadow_trades (
        trade_id TEXT PRIMARY KEY, ticker TEXT, status TEXT,
        pnl_pct REAL, pnl_dollars REAL, signal_price REAL,
        fill_price REAL, implementation_shortfall_bps REAL,
        exit_reason TEXT, actual_entry_time TEXT, actual_exit_time TEXT,
        planned_allocation REAL, direction TEXT, created_at TEXT)""")
    conn.execute("""CREATE TABLE training_examples (
        id INTEGER PRIMARY KEY, example_id TEXT UNIQUE, ticker TEXT,
        trade_date TEXT, input_text TEXT, output_text TEXT,
        quality_score REAL, curriculum_stage TEXT, outcome TEXT,
        source TEXT, model_version TEXT, created_at TEXT)""")
    conn.execute("""CREATE TABLE activity_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT, event_type TEXT,
        detail TEXT, created_at TEXT)""")
    # Insert sample data
    conn.execute("INSERT INTO shadow_trades (trade_id, ticker, status) VALUES ('t1', 'AAPL', 'open')")
    conn.execute("INSERT INTO training_examples (example_id, ticker) VALUES ('ex1', 'MSFT')")
    conn.execute("INSERT INTO activity_log (event_type, detail) VALUES ('scan', 'test')")
    conn.commit()
    conn.close()
    return db_path


def _run_migration(db_path: str):
    """Run the migration script against a DB path."""
    import importlib.util
    import sys
    spec = importlib.util.spec_from_file_location(
        "migrate", str(Path(__file__).resolve().parent.parent / "scripts" / "migrate_production_db.py"))
    mod = importlib.util.module_from_spec(spec)
    # Patch sys.argv so the script uses our DB path
    old_argv = sys.argv
    sys.argv = ["migrate_production_db.py", db_path]
    try:
        spec.loader.exec_module(mod)
        mod.main()
    finally:
        sys.argv = old_argv


def test_migration_adds_missing_columns(tmp_db):
    """Migration adds strategy_type, outcome_type, regime, and level columns."""
    _run_migration(tmp_db)
    conn = sqlite3.connect(tmp_db)
    shadow_cols = [r[1] for r in conn.execute("PRAGMA table_info(shadow_trades)").fetchall()]
    assert "strategy_type" in shadow_cols

    te_cols = [r[1] for r in conn.execute("PRAGMA table_info(training_examples)").fetchall()]
    assert "outcome_type" in te_cols
    assert "regime" in te_cols

    al_cols = [r[1] for r in conn.execute("PRAGMA table_info(activity_log)").fetchall()]
    assert "level" in al_cols
    conn.close()


def test_migration_is_idempotent(tmp_db):
    """Running migration twice should not error or duplicate columns."""
    _run_migration(tmp_db)
    _run_migration(tmp_db)  # Second run should be a no-op

    conn = sqlite3.connect(tmp_db)
    shadow_cols = [r[1] for r in conn.execute("PRAGMA table_info(shadow_trades)").fetchall()]
    # strategy_type should appear exactly once
    assert shadow_cols.count("strategy_type") == 1
    conn.close()


def test_migration_preserves_existing_data(tmp_db):
    """Migration should not drop or modify existing rows."""
    _run_migration(tmp_db)
    conn = sqlite3.connect(tmp_db)
    trade = conn.execute("SELECT ticker, status FROM shadow_trades WHERE trade_id='t1'").fetchone()
    assert trade == ("AAPL", "open")

    example = conn.execute("SELECT ticker FROM training_examples WHERE example_id='ex1'").fetchone()
    assert example[0] == "MSFT"

    log = conn.execute("SELECT event_type FROM activity_log WHERE detail='test'").fetchone()
    assert log[0] == "scan"
    conn.close()


def test_migration_creates_missing_tables(tmp_db):
    """Migration creates tables that don't exist yet (e.g. build_score_history)."""
    _run_migration(tmp_db)
    conn = sqlite3.connect(tmp_db)
    tables = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()]
    assert "build_score_history" in tables
    assert "pending_commands" in tables
    assert "command_results" in tables
    assert "config_overrides" in tables
    assert "log_entries" in tables
    conn.close()
