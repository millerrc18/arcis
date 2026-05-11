"""Tests for `src/api/routes/ib_status.py` — Sprint 5 §J5/§J6 Phase 2 T2.10.

Verifies the SQLite-only `date('now')` literal at :55 has been replaced with
a parameterized `date(created_at) = ?` query whose parameter is computed in
Python (`datetime.date.today().isoformat()`).

The `date(...)` SQL function works on BOTH SQLite and Postgres (it's ANSI
standard syntax) — the engine-specific part was `date('now')`, which is
SQLite-only (PG uses `CURRENT_DATE`). Parameterizing the literal solves the
cross-engine compatibility issue without depending on engine-specific
date-literal syntax.

Parametrized over [sqlite, postgres]. The Postgres variant skips cleanly when
`TEST_DATABASE_URL` is unset (operator laptops, CI without a test PG instance).
"""

import datetime as _datetime
import os
import sqlite3
import tempfile

import pytest


TEST_PG_URL = os.environ.get("TEST_DATABASE_URL") or os.environ.get(
    "DATABASE_URL", ""
)
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
        pytest.skip("TEST_DATABASE_URL / DATABASE_URL not set or not postgres://")

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
# Test — parameterized today-date query matches today's rows on both engines
# ---------------------------------------------------------------------------


def test_today_date_query_matches_today_rows_only(conn_engine):
    """T2.10: parameterized `date(created_at) = ?` matches today, skips others.

    Insert two rows:
      • r1 with created_at = today (full ISO timestamp)
      • r2 with created_at = yesterday

    Run the migrated query — `SELECT COUNT(*) FROM ib_shadow_log WHERE
    date(created_at) = ?` with `datetime.date.today().isoformat()` as the
    bound parameter — and assert the result is 1 (only r1 matches).

    This verifies the cross-engine fix: `date(...)` is ANSI standard
    (works on both SQLite and PG), and parameterizing the today-literal
    removes the SQLite-only `date('now')` dependency.
    """
    conn = conn_engine
    today = _datetime.date.today()
    today_iso = today.isoformat()
    today_ts = f"{today_iso}T12:00:00"
    yesterday_iso = (today - _datetime.timedelta(days=1)).isoformat()
    yesterday_ts = f"{yesterday_iso}T12:00:00"

    insert_sql = (
        "INSERT INTO ib_shadow_log (shadow_id, created_at, ticker, ib_connected) "
        "VALUES (?, ?, ?, ?)"
    )
    conn.execute(insert_sql, ("today-1", today_ts, "AAPL", 1))
    conn.execute(insert_sql, ("yesterday-1", yesterday_ts, "AAPL", 1))
    conn.commit()

    cur = conn.execute(
        "SELECT COUNT(*) AS total, "
        "SUM(CASE WHEN ib_connected = 1 THEN 1 ELSE 0 END) AS connected "
        "FROM ib_shadow_log WHERE date(created_at) = ?",
        (today_iso,),
    )
    row = cur.fetchone()
    total = row["total"]
    connected = row["connected"] or 0
    assert total == 1, (
        f"Expected exactly 1 row matching today's date {today_iso}, got {total}"
    )
    assert connected == 1


# ---------------------------------------------------------------------------
# Test — the route source no longer contains the SQLite-only date('now')
# literal at the shadow-log site (regression guard)
# ---------------------------------------------------------------------------


def test_route_source_has_no_date_now_literal():
    """Static-analysis guard: confirm date('now') no longer appears in the route.

    The migrated route MUST NOT contain `date('now')` because it's
    SQLite-only and would crash psycopg2's `date('now')` resolution on PG.
    """
    import inspect

    import src.api.routes.ib_status as mod

    source = inspect.getsource(mod)
    assert "date('now')" not in source, (
        "ib_status.py still contains the SQLite-only literal date('now') "
        "— the T2.10 migration must replace it with a parameterized "
        "date(created_at) = ? query."
    )
