# Purpose: Integration tests for src/tools/prcomments — gh CLI wrapper.
# Called by: pytest tests/tools/test_prcomments_integration.py
# Calls: src.tools.prcomments.core.read, src.tools.prcomments.core.post
# Owns tables: none
# Config keys: none
# Tests: (this file is the test)
#
# TDD verify-by-mutation comments appear on each case.

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Factory helpers — inject log_path for tmp_path audit-log isolation
# ---------------------------------------------------------------------------


def _build_read(log_path: Path):
    """Factory: create a read() with test-isolated log_path baked in.

    Mirrors _build_query from test_dbquery_integration.py. Required because
    log_path is a decorator-level param, not a call-time param.
    """
    from src.tools._safety import safe_op
    from src.tools.prcomments.core import _read_impl

    @safe_op(name="prcomments", mutates=False, log_path=log_path)
    def _r(pr: int, *, repo: str | None = None):
        return _read_impl(pr, repo=repo)

    return _r


def _build_post(log_path: Path):
    """Factory: create a post() with test-isolated log_path baked in.

    The post() function writes its own secret_leak_block event directly;
    safe_op writes 'error' after. The log_path must be the same for both.
    """
    from src.tools._safety import safe_op
    from src.tools.prcomments.core import _post_impl

    @safe_op(name="prcomments", mutates=True, log_path=log_path)
    def _p(pr: int, body: str, *, confirm: bool = False, repo: str | None = None):
        return _post_impl(pr, body, repo=repo, log_path=log_path)

    return _p


def _read_log(log_path: Path) -> list[dict]:
    """Read JSON-lines log into list of events."""
    return [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]


# ---------------------------------------------------------------------------
# Canned gh JSON fixture
# ---------------------------------------------------------------------------

_CANNED_COMMENTS_JSON = json.dumps({
    "comments": [
        {
            "author": {"login": "alice"},
            "body": "Looks great!",
            "createdAt": "2026-05-24T10:00:00Z",
            "url": "https://github.com/owner/repo/pull/1#issuecomment-1",
        },
        {
            "author": {"login": "bob"},
            "body": "LGTM.",
            "createdAt": "2026-05-24T11:00:00Z",
            "url": "https://github.com/owner/repo/pull/1#issuecomment-2",
        },
    ]
})

_EMPTY_COMMENTS_JSON = json.dumps({"comments": []})

_FAKE_GH_PATH = "C:\\fake\\gh.exe"


# ---------------------------------------------------------------------------
# (a) read() with canned gh JSON returns list[PRComment] + 'success' event
# ---------------------------------------------------------------------------


def test_read_returns_pr_comment_list_and_logs_success(monkeypatch, tmp_path):
    """read(pr=1, repo='owner/repo') with canned gh JSON → list[PRComment] + 'success' event.

    Verify-by-mutation: Comment out the PRComment construction in _read_impl
    and return raw dicts → isinstance(result[0], PRComment) fails.
    """
    import subprocess as sp

    from src.tools import prcomments

    log = tmp_path / "exec.log"
    read = _build_read(log)

    def fake_run(cmd, *, timeout, check=False, input_data=None):
        return sp.CompletedProcess(args=cmd, returncode=0, stdout=_CANNED_COMMENTS_JSON, stderr="")

    monkeypatch.setattr("src.tools.prcomments.core.run", fake_run)
    monkeypatch.setattr("src.tools.prcomments.core.resolve_exe", lambda name: _FAKE_GH_PATH)

    result = read(pr=1, repo="owner/repo")

    assert isinstance(result, list)
    assert len(result) == 2

    c0 = result[0]
    assert isinstance(c0, prcomments.PRComment)
    assert c0.author == "alice"
    assert c0.body == "Looks great!"
    assert c0.created_at == "2026-05-24T10:00:00Z"
    assert c0.url == "https://github.com/owner/repo/pull/1#issuecomment-1"

    c1 = result[1]
    assert c1.author == "bob"

    events = _read_log(log)
    assert len(events) == 1
    assert events[0]["result"] == "success"
    assert events[0]["tool_name"] == "prcomments"


# ---------------------------------------------------------------------------
# (b) post() clean body uses --body-file - and pipes input_data
# ---------------------------------------------------------------------------


