"""AST-based SQLite-ism discipline test (Sprint 5 §J5/§J6 Phase 2 T2.14 — Devil's Advocate M4 fix).

Walks every ``.py`` file under ``src/`` (minus allowlist) and flags SQLite-only
SQL patterns that would crash on Postgres after the Phase 3 cutover:

1.  ``INSERT OR REPLACE`` / ``INSERT OR IGNORE`` string literals passed to
    ``execute()`` / ``executemany()`` family calls — including dynamically
    constructed strings (f-strings, ``.format()`` chains, ``+``-concats).
2.  ``PRAGMA <name>`` literals in ``execute*`` calls (with a line-range
    allowlist for the SQLite Online Backup API in ``scheduler/watch.py``).
3.  ``sqlite_master`` references in ``execute*`` calls.
4.  SQLite-only date functions: ``julianday(``, ``date('now'``,
    ``datetime('now'`` in ``execute*`` calls.
5.  SQL-keyword strings (``INSERT``, ``SELECT``, ``UPDATE``, ``DELETE``,
    ``VALUES``) where a ``?`` placeholder is constructed dynamically — the
    M4 bug class: ``f'... ({", ".join("?" for _ in row)}) ...'`` produces a
    string whose ``?`` count varies at runtime. ``cursor.execute()`` on a
    raw ``sqlite3.Connection`` accepts these; psycopg2 does not, so post-
    cutover the call crashes. The wrapper rewrites static ``?`` to ``%s``,
    but only the substring scan can see; dynamic placeholder construction
    is invisible to substring static-analysis and was the exact bug class
    that caused the 2026-05-10 cutover crash at
    ``system_validator.py:1039``.

Why AST instead of grep: dynamic placeholder construction like ::

    placeholders = ", ".join("?" for _ in row)
    cursor.execute(f"INSERT INTO t ({cols}) VALUES ({placeholders})", row)

is invisible to substring scans but is the exact M4 bug class. AST
traversal detects the join-of-`?` plus f-string-of-that-result by
*structure*, not by literal match.

**Scope of "PG-safe":** by default every file under ``src/`` is treated as
PG-safe and subject to the scan, *except*:

- Files in ``ALLOWLIST_FILES`` (engine-specific schema, the wrapper itself,
  in-process maintenance jobs on the local SQLite mirror, retiring sync
  files slated for Phase 4 deletion).
- Line ranges in ``ALLOWLIST_LINE_RANGES`` (the SQLite Online Backup API
  in ``scheduler/watch.py``).
- ``KNOWN_OFFENDERS`` — file:line entries for SQLite-isms that exist in
  files NOT covered by the Phase 1+2 migration scope (per
  ``docs/audits/2026-05-11-modified-a-migration/spec.md`` §2.6). Each
  entry carries a reason tag so a future migration phase can remove it.
  This list is a snapshot of the Phase 2 baseline; ANY NEW offender that
  is not on this list will fail the test (the regression-lock mechanism).

**Completeness note (heuristic, not exhaustive):** the scanner catches
the M4 bug class plus the substring-detectable SQLite-isms when they
appear as ``execute*`` call arguments. It does NOT catch:

- SQL passed through ``cursor.executescript(...)``.
- SQL routed through a custom abstraction whose function name is not
  ``execute`` / ``executemany``.
- SQL stored in module-level constants and only later passed to
  ``execute`` (the scanner flags the call site, not the constant
  declaration — which means a constant declared in file A and used in
  file B is flagged at the use site in B).

The discipline test is paired with ``tests/test_connect_db_discipline.py``
(T2.13) for raw ``sqlite3.connect`` enforcement. Together they cover the
bulk of the Modified-A migration's drift surface; the residual blind
spots above are tracked as Phase 3+ follow-ups.

Called by: pytest (Sprint 5 Phase 2)
Calls: none
Owns tables: none
Config keys: none
Tests: self (positive synthetic fixtures verify the scanner catches each
       documented pattern)
"""

from __future__ import annotations

import ast
import textwrap
from pathlib import Path


# ── Constants ─────────────────────────────────────────────────────────────────

SRC = Path(__file__).parent.parent / "src"

# Files where SQLite-only patterns are intentional or out-of-migration-scope.
# Per spec section 2.7 (final allowlist) + retiring sync/* files (Phase 4
# deletions per T4.1, T4.2).
ALLOWLIST_FILES: frozenset[str] = frozenset({
    "src/schema/sqlite.py",      # Engine-specific schema generator
    "src/schema/registry.py",    # Declarative schema definition
    "src/schema/postgres.py",    # PG-specific schema (mirror of sqlite.py)
    "src/utils/db.py",           # The wrapper itself — has SQLite branch
    "src/training/trainer.py",   # Training corpus stays local SQLite (line 1171)
    "src/sync/render_sync.py",   # RETIRING: delete in SP5 §J6 Phase 4 (T4.1)
    "src/sync/reconcile.py",     # RETIRING: delete in SP5 §J6 Phase 4 (T4.2)
})

