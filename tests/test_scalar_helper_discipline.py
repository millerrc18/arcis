"""Discipline test: forbids the cross-engine scalar-fetch dispatch idiom.

The Sprint 5 Wave A+B T1ext sweep introduced a defensive dispatch pattern
to handle the M4/2026-05-10 KeyError:0 bug class: every call site that did
``conn.execute(...).fetchone()[0]`` had to inline-check whether the row was
a raw dict (psycopg2 RealDictCursor under ``PostgresConnectionWrapper.execute()``)
or a sequence-like row (sqlite3.Row / CompatRow). 82 sites grew the same
verbose two-branch idiom:

    _row = conn.execute("SELECT COUNT(*) FROM t").fetchone()
    total = _row[0] if not isinstance(_row, dict) else list(_row.values())[0]

Operator review observation (PR #1058): one site at ``watch.py:1181`` drifted
to a second idiom that uses a literal column key:

    count = row[0] if not isinstance(row, dict) else row['count']

This second idiom is brittle to SQL changes — psycopg2 auto-aliases
``COUNT(*)`` → ``'count'``, but ``MIN(x)`` → ``'min'``, ``AVG(x)`` → ``'avg'``,
subqueries → unpredictable names. Any SQL evolution breaks the literal key.

To prevent future idiom drift, every cross-engine scalar fetch MUST route
through the ``_scalar(row)`` helper at ``src/utils/db.py``:

    from src.utils.db import _scalar
    total = _scalar(conn.execute("SELECT COUNT(*) FROM t").fetchone())

This test AST-walks every ``.py`` file under ``src/`` (minus ``src/utils/db.py``
where ``_scalar`` is defined) and forbids the inline dispatch pattern.

Why AST instead of grep: the dispatch can be formatted across multiple lines,
broken at the ``else`` boundary by a linter, or wrapped in parentheses. The
substring forms vary; the AST structure is unique:

    IfExp(
        test=UnaryOp(op=Not(), operand=Call(func=Name('isinstance'),
                                            args=[..., Name('dict')])),
        body=Subscript(value=..., slice=Constant(0)),
        orelse=...
    )

Called by: pytest
Calls: none
Owns tables: none
Config keys: none
Tests: self (positive synthetic fixture verifies the AST matcher fires)
"""

from __future__ import annotations

import ast
import textwrap
from pathlib import Path


SRC = Path(__file__).parent.parent / "src"

# _scalar lives here; the helper itself is allowed to use the dispatch internally.
ALLOWLIST_FILES: frozenset[str] = frozenset({
    "src/utils/db.py",
})


def _is_isinstance_dict_check(node: ast.AST) -> bool:
    """True if node is ``not isinstance(X, dict)`` or ``isinstance(X, dict)``."""
    inner = node
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        inner = node.operand
    if not isinstance(inner, ast.Call):
        return False
    if not (isinstance(inner.func, ast.Name) and inner.func.id == "isinstance"):
        return False
    if len(inner.args) != 2:
        return False
    second = inner.args[1]
    return isinstance(second, ast.Name) and second.id == "dict"


def _is_scalar_fetch_dispatch(node: ast.IfExp) -> bool:
    """True if node has the exact shape of a cross-engine scalar-fetch dispatch.

    The IfExp body must be a Subscript with integer constant slice 0
    (``X[0]``). The orelse must be a dict-shape access on the same name:
    either ``Y['key']`` (literal key, Idiom B) or
    ``list(Y.values())[0]`` (positional via list-conversion, Idioms A & C).

    This narrow match avoids false positives on the dozens of unrelated
    ``X.get(...) if isinstance(X, dict) else fallback`` patterns scattered
    through the codebase — those are guarding against ``None`` / non-dict
    inputs, NOT recovering a scalar from a cross-engine fetchone.
    """
    body = node.body
    orelse = node.orelse

    # Body must be ``X[0]`` (Subscript with integer constant 0)
    if not isinstance(body, ast.Subscript):
        return False
    slice_node = body.slice
    if not (isinstance(slice_node, ast.Constant) and slice_node.value == 0):
        return False

    # Orelse: either ``X['key']`` OR ``list(X.values())[0]``
    if isinstance(orelse, ast.Subscript):
        # Literal-key access ``X['key']`` — Idiom B
        if isinstance(orelse.slice, ast.Constant) and isinstance(orelse.slice.value, str):
            return True
        # ``list(X.values())[0]`` — Idioms A & C
        outer_slice = orelse.slice
        if isinstance(outer_slice, ast.Constant) and outer_slice.value == 0:
            inner = orelse.value
            if (isinstance(inner, ast.Call)
                    and isinstance(inner.func, ast.Name)
                    and inner.func.id == "list"
                    and len(inner.args) == 1):
                arg = inner.args[0]
                if (isinstance(arg, ast.Call)
                        and isinstance(arg.func, ast.Attribute)
                        and arg.func.attr == "values"):
                    return True
    return False