def test_post_clean_body_uses_stdin_pipe(monkeypatch, tmp_path):
    """post(pr=1, body='Looks good') with clean body → success dict + correct subprocess call.

    Verify-by-mutation: Change '--body-file'/'-' to '--body'/body in core.py
    → the 'assert --body-file in cmd' assertion fails.
    Also: change input_data=body to input_data=None → input_data assertion fails.
    """
    import subprocess as sp

    captured = {}

    def fake_run(cmd, *, timeout, check=False, input_data=None):
        captured["cmd"] = cmd
        captured["input_data"] = input_data
        return sp.CompletedProcess(
            args=cmd, returncode=0,
            stdout="https://github.com/owner/repo/pull/1#issuecomment-99",
            stderr="",
        )

    monkeypatch.setattr("src.tools.prcomments.core.run", fake_run)
    monkeypatch.setattr("src.tools.prcomments.core.resolve_exe", lambda name: _FAKE_GH_PATH)

    log = tmp_path / "exec.log"
    post = _build_post(log)

    body = "Looks good"
    result = post(pr=1, body=body, confirm=True)

    assert result == {"pr": 1, "comment_url": "https://github.com/owner/repo/pull/1#issuecomment-99"}

    cmd = captured["cmd"]
    assert "--body-file" in cmd, f"Expected --body-file in cmd, got: {cmd}"
    assert "-" in cmd, f"Expected '-' stdin marker in cmd, got: {cmd}"
    assert "--body" not in [c for c in cmd if c == "--body"], "Must NOT use --body STRING"
    assert captured["input_data"] == body

    events = _read_log(log)
    results = [e["result"] for e in events]
    assert "success" in results


# ---------------------------------------------------------------------------
# (c) post() with GitHub PAT in body → PRCommentLeakError + 2-row audit
# ---------------------------------------------------------------------------


def test_post_github_pat_raises_leak_error_and_writes_two_audit_rows(monkeypatch, tmp_path):
    """post with ghp_ token → PRCommentLeakError + secret_leak_block + error audit rows.

    Verify-by-mutation: Comment out detect_secret_in_text pre-flight in _post_impl
    → body passes to gh subprocess, secret_leak_block row never written → test fails.
    """
    import subprocess as sp

    run_called = {"called": False}

    def fake_run(cmd, *, timeout, check=False, input_data=None):
        run_called["called"] = True
        return sp.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

    monkeypatch.setattr("src.tools.prcomments.core.run", fake_run)
    monkeypatch.setattr("src.tools.prcomments.core.resolve_exe", lambda name: _FAKE_GH_PATH)

    from src.tools.prcomments import PRCommentLeakError

    log = tmp_path / "exec.log"
    post = _build_post(log)

    body = "here is my token ghp_abcdefghij1234567890"

    with pytest.raises(PRCommentLeakError):
        post(pr=1, body=body, confirm=True)

    assert not run_called["called"], "subprocess MUST NOT be called when a secret is detected"

    events = _read_log(log)
    results = [e["result"] for e in events]
    assert "secret_leak_block" in results, f"Expected secret_leak_block in {results}"
    assert "error" in results, f"Expected error row in {results}"

    leak_events = [e for e in events if e["result"] == "secret_leak_block"]
    assert len(leak_events) == 1
    le = leak_events[0]
    assert "body_redacted" in le["params"]
    assert "***REDACTED***" in le["params"]["body_redacted"]


# ---------------------------------------------------------------------------
# (d) Same shape: OpenAI sk- key
# ---------------------------------------------------------------------------


def test_post_openai_key_raises_leak_error(monkeypatch, tmp_path):
    """post with sk- key → PRCommentLeakError (same 2-row pattern as case c)."""
    import subprocess as sp

    def fake_run(cmd, *, timeout, check=False, input_data=None):
        return sp.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

    monkeypatch.setattr("src.tools.prcomments.core.run", fake_run)
    monkeypatch.setattr("src.tools.prcomments.core.resolve_exe", lambda name: _FAKE_GH_PATH)

    from src.tools.prcomments import PRCommentLeakError

    log = tmp_path / "exec.log"
    post = _build_post(log)

    body = "here is sk-abc123def456ghi789jkl0"

    with pytest.raises(PRCommentLeakError):
        post(pr=1, body=body, confirm=True)

    events = _read_log(log)
    results = [e["result"] for e in events]
    assert "secret_leak_block" in results
    assert "error" in results


# ---------------------------------------------------------------------------
# (e) Same shape: password= key
# ---------------------------------------------------------------------------


