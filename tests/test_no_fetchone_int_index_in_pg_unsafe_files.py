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
