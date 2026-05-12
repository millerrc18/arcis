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
import sys
import time
from pathlib import Path

import psycopg2
import psycopg2.extras

from src.config import DB_PATH
from src.schema.registry import TABLES

logger = logging.getLogger(__name__)

DEFAULT_DB = DB_PATH
BUSY_TIMEOUT_MS = 30_000  # 30s — rides through typical external-tool locks

_SENTINEL = object()

_DB_PATH_WARNED: set[int] = set()

_GATE_ON_NO_PG_URL_WARNED: bool = False


def _warn_gate_on_no_pg_url_once() -> None:
    """Single WARN when gate is on but DATABASE_URL doesn't start with postgres.

    This is the symmetric forensic signal to _warn_db_path_ignored_once: if the
    operator sets ARCIS_PG_CUTOVER_ENABLED=1 but DATABASE_URL is empty or
    non-postgres, we silently fall through to SQLite. This WARN ensures the
    misconfig leaves a forensic trail.
    """
    global _GATE_ON_NO_PG_URL_WARNED
    if _GATE_ON_NO_PG_URL_WARNED:
        return
    _GATE_ON_NO_PG_URL_WARNED = True
    logger.warning(
        "[DB] ARCIS_PG_CUTOVER_ENABLED=1 but DATABASE_URL does not start with "
        "'postgres' — falling through to SQLite. Verify NSSM env via "
        "`nssm get <service> AppEnvironmentExtra`."
    )


def _warn_db_path_ignored_once(db_path) -> None:
    key = id(db_path)
    if key in _DB_PATH_WARNED:
        return
    _DB_PATH_WARNED.add(key)
    logger.warning(
        "[DB] connect_db(db_path=%r) overridden by Phase 3 cutover gate; "
        "ARCIS_PG_CUTOVER_ENABLED=1 routes to PG. Unset to revert to SQLite path.",
        db_path,
    )


def _rewrite_question_to_pct(sql: str) -> str:
    """Rewrite `?` placeholders to `%s` and escape unpaired `%` to `%%`.

    Quote-aware tokenizer for the SQLite-style placeholder → psycopg2 style
    rewrite (Sprint 5 §J5/§J6 Phase 0 T0.2 — Modified-A migration).

    Devil's Advocate C1 + M1 framing:

    - C1: psycopg2 uses Python's `%` formatting for parameter binding. ANY
      `%` character in the SQL string (including those inside `'...'` string
      literals like `LIKE '%position%'`) is treated as a format spec when
      `cursor.execute(sql, params)` is called with a non-None `params`.
      Unrecognised format specs crash with `IndexError: tuple index out of
      range`. The fix: when the SQL contains a `?` that we're rewriting to
      `%s` (signalling format-binding will happen), ALL literal `%` chars
      must be doubled to `%%` so they survive binding as a single `%`. This
      doubling applies inside AND outside string literals — psycopg2 doesn't
      parse SQL, only Python `%` formatting.

    - M1: literal `?` characters inside single-quoted SQL string literals
      must NOT be rewritten (they're data, not placeholders). The naive
      `sql.replace('?', '%s')` prototype at cloud_routes/platform.py:59 gets
      this wrong; this state-machine tokenizer gets it right.

    Two-pass strategy:

    Pass 1 (single tokenizer walk): determine if any `?` outside a string
    literal exists. If yes, the caller will supply params and psycopg2 will
    format-bind, so `%` must be escaped EVERYWHERE.

    Pass 2 (single tokenizer walk): produce the rewritten string with the
    decision from pass 1 applied.

    Why uniform-everywhere rather than outside-only: empirically, psycopg2
    crashes on `LIKE '%foo%' AND id=%s` with `(1,)` params because it tries
    to interpret `%f` as a format spec. The audit doc T0.0 mis-states this
    contract — see the docstring's "C1" paragraph for the empirical
    correction. Tests 8-10 + the JSON-fragment test in
    `tests/test_db_wrapper_rewrite.py` exercise this rule against a live
    PG fixture.

    When the SQL contains NO `?` outside literals: this function leaves the
    string unchanged (no rewrite, no escape). Callers without `?` won't
    pass params, psycopg2 won't format-bind, and existing literal `%` chars
    stay as data — exactly what `LIKE 'PCT%'`-style ad-hoc SELECT needs.

    State transitions for both passes:
        OUTSIDE -> IN_SINGLE on first `'`
        IN_SINGLE -> OUTSIDE on closing `'` (consecutive `''` is an embedded
                     quote per ANSI SQL — consume both and stay IN_SINGLE)
        OUTSIDE -> IN_DOUBLE on first `"`
        IN_DOUBLE -> OUTSIDE on closing `"` (PG identifier — no embedded
                     escapes per the SQL standard)
    """
    # Pass 1: detect any `?` outside string literals.
    has_question_outside = False
    state = "OUTSIDE"
    i = 0
    n = len(sql)
    while i < n:
        c = sql[i]
        if state == "OUTSIDE":
            if c == "'":
                state = "IN_SINGLE"
            elif c == '"':
                state = "IN_DOUBLE"
            elif c == "?":
                has_question_outside = True
                break
            i += 1
        elif state == "IN_SINGLE":
            if c == "'":
                if i + 1 < n and sql[i + 1] == "'":
                    i += 2
                    continue
                state = "OUTSIDE"
            i += 1
        else:  # IN_DOUBLE
            if c == '"':
                state = "OUTSIDE"
            i += 1

    if not has_question_outside:
        # No format-binding will happen. Leave SQL unchanged so literal `%`
        # in patterns like `LIKE 'PCT%'` reaches PG verbatim.
        return sql

    # Pass 2: rewrite `?` -> `%s` outside literals, escape every literal `%`
    # to `%%` (inside AND outside literals) so format-binding renders it as
    # a single `%` in the executed SQL. Pre-existing `%s`/`%%`/`%(name)s`
    # outside literals are preserved (already-valid psycopg2 syntax).
    out = []
    state = "OUTSIDE"
    i = 0
    while i < n:
        c = sql[i]
        if state == "OUTSIDE":
            if c == "'":
                state = "IN_SINGLE"
                out.append(c)
                i += 1
            elif c == '"':
                state = "IN_DOUBLE"
                out.append(c)
                i += 1
            elif c == "?":
                out.append("%s")
                i += 1
            elif c == "%":
                nxt = sql[i + 1] if i + 1 < n else ""
                if nxt in ("s", "%", "(", "d"):
                    # Already a psycopg2 placeholder or escape sequence;
                    # don't double.
                    out.append(c)
                    i += 1
                else:
                    out.append("%%")
                    i += 1
            else:
                out.append(c)
                i += 1
        elif state == "IN_SINGLE":
            if c == "'":
                if i + 1 < n and sql[i + 1] == "'":
                    out.append("''")
                    i += 2
                else:
                    state = "OUTSIDE"
                    out.append(c)
                    i += 1
            elif c == "%":
                # C1: literal `%` inside a string literal must also be
                # escaped — psycopg2 doesn't know about SQL string-literal
                # quoting, so an unescaped `%` triggers format-spec parsing
                # regardless of position.
                out.append("%%")
                i += 1
            else:
                out.append(c)
                i += 1
        else:  # IN_DOUBLE
            if c == '"':
                state = "OUTSIDE"
                out.append(c)
                i += 1
            elif c == "%":
                # PG double-quoted identifiers don't normally contain `%`,
                # but escape defensively just in case (same rationale as
                # IN_SINGLE).
                out.append("%%")
                i += 1
            else:
                out.append(c)
                i += 1
    return "".join(out)


