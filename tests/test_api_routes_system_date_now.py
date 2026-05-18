"""Sprint 5 §J5/§J6 Phase 2.5 T5 — api/routes/system.py datetime('now') migration.

Verifies the monitoring-history query in `src/api/routes/system.py:694` runs
against BOTH SQLite and Postgres. Previously the SQL used SQLite's
`datetime('now', ? || ' hours')` time-modifier syntax, which Postgres rejects
with a syntax error (PG uses ``CURRENT_TIMESTAMP - INTERVAL`` semantics that
do not compose with concatenated parameter strings). The Phase 2.5 rewrite
replaces the SQLite-only literal with a `?` placeholder bound to a Python-
computed UTC cutoff (`datetime.utcnow() - timedelta(hours=hours)` ISO-formatted),
so the same SQL works on both engines unchanged.

Parametrized over `engine=['sqlite', 'postgres']` via the local `conn_engine`
fixture. The postgres variant SKIPS cleanly when `TEST_DATABASE_URL` is unset
(operator must opt in — never `DATABASE_URL` which points at prod).

The Postgres branch bootstraps `system_metrics` from the registry's PG DDL
because `system_metrics.sync_to_postgres = False` (the table is local-only in
production but still needs to be exercised on PG for cross-engine query parity).

Static-analysis guard at the bottom confirms `datetime('now'` no longer appears
in the route source after the migration.
"""
from __future__ import annotations

import datetime as _dt
import os
import sqlite3
import tempfile

import pytest


TEST_PG_URL = os.environ.get("TEST_DATABASE_URL", "")
_PG_AVAILABLE = TEST_PG_URL.startswith("postgres")


# ---------------------------------------------------------------------------
# Fixtures — sqlite + (optional) pg conn for system_metrics
# ---------------------------------------------------------------------------


@pytest.fixture
def sqlite_db():
    """SQLite tmp database with the system_metrics table provisioned."""
    fd, path = tempfile.mkstemp(suffix=".sqlite3")
    os.close(fd)
    from tests.conftest import init_test_db

    init_test_db(path, ["system_metrics"])
    yield path
    try:
        os.unlink(path)
    except PermissionError:
        pass  # Windows file locking — cleaned up on next reboot


@pytest.fixture
def sqlite_conn(sqlite_db):
    """sqlite3.Connection bound to the provisioned schema."""
    conn = sqlite3.connect(sqlite_db)
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()


@pytest.fixture
def pg_conn():
    """psycopg2 wrapper bound to TEST_DATABASE_URL. Skips when unset.

    Bootstraps `system_metrics` from the registry's PG DDL and drops the
    table on teardown. `system_metrics.sync_to_postgres = False` so the
    standard `pg_wrapper` conftest fixture wouldn't create this table; we
    create it locally to exercise the cross-engine SQL parity.
    """
    if not _PG_AVAILABLE:
        pytest.skip("TEST_DATABASE_URL not set or not postgres://")

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
    cur.execute("DROP TABLE IF EXISTS system_metrics CASCADE")
    cur.execute(generate_create_sql(TABLES["system_metrics"]))
    cur.close()
    raw.autocommit = False
    wrapper = PostgresConnectionWrapper(raw)
    try:
        yield wrapper
    finally:
        try:
            wrapper.rollback()
        except Exception:
            pass
        try:
            raw.autocommit = True
            cleanup = raw.cursor()
            cleanup.execute("DROP TABLE IF EXISTS system_metrics CASCADE")
            cleanup.close()
        except Exception:
            pass
        wrapper.close()


def _get_conn(request):
    """Return the conn fixture matching the parametrized engine."""
    engine = request.param
    if engine == "sqlite":
        return request.getfixturevalue("sqlite_conn")
    if engine == "postgres":
        return request.getfixturevalue("pg_conn")
    raise ValueError(f"unknown engine: {engine}")


@pytest.fixture(params=["sqlite", "postgres"])
def conn_engine(request):
    return _get_conn(request)


# ---------------------------------------------------------------------------
# Test — parameterized hours-cutoff query matches recent rows on both engines
# ---------------------------------------------------------------------------


def test_monitoring_history_cutoff_query_works_on_both_engines(conn_engine):
    """T5: parameterized `timestamp >= ?` matches recent rows, skips stale.

    Insert three rows:
      • r1 with timestamp = 1 hour ago (within a 24h window)
      • r2 with timestamp = 5 hours ago (within a 24h window)
      • r3 with timestamp = 48 hours ago (outside a 24h window)

    Run the migrated query — `SELECT COUNT(*) FROM system_metrics WHERE
    timestamp >= ? ORDER BY timestamp ASC` with the cutoff computed in Python
    (now_utc - timedelta(hours=24)) as the bound parameter — and assert the
    result contains only r1 and r2 (r3 is filtered out).

    This verifies the cross-engine fix: the SQLite-only `datetime('now', ? ||
    ' hours')` literal is replaced with a Python-side cutoff bound as a single
    parameter, so the same SQL parses and executes on both engines.
    """
    conn = conn_engine

    now_utc = _dt.datetime.now(_dt.timezone.utc).replace(tzinfo=None)
    ts_recent = (now_utc - _dt.timedelta(hours=1)).isoformat()
    ts_mid = (now_utc - _dt.timedelta(hours=5)).isoformat()
    ts_stale = (now_utc - _dt.timedelta(hours=48)).isoformat()
    cutoff = (now_utc - _dt.timedelta(hours=24)).isoformat()

    insert_sql = (
        "INSERT INTO system_metrics (snapshot_id, timestamp, cpu_pct) "
        "VALUES (?, ?, ?)"
    )
    conn.execute(insert_sql, ("recent-1", ts_recent, 10.0))
    conn.execute(insert_sql, ("mid-5", ts_mid, 20.0))
    conn.execute(insert_sql, ("stale-48", ts_stale, 30.0))
    conn.commit()

    # Mirror the rewritten route query verbatim — `datetime('now', ? || ' hours')`
    # replaced by a `?` placeholder bound to the Python-computed cutoff ISO ts.
    cur = conn.execute(
        "SELECT snapshot_id, timestamp FROM system_metrics "
        "WHERE timestamp >= ? "
        "ORDER BY timestamp ASC",
        (cutoff,),
    )
    rows = cur.fetchall()
    snapshot_ids = [r["snapshot_id"] for r in rows]

    assert "stale-48" not in snapshot_ids, (
        f"Stale row (48h ago) should be filtered by 24h cutoff, got {snapshot_ids}"
    )
    assert "recent-1" in snapshot_ids
    assert "mid-5" in snapshot_ids
    assert len(rows) == 2, (
        f"Expected exactly 2 rows within 24h cutoff (recent + mid), got "
        f"{len(rows)}: {snapshot_ids}"
    )


# ---------------------------------------------------------------------------
# Test — the route source no longer contains the SQLite-only datetime('now')
# literal (regression guard)
# ---------------------------------------------------------------------------


def test_route_source_has_no_datetime_now_literal():
    """Static-analysis guard: confirm `datetime('now'` no longer appears.

    The migrated route MUST NOT contain `datetime('now'` because it's
    SQLite-only and crashes psycopg2's date-function resolution on PG.
    """
    import inspect

    import src.api.routes.system as mod

    source = inspect.getsource(mod)
    assert "datetime('now'" not in source, (
        "src/api/routes/system.py still contains the SQLite-only literal "
        "datetime('now' — the T5 migration must replace it with a "
        "parameterized timestamp cutoff computed in Python."
    )
