# Purpose: Integration tests for src/tools/_db.py — pg_connect contextmanager.
# Called by: pytest tests/tools/test_db_helper.py
# Calls: src.tools._db.pg_connect, psycopg2 against real PG at 127.0.0.1:5434
# Owns tables: none (uses throwaway temp table created/dropped per test)
# Config keys: none (DSN passed explicitly per spec §4.9 network-discipline)
# Tests: (this file is the test)

from __future__ import annotations

import time

import psycopg2
import psycopg2.errors
import pytest

_TEST_DSN = "host=127.0.0.1 port=5434 dbname=halcyon user=test password=test"


# ── (a) RealDictCursor default ────────────────────────────────────────────


def test_pg_connect_yields_realdict_cursor():
    """pg_connect yields a cursor whose fetchone() returns a dict-like row.

    This test would fail if _db.py removes cursor_factory=RealDictCursor because
    psycopg2 would return a plain tuple row and row['transaction_isolation'] would
    raise TypeError instead of returning the column value.
    """
    from src.tools._db import pg_connect

    with pg_connect(_TEST_DSN) as (conn, cur):
        cur.execute("SHOW transaction_isolation")
        row = cur.fetchone()

    assert row is not None
    assert isinstance(row, dict), f"expected dict-like row, got {type(row).__name__}: {row!r}"


# ── (b) read_only enforcement ─────────────────────────────────────────────


def test_pg_connect_read_only_blocks_insert(tmp_path):
    """pg_connect(dsn, read_only=True) causes INSERT to raise a read-only error.

    Setup creates a throwaway temp table, teardown drops it. The read_only assertion
    is isolated in a separate connection that uses the read_only flag.

    This test would fail if _db.py removes conn.set_session(readonly=True) because
    PG would accept the INSERT and no exception would be raised.
    """
    from src.tools._db import pg_connect

    table_name = "tmp_db_helper_test_ro"

    # Setup: create throwaway table using a normal write connection
    with pg_connect(_TEST_DSN) as (conn, cur):
        cur.execute(f"DROP TABLE IF EXISTS {table_name}")
        cur.execute(f"CREATE TABLE {table_name} (val TEXT)")

    try:
        # Assertion: write inside read_only connection must fail
        with pytest.raises((psycopg2.errors.ReadOnlySqlTransaction, psycopg2.ProgrammingError)) as exc_info:
            with pg_connect(_TEST_DSN, read_only=True) as (conn, cur):
                cur.execute(f"INSERT INTO {table_name} VALUES ('forbidden')")

        # pgcode must be 25006 (ReadOnlySqlTransaction)
        exc = exc_info.value
        assert hasattr(exc, 'pgcode') and exc.pgcode == '25006', (
            f"expected pgcode 25006 (ReadOnlySqlTransaction), got {getattr(exc, 'pgcode', None)!r}"
        )
    finally:
        # Teardown: drop the throwaway table
        with pg_connect(_TEST_DSN) as (conn, cur):
            cur.execute(f"DROP TABLE IF EXISTS {table_name}")


# ── (c) isolation_level=REPEATABLE READ ───────────────────────────────────


def test_pg_connect_isolation_level_repeatable_read():
    """pg_connect(dsn, isolation_level='REPEATABLE READ') sets PG transaction isolation.

    This test would fail if _db.py removes conn.set_session(isolation_level=...)
    because PG would default to 'read committed' and the assertion would fail.
    """
    from src.tools._db import pg_connect

    with pg_connect(_TEST_DSN, isolation_level="REPEATABLE READ") as (conn, cur):
        cur.execute("SHOW transaction_isolation")
        row = cur.fetchone()

    assert row is not None
    # RealDictCursor returns dict-like; key is lowercase 'transaction_isolation'
    isolation = row["transaction_isolation"]
    assert isolation == "repeatable read", (
        f"expected 'repeatable read', got {isolation!r}"
    )


# ── (d) named server-side cursor ─────────────────────────────────────────


def test_pg_connect_named_cursor_has_name():
    """pg_connect(dsn, named_cursor='stream_test') yields a server-side cursor.

    This test would fail if _db.py passes the name to conn.cursor() incorrectly
    (e.g., as a keyword arg instead of positional) because the cursor.name would
    be None or raise an error.
    """
    from src.tools._db import pg_connect

    with pg_connect(_TEST_DSN, named_cursor="stream_test") as (conn, cur):
        assert cur.name == "stream_test", (
            f"expected cursor name 'stream_test', got {cur.name!r}"
        )


# ── (e) timeout on unreachable host ──────────────────────────────────────


def test_pg_connect_timeout_on_unreachable_host():
    """pg_connect with an unreachable host raises within a bounded time.

    Windows note: psycopg2 connect_timeout=1 triggers the PG client-side timeout,
    but the Windows TCP stack rounds loopback connection attempts to ~2s intervals.
    The assertion is <3.5s to stay meaningful (verifies timeout fires, not 30s hang)
    while tolerating the Windows TCP rounding behavior on 127.0.0.1 port 1.

    This test would fail if _db.py removes connect_timeout from the connect() call
    because psycopg2 would use the OS default TCP timeout (>30s on most systems),
    making the test hang rather than fail fast.
    """
    from src.tools._db import pg_connect, DBHelperError

    start = time.perf_counter()
    with pytest.raises((psycopg2.OperationalError, DBHelperError)):
        with pg_connect("host=127.0.0.1 port=1 user=x password=x", timeout=1) as (conn, cur):
            pass
    elapsed = time.perf_counter() - start

    assert elapsed < 3.5, (
        f"connect should timeout in <3.5s (connect_timeout=1 + Windows TCP rounding), "
        f"took {elapsed:.2f}s — check that connect_timeout is being passed"
    )