def _scalar(row):
    """Return the single value from a one-column fetchone() result, engine-agnostic.

    Handles all three row shapes that can flow out of fetchone() under the
    cross-engine wrapper architecture:

    - ``None`` (cursor exhausted) → returns None
    - ``sqlite3.Row`` (SQLite path) → returns ``row[0]``
    - ``CompatRow`` (PG via ``PostgresConnectionWrapper.cursor()``) → returns ``row[0]``
    - raw ``dict`` (PG via ``PostgresConnectionWrapper.execute()`` — see note below)
      → returns the single dict value via ``next(iter(row.values()))``

    Why this helper exists (Sprint 5 Wave A+B T1ext review observation):
    Two PG code paths through ``PostgresConnectionWrapper`` produce different
    row shapes: ``.cursor().execute()`` wraps fetched rows in CompatRow, but
    ``.execute()`` returns a raw psycopg2 cursor whose fetchone() emits raw
    dicts. T1ext's 82-site sweep used a defensive dispatch idiom inline at
    each call site; this helper consolidates that into a single function so
    new SQL aggregate expressions (MIN, AVG, subqueries) can be added without
    drift to a brittle ``row['count']`` idiom that only works for ``COUNT(*)``.

    See follow-up tracker for the deeper structural fix (wrap the inner
    cursor in ``_RowFactoryCursor`` so ``wrapper.execute().fetchone()`` also
    returns CompatRow, eliminating the dict branch entirely).
    """
    if row is None:
        return None
    if isinstance(row, dict):
        return next(iter(row.values()))
    return row[0]