# Per-file line ranges where SQLite-only patterns are intentional. The
# Online Backup API in scheduler/watch.py copies physical pages between two
# real sqlite3.Connection objects — wrapping either side would break it.
ALLOWLIST_LINE_RANGES: dict[str, list[tuple[int, int]]] = {
    "src/scheduler/watch.py": [(1190, 1213)],  # _backup_database: Online Backup API
}

# Known existing SQLite-ism call sites in files NOT covered by the Phase 1+2
# migration scope (per spec §2.6) OR sites that go through the engine-aware
# wrapper (and thus the `?` rewrite handles them correctly at runtime, but
# our static AST heuristic still flags the construction pattern).
#
# The Phase 2 batch ships with these still present; ANY NEW offender that is
# not on this list is a regression. Each entry is (rel_path, lineno,
# reason_tag). When a future phase migrates a date-function site, remove the
# corresponding entry; the test will fail loudly if a previously-known
# offender is removed AND a new SQLite-ism is introduced at the same line.
#
# Line numbers are AST node line numbers — the line of the ``execute*`` call
# itself, NOT the line of the SQL substring. Regenerate with the
# ``scripts/regenerate-known-offenders.py`` helper if AST line attribution
# changes between Python versions (currently CPython 3.13).
#
# Reason tags:
#   "Phase 3+ date-function migration deferred"
#     — `datetime('now')` / `date('now')` site not in Phase 2B scope.
#   "Phase 2 guarded — SQLite-only path with isinstance check"
#     — PRAGMA gated by `isinstance(conn, sqlite3.Connection)` — runtime
#       safe but appears static-flaggable.
#   "Dynamic ? placeholder — wrapper-handled via connect_db()"
#     — code constructs `?` placeholders dynamically (e.g.
#       `", ".join("?" for _ in row)`) and passes the resulting SQL to a
#       connection obtained via `connect_db()`. The wrapper's
#       `_rewrite_question_to_pct` rewrites the `?` to `%s` at runtime,
#       so PG is safe. The static AST scan cannot tell which connection
#       path is used, so the construction site is flagged. These sites
#       are documented here as wrapper-routed; future audits may tighten
#       the detection to flag only raw-sqlite3 callers.
KNOWN_OFFENDERS: frozenset[tuple[str, int, str]] = frozenset({
    # ── PRAGMA gated by isinstance(conn, sqlite3.Connection) at runtime ──
    ("src/evaluation/system_validator.py", 167,
     "Phase 2 guarded — SQLite-only path with isinstance check"),

    # ── SQLite-only date functions in files not yet on Phase 2B list ─────
    # Each is a `WHERE created_at >= datetime('now', '-N days')` pattern
    # that needs Python-side computation of the cutoff before the cutover.
    ("src/council/context.py", 30,
     "Phase 3+ date-function migration deferred"),
    ("src/council/agent_data.py", 272,
     "Phase 3+ date-function migration deferred"),
    ("src/council/agent_data.py", 451,
     "Phase 3+ date-function migration deferred"),
    # build_score.py entries (was 151, 163, 408, 432) removed in Sprint 5
    # §J5/§J6 Phase 2.5 T1 — all 4 datetime('now', ...) sites migrated to
    # Python-side cutoffs (datetime.now(ET) - timedelta(days=N)).
    ("src/evaluation/hshs_live.py", 218,
     "Phase 3+ date-function migration deferred"),
    ("src/evaluation/hshs_live.py", 260,
     "Phase 3+ date-function migration deferred"),
    ("src/evaluation/hshs_live.py", 266,
     "Phase 3+ date-function migration deferred"),
    ("src/api/routes/system.py", 694,
     "Phase 3+ date-function migration deferred"),
    ("src/api/routes/ib_status.py", 76,
     "Phase 3+ date-function migration deferred"),

    # ── Dynamic `?` placeholder construction — wrapper-handled ───────────
    # 34 sites total. All use `connect_db()`/`closing(connect_db())` to
    # obtain the connection, so the wrapper rewrites `?` → `%s` at runtime.
    # The static AST scan flags the construction pattern; these are the
    # baseline allowlist of currently-known wrapper-routed sites.
    ("src/api/routes/logs.py", 74,
     "Dynamic ? placeholder — wrapper-handled via connect_db()"),
    ("src/api/routes/notes.py", 168,
     "Dynamic ? placeholder — wrapper-handled via connect_db()"),
    ("src/attribution/logger.py", 122,
     "Dynamic ? placeholder — wrapper-handled via connect_db()"),
    ("src/council/value_tracker.py", 313,
     "Dynamic ? placeholder — wrapper-handled via connect_db()"),
    ("src/data_collection/retention.py", 85,
     "Dynamic ? placeholder — wrapper-handled via connect_db()"),
    ("src/diagnostics/dashboard_runner.py", 87,
     "Dynamic ? placeholder — wrapper-handled via connect_db()"),
    ("src/features/traffic_light.py", 201,
     "Dynamic ? placeholder — wrapper-handled via connect_db()"),
    ("src/features/traffic_light.py", 210,
     "Dynamic ? placeholder — wrapper-handled via connect_db()"),
    ("src/features/traffic_light.py", 223,
     "Dynamic ? placeholder — wrapper-handled via connect_db()"),
    ("src/features/traffic_light.py", 234,
     "Dynamic ? placeholder — wrapper-handled via connect_db()"),
    ("src/features/traffic_light.py", 244,
     "Dynamic ? placeholder — wrapper-handled via connect_db()"),
    ("src/journal/store.py", 191,
     "Dynamic ? placeholder — wrapper-handled via connect_db()"),
    ("src/journal/store.py", 213,
     "Dynamic ? placeholder — wrapper-handled via connect_db()"),
    ("src/journal/store.py", 245,
     "Dynamic ? placeholder — wrapper-handled via connect_db()"),
    ("src/journal/store.py", 268,
     "Dynamic ? placeholder — wrapper-handled via connect_db()"),
    ("src/journal/store.py", 318,
     "Dynamic ? placeholder — wrapper-handled via connect_db()"),
    ("src/journal/store.py", 561,
     "Dynamic ? placeholder — wrapper-handled via connect_db()"),
    ("src/platform/features/cosine_similarity.py", 185,
     "Dynamic ? placeholder — wrapper-handled via connect_db()"),
    ("src/platform/features/cosine_similarity.py", 201,
     "Dynamic ? placeholder — wrapper-handled via connect_db()"),
    ("src/platform/promotion.py", 694,
     "Dynamic ? placeholder — wrapper-handled via connect_db()"),
    ("src/risk/governor.py", 865,
     "Dynamic ? placeholder — wrapper-handled via connect_db()"),
    ("src/scheduler/reports.py", 399,
     "Dynamic ? placeholder — wrapper-handled via connect_db()"),
    ("src/scheduler/reports.py", 415,
     "Dynamic ? placeholder — wrapper-handled via connect_db()"),
    ("src/scheduler/reports.py", 434,
     "Dynamic ? placeholder — wrapper-handled via connect_db()"),
    ("src/scheduler/reports.py", 441,
     "Dynamic ? placeholder — wrapper-handled via connect_db()"),
    ("src/scheduler/reports.py", 662,
     "Dynamic ? placeholder — wrapper-handled via connect_db()"),
    ("src/scheduler/reports.py", 667,
     "Dynamic ? placeholder — wrapper-handled via connect_db()"),
    ("src/scheduler/reports.py", 685,
     "Dynamic ? placeholder — wrapper-handled via connect_db()"),
    ("src/scheduler/reports.py", 691,
     "Dynamic ? placeholder — wrapper-handled via connect_db()"),
    ("src/scheduler/reports.py", 699,
     "Dynamic ? placeholder — wrapper-handled via connect_db()"),
    ("src/scheduler/reports.py", 705,
     "Dynamic ? placeholder — wrapper-handled via connect_db()"),
    ("src/shadow_trading/executor.py", 667,
     "Dynamic ? placeholder — wrapper-handled via connect_db()"),
    ("src/shadow_trading/executor.py", 2510,
     "Dynamic ? placeholder — wrapper-handled via connect_db()"),
    ("src/shadow_trading/executor.py", 2519,
     "Dynamic ? placeholder — wrapper-handled via connect_db()"),
})

