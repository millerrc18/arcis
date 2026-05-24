"""CLI: python -m src.tools.ciinvestigate <run_id> [--repo REPO] [--json] [--no-cache]

Called by: operator / agent via `python -m src.tools.ciinvestigate`
Calls: src.tools.ciinvestigate.core.investigate, src.tools._cli_envelope.run_cli
Owns tables: none
Config keys: none
Tests: tests/tools/test_ciinvestigate_integration.py (test_i)

Output modes:
  default  Markdown report: header + per-job table + failed-step preview.
  --json   Full payload as JSON (or error envelope on failure).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from src.tools._cli_envelope import run_cli
from src.tools.ciinvestigate.core import investigate


def _render_markdown(run_id: str, payload: dict) -> str:
    """Render a markdown report from a CI run payload."""
    conclusion = payload.get("conclusion") or "in_progress"
    title = payload.get("displayTitle", "")
    branch = payload.get("headBranch", "")
    sha = payload.get("headSha", "")[:8] if payload.get("headSha") else ""
    status = payload.get("status", "")

    lines = [
        f"# CI Run {run_id} — {conclusion}",
        "",
        f"**Title:** {title}  ",
        f"**Branch:** {branch}  ",
        f"**SHA:** {sha}  ",
        f"**Status:** {status}  ",
        "",
        "## Jobs",
        "",
        "| Job | Conclusion |",
        "|-----|-----------|",
    ]

    jobs = payload.get("jobs") or []
    failed_steps: list[tuple[str, list[dict]]] = []

    for job in jobs:
        job_name = job.get("name", "?")
        job_conclusion = job.get("conclusion", "?")
        lines.append(f"| {job_name} | {job_conclusion} |")

        if job_conclusion in ("failure", "timed_out"):
            steps = job.get("steps") or []
            failed = [s for s in steps if s.get("conclusion") not in ("success", None)]
            if failed:
                failed_steps.append((job_name, failed))

    if failed_steps:
        lines.append("")
        lines.append("## Failed Steps")
        lines.append("")
        for job_name, steps in failed_steps:
            for step in steps:
                step_name = step.get("name", "?")
                step_conclusion = step.get("conclusion", "?")
                lines.append(f"### {job_name} / {step_name} ({step_conclusion})")
                lines.append("")
                log_preview = step.get("log")
                if log_preview:
                    preview_lines = log_preview.splitlines()[-20:]
                    lines.append("```")
                    lines.extend(preview_lines)
                    lines.append("```")
                else:
                    lines.append("*(no log preview)*")
                lines.append("")

    return "\n".join(lines)


def _cli_main(run_id: str, repo: str | None, json_mode: bool, no_cache: bool) -> str:
    """Invoke investigate and format output. Called by run_cli."""
    payload = investigate(run_id, repo=repo, no_cache=no_cache)
    if json_mode:
        return json.dumps(payload, indent=2, default=str)
    return _render_markdown(run_id, payload)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m src.tools.ciinvestigate",
        description="Fetch GitHub Actions CI run details (cached, freshness-validated).",
    )
    parser.add_argument("run_id", help="GitHub Actions run database ID")
    parser.add_argument("--repo", "-R", default=None, help="OWNER/REPO override")
    parser.add_argument(
        "--json", dest="json_mode", action="store_true",
        help="Output full payload as JSON instead of markdown",
    )
    parser.add_argument(
        "--no-cache", dest="no_cache", action="store_true",
        help="Skip cache and force a fresh fetch from gh",
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    parser = _build_parser()
    args = parser.parse_args(argv)

    def _invoke(**kwargs):
        return _cli_main(
            run_id=kwargs["run_id"],
            repo=kwargs.get("repo"),
            json_mode=kwargs.get("json_mode", False),
            no_cache=kwargs.get("no_cache", False),
        )

    run_cli("ciinvestigate", _invoke, args, json_mode=args.json_mode)


if __name__ == "__main__":
    main()
