"""Tests for scripts/sqlite_to_pg_migrate.py.

All tests use mocked psycopg2 — no live PG connection required.
All tests use an in-memory SQLite fixture so no prod DB is touched.
"""

import importlib
import os
import sqlite3
import sys
import types
import unittest.mock as mock
from pathlib import Path

import pytest

# Ensure worktree root is on path so the script can be imported.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# ── helpers ────────────────────────────────────────────────────────────────

def _make_sqlite_db(columns: list[str], rows: list[tuple], table_name: str = "recommendations") -> sqlite3.Connection:
    """Create an in-memory SQLite DB with one table populated with rows."""
    conn = sqlite3.connect(":memory:")
    col_defs = ", ".join(f"{c} TEXT" for c in columns)
    conn.execute(f"CREATE TABLE {table_name} ({col_defs})")
    placeholders = ", ".join("?" for _ in columns)
    conn.executemany(f"INSERT INTO {table_name} VALUES ({placeholders})", rows)
    conn.commit()
    return conn


def _import_migrate(monkeypatch, database_url: str = "postgresql://user:pw@localhost/db"):
    """Import (or reload) the migrate script with environment set."""
    monkeypatch.setenv("ARCIS_DB_PATH", "C:/arcis/data/ai_research_desk.sqlite3")
    monkeypatch.setenv("DATABASE_URL", database_url)
    # Ensure a clean import on each call.
    if "scripts.sqlite_to_pg_migrate" in sys.modules:
        del sys.modules["scripts.sqlite_to_pg_migrate"]
    # scripts/ is not a package — import via importlib from path.
    spec = importlib.util.spec_from_file_location(
        "scripts.sqlite_to_pg_migrate",
        _REPO_ROOT / "scripts" / "sqlite_to_pg_migrate.py",
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ── tests ──────────────────────────────────────────────────────────────────


def test_migrate_skips_tables_with_sync_to_postgres_false(monkeypatch, tmp_path):
    """Tables with sync_to_postgres=False must not be queried from SQLite."""
    monkeypatch.setenv("ARCIS_DB_PATH", "C:/arcis/data/ai_research_desk.sqlite3")
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@localhost/db")
    mod = _import_migrate(monkeypatch)

    # Build a list of the 9 non-sync table names.
    from src.schema.registry import TABLES
    skip_tables = {t.name for t in TABLES.values() if not t.sync_to_postgres}
    assert len(skip_tables) == 9, f"Expected 9 non-sync tables, got {len(skip_tables)}"

    sqlite_path = str(tmp_path / "test.sqlite3")
    sqlite3.connect(sqlite_path).close()

    pg_conn_mock = mock.MagicMock()
    pg_cursor_mock = mock.MagicMock()
    pg_conn_mock.cursor.return_value = pg_cursor_mock
    pg_cursor_mock.fetchone.return_value = (0,)  # source count = 0
    pg_cursor_mock.fetchall.return_value = []

    sqlite_conn_mock = mock.MagicMock()
    sqlite_cursor_mock = mock.MagicMock()
    sqlite_conn_mock.cursor.return_value = sqlite_cursor_mock
    sqlite_cursor_mock.fetchone.return_value = (0,)
    sqlite_cursor_mock.description = []
    sqlite_cursor_mock.fetchall.return_value = []

    queried_tables = []

    original_execute = sqlite_cursor_mock.execute

    def tracking_execute(sql, *args, **kwargs):
        import re
        m = re.search(r"FROM\s+(\w+)", sql, re.IGNORECASE)
        if m:
            queried_tables.append(m.group(1))
        return original_execute(sql, *args, **kwargs)

    sqlite_cursor_mock.execute = tracking_execute

    with mock.patch("psycopg2.connect", return_value=pg_conn_mock):
        with mock.patch("sqlite3.connect", return_value=sqlite_conn_mock):
            mod.run_migration(
                sqlite_path=sqlite_path,
                database_url="postgresql://u:p@localhost/db",
                table_filter=None,
                dry_run=False,
                vacuum_after=False,
            )

    for skip_tbl in skip_tables:
        assert skip_tbl not in queried_tables, (
            f"Table {skip_tbl!r} (sync_to_postgres=False) was queried during migration"
        )


def test_migrate_handles_null_primary_keys(monkeypatch, tmp_path):
    """Rows with a NULL primary key must be filtered before executemany."""
    monkeypatch.setenv("ARCIS_DB_PATH", "C:/arcis/data/ai_research_desk.sqlite3")
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@localhost/db")
    mod = _import_migrate(monkeypatch)

    from src.schema.registry import TABLES

    # Use 'recommendations' — first sync table with TEXT pk.
    table = TABLES["recommendations"]
    pk = table.primary_key if isinstance(table.primary_key, str) else table.primary_key[0]
    col_names = [c.name for c in table.columns]
    pk_idx = col_names.index(pk)

    # Two rows: one valid (pk = "rec-1"), one with NULL pk.
    valid_row = tuple("val" if i != pk_idx else "rec-1" for i in range(len(col_names)))
    null_pk_row = tuple("val" if i != pk_idx else None for i in range(len(col_names)))

    sqlite_path = str(tmp_path / "test.sqlite3")
    conn = sqlite3.connect(sqlite_path)
    col_defs = ", ".join(f"{c.name} TEXT" for c in table.columns)
    conn.execute(f"CREATE TABLE recommendations ({col_defs})")
    conn.execute(
        f"INSERT INTO recommendations VALUES ({','.join('?' for _ in col_names)})",
        valid_row,
    )
    conn.execute(
        f"INSERT INTO recommendations VALUES ({','.join('?' for _ in col_names)})",
        null_pk_row,
    )
    conn.commit()
    conn.close()

    pg_conn_mock = mock.MagicMock()
    pg_cursor_mock = mock.MagicMock()
    pg_conn_mock.cursor.return_value = pg_cursor_mock
    pg_cursor_mock.fetchone.return_value = (2,)  # 2 rows in sqlite
    pg_cursor_mock.rowcount = 1

    with mock.patch("psycopg2.connect", return_value=pg_conn_mock):
        mod.run_migration(
            sqlite_path=sqlite_path,
            database_url="postgresql://u:p@localhost/db",
            table_filter=["recommendations"],
            dry_run=False,
            vacuum_after=False,
        )

    # executemany should have been called; check that the NULL-pk row was excluded.
    all_calls = pg_cursor_mock.executemany.call_args_list
    assert len(all_calls) >= 1, "executemany was never called"
    for call in all_calls:
        rows_arg = call[0][1]  # second positional arg to executemany
        for row in rows_arg:
            assert row[pk_idx] is not None, "NULL pk row was passed to executemany"


def test_migrate_chunks_at_1000_rows(monkeypatch, tmp_path):
    """2500 rows must result in exactly 3 executemany calls (1000, 1000, 500)."""
    monkeypatch.setenv("ARCIS_DB_PATH", "C:/arcis/data/ai_research_desk.sqlite3")
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@localhost/db")
    mod = _import_migrate(monkeypatch)

    from src.schema.registry import TABLES

    table = TABLES["recommendations"]
    pk = table.primary_key if isinstance(table.primary_key, str) else table.primary_key[0]
    col_names = [c.name for c in table.columns]
    pk_idx = col_names.index(pk)

    sqlite_path = str(tmp_path / "test.sqlite3")
    conn = sqlite3.connect(sqlite_path)
    col_defs = ", ".join(f"{c.name} TEXT" for c in table.columns)
    conn.execute(f"CREATE TABLE recommendations ({col_defs})")
    rows = []
    for i in range(2500):
        row = tuple(f"val_{i}" if j != pk_idx else f"rec-{i}" for j in range(len(col_names)))
        rows.append(row)
    conn.executemany(
        f"INSERT INTO recommendations VALUES ({','.join('?' for _ in col_names)})",
        rows,
    )
    conn.commit()
    conn.close()

    pg_conn_mock = mock.MagicMock()
    pg_cursor_mock = mock.MagicMock()
    pg_conn_mock.cursor.return_value = pg_cursor_mock
    pg_cursor_mock.fetchone.return_value = (2500,)
    pg_cursor_mock.rowcount = 1000

    with mock.patch("psycopg2.connect", return_value=pg_conn_mock):
        mod.run_migration(
            sqlite_path=sqlite_path,
            database_url="postgresql://u:p@localhost/db",
            table_filter=["recommendations"],
            dry_run=False,
            vacuum_after=False,
        )

    em_calls = pg_cursor_mock.executemany.call_args_list
    assert len(em_calls) == 3, (
        f"Expected 3 executemany calls for 2500 rows in chunks of 1000, got {len(em_calls)}"
    )
    assert len(em_calls[0][0][1]) == 1000
    assert len(em_calls[1][0][1]) == 1000
    assert len(em_calls[2][0][1]) == 500


def test_migrate_dry_run_does_not_call_executemany(monkeypatch, tmp_path):
    """--dry-run must print plan without calling executemany."""
    monkeypatch.setenv("ARCIS_DB_PATH", "C:/arcis/data/ai_research_desk.sqlite3")
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@localhost/db")
    mod = _import_migrate(monkeypatch)

    from src.schema.registry import TABLES

    table = TABLES["recommendations"]
    pk = table.primary_key if isinstance(table.primary_key, str) else table.primary_key[0]
    col_names = [c.name for c in table.columns]
    pk_idx = col_names.index(pk)

    sqlite_path = str(tmp_path / "test.sqlite3")
    conn = sqlite3.connect(sqlite_path)
    col_defs = ", ".join(f"{c.name} TEXT" for c in table.columns)
    conn.execute(f"CREATE TABLE recommendations ({col_defs})")
    row = tuple("val" if i != pk_idx else "rec-1" for i in range(len(col_names)))
    conn.execute(
        f"INSERT INTO recommendations VALUES ({','.join('?' for _ in col_names)})",
        row,
    )
    conn.commit()
    conn.close()

    pg_conn_mock = mock.MagicMock()
    pg_cursor_mock = mock.MagicMock()
    pg_conn_mock.cursor.return_value = pg_cursor_mock
    pg_cursor_mock.fetchone.return_value = (1,)

    with mock.patch("psycopg2.connect", return_value=pg_conn_mock):
        mod.run_migration(
            sqlite_path=sqlite_path,
            database_url="postgresql://u:p@localhost/db",
            table_filter=["recommendations"],
            dry_run=True,
            vacuum_after=False,
        )

    pg_cursor_mock.executemany.assert_not_called()


def test_migrate_aborts_when_database_url_missing(monkeypatch, tmp_path, capsys):
    """Missing DATABASE_URL must cause SystemExit with non-zero code."""
    monkeypatch.setenv("ARCIS_DB_PATH", "C:/arcis/data/ai_research_desk.sqlite3")
    monkeypatch.delenv("DATABASE_URL", raising=False)

    sqlite_path = str(tmp_path / "test.sqlite3")
    sqlite3.connect(sqlite_path).close()

    # Clear cached module so top-level env check re-runs.
    if "scripts.sqlite_to_pg_migrate" in sys.modules:
        del sys.modules["scripts.sqlite_to_pg_migrate"]

    mod = _import_migrate.__wrapped__ if hasattr(_import_migrate, "__wrapped__") else None

    # Import module fresh without DATABASE_URL — the run_migration call should abort.
    spec = importlib.util.spec_from_file_location(
        "scripts.sqlite_to_pg_migrate",
        _REPO_ROOT / "scripts" / "sqlite_to_pg_migrate.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    with pytest.raises(SystemExit) as exc_info:
        module.run_migration(
            sqlite_path=sqlite_path,
            database_url="",
            dry_run=False,
            vacuum_after=False,
        )
    assert exc_info.value.code != 0


def test_migrate_aborts_when_database_url_not_postgres(monkeypatch, tmp_path):
    """DATABASE_URL not starting with 'postgres' must cause SystemExit."""
    monkeypatch.setenv("ARCIS_DB_PATH", "C:/arcis/data/ai_research_desk.sqlite3")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///foo.db")

    sqlite_path = str(tmp_path / "test.sqlite3")
    sqlite3.connect(sqlite_path).close()

    if "scripts.sqlite_to_pg_migrate" in sys.modules:
        del sys.modules["scripts.sqlite_to_pg_migrate"]

    spec = importlib.util.spec_from_file_location(
        "scripts.sqlite_to_pg_migrate",
        _REPO_ROOT / "scripts" / "sqlite_to_pg_migrate.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    with pytest.raises(SystemExit) as exc_info:
        module.run_migration(
            sqlite_path=sqlite_path,
            database_url="sqlite:///foo.db",
            dry_run=False,
            vacuum_after=False,
        )
    assert exc_info.value.code != 0
