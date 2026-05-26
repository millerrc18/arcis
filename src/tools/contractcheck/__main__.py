"""CLI entry point for the ContractCheck tool — python -m src.tools.contractcheck.

Called by: operator agents, test subprocesses
Calls: src.tools.contractcheck.core.record, .verify, .diff,
       src.tools._cli_envelope.run_cli
Owns tables: none
Config keys: contracts (arcis_config.yaml)
Tests: tests/tools/test_contractcheck.py (T6)
"""

from __future__ import annotations

import argparse
import json as json_mod

from src.tools._cli_envelope import run_cli
from src.tools.contractcheck.core import diff, record, verify


def _add_json_flag(p: argparse.ArgumentParser) -> None:
    p.add_argument("--json", action="store_true", dest="json", help="Output JSON")


def _run(*, cmd: str, name: str, baseline_a: str | None, baseline_b: str | None, json: bool) -> str:
    """Dispatch to record(), verify(), or diff() and return formatted string.

    Called by run_cli(**vars(args_namespace)). Raises ContractCheckError
    on failure — run_cli handles the JSON envelope.
    """
    if cmd == "record":
        path = record(name)
        if json:
            return json_mod.dumps({"path": str(path)})
        return f"Recorded baseline: {path}"

    if cmd == "verify":
        result = verify(name)
        if json:
            return json_mod.dumps(result)
        verdict = result.get("verdict", "UNKNOWN")
        baseline = result.get("baseline_path", "")
        return f"Contract '{name}': {verdict} (baseline: {baseline})"

    if cmd == "diff":
        result = diff(name, baseline_a, baseline_b)
        if json:
            return json_mod.dumps(result)
        verdict = result.get("verdict", "UNKNOWN")
        return f"Diff '{name}' {baseline_a} vs {baseline_b}: {verdict}"

    raise ValueError(f"Unknown subcommand: {cmd!r}")


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="python -m src.tools.contractcheck",
        description="Record, verify, and diff CLI-invocation baselines (ContractCheck v1).",
    )
    subparsers = parser.add_subparsers(dest="cmd", required=True)

    p_record = subparsers.add_parser("record", help="Invoke contract and write a new baseline.")
    p_record.add_argument("name", help="Contract name (from arcis_config.yaml contracts section)")
    _add_json_flag(p_record)

    p_verify = subparsers.add_parser("verify", help="Invoke contract and compare vs latest baseline.")
    p_verify.add_argument("name", help="Contract name")
    _add_json_flag(p_verify)

    p_diff = subparsers.add_parser("diff", help="Compare two recorded baselines by filename.")
    p_diff.add_argument("name", help="Contract name")
    p_diff.add_argument("baseline_a", help="First baseline filename (e.g. 2026-05-25T17-30-00Z.json)")
    p_diff.add_argument("baseline_b", help="Second baseline filename")
    _add_json_flag(p_diff)

    args = parser.parse_args()

    if not hasattr(args, "baseline_a"):
        args.baseline_a = None
    if not hasattr(args, "baseline_b"):
        args.baseline_b = None

    run_cli(tool_name="contractcheck", fn=_run, args_namespace=args, json_mode=args.json)


if __name__ == "__main__":
    main()
