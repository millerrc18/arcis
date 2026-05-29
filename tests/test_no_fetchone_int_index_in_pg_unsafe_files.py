"""AST sweep: no .fetchone()[<int>] positional indexing in PG-reachable files.

Root cause context: `conn.execute(...).fetchone()[0]` uses positional indexing.
Against psycopg2's RealDictCursor (used by connect_db() on PG), `[0]` is a key
lookup that raises KeyError(0). This was the bug class at watch.py:1178 — same
class as task #34 (KeyError:0 in Wave 5 orphan-guard).

This sweep uses the same allowlist as test_no_sqlite_isms_in_pg_safe_files.py to
identify which files are PG-reachable (i.e., not SQLite-only-by-design). For each
such file, AST-parses to find `Subscript` nodes whose value is a `Call` with
`func.attr == 'fetchone'` and whose slice is an integer constant.

Called by: pytest (Sprint 5 Wave A T1)
Calls: none
Owns tables: none
Config keys: none
"""

from __future__ import annotations

import ast
from pathlib import Path


# ── Constants (mirrors test_no_sqlite_isms_in_pg_safe_files.py allowlist) ─────

SRC = Path(__file__).parent.parent / "src"

# Files where SQLite-only patterns are intentional — same set as the
# no-sqlite-isms test. These files legitimately use SQLite-only connections
# and are not reachable via connect_db() on PG.
ALLOWLIST_FILES: frozenset[str] = frozenset({
    "src/schema/sqlite.py",
    "src/schema/registry.py",
    "src/schema/postgres.py",
    "src/utils/db.py",
    "src/training/trainer.py",
    "src/sync/render_sync.py",
    "src/sync/reconcile.py",
    # Uses a raw psycopg2.connect() connection passed from the simulation oracle
    # (not connect_db()), so the cursor returns plain tuples. Integer indexing
    # r[0] IS correct positional access here — RealDictCursor is not in the path.
    "src/simulation/lifecycle/oracle/_checks_db.py",
})

# Scripts that are excluded from the fetchall listcomp scan for one of two reasons:
#   A) They use a raw psycopg2.connect() default cursor (tuple rows, not RealDictCursor)
#      so row[N] is correct positional access — the scanner would fire a false positive.
#   B) Their fetchall() calls are guarded exclusively by PRAGMA/sqlite_master queries
#      that will fail on PG before any positional indexing occurs.
# Each entry carries a reason tag.
SCRIPTS_ALLOWLIST_FETCHALL: dict[str, str] = {
    "scripts/audit_db_sync.py": (
        "Uses raw psycopg2.connect() default cursor (tuple rows, not RealDictCursor); "
        "row[0] is correct positional access here."
    ),
    "scripts/diagnose_leakage.py": (
        "All fetchall()[N] sites are inside PRAGMA table_info() queries which are "
        "SQLite-only — PG will never reach the positional index."
    ),
    "scripts/post_close_check.py": (
        "All fetchall()[N] sites use PRAGMA table_info() / sqlite_master queries which "
        "are SQLite-only — PG will never reach the positional index."
    ),
    "scripts/weekly_review.py": (
        "All fetchall()[N] sites use PRAGMA table_info() / sqlite_master queries which "
        "are SQLite-only — PG will never reach the positional index."
    ),
}

# Known violations in src/ that existed at the time the scanner was introduced
# and have not yet been fixed. Each entry is (rel_path, lineno, reason_tag).
# Do NOT add entries here to silence NEW violations — fix them instead.
KNOWN_OFFENDERS_FETCHALL: frozenset[tuple[str, int, str]] = frozenset({
    (
        "src/evaluation/build_score.py",
        352,
        "Missed by PR-1060 cleanup; uses connect_db() non-PRAGMA query — "
        "MUST be fixed (use row['build_score'] or _scalar). #100-followup",
    ),
})


# ── Scanner ────────────────────────────────────────────────────────────────────


def _scan_fetchone_int_index(src_root: Path) -> list[str]:
    """Walk PG-reachable src/ files and find .fetchone()[<int>] patterns.

    Returns a list of 'rel_path:lineno' strings for each violation found.
    An empty list means no violations.
    """
    violations: list[str] = []
    for path in sorted(src_root.rglob("*.py")):
        rel = str(path.relative_to(src_root.parent).as_posix())
        if rel in ALLOWLIST_FILES:
            continue
        try:
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(path))
        except SyntaxError:
            continue

        for node in ast.walk(tree):
            # Look for Subscript nodes: expr[something]
            if not isinstance(node, ast.Subscript):
                continue
            # The subscripted value must be a Call
            if not isinstance(node.value, ast.Call):
                continue
            call = node.value
            # The call must be an attribute access with attr == 'fetchone'
            if not isinstance(call.func, ast.Attribute):
                continue
            if call.func.attr != "fetchone":
                continue
            # The slice must be an integer constant
            slice_node = node.slice
            # Python 3.9+: slice is the index directly (no Index wrapper)
            # Python 3.8: slice may be ast.Index wrapping the constant
            if isinstance(slice_node, ast.Index):
                slice_node = slice_node.value  # type: ignore[attr-defined]
            if isinstance(slice_node, ast.Constant) and isinstance(
                slice_node.value, int
            ):
                violations.append(f"{rel}:{node.lineno}")

    return violations