# SQLite-only SQL substrings flagged in execute() argument strings.
INSERT_OR_FRAGMENTS: tuple[str, ...] = ("INSERT OR REPLACE", "INSERT OR IGNORE")
PRAGMA_FRAGMENT: str = "PRAGMA "
SQLITE_MASTER_FRAGMENT: str = "sqlite_master"
SQLITE_DATE_FRAGMENTS: tuple[str, ...] = (
    "julianday(", "date('now'", "datetime('now'",
)

# SQL keywords used by the unrewritten-? heuristic.
SQL_KEYWORDS_FOR_PLACEHOLDER_CHECK: tuple[str, ...] = (
    "INSERT", "SELECT", "UPDATE", "DELETE", "VALUES",
)


# ── AST helpers ───────────────────────────────────────────────────────────────


def _walk_pg_safe_src_files():
    """Yield (rel_path, ast.Module) for each scannable src/ python file.

    Skips files in ALLOWLIST_FILES. ``rel_path`` uses forward slashes for
    cross-platform stability (the constants above use forward-slash form).
    """
    for path in sorted(SRC.rglob("*.py")):
        rel = str(path.relative_to(SRC.parent).as_posix())
        if rel in ALLOWLIST_FILES:
            continue
        text = path.read_text(encoding="utf-8")
        try:
            tree = ast.parse(text)
        except SyntaxError:
            # Files that don't parse are skipped — pre-existing test
            # ``test_repo_structure`` would catch genuinely-broken syntax.
            continue
        yield rel, tree


def _is_line_allowlisted(rel_path: str, lineno: int) -> bool:
    """True if (file, lineno) falls in an ALLOWLIST_LINE_RANGES entry."""
    for low, high in ALLOWLIST_LINE_RANGES.get(rel_path, []):
        if low <= lineno <= high:
            return True
    return False