def _resolve_conflict_target(table_name: str) -> list[str]:
    """Return the ON CONFLICT target columns for `table_name`.

    Precedence (Sprint 5 §J5/§J6 Phase 0 T0.3):
        1. If TABLES[table_name].sync_conflict_col is set, comma-split it
           and strip whitespace from each part. This handles tables whose
           PK is an autoincrement INTEGER but whose uniqueness for dedup
           is on another column (e.g. edgar_filings uses accession_number,
           not the integer id — see #185).
        2. Otherwise fall back to TABLES[table_name].primary_key — a string
           PK becomes a single-element list, a list PK is returned as-is
           (composite PKs must include ALL their columns in the ON CONFLICT
           target, because Postgres requires the conflict target to match
           an exact UNIQUE/PRIMARY KEY constraint).

    Raises ValueError if `table_name` is not registered in TABLES.

    Mirrors the inline `_resolve_primary_key_columns` helper in
    scripts/sqlite_to_pg_migrate.py (which intentionally stays inline for
    the one-shot migrator) but adds the sync_conflict_col precedence so
    the runtime upsert path (T0.4 `engine_aware_upsert`) gets the correct
    target for the 8 tables that override their PK with sync_conflict_col.
    """
    if table_name not in TABLES:
        raise ValueError(f"Unknown table: {table_name}")
    table = TABLES[table_name]
    if table.sync_conflict_col:
        return [col.strip() for col in table.sync_conflict_col.split(",")]
    pk = table.primary_key
    if isinstance(pk, str):
        return [pk]
    return list(pk)


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

    `execute` and `executemany` rewrite the SQL via `_rewrite_question_to_pct`
    before delegating, so call sites that pass SQLite-style `?` placeholders
    transparently get the `%s` form psycopg2 expects (Sprint 5 §J5/§J6 Phase
    0 T0.2). `close`, `fetchone`, and other attributes pass through
    unchanged via `__getattr__` (fetch* wrap rows in CompatRow).
    """

    def __init__(self, inner_cursor):
        self._cursor = inner_cursor

    def execute(self, sql, params=None):
        rewritten = _rewrite_question_to_pct(sql)
        if params is None:
            return self._cursor.execute(rewritten)
        return self._cursor.execute(rewritten, params)

    def executemany(self, sql, params_seq):
        rewritten = _rewrite_question_to_pct(sql)
        return self._cursor.executemany(rewritten, params_seq)

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
        # Wrap in _RowFactoryCursor so callers that do
        # `wrapper.cursor().execute(sql, params)` also route SQL through the
        # quote-aware `?`->`%s` rewrite (Sprint 5 §J5/§J6 Phase 0 T0.2).
        return _RowFactoryCursor(self._conn.cursor())

    def execute(self, sql, params=None):
        # Wrap in _RowFactoryCursor so the returned cursor's fetch* methods
        # produce CompatRow instances (supporting both `row[0]` and `row['col']`)
        # rather than raw psycopg2 dicts. Without this wrapping the caller
        # pattern `wrapper.execute(sql).fetchone()` returned a raw dict, which
        # raises KeyError(0) on `row[0]` access — the M4/2026-05-10 bug class
        # that drove the T1ext 82-site defensive-dispatch sweep. By wrapping
        # the cursor uniformly with `wrapper.cursor().execute()`'s wrapping,
        # the dispatch becomes unnecessary at all call sites (the `_scalar()`
        # helper is preserved as a forward-compatible convenience for the
        # None / single-column scalar fetch pattern, but its `isinstance(row,
        # dict)` branch is now unreachable in practice — see follow-up tracker).
        rewritten = _rewrite_question_to_pct(sql)
        cur = self._conn.cursor()
        if params is None:
            cur.execute(rewritten)
        else:
            cur.execute(rewritten, params)
        return _RowFactoryCursor(cur)

    def executemany(self, sql, params):
        rewritten = _rewrite_question_to_pct(sql)
        cur = self._conn.cursor()
        cur.executemany(rewritten, params)
        return _RowFactoryCursor(cur)

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

    Precedence — Phase 3-revised (spec-revised-one-db.md §2.1 truth table):

    The gate (ARCIS_PG_CUTOVER_ENABLED=1) + PG URL (DATABASE_URL starting
    with "postgres") together route EVERY call site to Postgres — including
    calls that pass an explicit `db_path`. When an explicit path is overridden,
    `_warn_db_path_ignored_once` emits a one-time WARN so the override is
    auditable.

    Truth table (8 rows):
      gate=off, url=off, path=sentinel  → SQLite at DEFAULT_DB
      gate=off, url=off, path=explicit  → SQLite at explicit path
      gate=off, url=pg,  path=sentinel  → SQLite at DEFAULT_DB (gate-off ignores url)
      gate=off, url=pg,  path=explicit  → SQLite at explicit path
      gate=on,  url=off, path=sentinel  → SQLite at DEFAULT_DB (gate requires url)
      gate=on,  url=off, path=explicit  → SQLite at explicit path
      gate=on,  url=pg,  path=sentinel  → PostgresConnectionWrapper
      gate=on,  url=pg,  path=explicit  → PostgresConnectionWrapper (path IGNORED, WARN emitted)

    Why the gate (Phase 3 T3.2 — M2 mitigation):
    Without ARCIS_PG_CUTOVER_ENABLED, merging T3.2 to main would flip
    precedence on every developer machine that has DATABASE_URL=postgresql://...
    in shell (including project-unrelated PG URLs). The 2026-05-10 cutover
    attempt failed in 2 minutes from exactly this shape. The gate makes T3.2's
    merge a no-op on developer boxes; only production NSSM (which sets BOTH
    DATABASE_URL AND ARCIS_PG_CUTOVER_ENABLED=1 via AppEnvironmentExtra)
    routes to PG. T3.5 rollback = single env unset:
    `nssm set ArcisWatchLoop AppEnvironmentExtra ARCIS_PG_CUTOVER_ENABLED=`
    → instant SQLite revert. Gate removed in Phase 4 T4.4 once cutover stable.

    Why Phase 3-revised inverts explicit-path precedence (PR #1054 fix):
    PR #1054 gated only the sentinel-default branch. With 265 of 336 call sites
    passing an explicit db_path, the gate routed only ~5 sites to PG. The watch
    loop's writes kept landing in SQLite even when the gate was ON. All 336 call
    sites have been audited (Sprint 5 §J5/§J6 scope) — those needing guaranteed
    SQLite now call sqlite3.connect directly or _sqlite_only_connect. The gate
    routing every call to PG is now safe. See spec-revised-one-db.md §2.1.

    M3 fast-exit for PG transient failures: use connect_db_with_pg_retry().

    SQLite connections always carry busy_timeout=30000 and row_factory=sqlite3.Row.
    """
    database_url = os.environ.get("DATABASE_URL", "")
    gate_on = os.environ.get("ARCIS_PG_CUTOVER_ENABLED") == "1"
    pg_url = database_url.startswith("postgres")

    if gate_on and pg_url:
        if db_path is not _SENTINEL:
            _warn_db_path_ignored_once(db_path)
        raw = psycopg2.connect(database_url, cursor_factory=psycopg2.extras.RealDictCursor)
        return PostgresConnectionWrapper(raw)

    if gate_on and not pg_url:
        _warn_gate_on_no_pg_url_once()

    effective_path = DEFAULT_DB if db_path is _SENTINEL else db_path
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


