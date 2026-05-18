"""Tests for `src/api/routes/ib_status.py` 30-day uptime query — Sprint 5 §J5/§J6 Phase 2.5 T6.

Verifies the SQLite-only `datetime('now', '-30 days')` literal at :76 has
been replaced with a parameterized `created_at >= ?` query whose parameter
is computed in Python (`(datetime.now() - timedelta(days=30)).isoformat()`).

The T2.10 agent flagged this as a sibling-search finding when migrating the
`date('now')` site at :55. This task closes that gap: same engine-
incompatibility class (SQLite-only date literal that PG rejects), same
parameterization fix, separate test file (T2.10's test stays focused on the
today-date query).

Parametrized over [sqlite, postgres]. The Postgres variant skips cleanly
when `TEST_DATABASE_URL` is unset (operator laptops, CI without a test PG).
"""

import datetime as _datetime
import os
import sqlite3
import tempfile

import pytest


TEST_PG_URL = os.environ.get("TEST_DATABASE_URL", "")
_PG_AVAILABLE = TEST_PG_URL.startswith("postgres")


# ---------------------------------------------------------------------------
# Fixtures — sqlite + (optional) pg conn for ib_shadow_log
# ---------------------------------------------------------------------------


@pytest.fixture
def sqlite_db():
    """SQLite tmp database with the ib_shadow_log table provisioned."""
    fd, path = tempfile.mkstemp(suffix=".sqlite3")
    os.close(fd)
    from tests.conftest import init_test_db

    init_test_db(path, ["ib_shadow_log"])
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

    Bootstraps `ib_shadow_log` from the registry's PG DDL and drops the
    table on teardown so this fixture is self-contained.
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
    cur.execute("DROP TABLE IF EXISTS ib_shadow_log CASCADE")
    cur.execute(generate_create_sql(TABLES["ib_shadow_log"]))
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
            cleanup.execute("DROP TABLE IF EXISTS ib_shadow_log CASCADE")
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
# Test — parameterized 30-day window query matches recent rows on both engines
# ---------------------------------------------------------------------------


def test_uptime_30d_window_query_matches_recent_rows_only(conn_engine):
    """T6: parameterized `created_at >= ?` matches last 30 days, skips older.

    Insert three rows:
      • r1 with created_at = now  (full ISO timestamp, today)
      • r2 with created_at = 10 days ago
      • r3 with created_at = 60 days ago

    Run the migrated query — `SELECT COUNT(*) FROM ib_shadow_log WHERE
    created_at >= ?` with `(datetime.now() - timedelta(days=30)).isoformat()`
    as the bound parameter — and assert the result is 2 (r1, r2 only).

    This verifies the cross-engine fix: parameterizing the cutoff removes
    the SQLite-only `datetime('now', '-30 days')` dependency that crashes
    on Postgres.
    """
    conn = conn_engine
    now = _datetime.datetime.now()
    today_ts = now.isoformat()
    ten_days_ago_ts = (now - _datetime.timedelta(days=10)).isoformat()
    sixty_days_ago_ts = (now - _datetime.timedelta(days=60)).isoformat()
    cutoff_30d = (now - _datetime.timedelta(days=30)).isoformat()

    insert_sql = (
        "INSERT INTO ib_shadow_log (shadow_id, created_at, ticker, ib_connected) "
        "VALUES (?, ?, ?, ?)"
    )
    conn.execute(insert_sql, ("today-1", today_ts, "AAPL", 1))
    conn.execute(insert_sql, ("ten-days-1", ten_days_ago_ts, "AAPL", 1))
    conn.execute(insert_sql, ("sixty-days-1", sixty_days_ago_ts, "AAPL", 0))
    conn.commit()

    cur = conn.execute(
        "SELECT COUNT(*) AS total, "
        "SUM(CASE WHEN ib_connected = 1 THEN 1 ELSE 0 END) AS connected "
        "FROM ib_shadow_log WHERE created_at >= ?",
        (cutoff_30d,),
    )
    row = cur.fetchone()
    total = row["total"]
    connected = row["connected"] or 0
    assert total == 2, (
        f"Expected exactly 2 rows within 30 days of {cutoff_30d}, got {total}"
    )
    assert connected == 2


# ---------------------------------------------------------------------------
# Test — the route source no longer contains the SQLite-only datetime('now', ...)
# literal at the 30-day uptime site (regression guard)
# ---------------------------------------------------------------------------


def test_route_source_has_no_datetime_now_literal():
    """Static-analysis guard: confirm datetime('now' no longer appears in the route.

    The migrated route MUST NOT contain `datetime('now'` because it's
    SQLite-only and would crash on PG.
    """
    import inspect

    import src.api.routes.ib_status as mod

    source = inspect.getsource(mod)
    assert "datetime('now'" not in source, (
        "ib_status.py still contains the SQLite-only literal datetime('now' "
        "— the T6 migration must replace it with a parameterized "
        "`created_at >= ?` query."
    )