def _is_known_offender(rel_path: str, lineno: int) -> bool:
    """True if (file, lineno) appears in KNOWN_OFFENDERS (any reason tag)."""
    for off_path, off_line, _reason in KNOWN_OFFENDERS:
        if off_path == rel_path and off_line == lineno:
            return True
    return False


def _reconstruct_string(node: ast.AST) -> str | None:
    """Best-effort string reconstruction from an AST expression node.

    Handles:
      - ``ast.Constant(str)`` — return the literal.
      - ``ast.JoinedStr`` (f-string) — concatenate constant parts; for
        ``FormattedValue`` whose ``value`` is a ``Name`` we substitute a
        sentinel ``"<dyn>"`` so the surrounding literal context remains
        searchable.
      - ``ast.BinOp(op=Add)`` — concatenate the reconstructed left + right.
      - ``ast.Call`` to ``str.format`` or ``str.join`` — return the
        receiver string (``"a={}".format(x)`` → ``"a={}"``); join
        receivers with ``", "``-style separator return the format too.

    Returns None if the node cannot be reconstructed at all (e.g.
    ``var_name`` alone). Returns a partial string when fragments are
    statically visible — sufficient for substring search against
    SQLite-ism fragments.
    """
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value

    if isinstance(node, ast.JoinedStr):
        parts: list[str] = []
        for value in node.values:
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                parts.append(value.value)
            elif isinstance(value, ast.FormattedValue):
                # Try to reconstruct the formatted expression. If it's a
                # constant string, inline it; otherwise insert a sentinel
                # so adjacent literal fragments remain visible.
                sub = _reconstruct_string(value.value)
                parts.append(sub if sub is not None else "<dyn>")
        return "".join(parts)

    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _reconstruct_string(node.left)
        right = _reconstruct_string(node.right)
        if left is None and right is None:
            return None
        return (left or "<dyn>") + (right or "<dyn>")

    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
        attr = node.func.attr
        # "...".format(...) — return the receiver template string.
        if attr == "format":
            return _reconstruct_string(node.func.value)
        # ", ".join([...]) — return the separator (we lose the items, but
        # callers that look for SQL keywords will fall back to the parent
        # f-string context anyway).
        if attr == "join":
            return _reconstruct_string(node.func.value)

    return None


def _yields_qmark(node: ast.AST) -> bool:
    """Check if a GeneratorExp / List / BinOp(Mult) yields ``"?"`` strings.

    Detects the M4 bug class:
      - ``("?" for _ in row)`` — GeneratorExp with elt being ``"?"``
      - ``["?"] * N`` or ``N * ["?"]`` — BinOp Mult with a list of ``"?"``
      - ``["?"] * len(row)`` — same shape as above
      - ``["?", "?", ...]`` — explicit list of ``"?"``
    """
    if isinstance(node, ast.GeneratorExp):
        if isinstance(node.elt, ast.Constant) and node.elt.value == "?":
            return True

    if isinstance(node, ast.List):
        if node.elts and all(
            isinstance(e, ast.Constant) and e.value == "?" for e in node.elts
        ):
            return True

    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mult):
        for side in (node.left, node.right):
            if isinstance(side, ast.List) and side.elts and all(
                isinstance(e, ast.Constant) and e.value == "?" for e in side.elts
            ):
                return True
            if isinstance(side, ast.Constant) and side.value == "?":
                # ``"?" * N`` (without list wrapping) — also produces
                # repeated ``?`` characters used in placeholder lists.
                return True

    return False


def _expr_yields_qmark_string(expr: ast.AST) -> bool:
    """True iff ``expr`` is an expression that statically produces a string
    containing one or more ``?`` placeholders constructed dynamically.

    Patterns matched:

      1. A ``str.join(...)`` whose iterable yields ``"?"`` literals
         (covers ``", ".join("?" for _ in row)`` and
         ``", ".join(["?"] * N)``).
      2. ``ast.Constant`` whose string value contains a literal ``?``
         (used as a hop-through case when expressions are nested).

    Used by ``_collect_qmark_placeholder_names`` to find assignment
    targets that hold ``?``-string values, and by
    ``_arg_constructs_qmark_placeholder`` to detect inline construction
    inside ``execute*`` calls.
    """
    if isinstance(expr, ast.Call) and isinstance(expr.func, ast.Attribute):
        if expr.func.attr == "join":
            for iterable_arg in expr.args:
                if _yields_qmark(iterable_arg):
                    return True
    if isinstance(expr, ast.Constant) and isinstance(expr.value, str):
        if "?" in expr.value:
            return True
    return False


def _collect_qmark_placeholder_names(tree: ast.Module) -> set[str]:
    """Return the set of variable names assigned a ``?``-containing
    placeholder-string anywhere in ``tree``.

    Catches assignments of either shape:
      - ``placeholders = ", ".join("?" for _ in row)``
      - ``placeholders = ", ".join(["?"] * len(row))``

    Module-scope analysis: we don't track scopes, so a name introduced in
    one function bleeds into the visibility of another. This is a
    deliberate over-approximation — in the M4 bug class the assignment is
    in the same function as the offending ``execute*``, and tracking the
    AST function boundary adds complexity without changing the detection
    result.
    """
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            if _expr_yields_qmark_string(node.value):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        names.add(target.id)
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            if _expr_yields_qmark_string(node.value):
                if isinstance(node.target, ast.Name):
                    names.add(node.target.id)
    return names