def engine_aware_table_list(conn) -> list[str]:
    """Return a sorted list of base-table names in the connection's database.

    Engine-aware (Sprint 5 §J5/§J6 Phase 0 T0.5):
    - SQLite path: `SELECT name FROM sqlite_master WHERE type='table'`
    - PG path: `SELECT tablename FROM pg_catalog.pg_tables
               WHERE schemaname = 'public'`

    The returned list is sorted alphabetically — call sites diffing
    registry tables vs. database tables rely on a stable order.

    Both paths filter system tables (SQLite internal `sqlite_*`, PG
    `information_schema` / `pg_*`) so the result reflects only the
    application's own tables.
    """
    if isinstance(conn, PostgresConnectionWrapper):
        cur = conn.execute(
            "SELECT tablename FROM pg_catalog.pg_tables "
            "WHERE schemaname = 'public' ORDER BY tablename"
        )
        rows = cur.fetchall()
        names = [r["tablename"] for r in rows]
    else:
        cur = conn.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name NOT LIKE 'sqlite_%' "
            "ORDER BY name"
        )
        rows = cur.fetchall()
        names = [r[0] for r in rows]
    return sorted(names)


def engine_aware_column_info(conn, table_name: str) -> list:
    """Return column metadata for `table_name`, shape matches PRAGMA table_info.

    Each row exposes the six PRAGMA fields: `cid` (0-based ordinal), `name`,
    `type`, `notnull` (1/0), `dflt_value`, `pk` (1 if column is part of the
    primary key, else 0). Rows support dict-style access via `row["name"]`.

    Engine-aware (Sprint 5 §J5/§J6 Phase 0 T0.5):
    - SQLite path: `PRAGMA table_info(table_name)` — emits the six fields
      natively. The cursor is wrapped to a list of dicts for cross-engine
      access uniformity.
    - PG path: `information_schema.columns` joined with
      `information_schema.key_column_usage` (filtered by the pkey
      constraint) so `pk` reflects PK membership. `cid = ordinal_position - 1`
      to align with SQLite's 0-based ordinal.

    Returns `[]` when `table_name` does not exist on either engine — this
    matches PRAGMA table_info(missing) silent-empty behavior. Call sites
    that need a hard error must check the result themselves.
    """
    if isinstance(conn, PostgresConnectionWrapper):
        # Subquery determines whether each column is part of the table's
        # primary key by joining the table_constraints / key_column_usage
        # views filtered to constraint_type = 'PRIMARY KEY'.
        sql = (
            "SELECT "
            "  c.ordinal_position - 1 AS cid, "
            "  c.column_name AS name, "
            "  c.data_type AS type, "
            "  CASE WHEN c.is_nullable = 'NO' THEN 1 ELSE 0 END AS notnull, "
            "  c.column_default AS dflt_value, "
            "  CASE WHEN kcu.column_name IS NOT NULL THEN 1 ELSE 0 END AS pk "
            "FROM information_schema.columns c "
            "LEFT JOIN information_schema.key_column_usage kcu "
            "  ON kcu.table_schema = c.table_schema "
            "  AND kcu.table_name = c.table_name "
            "  AND kcu.column_name = c.column_name "
            "  AND kcu.constraint_name IN ( "
            "    SELECT constraint_name FROM information_schema.table_constraints "
            "    WHERE table_schema = c.table_schema "
            "    AND table_name = c.table_name "
            "    AND constraint_type = 'PRIMARY KEY' "
            "  ) "
            "WHERE c.table_schema = 'public' AND c.table_name = %s "
            "ORDER BY c.ordinal_position"
        )
        cur = conn.execute(sql, (table_name,))
        rows = cur.fetchall()
        # Rows already expose CompatRow dict-style access — return as-is.
        return list(rows)

    # SQLite: PRAGMA table_info returns 6-column rows. Wrap each as a dict
    # so callers can use `row["name"]` uniformly with the PG path. PRAGMA
    # is silent on unknown tables, returning zero rows.
    cur = conn.execute(f"PRAGMA table_info({table_name})")
    rows = cur.fetchall()
    fields = ("cid", "name", "type", "notnull", "dflt_value", "pk")
    return [dict(zip(fields, tuple(r))) for r in rows]


