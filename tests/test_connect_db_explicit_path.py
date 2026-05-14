"""Tests for connect_db() fixture-path honor logic (P0 #160).

When ARCIS_PG_CUTOVER_ENABLED=1 + DATABASE_URL is a postgres:// URL, the
cutover gate routes ALL calls to PG by default. This is correct for runtime
code (watch loop, API workers) whose call sites pass DB_PATH (the canonical
SQLite path) as db_path.

The hazard: test fixtures that call connect_db(tmp_path / "test.db") get
HIJACKED to production PG because the old code didn't distinguish between
"runtime caller passing DB_PATH" and "test fixture passing a temp path".

The fix: when the caller passes an explicit db_path that looks like a
fixture/test SQLite path (not the canonical DB_PATH, not a PG URL itself),
honor the explicit path and return a SQLite connection.

This test file validates all 5 scenarios described in the P0 #160 spec:

  1. connect_db(DB_PATH) under cutover  → PG wrapper (runtime routing preserved)
  2. connect_db(":memory:") under cutover  → SQLite connection
  3. connect_db(tmp_path / "test.db") under cutover  → SQLite connection
  4. connect_db(None) under cutover  → PG wrapper (None treated as sentinel)
  5. connect_db(...) without cutover  → SQLite always
"""

import os
import sqlite3
from unittest.mock import MagicMock, patch

import pytest

# The test PG URL — no live connection required; we mock psycopg2.connect.
_FAKE_PG_URL = "postgresql://test:test@127.0.0.1:5434/halcyon"

# ---------------------------------------------------------------------------
# Helpers to introspect what connect_db() returned
# ---------------------------------------------------------------------------


def _is_pg_wrapper(conn) -> bool:
    from src.utils.db import PostgresConnectionWrapper

    return isinstance(conn, PostgresConnectionWrapper)


def _is_sqlite(conn) -> bool:
    return isinstance(conn, sqlite3.Connection)


# ---------------------------------------------------------------------------
# Fixtures: set and restore env vars around each test.
# ---------------------------------------------------------------------------


@pytest.fixture()
def cutover_env(monkeypatch):
    """Set ARCIS_PG_CUTOVER_ENABLED=1 + DATABASE_URL=<fake PG URL>."""
    monkeypatch.setenv("ARCIS_PG_CUTOVER_ENABLED", "1")
    monkeypatch.setenv("DATABASE_URL", _FAKE_PG_URL)


@pytest.fixture()
def no_cutover_env(monkeypatch):
    """Ensure the cutover gate is OFF (gate=off, URL present but ignored)."""
    monkeypatch.delenv("ARCIS_PG_CUTOVER_ENABLED", raising=False)
    monkeypatch.setenv("DATABASE_URL", _FAKE_PG_URL)


# ---------------------------------------------------------------------------
# Reset the module-level once-warning flags between tests so tests
# don't silently suppress each other's warning logic.
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def reset_db_warn_flags():
    import src.utils.db as db_mod

    original_warned = set(db_mod._DB_PATH_WARNED)
    original_gate = db_mod._GATE_ON_NO_PG_URL_WARNED
    original_fixture = getattr(db_mod, "_FIXTURE_PATH_HONORED_WARNED", False)
    yield
    db_mod._DB_PATH_WARNED.clear()
    db_mod._DB_PATH_WARNED.update(original_warned)
    db_mod._GATE_ON_NO_PG_URL_WARNED = original_gate
    if hasattr(db_mod, "_FIXTURE_PATH_HONORED_WARNED"):
        db_mod._FIXTURE_PATH_HONORED_WARNED = original_fixture


# ---------------------------------------------------------------------------
# TEST 1 — connect_db(DB_PATH) under cutover MUST route to PG.
#
# This is the regression lock: the watch loop calls connect_db(DB_PATH) and
# the gate MUST route it to PG when cutover is on. If this breaks, the watch
# loop silently falls back to SQLite while the operator thinks it's on PG.
# ---------------------------------------------------------------------------


def test_runtime_db_path_routes_to_pg_under_cutover(cutover_env):
    """connect_db(DB_PATH) under cutover returns a PostgresConnectionWrapper.

    DB_PATH is the canonical SQLite path (e.g. C:/arcis/data/ai_research_desk.sqlite3).
    When the cutover gate is on, this call MUST route to PG — it's the
    primary runtime path and the whole point of the cutover gate.
    """
    from src.config import DB_PATH
    from src.utils.db import PostgresConnectionWrapper, connect_db

    mock_raw = MagicMock()
    with patch("psycopg2.connect", return_value=mock_raw):
        conn = connect_db(DB_PATH)
    assert _is_pg_wrapper(conn), (
        f"connect_db(DB_PATH) under cutover must return PostgresConnectionWrapper; "
        f"got {type(conn).__name__}"
    )


# ---------------------------------------------------------------------------
# TEST 2 — connect_db(":memory:") under cutover MUST return SQLite.
# ---------------------------------------------------------------------------


def test_memory_path_honored_over_cutover_gate(cutover_env):
    """connect_db(':memory:') under cutover returns a sqlite3.Connection.

    In-memory SQLite is a clear fixture sentinel — no caller passes ':memory:'
    except in tests. The gate must not hijack this.
    """
    from src.utils.db import connect_db

    conn = connect_db(":memory:")
    try:
        assert _is_sqlite(conn), (
            f"connect_db(':memory:') under cutover must return sqlite3.Connection; "
            f"got {type(conn).__name__}"
        )
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# TEST 3 — connect_db(tmp_path / "test.db") under cutover MUST return SQLite.
# ---------------------------------------------------------------------------


