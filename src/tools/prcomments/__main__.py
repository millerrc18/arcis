"""CLI entry point for the PRComments tool — python -m src.tools.prcomments.

Usage:
    python -m src.tools.prcomments read <PR> [--repo OWNER/REPO] [--json]
    python -m src.tools.prcomments post <PR> [--body TEXT | --body-file PATH]
                                             [--repo OWNER/REPO] [--confirm] [--json]

External preconditions (FB6):
    gh >= 2.0 must be on PATH (required for --body-file - stdin pipe).
    Auth: run ``gh auth login`` if authentication is needed.
    Rate-limit errors are surfaced verbatim; no retry is performed.

Called by: operator agents, test subprocesses (pytest subprocess case k)
Calls: src.tools.prcomments.core.read, src.tools.prcomments.core.post,
       src.tools._cli_envelope.run_cli
Owns tables: none
Config keys: none
Tests: tests/tools/test_prcomments_integration.py (case k)
"""

from __future__ import annotations

import argparse
import json as json_mod
import sys
from pathlib import Path

from src.tools._cli_envelope import run_cli
from src.tools.prcomments.core import post, read
from src.tools._safety import DryRunResult


def _render_read(pr: int, comments) -> str:
    """Render list[PRComment] as markdown."""
    n = len(comments)
    lines = [f"# PR #{pr} Comments ({n})"]
    for c in comments:
        lines.append(f"\n## @{c.author} — {c.created_at}")
        lines.append(c.body)
    return "\n".join(lines)


def _render_post(result: dict) -> str:
    """Render post() result as markdown."""
    return f"# Posted to PR #{result['pr']}\nComment URL: {result['comment_url']}"


def _run_read(pr: int, *, repo: str | None, json: bool) -> str:
    """Execute read and return formatted output string."""
    comments = read(pr, repo=repo)
    if json:
        return json_mod.dumps([
            {"author": c.author, "body": c.body, "created_at": c.created_at, "url": c.url}
            for c in comments
        ])
    return _render_read(pr, comments)


def _run_post(pr: int, body: str, *, confirm: bool, repo: str | None, json: bool) -> str:
    """Execute post and return formatted output string."""
    result = post(pr, body, confirm=confirm, repo=repo)
    if isinstance(result, DryRunResult):
        return repr(result) if not json else json_mod.dumps(result.to_json())
    if json:
        return json_mod.dumps(result)
    return _render_post(result)


def _build_parser() -> argparse.ArgumentParser:
    """Construct and return the argument parser."""
    parser = argparse.ArgumentParser(
        prog="python -m src.tools.prcomments",
        description=(
            "Post or read GitHub PR comments via the gh CLI.\n\n"
            "External preconditions (FB6):\n"
            "  - gh >= 2.0 must be on PATH (for --body-file - stdin pipe).\n"
            "  - Auth: run 'gh auth login' if authentication is needed.\n"
            "  - Rate-limit errors are surfaced verbatim; no retry is performed."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subs = parser.add_subparsers(dest="verb", required=True)

    rp = subs.add_parser("read", help="Fetch all comments on a PR")
    rp.add_argument("pr", type=int, help="Pull request number")
    rp.add_argument("--repo", default=None, metavar="OWNER/REPO")
    rp.add_argument("--json", action="store_true", dest="json", help="Output JSON")

    pp = subs.add_parser("post", help="Post a comment on a PR")
    pp.add_argument("pr", type=int, help="Pull request number")
    body_group = pp.add_mutually_exclusive_group(required=True)
    body_group.add_argument("--body", default=None, metavar="TEXT")
    body_group.add_argument("--body-file", default=None, metavar="PATH")
    pp.add_argument("--repo", default=None, metavar="OWNER/REPO")
    pp.add_argument("--confirm", action="store_true")
    pp.add_argument("--json", action="store_true", dest="json", help="Output JSON")

    return parser


def main() -> None:
    args = _build_parser().parse_args()
    json_mode = args.json

    if args.verb == "read":
        run_cli(
            tool_name="prcomments",
            fn=lambda **kw: _run_read(kw["pr"], repo=kw.get("repo"), json=kw.get("json", False)),
            args_namespace=args,
            json_mode=json_mode,
        )
    else:
        body_text = args.body
        if body_text is None:
            body_file = args.body_file
            body_text = sys.stdin.read() if body_file == "-" else Path(body_file).read_text(encoding="utf-8")
        _body = body_text
        _confirm = args.confirm
        run_cli(
            tool_name="prcomments",
            fn=lambda **kw: _run_post(
                kw["pr"], _body, confirm=_confirm, repo=kw.get("repo"), json=kw.get("json", False),
            ),
            args_namespace=args,
            json_mode=json_mode,
        )


if __name__ == "__main__":
    main()
