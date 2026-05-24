"""SymbolFind CLI — locate Python symbol definitions and references.

Called by: python -m src.tools.symbolfind
Calls: src.tools.symbolfind.core.find, src.tools._cli_envelope.run_cli
Owns tables: none
Config keys: none
Tests: tests/tools/test_symbolfind_integration.py (CLI subprocess test)

Usage:
    python -m src.tools.symbolfind <symbol> [--kind def|use|any] [--path PATH] [--json]

Positional arguments:
    symbol          The Python symbol name to search for.

Optional arguments:
    --kind          'def', 'use', or 'any' (default: 'any').
    --path PATH     Root directory to search (default: current working directory).
    --json          Output a JSON array of dicts instead of a markdown table.

Markdown output format: file:line | kind | snippet table.
JSON output format: array of {'file', 'line', 'col', 'kind', 'snippet'} dicts.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from src.tools._cli_envelope import run_cli
from src.tools.symbolfind.core import find


def _render_markdown(results: list[dict]) -> str:
    """Render results as a markdown table."""
    if not results:
        return "(no matches found)"
    header = "| file:line | kind | snippet |"
    sep = "|-----------|------|---------|"
    rows = [header, sep]
    for r in results:
        file_line = f"{r['file']}:{r['line']}"
        rows.append(f"| {file_line} | {r['kind']} | {r['snippet']} |")
    return "\n".join(rows)


def _cli_find(symbol: str, kind: str, path: str | None, json_mode: bool) -> str:
    """Invoke find() and render output for the CLI."""
    search_path = Path(path) if path else None
    results = find(symbol, kind=kind, path=search_path)
    if json_mode:
        return json.dumps(results, indent=2)
    return _render_markdown(results)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Locate Python symbol definitions and references via rg."
    )
    parser.add_argument("symbol", help="Python symbol name to search for.")
    parser.add_argument(
        "--kind",
        choices=["def", "use", "any"],
        default="any",
        help="'def' for definitions, 'use' for references, 'any' for both (default: any).",
    )
    parser.add_argument(
        "--path",
        default=None,
        help="Root directory to search (default: current working directory).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="json_mode",
        help="Output JSON array instead of markdown table.",
    )
    args = parser.parse_args()

    run_cli(
        "symbolfind",
        lambda **kw: _cli_find(kw["symbol"], kw["kind"], kw["path"], kw["json_mode"]),
        args,
        json_mode=args.json_mode,
    )


if __name__ == "__main__":
    main()
