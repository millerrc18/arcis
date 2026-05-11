"""Tests for engine_aware_table_list + engine_aware_column_info in src/utils/db.py.

These helpers replace `sqlite_master` / `PRAGMA table_info` call sites with
engine-agnostic introspection. The output shape MUST match `PRAGMA table_info`
output so call sites can use the helpers as drop-in replacements: tuples
`(cid, name, type, notnull, dflt_value, pk)` (or row-like objects with the
same fields).

Test contracts:

* `engine_aware_table_list(conn)` returns the registry table names that
  exist in the underlying database, sorted alphabetically. The sorting
  is part of the contract — call sites can depend on a stable order
  for comparison loops and diff output.

* `engine_aware_column_info(conn, table)` returns a list of column-info
  rows whose first row exposes `(cid, name, type, notnull, dflt_value, pk)`.
  When `table` does not exist, an empty list is returned (matching
  `PRAGMA table_info(nonexistent)` silent-empty behavior).

Tests parametrize on `engine` ∈ {'sqlite', 'postgres'}. Postgres-engine
tests skip when `TEST_DATABASE_URL` (or `DATABASE_URL`) is not set or
not a `postgres://` URL — same convention as test_db_wrapper_rewrite.py.

T0.6 (engine_aware_index_list + engine_aware_foreign_key_list) will append
its tests to this same file under separately-scoped classes.

Sprint 5 §J5/§J6 Phase 0 T0.5 — Modified-A migration introspection helpers.
"""

import os
import sqlite3
import tempfile

import psycopg2
import psycopg2.extras
import pytest


# ---------------------------------------------------------------------------
# Postgres fixture detection — skip PG cases when no live cluster reachable.
# ---------------------------------------------------------------------------

TEST_PG_URL = os.environ.get("TEST_DATABASE_URL") or os.environ.get(
    "DATABASE_URL", ""
)
_PG_AVAILABLE = TEST_PG_URL.startswith("postgres")

_PG_SKIP_REASON = "TEST_DATABASE_URL / DATABASE_URL not set or not postgres://"


# ---------------------------------------------------------------------------
# Per-engine fixture: build a known schema with exactly two tables so the
# tests can pin exact expected names. The fixture yields a connection-like
# object (sqlite3.Connection or PostgresConnectionWrapper) wired up the
# same way production code consumes it.
# ---------------------------------------------------------------------------


def _build_sqlite_fixture():
    """Return (conn, cleanup_fn) for SQLite. The fixture creates
    `shadow_trades` (via registry DDL) and `widgets` (a synthetic table)
    in a temp DB file.

    Using the real `shadow_trades` DDL exercises the helper against the
    column-shape call sites will see in production.
    """
    from src.schema.registry import TABLES
    from src.schema.sqlite import generate_create_sql

    fd, db_path = tempfile.mkstemp(suffix=".sqlite3")
    os.close(fd)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(generate_create_sql(TABLES["shadow_trades"]))
    conn.executescript(
        "CREATE TABLE widgets ("
        "  id INTEGER PRIMARY KEY,"
        "  name TEXT NOT NULL,"
        "  qty INTEGER DEFAULT 0"
        ")"
    )
    conn.commit()

    def cleanup():
        conn.close()
        try:
            os.unlink(db_path)
        except OSError:
            pass

    return conn, cleanup


def _build_pg_fixture():
    """Return (conn, cleanup_fn) for Postgres.

    Creates `shadow_trades` (via registry DDL converted to PG dialect)
    and `widgets` in the public schema, then yields a
    PostgresConnectionWrapper. Cleanup drops both tables to keep the
    fixture hermetic across runs.
    """
    from src.schema.registry import TABLES
    from src.schema.postgres import generate_create_sql
    from src.utils.db import PostgresConnectionWrapper

    raw = psycopg2.connect(
        TEST_PG_URL, cursor_factory=psycopg2.extras.RealDictCursor
    )
    cur = raw.cursor()
    # Defensive drop to handle leftover fixture state from a crashed run.
    cur.execute("DROP TABLE IF EXISTS shadow_trades CASCADE")
    cur.execute("DROP TABLE IF EXISTS widgets CASCADE")
    cur.execute(generate_create_sql(TABLES["shadow_trades"]))
    cur.execute(
        "CREATE TABLE widgets ("
        "  id SERIAL PRIMARY KEY,"
        "  name TEXT NOT NULL,"
        "  qty INTEGER DEFAULT 0"
        ")"
    )
    raw.commit()
    cur.close()

    wrapper = PostgresConnectionWrapper(raw)

    def cleanup():
        try:
            cur2 = raw.cursor()
            cur2.execute("DROP TABLE IF EXISTS shadow_trades CASCADE")
            cur2.execute("DROP TABLE IF EXISTS widgets CASCADE")
            raw.commit()
            cur2.close()
        except Exception:
            pass
        wrapper.close()

    return wrapper, cleanup


@pytest.fixture
def db_conn(request):
    """Parametrized fixture yielding either a SQLite or PG connection.

    Tests parametrize via `@pytest.mark.parametrize("engine", ...)` and
    use this fixture to obtain the matching connection. The fixture
    skips PG cases automatically when no live cluster is configured.
    """
    engine = request.param
    if engine == "sqlite":
        conn, cleanup = _build_sqlite_fixture()
    elif engine == "postgres":
        if not _PG_AVAILABLE:
            pytest.skip(_PG_SKIP_REASON)
        conn, cleanup = _build_pg_fixture()
    else:
        raise ValueError(f"Unknown engine: {engine}")
    try:
        yield conn
    finally:
        cleanup()


