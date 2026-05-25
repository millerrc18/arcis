"""HealthProbe CLI entry point.

Usage:
    python -m src.tools.healthprobe [--services NAME[,NAME...]] [--stale-seconds N] [--json]

Called by: operator agents, automated checks
Calls: src.tools.healthprobe.core.check, src.tools._cli_envelope.run_cli
Owns tables: none
Config keys: services.*, ports.*, paths.*
Tests: tests/tools/test_healthprobe_integration.py (case h)
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from src.tools._cli_envelope import run_cli


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m src.tools.healthprobe",
        description="Composite read-only health check for Arcis NSSM services.",
    )
    p.add_argument(
        "--services",
        metavar="NAME[,NAME...]",
        default=None,
        help="Comma-separated NSSM service names (default: all 3)",
    )
    p.add_argument(
        "--stale-seconds",
        type=int,
        default=None,
        metavar="N",
        help="Override heartbeat staleness threshold in seconds",
    )
    p.add_argument(
        "--json",
        action="store_true",
        default=False,
        help="Output JSON error envelope on failure (for agent consumption)",
    )
    return p


def _run(services=None, stale_seconds=None, json=False):
    from src.tools._config import load_arcis_config
    from src.tools.healthprobe.core import _check_impl

    # Support test-seam env override for cfg path
    override = os.environ.get("ARCIS_CONFIG_PATH_OVERRIDE")
    if override:
        cfg = load_arcis_config(Path(override))
    else:
        cfg = load_arcis_config()

    svc_list = [s.strip() for s in services.split(",")] if services else None

    result = _check_impl(services=svc_list, stale_seconds=stale_seconds, cfg=cfg)

    # Format as markdown table
    lines = [
        f"# Health Probe ({result['as_of_et']})",
        "",
        f"## Overall: {result['overall']}",
        "",
        "| Service | State | Heartbeat | Port | Recent Errors (15m) | Verdict |",
        "|---------|-------|-----------|------|---------------------|---------|",
    ]
    for svc, sh in result["services"].items():
        hb_str = "N/A"
        if sh["heartbeat_fresh"] is True:
            hb_str = "fresh"
        elif sh["heartbeat_fresh"] is False:
            hb_str = f"STALE ({sh['heartbeat_reason']})" if sh["heartbeat_reason"] else "STALE"

        port_str = "N/A"
        if sh["port_listening"] is True:
            port_str = "listening"
        elif sh["port_listening"] is False:
            port_str = "not listening"

        lines.append(
            f"| {svc} | {sh['state']} | {hb_str} | {port_str} | {sh['recent_error_count']} | {sh['verdict']} |"
        )

    return "\n".join(lines)


def main():
    parser = _build_parser()
    args = parser.parse_args()
    run_cli("healthprobe", _run, args, json_mode=args.json)


if __name__ == "__main__":
    main()
