"""Schema tests for Sprint 3 Task 11b.1 — correlation tables.

Non-negotiable gate: correlation_matrices + factor_loadings declared
with sync_to_postgres=True, sync_mode='incremental'.
"""
import sqlite3

import pytest

from src.schema.registry import TABLES
from src.schema.sqlite import create_all_tables, ensure_columns


def test_correlation_matrices_registered():
    assert "correlation_matrices" in TABLES


def test_factor_loadings_registered():
    assert "factor_loadings" in TABLES


def test_correlation_matrices_sync_to_postgres_incremental():
    t = TABLES["correlation_matrices"]
    assert getattr(t, "sync_to_postgres", False) is True
    assert getattr(t, "sync_mode", None) == "incremental"
    assert getattr(t, "sync_time_column", None) == "date"


def test_factor_loadings_sync_to_postgres_incremental():
    t = TABLES["factor_loadings"]
    assert getattr(t, "sync_to_postgres", False) is True
    assert getattr(t, "sync_mode", None) == "incremental"
    assert getattr(t, "sync_time_column", None) == "date"


def test_correlation_matrices_has_expected_columns():
    cols = {c.name for c in TABLES["correlation_matrices"].columns}
    assert {
        "date", "method", "strategy_a", "strategy_b",
        "value", "window_days", "n_observations",
    }.issubset(cols)


def test_factor_loadings_has_expected_columns():
    cols = {c.name for c in TABLES["factor_loadings"].columns}
    assert {
        "date", "strategy_id", "factor",
        "beta", "tstat_hac", "r2",
        "window_days", "n_observations",
    }.issubset(cols)


def test_correlation_matrices_indexes_present():
    index_names = {i.name for i in TABLES["correlation_matrices"].indexes}
    assert "idx_corr_date" in index_names
    assert "idx_corr_pair" in index_names


def test_factor_loadings_index_present():
    index_names = {i.name for i in TABLES["factor_loadings"].indexes}
    assert "idx_factor_strategy_date" in index_names


def test_ensure_columns_creates_both_tables(tmp_path):
    """Migration on a fresh DB should create both tables."""
    db = tmp_path / "test.db"
    create_all_tables(str(db))
    conn = sqlite3.connect(db)
    tables = {
        row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    conn.close()
    assert "correlation_matrices" in tables
    assert "factor_loadings" in tables
