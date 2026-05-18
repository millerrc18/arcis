"""Tests for startup_checks.py introspection migration to engine-aware helpers.

Sprint 5 §J5/§J6 Phase 2 T2.8 — Modified-A migration.

startup_checks.py has two SQLite-only introspection sites in `check_schema`
(line 153 inside the no-issues branch + line 167 after `fix_issues`):

    SELECT COUNT(*) FROM sqlite_master WHERE type='table'

Both are replaced with `len(engine_aware_table_list(conn))` so the startup
table-count check works whether the connection is sqlite3.Connection or a
PostgresConnectionWrapper.

The tests exercise `check_schema` end-to-end against BOTH engines via a
parametrized fixture. Since `check_schema(db_path)` opens its own
connection internally via `connect_db(db_path)`, and `connect_db` with an
explicit path always opens SQLite, we patch `connect_db` inside
startup_checks to return our engine-parametrized connection instead.

  * SQLite path: hermetic — creates a tmp DB seeded with registry tables
    and verifies the count check reports the right table count and an `ok`
    status.
  * PG path: parametrized on `engine='postgres'`; SKIPS cleanly when
    `TEST_DATABASE_URL` is unset (worktree without operator's .env).
"""

import os
import sqlite3
import tempfile
from unittest.mock import patch

import pytest


# ---------------------------------------------------------------------------
# Postgres fixture detection — skip PG cases when no live cluster reachable.
# ---------------------------------------------------------------------------

TEST_PG_URL = os.environ.get("TEST_DATABASE_URL", "")
_PG_AVAILABLE = TEST_PG_URL.startswith("postgres")

_PG_SKIP_REASON = "TEST_DATABASE_URL not set or not postgres://"


# Two registry tables to seed for the schema-count check. Picked because
# they are present in `src/schema/registry.py`.
_SEED_TABLES = ["activity_log", "scan_metrics"]


def _build_sqlite_fixture():
    """Return (conn, cleanup, baseline_count) for SQLite seeded with two tables.

    `baseline_count` is 0 because the fixture creates a fresh tmp database
    each call — kept in the return signature so both fixtures share the same
    shape and the test can assert `count == baseline + len(_SEED_TABLES)`
    uniformly across engines.
    """
    from src.schema.registry import TABLES
    from src.schema.sqlite import generate_create_sql

    fd, db_path = tempfile.mkstemp(suffix=".sqlite3")
    os.close(fd)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    for name in _SEED_TABLES:
        conn.executescript(generate_create_sql(TABLES[name]))
    conn.commit()

    def cleanup():
        conn.close()
        try:
            os.unlink(db_path)
        except OSError:
            pass

    return conn, cleanup, 0


def _build_pg_fixture():
    """Return (wrapper, cleanup, baseline_count) for PG seeded with two test tables.

    `baseline_count` is the number of public-schema tables present before the
    fixture seeded its two — used by the assertion so the test tolerates
    pre-existing tables in the shared test database (e.g., leftover artifacts
    from other test runs against the same TEST_DATABASE_URL).
    """
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
    for name in reversed(_SEED_TABLES):
        cur.execute(f"DROP TABLE IF EXISTS {name} CASCADE")
    cur.execute(
        "SELECT COUNT(*) AS c FROM pg_catalog.pg_tables "
        "WHERE schemaname = 'public'"
    )
    baseline_count = cur.fetchone()["c"]
    for name in _SEED_TABLES:
        cur.execute(generate_create_sql(TABLES[name]))
    raw.autocommit = False
    cur.close()

    wrapper = PostgresConnectionWrapper(raw)

    def cleanup():
        # check_schema closes the wrapper via `with connect_db(...) as conn:`,
        # which closes `raw` too. Re-open a fresh connection for cleanup so
        # we don't try to drop tables through a closed conn.
        try:
            wrapper.close()
        except Exception:
            pass
        try:
            cleanup_conn = psycopg2.connect(
                TEST_PG_URL, cursor_factory=psycopg2.extras.RealDictCursor
            )
            cleanup_conn.autocommit = True
            cleanup_cur = cleanup_conn.cursor()
            for name in reversed(_SEED_TABLES):
                try:
                    cleanup_cur.execute(f"DROP TABLE IF EXISTS {name} CASCADE")
                except Exception:
                    pass
            cleanup_cur.close()
            cleanup_conn.close()
        except Exception:
            pass

    return wrapper, cleanup, baseline_count