# Re-export _sqlite_only_connect so call sites that want a guaranteed SQLite
# connection (without going through the engine-aware connect_db()) can import
# it via `from src.utils.db import _sqlite_only_connect`. The canonical
# implementation lives in src/schema/sqlite.py — see Sprint 5 §J5/§J6 phase 0.
from src.schema.sqlite import _sqlite_only_connect  # noqa: E402,F401


# ---------------------------------------------------------------------------
# Sprint 5 §J5/§J6 Phase 0 T0.4 — central UPSERT helper
# ---------------------------------------------------------------------------
#
# Devil's Advocate C2 (REPLACE-semantic divergence between engines):
#
#   SQLite's `INSERT OR REPLACE` does DELETE-then-INSERT (one atomic step):
#     • ON DELETE triggers fire
#     • ON DELETE CASCADE FKs cascade to child rows
#     • AUTOINCREMENT rowid is reassigned
#
#   PG's `INSERT ... ON CONFLICT ... DO UPDATE` does in-place UPDATE:
#     • Triggers don't fire (the row is updated, not deleted)
#     • CASCADE doesn't fire
#     • ctid / rowid is preserved
#
#   For tables with NO incoming FKs, NO triggers, and NO rowid-dependent
#   readers, these two paths are functionally identical. The T0.12 audit
#   (docs/audits/2026-05-11-modified-a-migration/replace-semantics-audit.md)
#   classified all 9 Phase 1 `action='replace'` target tables as such — they
#   are dispatched as `in_place_update`. The `delete_insert` branch is
#   implemented so that future tables that DO have cascade dependencies can
#   route through it without code churn — the dispatch table is the policy
#   surface.
#
# The audit's `_REPLACE_SEMANTICS` dict below MUST match the audit doc §7
# verbatim. The test_replace_semantics_dict_matches_audit_verbatim test in
# tests/test_db_engine_aware_upsert.py pins this.

_REPLACE_SEMANTICS = {
    "data_freshness": "in_place_update",
    "build_score_history": "in_place_update",
    "config_overrides": "in_place_update",
    "system_metrics": "in_place_update",
    "council_parameter_state": "in_place_update",
    "operator_view_state": "in_place_update",
    "simulation_results": "in_place_update",
    "walkforward_results": "in_place_update",
    "walkforward_trades": "in_place_update",
    "sp100_historical_constituents": "in_place_update",
}


def _require_classified_replace(table_name):
    """Raise ValueError if `table_name` is not in `_REPLACE_SEMANTICS`.

    Sprint 5 §J5/§J6 Phase 0 T0.4 (Devil's Advocate C2): forces every future
    `action='replace'` target through the T0.12-style audit before its
    dispatch lands. Without this guard, a Phase-2+ refactor could silently
    add a new replace target whose SQLite-vs-PG semantics diverge and
    corrupt FK-related data over the 7-day observability window.
    """
    if table_name not in _REPLACE_SEMANTICS:
        raise ValueError(
            f"engine_aware_upsert(action='replace') called on table "
            f"{table_name!r} without semantic classification — add to "
            f"_REPLACE_SEMANTICS dict in src/utils/db.py (see "
            f"docs/audits/2026-05-11-modified-a-migration/"
            f"replace-semantics-audit.md for the classification procedure)"
        )


def _transactional_delete_insert(conn, table_name, row_dict, conflict_target):
    """Atomic DELETE + INSERT pair inside the existing transaction.

    Used by `engine_aware_upsert` when a table is classified `delete_insert`
    in `_REPLACE_SEMANTICS` (T0.12 audit found 0 such tables in Phase 1,
    but the branch exists for future tables that DO need cascade semantics).

    On any exception during DELETE or INSERT, `conn.rollback()` is called
    so the DELETE half doesn't persist. Caller re-raises the original
    exception so the failure surfaces to the application layer.
    """
    col_names = list(row_dict.keys())
    col_values = tuple(row_dict[c] for c in col_names)
    cols_sql = ", ".join(col_names)
    placeholders = ", ".join(["?"] * len(col_names))
    where_clause = " AND ".join(f"{c}=?" for c in conflict_target)
    target_values = tuple(row_dict[c] for c in conflict_target)
    try:
        conn.execute(
            f"DELETE FROM {table_name} WHERE {where_clause}", target_values
        )
        conn.execute(
            f"INSERT INTO {table_name} ({cols_sql}) VALUES ({placeholders})",
            col_values,
        )
    except Exception:
        conn.rollback()
        raise


