"""CLI entry point for the DocConsistency tool — python -m src.tools.docconsistency.

Called by: operator agents, test subprocesses (pytest subprocess cases)
Calls: src.tools.docconsistency.core.scan, src.tools._cli_envelope.run_cli
Owns tables: none
Config keys: none
Tests: tests/tools/test_docconsistency_integration.py (subprocess cases)
"""

from __future__ import annotations

import argparse
import json as json_mod

from src.tools._cli_envelope import run_cli
from src.tools.docconsistency.core import scan


def _run(*, cmd: str, target: list[str] | None, allowlist: str | None, json: bool) -> str:
    """Dispatch to scan() and return formatted output.

    Called by run_cli(**vars(args_namespace)). Raises DocConsistencyError
    subclasses on failure — run_cli handles the JSON envelope.
    """
    from pathlib import Path

    targets = target if target else None
    allowlist_path = Path(allowlist) if allowlist else None

    result = scan(targets=targets, allowlist_path=allowlist_path)

    if json:
        return json_mod.dumps(result)

    findings = result["findings"]
    lines = [
        f"DocConsistency scan — {result['scan_at']}",
        f"Targets scanned: {len(result['targets_scanned'])}",
        f"Refs found: {result['refs_found']}  "
        f"OK: {result['refs_verified_ok']}  "
        f"Allowlisted: {result['refs_allowlisted']}  "
        f"Findings: {len(findings)}",
    ]
    if findings:
        lines.append("")
        for f in findings:
            lines.append(
                f"  [{f['severity']}] {f['doc_path']}:{f['doc_line']} -> {f['ref']}"
            )
            lines.append(f"    {f['detail']}")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="python -m src.tools.docconsistency",
        description="DocConsistency v1 — verify file:line refs in markdown docs.",
    )
    subparsers = parser.add_subparsers(dest="cmd", required=True)

    scan_parser = subparsers.add_parser(
        "scan",
        help="Scan markdown targets for dead file:line references.",
    )
    scan_parser.add_argument(
        "--target",
        action="append",
        dest="target",
        metavar="PATH",
        help="File to scan (repeatable). Omit to use default scope.",
    )
    scan_parser.add_argument(
        "--allowlist",
        default=None,
        metavar="PATH",
        help="Path to allowlist YAML. Defaults to data/docconsistency-allowlist.yaml.",
    )
    scan_parser.add_argument(
        "--json",
        action="store_true",
        dest="json",
        help="Output JSON instead of human-readable text.",
    )

    args = parser.parse_args()

    run_cli(
        tool_name="docconsistency",
        fn=_run,
        args_namespace=args,
        json_mode=args.json,
    )


if __name__ == "__main__":
    main()
