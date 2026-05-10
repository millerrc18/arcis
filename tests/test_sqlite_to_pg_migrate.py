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
    sys.modules["scripts.sqlite_to_pg_migrate"] = mod
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
    sqlite_cursor_mock.fetchmany.return_value = []

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
    """Rows with a NULL primary key must be filtered before execute_values."""
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

    with mock.patch("psycopg2.connect", return_value=pg_conn_mock):
        with mock.patch("scripts.sqlite_to_pg_migrate.execute_values") as ev_mock:
            mod.run_migration(
                sqlite_path=sqlite_path,
                database_url="postgresql://u:p@localhost/db",
                table_filter=["recommendations"],
                dry_run=False,
                vacuum_after=False,
            )

    # execute_values should have been called; check that the NULL-pk row was excluded.
    assert ev_mock.call_count >= 1, "execute_values was never called"
    for call in ev_mock.call_args_list:
        rows_arg = call[0][2]  # third positional arg to execute_values(cur, sql, rows)
        for row in rows_arg:
            assert row[pk_idx] is not None, "NULL pk row was passed to execute_values"


def test_migrate_chunks_at_1000_rows(monkeypatch, tmp_path):
    """2500 rows must result in exactly 3 execute_values calls (1000, 1000, 500)."""
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

    with mock.patch("psycopg2.connect", return_value=pg_conn_mock):
        with mock.patch("scripts.sqlite_to_pg_migrate.execute_values") as ev_mock:
            mod.run_migration(
                sqlite_path=sqlite_path,
                database_url="postgresql://u:p@localhost/db",
                table_filter=["recommendations"],
                dry_run=False,
                vacuum_after=False,
            )

    assert ev_mock.call_count == 3, (
        f"Expected 3 execute_values calls for 2500 rows in chunks of 1000, got {ev_mock.call_count}"
    )
    assert len(ev_mock.call_args_list[0][0][2]) == 1000
    assert len(ev_mock.call_args_list[1][0][2]) == 1000
    assert len(ev_mock.call_args_list[2][0][2]) == 500


def test_migrate_dry_run_does_not_call_execute_values(monkeypatch, tmp_path):
    """--dry-run must print plan without calling execute_values."""
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
        with mock.patch("scripts.sqlite_to_pg_migrate.execute_values") as ev_mock:
            mod.run_migration(
                sqlite_path=sqlite_path,
                database_url="postgresql://u:p@localhost/db",
                table_filter=["recommendations"],
                dry_run=True,
                vacuum_after=False,
            )

    ev_mock.assert_not_called()


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


def test_build_insert_sql_template_uses_composite_pk_conflict_target(monkeypatch):
    """For composite-PK tables (e.g. minute_bars), the ON CONFLICT target must list ALL pk columns.

    Postgres requires the ON CONFLICT specification to match an exact UNIQUE/PRIMARY KEY
    constraint. A single-column target against a composite PK raises:
        ERROR: there is no unique or exclusion constraint matching the ON CONFLICT specification

    Pre-fix this script used `pk[0]` only and would have crashed on minute_bars (435K rows,
    33% of the operator's 1.3M row total).
    """
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@localhost/db")
    mod = _import_migrate(monkeypatch)
    sql = mod._build_insert_sql_template(
        "minute_bars", ["ticker", "timestamp", "open", "high", "low", "close", "volume"],
        ["ticker", "timestamp"],
    )
    assert "ON CONFLICT (ticker, timestamp) DO NOTHING" in sql, (
        f"Composite PK conflict target missing both columns; got: {sql}"
    )
    # Single-PK form must also still work (regression guard for the simple case)
    sql_single = mod._build_insert_sql_template(
        "recommendations", ["id", "ticker", "score"], ["id"]
    )
    assert "ON CONFLICT (id) DO NOTHING" in sql_single