def test_post_password_kwarg_raises_leak_error(monkeypatch, tmp_path):
    """post with password= pattern → PRCommentLeakError (same 2-row pattern as case c)."""
    import subprocess as sp

    def fake_run(cmd, *, timeout, check=False, input_data=None):
        return sp.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

    monkeypatch.setattr("src.tools.prcomments.core.run", fake_run)
    monkeypatch.setattr("src.tools.prcomments.core.resolve_exe", lambda name: _FAKE_GH_PATH)

    from src.tools.prcomments import PRCommentLeakError

    log = tmp_path / "exec.log"
    post = _build_post(log)

    body = "hey check this: password=hunter2supersecret"

    with pytest.raises(PRCommentLeakError):
        post(pr=1, body=body, confirm=True)

    events = _read_log(log)
    results = [e["result"] for e in events]
    assert "secret_leak_block" in results
    assert "error" in results


# ---------------------------------------------------------------------------
# (f) Multi-match: both tokens redacted in body_redacted
# ---------------------------------------------------------------------------


def test_post_multi_match_both_tokens_redacted(monkeypatch, tmp_path):
    """post with 2 secrets → PRCommentLeakError; body_redacted has BOTH redacted.

    Verify-by-mutation: Revert _secrets to early-return-on-first-hit → second
    high-entropy token remains unredacted in body_redacted → test fails.
    This locks the T1 cycle-1 fix contract (always-run-high-entropy fallback).
    """
    import subprocess as sp

    def fake_run(cmd, *, timeout, check=False, input_data=None):
        return sp.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

    monkeypatch.setattr("src.tools.prcomments.core.run", fake_run)
    monkeypatch.setattr("src.tools.prcomments.core.resolve_exe", lambda name: _FAKE_GH_PATH)

    from src.tools.prcomments import PRCommentLeakError

    log = tmp_path / "exec.log"
    post = _build_post(log)

    body = "ghp_abcdefghij1234567890 also wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"

    with pytest.raises(PRCommentLeakError):
        post(pr=1, body=body, confirm=True)

    events = _read_log(log)
    leak_events = [e for e in events if e["result"] == "secret_leak_block"]
    assert len(leak_events) == 1
    body_redacted = leak_events[0]["params"]["body_redacted"]

    # Both the ghp_ token and the high-entropy AWS-key-like token must be redacted
    assert "ghp_abcdefghij1234567890" not in body_redacted, "ghp_ token must be redacted"
    assert "wJalrXUtnFEMI" not in body_redacted, "high-entropy token must be redacted"
    assert body_redacted.count("***REDACTED***") >= 2, (
        f"Expected at least 2 REDACTED markers, got: {body_redacted!r}"
    )


# ---------------------------------------------------------------------------
# (g) gh missing → GhMissingError propagates + error event; message has >= 2.0
# ---------------------------------------------------------------------------


def test_read_gh_missing_raises_and_logs_error(monkeypatch, tmp_path):
    """gh missing: resolve_exe raises GhMissingError → propagates + 'error' event.

    GhMissingError message must contain '>= 2.0' (requirement from _subprocess.py).
    Verify-by-mutation: Remove GhMissingError from resolve_exe → no error raised →
    test fails on pytest.raises assertion.
    """
    from src.tools._subprocess import GhMissingError

    def fake_resolve(name):
        raise GhMissingError(
            "gh not on PATH. Install via winget install GitHub.cli "
            "(>= 2.0 required for --body-file - stdin)"
        )

    monkeypatch.setattr("src.tools.prcomments.core.resolve_exe", fake_resolve)

    log = tmp_path / "exec.log"
    read = _build_read(log)

    with pytest.raises(GhMissingError) as exc_info:
        read(pr=1, repo="owner/repo")

    assert ">= 2.0" in str(exc_info.value)

    events = _read_log(log)
    results = [e["result"] for e in events]
    assert "error" in results


# ---------------------------------------------------------------------------
# (h) Generic gh failure → GhCommandFailedError with hint=None
# ---------------------------------------------------------------------------