def _pg_replace_in_place(conn, table_name, row_dict, conflict_target):
    """INSERT ... ON CONFLICT (target) DO UPDATE SET non_target=EXCLUDED.non_target.

    PG path for `in_place_update`-classified tables. Computes the SET clause
    from the columns the caller actually supplied — any column in the
    conflict target itself is excluded (PG forbids updating a column that
    appears in the conflict specification).
    """
    col_names = list(row_dict.keys())
    col_values = tuple(row_dict[c] for c in col_names)
    cols_sql = ", ".join(col_names)
    placeholders = ", ".join(["?"] * len(col_names))
    target_sql = ", ".join(conflict_target)
    non_target_cols = [c for c in col_names if c not in conflict_target]
    if non_target_cols:
        set_sql = ", ".join(f"{c}=EXCLUDED.{c}" for c in non_target_cols)
        sql = (
            f"INSERT INTO {table_name} ({cols_sql}) VALUES ({placeholders}) "
            f"ON CONFLICT ({target_sql}) DO UPDATE SET {set_sql}"
        )
    else:
        sql = (
            f"INSERT INTO {table_name} ({cols_sql}) VALUES ({placeholders}) "
            f"ON CONFLICT ({target_sql}) DO NOTHING"
        )
    conn.execute(sql, col_values)


def _dispatch_pg(conn, table_name, row_dict, action, conflict_target):
    """PG dispatch — `ignore` → DO NOTHING; `replace` → consult _REPLACE_SEMANTICS."""
    col_names = list(row_dict.keys())
    col_values = tuple(row_dict[c] for c in col_names)
    cols_sql = ", ".join(col_names)
    placeholders = ", ".join(["?"] * len(col_names))
    target_sql = ", ".join(conflict_target)

    if action == "ignore":
        sql = (
            f"INSERT INTO {table_name} ({cols_sql}) VALUES ({placeholders}) "
            f"ON CONFLICT ({target_sql}) DO NOTHING"
        )
        conn.execute(sql, col_values)
        return

    _require_classified_replace(table_name)
    semantic = _REPLACE_SEMANTICS[table_name]
    if semantic == "in_place_update":
        _pg_replace_in_place(conn, table_name, row_dict, conflict_target)
    elif semantic == "delete_insert":
        _transactional_delete_insert(conn, table_name, row_dict, conflict_target)
    else:
        raise ValueError(
            f"engine_aware_upsert: _REPLACE_SEMANTICS[{table_name!r}]="
            f"{semantic!r} — expected 'in_place_update' or 'delete_insert'"
        )


def _dispatch_sqlite(conn, table_name, row_dict, action, conflict_target):
    """SQLite dispatch — INSERT OR REPLACE / INSERT OR IGNORE."""
    col_names = list(row_dict.keys())
    col_values = tuple(row_dict[c] for c in col_names)
    cols_sql = ", ".join(col_names)
    placeholders = ", ".join(["?"] * len(col_names))

    if action == "ignore":
        sql = f"INSERT OR IGNORE INTO {table_name} ({cols_sql}) VALUES ({placeholders})"
        conn.execute(sql, col_values)
        return

    # action == 'replace' — gate through the audit dispatch table even on
    # SQLite so the side that has DELETE+INSERT semantics natively doesn't
    # let a future Phase-2+ caller silently bypass the audit.
    _require_classified_replace(table_name)
    semantic = _REPLACE_SEMANTICS[table_name]
    if semantic == "delete_insert":
        _transactional_delete_insert(conn, table_name, row_dict, conflict_target)
    else:
        # in_place_update on SQLite → native INSERT OR REPLACE (DELETE+INSERT
        # is the SQLite semantic; reader-invisible for all 9 audited tables).
        sql = (
            f"INSERT OR REPLACE INTO {table_name} ({cols_sql}) "
            f"VALUES ({placeholders})"
        )
        conn.execute(sql, col_values)


