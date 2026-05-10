"""SQLite / PostgreSQL connection helper.

Called by: scheduler.watch, shadow_trading.executor, sync.render_sync, and others
Calls: none
Owns tables: none
Config keys: DATABASE_URL (optional — if set and starts with 'postgres', uses PG)
Tests: tests/test_db_util.py

When DATABASE_URL is unset (or empty), connect_db() returns a plain
sqlite3.Connection against DEFAULT_DB, exactly as before this change.  When
DATABASE_URL starts with 'postgres', connect_db() (called with no db_path)
returns a PostgresConnectionWrapper backed by psycopg2.  When an explicit
db_path is passed the SQLite path is ALWAYS used, preserving test-fixture
compatibility for the 336 callers that use init_test_db(db_path).

The busy_timeout is critical because multiple threads (watch loop, sync thread,
FastAPI workers) all access the same SQLite database file — and external tools
(MS Access, DB Browser, etc.) can hold the file lock for indefinite durations
while the operator inspects data. Without it, a thread that tries to write
while another transaction holds the lock gets an immediate "database is
locked" error.

Prior timeout was 5s, which was insufficient to ride through external-tool
locks (observed 2026-04-19: 118 "database is locked" errors in arcis.log,
concentrated during a window where the operator had the DB open in MS Access).
30s gives enough slack to span most interactive inspections without
compromising trading-critical paths, which normally write in <100ms.

Row factory is set to sqlite3.Row globally so that results are accessible by
column name (dict-like) rather than tuple index. This prevents bugs when columns
are reordered in the schema registry.
"""

import os
import sqlite3

import psycopg2
import psycopg2.extras

from src.config import DB_PATH

DEFAULT_DB = DB_PATH
BUSY_TIMEOUT_MS = 30_000  # 30s — rides through typical external-tool locks

_SENTINEL = object()


class PostgresConnectionWrapper:
    """Thin context-manager wrapper around a psycopg2 connection.

    Exposes the same surface as sqlite3.Connection that callers rely on:
    cursor(), execute(), executemany(), commit(), rollback(), close(),
    and a settable row_factory attribute (no-op — psycopg2 RealDictCursor
    already provides name-based access).
    """

    def __init__(self, conn):
        self._conn = conn
        self.row_factory = None

    def cursor(self):
        return self._conn.cursor()

    def execute(self, sql, params=None):
        cur = self._conn.cursor()
        if params is None:
            cur.execute(sql)
        else:
            cur.execute(sql, params)
        return cur

    def executemany(self, sql, params):
        cur = self._conn.cursor()
        cur.executemany(sql, params)
        return cur

    def commit(self):
        return self._conn.commit()

    def rollback(self):
        return self._conn.rollback()

    def close(self):
        return self._conn.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is None:
            self.commit()
        else:
            self.rollback()
        self.close()
        return False


def connect_db(db_path=_SENTINEL):
    """Return a database connection.

    Precedence — **DATABASE_URL wins**:

    1. If `DATABASE_URL` is set and starts with "postgres", return a
       PostgresConnectionWrapper. The `db_path` arg is IGNORED in this branch.
    2. Otherwise (DATABASE_URL unset or non-postgres): return a SQLite
       connection. Path resolution:
         - `db_path = _SENTINEL` (no arg)  → DEFAULT_DB
         - `db_path` provided (any value, including None) → that value
           (None opens `:memory:` — what tests that patch DB_PATH=None rely on)

    Why this precedence: production code at 265+ of the 336 call sites passes
    `connect_db(db_path)` or `connect_db(DB_PATH)` explicitly. If the shim
    treated any explicit arg as "force SQLite", the Modified-A cutover's
    DATABASE_URL flip would silently fail to route production reads/writes
    to Postgres — the watch loop would keep writing SQLite forever. This was
    observed live on 2026-05-10 19:25 EDT when the NSSM env update flipped
    DATABASE_URL but writes kept landing in SQLite. The fix inverts the
    precedence: DATABASE_URL wins, db_path becomes advisory.

    For test fixtures that need SQLite when DATABASE_URL happens to be set
    in the environment: use `monkeypatch.delenv("DATABASE_URL", raising=False)`
    or `monkeypatch.setenv("DATABASE_URL", "")` in the fixture setup. Tests
    in this repo don't generally set DATABASE_URL (env-drift memory means
    worktrees don't carry .env), so the default behavior continues to use
    SQLite paths for test_db_path-style fixtures.

    SQLite connections always carry busy_timeout=30000 and row_factory=sqlite3.Row.
    """
    database_url = os.environ.get("DATABASE_URL", "")
    if database_url.startswith("postgres"):
        raw = psycopg2.connect(database_url, cursor_factory=psycopg2.extras.RealDictCursor)
        return PostgresConnectionWrapper(raw)

    if db_path is _SENTINEL:
        effective_path = DEFAULT_DB
    else:
        effective_path = db_path

    conn = sqlite3.connect(effective_path, timeout=BUSY_TIMEOUT_MS / 1000.0)
    conn.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
    conn.row_factory = sqlite3.Row
    return conn