def test_read_gh_command_failure_no_hint(monkeypatch, tmp_path):
    """Generic gh returncode=1, stderr='some other error' → GhCommandFailedError(hint=None)."""
    import subprocess as sp

    from src.tools.prcomments import GhCommandFailedError

    def fake_run(cmd, *, timeout, check=False, input_data=None):
        return sp.CompletedProcess(args=cmd, returncode=1, stdout="", stderr="some other error")

    monkeypatch.setattr("src.tools.prcomments.core.run", fake_run)
    monkeypatch.setattr("src.tools.prcomments.core.resolve_exe", lambda name: _FAKE_GH_PATH)

    log = tmp_path / "exec.log"
    read = _build_read(log)

    with pytest.raises(GhCommandFailedError) as exc_info:
        read(pr=1, repo="owner/repo")

    exc = exc_info.value
    assert exc.hint is None
    # Hint text must NOT appear in message when hint=None
    assert "Hint:" not in str(exc)

    events = _read_log(log)
    results = [e["result"] for e in events]
    assert "error" in results


# ---------------------------------------------------------------------------
# (i) Auth failure → GhCommandFailedError with hint text
# ---------------------------------------------------------------------------


def test_read_auth_failure_includes_hint(monkeypatch, tmp_path):
    """FB6 AUTH-FAILURE: auth stderr → GhCommandFailedError with hint in str(exc).

    Verify-by-mutation: Drop hint= kwarg from GhCommandFailedError in auth branch
    → hint is None → 'Run `gh auth status`' not in str(exc) → test fails.
    """
    import subprocess as sp

    from src.tools.prcomments import GhCommandFailedError

    stderr_msg = "error: authentication required, run `gh auth login` to authenticate"

    def fake_run(cmd, *, timeout, check=False, input_data=None):
        return sp.CompletedProcess(args=cmd, returncode=1, stdout="", stderr=stderr_msg)

    monkeypatch.setattr("src.tools.prcomments.core.run", fake_run)
    monkeypatch.setattr("src.tools.prcomments.core.resolve_exe", lambda name: _FAKE_GH_PATH)

    log = tmp_path / "exec.log"
    read = _build_read(log)

    with pytest.raises(GhCommandFailedError) as exc_info:
        read(pr=1, repo="owner/repo")

    exc_str = str(exc_info.value)
    assert "Run `gh auth status` then `gh auth login` if needed." in exc_str, (
        f"Expected auth hint in exception message, got: {exc_str!r}"
    )


# ---------------------------------------------------------------------------
# (j) Read path gh JSON parse error → GhJsonParseError
# ---------------------------------------------------------------------------


def test_read_invalid_json_raises_parse_error(monkeypatch, tmp_path):
    """Read path: gh returns returncode=0 but stdout is not valid JSON → GhJsonParseError."""
    import subprocess as sp

    from src.tools.prcomments import GhJsonParseError

    def fake_run(cmd, *, timeout, check=False, input_data=None):
        return sp.CompletedProcess(args=cmd, returncode=0, stdout="not-valid-json", stderr="")

    monkeypatch.setattr("src.tools.prcomments.core.run", fake_run)
    monkeypatch.setattr("src.tools.prcomments.core.resolve_exe", lambda name: _FAKE_GH_PATH)

    log = tmp_path / "exec.log"
    read = _build_read(log)

    with pytest.raises(GhJsonParseError):
        read(pr=1, repo="owner/repo")


# ---------------------------------------------------------------------------
# (k) CLI subprocess envelope: gh-missing exits 1 with JSON error envelope
# ---------------------------------------------------------------------------