# ── fetchall() list-comprehension integer-index scanner ───────────────────────


def _scan_fetchall_int_index_listcomp(
    src_root: Path,
    *,
    skip_known_offenders: bool = True,
) -> list[str]:
    """Walk PG-reachable files and find [r[<int>] for r in <expr>.fetchall()].

    Matches list comprehensions (and generator expressions) whose iterable is
    a call with attribute ``fetchall`` AND whose element expression subscripts
    the loop variable with an integer constant.

    Skips files in ``ALLOWLIST_FILES`` (SQLite-only by design) and
    ``SCRIPTS_ALLOWLIST_FETCHALL`` (raw-psycopg2 or PRAGMA-only contexts).
    When ``skip_known_offenders`` is True, also skips entries in
    ``KNOWN_OFFENDERS_FETCHALL`` (pre-existing violations not yet fixed).

    Returns a list of 'rel_path:lineno' strings for each violation found.
    An empty list means no violations.
    """
    violations: list[str] = []
    for path in sorted(src_root.rglob("*.py")):
        rel = str(path.relative_to(src_root.parent).as_posix())
        if rel in ALLOWLIST_FILES:
            continue
        if rel in SCRIPTS_ALLOWLIST_FETCHALL:
            continue
        try:
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(path))
        except SyntaxError:
            continue

        for node in ast.walk(tree):
            # Match both ListComp and GeneratorExp — same structure
            if not isinstance(node, (ast.ListComp, ast.GeneratorExp)):
                continue
            # Must have at least one comprehension clause
            if not node.generators:
                continue
            gen = node.generators[0]
            # The iterable must be a call with attr == 'fetchall'
            iter_node = gen.iter
            if not isinstance(iter_node, ast.Call):
                continue
            if not isinstance(iter_node.func, ast.Attribute):
                continue
            if iter_node.func.attr != "fetchall":
                continue
            # The loop target must be a simple Name (e.g. `r`)
            if not isinstance(gen.target, ast.Name):
                continue
            loop_var = gen.target.id
            # The element expression must be Subscript(Name(loop_var), int)
            elt = node.elt
            if not isinstance(elt, ast.Subscript):
                continue
            if not (isinstance(elt.value, ast.Name) and elt.value.id == loop_var):
                continue
            slice_node = elt.slice
            # Python 3.8 compat: unwrap ast.Index
            if isinstance(slice_node, ast.Index):
                slice_node = slice_node.value  # type: ignore[attr-defined]
            if not (
                isinstance(slice_node, ast.Constant)
                and isinstance(slice_node.value, int)
            ):
                continue
            if skip_known_offenders and any(
                off_path == rel and off_line == node.lineno
                for off_path, off_line, _ in KNOWN_OFFENDERS_FETCHALL
            ):
                continue
            violations.append(f"{rel}:{node.lineno}")

    return violations


# ── Production sweep test ──────────────────────────────────────────────────────


def test_no_fetchone_int_index_in_pg_unsafe_files():
    """No .fetchone()[<int>] positional indexing in PG-reachable src/ files.

    Against psycopg2 RealDictCursor, row[<int>] is a key lookup, not positional
    — raises KeyError(<int>). Use row['column_name'] or CompatRow (which supports
    both) instead.

    If this test fails with a list of violations, the operator must triage each
    site. Do NOT add to ALLOWLIST_FILES to silence real violations.
    """
    violations = _scan_fetchone_int_index(SRC)
    assert not violations, (
        f"{len(violations)} .fetchone()[<int>] positional-index site(s) found "
        f"in PG-reachable files — these will raise KeyError(<int>) on PG:\n"
        + "\n".join(violations)
    )


# ── Self-test: scanner catches synthetic violation ─────────────────────────────


def test_scanner_catches_synthetic_fetchone_int_index(tmp_path):
    """Self-test: scanner catches a synthetic .fetchone()[0] site.

    Writes a temporary Python file with the violation pattern and verifies the
    scanner flags it. Without this self-test, the production sweep could silently
    degrade into a no-op (e.g., if AST node shapes change between Python versions).
    """
    bad_file = tmp_path / "bad_fetchone.py"
    bad_file.write_text(
        "def check_count(conn):\n"
        "    count = conn.execute('SELECT COUNT(*) FROM t').fetchone()[0]\n"
        "    return count\n"
    )
    violations = _scan_fetchone_int_index(tmp_path)
    assert any("bad_fetchone.py" in v for v in violations), (
        f"Scanner should have caught synthetic .fetchone()[0] violation; "
        f"got: {violations!r}"
    )


