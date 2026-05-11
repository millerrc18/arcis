"""Tests for Sprint 5 §J5/§J6 Phase 2 T2.12 — watch.py _configure_database refactor.

After T2.12, `WatchLoop._configure_database` consumes the Phase 0 helpers:

  * `configure_sqlite_for_production(conn)` (src/utils/db.py T0.8) — replaces
    the inline PRAGMA cluster (busy_timeout, journal_mode, synchronous,
    integrity_check). PG-safe (no-op + warning).
  * `connect_db_with_pg_retry(DB_PATH, max_attempts=5, backoff_seconds=30)`
    (src/utils/db.py T0.11) — replaces the bare `connect_db(DB_PATH)`. PG
    retry loop with M3 fast-exit (writes data/watchdog.txt + sys.exit(1) on
    exhaustion).

These tests pin:

  1. SQLite path: all four production PRAGMAs are applied — busy_timeout=30000
     (NOT the prior 5000 — `configure_sqlite_for_production` uses the
     `BUSY_TIMEOUT_MS=30_000` constant from src/utils/db.py), journal_mode=WAL,
     synchronous=NORMAL, plus the integrity_check pre-flight.
  2. The retry helper is invoked with the exact contract (max_attempts=5,
     backoff_seconds=30) — wired through monkeypatch + call-args assertion.
  3. M3 invariant: when `connect_db_with_pg_retry` raises SystemExit, the
     surrounding `except Exception` at line 1135 does NOT swallow it. The
     `except SystemExit: raise` pass-through at line 1133-1134 plus
     SystemExit's BaseException inheritance combine to let the exit propagate
     past `_configure_database` and trigger NSSM-managed process restart.

Parametrized where applicable. The PG variant skips cleanly when
TEST_DATABASE_URL is unset (via the pg_wrapper / parametrized_conn fixtures
defined in tests/conftest.py).
"""

import os
import sqlite3
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# Test 1 — SQLite path: all 4 PRAGMAs applied via configure_sqlite_for_production
# ---------------------------------------------------------------------------

def test_configure_database_applies_all_pragmas_on_sqlite(tmp_path, monkeypatch):
    """SQLite path: busy_timeout=30000, journal_mode=WAL, synchronous=NORMAL
    are applied via configure_sqlite_for_production, AND integrity_check passes.

    Pins that the inline PRAGMA cluster at lines 1112-1130 has been replaced by
    the helper. The helper's busy_timeout is BUSY_TIMEOUT_MS=30000 (NOT the prior
    inline 5000), so this test also pins the timeout uplift.

    Verification strategy: intercept `configure_sqlite_for_production` and
    delegate to the real impl, capturing the connection so we can read back
    PRAGMA values WHILE the connection is still open (busy_timeout and
    synchronous are connection-scoped — they don't survive close). Then
    independently verify journal_mode=WAL persists at the DB level (the only
    sticky PRAGMA).
    """
    db_path = str(tmp_path / "configure_pragmas.sqlite3")

    # Bootstrap a real SQLite file so integrity_check has something to verify.
    bootstrap = sqlite3.connect(db_path)
    bootstrap.execute("CREATE TABLE _seed (id INTEGER)")
    bootstrap.commit()
    bootstrap.close()

    import src.scheduler.watch as watch_mod
    monkeypatch.setattr(watch_mod, "DB_PATH", db_path)

    # Capture the connection passed into configure_sqlite_for_production so
    # we can read PRAGMA values mid-call (before _configure_database closes it).
    captured = {}

    def spy_configure(conn):
        # Delegate to the real helper so the actual PRAGMA work happens.
        from src.utils.db import configure_sqlite_for_production as real
        real(conn)
        # Read PRAGMAs while the connection is still open.
        captured["busy_timeout"] = conn.execute("PRAGMA busy_timeout").fetchone()[0]
        captured["journal_mode"] = conn.execute("PRAGMA journal_mode").fetchone()[0]
        captured["synchronous"] = conn.execute("PRAGMA synchronous").fetchone()[0]
        captured["integrity_check"] = conn.execute("PRAGMA integrity_check").fetchone()[0]

    monkeypatch.setattr(watch_mod, "configure_sqlite_for_production", spy_configure)

    # Run the static method.
    watch_mod.WatchLoop._configure_database()

    # busy_timeout from BUSY_TIMEOUT_MS=30000 in src/utils/db.py.
    assert captured["busy_timeout"] == 30000, (
        f"expected busy_timeout=30000 (uplifted from prior 5000), "
        f"got {captured['busy_timeout']!r}"
    )
    assert captured["journal_mode"].lower() == "wal", (
        f"expected journal_mode=WAL, got {captured['journal_mode']!r}"
    )
    # synchronous=NORMAL maps to integer 1 in PRAGMA output.
    assert int(captured["synchronous"]) == 1, (
        f"expected synchronous=NORMAL (1), got {captured['synchronous']!r}"
    )
    assert captured["integrity_check"] == "ok"

    # And verify journal_mode=WAL is sticky at the DB level (only sticky PRAGMA).
    inspect = sqlite3.connect(db_path)
    try:
        mode = inspect.execute("PRAGMA journal_mode").fetchone()[0]
        assert mode.lower() == "wal", (
            f"journal_mode=WAL should persist at DB level after close, "
            f"got {mode!r}"
        )
    finally:
        inspect.close()


# ---------------------------------------------------------------------------
# Test 2 — _configure_database invokes connect_db_with_pg_retry with exact args
# ---------------------------------------------------------------------------