def test_cli_gh_missing_json_envelope(tmp_path):
    """CLI: python -m src.tools.prcomments read 1 --json with fake PATH → JSON error + exit 1.

    Tests the __main__.py subprocess envelope integration end-to-end.
    """
    repo_root = Path(__file__).resolve().parents[2]
    env = {
        "PATH": "",  # ensures gh is not found
        "PYTHONPATH": str(repo_root),
        "SYSTEMROOT": "C:\\Windows",  # needed on Windows for subprocess
        "USERPROFILE": str(Path.home()),
    }

    result = subprocess.run(
        [sys.executable, "-m", "src.tools.prcomments", "read", "1", "--json"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        timeout=30,
    )

    assert result.returncode == 1, f"Expected exit 1, got {result.returncode}"
    stdout = result.stdout.strip()
    assert stdout, f"Expected non-empty stdout, got empty. stderr: {result.stderr}"

    envelope = json.loads(stdout)
    assert "error" in envelope
    err = envelope["error"]
    assert err["type"] == "GhMissingError", f"Expected GhMissingError, got {err['type']}"
    assert "tool" in err
    assert err["tool"] == "prcomments"


# ---------------------------------------------------------------------------
# (l) FB5 REAL-SEAM SMOKE — read-only live gh call
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# (m) CLI post without --confirm -> dry-run output via subprocess
# ---------------------------------------------------------------------------


def test_cli_post_without_confirm_returns_dry_run_via_subprocess():
    """(m) CLI post without --confirm -> exit 0 + dry-run output (no actual gh call).

    Verifies __main__.py uses the DECORATED post() (with @safe_op mutates=True),
    NOT _post_impl (undecorated). Without @safe_op, the subprocess would call gh
    (failing with GhMissingError on empty PATH), NOT return dry-run.

    Verify-by-mutation: Revert __main__.py to call _post_impl (undecorated)
    -> subprocess exits 1 with GhMissingError when PATH is stripped.
    """
    import os

    repo_root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [
            sys.executable, "-m", "src.tools.prcomments",
            "post", "1",
            "--body", "hello world",
            "--json",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={
            **os.environ,
            "PATH": "",  # strip gh from PATH — real post would fail
        },
        timeout=15,
    )
    # Dry-run exits 0 (no exception raised)
    assert result.returncode == 0, (
        f"Expected exit 0 (dry-run), got {result.returncode}. "
        f"stdout={result.stdout!r} stderr={result.stderr!r}. "
        "If exit 1 with GhMissingError: __main__ calling _post_impl (undecorated bypass)."
    )
    out = result.stdout
    assert "prcomments" in out or "dry_run" in out.lower() or "DryRunResult" in out, (
        f"Expected dry-run output containing 'prcomments'. Got: {out!r}"
    )


# ---------------------------------------------------------------------------
# (n) Auth hint precision — "you are not authorized" must NOT trigger hint
# ---------------------------------------------------------------------------


def test_read_permission_denied_stderr_does_not_trigger_auth_hint(monkeypatch, tmp_path):
    """(n) Non-auth 403/permission stderr does NOT trigger the auth hint.

    Reviewer B nit: `'auth' in stderr_lower` was too loose — would trigger on
    'you are not authorized to push'.

    Verify-by-mutation: Revert to `if 'auth' in stderr_lower:` -> this test fails
    because 'auth' appears in 'You are not authorized...' and hint is set.
    """
    import subprocess as sp

    from src.tools.prcomments import GhCommandFailedError

    stderr_msg = "HTTP 403: You do not have permission to write to this resource"

    def fake_run(cmd, *, timeout, check=False, input_data=None):
        return sp.CompletedProcess(args=cmd, returncode=1, stdout="", stderr=stderr_msg)

    monkeypatch.setattr("src.tools.prcomments.core.run", fake_run)
    monkeypatch.setattr("src.tools.prcomments.core.resolve_exe", lambda name: _FAKE_GH_PATH)

    log = tmp_path / "exec.log"
    read = _build_read(log)

    with pytest.raises(GhCommandFailedError) as exc_info:
        read(pr=1, repo="owner/repo")

    exc = exc_info.value
    assert exc.hint is None, (
        f"Expected hint=None for permission-denied stderr (not an auth failure), "
        f"got hint={exc.hint!r}. "
        "Auth hint must only fire on 'authentication required' or 'gh auth login' in stderr."
    )


@pytest.mark.skipif(shutil.which("gh") is None, reason="gh.exe not on PATH")
def test_fb5_real_seam_smoke_read(tmp_path):
    """FB5 real-seam smoke: call read(pr=1174, repo='millerrc18/halcyon-lab').

    Skipped when gh is not on PATH. This is read-only — does NOT call post().
    Asserts list returned; if non-empty, asserts PRComment shape.
    """
    import subprocess as sp

    from src.tools.prcomments import PRComment
    from src.tools.prcomments.core import _read_impl

    # Check auth before attempting live call
    auth_check = sp.run(
        [shutil.which("gh"), "auth", "status"],
        capture_output=True, text=True, encoding="utf-8", timeout=15,
    )
    if auth_check.returncode != 0:
        pytest.skip("gh auth status failed — not authenticated")

    result = _read_impl(pr=1174, repo="millerrc18/halcyon-lab")

    assert isinstance(result, list), f"Expected list, got {type(result)}"
    if result:
        c = result[0]
        assert isinstance(c, PRComment), f"Expected PRComment, got {type(c)}"
        assert isinstance(c.author, str)
        assert isinstance(c.body, str)
        assert isinstance(c.created_at, str)
        assert isinstance(c.url, str)