def test_scanner_does_not_flag_fetchone_name_index(tmp_path):
    """Self-test: scanner does NOT flag .fetchone()['col'] string indexing.

    String-keyed access is the correct pattern for PG RealDictCursor rows.
    """
    good_file = tmp_path / "good_fetchone.py"
    good_file.write_text(
        "def check_count(conn):\n"
        "    count = conn.execute('SELECT COUNT(*) AS n FROM t').fetchone()['n']\n"
        "    return count\n"
    )
    violations = _scan_fetchone_int_index(tmp_path)
    assert not any("good_fetchone.py" in v for v in violations), (
        f"Scanner false-positive: flagged string-keyed .fetchone()['col'] access"
    )


def test_scanner_does_not_flag_list_int_index(tmp_path):
    """Self-test: scanner does NOT flag list[0] that is unrelated to fetchone."""
    good_file = tmp_path / "good_list.py"
    good_file.write_text(
        "def first(items):\n"
        "    return items[0]\n"
    )
    violations = _scan_fetchone_int_index(tmp_path)
    assert not any("good_list.py" in v for v in violations), (
        f"Scanner false-positive: flagged items[0] unrelated to fetchone"
    )


# ── New tests for [r[N] for r in fetchall()] pattern ──────────────────────────


def test_scanner_catches_synthetic_fetchall_int_index_listcomp(tmp_path):
    """Self-test: scanner catches [r[0] for r in conn.execute(...).fetchall()].

    Against psycopg2 RealDictCursor, r[0] inside a list comprehension over
    fetchall() rows raises KeyError(0) for the same reason as fetchone()[0].
    This test verifies the extended scanner fires on the list-comprehension form.
    """
    bad_file = tmp_path / "bad_fetchall_listcomp.py"
    bad_file.write_text(
        "def get_prices(conn):\n"
        "    prices = [r[0] for r in conn.execute('SELECT price FROM t').fetchall()]\n"
        "    return prices\n"
    )
    violations = _scan_fetchall_int_index_listcomp(tmp_path)
    assert any("bad_fetchall_listcomp.py" in v for v in violations), (
        f"Scanner should have caught synthetic [r[0] for r in ...fetchall()] violation; "
        f"got: {violations!r}"
    )


def test_scanner_does_not_flag_fetchall_name_key_listcomp(tmp_path):
    """Self-test: scanner does NOT flag [r['name'] for r in ...fetchall()].

    String-keyed access inside a list comprehension is the correct pattern
    for PG RealDictCursor rows — it should NOT be flagged.
    """
    good_file = tmp_path / "good_fetchall_namekey.py"
    good_file.write_text(
        "def get_symbols(conn):\n"
        "    return [r['symbol'] for r in conn.execute('SELECT symbol FROM t').fetchall()]\n"
    )
    violations = _scan_fetchall_int_index_listcomp(tmp_path)
    assert not any("good_fetchall_namekey.py" in v for v in violations), (
        f"Scanner false-positive: flagged string-keyed [r['name'] for r in ...fetchall()]"
    )


def test_scanner_does_not_flag_get_method_in_listcomp(tmp_path):
    """Self-test: scanner does NOT flag [d.get(0) for d in some_list].

    A .get() call with integer argument is a different pattern — defensive
    access on an arbitrary list, not positional-index on fetchall() rows.
    """
    good_file = tmp_path / "good_get_method.py"
    good_file.write_text(
        "def extract(rows):\n"
        "    return [d.get(0) for d in rows]\n"
    )
    violations = _scan_fetchall_int_index_listcomp(tmp_path)
    assert not any("good_get_method.py" in v for v in violations), (
        f"Scanner false-positive: flagged [d.get(0) for d in rows] pattern"
    )


def test_no_fetchall_int_index_listcomp_in_src():
    """Production sweep: no new [r[N] for r in <expr>.fetchall()] in src/ + scripts/.

    Sites in SCRIPTS_ALLOWLIST_FETCHALL are excluded (raw-psycopg2 tuple cursor
    or PRAGMA-only SQLite contexts). Sites in KNOWN_OFFENDERS_FETCHALL are
    silently skipped — each entry there carries a reason tag and must be fixed
    in a follow-up PR. Do NOT add to either list to silence new violations.
    """
    violations = _scan_fetchall_int_index_listcomp(SRC)
    scripts_root = SRC.parent / "scripts"
    if scripts_root.exists():
        violations += _scan_fetchall_int_index_listcomp(scripts_root)
    assert not violations, (
        f"{len(violations)} [r[<int>] for r in ...fetchall()] positional-index "
        f"site(s) found in PG-reachable files — these will raise KeyError(<int>) on PG:\n"
        + "\n".join(violations)
    )