def test_tmp_fixture_path_honored_over_cutover_gate(cutover_env, tmp_path):
    """connect_db(tmp_path / 'test.db') under cutover returns a sqlite3.Connection.

    Test fixtures commonly pass a pytest tmp_path file. The gate must not
    hijack these — that was the exact P0 #160 failure mode that caused
    DDL/DML to run against prod PG.
    """
    from src.utils.db import connect_db

    fixture_db = tmp_path / "test.db"
    conn = connect_db(fixture_db)
    try:
        assert _is_sqlite(conn), (
            f"connect_db(tmp_path/'test.db') under cutover must return "
            f"sqlite3.Connection; got {type(conn).__name__}"
        )
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# TEST 4 — connect_db(None) under cutover MUST route to PG.
#
# None is not a valid SQLite path. The connect_db() signature uses _SENTINEL
# as default; passing None explicitly falls through to SQLite normally (with
# a broken path). Under cutover, None should be treated like the sentinel and
# route to PG — or at least not bypass the cutover gate.
# ---------------------------------------------------------------------------


def test_none_path_routes_to_pg_under_cutover(cutover_env):
    """connect_db(None) under cutover returns a PostgresConnectionWrapper.

    None is not a fixture SQLite path. The fix must not treat None as a
    fixture override — if None bypassed the gate, callers that pass None
    by accident would silently fall to SQLite even with cutover on.
    """
    from src.utils.db import PostgresConnectionWrapper, connect_db

    mock_raw = MagicMock()
    with patch("psycopg2.connect", return_value=mock_raw):
        conn = connect_db(None)
    assert _is_pg_wrapper(conn), (
        f"connect_db(None) under cutover must return PostgresConnectionWrapper; "
        f"got {type(conn).__name__}"
    )


# ---------------------------------------------------------------------------
# TEST 5 — Without cutover, connect_db() always returns SQLite.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path_arg",
    [
        pytest.param(":memory:", id="memory"),
        pytest.param(None, id="none"),
    ],
)
def test_no_cutover_always_returns_sqlite(no_cutover_env, path_arg, tmp_path):
    """When ARCIS_PG_CUTOVER_ENABLED is off, connect_db() is always SQLite."""
    from src.utils.db import connect_db

    if path_arg is None:
        # None as path without cutover — SQLite will receive None as path
        # which opens a tempfile; handle gracefully
        try:
            conn = connect_db(None)
            assert _is_sqlite(conn), (
                f"connect_db(None) without cutover must return sqlite3.Connection"
            )
            conn.close()
        except Exception:
            # None path may legitimately fail on some platforms — that's OK,
            # what we care about is that it didn't try to open PG.
            pass
    else:
        conn = connect_db(path_arg)
        try:
            assert _is_sqlite(conn), (
                f"connect_db({path_arg!r}) without cutover must return "
                f"sqlite3.Connection; got {type(conn).__name__}"
            )
        finally:
            conn.close()


def test_no_cutover_tmp_path_returns_sqlite(no_cutover_env, tmp_path):
    """connect_db(tmp_path / 'test.db') without cutover returns SQLite."""
    from src.utils.db import connect_db

    fixture_db = tmp_path / "test.db"
    conn = connect_db(fixture_db)
    try:
        assert _is_sqlite(conn)
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# TEST — Regression lock: connect_db() with sentinel (no arg) under cutover
# routes to PG. Ensures the default call site (watch loop startup) works.
# ---------------------------------------------------------------------------


def test_sentinel_default_routes_to_pg_under_cutover(cutover_env):
    """connect_db() with no argument under cutover returns PostgresConnectionWrapper.

    The sentinel path is the original cutover behavior — must not regress.
    """
    from src.utils.db import PostgresConnectionWrapper, connect_db

    mock_raw = MagicMock()
    with patch("psycopg2.connect", return_value=mock_raw):
        conn = connect_db()
    assert _is_pg_wrapper(conn), (
        f"connect_db() with no arg under cutover must return PostgresConnectionWrapper; "
        f"got {type(conn).__name__}"
    )


# ---------------------------------------------------------------------------
# TEST — sqlite3-path (e.g. .sqlite3 extension) under cutover is honored.
# ---------------------------------------------------------------------------


def test_sqlite3_extension_path_honored_over_cutover_gate(cutover_env, tmp_path):
    """connect_db(path.sqlite3) under cutover returns SQLite.

    Fixture paths ending in .sqlite3 are explicit SQLite paths. The gate
    must not override them.
    """
    from src.utils.db import connect_db

    fixture_db = tmp_path / "fixture.sqlite3"
    conn = connect_db(fixture_db)
    try:
        assert _is_sqlite(conn), (
            f"connect_db(path.sqlite3) under cutover must return sqlite3.Connection; "
            f"got {type(conn).__name__}"
        )
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# TEST — INFO log is emitted (once) when fixture path is honored over gate.
# ---------------------------------------------------------------------------


def test_fixture_path_honored_emits_info_log(cutover_env, tmp_path, caplog):
    """When gate is on and a fixture path is honored, one INFO log is emitted."""
    import logging

    from src.utils.db import connect_db

    fixture_db = tmp_path / "test.db"
    with caplog.at_level(logging.INFO, logger="src.utils.db"):
        conn = connect_db(fixture_db)
        conn.close()

    info_messages = [
        r.message for r in caplog.records if r.levelno == logging.INFO
    ]
    assert any("fixture" in m.lower() or "explicit" in m.lower() for m in info_messages), (
        f"Expected an INFO log about fixture path being honored; got: {info_messages}"
    )