def _scan_file(path: Path) -> list[tuple[int, str]]:
    """Return list of (lineno, snippet) for dispatch sites in ``path``."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError:
        return []
    offenders: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.IfExp):
            continue
        if _is_isinstance_dict_check(node.test) and _is_scalar_fetch_dispatch(node):
            offenders.append((node.lineno, ast.unparse(node)[:80]))
    return offenders


def test_no_inline_scalar_dispatch_idiom() -> None:
    """No file under ``src/`` (except db.py) may use the inline dispatch idiom.

    Use ``_scalar(row)`` from ``src.utils.db`` instead.
    """
    offenders: list[str] = []
    for path in SRC.rglob("*.py"):
        rel = path.relative_to(SRC.parent).as_posix()
        if rel in ALLOWLIST_FILES:
            continue
        for lineno, snippet in _scan_file(path):
            offenders.append(f"{rel}:{lineno}: {snippet}")
    assert not offenders, (
        "Inline dispatch idiom for cross-engine fetchone (the M4 bug class) "
        "found at the sites below. Use ``_scalar(row)`` from "
        "``src.utils.db`` instead. The helper handles None / sqlite3.Row / "
        "CompatRow / raw-dict shapes uniformly.\n"
        + "\n".join(offenders)
    )


def test_scalar_matcher_fires_on_synthetic_positive() -> None:
    """Confirm the AST matcher catches a synthetic positive fixture."""
    src = textwrap.dedent("""
        def f(conn):
            row = conn.execute("SELECT COUNT(*) FROM t").fetchone()
            total = row[0] if not isinstance(row, dict) else list(row.values())[0]
            return total
    """).strip()
    tree = ast.parse(src)
    found = [
        n for n in ast.walk(tree)
        if isinstance(n, ast.IfExp)
        and _is_isinstance_dict_check(n.test)
        and _is_scalar_fetch_dispatch(n)
    ]
    assert len(found) == 1, f"Expected 1 match in synthetic fixture, got {len(found)}"


def test_scalar_matcher_skips_unrelated_isinstance() -> None:
    """Confirm the matcher does NOT fire on isinstance checks unrelated to dict."""
    src = textwrap.dedent("""
        def f(x):
            return x[0] if not isinstance(x, list) else x['k']
    """).strip()
    tree = ast.parse(src)
    found = [
        n for n in ast.walk(tree)
        if isinstance(n, ast.IfExp) and _is_isinstance_dict_check(n.test)
    ]
    assert not found, "Matcher fired on non-dict isinstance check"


def test_scalar_matcher_skips_get_with_isinstance_dict() -> None:
    """Confirm the matcher does NOT fire on ``X.get(k) if isinstance(X, dict) else default``.

    This is a different and legitimate pattern — guarding against non-dict
    inputs when a function accepts loose shapes. It's NOT a scalar-fetch
    recovery from cross-engine fetchone.
    """
    src = textwrap.dedent("""
        def f(t):
            return t.get('exit_price') if isinstance(t, dict) else None
    """).strip()
    tree = ast.parse(src)
    found = [
        n for n in ast.walk(tree)
        if isinstance(n, ast.IfExp)
        and _is_isinstance_dict_check(n.test)
        and _is_scalar_fetch_dispatch(n)
    ]
    assert not found, "Matcher false-positived on ``.get()`` defensive pattern"


def test_scalar_matcher_catches_idiom_b_literal_key() -> None:
    """Confirm the matcher catches the brittle Idiom B (literal key)."""
    src = textwrap.dedent("""
        def f(conn):
            row = conn.execute("SELECT COUNT(*) FROM t").fetchone()
            return row[0] if not isinstance(row, dict) else row['count']
    """).strip()
    tree = ast.parse(src)
    found = [
        n for n in ast.walk(tree)
        if isinstance(n, ast.IfExp)
        and _is_isinstance_dict_check(n.test)
        and _is_scalar_fetch_dispatch(n)
    ]
    assert len(found) == 1, f"Expected 1 Idiom-B match, got {len(found)}"