def engine_aware_upsert(conn, table_name, row_dict, action="replace"):
    """Engine-agnostic UPSERT — dispatch by engine + action.

    Used by 17 Phase 1 call sites that need to dedup-insert rows on both
    SQLite and PostgreSQL. Resolves the conflict target via
    `_resolve_conflict_target` (T0.3) — honoring sync_conflict_col over
    primary_key — then dispatches per engine:

    - SQLite: `INSERT OR REPLACE/IGNORE INTO {table} ...` (native one-statement
      atomic DELETE+INSERT or skip-on-conflict).
    - PG action='ignore': `INSERT ... ON CONFLICT (target) DO NOTHING`
      (mirrors the migrator's `_build_insert_sql_template` at
      scripts/sqlite_to_pg_migrate.py:97).
    - PG action='replace': consults `_REPLACE_SEMANTICS` (T0.12 audit).
      `in_place_update` → ON CONFLICT DO UPDATE SET non_target=EXCLUDED.
      `delete_insert` → transactional DELETE + INSERT.

    Raises:
        ValueError if `action` not in {'replace', 'ignore'}.
        ValueError if `table_name` is not registered in `TABLES`.
        ValueError if `action='replace'` and `table_name` is not in
            `_REPLACE_SEMANTICS` — forces every future replace target through
            the T0.12-style audit before its dispatch lands.

    Sprint 5 §J5/§J6 Phase 0 T0.4 — Modified-A migration central helper.
    """
    if action not in ("replace", "ignore"):
        raise ValueError(
            f"engine_aware_upsert: action must be 'replace' or 'ignore', "
            f"got {action!r}"
        )
    conflict_target = _resolve_conflict_target(table_name)
    if isinstance(conn, PostgresConnectionWrapper):
        _dispatch_pg(conn, table_name, row_dict, action, conflict_target)
    else:
        _dispatch_sqlite(conn, table_name, row_dict, action, conflict_target)


# ---------------------------------------------------------------------------
# T0.6: engine_aware_index_list + engine_aware_foreign_keys
# ---------------------------------------------------------------------------

def engine_aware_index_list(conn, table_name: str) -> list:
    """Return list of index metadata dicts. Engine-aware.

    Output shape matches `PRAGMA index_list(<table>)`:
        (seq, name, unique, origin, partial)

    SQLite path: delegates to PRAGMA index_list and projects rows to dicts.
    PG path: queries pg_catalog.pg_indexes / pg_catalog.pg_index to derive
    the equivalent fields. `origin` is reported as 'pk' for primary-key
    indexes, 'u' for unique constraints, and 'c' otherwise. `partial` is
    1 if the index has a WHERE clause, 0 otherwise.

    Sprint 5 §J5/§J6 Phase 0 T0.6 — Modified-A migration helper. Phase 2A
    call sites at src/schema/validator.py + src/scheduler/watch.py will
    consume this helper to replace inlined PRAGMA queries.
    """
    if isinstance(conn, PostgresConnectionWrapper):
        cur = conn.cursor()
        cur.execute(
            """
            SELECT
                0 AS seq,
                i.relname AS name,
                CASE WHEN ix.indisunique THEN 1 ELSE 0 END AS unique,
                CASE
                    WHEN ix.indisprimary THEN 'pk'
                    WHEN ix.indisunique THEN 'u'
                    ELSE 'c'
                END AS origin,
                CASE WHEN ix.indpred IS NOT NULL THEN 1 ELSE 0 END AS partial
            FROM pg_catalog.pg_index ix
            JOIN pg_catalog.pg_class i ON i.oid = ix.indexrelid
            JOIN pg_catalog.pg_class t ON t.oid = ix.indrelid
            JOIN pg_catalog.pg_namespace n ON n.oid = t.relnamespace
            WHERE n.nspname = 'public' AND t.relname = %s
            ORDER BY i.relname
            """,
            (table_name,),
        )
        rows = cur.fetchall()
        return [
            {
                "seq": row["seq"],
                "name": row["name"],
                "unique": int(row["unique"]),
                "origin": row["origin"],
                "partial": int(row["partial"]),
            }
            for row in rows
        ]

    # SQLite path
    cur = conn.execute(f"PRAGMA index_list({table_name})")
    rows = cur.fetchall()
    return [
        {
            "seq": row[0],
            "name": row[1],
            "unique": int(row[2]),
            "origin": row[3],
            "partial": int(row[4]),
        }
        for row in rows
    ]


def engine_aware_foreign_keys(conn, table_name: str) -> list:
    """Return list of foreign-key metadata dicts. Engine-aware.

    Output shape matches `PRAGMA foreign_key_list(<table>)`:
        (id, seq, table, from, to, on_update, on_delete, match)

    SQLite path: delegates to PRAGMA foreign_key_list and projects rows
    to dicts.
    PG path: queries information_schema.referential_constraints joined
    with key_column_usage and constraint_column_usage to derive the
    equivalent fields. `id` and `seq` are not meaningful in PG, so they
    are reported as 0. `match` is reported as 'NONE'.

    Sprint 5 §J5/§J6 Phase 0 T0.6 — Modified-A migration helper. Phase 2A
    call sites will consume this helper to replace inlined PRAGMA queries.
    """
    if isinstance(conn, PostgresConnectionWrapper):
        cur = conn.cursor()
        cur.execute(
            """
            SELECT
                0 AS id,
                (kcu.ordinal_position - 1) AS seq,
                ccu.table_name AS "table",
                kcu.column_name AS "from",
                ccu.column_name AS "to",
                rc.update_rule AS on_update,
                rc.delete_rule AS on_delete,
                'NONE' AS match
            FROM information_schema.referential_constraints rc
            JOIN information_schema.key_column_usage kcu
                ON kcu.constraint_name = rc.constraint_name
                AND kcu.constraint_schema = rc.constraint_schema
            JOIN information_schema.constraint_column_usage ccu
                ON ccu.constraint_name = rc.constraint_name
                AND ccu.constraint_schema = rc.constraint_schema
            WHERE kcu.table_name = %s
              AND kcu.table_schema = 'public'
            ORDER BY rc.constraint_name, kcu.ordinal_position
            """,
            (table_name,),
        )
        rows = cur.fetchall()
        return [
            {
                "id": row["id"],
                "seq": row["seq"],
                "table": row["table"],
                "from": row["from"],
                "to": row["to"],
                "on_update": row["on_update"],
                "on_delete": row["on_delete"],
                "match": row["match"],
            }
            for row in rows
        ]

    # SQLite path
    cur = conn.execute(f"PRAGMA foreign_key_list({table_name})")
    rows = cur.fetchall()
    return [
        {
            "id": row[0],
            "seq": row[1],
            "table": row[2],
            "from": row[3],
            "to": row[4],
            "on_update": row[5],
            "on_delete": row[6],
            "match": row[7],
        }
        for row in rows
    ]


