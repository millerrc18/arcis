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


# ---------------------------------------------------------------------------
# T0.6: engine_aware_index_list + engine_aware_foreign_keys tests
# ---------------------------------------------------------------------------

def _sqlite_conn_with_schema(tmp_path, table_names):
    """Open a SQLite connection and create the named registry tables on it."""
    from src.schema.registry import TABLES
    from src.schema.sqlite import generate_create_sql

    db_path = tmp_path / "introspect.sqlite3"
    conn = sqlite3.connect(str(db_path), timeout=5.0)
    conn.row_factory = sqlite3.Row
    for name in table_names:
        conn.executescript(generate_create_sql(TABLES[name]))
    conn.commit()
    return conn


def _pg_wrapper_with_schema(table_names):
    """Open a PG wrapper and ensure the named registry tables exist.

    Skips the test if TEST_DATABASE_URL is unset. Uses the same DDL the
    SQLite path uses (registry-generated CREATE TABLE) — Postgres accepts
    the SQLite-flavored CREATE TABLE for the tables we test against here
    (no SQLite-specific features in shadow_trades / recommendations DDL
    beyond what's portable).

    Drops the tables first to ensure a clean slate per test, then creates
    them so the introspection queries observe a known shape.
    """
    test_database_url = os.environ.get("TEST_DATABASE_URL")
    if not test_database_url:
        pytest.skip("TEST_DATABASE_URL not set; postgres path cannot run")

    import psycopg2
    import psycopg2.extras

    from src.schema.registry import TABLES
    from src.schema.sqlite import generate_create_sql
    from src.utils.db import PostgresConnectionWrapper

    raw = psycopg2.connect(test_database_url, cursor_factory=psycopg2.extras.RealDictCursor)
    raw.autocommit = True
    cur = raw.cursor()
    # Drop in reverse dependency order — best-effort CASCADE
    for name in reversed(table_names):
        cur.execute(f"DROP TABLE IF EXISTS {name} CASCADE")
    for name in table_names:
        # Generate SQLite-flavored DDL; convert known SQLite-isms to PG
        # equivalents for the tables under test. The Phase 2 sync layer
        # has its own canonical PG DDL — for introspection tests we only
        # need the schema to exist with the same indexes + FKs.
        ddl = generate_create_sql(TABLES[name])
        # Strip SQLite-specific tokens that Postgres doesn't accept
        ddl_pg = (
            ddl.replace("AUTOINCREMENT", "")
            .replace("INTEGER PRIMARY KEY", "SERIAL PRIMARY KEY")
        )
        cur.execute(ddl_pg)
    raw.autocommit = False
    return PostgresConnectionWrapper(raw)


def _open_conn(engine, tmp_path, table_names):
    if engine == "sqlite":
        return _sqlite_conn_with_schema(tmp_path, table_names)
    return _pg_wrapper_with_schema(table_names)


# ---------------------------------------------------------------------------
# T0.6 TESTS — engine_aware_index_list
# ---------------------------------------------------------------------------


class TestIndexList:
    """engine_aware_index_list(conn, table) returns PRAGMA-shaped index dicts."""

    @pytest.mark.parametrize("engine", ["sqlite", "postgres"])
    def test_index_list_returns_pragma_shape(self, engine, tmp_path):
        """Each row has the 5 PRAGMA index_list fields:
        (seq, name, unique, origin, partial).
        """
        from src.utils.db import engine_aware_index_list

        conn = _open_conn(engine, tmp_path, ["shadow_trades"])
        try:
            rows = engine_aware_index_list(conn, "shadow_trades")
        finally:
            conn.close()

        assert isinstance(rows, list)
        assert len(rows) >= 1, "shadow_trades should have at least one index"
        for row in rows:
            # PRAGMA index_list returns 5 fields: seq, name, unique, origin, partial
            assert "seq" in row, f"missing 'seq' in {row}"
            assert "name" in row, f"missing 'name' in {row}"
            assert "unique" in row, f"missing 'unique' in {row}"
            assert "origin" in row, f"missing 'origin' in {row}"
            assert "partial" in row, f"missing 'partial' in {row}"
            assert isinstance(row["name"], str)
            assert isinstance(row["unique"], int)
            assert isinstance(row["partial"], int)

    @pytest.mark.parametrize("engine", ["sqlite", "postgres"])
    def test_index_list_returns_registry_indexes(self, engine, tmp_path):
        """All indexes declared in the registry for shadow_trades are present
        in the introspection result.
        """
        from src.schema.registry import TABLES
        from src.utils.db import engine_aware_index_list

        expected_names = {idx.name for idx in TABLES["shadow_trades"].indexes}

        conn = _open_conn(engine, tmp_path, ["shadow_trades"])
        try:
            rows = engine_aware_index_list(conn, "shadow_trades")
        finally:
            conn.close()

        actual_names = {row["name"] for row in rows}
        missing = expected_names - actual_names
        assert not missing, (
            f"registry-declared indexes missing from introspection: {missing}; "
            f"got: {actual_names}"
        )


# ---------------------------------------------------------------------------
# T0.6 TESTS — engine_aware_foreign_keys
# ---------------------------------------------------------------------------


class TestForeignKeys:
    """engine_aware_foreign_keys(conn, table) returns PRAGMA-shaped FK dicts."""

    @pytest.mark.parametrize("engine", ["sqlite", "postgres"])
    def test_foreign_keys_returns_pragma_shape(self, engine, tmp_path):
        """Each row has the 8 PRAGMA foreign_key_list fields:
        (id, seq, table, from, to, on_update, on_delete, match).
        """
        from src.utils.db import engine_aware_foreign_keys

        # shadow_trades has FK to recommendations(recommendation_id)
        conn = _open_conn(engine, tmp_path, ["recommendations", "shadow_trades"])
        try:
            rows = engine_aware_foreign_keys(conn, "shadow_trades")
        finally:
            conn.close()

        assert isinstance(rows, list)
        assert len(rows) >= 1, (
            "shadow_trades should have at least one FK (recommendation_id -> "
            "recommendations.recommendation_id)"
        )
        for row in rows:
            # PRAGMA foreign_key_list fields
            for field in ("id", "seq", "table", "from", "to", "on_update", "on_delete", "match"):
                assert field in row, f"missing '{field}' in {row}"
            assert isinstance(row["table"], str)
            assert isinstance(row["from"], str)
            assert isinstance(row["to"], str)

        # Verify the known recommendation_id -> recommendations.recommendation_id FK is present
        fk_tuples = {(row["table"], row["from"], row["to"]) for row in rows}
        assert ("recommendations", "recommendation_id", "recommendation_id") in fk_tuples, (
            f"expected (recommendations, recommendation_id, recommendation_id) FK; got: {fk_tuples}"
        )

    @pytest.mark.parametrize("engine", ["sqlite", "postgres"])
    def test_foreign_keys_empty_for_table_with_no_fks(self, engine, tmp_path):
        """A table with no FKs returns an empty list (not None, not error)."""
        from src.utils.db import engine_aware_foreign_keys

        # recommendations has no FK declarations in the registry
        conn = _open_conn(engine, tmp_path, ["recommendations"])
        try:
            rows = engine_aware_foreign_keys(conn, "recommendations")
        finally:
            conn.close()

        assert rows == [], f"expected [] for table with no FKs, got: {rows}"