@pytest.fixture
def seeded_conn(request):
    """Parametrized fixture yielding (conn, expected_table_count).

    `expected_table_count = baseline_pre_seed + len(_SEED_TABLES)` — lets the
    test tolerate pre-existing tables in the shared PG test database while
    still verifying the table-count check returns the correct value via the
    engine-aware helper.

    PG variant skips cleanly when TEST_DATABASE_URL is unset.
    """
    engine = request.param
    if engine == "sqlite":
        conn, cleanup, baseline = _build_sqlite_fixture()
    elif engine == "postgres":
        if not _PG_AVAILABLE:
            pytest.skip(_PG_SKIP_REASON)
        conn, cleanup, baseline = _build_pg_fixture()
    else:
        raise ValueError(f"Unknown engine: {engine}")
    expected_count = baseline + len(_SEED_TABLES)
    try:
        yield conn, expected_count
    finally:
        cleanup()


# ---------------------------------------------------------------------------
# check_schema table-count introspection contract.
# ---------------------------------------------------------------------------


class TestStartupCheckSchemaIntrospection:
    """startup_checks.check_schema uses engine-aware table listing on both engines."""

    @pytest.mark.parametrize(
        "seeded_conn", ["sqlite", "postgres"], indirect=True
    )
    def test_check_schema_count_ok_branch_uses_engine_aware(
        self, seeded_conn
    ):
        """When `validate_sqlite` returns no issues, the count check reports
        the number of tables visible via the engine-aware helper.

        Patches `connect_db` inside startup_checks so the function sees our
        parametrized connection regardless of engine, and patches
        `validate_sqlite` to return an empty list (no drift) so the first
        sqlite_master COUNT site (line 153 in the original file) is taken.
        """
        # Import via src.startup to avoid circular-import pitfalls
        # (startup.py re-exports startup_checks symbols).
        from src.startup import check_schema

        conn, expected_count = seeded_conn
        # `validate_sqlite` returns no issues -> first COUNT branch hit.
        # Patch at src.schema.validator since check_schema imports it
        # inside the function body via `from src.schema.validator import ...`.
        with patch("src.startup_checks.connect_db", return_value=conn), \
             patch("src.schema.validator.validate_sqlite", return_value=[]):
            results = check_schema({}, db_path="ignored")

        assert len(results) == 1
        result = results[0]
        assert result.name == "schema_drift"
        assert result.status == "ok"
        # Detail format: "<N> tables, 0 drift" — N comes from the engine-aware
        # helper, which on SQLite filters `sqlite_%` system tables (so an
        # auto-created `sqlite_sequence` does NOT inflate the count) and on PG
        # filters `information_schema`/`pg_*` system schemas.
        assert f"{expected_count} tables" in result.detail
        assert "0 drift" in result.detail

    @pytest.mark.parametrize(
        "seeded_conn", ["sqlite", "postgres"], indirect=True
    )
    def test_check_schema_count_after_fix_uses_engine_aware(
        self, seeded_conn
    ):
        """When `validate_sqlite` first reports issues, `check_schema` calls
        `fix_issues`, then re-validates, then counts tables — exercising the
        SECOND sqlite_master COUNT site (line 167 in the original file).

        Patches the validators so the first call returns one issue and the
        second returns []; the test verifies the post-fix count reflects
        what the engine-aware helper sees.
        """
        from src.schema.validator import SchemaIssue
        from src.startup_checks import check_schema

        conn, expected_count = seeded_conn
        issue = SchemaIssue(
            severity="error",
            issue_type="missing_table",
            table="phantom_table",
            column=None,
            detail="not found",
        )

        with patch("src.startup_checks.connect_db", return_value=conn), \
             patch("src.schema.validator.validate_sqlite",
                   side_effect=[[issue], []]), \
             patch("src.schema.validator.fix_issues",
                   return_value=["created phantom_table"]):
            results = check_schema({}, db_path="ignored")

        assert len(results) == 1
        result = results[0]
        assert result.name == "schema_drift"
        assert result.status == "ok"
        # Detail format: "<N> tables, 0 drift (1 auto-fixed)"
        assert f"{expected_count} tables" in result.detail
        assert "0 drift" in result.detail
        assert "1 auto-fixed" in result.detail
