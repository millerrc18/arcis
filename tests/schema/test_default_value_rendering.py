"""Tests for SQL-function-aware DEFAULT value rendering in schema DDL emitters.

Covers the fix for the bug where CURRENT_TIMESTAMP and other SQL function
defaults were being emitted quoted (e.g. DEFAULT 'CURRENT_TIMESTAMP') instead
of unquoted (DEFAULT CURRENT_TIMESTAMP), causing Postgres InvalidDatetimeFormat
errors at INSERT time and SQLite silently storing the literal string.
"""

import pytest

from src.schema.registry import ColumnDef, TableDef
from src.schema.postgres import generate_create_table_sql, generate_ensure_column_sql
from src.schema.sqlite import generate_create_sql, ensure_columns


def _make_table(col: ColumnDef) -> TableDef:
    """Build a minimal single-column TableDef around the provided column."""
    return TableDef(
        name="_test_default_rendering",
        description="Transient table for default-rendering tests",
        columns=[
            ColumnDef("id", "INTEGER", nullable=False),
            col,
        ],
        primary_key="id",
    )


# ── Postgres CREATE TABLE ─────────────────────────────────────────────────────

def test_postgres_create_table_emits_current_timestamp_unquoted():
    """CURRENT_TIMESTAMP default must appear UNQUOTED in Postgres CREATE TABLE."""
    table = _make_table(ColumnDef("created_at", "TIMESTAMP", default="CURRENT_TIMESTAMP"))
    sql = generate_create_table_sql(table)
    assert "DEFAULT CURRENT_TIMESTAMP" in sql, (
        f"Expected DEFAULT CURRENT_TIMESTAMP (unquoted) in:\n{sql}"
    )
    assert "DEFAULT 'CURRENT_TIMESTAMP'" not in sql, (
        f"Must NOT contain quoted DEFAULT 'CURRENT_TIMESTAMP' in:\n{sql}"
    )


def test_postgres_create_table_emits_string_default_quoted():
    """String literal defaults must remain QUOTED in Postgres CREATE TABLE."""
    table = _make_table(ColumnDef("source", "TEXT", default="unknown"))
    sql = generate_create_table_sql(table)
    assert "DEFAULT 'unknown'" in sql, (
        f"Expected DEFAULT 'unknown' (quoted) in:\n{sql}"
    )


# ── SQLite CREATE TABLE ───────────────────────────────────────────────────────

def test_sqlite_create_table_emits_current_timestamp_unquoted():
    """CURRENT_TIMESTAMP default must appear UNQUOTED in SQLite CREATE TABLE."""
    table = _make_table(ColumnDef("created_at", "TIMESTAMP", default="CURRENT_TIMESTAMP"))
    sql = generate_create_sql(table)
    assert "DEFAULT CURRENT_TIMESTAMP" in sql, (
        f"Expected DEFAULT CURRENT_TIMESTAMP (unquoted) in:\n{sql}"
    )
    assert "DEFAULT 'CURRENT_TIMESTAMP'" not in sql, (
        f"Must NOT contain quoted DEFAULT 'CURRENT_TIMESTAMP' in:\n{sql}"
    )


def test_sqlite_create_table_emits_string_default_quoted():
    """String literal defaults must remain QUOTED in SQLite CREATE TABLE."""
    table = _make_table(ColumnDef("source", "TEXT", default="unknown"))
    sql = generate_create_sql(table)
    assert "DEFAULT 'unknown'" in sql, (
        f"Expected DEFAULT 'unknown' (quoted) in:\n{sql}"
    )


# ── Postgres ALTER TABLE ADD COLUMN ──────────────────────────────────────────

def test_postgres_add_column_emits_current_timestamp_unquoted():
    """CURRENT_TIMESTAMP default must appear UNQUOTED in Postgres ALTER TABLE."""
    col = ColumnDef("created_at", "TIMESTAMP", default="CURRENT_TIMESTAMP")
    sql = generate_ensure_column_sql("_test_table", col)
    assert "DEFAULT CURRENT_TIMESTAMP" in sql, (
        f"Expected DEFAULT CURRENT_TIMESTAMP (unquoted) in:\n{sql}"
    )
    assert "DEFAULT 'CURRENT_TIMESTAMP'" not in sql, (
        f"Must NOT contain quoted DEFAULT 'CURRENT_TIMESTAMP' in:\n{sql}"
    )


# ── SQLite ALTER TABLE ADD COLUMN ─────────────────────────────────────────────

def test_sqlite_add_column_emits_current_timestamp_unquoted():
    """CURRENT_TIMESTAMP default must appear UNQUOTED in SQLite ALTER TABLE ADD COLUMN."""
    import sqlite3
    from src.schema.sqlite import _format_default

    result = _format_default("CURRENT_TIMESTAMP")
    assert result == "CURRENT_TIMESTAMP", (
        f"_format_default('CURRENT_TIMESTAMP') should return 'CURRENT_TIMESTAMP' unquoted, got: {result!r}"
    )
    result_str = _format_default("unknown")
    assert result_str == "'unknown'", (
        f"_format_default('unknown') should return \"'unknown'\" quoted, got: {result_str!r}"
    )