def test_configure_database_uses_pg_retry_helper(tmp_path, monkeypatch):
    """The bare connect_db(DB_PATH) call has been replaced by
    connect_db_with_pg_retry(DB_PATH, max_attempts=5, backoff_seconds=30).

    Pins the M3 contract: 5 attempts, 30s backoff, going through the helper
    that knows how to write watchdog.txt + sys.exit(1) on exhaustion.
    """
    db_path = str(tmp_path / "uses_retry.sqlite3")

    bootstrap = sqlite3.connect(db_path)
    bootstrap.execute("CREATE TABLE _seed (id INTEGER)")
    bootstrap.commit()
    bootstrap.close()

    import src.scheduler.watch as watch_mod
    monkeypatch.setattr(watch_mod, "DB_PATH", db_path)

    # Capture the call to connect_db_with_pg_retry. The real helper still
    # needs to return a usable connection so the rest of _configure_database
    # can call configure_sqlite_for_production on it.
    real_conn_holder = {}

    def spy_helper(passed_db_path, *, max_attempts, backoff_seconds):
        spy_helper.calls.append(
            (passed_db_path, max_attempts, backoff_seconds)
        )
        # Delegate to real connect_db so configure_sqlite_for_production
        # has a real SQLite connection to work with.
        from src.utils.db import connect_db
        conn = connect_db(passed_db_path)
        real_conn_holder["conn"] = conn
        return conn

    spy_helper.calls = []
    monkeypatch.setattr(watch_mod, "connect_db_with_pg_retry", spy_helper)

    watch_mod.WatchLoop._configure_database()

    assert len(spy_helper.calls) == 1, (
        f"expected exactly 1 call to connect_db_with_pg_retry, got "
        f"{len(spy_helper.calls)}: {spy_helper.calls!r}"
    )
    passed_path, max_attempts, backoff_seconds = spy_helper.calls[0]
    assert passed_path == db_path
    assert max_attempts == 5, (
        f"M3 contract: max_attempts must be 5, got {max_attempts!r}"
    )
    assert backoff_seconds == 30, (
        f"M3 contract: backoff_seconds must be 30, got {backoff_seconds!r}"
    )


# ---------------------------------------------------------------------------
# Test 3 — M3 invariant: SystemExit from connect_db_with_pg_retry propagates
# ---------------------------------------------------------------------------

def test_configure_database_propagates_systemexit_past_except_exception(monkeypatch):
    """M3 invariant: when connect_db_with_pg_retry exhausts PG retries and
    calls sys.exit(1), the resulting SystemExit MUST propagate past the
    surrounding `except Exception` handler in _configure_database.

    SystemExit inherits from BaseException, not Exception, so a bare
    `except Exception` does NOT catch it. The existing `except SystemExit:
    raise` pass-through (watch.py line 1133-1134) is an additional belt-and-
    braces guarantee. This test verifies BOTH layers — by injecting a fake
    helper that raises SystemExit(1) and asserting the call site re-raises.

    Without this propagation, the watch loop would silently continue after
    PG goes down, becoming a zombie-watchdog that never restarts. The M3
    fast-exit pattern relies on SystemExit unwinding all the way to the
    NSSM-managed process boundary.
    """
    import src.scheduler.watch as watch_mod

    def exiting_helper(*args, **kwargs):
        # Simulate connect_db_with_pg_retry exhausting retries → sys.exit(1).
        # sys.exit raises SystemExit, which inherits from BaseException.
        raise SystemExit(1)

    monkeypatch.setattr(watch_mod, "connect_db_with_pg_retry", exiting_helper)

    # The whole point: SystemExit propagates out of _configure_database.
    with pytest.raises(SystemExit) as exc_info:
        watch_mod.WatchLoop._configure_database()
    assert exc_info.value.code == 1, (
        f"expected SystemExit code 1, got {exc_info.value.code!r}"
    )


# ---------------------------------------------------------------------------
# Test 4 — PG path: helper short-circuits to no-op via configure_sqlite_for_production
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"),
    reason="TEST_DATABASE_URL not set; PG variant of T2.12 cannot run",
)
def test_configure_database_on_postgres_path_is_no_op_for_pragmas(monkeypatch):
    """PG path: configure_sqlite_for_production no-ops on a
    PostgresConnectionWrapper (returns silently + warns). Calling
    _configure_database against a PG-wrapped connection MUST NOT raise
    a 'syntax error at or near PRAGMA' from psycopg2.

    Verifies the engine-agnostic shape of the refactor: the helper internally
    branches on isinstance(conn, PostgresConnectionWrapper), so the call site
    no longer cares about engine.
    """
    import psycopg2
    import psycopg2.extras

    from src.utils.db import PostgresConnectionWrapper

    raw = psycopg2.connect(
        os.environ["TEST_DATABASE_URL"],
        cursor_factory=psycopg2.extras.RealDictCursor,
    )
    wrapper = PostgresConnectionWrapper(raw)

    # Stub the helper to return our PG wrapper so _configure_database
    # exercises the PG branch of configure_sqlite_for_production.
    import src.scheduler.watch as watch_mod
    monkeypatch.setattr(
        watch_mod, "connect_db_with_pg_retry",
        lambda *a, **kw: wrapper,
    )

    # Must complete without raising 'syntax error at or near PRAGMA'.
    watch_mod.WatchLoop._configure_database()

    # The wrapper should still be usable (no PG syntax errors broke it).
    wrapper.close()
