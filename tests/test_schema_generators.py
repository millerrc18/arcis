"""Tests for schema-driven SQL generation."""

import sqlite3

import pytest

from src.schema.registry import TABLES, TableDef, ColumnDef, IndexDef


@pytest.fixture
def tmp_db(tmp_path):
    """Return path to a temp SQLite database."""
    return str(tmp_path / "test.sqlite3")


# ── SQLite generator tests ────────────────────────────────────────

from src.schema.sqlite import generate_create_sql, create_all_tables, ensure_columns


def test_generate_create_sql_basic():
    table = TableDef(
        name="test_basic",
        description="Test",
        columns=[
            ColumnDef("id", "INTEGER", nullable=False),
            ColumnDef("name", "TEXT"),
        ],
        primary_key="id",
    )
    sql = generate_create_sql(table)
    assert "CREATE TABLE IF NOT EXISTS test_basic" in sql
    # Single INTEGER PK uses inline PRIMARY KEY (ROWID alias for SQLite)
    assert "id INTEGER NOT NULL PRIMARY KEY" in sql
    assert "name TEXT" in sql


def test_generate_create_sql_with_default():
    table = TableDef(
        name="test_defaults",
        description="Test",
        columns=[
            ColumnDef("id", "INTEGER", nullable=False),
            ColumnDef("source", "TEXT", default="paper"),
        ],
        primary_key="id",
    )
    sql = generate_create_sql(table)
    assert "DEFAULT 'paper'" in sql


def test_generate_create_sql_with_index():
    table = TableDef(
        name="test_indexed",
        description="Test",
        columns=[
            ColumnDef("id", "INTEGER", nullable=False),
            ColumnDef("ticker", "TEXT"),
        ],
        primary_key="id",
        indexes=[IndexDef("idx_test_ticker", ["ticker"])],
    )
    sql = generate_create_sql(table)
    assert "CREATE INDEX IF NOT EXISTS idx_test_ticker ON test_indexed(ticker)" in sql


def test_create_all_tables_creates_tables(tmp_db):
    create_all_tables(tmp_db)
    conn = sqlite3.connect(tmp_db)
    tables = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    conn.close()
    for name in TABLES:
        assert name in tables, f"Table {name} not created"


def test_create_all_tables_is_idempotent(tmp_db):
    create_all_tables(tmp_db)
    create_all_tables(tmp_db)  # Should not raise


def test_ensure_columns_adds_missing(tmp_db):
    from src.schema.registry import _register

    # Create a table manually with one column
    conn = sqlite3.connect(tmp_db)
    conn.execute("CREATE TABLE _test_ensure (id INTEGER PRIMARY KEY)")
    conn.close()

    # Register a table with an extra column
    _register(
        TableDef(
            name="_test_ensure",
            description="Test",
            columns=[
                ColumnDef("id", "INTEGER", nullable=False),
                ColumnDef("new_col", "TEXT"),
            ],
            primary_key="id",
        )
    )
    added = ensure_columns(tmp_db)
    assert "_test_ensure.new_col" in added

    # Verify column exists
    conn = sqlite3.connect(tmp_db)
    cols = [row[1] for row in conn.execute("PRAGMA table_info(_test_ensure)").fetchall()]
    conn.close()
    assert "new_col" in cols

    # Cleanup
    del TABLES["_test_ensure"]


def test_ensure_columns_is_idempotent(tmp_db):
    create_all_tables(tmp_db)
    ensure_columns(tmp_db)
    added2 = ensure_columns(tmp_db)
    assert added2 == [], "Second run should add nothing"


# ── Postgres generator tests ─────────────────────────────────────

from src.schema.postgres import (
    generate_create_sql as pg_create_sql,
    generate_ensure_column_sql,
)


def test_postgres_create_sql_basic():
    table = TableDef(
        name="test_pg",
        description="Test",
        columns=[
            ColumnDef("id", "INTEGER", nullable=False),
            ColumnDef("name", "TEXT"),
        ],
        primary_key="id",
    )
    sql = pg_create_sql(table)
    assert "CREATE TABLE IF NOT EXISTS test_pg" in sql
    assert "SERIAL" in sql  # INTEGER PK becomes SERIAL


def test_postgres_ensure_column_sql():
    sql = generate_ensure_column_sql(
        "my_table", ColumnDef("new_col", "TEXT", default="foo")
    )
    assert "ALTER TABLE my_table ADD COLUMN" in sql
    assert "new_col" in sql
    assert "DO $$" in sql  # PL/pgSQL idempotent wrapper


# ── Sync config generator tests ──────────────────────────────────

from src.schema.sync_config import generate_sync_tables


def test_generate_sync_tables_includes_synced():
    config = generate_sync_tables()
    for name, table in TABLES.items():
        if table.sync_to_postgres:
            assert name in config, f"Synced table {name} missing from generated config"


def test_generate_sync_tables_excludes_non_synced():
    config = generate_sync_tables()
    for name, table in TABLES.items():
        if not table.sync_to_postgres:
            assert name not in config, f"Non-synced table {name} in config"


