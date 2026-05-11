"""Tests for src/utils/db.py — SQLite connection helper.

Covers: #160 (busy_timeout on all connections).
"""

import sqlite3
from unittest.mock import MagicMock, patch

import pytest


def test_connect_db_uses_sqlite_when_database_url_unset(monkeypatch):
    """connect_db with no args and no DATABASE_URL should return a sqlite3.Connection.

    Uses `setenv("", "")` instead of `delenv` because python-dotenv runs at
    module import time (via src.config) with default override=False, which
    would re-set DATABASE_URL from .env if it's missing from os.environ.
    Setting it to empty string ensures the env var is present but the
    startswith("postgres") check returns False.
    """
    monkeypatch.setenv("DATABASE_URL", "")
    from src.utils.db import connect_db
    conn = connect_db()
    assert type(conn) is sqlite3.Connection
    conn.close()


def test_connect_db_uses_postgres_when_database_url_postgres_scheme(monkeypatch):
    """connect_db with DATABASE_URL=postgresql://... should call psycopg2.connect and return a wrapper.

    Phase 3 T3.2: ARCIS_PG_CUTOVER_ENABLED=1 must also be set, or the gate
    keeps routing to SQLite (developer-machine safety).
    """
    import psycopg2.extras
    pg_url = "postgresql://halcyon:pw@localhost:5433/halcyon"
    monkeypatch.setenv("DATABASE_URL", pg_url)
    monkeypatch.setenv("ARCIS_PG_CUTOVER_ENABLED", "1")
    sentinel_conn = MagicMock(name="pg_raw_conn")
    with patch("psycopg2.connect", return_value=sentinel_conn) as mock_pg:
        from src.utils.db import connect_db
        wrapper = connect_db()
        mock_pg.assert_called_once_with(pg_url, cursor_factory=psycopg2.extras.RealDictCursor)
    assert hasattr(wrapper, "cursor")
    assert hasattr(wrapper, "execute")
    assert hasattr(wrapper, "executemany")
    assert hasattr(wrapper, "commit")
    assert hasattr(wrapper, "rollback")
    assert hasattr(wrapper, "close")
    assert hasattr(wrapper, "row_factory")


def test_connect_db_explicit_db_path_forces_sqlite_when_gate_off(tmp_path, monkeypatch):
    """An explicit db_path arg uses SQLite when the gate is OFF, even when DATABASE_URL is set.

    Phase 3-revised: explicit path → SQLite is only the behavior when the gate
    is OFF. With gate ON + PG URL, the gate takes precedence (see
    test_truth_row8_gate_pg_url_explicit_path_IGNORED for the gate-ON case).
    """
    monkeypatch.setenv("DATABASE_URL", "postgresql://halcyon:pw@localhost:5433/halcyon")
    monkeypatch.delenv("ARCIS_PG_CUTOVER_ENABLED", raising=False)
    db_path = str(tmp_path / "test.sqlite3")
    from src.utils.db import connect_db
    conn = connect_db(db_path=db_path)
    assert type(conn) is sqlite3.Connection
    conn.close()


def test_pg_wrapper_exposes_required_methods(monkeypatch):
    """The PG wrapper class must expose cursor, execute, executemany, commit, rollback, close, row_factory.

    Phase 3 T3.2: ARCIS_PG_CUTOVER_ENABLED=1 must also be set to route to PG.
    """
    pg_url = "postgresql://halcyon:pw@localhost:5433/halcyon"
    monkeypatch.setenv("DATABASE_URL", pg_url)
    monkeypatch.setenv("ARCIS_PG_CUTOVER_ENABLED", "1")
    sentinel_conn = MagicMock(name="pg_raw_conn")
    with patch("psycopg2.connect", return_value=sentinel_conn):
        from src.utils.db import connect_db
        wrapper = connect_db()
    for method in ("cursor", "execute", "executemany", "commit", "rollback", "close"):
        assert callable(getattr(wrapper, method)), f"wrapper.{method} must be callable"
    assert hasattr(wrapper, "row_factory")


def test_connect_db_sets_busy_timeout(tmp_path, monkeypatch):
    """connect_db should set PRAGMA busy_timeout=30000 (30s) on the SQLite path.

    Bumped from 5000 after 2026-04-19 incident: MS Access held the DB file
    lock while the operator inspected data, causing 118 'database is locked'
    errors. 30s rides through typical external-tool locks.

    Requires DATABASE_URL cleared since the post-2026-05-10 precedence is
    "DATABASE_URL wins, db_path advisory" — without delenv the test routes
    to PG and asserts on PostgresConnectionWrapper, which is wrong scope.
    """
    monkeypatch.delenv("DATABASE_URL", raising=False)
    db_path = str(tmp_path / "test.sqlite3")
    from src.utils.db import BUSY_TIMEOUT_MS, connect_db
    conn = connect_db(db_path)
    result = conn.execute("PRAGMA busy_timeout").fetchone()
    assert result[0] == 30000
    assert BUSY_TIMEOUT_MS == 30000
    conn.close()


