"""Dual-engine introspection test for src/features/event_risk_score.py:_get_table_columns.

Sprint 5 §J5/§J6 Phase 2 T2.3 — Modified-A migration: replace the inline
`PRAGMA table_info(...)` call at event_risk_score.py:48 with the
engine-aware `engine_aware_column_info` helper from src/utils/db.py.

Parametrized over engine=['sqlite','postgres']. The postgres variant skips
cleanly when TEST_DATABASE_URL is unset — same convention used by
test_db_engine_aware_introspection.py.
"""

import os
import sqlite3
import tempfile

import pytest


# ---------------------------------------------------------------------------
# Postgres fixture detection — skip PG cases when no live cluster reachable.
# ---------------------------------------------------------------------------

TEST_PG_URL = os.environ.get("TEST_DATABASE_URL") or os.environ.get(
    "DATABASE_URL", ""
)
_PG_AVAILABLE = TEST_PG_URL.startswith("postgres")
_PG_SKIP_REASON = "TEST_DATABASE_URL / DATABASE_URL not set or not postgres://"


def _build_sqlite_fixture():
    """Open a SQLite fixture with an economic_calendar table mimicking prod shape."""
    fd, db_path = tempfile.mkstemp(suffix=".sqlite3")
    os.close(fd)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE economic_calendar ("
        "  event_type TEXT,"
        "  event_date TEXT,"
        "  description TEXT"
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
    """Open a PG wrapper fixture with the same economic_calendar shape.

    Skips if TEST_DATABASE_URL is unset. Defensively drops the table on
    setup AND teardown to keep the fixture hermetic across runs.
    """
    import psycopg2
    import psycopg2.extras

    from src.utils.db import PostgresConnectionWrapper

    if not _PG_AVAILABLE:
        pytest.skip(_PG_SKIP_REASON)

    raw = psycopg2.connect(
        TEST_PG_URL, cursor_factory=psycopg2.extras.RealDictCursor
    )
    cur = raw.cursor()
    cur.execute("DROP TABLE IF EXISTS economic_calendar CASCADE")
    cur.execute(
        "CREATE TABLE economic_calendar ("
        "  event_type TEXT,"
        "  event_date TEXT,"
        "  description TEXT"
        ")"
    )
    raw.commit()
    cur.close()

    wrapper = PostgresConnectionWrapper(raw)

    def cleanup():
        try:
            cur2 = raw.cursor()
            cur2.execute("DROP TABLE IF EXISTS economic_calendar CASCADE")
            raw.commit()
            cur2.close()
        except Exception:
            pass
        wrapper.close()

    return wrapper, cleanup


@pytest.fixture
def event_risk_conn(request):
    """Parametrized fixture yielding SQLite or PG connection w/ economic_calendar.

    Tests parametrize via `@pytest.mark.parametrize("engine", ...)` indirectly
    on this fixture and obtain a connection-like object with the
    economic_calendar table created.
    """
    engine = request.param
    if engine == "sqlite":
        conn, cleanup = _build_sqlite_fixture()
    elif engine == "postgres":
        conn, cleanup = _build_pg_fixture()
    else:
        raise ValueError(f"Unknown engine: {engine}")
    try:
        yield conn
    finally:
        cleanup()


# ---------------------------------------------------------------------------
# _get_table_columns must read column names from BOTH engines.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "event_risk_conn", ["sqlite", "postgres"], indirect=True
)
def test_get_table_columns_returns_economic_calendar_columns(event_risk_conn):
    """_get_table_columns returns the lowercase column-name set for economic_calendar.

    Regression test for Sprint 5 §J5/§J6 Phase 2 T2.3: the helper at
    src/features/event_risk_score.py:_get_table_columns must consult the
    engine-aware introspection helper (engine_aware_column_info), not
    `PRAGMA table_info` directly — the latter raises on PG-backed connections.
    """
    from src.features.event_risk_score import _get_table_columns

    cols = _get_table_columns(event_risk_conn, "economic_calendar")
    assert cols == {"event_type", "event_date", "description"}


@pytest.mark.parametrize(
    "event_risk_conn", ["sqlite", "postgres"], indirect=True
)
def test_get_table_columns_returns_empty_set_for_missing_table(event_risk_conn):
    """Missing table yields an empty set on BOTH engines.

    PRAGMA table_info(missing) is silently empty on SQLite; the PG helper
    matches that contract by returning [] for unknown tables, which
    _get_table_columns must then surface as set().
    """
    from src.features.event_risk_score import _get_table_columns

    cols = _get_table_columns(event_risk_conn, "this_table_does_not_exist_xyz")
    assert cols == set()
