"""GitArchaeology CLI entry point.

Usage:
  python -m src.tools.gitarchaeology <subcommand> [options]

Subcommands (7 read-only ops):
  log        [--range RANGE] [--path PATH] [--limit N] [--repo DIR]
  blame      <file> [--start N] [--end N] [--repo DIR]
  show       <sha> [--path PATH] [--repo DIR]
  diff       <ref_a> <ref_b> [--path PATH] [--repo DIR]
  rev-list   <range> [--path PATH] [--limit N] [--repo DIR]
  merge-base <ref_a> <ref_b> [--repo DIR]
  tag-l      [--pattern PATTERN] [--repo DIR]

Each subcommand also accepts:
  --json                   Output JSON envelope (errors also JSON).
  --max-output-bytes N     Override per-op default output size cap (DA4).

FORBIDDEN ops (structural defense — argparse rejects them at parse time):
  commit, push, reset, rebase, checkout, branch-D, clean-f,
  cherry-pick, stash-drop, tag-d
"""

from __future__ import annotations

import argparse
import json
import sys

from src.tools._cli_envelope import run_cli


def _run(
    *,
    cmd: str,
    # log args
    range: str | None = None,
    path: str | None = None,
    format: str = "%H%x09%an%x09%ai%x09%s",
    limit: int = 50,
    # blame args
    file: str | None = None,
    start: int | None = None,
    end: int | None = None,
    # show / diff / merge-base / rev-list / tag-l args
    sha: str | None = None,
    ref_a: str | None = None,
    ref_b: str | None = None,
    pattern: str | None = None,
    # shared
    repo: str | None = None,
    max_output_bytes: int | None = None,
    # json flag is consumed by run_cli; _run receives it via **vars(args)
    json: bool = False,
) -> str:
    """Dispatch to the correct core function based on args.cmd.

    Called by run_cli(**vars(args_namespace)). Returns a string for stdout.
    """
    import src.tools.gitarchaeology.core as _core

    if cmd == "log":
        result = _core.log(
            range=range,
            path=path,
            format=format,
            limit=limit,
            repo=repo,
            max_output_bytes=max_output_bytes,
        )
        return _json_or_text(result, as_json=json)

    if cmd == "blame":
        if file is None:
            raise ValueError("blame requires <file> positional argument")
        result = _core.blame(
            file,
            start_line=start,
            end_line=end,
            repo=repo,
            max_output_bytes=max_output_bytes,
        )
        return _json_or_text(result, as_json=json)

    if cmd == "show":
        if sha is None:
            raise ValueError("show requires <sha> positional argument")
        result = _core.show(
            sha,
            path=path,
            repo=repo,
            max_output_bytes=max_output_bytes,
        )
        return _json_or_text(result, as_json=json)

    if cmd == "diff":
        if ref_a is None or ref_b is None:
            raise ValueError("diff requires <ref_a> <ref_b> positional arguments")
        result = _core.diff(
            ref_a,
            ref_b,
            path=path,
            repo=repo,
            max_output_bytes=max_output_bytes,
        )
        return _json_or_text(result, as_json=json)

    if cmd == "rev-list":
        if range is None:
            raise ValueError("rev-list requires <range> positional argument")
        result = _core.rev_list(
            range,
            path=path,
            limit=limit if limit != 50 else None,
            repo=repo,
            max_output_bytes=max_output_bytes,
        )
        return _json_or_text(result, as_json=json)

    if cmd == "merge-base":
        if ref_a is None or ref_b is None:
            raise ValueError("merge-base requires <ref_a> <ref_b> positional arguments")
        result = _core.merge_base(ref_a, ref_b, repo=repo)
        return _json_or_text(result, as_json=json)

    if cmd == "tag-l":
        result = _core.tag_l(pattern=pattern, repo=repo)
        return _json_or_text(result, as_json=json)

    raise ValueError(f"unknown subcommand: {cmd!r}")