def test_connect_db_sets_row_factory(tmp_path, monkeypatch):
    """connect_db should set row_factory to sqlite3.Row on the SQLite path."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    db_path = str(tmp_path / "test.sqlite3")
    from src.utils.db import connect_db
    conn = connect_db(db_path)
    assert conn.row_factory is sqlite3.Row
    conn.close()


def test_connect_db_default_path(monkeypatch):
    """connect_db with no args and no DATABASE_URL should use default SQLite path."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    from src.utils.db import connect_db, DEFAULT_DB
    conn = connect_db()
    assert conn is not None
    conn.close()


# ---------------------------------------------------------------------------
# Phase 3 T3.2 — ARCIS_PG_CUTOVER_ENABLED gate tests
# ---------------------------------------------------------------------------

def test_connect_db_routes_to_sqlite_when_cutover_disabled_even_with_pg_url(monkeypatch):
    """Gate OFF + PG DATABASE_URL → SQLite.

    Asserts developer-box post-merge behavior: if ARCIS_PG_CUTOVER_ENABLED is
    absent (unset), connect_db() stays on SQLite even when DATABASE_URL is a
    postgres URL. This is the M2 invariant — merging T3.2 to main is a no-op
    on any dev machine that happens to have a stale DATABASE_URL in shell.
    The 2026-05-10 cutover attempt failed in 2 minutes from exactly this shape.
    """
    pg_url = "postgresql://halcyon:halcyon@127.0.0.1:5433/halcyon"
    monkeypatch.setenv("DATABASE_URL", pg_url)
    monkeypatch.delenv("ARCIS_PG_CUTOVER_ENABLED", raising=False)
    from src.utils.db import connect_db
    conn = connect_db()
    assert type(conn) is sqlite3.Connection, (
        f"Expected sqlite3.Connection with gate OFF, got {type(conn).__name__}"
    )
    conn.close()


def test_connect_db_routes_to_pg_when_cutover_enabled_and_pg_url_set(monkeypatch):
    """Gate ON + PG DATABASE_URL → PostgresConnectionWrapper.

    Asserts production behavior: both ARCIS_PG_CUTOVER_ENABLED=1 AND a
    DATABASE_URL starting with 'postgres' are required to route to PG.
    psycopg2.connect is mocked so no real network connection is opened.
    """
    import psycopg2.extras
    from src.utils.db import PostgresConnectionWrapper
    pg_url = "postgresql://halcyon:halcyon@127.0.0.1:5433/halcyon"
    monkeypatch.setenv("DATABASE_URL", pg_url)
    monkeypatch.setenv("ARCIS_PG_CUTOVER_ENABLED", "1")
    sentinel_conn = MagicMock(name="pg_raw_conn")
    with patch("psycopg2.connect", return_value=sentinel_conn) as mock_pg:
        from src.utils.db import connect_db
        conn = connect_db()
        mock_pg.assert_called_once_with(pg_url, cursor_factory=psycopg2.extras.RealDictCursor)
    assert isinstance(conn, PostgresConnectionWrapper), (
        f"Expected PostgresConnectionWrapper with gate ON + PG URL, got {type(conn).__name__}"
    )


def test_connect_db_routes_to_sqlite_when_cutover_enabled_but_no_pg_url(monkeypatch):
    """Gate ON + no DATABASE_URL → SQLite.

    Asserts the gate alone does not synthesize a PG connection. The gate is
    a guard, not a URL source. Without DATABASE_URL starting with 'postgres',
    connect_db() falls through to the default SQLite path regardless of the
    gate setting.  Phase 3-revised: unchanged behavior (gate-on + no PG URL → SQLite).
    """
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("ARCIS_PG_CUTOVER_ENABLED", "1")
    from src.utils.db import connect_db
    conn = connect_db()
    assert type(conn) is sqlite3.Connection, (
        f"Expected sqlite3.Connection with gate ON but no PG URL, got {type(conn).__name__}"
    )
    conn.close()


# ---------------------------------------------------------------------------
# Phase 3-revised — 8-row truth table + warn-once + retry parity
# (spec-revised-one-db.md §2.1)
# ---------------------------------------------------------------------------

_PG_URL = "postgresql://halcyon:pw@localhost:5433/halcyon"


