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

import logging
import os
import sqlite3

import psycopg2
import psycopg2.extras

from src.config import DB_PATH

logger = logging.getLogger(__name__)

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

    Precedence — explicit `db_path` wins (original Wave 2.1 contract,
    restored after the 2026-05-10 hotfix rollback):

    1. If `db_path` is explicitly provided (any value), always use SQLite at
       that path. None opens `:memory:` (test-fixture compat).
    2. If `db_path` is omitted (sentinel default), check `DATABASE_URL`:
       - postgres scheme → return PostgresConnectionWrapper
       - empty / non-postgres → return SQLite at DEFAULT_DB

    Why this precedence (NOT "DATABASE_URL wins"): 265 of the 336 call sites
    pass `connect_db(db_path)` with an explicit path. The downstream code at
    many of those sites uses SQLite-specific syntax (PRAGMA index_list,
    `?` placeholders, `sqlite_master`) that Postgres rejects. The 2026-05-10
    hotfix attempt to invert precedence (DATABASE_URL wins) tripped on three
    such call paths within 2 minutes of watch loop restart:

      - src/schema/sqlite.py: PRAGMA index_list (fixed by ed1757c — file
        now uses sqlite3.connect directly)
      - src/evaluation/system_validator.py:1039: `INSERT ... VALUES (?,?,?...)`
        with SQLite placeholders against PG
      - src/schema/validator.py: `SELECT name FROM sqlite_master` against PG

    The proper Modified-A migration audits ALL such call sites + queries
    and converts them either to PG-compatible syntax (`%s` placeholders,
    `information_schema` lookups) OR routes them through a direct
    `sqlite3.connect` for SQLite-only operations. That's Sprint 5 §J5/§J6
    scope, not a one-line shim flip.

    Until SP5 lands, production stays on SQLite via this explicit-path
    contract. Cloud-routes that already have manual `if database_url:`
    runtime branches (src/api/cloud_routes/{kpis_compute,platform,…}.py)
    continue to use that pattern unchanged.

    SQLite connections always carry busy_timeout=30000 and row_factory=sqlite3.Row.
    """
    if db_path is _SENTINEL:
        database_url = os.environ.get("DATABASE_URL", "")
        if database_url.startswith("postgres"):
            raw = psycopg2.connect(database_url, cursor_factory=psycopg2.extras.RealDictCursor)
            return PostgresConnectionWrapper(raw)
        effective_path = DEFAULT_DB
    else:
        effective_path = db_path

    conn = sqlite3.connect(effective_path, timeout=BUSY_TIMEOUT_MS / 1000.0)
    conn.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
    conn.row_factory = sqlite3.Row
    return conn


def configure_sqlite_for_production(conn) -> None:
    """Apply runtime-tuning PRAGMAs (SQLite-only; no-op on PG).

    Applies: busy_timeout=30000, journal_mode=WAL, synchronous=NORMAL, and
    integrity_check verification (raises RuntimeError if the result is not
    "ok"). Designed to replace the inline PRAGMA block in the watch loop
    startup path (src/scheduler/watch.py: _configure_database, T2.12).

    PG-wrapped connections: no-op + warning log. PRAGMA is SQLite-specific
    syntax that Postgres rejects with "syntax error at or near PRAGMA";
    Postgres tuning is managed at the server / connection-string level.
    """
    if isinstance(conn, PostgresConnectionWrapper):
        logger.warning(
            "PRAGMA runtime tuning is SQLite-only; skipping on PG-backed connection"
        )
        return

    # Integrity check first — abort before any writes if DB is corrupted
    row = conn.execute("PRAGMA integrity_check").fetchone()
    if row is not None:
        result = row[0]
        if result != "ok":
            raise RuntimeError(f"SQLite integrity_check failed: {result}")

    conn.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")


# Re-export _sqlite_only_connect so call sites that want a guaranteed SQLite
# connection (without going through the engine-aware connect_db()) can import
# it via `from src.utils.db import _sqlite_only_connect`. The canonical
# implementation lives in src/schema/sqlite.py — see Sprint 5 §J5/§J6 phase 0.
from src.schema.sqlite import _sqlite_only_connect  # noqa: E402,F401