def _arg_constructs_qmark_placeholder(
    arg: ast.AST, qmark_names: set[str]
) -> bool:
    """True iff ``arg`` is an expression that dynamically produces a string
    containing one or more ``?`` placeholders.

    Walks the expression tree looking for three M4 patterns:

      1. A ``str.join(...)`` whose iterable yields ``"?"`` literals,
         constructed INLINE inside the ``execute*`` argument.
      2. An f-string (``ast.JoinedStr``) containing a literal ``?`` in any
         of its constant fragments — the user-facing pattern that bypasses
         the wrapper's ``?`` → ``%s`` rewrite by hiding the placeholder
         inside an interpolation.
      3. An f-string whose ``FormattedValue`` references a ``Name`` whose
         module-scoped binding holds a ``?``-yielding expression (per
         ``qmark_names`` from ``_collect_qmark_placeholder_names``). This
         is the EXACT M4 bug shape: ``placeholders = ", ".join("?" ...)``
         followed by ``execute(f"... ({placeholders}) ...")``.

    Any pattern is sufficient evidence that the SQL string passed to
    ``execute*`` contains a runtime-variable number of ``?`` placeholders.
    """
    for inner in ast.walk(arg):
        # Pattern 1: inline str.join(...) with iterable yielding "?"
        if isinstance(inner, ast.Call) and isinstance(inner.func, ast.Attribute):
            if inner.func.attr == "join":
                for iterable_arg in inner.args:
                    if _yields_qmark(iterable_arg):
                        return True

        # Pattern 2 + 3: f-string with literal ? OR with a Name binding to
        # a ?-yielding value.
        if isinstance(inner, ast.JoinedStr):
            for part in inner.values:
                if isinstance(part, ast.Constant) and isinstance(part.value, str):
                    if "?" in part.value:
                        return True
                if isinstance(part, ast.FormattedValue):
                    if isinstance(part.value, ast.Name) and part.value.id in qmark_names:
                        return True

    return False


def _is_execute_call(node: ast.Call) -> bool:
    """True iff ``node`` is a method call named ``execute`` or ``executemany``.

    Matches any receiver: ``conn.execute(...)``, ``cursor.execute(...)``,
    ``wrapper.executemany(...)``, ``self._conn.execute(...)``. Free-function
    calls (``execute(...)`` without a receiver) are not matched — they would
    likely indicate a non-DB ``execute`` helper.
    """
    return (
        isinstance(node.func, ast.Attribute)
        and node.func.attr in ("execute", "executemany")
    )


def _iter_execute_call_sql_args(tree: ast.Module):
    """Yield (call_node, first_arg_node) for every ``execute*`` call in
    ``tree`` that has at least one positional argument.

    The first positional argument is the SQL string for every common
    ``execute(sql)`` / ``execute(sql, params)`` shape; callers run their
    pattern detection on this arg.
    """
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and _is_execute_call(node):
            if node.args:
                yield node, node.args[0]


def _scan(predicate, *, allow_known_offenders: bool = True) -> list[str]:
    """Walk every PG-safe ``src/`` file's ``execute*`` calls and apply
    ``predicate(rel_path, first_arg_node, qmark_names)``.

    ``predicate`` returns a string description (the SQLite-ism fragment it
    detected) or None. ``qmark_names`` is the set of variable names
    assigned a ``?``-string in the same module, used for cross-statement
    dataflow detection of the M4 placeholder bug.

    Offending lines that match ``ALLOWLIST_LINE_RANGES`` are silently
    skipped; offending lines that match ``KNOWN_OFFENDERS`` are silently
    skipped only when ``allow_known_offenders`` is True.
    """
    offenders: list[str] = []
    for rel, tree in _walk_pg_safe_src_files():
        qmark_names = _collect_qmark_placeholder_names(tree)
        for call_node, sql_arg in _iter_execute_call_sql_args(tree):
            hit = predicate(rel, sql_arg, qmark_names)
            if hit is None:
                continue
            lineno = call_node.lineno
            if _is_line_allowlisted(rel, lineno):
                continue
            if allow_known_offenders and _is_known_offender(rel, lineno):
                continue
            offenders.append(f"{rel}:{lineno}: {hit}")
    return offenders


# ── Tests against real src/ tree ──────────────────────────────────────────────


def test_no_insert_or_replace_or_ignore_ast():
    """No ``INSERT OR REPLACE`` / ``INSERT OR IGNORE`` in ``execute*`` calls.

    Detects literal, f-string, and concat-constructed strings. Phase 1
    migrated all 17 sites to ``engine_aware_upsert`` — this test asserts
    that none came back via copy-paste or new code.
    """
    def predicate(rel: str, arg: ast.AST, qmark_names: set[str]) -> str | None:
        reconstructed = _reconstruct_string(arg)
        if reconstructed is None:
            return None
        for fragment in INSERT_OR_FRAGMENTS:
            if fragment in reconstructed:
                return f"contains {fragment!r}"
        return None

    offenders = _scan(predicate)
    assert not offenders, (
        "INSERT OR REPLACE/IGNORE in execute() calls — must use "
        "engine_aware_upsert(action=...) from src.utils.db:\n"
        + "\n".join(offenders)
    )


