"""PRComments core — post and read PR comments via gh CLI with secret-leak pre-flight.

External preconditions (FB6):
  - gh >= 2.0 required for ``--body-file -`` stdin pipe (DO NOT pre-flight;
    rely on gh's own "unknown flag" error message).
  - Auth: DO NOT call ``gh auth status`` proactively; surface auth errors verbatim.
  - Rate-limit: DO NOT retry or backoff; surface stderr verbatim.

Called by: src/tools/prcomments/__main__.py, operator agents, integration tests
Calls: src.tools._subprocess (resolve_exe, run, GhMissingError),
       src.tools._secrets (detect_secret_in_text),
       src.tools._execution_log (write_event)
Owns tables: none
Config keys: none
Tests: tests/tools/test_prcomments_integration.py
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from src.tools._execution_log import write_event
from src.tools._secrets import detect_secret_in_text
from src.tools._subprocess import GhMissingError, resolve_exe, run


# ── Error hierarchy ───────────────────────────────────────────────────────────


class PRCommentsError(RuntimeError):
    """Base class for prcomments tool errors."""


class PRCommentLeakError(PRCommentsError):
    """Raised by post() when the body contains a detectable secret pattern.

    Constructor takes the redacted_preview string so callers can surface
    the (already-redacted) preview without re-exposing the raw secret.
    """

    def __init__(self, redacted_preview: str) -> None:
        super().__init__(
            f"Secret detected in PR comment body — blocked before gh was invoked. "
            f"Redacted preview: {redacted_preview[:200]}"
        )
        self.redacted_preview = redacted_preview


class GhCommandFailedError(PRCommentsError):
    """Raised when gh exits non-zero.

    Attributes:
        returncode: gh process exit code
        stderr:     raw stderr text (stripped)
        hint:       optional actionable string appended to str(exc) when set
    """

    def __init__(self, returncode: int, stderr: str, *, hint: Optional[str] = None) -> None:
        msg = f"gh exited {returncode}: {stderr}"
        if hint:
            msg += f" | Hint: {hint}"
        super().__init__(msg)
        self.returncode = returncode
        self.stderr = stderr
        self.hint = hint


class GhJsonParseError(PRCommentsError):
    """Raised when gh stdout is not valid JSON on the read path."""


# Re-export GhMissingError so callers can import it from this module.
__all__ = [
    "PRCommentsError",
    "PRCommentLeakError",
    "GhCommandFailedError",
    "GhJsonParseError",
    "GhMissingError",
    "PRComment",
    "read",
    "post",
    "_read_impl",
    "_post_impl",
]


# ── Data model ────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class PRComment:
    """A single comment on a GitHub pull request.

    Fields map directly to the gh pr view --json comments output:
        author     ← c['author']['login']
        body       ← c['body']
        created_at ← c['createdAt']
        url        ← c['url']
    """

    author: str
    body: str
    created_at: str
    url: str


# ── Raw implementations (undecorated — tests inject log_path via factory) ─────


def _read_impl(pr: int, *, repo: Optional[str] = None) -> list[PRComment]:
    """Fetch comments for PR `pr` and return list[PRComment].

    Calls ``gh pr view <pr> --json comments [-R <repo>]``.
    Raises GhMissingError, GhCommandFailedError, or GhJsonParseError on failure.
    """
    cmd = [resolve_exe("gh"), "pr", "view", str(pr), "--json", "comments"]
    if repo:
        cmd.extend(["-R", repo])

    result = run(cmd, timeout=30)

    if result.returncode != 0:
        hint = None
        if "auth" in result.stderr.lower():
            hint = "Run `gh auth status` then `gh auth login` if needed."
        raise GhCommandFailedError(
            returncode=result.returncode,
            stderr=result.stderr.strip(),
            hint=hint,
        )

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise GhJsonParseError(f"gh stdout not valid JSON: {exc}") from exc

    return [
        PRComment(
            author=c["author"]["login"],
            body=c["body"],
            created_at=c["createdAt"],
            url=c["url"],
        )
        for c in data.get("comments", [])
    ]


def _post_impl(
    pr: int,
    body: str,
    *,
    repo: Optional[str] = None,
    log_path: Optional[Path] = None,
) -> dict:
    """Post `body` as a comment on PR `pr`.

    PRE-FLIGHT: secret scan BEFORE invoking gh (spec §5 — 2-row audit pattern):
      1. detect_secret_in_text(body) → if leak, write secret_leak_block row FIRST,
         then raise PRCommentLeakError (safe_op will write the 'error' row second).
      2. If clean, call gh with ``--body-file -`` and pipe body via stdin (DD-14).

    Returns {'pr': pr, 'comment_url': <url>} on success.
    Raises PRCommentLeakError, GhMissingError, or GhCommandFailedError.
    """
    # PRE-FLIGHT secret scan — MUST happen before gh is ever invoked.
    is_leak, redacted_preview, kind = detect_secret_in_text(body)
    if is_leak:
        # Write the dedicated secret_leak_block row FIRST.
        # @safe_op (the outer decorator in the factory) will write 'error' on
        # PRCommentLeakError — this produces the 2-row audit pattern (spec §5).
        write_event(
            log_path=log_path,
            tool_name="prcomments",
            params={"pr": pr, "body_redacted": redacted_preview[:500], "kind": kind},
            result="secret_leak_block",
            duration_ms=0,
        )
        raise PRCommentLeakError(redacted_preview)

    # Clean body — invoke gh with stdin pipe (DD-14: never --body STRING).
    cmd = [resolve_exe("gh"), "pr", "comment", str(pr), "--body-file", "-"]
    if repo:
        cmd.extend(["-R", repo])

    result = run(cmd, timeout=30, input_data=body)

    if result.returncode != 0:
        hint = None
        stderr_lower = result.stderr.lower()
        if "auth" in stderr_lower or "authentication required" in stderr_lower:
            hint = "Run `gh auth status` then `gh auth login` if needed."
        raise GhCommandFailedError(
            returncode=result.returncode,
            stderr=result.stderr.strip(),
            hint=hint,
        )

    comment_url = result.stdout.strip()
    return {"pr": pr, "comment_url": comment_url}


# ── Public API (decorated) ────────────────────────────────────────────────────
# Note: These decorated versions use the DEFAULT_LOG_PATH (data/logs/).
# Tests use _build_read/_build_post factories to inject tmp_path log_path.

from src.tools._safety import safe_op  # noqa: E402 (after error defs for clarity)


@safe_op(name="prcomments", mutates=False)
def read(pr: int, *, repo: Optional[str] = None) -> list[PRComment]:
    """Return all comments on GitHub PR `pr` as a list of PRComment objects.

    Args:
        pr:   Pull request number.
        repo: Optional OWNER/REPO string (e.g. 'millerrc18/halcyon-lab').
              Defaults to the repo inferred from the current git remote by gh.

    Raises:
        GhMissingError:       gh not on PATH (>= 2.0 required).
        GhCommandFailedError: gh exited non-zero (e.g. auth failure, no such PR).
        GhJsonParseError:     gh stdout not parseable as JSON.

    External preconditions (FB6):
        gh >= 2.0 must be on PATH. Auth must be configured via ``gh auth login``.
        Rate-limit errors are surfaced verbatim; no retry is performed.
    """
    return _read_impl(pr, repo=repo)


@safe_op(name="prcomments", mutates=True)
def post(pr: int, body: str, *, confirm: bool = False, repo: Optional[str] = None) -> dict:
    """Post `body` as a comment on GitHub PR `pr`.

    Secret pre-flight: body is scanned for known credential patterns before gh
    is invoked. Any detected secret raises PRCommentLeakError and writes a
    'secret_leak_block' audit event (plus 'error' from safe_op — 2-row pattern).

    Args:
        pr:      Pull request number.
        body:    Comment text. MUST NOT contain secrets (scanned by detect_secret_in_text).
        confirm: Must be True to execute mutation (safe_op dry-run gate).
        repo:    Optional OWNER/REPO string.

    Returns:
        {'pr': pr, 'comment_url': '<gh comment URL>'}

    Raises:
        PRCommentLeakError:   Secret detected in body — gh was NOT invoked.
        GhMissingError:       gh not on PATH (>= 2.0 required).
        GhCommandFailedError: gh exited non-zero.

    External preconditions (FB6):
        gh >= 2.0 must be on PATH (for --body-file - stdin support).
        Auth must be configured via ``gh auth login``.
        Rate-limit errors are surfaced verbatim; no retry is performed.
    """
    return _post_impl(pr, body, repo=repo)
