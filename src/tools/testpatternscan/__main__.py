"""TestPatternScan CLI — AST-based test anti-pattern scanner.

Called by: python -m src.tools.testpatternscan
Calls: src.tools.testpatternscan.core.scan, src.tools._cli_envelope.run_cli
Owns tables: none
Config keys: none
Tests: tests/tools/test_testpatternscan_integration.py (CLI subprocess tests)

Usage:
    python -m src.tools.testpatternscan [--path DIR] [--kinds K[,K...]] [--json]

Optional arguments:
    --path DIR      Directory to scan (default: cwd/tests).
    --kinds K,...   Comma-separated rule kinds: vacuous,patch_drift,mock_only,
                    side_effect_unreached (default: vacuous,patch_drift).
    --json          Output JSON list of findings instead of plain text.

JSON output format: array of Finding dicts.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
from pathlib import Path

from src.tools._cli_envelope import run_cli
from src.tools.testpatternscan.core import scan


def _cli_scan(path: str | None, kinds: str | None, json_mode: bool) -> str:
    search_path = Path(path) if path else None
    kind_list = [k.strip() for k in kinds.split(",")] if kinds else None
    results = scan(path=search_path, kinds=kind_list)
    if json_mode:
        return json.dumps([dataclasses.asdict(f) for f in results], indent=2)
    if not results:
        return "(no findings)"
    lines = []
    for f in results:
        lines.append(
            f"{f.file}:{f.line} [{f.rule}/{f.confidence}] {f.function}: {f.detail}"
        )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="python -m src.tools.testpatternscan",
        description="AST-based test anti-pattern scanner.",
    )
    parser.add_argument(
        "--path",
        default=None,
        help="Directory to scan (default: cwd/tests).",
    )
    parser.add_argument(
        "--kinds",
        default=None,
        help="Comma-separated rule kinds (default: vacuous,patch_drift).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="json_mode",
        help="Output JSON list of findings.",
    )
    args = parser.parse_args()

    run_cli(
        "testpatternscan",
        lambda **kw: _cli_scan(kw["path"], kw["kinds"], kw["json_mode"]),
        args,
        json_mode=args.json_mode,
    )


if __name__ == "__main__":
    main()