# ---------------------------------------------------------------------------
# TestTableList — engine_aware_table_list contract
# ---------------------------------------------------------------------------


class TestTableList:
    """Engine-aware table list returns known tables, sorted alphabetically."""

    @pytest.mark.parametrize(
        "db_conn", ["sqlite", "postgres"], indirect=True
    )
    def test_returns_expected_table_names(self, db_conn):
        """The helper returns BOTH fixture tables in the public schema."""
        from src.utils.db import engine_aware_table_list

        names = engine_aware_table_list(db_conn)
        assert "shadow_trades" in names
        assert "widgets" in names

    @pytest.mark.parametrize(
        "db_conn", ["sqlite", "postgres"], indirect=True
    )
    def test_returns_alphabetically_sorted(self, db_conn):
        """Contract: returned names are sorted alphabetically.

        Call sites that diff registry tables vs. db tables rely on a
        stable order to avoid spurious diffs. Sorting here is cheap
        and matches the `ORDER BY tablename` in the PG query path.
        """
        from src.utils.db import engine_aware_table_list

        names = engine_aware_table_list(db_conn)
        assert names == sorted(names), (
            f"engine_aware_table_list must return sorted names: {names}"
        )


# ---------------------------------------------------------------------------
# TestColumnInfo — engine_aware_column_info contract
# ---------------------------------------------------------------------------


class TestColumnInfo:
    """Engine-aware column info matches PRAGMA table_info output shape."""

    @pytest.mark.parametrize(
        "db_conn", ["sqlite", "postgres"], indirect=True
    )
    def test_returns_expected_column_count_for_shadow_trades(self, db_conn):
        """shadow_trades column count from the helper equals the registry count."""
        from src.schema.registry import TABLES
        from src.utils.db import engine_aware_column_info

        rows = engine_aware_column_info(db_conn, "shadow_trades")
        expected = len(TABLES["shadow_trades"].columns)
        assert len(rows) == expected, (
            f"expected {expected} columns from registry, "
            f"got {len(rows)} from engine_aware_column_info"
        )

    @pytest.mark.parametrize(
        "db_conn", ["sqlite", "postgres"], indirect=True
    )
    def test_first_row_matches_pragma_table_info_shape(self, db_conn):
        """First row of column-info exposes (cid, name, type, notnull, dflt_value, pk).

        `PRAGMA table_info(t)` on SQLite returns tuples with exactly these
        six fields. The PG path must emit row-like objects with the same
        named-attribute access so call sites can read `row["name"]`,
        `row["type"]`, `row["pk"]`, etc. without per-engine branches.
        """
        from src.utils.db import engine_aware_column_info

        rows = engine_aware_column_info(db_conn, "shadow_trades")
        assert rows, "shadow_trades must yield at least one column"
        first = rows[0]
        # Each row must support dict-style access by these PRAGMA field names.
        for field in ("cid", "name", "type", "notnull", "dflt_value", "pk"):
            assert field in first.keys(), (
                f"column-info row missing field '{field}': keys={list(first.keys())}"
            )
        # cid is zero-based ordinal per PRAGMA contract.
        assert first["cid"] == 0
        # First column of shadow_trades is `trade_id` per the registry.
        assert first["name"] == "trade_id"

    @pytest.mark.parametrize(
        "db_conn", ["sqlite", "postgres"], indirect=True
    )
    def test_nonexistent_table_returns_empty_list(self, db_conn):
        """engine_aware_column_info on a missing table returns []
        (matches PRAGMA table_info(missing) silent-empty behavior)."""
        from src.utils.db import engine_aware_column_info

        rows = engine_aware_column_info(db_conn, "this_table_does_not_exist_xyz")
        assert rows == [], (
            f"expected empty list for unknown table, got: {rows}"
        )


# ---------------------------------------------------------------------------
# Cross-engine equivalence: same column names on both engines for the same
# registry-defined table. This is the gate that lets Phase 2A call sites
# treat the helper as engine-agnostic.
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not _PG_AVAILABLE, reason=_PG_SKIP_REASON
)
def test_same_column_names_on_both_engines_for_shadow_trades():
    """SQLite and PG return the SAME set of column names for shadow_trades.

    Order may differ (PG returns ordinal_position, SQLite returns cid; both
    start at 0 and follow CREATE TABLE order, so the values should match,
    but assert on set equality to be robust against historical reordering).
    """
    from src.utils.db import engine_aware_column_info

    sqlite_conn, sqlite_cleanup = _build_sqlite_fixture()
    pg_conn, pg_cleanup = _build_pg_fixture()
    try:
        sqlite_rows = engine_aware_column_info(sqlite_conn, "shadow_trades")
        pg_rows = engine_aware_column_info(pg_conn, "shadow_trades")
        sqlite_names = {r["name"] for r in sqlite_rows}
        pg_names = {r["name"] for r in pg_rows}
        assert sqlite_names == pg_names, (
            f"engine mismatch on shadow_trades columns. "
            f"sqlite-only={sqlite_names - pg_names}, "
            f"pg-only={pg_names - sqlite_names}"
        )
    finally:
        sqlite_cleanup()
        pg_cleanup()