def test_sync_config_has_required_keys():
    # Tables that sync incrementally via FK relationship (no time column)
    FK_SYNCED = {"council_votes"}

    config = generate_sync_tables()
    for name, entry in config.items():
        assert "mode" in entry, f"{name} missing 'mode'"
        assert "pk" in entry, f"{name} missing 'pk'"
        if entry["mode"] in ("incremental", "latest_only") and name not in FK_SYNCED:
            assert "time_col" in entry, f"{name} (mode={entry['mode']}) missing 'time_col'"


def test_generate_sync_tables_exposes_sync_reconcile():
    """generate_sync_tables() output must include sync_reconcile in every entry (#73)."""
    config = generate_sync_tables()
    assert len(config) > 0, "generate_sync_tables returned empty config"
    sample_name, sample_entry = next(iter(config.items()))
    assert "sync_reconcile" in sample_entry, (
        f"Entry for '{sample_name}' missing 'sync_reconcile' key"
    )
    for name, entry in config.items():
        assert "sync_reconcile" in entry, f"Entry for '{name}' missing 'sync_reconcile' key"


# ── #798 — scan_metrics UNIQUE constraint runtime test ────────────

def test_scan_metrics_created_at_unique_constraint_raises_on_duplicate(tmp_db):
    """Duplicate created_at insert must raise IntegrityError.

    scan_number/scan_time pairs may recur across days, but created_at is the
    stable per-row identity for retained scan history.
    """
    create_all_tables(tmp_db)
    conn = sqlite3.connect(tmp_db)
    conn.execute(
        "INSERT INTO scan_metrics "
        "(id, scan_number, scan_time, universe_count, features_count, "
        "scored_count, packet_worthy, risk_passed, paper_traded, "
        "live_traded, llm_success, llm_total, llm_fallback, "
        "avg_conviction, duration_seconds, created_at) "
        "VALUES (1, 1, '10:00', 100, 95, 90, 5, 4, 3, 0, 4, 5, 0, 0.75, 12.5, '2026-01-01T10:00:00')"
    )
    conn.commit()
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO scan_metrics "
            "(id, scan_number, scan_time, universe_count, features_count, "
            "scored_count, packet_worthy, risk_passed, paper_traded, "
            "live_traded, llm_success, llm_total, llm_fallback, "
            "avg_conviction, duration_seconds, created_at) "
            "VALUES (2, 1, '10:00', 100, 95, 90, 5, 4, 3, 0, 4, 5, 0, 0.75, 12.5, '2026-01-01T10:00:00')"
        )
    conn.close()


def test_scan_metrics_allows_repeated_scan_number_and_time_on_different_timestamps(tmp_db):
    """Repeated scan slots on different days must remain valid retained history."""
    create_all_tables(tmp_db)
    conn = sqlite3.connect(tmp_db)
    conn.execute(
        "INSERT INTO scan_metrics "
        "(id, scan_number, scan_time, universe_count, features_count, "
        "scored_count, packet_worthy, risk_passed, paper_traded, "
        "live_traded, llm_success, llm_total, llm_fallback, "
        "avg_conviction, duration_seconds, created_at) "
        "VALUES (1, 22, '14:49', 100, 95, 90, 5, 4, 3, 0, 4, 5, 0, 0.75, 12.5, '2026-04-17T14:49:33')"
    )
    conn.execute(
        "INSERT INTO scan_metrics "
        "(id, scan_number, scan_time, universe_count, features_count, "
        "scored_count, packet_worthy, risk_passed, paper_traded, "
        "live_traded, llm_success, llm_total, llm_fallback, "
        "avg_conviction, duration_seconds, created_at) "
        "VALUES (2, 22, '14:49', 100, 95, 90, 5, 4, 3, 0, 4, 5, 0, 0.75, 12.5, '2026-04-28T14:49:39')"
    )
    conn.commit()
    count = conn.execute("SELECT COUNT(*) FROM scan_metrics").fetchone()[0]
    conn.close()
    assert count == 2


# ── Validator tests ──────────────────────────────────────────────

from src.schema.validator import validate_sqlite, SchemaIssue, validate_codebase


def test_validate_sqlite_clean_db(tmp_db):
    """A DB created from the registry should have zero issues."""
    create_all_tables(tmp_db)
    issues = validate_sqlite(tmp_db)
    assert issues == [], f"Issues on fresh DB: {issues}"


def test_validate_sqlite_detects_missing_table(tmp_db):
    sqlite3.connect(tmp_db).close()  # Empty DB
    issues = validate_sqlite(tmp_db)
    assert len(issues) > 0
    assert any("missing_table" in str(i) for i in issues)


def test_validate_codebase_runs():
    issues = validate_codebase()
    assert isinstance(issues, list)


# ── SQL validity tests ───────────────────────────────────────────

def test_sqlite_create_sql_is_valid():
    """Generated SQL parses without error in SQLite."""
    conn = sqlite3.connect(":memory:")
    for table in TABLES.values():
        sql = generate_create_sql(table)
        conn.executescript(sql)  # Should not raise
    conn.close()
