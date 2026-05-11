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


class CompatRow:
    """Row wrapper supporting BOTH `row[int]` AND `row['col']` access.

    Mirrors sqlite3.Row semantics for psycopg2 RealDictCursor results. Used by
    `_RowFactoryCursor` to wrap each dict returned by psycopg2 so that
    SQLite-shaped call sites (`row[0]`, `tuple(row)`, `a, b = row`) keep
    working under PG without per-site rewrites.

    CRITICAL INVARIANT (Devil's Advocate finding C3): Iteration yields VALUES,
    not keys. This matches sqlite3.Row exactly:

        for v in row    -> values
        tuple(row)      -> (v1, v2, ...)
        list(row)       -> [v1, v2, ...]
        a, b = row      -> values destructured

    For column-name iteration, callers must use `row.keys()` explicitly. If
    `__iter__` yielded keys, code paths that destructure rows (`a, b = row`)
    or coerce to tuple/list would silently swap values for column names — the
    silent-data-corruption class of bug the Modified-A migration must prevent.

    `dict(CompatRow)` returns a column-keyed dict by virtue of Python's
    `dict()` constructor preferring `keys() + __getitem__` over `__iter__`
    when both are available — same behavior as `dict(sqlite3.Row)`.
    """

    __slots__ = ("_row",)

    def __init__(self, row_dict):
        self._row = row_dict

    def __getitem__(self, key):
        if isinstance(key, int):
            return list(self._row.values())[key]
        return self._row[key]

    def __iter__(self):
        # C3: yield VALUES, not keys — matches sqlite3.Row.
        return iter(self._row.values())

    def __len__(self):
        return len(self._row)

    def __contains__(self, key):
        return key in self._row

    def keys(self):
        return self._row.keys()

    def __repr__(self):
        return f"CompatRow({self._row!r})"


class _RowFactoryCursor:
    """Wraps a psycopg2 cursor so fetch* methods return CompatRow instances.

    The inner cursor is expected to be a `psycopg2.extras.RealDictCursor` (set
    by `connect_db()` via `cursor_factory=psycopg2.extras.RealDictCursor`), so
    its fetch methods return dicts. This wrapper translates each dict to a
    CompatRow on the way out. `fetchone()` returns `None` (not a CompatRow)
    when the cursor is exhausted, matching DB-API 2.0 semantics.

    `execute`, `executemany`, `close`, and other cursor attributes pass
    through unchanged via `__getattr__`. The `PostgresConnectionWrapper` layer
    is responsible for any SQL rewrites (`?` -> `%s`, etc.) before the SQL
    reaches this cursor.
    """

    def __init__(self, inner_cursor):
        self._cursor = inner_cursor

    def fetchone(self):
        row = self._cursor.fetchone()
        if row is None:
            return None
        return CompatRow(row)

    def fetchall(self):
        return [CompatRow(r) for r in self._cursor.fetchall()]

    def fetchmany(self, size=None):
        if size is None:
            rows = self._cursor.fetchmany()
        else:
            rows = self._cursor.fetchmany(size)
        return [CompatRow(r) for r in rows]

    def __getattr__(self, name):
        return getattr(self._cursor, name)


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
