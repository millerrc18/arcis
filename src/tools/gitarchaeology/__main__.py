"""GitArchaeology CLI entry point.

Purpose: Argparse front-end for the 7 read-only git ops. Forbidden mutating
         ops (commit / push / reset / rebase / checkout / branch -D /
         clean -f / cherry-pick / stash drop / tag -d) are structurally
         absent — they fail at argparse parse time with `invalid choice`.

Called by: operator (`python -m src.tools.gitarchaeology <op>`),
           git-historian agent (#108) via subprocess
Calls:     src.tools.gitarchaeology.core (all 7 ops),
           src.tools._cli_envelope (run_cli JSON envelope)
Owns tables: none
Config keys: none
Tests: tests/tools/test_gitarchaeology_integration.py (T7;
       including test_forbidden_op_argparse_rejected)

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
"""

from __future__ import annotations

import argparse
import json
import sys

from src.tools._cli_envelope import run_cli


def _dispatch_log(kw, _core):
    return _core.log(range=kw["range"], path=kw["path"], format=kw["format"],
                     limit=kw["limit"], repo=kw["repo"], max_output_bytes=kw["max_output_bytes"])


def _dispatch_blame(kw, _core):
    if kw["file"] is None:
        raise ValueError("blame requires <file> positional argument")
    return _core.blame(kw["file"], start_line=kw["start"], end_line=kw["end"],
                       repo=kw["repo"], max_output_bytes=kw["max_output_bytes"])


def _dispatch_show(kw, _core):
    if kw["sha"] is None:
        raise ValueError("show requires <sha> positional argument")
    return _core.show(kw["sha"], path=kw["path"], repo=kw["repo"],
                      max_output_bytes=kw["max_output_bytes"])


def _dispatch_diff(kw, _core):
    if kw["ref_a"] is None or kw["ref_b"] is None:
        raise ValueError("diff requires <ref_a> <ref_b> positional arguments")
    return _core.diff(kw["ref_a"], kw["ref_b"], path=kw["path"], repo=kw["repo"],
                      max_output_bytes=kw["max_output_bytes"])


def _dispatch_rev_list(kw, _core):
    if kw["range"] is None:
        raise ValueError("rev-list requires <range> positional argument")
    limit = kw["limit"] if kw["limit"] != 50 else None
    return _core.rev_list(kw["range"], path=kw["path"], limit=limit, repo=kw["repo"],
                          max_output_bytes=kw["max_output_bytes"])


def _dispatch_merge_base(kw, _core):
    if kw["ref_a"] is None or kw["ref_b"] is None:
        raise ValueError("merge-base requires <ref_a> <ref_b> positional arguments")
    return _core.merge_base(kw["ref_a"], kw["ref_b"], repo=kw["repo"])


def _dispatch_tag_l(kw, _core):
    return _core.tag_l(pattern=kw["pattern"], repo=kw["repo"])


_DISPATCH = {
    "log": _dispatch_log, "blame": _dispatch_blame, "show": _dispatch_show,
    "diff": _dispatch_diff, "rev-list": _dispatch_rev_list,
    "merge-base": _dispatch_merge_base, "tag-l": _dispatch_tag_l,
}


def _run(
    *,
    cmd: str,
    range: str | None = None,
    path: str | None = None,
    format: str = "%H%x09%an%x09%ai%x09%s",
    limit: int = 50,
    file: str | None = None,
    start: int | None = None,
    end: int | None = None,
    sha: str | None = None,
    ref_a: str | None = None,
    ref_b: str | None = None,
    pattern: str | None = None,
    repo: str | None = None,
    max_output_bytes: int | None = None,
    json: bool = False,
) -> str:
    """Dispatch to the correct core function based on args.cmd via _DISPATCH table."""
    import src.tools.gitarchaeology.core as _core

    handler = _DISPATCH.get(cmd)
    if handler is None:
        raise ValueError(f"unknown subcommand: {cmd!r}")
    result = handler(locals(), _core)
    return _json_or_text(result, as_json=json)


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


def _add_common(sp: argparse.ArgumentParser) -> None:
    sp.add_argument("--repo", default=None, metavar="DIR",
                    help="Run git as if started in DIR (-C <dir>).")
    sp.add_argument("--json", action="store_true", default=False,
                    help="Output JSON (errors also as JSON envelope).")
    sp.add_argument("--max-output-bytes", type=int, default=None, dest="max_output_bytes",
                    metavar="N", help="Override per-op output size cap (DA4).")


def _build_parsers(subparsers) -> None:
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

    sp_blame = subparsers.add_parser("blame", help="Run git blame.")
    sp_blame.add_argument("file", metavar="FILE", help="File to blame.")
    sp_blame.add_argument("--start", type=int, default=None, metavar="N",
                          help="Start line (1-based).")
    sp_blame.add_argument("--end", type=int, default=None, metavar="N",
                          help="End line (1-based, inclusive).")
    _add_common(sp_blame)

    sp_show = subparsers.add_parser("show", help="Run git show.")
    sp_show.add_argument("sha", metavar="SHA", help="Commit SHA to show.")
    sp_show.add_argument("--path", default=None, metavar="PATH",
                         help="Limit diff to PATH.")
    _add_common(sp_show)

    sp_diff = subparsers.add_parser("diff", help="Run git diff.")
    sp_diff.add_argument("ref_a", metavar="REF_A")
    sp_diff.add_argument("ref_b", metavar="REF_B")
    sp_diff.add_argument("--path", default=None, metavar="PATH",
                         help="Limit diff to PATH.")
    _add_common(sp_diff)

    sp_rev = subparsers.add_parser("rev-list", help="Run git rev-list.")
    sp_rev.add_argument("range", metavar="RANGE", help="Commit range.")
    sp_rev.add_argument("--path", default=None, metavar="PATH")
    sp_rev.add_argument("--limit", type=int, default=None, metavar="N",
                        help="Maximum number of SHAs to return.")
    _add_common(sp_rev)

    sp_mb = subparsers.add_parser("merge-base", help="Run git merge-base.")
    sp_mb.add_argument("ref_a", metavar="REF_A")
    sp_mb.add_argument("ref_b", metavar="REF_B")
    _add_common(sp_mb)

    sp_tag = subparsers.add_parser("tag-l", help="Run git tag -l.")
    sp_tag.add_argument("--pattern", default=None, metavar="PATTERN",
                        help="Optional tag glob pattern.")
    _add_common(sp_tag)


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="python -m src.tools.gitarchaeology",
        description="Read-only git CLI wrapper (7 ops). Mutating ops are not registered.",
    )
    subparsers = parser.add_subparsers(dest="cmd", metavar="cmd")
    subparsers.required = True
    _build_parsers(subparsers)
    args = parser.parse_args()
    run_cli("gitarchaeology", _run, args, json_mode=args.json)


if __name__ == "__main__":
    main()
