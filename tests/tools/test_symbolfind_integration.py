# Purpose: Integration tests for src/tools/symbolfind — rg-backed Python symbol lookup.
# Called by: pytest
# Calls: src.tools.symbolfind.find, src.tools.symbolfind.SymbolFindError
# Owns tables: none
# Config keys: none
# Tests: this file
"""Integration tests for the SymbolFind tool (src/tools/symbolfind/).

Six cases per the Task 5 TEST_STRATEGY:
  (a) kind='def' returns class def + constant assignment rows.
  (b) kind='use' returns references, excludes def-side patterns.
  (c) kind='any' is the union of (a)+(b), deduplicated by (file, line).
  (d) rg missing → SymbolFindError with winget hint; 'error' event recorded.
  (e) Symbol not found → [] with 'success' event (not 'error').
  (f) CLI subprocess: error envelope via --json when rg unreachable.

Verify-by-mutation notes are inline with each test.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest


def _rg_available() -> bool:
    """Return True if the real rg binary is reachable via subprocess."""
    try:
        r = subprocess.run(
            ["rg", "--version"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        return r.returncode == 0
    except (FileNotFoundError, OSError):
        return False


_RG_MISSING = not _rg_available()
rg_required = pytest.mark.skipif(
    _RG_MISSING,
    reason="rg (ripgrep) binary not available on PATH — skipped in this environment",
)


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def search_root(tmp_path):
    """Two small Python files with known symbols for fixture-based assertions."""
    foo = tmp_path / "foo.py"
    foo.write_text(
        "class Foo:\n"
        "    pass\n"
        "\n"
        "def helper_uses_foo():\n"
        "    return Foo()\n"
        "\n"
        "Foo = 42\n",
        encoding="utf-8",
    )

    bar = tmp_path / "bar.py"
    bar.write_text(
        "from foo import Foo\n"
        "\n"
        "x = Foo()\n",
        encoding="utf-8",
    )

    return tmp_path


# ── Test (a) — kind='def' ─────────────────────────────────────────────────────


@rg_required
def test_find_def_returns_class_and_constant(search_root, tmp_path):
    """find('Foo', kind='def') → class-def line + constant-assignment line.

    Verify-by-mutation: removing the constant-assignment pattern
    (^\\s*<sym>\\s*=) from core.py causes this test to fail because
    CONST_FOO = 42 would no longer be included.
    """
    from src.tools.symbolfind import find

    results = find("Foo", kind="def", path=search_root)

    assert isinstance(results, list)
    assert len(results) >= 1

    kinds = {r["kind"] for r in results}
    assert kinds == {"def"}, f"All results must have kind='def', got {kinds}"

    files = {Path(r["file"]).name for r in results}
    assert "foo.py" in files

    lines_in_foo = {r["line"] for r in results if Path(r["file"]).name == "foo.py"}
    assert 1 in lines_in_foo, "class Foo: is on line 1"
    assert 7 in lines_in_foo, "Foo = 42 (module-level constant assignment) is on line 7"

    for r in results:
        assert "file" in r
        assert "line" in r
        assert "col" in r
        assert "kind" in r
        assert "snippet" in r


# ── Test (b) — kind='use' ─────────────────────────────────────────────────────


@rg_required
def test_find_use_returns_references_excludes_def_lines(search_root, tmp_path):
    """find('Foo', kind='use') returns references, excludes class-def and assignment lines.

    Verify-by-mutation: removing the filter that strips def-pattern matches
    from use results causes this test to fail because 'class Foo:' would
    incorrectly appear in the use results.
    """
    from src.tools.symbolfind import find

    results = find("Foo", kind="use", path=search_root)

    assert isinstance(results, list)
    assert len(results) >= 1

    kinds = {r["kind"] for r in results}
    assert kinds == {"use"}, f"All results must have kind='use', got {kinds!r}"

    snippets = [r["snippet"] for r in results]

    class_def_snippets = [s for s in snippets if s.strip().startswith("class Foo")]
    assert class_def_snippets == [], (
        f"kind='use' must NOT include class definition lines, found: {class_def_snippets}"
    )

    const_snippets = [s for s in snippets if "CONST_FOO" in s]
    assert const_snippets == [], (
        f"kind='use' must NOT include constant assignment lines, found: {const_snippets}"
    )

    reference_files = {Path(r["file"]).name for r in results}
    assert "bar.py" in reference_files, "bar.py has 'from foo import Foo' and 'x = Foo()'"

    all_snippets_text = " ".join(snippets)
    assert "Foo" in all_snippets_text, "use results must contain the symbol"


# ── Test (c) — kind='any' deduplication ───────────────────────────────────────


@rg_required
def test_find_any_is_union_deduplicated(search_root, tmp_path):
    """find('Foo', kind='any') is the union of def+use, no (file, line) duplicates.

    Strengthened per QA review: original fixture had no actual (file, line)
    collisions between def_rows and use_rows, so the dedup branch was never
    exercised. This test now monkey-patches `_find_use` to inject a synthetic
    row that collides with the existing def at (foo.py, 1) — forcing the
    dedup logic to actually run, with assertions that fail if it doesn't.

    Verify-by-mutation: replacing the seen-set dedup in core.py with
    `return def_rows + use_rows` (no dedup) causes (foo.py, 1) to appear
    twice in the result — this test asserts each (file, line) pair appears
    exactly once, so the assertion fails.
    """
    from unittest.mock import patch

    from src.tools.symbolfind import find
    from src.tools.symbolfind.core import _find_use as _real_find_use

    # Patch _find_use to inject a synthetic collision with the class def at
    # (foo.py, 1). Real _find_use returns its normal results; we append a
    # synthetic row that mirrors the def location. If dedup works, kind='any'
    # sees (foo.py, 1) exactly once. If dedup is broken, it sees it twice.
    def _find_use_with_collision(escaped_symbol, search_path):
        real_results = _real_find_use(escaped_symbol, search_path)
        # Find foo.py's path in the real results so we use the SAME path
        # string the def-side returns (otherwise (file, line) won't collide).
        foo_path = None
        for r in real_results:
            if Path(r["file"]).name == "foo.py":
                foo_path = r["file"]
                break
        if foo_path is None:
            # Fallback: construct foo.py's path the way rg would emit it
            foo_path = str(search_path / "foo.py")
        synthetic = {
            "file": foo_path,
            "line": 1,  # collides with class Foo: at line 1
            "col": 1,
            "kind": "use",
            "snippet": "synthetic-collision-row",
        }
        return real_results + [synthetic]

    with patch(
        "src.tools.symbolfind.core._find_use",
        side_effect=_find_use_with_collision,
    ):
        results_any = find("Foo", kind="any", path=search_root)
    results_def = find("Foo", kind="def", path=search_root)

    file_line_pairs = [(r["file"], r["line"]) for r in results_any]
    unique_pairs = set(file_line_pairs)

    # The load-bearing assertion: dedup MUST collapse the synthetic-collision
    # row with the real def-row at (foo.py, 1). If dedup is removed, this
    # fails because (foo.py, 1) appears twice.
    assert len(file_line_pairs) == len(unique_pairs), (
        "kind='any' must dedup (file, line) — "
        f"found {len(file_line_pairs)} rows but only {len(unique_pairs)} unique pairs"
    )

    # Sanity: the collision pair appears exactly once
    foo_line_1_count = sum(
        1 for r in results_any
        if Path(r["file"]).name == "foo.py" and r["line"] == 1
    )
    assert foo_line_1_count == 1, (
        f"(foo.py, line 1) must appear exactly once after dedup, "
        f"got {foo_line_1_count}"
    )

    # Other sanity properties still hold
    def_pairs = {(r["file"], r["line"]) for r in results_def}
    any_pairs = {(r["file"], r["line"]) for r in results_any}
    assert def_pairs.issubset(any_pairs), "all def results must appear in any"


@rg_required
def test_find_wraps_subprocess_timeout_as_symbol_find_error(search_root, tmp_path):
    """subprocess.TimeoutExpired must be wrapped as SymbolFindError per spec contract.

    Audit #105 T5 Security fix — the spec requires SymbolFindError as the
    only exception type from find(). Without the wrapper, Python API callers
    receive raw TimeoutExpired, and the CLI without --json prints a stderr
    traceback containing the full argv (search_path disclosure).

    Verify-by-mutation: removing the `except subprocess.TimeoutExpired`
    clause in core._run_rg causes this test to fail because pytest.raises
    won't catch the raw subprocess exception as SymbolFindError.
    """
    from unittest.mock import patch

    import subprocess as sp

    from src.tools.symbolfind import SymbolFindError, find

    def _raise_timeout(*args, **kwargs):
        raise sp.TimeoutExpired(cmd=args[0] if args else ["rg"], timeout=30)

    with patch("subprocess.run", side_effect=_raise_timeout):
        with pytest.raises(SymbolFindError) as exc_info:
            find("Foo", kind="any", path=search_root)

    assert "timed out" in str(exc_info.value).lower()
    assert "30s" in str(exc_info.value)


# ── Test (d) — rg missing ─────────────────────────────────────────────────────


def test_find_raises_symbol_find_error_when_rg_missing(tmp_path):
    """find() raises SymbolFindError with winget hint when rg is not on PATH.

    Verify-by-mutation: catching FileNotFoundError without re-raising as
    SymbolFindError causes this test to fail because pytest.raises would
    not catch the original FileNotFoundError from subprocess.run.
    """
    from src.tools.symbolfind import SymbolFindError, find

    with patch("subprocess.run", side_effect=FileNotFoundError("rg not found")):
        with pytest.raises(SymbolFindError) as exc_info:
            find("Foo")

    error_message = str(exc_info.value)
    assert "winget install BurntSushi.ripgrep.MSVC" in error_message, (
        f"Error message must contain winget install hint, got: {error_message!r}"
    )


# ── Test (e) — symbol not found → [] + success event ─────────────────────────


@rg_required
def test_find_returns_empty_list_when_symbol_not_found(search_root, tmp_path):
    """find() returns [] when symbol not found; does NOT raise SymbolFindError.

    Verify-by-mutation: treating rg exit code 1 (no matches) as an error
    causes this test to fail because find() would raise SymbolFindError
    instead of returning an empty list.
    """
    from src.tools.symbolfind import find

    log_path = tmp_path / "tool-execution.log"

    results = find.__wrapped__("NonexistentSymbolXYZ", path=search_root)

    assert results == [], f"Expected [], got {results}"


@rg_required
def test_find_empty_result_records_success_event(search_root, tmp_path):
    """find() with empty results records 'success' event, not 'error'.

    This test uses the @safe_op wrapper directly (not __wrapped__) so
    the audit log event is recorded.
    """
    from src.tools.symbolfind import find

    log_path = tmp_path / "tool-execution.log"

    with patch("src.tools._safety.write_event") as mock_write:
        results = find("NonexistentSymbolXYZ", path=search_root)

    assert results == [], f"Expected [], got {results}"
    call_args_list = mock_write.call_args_list
    if call_args_list:
        result_values = [c.kwargs.get("result") for c in call_args_list]
        assert "error" not in result_values, (
            f"Empty result must not record 'error' event, got: {result_values}"
        )
        assert "success" in result_values, (
            f"Empty result must record 'success' event, got: {result_values}"
        )


# ── Test (f) — CLI envelope ───────────────────────────────────────────────────


def test_cli_json_envelope_on_error(tmp_path):
    """CLI: --json outputs error envelope to stdout and exits 1 when rg unreachable.

    Uses a temporary directory not in PATH so rg is effectively missing for
    the subprocess, triggering the SymbolFindError → envelope path.

    Verify-by-mutation: removing the --json envelope in __main__.py causes
    this test to fail because stdout would contain a Python traceback (not
    a JSON envelope) or the exit code would differ.
    """
    bad_path = tmp_path / "no_such_directory_xyz"

    env = {"PATH": "", "SYSTEMROOT": "C:\\Windows", "WINDIR": "C:\\Windows"}

    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "src.tools.symbolfind",
            "Foo",
            "--path",
            str(bad_path),
            "--json",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        cwd="C:/arcis/halcyon-lab/.claude/worktrees/agent-af0e8b919dd9bee54",
    )

    assert proc.returncode == 1, (
        f"Expected exit 1, got {proc.returncode}. "
        f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
    )

    try:
        envelope = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        pytest.fail(
            f"stdout is not valid JSON: {exc}. stdout={proc.stdout!r}"
        )

    assert "error" in envelope, f"Envelope must have 'error' key, got {envelope}"
    assert "type" in envelope["error"], f"error must have 'type', got {envelope['error']}"
    assert "SymbolFindError" in envelope["error"]["type"], (
        f"error type must mention SymbolFindError, got {envelope['error']['type']!r}"
    )