# Re-export _sqlite_only_connect so call sites that want a guaranteed SQLite
# connection (without going through the engine-aware connect_db()) can import
# it via `from src.utils.db import _sqlite_only_connect`. The canonical
# implementation lives in src/schema/sqlite.py — see Sprint 5 §J5/§J6 phase 0.


# ---------------------------------------------------------------------------
# Sprint 5 §J5/§J6 Phase 0 T0.11 — connect_db_with_pg_retry (M3 fast-exit)
# ---------------------------------------------------------------------------

def connect_db_with_pg_retry(db_path=_SENTINEL, *, max_attempts=5, backoff_seconds=30):
    """Connect with bounded retry on PG transient failures + fast-exit on exhaustion.

    SQLite path: identity passthrough to `connect_db()` (no retry — local file
    operations don't have the network-style transient failure profile).

    PG path (Phase 3 gate): BOTH ARCIS_PG_CUTOVER_ENABLED == "1" AND
    DATABASE_URL starts with "postgres" must be true to enter the retry loop.
    This mirrors the gate in connect_db() so the retry wrapper agrees with the
    underlying routing decision and does not spin wasted retry attempts when
    connect_db() would return SQLite anyway. Gate semantics match T3.2 —
    see connect_db() docstring for the M2 rationale.

    PG retry: wrap `connect_db()` in a try/except `psycopg2.OperationalError`
    loop. On failure, sleep `backoff_seconds` and retry up to `max_attempts`.

    M3 (Devil's Advocate critical fix) — on exhaustion:
      1. Write `PG_CONNECT_FAIL: <exc>` to `<DB_PATH parent>/watchdog.txt` so
         NSSM's external watcher can distinguish DB-induced restarts from
         unrelated crashes.
      2. Log `logger.critical('PG unreachable after %d attempts; exiting for
         NSSM restart', max_attempts)`.
      3. `sys.exit(1)` — raises SystemExit which is NOT caught by
         `except Exception` handlers in watch.py:1133 (that handler has a
         dedicated `except SystemExit: raise` pass-through). The process
         exits cleanly with code 1; NSSM's auto-restart policy kicks in.
         This prevents the zombie-watchdog mode where the watch loop keeps
         running without a configured DB.

    On success after retries, logs at INFO level with the attempt count so
    operators can see retry activity post-mortem.
    """
    database_url = os.environ.get("DATABASE_URL", "")
    gate_on = os.environ.get("ARCIS_PG_CUTOVER_ENABLED") == "1"
    pg_url = database_url.startswith("postgres")

    if not (gate_on and pg_url):
        # SQLite path: identity passthrough to connect_db (no retry needed)
        return connect_db(db_path)

    last_exc = None
    for attempt in range(1, max_attempts + 1):
        try:
            conn = connect_db(db_path)
            if attempt > 1:
                logger.info(
                    "[DB] PG connect succeeded on attempt %d/%d",
                    attempt, max_attempts,
                )
            return conn
        except psycopg2.OperationalError as exc:
            last_exc = exc
            if attempt < max_attempts:
                logger.warning(
                    "[DB] PG connect attempt %d/%d failed: %s — retrying in %ds",
                    attempt, max_attempts, exc, backoff_seconds,
                )
                time.sleep(backoff_seconds)

    # Exhausted: M3 fast-exit. Write watchdog.txt BEFORE sys.exit so the
    # marker is durable even though SystemExit unwinds the stack.
    watchdog_parent = Path(DB_PATH).parent if DB_PATH else Path("data")
    watchdog_file = watchdog_parent / "watchdog.txt"
    try:
        watchdog_parent.mkdir(parents=True, exist_ok=True)
        watchdog_file.write_text(
            f"PG_CONNECT_FAIL: {last_exc}\n", encoding="utf-8",
        )
    except OSError as write_exc:
        logger.error("[DB] Could not write watchdog.txt: %s", write_exc)

    logger.critical(
        "PG unreachable after %d attempts; exiting for NSSM restart",
        max_attempts,
    )
    sys.exit(1)
