"""CLI entry point for ProcessManager — python -m src.tools.processmanager.

Called by: operator agents, test subprocesses
Calls: src.tools.processmanager.core, src.tools._cli_envelope.run_cli
Owns tables: none
Config keys: services.*, safety_windows.no_restart_overnight
Tests: tests/tools/test_processmanager_integration.py (case j)
"""

from __future__ import annotations

import argparse
import json as json_mod

from src.tools._cli_envelope import run_cli
from src.tools.processmanager.core import RestartResult, ServiceState, _restart_impl, _start_impl, _status_impl, _stop_impl


def _render_status_markdown(service: str, state: ServiceState) -> str:
    return (
        "# Service Status\n"
        "| Service       | State    |\n"
        "|---------------|----------|\n"
        f"| {service:<13} | {state.value:<8} |"
    )


def _render_restart_markdown(service: str, result: RestartResult) -> str:
    evidence = result.log_evidence or "None"
    return (
        f"# Restart Result: {service}\n"
        f"- restarted: {result.restarted}\n"
        f"- verified:  {result.verified}\n"
        f"- elapsed:   {result.elapsed_s:.1f}s\n"
        f"- evidence:  {evidence}\n"
        f"- state:     {result.state.value}"
    )


def _run(verb: str, service: str, *, confirm: bool, emergency: bool, json: bool) -> str:
    if verb == "status":
        state = _status_impl(service)
        if json:
            return json_mod.dumps({"service": service, "state": state.value})
        return _render_status_markdown(service, state)

    if verb == "start":
        state = _start_impl(service)
        if json:
            return json_mod.dumps({"service": service, "state": state.value})
        return _render_status_markdown(service, state)

    if verb == "stop":
        state = _stop_impl(service)
        if json:
            return json_mod.dumps({"service": service, "state": state.value})
        return _render_status_markdown(service, state)

    if verb == "restart":
        result = _restart_impl(service)
        if json:
            return json_mod.dumps({
                "service": service,
                "restarted": result.restarted,
                "verified": result.verified,
                "elapsed_s": result.elapsed_s,
                "log_evidence": result.log_evidence,
                "state": result.state.value,
            })
        return _render_restart_markdown(service, result)

    raise ValueError(f"Unknown verb: {verb!r}")


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="python -m src.tools.processmanager",
        description="NSSM service control for Arcis services.",
    )
    parser.add_argument(
        "verb",
        choices=["status", "start", "stop", "restart"],
        help="Operation to perform",
    )
    parser.add_argument("service", help="Service name or alias")
    parser.add_argument(
        "--confirm",
        action="store_true",
        default=False,
        help="Confirm mutating operation (required for start/stop/restart)",
    )
    parser.add_argument(
        "--emergency",
        action="store_true",
        default=False,
        help="Bypass safety window (logged)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="json",
        default=False,
        help="Output JSON instead of markdown",
    )

    args = parser.parse_args()

    run_cli(
        tool_name="processmanager",
        fn=_run,
        args_namespace=args,
        json_mode=args.json,
    )


if __name__ == "__main__":
    main()