def test_migrate_filters_rows_with_any_null_pk_column(monkeypatch, tmp_path):
    """For composite-PK tables, rows with ANY NULL pk column must be filtered before insert.

    Uses minute_bars (composite PK = [ticker, timestamp]). Rows tested:
      - ('AAPL', '2026-01-01', …) — valid
      - (None,    '2026-01-02', …) — NULL ticker → filtered
      - ('MSFT', None,           …) — NULL timestamp → filtered
      - (None,    None,           …) — both NULL → filtered
    Only the first row should reach execute_values.
    """
    monkeypatch.setenv("ARCIS_DB_PATH", "C:/arcis/data/ai_research_desk.sqlite3")
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@localhost/db")
    mod = _import_migrate(monkeypatch)

    from src.schema.registry import TABLES
    table = TABLES["minute_bars"]
    col_names = [c.name for c in table.columns]
    pk_cols = list(table.primary_key)

    def make_row(ticker, ts):
        row = []
        for c in col_names:
            if c == "ticker":
                row.append(ticker)
            elif c == "timestamp":
                row.append(ts)
            else:
                row.append("placeholder")
        return tuple(row)

    rows = [
        make_row("AAPL", "2026-01-01T09:30:00"),  # valid
        make_row(None, "2026-01-02T09:30:00"),    # null ticker → skip
        make_row("MSFT", None),                    # null timestamp → skip
        make_row(None, None),                      # both null → skip
    ]

    sqlite_path = str(tmp_path / "test.sqlite3")
    conn = sqlite3.connect(sqlite_path)
    col_defs = ", ".join(f"{c.name} TEXT" for c in table.columns)
    conn.execute(f"CREATE TABLE minute_bars ({col_defs})")
    conn.executemany(
        f"INSERT INTO minute_bars VALUES ({','.join('?' for _ in col_names)})",
        rows,
    )
    conn.commit()
    conn.close()

    pg_conn_mock = mock.MagicMock()
    pg_cursor_mock = mock.MagicMock()
    pg_conn_mock.cursor.return_value = pg_cursor_mock
    pg_cursor_mock.fetchone.return_value = (4,)

    with mock.patch("psycopg2.connect", return_value=pg_conn_mock):
        with mock.patch("scripts.sqlite_to_pg_migrate.execute_values") as ev_mock:
            mod.run_migration(
                sqlite_path=sqlite_path,
                database_url="postgresql://u:p@localhost/db",
                table_filter=["minute_bars"],
                dry_run=False,
                vacuum_after=False,
            )

    assert ev_mock.call_count == 1, f"Expected 1 execute_values call (1 valid row), got {ev_mock.call_count}"
    rows_arg = ev_mock.call_args_list[0][0][2]
    assert len(rows_arg) == 1, f"Expected 1 row after NULL-pk filter, got {len(rows_arg)}"
    pk_indexes = [col_names.index(c) for c in pk_cols]
    for i in pk_indexes:
        assert rows_arg[0][i] is not None, "Filtered row should have non-null PK columns"


def test_redact_password_masks_dsn_credentials(monkeypatch):
    """_redact_password must mask the password fragment in DSN-style URLs (Issue 3a).

    Uses a fabricated test password (NOT any production substring) — earlier
    revisions of this test mistakenly used a fragment of the real leaked
    password as the fixture value, which would have committed the substring
    to git permanently. Operator caught that during PR #1047 re-review.
    """
    mod = _import_migrate(monkeypatch)
    assert mod._redact_password(
        "postgresql://halcyon:fake-test-password-xyz123@localhost:5433/halcyon"
    ) == "postgresql://halcyon:<redacted>@localhost:5433/halcyon"
    # No password → leave unchanged
    assert mod._redact_password("postgresql://localhost:5433/halcyon") == (
        "postgresql://localhost:5433/halcyon"
    )
    # Empty string → leave unchanged (defensive)
    assert mod._redact_password("") == ""
    # Special-character passwords (operator may rotate to a token with `:` or `@`-like chars)
    assert mod._redact_password(
        "postgresql://user:p%40ssw%3Ard@host:5432/db"
    ) == "postgresql://user:<redacted>@host:5432/db"


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
