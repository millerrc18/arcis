"""Schema tests for the walk-forward validation framework (R7 + R3).

Verifies that the three new tables — walkforward_results, walkforward_trades,
sp100_historical_constituents — are registered, have the columns the rest of
the framework depends on, and survive round-trip DDL creation under SQLite.
"""
from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

import pytest

from src.schema.registry import TABLES
from src.schema.sqlite import create_all_tables


REQUIRED_WF_RESULTS_COLUMNS = {
    "run_id", "strategy_id", "spec_hash", "code_git_sha", "random_seed",
    "config_json", "outcome_state", "reason", "pooled_sharpe", "pooled_mde",
    "heavy_tail_flag", "n_windows", "n_windows_pass", "n_windows_fail",
    "n_windows_inconclusive_data", "n_windows_inconclusive_power",
    "derived_from_source_type", "derived_from_source_run_id",
    "effective_universe_size", "max_drawdown_pct", "vix_tier_coverage",
    "created_at",
}

REQUIRED_WF_TRADES_COLUMNS = {
    "trade_id", "run_id", "window_index", "is_in_is_window", "ticker",
    "entry_date", "exit_date", "pnl_pct", "excess_return", "exit_reason",
    "hold_days", "vix_at_entry", "vix_tier", "purged", "embargoed",
    "sharpe_observed", "bootstrap_se", "mde_value",
}

REQUIRED_SP100_HIST_COLUMNS = {
    "ticker", "added_date", "removed_date", "company_name", "reason",
}


def test_walkforward_results_table_registered():
    assert "walkforward_results" in TABLES
    cols = {c.name for c in TABLES["walkforward_results"].columns}
    missing = REQUIRED_WF_RESULTS_COLUMNS - cols
    assert not missing, f"walkforward_results missing columns: {missing}"


def test_walkforward_trades_table_registered():
    assert "walkforward_trades" in TABLES
    cols = {c.name for c in TABLES["walkforward_trades"].columns}
    missing = REQUIRED_WF_TRADES_COLUMNS - cols
    assert not missing, f"walkforward_trades missing columns: {missing}"


def test_sp100_historical_constituents_table_registered():
    assert "sp100_historical_constituents" in TABLES
    cols = {c.name for c in TABLES["sp100_historical_constituents"].columns}
    missing = REQUIRED_SP100_HIST_COLUMNS - cols
    assert not missing, f"sp100_historical_constituents missing columns: {missing}"


def test_outcome_state_column_nullable_is_false():
    """Outcome state must be non-null — a walk-forward row without an outcome is
    a data integrity bug that would break the three-state promotion gate."""
    col = next(
        c for c in TABLES["walkforward_results"].columns
        if c.name == "outcome_state"
    )
    assert col.nullable is False


def test_derived_from_columns_nullable():
    """R8: derived_from_source_type can be NULL (organic / literature strategies)."""
    col = next(
        c for c in TABLES["walkforward_results"].columns
        if c.name == "derived_from_source_type"
    )
    assert col.nullable is True


def test_walkforward_tables_create_in_sqlite(tmp_path):
    """End-to-end: the three tables can be created in SQLite via the registry."""
    db = tmp_path / "wf_schema.sqlite3"
    create_all_tables(str(db))
    conn = sqlite3.connect(db)
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' "
        "AND name IN (?, ?, ?)",
        ("walkforward_results", "walkforward_trades",
         "sp100_historical_constituents"),
    ).fetchall()
    conn.close()
    created = {r[0] for r in rows}
    assert created == {
        "walkforward_results", "walkforward_trades",
        "sp100_historical_constituents",
    }


def test_walkforward_tables_round_trip_insert(tmp_path):
    """Insert a synthetic row into each table to verify column order + types."""
    db = tmp_path / "wf_roundtrip.sqlite3"
    create_all_tables(str(db))
    conn = sqlite3.connect(db)
    try:
        conn.execute(
            "INSERT INTO walkforward_results "
            "(run_id, strategy_id, spec_hash, random_seed, outcome_state, "
            "n_windows, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("r1", "lazy_prices_v1", "deadbeef", 42, "INCONCLUSIVE", 5,
             "2024-01-01T00:00:00"),
        )
        conn.execute(
            "INSERT INTO walkforward_trades "
            "(trade_id, run_id, window_index, ticker, entry_date) "
            "VALUES (?, ?, ?, ?, ?)",
            ("t1", "r1", 0, "AAPL", "2024-01-02"),
        )
        conn.execute(
            "INSERT INTO sp100_historical_constituents "
            "(ticker, added_date) VALUES (?, ?)",
            ("AAPL", "2019-01-01"),
        )
        conn.commit()
        r = conn.execute(
            "SELECT outcome_state FROM walkforward_results WHERE run_id = ?",
            ("r1",),
        ).fetchone()
        assert r[0] == "INCONCLUSIVE"
    finally:
        conn.close()


def test_sp100_historical_primary_key_is_composite():
    """(ticker, added_date) is the PK — a ticker can be added more than once."""
    pk = TABLES["sp100_historical_constituents"].primary_key
    assert pk == ["ticker", "added_date"]


def test_walkforward_results_indexes_present():
    idx_names = {i.name for i in TABLES["walkforward_results"].indexes}
    assert "idx_wf_strategy_created" in idx_names
    assert "idx_wf_outcome" in idx_names
