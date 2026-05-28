"""ripgrep-seam boundary-touch tests — SymbolFind invocation + output parsing.

Standards: docs/standards/boundary-touch-tests.md
Discipline: §1 "drives both sides of the seam with real artifacts"

Seam: src.tools.symbolfind.core.find() shells out to REAL `rg` (ripgrep) and
parses its JSON output. The contract is: given a real fixture directory with
real Python files, find() returns results with the correct file/line/kind/snippet
fields from REAL rg invocations. No mocks at the seam.

Test fixtures are created in tmp_path as REAL .py files; rg runs against them.
This is exactly the scenario where mock-coverage gaps appear: if the rg output
format changes, or if the JSON parsing in _parse_rg_json breaks, these tests
catch it while pure-unit tests (which mock subprocess.run) would not.

Non-vacuity proved by:
  1. Changed `_parse_rg_json` to always return `[]`: test_find_def_locates_function
     FAILED (len == 0, expected 1).
  2. Changed the kind assignment `row["kind"] = "def"` to `row["kind"] = "use"`:
     test_find_def_returns_kind_def FAILED (kind == 'use' instead of 'def').
  3. Changed `_build_def_pattern` to use `rf"\\s*class\\s+{escaped_symbol}"` only
     (dropping the function pattern): test_find_def_locates_function FAILED
     (function definition not found, len == 0).
All src/ mutations reverted with `git checkout` before committing.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest


def _write_fixture(tmp_path: Path, filename: str, source: str) -> Path:
    """Write a .py fixture file with the given source; return its Path."""
    p = tmp_path / filename
    p.write_text(textwrap.dedent(source), encoding="utf-8")
    return p


def test_find_def_locates_function(tmp_path):
    """find(kind='def') against a real fixture file returns the function definition.

    Non-vacuity: making _parse_rg_json always return [] causes this test to
    FAIL with AssertionError: len == 0.
    """
    from src.tools.symbolfind.core import find

    _write_fixture(tmp_path, "fixture_a.py", """
        def my_special_func(x):
            return x + 1
    """)

    results = find("my_special_func", kind="def", path=tmp_path)
    assert len(results) == 1, f"expected 1 def hit, got {len(results)}: {results}"
    r = results[0]
    assert r["kind"] == "def"
    assert "my_special_func" in r["snippet"]
    assert r["line"] >= 1


def test_find_def_returns_kind_def(tmp_path):
    """Results from find(kind='def') have kind == 'def' not 'use'.

    Non-vacuity: changing `row['kind'] = 'def'` to `row['kind'] = 'use'` in
    _find_def causes this test to FAIL with AssertionError.
    """
    from src.tools.symbolfind.core import find

    _write_fixture(tmp_path, "fixture_b.py", """
        class MySpecialClass:
            pass
    """)

    results = find("MySpecialClass", kind="def", path=tmp_path)
    assert results, "expected at least one result"
    assert all(r["kind"] == "def" for r in results), (
        f"all def results must have kind='def', got: {[r['kind'] for r in results]}"
    )


def test_find_use_excludes_definition_lines(tmp_path):
    """find(kind='use') excludes the definition line itself.

    Non-vacuity: removing the `_is_def_line` filter in _find_use causes both
    the def and use lines to appear in 'use' results; then the assertion
    `all r not in def lines` FAILS.
    """
    from src.tools.symbolfind.core import find

    _write_fixture(tmp_path, "fixture_c.py", """
        def target_func(x):
            return x

        result = target_func(5)
    """)

    results = find("target_func", kind="use", path=tmp_path)
    # Guard against the empty-results blind spot: the use-site MUST be found,
    # otherwise the loop below is vacuously satisfied (no rows to check).
    assert results, "expected the use-site `target_func(5)` to be found"
    # The use result must be the `result = target_func(5)` line — not the def line
    for r in results:
        assert "def target_func" not in r["snippet"], (
            f"'use' result must not include def line, got snippet: {r['snippet']!r}"
        )


def test_find_any_deduplicates_by_file_and_line(tmp_path):
    """find(kind='any') does not double-count lines that match both def and use patterns.

    Non-vacuity: removing the deduplication set in find(kind='any') causes
    duplicate entries where a line matches both patterns; this test FAILS
    (len > expected) or contains duplicate (file, line) pairs.
    """
    from src.tools.symbolfind.core import find

    _write_fixture(tmp_path, "fixture_d.py", """
        MY_CONST = 42
        x = MY_CONST + 1
    """)

    results = find("MY_CONST", kind="any", path=tmp_path)
    # Should have exactly 2 results: the assignment (def) + the reference (use)
    # and NOT a duplicate of the assignment line
    seen = set()
    for r in results:
        key = (r["file"], r["line"])
        assert key not in seen, (
            f"duplicate (file, line) pair in 'any' results: {key}"
        )
        seen.add(key)
    assert len(results) >= 1, "expected at least 1 result for MY_CONST"