def test_no_pragma_in_pg_safe_files():
    """No ``PRAGMA <name>`` literals in ``execute*`` calls.

    PRAGMA is SQLite-only syntax. Phase 2 migrated all introspection
    PRAGMAs (table_info, index_list, foreign_key_list) to
    ``engine_aware_*`` helpers; the only remaining production PRAGMA is
    the runtime tuning cluster inside ``configure_sqlite_for_production``
    (in src/utils/db.py, allowlisted).

    Line-range allowlist: ``src/scheduler/watch.py:1190-1213`` (Online
    Backup API).
    """
    def predicate(rel: str, arg: ast.AST, qmark_names: set[str]) -> str | None:
        reconstructed = _reconstruct_string(arg)
        if reconstructed is None:
            return None
        if PRAGMA_FRAGMENT in reconstructed:
            return f"contains {PRAGMA_FRAGMENT!r}"
        return None

    offenders = _scan(predicate)
    assert not offenders, (
        "PRAGMA in execute() calls — must use engine_aware_* helpers "
        "from src.utils.db:\n" + "\n".join(offenders)
    )


def test_no_sqlite_master_references_ast():
    """No ``sqlite_master`` references in ``execute*`` calls.

    ``sqlite_master`` is the SQLite system catalog table; PG uses
    ``pg_catalog.pg_tables`` / ``information_schema.tables``. Use
    ``engine_aware_table_list`` from src.utils.db.
    """
    def predicate(rel: str, arg: ast.AST, qmark_names: set[str]) -> str | None:
        reconstructed = _reconstruct_string(arg)
        if reconstructed is None:
            return None
        if SQLITE_MASTER_FRAGMENT in reconstructed:
            return f"contains {SQLITE_MASTER_FRAGMENT!r}"
        return None

    offenders = _scan(predicate)
    assert not offenders, (
        "sqlite_master references in execute() calls — must use "
        "engine_aware_table_list from src.utils.db:\n"
        + "\n".join(offenders)
    )


def test_no_sqlite_date_functions_ast():
    """No SQLite-only date functions in ``execute*`` calls.

    Detects ``julianday(``, ``date('now'``, ``datetime('now'``. Equivalent
    PG syntax differs (e.g., ``CURRENT_DATE - INTERVAL '7 days'``); the
    fix is to compute the cutoff in Python and pass as a parameter.

    Phase 2B migrated three files (council/agent_data, api/routes/ib_status,
    shadow_trading/executor); the remaining sites are tracked in
    ``KNOWN_OFFENDERS`` with a ``"Phase 3+ date-function migration
    deferred"`` reason tag.
    """
    def predicate(rel: str, arg: ast.AST, qmark_names: set[str]) -> str | None:
        reconstructed = _reconstruct_string(arg)
        if reconstructed is None:
            return None
        for fragment in SQLITE_DATE_FRAGMENTS:
            if fragment in reconstructed:
                return f"contains {fragment!r}"
        return None

    offenders = _scan(predicate)
    assert not offenders, (
        "SQLite-only date function in execute() calls — compute the "
        "cutoff timestamp in Python and pass as a parameter:\n"
        + "\n".join(offenders)
    )


def test_no_unrewritten_question_placeholders_ast():
    """No DYNAMICALLY constructed ``?`` placeholders in ``execute*`` calls.

    The M4 bug class. Static ``?`` placeholders are fine: the wrapper
    rewrites them to ``%s`` for psycopg2. But ``f"... ({', '.join('?'
    for _ in row)}) ..."`` builds a runtime-variable number of ``?``
    inside an f-string — psycopg2 does not see this through the wrapper
    rewrite reliably, and substring-based static analysis misses it
    entirely.

    Detects two AST patterns:
      1. ``str.join(...)`` whose iterable yields ``"?"`` literals
         (``", ".join("?" for _ in row)``, ``", ".join(["?"] * N)``).
      2. An f-string containing a literal ``?`` in any of its constant
         fragments (the user-facing pattern that injects the
         placeholders-string into the SQL).
    """
    def predicate(rel: str, arg: ast.AST, qmark_names: set[str]) -> str | None:
        if _arg_constructs_qmark_placeholder(arg, qmark_names):
            # Confirm the surrounding context looks like SQL — reduces
            # false positives on non-SQL ``execute`` overloads (rare).
            reconstructed = _reconstruct_string(arg) or ""
            if any(
                kw in reconstructed.upper()
                for kw in SQL_KEYWORDS_FOR_PLACEHOLDER_CHECK
            ):
                return "dynamic ? placeholder construction in SQL"
        return None

    offenders = _scan(predicate)
    assert not offenders, (
        "Dynamic ? placeholder construction in execute() calls — this "
        "was the M4 / 2026-05-10 bug class. Build the placeholder list "
        "via a wrapper helper that rewrites to %s, or compute the SQL "
        "string entirely with %s placeholders for PG safety:\n"
        + "\n".join(offenders)
    )


