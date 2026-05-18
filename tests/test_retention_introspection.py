"""Tests for retention.py introspection migration to engine-aware helpers.

Sprint 5 §J5/§J6 Phase 2 T2.2 — Modified-A migration.

retention.py has two introspection sites that were SQLite-only:

* Line 108 (`_get_existing_tables`): `SELECT name FROM sqlite_master WHERE
  type='table'` — replaced with `engine_aware_table_list(conn)`.
* Line 116 (`_column_exists`): `PRAGMA table_info(<table>)` — replaced with
  `engine_aware_column_info(conn, table)`.

The test below exercises both helpers via the public retention helpers
(`_get_existing_tables` and `_column_exists`) against BOTH SQLite and
Postgres so the call-site migration is verified end-to-end:

  * SQLite path: hermetic — creates a tmp DB seeded with two registry
    tables and verifies both helpers see them.
  * PG path: parametrized on `engine='postgres'`; SKIPS cleanly when
    TEST_DATABASE_URL is unset (worktree without operator's .env).

The PG fixture uses the same approach as
`tests/test_db_engine_aware_introspection.py` — drop+recreate the two
tables to ensure a hermetic per-test slate, then exercise the
introspection contract.
"""

import os
import sqlite3
import tempfile

import pytest


# ---------------------------------------------------------------------------
# Postgres fixture detection — skip PG cases when no live cluster reachable.
# ---------------------------------------------------------------------------

TEST_PG_URL = os.environ.get("TEST_DATABASE_URL", "")
_PG_AVAILABLE = TEST_PG_URL.startswith("postgres")

_PG_SKIP_REASON = "TEST_DATABASE_URL not set or not postgres://"


# Two registry tables retention.py would prune from. Picked because both
# are registered in `src/schema/registry.py` and contain a `created_at`
# column (the time-axis used by retention's `_column_exists` check).
_RETENTION_TABLES = ["activity_log", "scan_metrics"]


def _build_sqlite_fixture():
    """Return (conn, cleanup) for SQLite seeded with retention tables."""
    from src.schema.registry import TABLES
    from src.schema.sqlite import generate_create_sql

    fd, db_path = tempfile.mkstemp(suffix=".sqlite3")
    os.close(fd)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    for name in _RETENTION_TABLES:
        conn.executescript(generate_create_sql(TABLES[name]))
    conn.commit()

    def cleanup():
        conn.close()
        try:
            os.unlink(db_path)
        except OSError:
            pass

    return conn, cleanup


def _build_pg_fixture():
    """Return (wrapper, cleanup) for PG seeded with retention tables."""
    import psycopg2
    import psycopg2.extras

    from src.schema.postgres import generate_create_sql
    from src.schema.registry import TABLES
    from src.utils.db import PostgresConnectionWrapper

    raw = psycopg2.connect(
        TEST_PG_URL, cursor_factory=psycopg2.extras.RealDictCursor
    )
    raw.autocommit = True
    cur = raw.cursor()
    for name in reversed(_RETENTION_TABLES):
        cur.execute(f"DROP TABLE IF EXISTS {name} CASCADE")
    for name in _RETENTION_TABLES:
        cur.execute(generate_create_sql(TABLES[name]))
    raw.autocommit = False
    cur.close()

    wrapper = PostgresConnectionWrapper(raw)

    def cleanup():
        try:
            try:
                raw.rollback()
            except Exception:
                pass
            raw.autocommit = True
            cleanup_cur = raw.cursor()
            for name in reversed(_RETENTION_TABLES):
                try:
                    cleanup_cur.execute(f"DROP TABLE IF EXISTS {name} CASCADE")
                except Exception:
                    pass
            cleanup_cur.close()
        finally:
            wrapper.close()

    return wrapper, cleanup


@pytest.fixture
def retention_conn(request):
    """Parametrized fixture yielding either a SQLite or PG connection.

    PG variant skips cleanly when TEST_DATABASE_URL is unset (worktree
    without operator's .env).
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
# Retention introspection contract — both helpers must see the retention
# tables on BOTH engines via the engine-aware helpers.
# ---------------------------------------------------------------------------


class TestRetentionIntrospection:
    """retention.py's two introspection helpers work on both engines."""

    @pytest.mark.parametrize(
        "retention_conn", ["sqlite", "postgres"], indirect=True
    )
    def test_get_existing_tables_sees_retention_tables(self, retention_conn):
        """`_get_existing_tables(conn)` returns the seeded retention tables.

        Verifies that retention.py's helper (which now calls
        `engine_aware_table_list`) sees both tables on either engine.
        """
        from src.data_collection.retention import _get_existing_tables

        existing = _get_existing_tables(retention_conn)
        assert "activity_log" in existing
        assert "scan_metrics" in existing

    @pytest.mark.parametrize(
        "retention_conn", ["sqlite", "postgres"], indirect=True
    )
    def test_column_exists_finds_created_at(self, retention_conn):
        """`_column_exists(conn, table, col)` returns True for present columns.

        Verifies that retention.py's helper (which now calls
        `engine_aware_column_info`) correctly identifies the `created_at`
        column on both retention tables across engines.
        """
        from src.data_collection.retention import _column_exists

        assert _column_exists(retention_conn, "activity_log", "created_at")
        assert _column_exists(retention_conn, "scan_metrics", "created_at")

    @pytest.mark.parametrize(
        "retention_conn", ["sqlite", "postgres"], indirect=True
    )
    def test_column_exists_returns_false_for_missing_column(
        self, retention_conn
    ):
        """`_column_exists` returns False for a column not on the table."""
        from src.data_collection.retention import _column_exists

        assert not _column_exists(
            retention_conn, "activity_log", "no_such_column_xyz"
        )

    @pytest.mark.parametrize(
        "retention_conn", ["sqlite", "postgres"], indirect=True
    )
    def test_column_exists_returns_false_for_missing_table(
        self, retention_conn
    ):
        """`_column_exists` returns False for a table not in the DB."""
        from src.data_collection.retention import _column_exists

        assert not _column_exists(
            retention_conn, "this_table_does_not_exist_xyz", "anything"
        )
