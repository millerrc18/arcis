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
from src.schema.registry import TABLES

logger = logging.getLogger(__name__)

DEFAULT_DB = DB_PATH
BUSY_TIMEOUT_MS = 30_000  # 30s — rides through typical external-tool locks

_SENTINEL = object()


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
        rewritten = _rewrite_question_to_pct(sql)
        cur = self._conn.cursor()
        if params is None:
            cur.execute(rewritten)
        else:
            cur.execute(rewritten, params)
        return cur

    def executemany(self, sql, params):
        rewritten = _rewrite_question_to_pct(sql)
        cur = self._conn.cursor()
        cur.executemany(rewritten, params)
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