# ── Self-tests: synthetic offender fixtures ───────────────────────────────────
#
# These verify the scanner ACTUALLY catches each documented anti-pattern.
# Without them, the tests above could silently degrade into no-ops (e.g.
# if an AST node-class name changes between Python versions). Each test
# parses a small in-memory fixture and asserts the corresponding predicate
# fires.


def _parse_and_scan_with_predicate(source: str, predicate) -> list[tuple[int, str]]:
    """Helper for synthetic tests: parse ``source`` and run ``predicate``
    against every ``execute*`` call's first arg, returning hits without
    consulting the production allowlists.

    Collects qmark-name bindings module-wide first, so dataflow predicates
    (the M4 cross-statement case) work against synthetic fixtures.
    """
    tree = ast.parse(textwrap.dedent(source))
    qmark_names = _collect_qmark_placeholder_names(tree)
    hits: list[tuple[int, str]] = []
    for call_node, sql_arg in _iter_execute_call_sql_args(tree):
        result = predicate("synthetic.py", sql_arg, qmark_names)
        if result is not None:
            hits.append((call_node.lineno, result))
    return hits


def test_scanner_catches_synthetic_insert_or_replace_literal():
    """Self-test: scanner catches a literal ``INSERT OR REPLACE``."""
    source = """
        def bad(conn):
            conn.execute("INSERT OR REPLACE INTO foo VALUES (1, 2)")
    """

    def predicate(rel, arg, qmark_names):
        reconstructed = _reconstruct_string(arg)
        if reconstructed and "INSERT OR REPLACE" in reconstructed:
            return "matched"
        return None

    hits = _parse_and_scan_with_predicate(source, predicate)
    assert hits, (
        "Synthetic test: scanner failed to flag literal INSERT OR REPLACE — "
        "the AST scanner is broken."
    )


def test_scanner_catches_synthetic_insert_or_ignore_in_fstring():
    """Self-test: scanner catches ``INSERT OR IGNORE`` split into an f-string.

    This is the M4 dynamic-fragment case: the OR keyword is interpolated
    rather than literal, so substring scan misses it. ``_reconstruct_string``
    inlines the constant ``"IGNORE"`` from ``ast.Constant`` Name resolution
    when possible; for a variable Name we fall back to ``<dyn>`` which still
    preserves enough literal context for SQL fragments. This test uses an
    explicit literal interpolation so the reconstruction is complete.
    """
    source = """
        def bad(conn, action):
            conn.execute(f"INSERT OR {'IGNORE'} INTO foo VALUES (1)")
    """

    def predicate(rel, arg, qmark_names):
        reconstructed = _reconstruct_string(arg)
        if reconstructed and "INSERT OR IGNORE" in reconstructed:
            return "matched"
        return None

    hits = _parse_and_scan_with_predicate(source, predicate)
    assert hits, (
        "Synthetic test: scanner failed to flag INSERT OR IGNORE built via "
        "f-string interpolation."
    )


def test_scanner_catches_synthetic_pragma_in_execute():
    """Self-test: scanner catches a ``PRAGMA table_info`` call."""
    source = """
        def bad(conn):
            cursor = conn.execute("PRAGMA table_info(foo)")
    """

    def predicate(rel, arg, qmark_names):
        reconstructed = _reconstruct_string(arg)
        if reconstructed and PRAGMA_FRAGMENT in reconstructed:
            return "matched"
        return None

    hits = _parse_and_scan_with_predicate(source, predicate)
    assert hits, "Synthetic test: scanner failed to flag PRAGMA table_info."


def test_scanner_catches_synthetic_sqlite_master_in_execute():
    """Self-test: scanner catches a ``sqlite_master`` reference."""
    source = """
        def bad(conn):
            rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    """

    def predicate(rel, arg, qmark_names):
        reconstructed = _reconstruct_string(arg)
        if reconstructed and SQLITE_MASTER_FRAGMENT in reconstructed:
            return "matched"
        return None

    hits = _parse_and_scan_with_predicate(source, predicate)
    assert hits, "Synthetic test: scanner failed to flag sqlite_master."


def test_scanner_catches_synthetic_datetime_now_in_execute():
    """Self-test: scanner catches a ``datetime('now', '-7 days')`` reference."""
    source = """
        def bad(conn):
            conn.execute("SELECT 1 FROM t WHERE x >= datetime('now', '-7 days')")
    """

    def predicate(rel, arg, qmark_names):
        reconstructed = _reconstruct_string(arg)
        if not reconstructed:
            return None
        for f in SQLITE_DATE_FRAGMENTS:
            if f in reconstructed:
                return "matched"
        return None

    hits = _parse_and_scan_with_predicate(source, predicate)
    assert hits, (
        "Synthetic test: scanner failed to flag datetime('now', ...)."
    )