def test_truth_row1_no_gate_no_url_no_path(monkeypatch):
    """Row 1: gate=off, url=off, path=sentinel → sqlite3.Connection at DEFAULT_DB."""
    monkeypatch.setenv("DATABASE_URL", "")
    monkeypatch.delenv("ARCIS_PG_CUTOVER_ENABLED", raising=False)
    from src.utils.db import connect_db
    conn = connect_db()
    assert type(conn) is sqlite3.Connection
    conn.close()


def test_truth_row2_no_gate_no_url_explicit_path(tmp_path, monkeypatch):
    """Row 2: gate=off, url=off, path=:memory: → sqlite3.Connection at :memory:."""
    monkeypatch.setenv("DATABASE_URL", "")
    monkeypatch.delenv("ARCIS_PG_CUTOVER_ENABLED", raising=False)
    from src.utils.db import connect_db
    conn = connect_db(db_path=":memory:")
    assert type(conn) is sqlite3.Connection
    conn.close()


def test_truth_row3_no_gate_pg_url_no_path(monkeypatch):
    """Row 3: gate=off, url=pg, path=sentinel → sqlite3.Connection (gate-off ignores url)."""
    monkeypatch.setenv("DATABASE_URL", _PG_URL)
    monkeypatch.delenv("ARCIS_PG_CUTOVER_ENABLED", raising=False)
    from src.utils.db import connect_db
    conn = connect_db()
    assert type(conn) is sqlite3.Connection, (
        f"Expected SQLite with gate off, got {type(conn).__name__}"
    )
    conn.close()


def test_truth_row4_no_gate_pg_url_explicit_path(tmp_path, monkeypatch):
    """Row 4: gate=off, url=pg, path=:memory: → sqlite3.Connection at :memory:."""
    monkeypatch.setenv("DATABASE_URL", _PG_URL)
    monkeypatch.delenv("ARCIS_PG_CUTOVER_ENABLED", raising=False)
    from src.utils.db import connect_db
    conn = connect_db(db_path=":memory:")
    assert type(conn) is sqlite3.Connection
    conn.close()


def test_truth_row5_gate_no_url_no_path(monkeypatch):
    """Row 5: gate=on, url=off, path=sentinel → sqlite3.Connection (gate-on requires url too)."""
    monkeypatch.setenv("DATABASE_URL", "")
    monkeypatch.setenv("ARCIS_PG_CUTOVER_ENABLED", "1")
    from src.utils.db import connect_db
    conn = connect_db()
    assert type(conn) is sqlite3.Connection, (
        f"Expected SQLite with gate on but no PG URL, got {type(conn).__name__}"
    )
    conn.close()


def test_truth_row6_gate_no_url_explicit_path(tmp_path, monkeypatch):
    """Row 6: gate=on, url=off, path=:memory: → sqlite3.Connection at :memory:."""
    monkeypatch.setenv("DATABASE_URL", "")
    monkeypatch.setenv("ARCIS_PG_CUTOVER_ENABLED", "1")
    from src.utils.db import connect_db
    conn = connect_db(db_path=":memory:")
    assert type(conn) is sqlite3.Connection
    conn.close()


def test_truth_row7_gate_pg_url_no_path(monkeypatch):
    """Row 7: gate=on, url=pg, path=sentinel → PostgresConnectionWrapper."""
    from src.utils.db import PostgresConnectionWrapper
    monkeypatch.setenv("DATABASE_URL", _PG_URL)
    monkeypatch.setenv("ARCIS_PG_CUTOVER_ENABLED", "1")
    sentinel_conn = MagicMock(name="pg_raw_conn")
    with patch("psycopg2.connect", return_value=sentinel_conn):
        from src.utils.db import connect_db
        conn = connect_db()
    assert isinstance(conn, PostgresConnectionWrapper), (
        f"Expected PostgresConnectionWrapper, got {type(conn).__name__}"
    )


def test_truth_row8_gate_pg_url_explicit_path_IGNORED(tmp_path, monkeypatch, caplog):
    """Row 8: gate=on, url=pg, path=explicit → PostgresConnectionWrapper (gate overrides path).

    This is the cell that PR #1054 got wrong — explicit db_path must NOT force
    SQLite when both ARCIS_PG_CUTOVER_ENABLED=1 AND DATABASE_URL=postgres are set.
    Also asserts that the WARN log is emitted exactly once for the path override.
    """
    import logging
    from src.utils.db import PostgresConnectionWrapper
    monkeypatch.setenv("DATABASE_URL", _PG_URL)
    monkeypatch.setenv("ARCIS_PG_CUTOVER_ENABLED", "1")
    explicit_path = str(tmp_path / "some_sqlite.db")
    sentinel_conn = MagicMock(name="pg_raw_conn")
    with caplog.at_level(logging.WARNING, logger="src.utils.db"):
        with patch("psycopg2.connect", return_value=sentinel_conn):
            from src.utils.db import connect_db
            conn = connect_db(db_path=explicit_path)
    assert isinstance(conn, PostgresConnectionWrapper), (
        f"Expected PostgresConnectionWrapper with gate ON + explicit path, got {type(conn).__name__}"
    )
    warn_msgs = [r.message for r in caplog.records if r.levelno == logging.WARNING]
    assert any(explicit_path in m or "overridden" in m.lower() for m in warn_msgs), (
        f"Expected WARN about db_path override, got: {warn_msgs}"
    )


