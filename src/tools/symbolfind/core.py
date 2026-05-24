"""SymbolFind core — locate Python symbol definitions and references via rg.

Called by: src/tools/symbolfind/__main__.py, agents, operators (Python API)
Calls: subprocess (rg), re, json, src.tools._safety.safe_op
Owns tables: none
Config keys: none
Tests: tests/tools/test_symbolfind_integration.py

Public API:
    find(symbol, *, kind='any', path=None) -> list[dict]

Each result dict: {'file': str, 'line': int, 'col': int, 'kind': 'def'|'use', 'snippet': str}

kind='def'  -> class/function definitions + module-level constant assignments
kind='use'  -> references (lines matching symbol but NOT matching def patterns)
kind='any'  -> union of def + use, deduplicated by (file, line)

Fails fast when rg is not on PATH -- no pure-Python fallback (operator decision #8).
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Optional

from src.tools._safety import safe_op


class SymbolFindError(RuntimeError):
    """Raised when rg is missing or returns a non-zero exit code (except exit 1).

    Exit code 1 from rg means 'no matches found' — that is a success case
    returning an empty list, not an error.
    """


def _build_def_pattern(escaped_symbol: str) -> str:
    r"""Return the rg regex pattern matching symbol definitions.

    Matches:
    - Function/class definitions: ^\s*(def|class)\s+<sym>\b
    - Module-level constant assignments: ^\s*<sym>\s*=
    """
    return rf"^\s*(def|class)\s+{escaped_symbol}\b|^\s*{escaped_symbol}\s*="


def _build_use_pattern(escaped_symbol: str) -> str:
    """Return the rg regex pattern matching any occurrence of the symbol."""
    return rf"\b{escaped_symbol}\b"


def _is_def_line(line_text: str, escaped_symbol: str) -> bool:
    """Return True if the line matches the def-side patterns."""
    def_regex = re.compile(
        rf"^\s*(def|class)\s+{escaped_symbol}\b|^\s*{escaped_symbol}\s*="
    )
    return bool(def_regex.search(line_text))


def _parse_rg_json(stdout: str) -> list[dict]:
    """Parse rg --json output and return raw match dicts.

    Each returned dict has: 'file', 'line', 'col', 'snippet'.
    The 'kind' field is not set here — caller attaches it.
    """
    matches = []
    for line in stdout.splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") != "match":
            continue
        data = event["data"]
        matches.append({
            "file": data["path"]["text"],
            "line": data["line_number"],
            "col": data["submatches"][0]["start"] + 1,
            "snippet": data["lines"]["text"].rstrip(),
        })
    return matches


def _run_rg(pattern: str, search_path: Path) -> str:
    """Run rg and return stdout. Raises SymbolFindError on missing rg or bad exit."""
    cmd = ["rg", "--json", "--type", "py", pattern, str(search_path)]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=30,
            check=False,
        )
    except FileNotFoundError:
        raise SymbolFindError(
            "rg (ripgrep) not on PATH. Install via:\n"
            "  winget install BurntSushi.ripgrep.MSVC\n"
            "  scoop install ripgrep\n"
            "  choco install ripgrep"
        )

    if result.returncode not in (0, 1):
        raise SymbolFindError(
            f"rg exited with code {result.returncode}: {result.stderr.strip()}"
        )

    return result.stdout


def _find_def(escaped_symbol: str, search_path: Path) -> list[dict]:
    """Find symbol definitions. Returns list of dicts with kind='def'."""
    pattern = _build_def_pattern(escaped_symbol)
    stdout = _run_rg(pattern, search_path)
    rows = _parse_rg_json(stdout)
    for row in rows:
        row["kind"] = "def"
    return rows


def _find_use(escaped_symbol: str, search_path: Path) -> list[dict]:
    """Find symbol references (excludes def-side matches). Returns list with kind='use'."""
    pattern = _build_use_pattern(escaped_symbol)
    stdout = _run_rg(pattern, search_path)
    rows = _parse_rg_json(stdout)
    result = []
    for row in rows:
        if not _is_def_line(row["snippet"], escaped_symbol):
            row["kind"] = "use"
            result.append(row)
    return result


@safe_op(name="symbolfind", mutates=False)
def find(
    symbol: str,
    *,
    kind: str = "any",
    path: Optional[Path] = None,
) -> list[dict]:
    """Find symbol definitions and/or references in Python source.

    kind='def'  -> symbol definitions only (def/class/module-level constant assignment)
    kind='use'  -> symbol references only (excludes def/class declaration lines)
    kind='any'  -> union of def + use, deduplicated by (file, line)

    Returns list of dicts: {'file': str, 'line': int, 'col': int, 'kind': 'def'|'use', 'snippet': str}
    """
    if kind not in ("def", "use", "any"):
        raise SymbolFindError(f"kind must be 'def', 'use', or 'any'; got {kind!r}")

    search_path = path or Path.cwd()
    escaped_symbol = re.escape(symbol)

    if kind == "def":
        return _find_def(escaped_symbol, search_path)

    if kind == "use":
        return _find_use(escaped_symbol, search_path)

    def_rows = _find_def(escaped_symbol, search_path)
    use_rows = _find_use(escaped_symbol, search_path)

    seen: set[tuple[str, int]] = set()
    combined: list[dict] = []
    for row in def_rows + use_rows:
        key = (row["file"], row["line"])
        if key not in seen:
            seen.add(key)
            combined.append(row)

    return combined