def test_scanner_catches_synthetic_dynamic_qmark_placeholder_generator():
    """Self-test: scanner catches ``f"... ({', '.join('?' for _ in row)}) ..."``.

    The exact M4 bug pattern that triggered the 2026-05-10 cutover crash.
    """
    source = """
        def bad(cursor, row, cols):
            placeholders = ", ".join("?" for _ in row)
            cursor.execute(
                f"INSERT INTO t ({cols}) VALUES ({placeholders})",
                row,
            )
    """

    def predicate(rel, arg, qmark_names):
        if not _arg_constructs_qmark_placeholder(arg, qmark_names):
            return None
        recon = _reconstruct_string(arg) or ""
        if any(kw in recon.upper() for kw in SQL_KEYWORDS_FOR_PLACEHOLDER_CHECK):
            return "matched"
        return None

    hits = _parse_and_scan_with_predicate(source, predicate)
    assert hits, (
        "Synthetic test: scanner failed to flag dynamic ? placeholder "
        "construction — this is the M4 bug class and MUST be detected."
    )


def test_scanner_catches_synthetic_dynamic_qmark_placeholder_list_mult():
    """Self-test: scanner catches the ``", ".join(["?"] * N)`` variant."""
    source = """
        def bad(cursor, statuses):
            placeholders = ", ".join(["?"] * len(statuses))
            cursor.execute(
                f"SELECT * FROM t WHERE status IN ({placeholders})",
                statuses,
            )
    """

    def predicate(rel, arg, qmark_names):
        if not _arg_constructs_qmark_placeholder(arg, qmark_names):
            return None
        recon = _reconstruct_string(arg) or ""
        if any(kw in recon.upper() for kw in SQL_KEYWORDS_FOR_PLACEHOLDER_CHECK):
            return "matched"
        return None

    hits = _parse_and_scan_with_predicate(source, predicate)
    assert hits, (
        'Synthetic test: scanner failed to flag ", ".join(["?"] * N) — '
        "the list-multiplication variant of the M4 bug class."
    )


def test_scanner_does_not_flag_docstring_mentioning_insert_or_replace():
    """Self-test: scanner ignores ``INSERT OR REPLACE`` in docstrings/prose.

    The fix-direction was 'only flag ``execute*`` call arguments'. A
    function docstring that prose-mentions ``INSERT OR REPLACE`` (as
    Phase 1 migrated files often do) is NOT an offender.
    """
    source = '''
        def write_score(conn):
            """Insert a row. Uses INSERT OR REPLACE keyed on score_date."""
            conn.execute("INSERT INTO t VALUES (?, ?)", (1, 2))
    '''

    def predicate(rel, arg, qmark_names):
        reconstructed = _reconstruct_string(arg)
        if reconstructed and "INSERT OR REPLACE" in reconstructed:
            return "matched"
        return None

    hits = _parse_and_scan_with_predicate(source, predicate)
    assert not hits, (
        "Synthetic test: scanner false-positive — flagged a docstring "
        "mention of INSERT OR REPLACE outside any execute() call."
    )


def test_scanner_does_not_flag_static_question_mark_placeholders():
    """Self-test: scanner does NOT flag static ``?`` placeholders.

    ``"INSERT INTO t VALUES (?, ?, ?)"`` is fine — the wrapper rewrites
    them to ``%s``. Only DYNAMIC placeholder counts are the M4 bug.
    """
    source = """
        def good(conn, a, b, c):
            conn.execute("INSERT INTO t VALUES (?, ?, ?)", (a, b, c))
    """

    def predicate(rel, arg, qmark_names):
        if not _arg_constructs_qmark_placeholder(arg, qmark_names):
            return None
        return "matched"

    hits = _parse_and_scan_with_predicate(source, predicate)
    assert not hits, (
        "Synthetic test: scanner false-positive — flagged static ? "
        "placeholders that the wrapper handles correctly."
    )


# ── Cross-reference test ──────────────────────────────────────────────────────


def test_allowlists_are_disjoint_and_self_consistent():
    """ALLOWLIST_FILES and ALLOWLIST_LINE_RANGES describe different files.

    A file should either be entirely allowlisted OR have specific lines
    allowlisted, but not both. A blanket file allowlist makes the
    line-range entries dead code, which is a maintenance hazard.
    """
    file_overlap = ALLOWLIST_FILES & set(ALLOWLIST_LINE_RANGES.keys())
    assert not file_overlap, (
        "Files appear in both ALLOWLIST_FILES (blanket) and "
        "ALLOWLIST_LINE_RANGES (specific lines) — pick one: "
        + ", ".join(sorted(file_overlap))
    )

    known_files_in_blanket = {p for p, _line, _r in KNOWN_OFFENDERS} & ALLOWLIST_FILES
    assert not known_files_in_blanket, (
        "Files appear in both ALLOWLIST_FILES (blanket) and "
        "KNOWN_OFFENDERS — a blanket allowlist makes the KNOWN_OFFENDERS "
        "entries dead. Pick one: "
        + ", ".join(sorted(known_files_in_blanket))
    )