def _json_or_text(result: object, *, as_json: bool) -> str:
    """Serialize result to JSON string or human-readable text."""
    if as_json:
        return json.dumps(result)
    if isinstance(result, list):
        lines = []
        for item in result:
            if isinstance(item, dict):
                lines.append("\t".join(str(v) for v in item.values()))
            else:
                lines.append(str(item))
        return "\n".join(lines)
    if isinstance(result, dict):
        return "\n".join(f"{k}: {v}" for k, v in result.items())
    return str(result)


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="python -m src.tools.gitarchaeology",
        description="Read-only git CLI wrapper (7 ops). Mutating ops are not registered.",
    )
    subparsers = parser.add_subparsers(dest="cmd", metavar="cmd")
    subparsers.required = True

    def _add_common(sp: argparse.ArgumentParser) -> None:
        sp.add_argument("--repo", default=None, metavar="DIR",
                        help="Run git as if started in DIR (-C <dir>).")
        sp.add_argument("--json", action="store_true", default=False,
                        help="Output JSON (errors also as JSON envelope).")
        sp.add_argument("--max-output-bytes", type=int, default=None, dest="max_output_bytes",
                        metavar="N", help="Override per-op output size cap (DA4).")

    # ── log ─────────────────────────────────────────────────────────
    sp_log = subparsers.add_parser("log", help="Run git log.")
    sp_log.add_argument("--range", default=None, metavar="RANGE",
                        help="Commit range (e.g., HEAD~10..HEAD).")
    sp_log.add_argument("--path", default=None, metavar="PATH",
                        help="Limit to commits touching PATH.")
    sp_log.add_argument("--format", default="%H%x09%an%x09%ai%x09%s", metavar="FMT",
                        help="Git log format string.")
    sp_log.add_argument("--limit", type=int, default=50, metavar="N",
                        help="Maximum number of commits (default: 50).")
    _add_common(sp_log)

    # ── blame ────────────────────────────────────────────────────────
    sp_blame = subparsers.add_parser("blame", help="Run git blame.")
    sp_blame.add_argument("file", metavar="FILE", help="File to blame.")
    sp_blame.add_argument("--start", type=int, default=None, metavar="N",
                          help="Start line (1-based).")
    sp_blame.add_argument("--end", type=int, default=None, metavar="N",
                          help="End line (1-based, inclusive).")
    _add_common(sp_blame)

    # ── show ─────────────────────────────────────────────────────────
    sp_show = subparsers.add_parser("show", help="Run git show.")
    sp_show.add_argument("sha", metavar="SHA", help="Commit SHA to show.")
    sp_show.add_argument("--path", default=None, metavar="PATH",
                         help="Limit diff to PATH.")
    _add_common(sp_show)

    # ── diff ─────────────────────────────────────────────────────────
    sp_diff = subparsers.add_parser("diff", help="Run git diff.")
    sp_diff.add_argument("ref_a", metavar="REF_A")
    sp_diff.add_argument("ref_b", metavar="REF_B")
    sp_diff.add_argument("--path", default=None, metavar="PATH",
                         help="Limit diff to PATH.")
    _add_common(sp_diff)

    # ── rev-list ─────────────────────────────────────────────────────
    sp_rev = subparsers.add_parser("rev-list", help="Run git rev-list.")
    sp_rev.add_argument("range", metavar="RANGE", help="Commit range.")
    sp_rev.add_argument("--path", default=None, metavar="PATH")
    sp_rev.add_argument("--limit", type=int, default=None, metavar="N",
                        help="Maximum number of SHAs to return.")
    _add_common(sp_rev)

    # ── merge-base ────────────────────────────────────────────────────
    sp_mb = subparsers.add_parser("merge-base", help="Run git merge-base.")
    sp_mb.add_argument("ref_a", metavar="REF_A")
    sp_mb.add_argument("ref_b", metavar="REF_B")
    _add_common(sp_mb)

    # ── tag-l ─────────────────────────────────────────────────────────
    sp_tag = subparsers.add_parser("tag-l", help="Run git tag -l.")
    sp_tag.add_argument("--pattern", default=None, metavar="PATTERN",
                        help="Optional tag glob pattern.")
    _add_common(sp_tag)

    args = parser.parse_args()

    run_cli("gitarchaeology", _run, args, json_mode=args.json)


if __name__ == "__main__":
    main()
