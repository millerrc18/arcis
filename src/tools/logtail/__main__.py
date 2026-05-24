"""CLI entry point for LogTail tool.

Usage:
    python -m src.tools.logtail [--lines N] [--level LEVEL] [--grep PATTERN]
                                [--log-path PATH] [--json]

Called by: operators, agent subprocess calls
Calls: src.tools._cli_envelope.run_cli, src.tools.logtail.core.tail
Owns tables: none
Config keys: none (log path resolved by core.py via paths.logs_runtime)
Tests: tests/tools/test_logtail_integration.py (test_cli_envelope_missing_file)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional

from src.tools._cli_envelope import run_cli
from src.tools.logtail.core import tail


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m src.tools.logtail",
        description="Tail the last N entries from arcis.log with multi-line awareness.",
    )
    parser.add_argument("--lines", type=int, default=100, metavar="N",
                        help="Number of log entries to return (default: 100)")
    parser.add_argument("--level", default=None, metavar="LEVEL",
                        help="Minimum log level filter (DEBUG/INFO/WARNING/ERROR/CRITICAL)")
    parser.add_argument("--grep", default=None, metavar="PATTERN",
                        help="Case-sensitive substring filter applied to each entry")
    parser.add_argument("--log-path", default=None, dest="log_path", metavar="PATH",
                        help="Path to log file (default: cfg.paths.logs_runtime/arcis.log)")
    parser.add_argument("--json", action="store_true", dest="json_mode",
                        help="Output as JSON array instead of Markdown")
    return parser


def _run(*, lines: int, level: Optional[str], grep: Optional[str],
         log_path: Optional[str], json_mode: bool) -> str:
    resolved_path = Path(log_path) if log_path is not None else None
    entries = tail(lines=lines, level=level, grep=grep, log_path=resolved_path)

    if json_mode:
        return json.dumps(entries)

    # Markdown output
    n = len(entries)
    # Pre-filter count is n when no filter was applied; if filters were applied
    # we don't have easy access to the pre-filter count here, so we use n for
    # the base when reporting.
    output_parts = ["\n\n".join(entries)] if entries else ["(no entries)"]
    footer = f"({n} entries)"
    if level or grep:
        footer = f"({n} entries, filtered)"
    output_parts.append(footer)
    return "\n\n".join(output_parts)


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    run_cli("logtail", _run, args, json_mode=args.json_mode)


if __name__ == "__main__":
    main()
