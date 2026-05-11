"""Tests for engine-aware migration of src/schema/validator.py.

T2.7 (Sprint 5 §J5/§J6 Phase 2 Batch 2). The watch loop's first query on
startup hit `SELECT name FROM sqlite_master` against PG and crashed hard
on the 2026-05-10 cutover (crash site #3). Phase 2 makes validator engine-
aware via `engine_aware_table_list` and `engine_aware_column_info`.

Two parametrized tests over engine ∈ {'sqlite', 'postgres'}:

1. `test_validator_runs_cleanly_on_fresh_schema` — when the underlying
   database carries every registry table (created via the engine's own
   DDL generator), validator should report zero issues.

2. `test_validator_detects_missing_table_drift` — when a registry table is
   absent from the database, validator must emit a `missing_table` issue
   for that table. This exercises the engine_aware_table_list path.

Postgres-engine cases skip when TEST_DATABASE_URL is unset (so the test
file is hermetic on developer machines without a live PG cluster).
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
# Per-engine fixture builders. Both produce a database carrying every
# registry table so the cross-engine equivalence is exercised end-to-end.
# ---------------------------------------------------------------------------


def _build_sqlite_full_schema():
    """SQLite path: temp file with every registry table created."""
    from src.schema.registry import TABLES
    from src.schema.sqlite import generate_create_sql

    fd, db_path = tempfile.mkstemp(suffix=".sqlite3")
    os.close(fd)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    for tdef in TABLES.values():
        conn.executescript(generate_create_sql(tdef))
    conn.commit()

    def cleanup():
        conn.close()
        try:
            os.unlink(db_path)
        except OSError:
            pass

    return conn, db_path, cleanup


def _build_pg_full_schema():
    """PG path: PostgresConnectionWrapper with every registry table created
    on the public schema. Returns (wrapper, created, cleanup).

    Bootstraps EVERY registry table (not just sync_to_postgres ones) because
    `validate_sqlite()` checks every entry in TABLES regardless of sync
    eligibility — a missing table is a drift report whether or not it syncs
    to the cloud dashboard. Tables are dropped on cleanup so repeated test
    runs are idempotent.

    Uses a fresh raw psycopg2 connection for cleanup because validate_sqlite()
    calls `conn.close()` on the wrapper at the end of its work, which leaves
    `raw` in a closed state. The cleanup callable opens a NEW connection to
    run the DROP TABLE pass, so it never tries to touch the closed cursor.
    """
    from src.schema.postgres import generate_create_sql
    from src.schema.registry import TABLES
    from src.utils.db import PostgresConnectionWrapper

    raw = psycopg2.connect(
        TEST_PG_URL, cursor_factory=psycopg2.extras.RealDictCursor
    )
    raw.autocommit = True
    cur = raw.cursor()

    created = []
    for tdef in TABLES.values():
        cur.execute(f"DROP TABLE IF EXISTS {tdef.name} CASCADE")
        cur.execute(generate_create_sql(tdef))
        created.append(tdef.name)
    raw.autocommit = False
    cur.close()

    wrapper = PostgresConnectionWrapper(raw)

    def cleanup():
        # validate_sqlite() closes `raw` via wrapper.close(); reconnect to
        # run the teardown DROP TABLE pass on a fresh connection.
        try:
            cleanup_raw = psycopg2.connect(
                TEST_PG_URL,
                cursor_factory=psycopg2.extras.RealDictCursor,
            )
        except Exception:
            return
        try:
            cleanup_raw.autocommit = True
            cur2 = cleanup_raw.cursor()
            for name in reversed(created):
                try:
                    cur2.execute(f"DROP TABLE IF EXISTS {name} CASCADE")
                except Exception:
                    pass
            cur2.close()
        finally:
            cleanup_raw.close()

    return wrapper, created, cleanup


# ---------------------------------------------------------------------------
# Parametrized engine fixture. Skips PG variant cleanly when unavailable.
# ---------------------------------------------------------------------------


@pytest.fixture(params=["sqlite", "postgres"])
def engine_full_schema(request, monkeypatch):
    """Yield (validator_fn, conn) for the parametrized engine.

    The yielded `validator_fn` is a thunk that calls
    `src.schema.validator.validate_sqlite()` against the engine's fixture
    DB. SQLite path passes the temp DB path. PG path sets DATABASE_URL so
    `connect_db()` returns a Postgres wrapper, and passes db_path=None.

    This wiring lets us test both engines through the same public surface
    (`validate_sqlite`) so the engine-aware migration is validated as the
    drop-in replacement it must be.
    """
    engine = request.param
    if engine == "sqlite":
        conn, db_path, cleanup = _build_sqlite_full_schema()
        from src.schema.validator import validate_sqlite

        def run():
            return validate_sqlite(db_path)

        try:
            yield run, conn
        finally:
            cleanup()
    elif engine == "postgres":
        if not _PG_AVAILABLE:
            pytest.skip(_PG_SKIP_REASON)
        wrapper, _created, cleanup = _build_pg_full_schema()
        # validate_sqlite() calls connect_db(db_path); to route it to PG we
        # need DATABASE_URL set AND the call site must use the sentinel path.
        # However, validate_sqlite() takes an explicit db_path arg, so we
        # patch connect_db within the validator module to return our wrapper.
        from src.schema import validator as validator_mod

        def fake_connect_db(db_path):
            return wrapper

        monkeypatch.setattr(validator_mod, "connect_db", fake_connect_db)

        def run():
            # db_path is ignored by the patched connect_db.
            return validator_mod.validate_sqlite("ignored")

        try:
            yield run, wrapper
        finally:
            cleanup()
    else:
        raise ValueError(f"unknown engine: {engine!r}")


# ---------------------------------------------------------------------------
# Test 1 — fresh full schema must report zero issues on both engines.
# ---------------------------------------------------------------------------


def test_validator_runs_cleanly_on_fresh_schema(engine_full_schema):
    """validate_sqlite() emits zero issues when every registry table exists.

    Sprint 5 §J5/§J6 Phase 2 T2.7 — the validator must not crash on
    Postgres (where `SELECT name FROM sqlite_master` and
    `PRAGMA table_info(...)` are both syntax errors) and must report the
    same zero-issue outcome both engines would on a fresh registry-aligned
    schema.

    On SQLite: confirmation that the engine_aware_table_list /
    engine_aware_column_info wiring did not alter the SQLite-correct
    behavior (regression guard for the production path until cutover).

    On PG: confirmation that the new path actually executes against
    `pg_catalog.pg_tables` + `information_schema.columns` without crashing
    on PRAGMA / sqlite_master syntax — the cutover-blocker the design doc
    targets.
    """
    run_validate, _conn = engine_full_schema
    issues = run_validate()
    # On a fresh registry-aligned schema, no issues should be reported.
    # We filter for missing_table / missing_column issues — codebase_violation
    # is computed by validate_codebase() (a separate function) so isn't here.
    missing_table_issues = [
        i for i in issues if i.issue_type == "missing_table"
    ]
    missing_col_issues = [
        i for i in issues if i.issue_type == "missing_column"
    ]
    assert missing_table_issues == [], (
        f"expected zero missing_table issues on fresh schema, got: "
        f"{[str(i) for i in missing_table_issues]}"
    )
    assert missing_col_issues == [], (
        f"expected zero missing_column issues on fresh schema, got: "
        f"{[str(i) for i in missing_col_issues]}"
    )


# ---------------------------------------------------------------------------
# Test 2 — missing-table drift is correctly detected on both engines.
# ---------------------------------------------------------------------------


def test_validator_detects_missing_table_drift(engine_full_schema):
    """When a registry table is absent, validator emits a missing_table issue.

    Drops one specific table (`activity_log`) from the fixture DB, then
    invokes the validator and asserts:
      1. The result contains at least one issue.
      2. There is a `missing_table` issue for `activity_log`.

    Exercises the `engine_aware_table_list` path that replaced the
    `SELECT name FROM sqlite_master` call at validator.py:43.
    """
    run_validate, conn = engine_full_schema
    # Drop a known registry table so it shows up as drift.
    # activity_log is a common, sync-eligible table — present on both engines.
    target_table = "activity_log"

    # Drop using engine-appropriate syntax. PG path needs CASCADE; SQLite
    # doesn't support it, but DROP TABLE IF EXISTS works on both.
    from src.utils.db import PostgresConnectionWrapper

    if isinstance(conn, PostgresConnectionWrapper):
        cur = conn.cursor()
        cur.execute(f"DROP TABLE IF EXISTS {target_table} CASCADE")
        conn.commit()
    else:
        conn.execute(f"DROP TABLE IF EXISTS {target_table}")
        conn.commit()

    issues = run_validate()
    missing_tables = {
        i.table for i in issues if i.issue_type == "missing_table"
    }
    assert target_table in missing_tables, (
        f"expected missing_table issue for {target_table!r}, got tables: "
        f"{missing_tables} (all issues: {[str(i) for i in issues]})"
    )