def test_retry_wrapper_enters_loop_when_gate_on_even_with_explicit_path(monkeypatch):
    """gate=on, url=pg, db_path passed → retry helper attempts PG (not SQLite passthrough).

    Mocks psycopg2.connect to raise OperationalError twice then succeed.
    Asserts 3 total connect attempts happened.
    """
    import psycopg2
    monkeypatch.setenv("DATABASE_URL", _PG_URL)
    monkeypatch.setenv("ARCIS_PG_CUTOVER_ENABLED", "1")
    from src.utils.db import PostgresConnectionWrapper
    sentinel_conn = MagicMock(name="pg_raw_conn")
    fail_twice = [
        psycopg2.OperationalError("conn refused"),
        psycopg2.OperationalError("conn refused"),
        sentinel_conn,
    ]
    call_count = {"n": 0}

    def mock_connect(*args, **kwargs):
        result = fail_twice[call_count["n"]]
        call_count["n"] += 1
        if isinstance(result, Exception):
            raise result
        return result

    with patch("psycopg2.connect", side_effect=mock_connect):
        with patch("time.sleep"):
            from src.utils.db import connect_db_with_pg_retry
            conn = connect_db_with_pg_retry(db_path=":memory:")
    assert call_count["n"] == 3, f"Expected 3 connect attempts, got {call_count['n']}"
    assert isinstance(conn, PostgresConnectionWrapper)


def test_retry_wrapper_passthrough_when_gate_off_with_explicit_path(tmp_path, monkeypatch):
    """gate=off, db_path=:memory: → identity passthrough to connect_db (no retry, returns SQLite)."""
    monkeypatch.setenv("DATABASE_URL", "")
    monkeypatch.delenv("ARCIS_PG_CUTOVER_ENABLED", raising=False)
    from src.utils.db import connect_db_with_pg_retry
    conn = connect_db_with_pg_retry(db_path=":memory:")
    assert type(conn) is sqlite3.Connection
    conn.close()


def test_warn_once_per_distinct_db_path(monkeypatch, caplog):
    """gate=on, url=pg: two calls with same path → 1 WARN. Call with new path → 2 WARNs total."""
    import logging
    import src.utils.db as db_module
    monkeypatch.setenv("DATABASE_URL", _PG_URL)
    monkeypatch.setenv("ARCIS_PG_CUTOVER_ENABLED", "1")

    path_a = "/path/alpha"
    path_b = "/path/beta"

    sentinel_conn = MagicMock(name="pg_raw_conn")
    with caplog.at_level(logging.WARNING, logger="src.utils.db"):
        with patch("psycopg2.connect", return_value=sentinel_conn):
            from src.utils.db import connect_db

            db_module._DB_PATH_WARNED.discard(id(path_a))
            db_module._DB_PATH_WARNED.discard(id(path_b))

            connect_db(db_path=path_a)
            connect_db(db_path=path_a)

    warn_msgs_a = [r.message for r in caplog.records if r.levelno == logging.WARNING]
    path_a_warns = [m for m in warn_msgs_a if path_a in m or "overridden" in m.lower()]
    assert len(path_a_warns) == 1, (
        f"Expected exactly 1 WARN for path_a after 2 calls, got {len(path_a_warns)}: {path_a_warns}"
    )

    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="src.utils.db"):
        with patch("psycopg2.connect", return_value=sentinel_conn):
            connect_db(db_path=path_b)

    warn_msgs_b = [r.message for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warn_msgs_b) == 1, (
        f"Expected exactly 1 WARN for path_b, got {len(warn_msgs_b)}: {warn_msgs_b}"
    )


def test_warn_once_resets_across_test_isolation_or_not_doc(monkeypatch):
    """Assert _DB_PATH_WARNED is module-level (not per-call); documents bounded id() set behavior."""
    import src.utils.db as db_module
    assert hasattr(db_module, "_DB_PATH_WARNED"), (
        "_DB_PATH_WARNED must be a module-level set in src/utils/db.py"
    )
    assert isinstance(db_module._DB_PATH_WARNED, set), (
        "_DB_PATH_WARNED must be a set instance"
    )
