# Purpose: Integration tests for src/tools/gitarchaeology — 7 read-only git ops.
# Called by: pytest tests/tools/test_gitarchaeology_integration.py
# Calls: src.tools.gitarchaeology.core (log, blame, show, diff, rev_list, merge_base, tag_l)
#        src.tools._subprocess (mocked)
# Owns tables: none
# Config keys: none
# Tests: (this file is the test)

"""Integration tests for GitArchaeology (T7).

Coverage: 7 read-only ops + DA3 parsing-contract + DA4 size-governance
+ forbidden-op argparse rejection + CLI JSON envelope.

Anti-vacuous notes:
  - DA3 embedded-tab test fails if maxsplit is removed from log().
  - DA4 truncation tests fail if the size check is removed from _git().
  - Forbidden-op test fails if 'commit' is registered as a subparser.
"""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from src.tools.gitarchaeology.core import (
    GitArgError,
    GitInvocationError,
    GitOutputTruncatedError,
    GitParseError,
    blame,
    diff,
    log,
    merge_base,
    rev_list,
    show,
    tag_l,
)
from src.tools._subprocess import GitMissingError


# ─── helpers ──────────────────────────────────────────────────────────────────

def _completed(stdout: str = "", stderr: str = "", returncode: int = 0):
    """Build a fake CompletedProcess."""
    r = MagicMock()
    r.stdout = stdout
    r.stderr = stderr
    r.returncode = returncode
    return r


def _mock_run(stdout: str = "", stderr: str = "", returncode: int = 0):
    """Return a patch target that yields _completed(...)."""
    return patch(
        "src.tools.gitarchaeology.core._subprocess_run",
        return_value=_completed(stdout, stderr, returncode),
    )


# ─── 1. log_basic ─────────────────────────────────────────────────────────────

def test_log_basic():
    """log() returns list-of-dicts from mocked stdout."""
    fake_out = "abc123\tAlice\t2026-05-25 10:00:00 +0000\tfix: broken widget"
    with _mock_run(stdout=fake_out):
        result = log()
    assert isinstance(result, list)
    assert len(result) == 1
    row = result[0]
    assert row["sha"] == "abc123"
    assert row["author"] == "Alice"
    assert row["subject"] == "fix: broken widget"


# ─── 2. log_path_filter ───────────────────────────────────────────────────────

def test_log_path_filter():
    """log(path=...) places '-- <path>' in argv."""
    fake_out = "deadbeef\tBob\t2026-05-25 11:00:00 +0000\tchore: update readme"
    captured_args = []

    def _capture(args, **kwargs):
        captured_args.extend(args)
        return _completed(stdout=fake_out)

    with patch("src.tools.gitarchaeology.core._subprocess_run", side_effect=_capture):
        result = log(path="src/tools/gitarchaeology/core.py")

    assert "--" in captured_args
    idx = captured_args.index("--")
    assert captured_args[idx + 1] == "src/tools/gitarchaeology/core.py"
    assert len(result) == 1


# ─── 3. log_range ─────────────────────────────────────────────────────────────

def test_log_range():
    """log(range='HEAD~5..HEAD') includes range in argv."""
    fake_out = "aaa\tCarol\t2026-05-25 12:00:00 +0000\tfeat: new thing"
    captured_args = []

    def _capture(args, **kwargs):
        captured_args.extend(args)
        return _completed(stdout=fake_out)

    with patch("src.tools.gitarchaeology.core._subprocess_run", side_effect=_capture):
        result = log(range="HEAD~5..HEAD")

    assert "HEAD~5..HEAD" in captured_args
    assert len(result) == 1


# ─── 4. log_limit ─────────────────────────────────────────────────────────────

def test_log_limit():
    """Default limit is 50; can be overridden."""
    captured_args_default = []
    captured_args_override = []

    def _capture_default(args, **kwargs):
        captured_args_default.extend(args)
        return _completed(stdout="")

    def _capture_override(args, **kwargs):
        captured_args_override.extend(args)
        return _completed(stdout="")

    with patch("src.tools.gitarchaeology.core._subprocess_run", side_effect=_capture_default):
        log()
    with patch("src.tools.gitarchaeology.core._subprocess_run", side_effect=_capture_override):
        log(limit=10)

    assert "-n" in captured_args_default
    idx = captured_args_default.index("-n")
    assert captured_args_default[idx + 1] == "50"

    idx2 = captured_args_override.index("-n")
    assert captured_args_override[idx2 + 1] == "10"


# ─── 5. blame_full_file ───────────────────────────────────────────────────────

def test_blame_full_file(tmp_path):
    """blame() on a small file returns list-of-dicts."""
    small_file = tmp_path / "small.py"
    # 5 lines — well under the 5000-line gate
    small_file.write_text("line1\nline2\nline3\nline4\nline5\n", encoding="utf-8")

    fake_blame_out = (
        "abc1234 (Alice 2026-05-25 10:00:00 +0000 1) line1\n"
        "abc1234 (Alice 2026-05-25 10:00:00 +0000 2) line2\n"
    )
    with _mock_run(stdout=fake_blame_out):
        result = blame(file=str(small_file))
    assert isinstance(result, list)
    assert len(result) == 2


# ─── 6. blame_range ───────────────────────────────────────────────────────────

def test_blame_range(tmp_path):
    """blame(start_line=10, end_line=20) includes '-L 10,20' in argv."""
    small_file = tmp_path / "src.py"
    small_file.write_text("\n".join(f"line{i}" for i in range(1, 30)) + "\n", encoding="utf-8")

    captured_args = []

    def _capture(args, **kwargs):
        captured_args.extend(args)
        return _completed(stdout="abc1234 (Bob 2026-05-25 10:00:00 +0000 10) content\n")

    with patch("src.tools.gitarchaeology.core._subprocess_run", side_effect=_capture):
        result = blame(file=str(small_file), start_line=10, end_line=20)

    assert "-L" in captured_args
    idx = captured_args.index("-L")
    assert captured_args[idx + 1] == "10,20"
    assert isinstance(result, list)


# ─── 7. blame_invalid_range ───────────────────────────────────────────────────

def test_blame_invalid_range(tmp_path):
    """blame(start_line=20, end_line=10) raises GitArgError before subprocess."""
    f = tmp_path / "code.py"
    f.write_text("x\n" * 50, encoding="utf-8")

    with patch("src.tools.gitarchaeology.core._subprocess_run") as mock_run:
        with pytest.raises(GitArgError, match="start_line"):
            blame(file=str(f), start_line=20, end_line=10)
        mock_run.assert_not_called()


# ─── 8. show ─────────────────────────────────────────────────────────────────

def test_show():
    """show() parses subject + body + diff from mocked stdout."""
    fake_out = textwrap.dedent("""\
        commit deadbeefdeadbeefdeadbeefdeadbeefdeadbeef
        Author: Alice <alice@example.com>
        Date:   Mon May 25 10:00:00 2026 +0000

            fix: do the thing

            Body text goes here.

        diff --git a/src/tools/foo.py b/src/tools/foo.py
        index 1234567..abcdefg 100644
        --- a/src/tools/foo.py
        +++ b/src/tools/foo.py
        @@ -1,1 +1,1 @@
        -old
        +new
    """)
    with _mock_run(stdout=fake_out):
        result = show(sha="deadbeef")

    assert result["subject"] == "fix: do the thing"
    assert "Body text" in result["body"]
    assert "diff --git" in result["diff"]


# ─── 9. diff ─────────────────────────────────────────────────────────────────

def test_diff():
    """diff(ref_a, ref_b) includes 'ref_a..ref_b' in argv; returns str."""
    captured_args = []

    def _capture(args, **kwargs):
        captured_args.extend(args)
        return _completed(stdout="diff --git a/foo b/foo\n+new line\n")

    with patch("src.tools.gitarchaeology.core._subprocess_run", side_effect=_capture):
        result = diff("abc123", "def456")

    assert "abc123..def456" in captured_args
    assert isinstance(result, str)
    assert "diff --git" in result


# ─── 10. rev_list ────────────────────────────────────────────────────────────

def test_rev_list():
    """rev_list() returns list of sha dicts."""
    fake_out = "aaa111\nbbb222\nccc333\n"
    with _mock_run(stdout=fake_out):
        result = rev_list("HEAD~3..HEAD")

    assert result == [{"sha": "aaa111"}, {"sha": "bbb222"}, {"sha": "ccc333"}]


# ─── 11. merge_base ──────────────────────────────────────────────────────────

def test_merge_base():
    """merge_base() returns stripped SHA string."""
    with _mock_run(stdout="abc1234567890abcdef\n"):
        result = merge_base("main", "feature-branch")

    assert result == "abc1234567890abcdef"


# ─── 12. tag_l ───────────────────────────────────────────────────────────────

def test_tag_l():
    """tag_l() returns list of {'tag': name} dicts."""
    fake_out = "v0.1.0\nv0.2.0\nv0.3.0\n"
    with _mock_run(stdout=fake_out):
        result = tag_l()

    assert result == [{"tag": "v0.1.0"}, {"tag": "v0.2.0"}, {"tag": "v0.3.0"}]


# ─── 13. git_missing ─────────────────────────────────────────────────────────

def test_git_missing():
    """shutil.which returning None raises GitMissingError with install hint."""
    with patch("src.tools._subprocess.shutil.which", return_value=None):
        # Clear lru_cache so the patched which() is actually called
        from src.tools._subprocess import resolve_exe
        resolve_exe.cache_clear()
        try:
            with pytest.raises(GitMissingError, match="git-scm"):
                log()
        finally:
            resolve_exe.cache_clear()


# ─── 14. git_invocation_error ────────────────────────────────────────────────

def test_git_invocation_error():
    """Subprocess exit 128 with stderr raises GitInvocationError; stderr wrapped."""
    with _mock_run(stderr="fatal: not a git repository", returncode=128):
        with pytest.raises(GitInvocationError, match="fatal: not a git repository"):
            log()


# ─── 15. dubious_ownership_hint ──────────────────────────────────────────────

def test_dubious_ownership_hint():
    """stderr with 'fatal: detected dubious ownership' includes safe.directory hint."""
    with _mock_run(
        stderr="fatal: detected dubious ownership in repository at '/c/arcis/halcyon-lab'",
        returncode=128,
    ):
        with pytest.raises(GitInvocationError) as exc_info:
            log()
    assert "git config --system --add safe.directory" in str(exc_info.value)


# ─── 16. forbidden_op_argparse_rejected ──────────────────────────────────────

def test_forbidden_op_argparse_rejected():
    """Invoking 'python -m src.tools.gitarchaeology commit' exits 2 with argparse error.

    Regression-locks structural FORBIDDEN-list enforcement: the subparser for
    'commit' must NOT exist. argparse responds to an unrecognised subcommand
    with exit code 2 and a message containing 'invalid choice'.
    """
    result = subprocess.run(
        [sys.executable, "-m", "src.tools.gitarchaeology", "commit"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=15,
    )
    assert result.returncode == 2, (
        f"Expected exit 2 for forbidden op 'commit', got {result.returncode}. "
        f"stderr={result.stderr!r}"
    )
    assert "invalid choice" in result.stderr, (
        f"Expected 'invalid choice' in stderr, got: {result.stderr!r}"
    )


# ─── 17. cli_envelope_json_log ───────────────────────────────────────────────

def test_cli_envelope_json_log(tmp_path):
    """CLI --json flag returns valid JSON for log subcommand (against real repo)."""
    repo_root = str(Path(__file__).resolve().parents[2])
    result = subprocess.run(
        [
            sys.executable, "-m", "src.tools.gitarchaeology",
            "log", "--limit", "1", "--repo", repo_root, "--json",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
    )
    assert result.returncode == 0, f"CLI exited non-zero: stderr={result.stderr!r}"
    parsed = json.loads(result.stdout.strip())
    assert isinstance(parsed, list)
    assert len(parsed) >= 1
    assert "sha" in parsed[0]


# ═══════════════════════════════════════════════════════════════════
# DA3 parsing-contract tests
# ═══════════════════════════════════════════════════════════════════


# ─── 18. log_subject_with_embedded_tab ───────────────────────────────────────

def test_log_subject_with_embedded_tab():
    """DA3 maxsplit: embedded tab in subject is preserved — NOT split into phantom column.

    Mutation to remove maxsplit (unbounded split) would break this test.
    """
    # Subject contains a literal tab: "fix:\tactually do the thing"
    sha = "abc1234567890123456789012345678901234567890"
    embedded_subject = "fix:\tactually do the thing"
    fake_line = f"{sha}\tAlice\t2026-05-25 10:00:00 +0000\t{embedded_subject}"

    with _mock_run(stdout=fake_line):
        result = log()

    assert len(result) == 1
    row = result[0]
    assert row["subject"] == embedded_subject, (
        f"Embedded tab in subject was split. Got: {row['subject']!r}"
    )
    assert "\t" in row["subject"]


# ─── 19. log_custom_format_requires_columns ──────────────────────────────────

def test_log_custom_format_requires_columns():
    """DA3: custom format= without format_columns= raises GitArgError BEFORE subprocess."""
    custom_fmt = "%H%x09%an%x09%ae%x09%s"

    with patch("src.tools.gitarchaeology.core._subprocess_run") as mock_run:
        with pytest.raises(GitArgError, match="format_columns"):
            log(format=custom_fmt)
        mock_run.assert_not_called()


# ─── 20. log_custom_format_with_columns ──────────────────────────────────────

def test_log_custom_format_with_columns():
    """DA3: custom format= + format_columns= returns dicts with 4 keys; tab in subject preserved."""
    sha = "aabbccdd" * 5
    fake_line = f"{sha}\tAlice\talice@example.com\tfeat:\treal subject content"
    with _mock_run(stdout=fake_line):
        result = log(
            format="%H%x09%an%x09%ae%x09%s",
            format_columns=["sha", "author", "email", "subject"],
        )

    assert len(result) == 1
    row = result[0]
    assert list(row.keys()) == ["sha", "author", "email", "subject"]
    # embedded tab preserved in subject
    assert row["subject"] == "feat:\treal subject content"


# ─── 21. log_parse_failure_raises ────────────────────────────────────────────

def test_log_parse_failure_raises():
    """DA3: malformed line (too few tabs) raises GitParseError with fields populated."""
    # Default columns: sha, author, date, subject (4 fields, 3 tabs needed)
    # Only 1 tab — malformed
    malformed_line = "abc1234\tonly-one-tab-here"

    with _mock_run(stdout=malformed_line):
        with pytest.raises(GitParseError) as exc_info:
            log()

    err = exc_info.value
    assert err.offending_line == malformed_line
    assert err.expected_columns == 4
    assert err.op == "log"


# ═══════════════════════════════════════════════════════════════════
# DA4 size-governance tests
# ═══════════════════════════════════════════════════════════════════


# ─── 22. blame_large_file_requires_range ─────────────────────────────────────

def test_blame_large_file_requires_range(tmp_path):
    """DA4 pre-invocation gate: blame on >5000-line file without range raises GitArgError.

    Mutation: removing the line-count gate in blame() makes this test fail.
    """
    large_file = tmp_path / "large.py"
    # 5001 lines
    large_file.write_text("\n".join(f"line{i}" for i in range(5001)) + "\n", encoding="utf-8")

    with patch("src.tools.gitarchaeology.core._subprocess_run") as mock_run:
        with pytest.raises(GitArgError, match="5000"):
            blame(file=str(large_file))
        mock_run.assert_not_called()


# ─── 23. blame_large_file_truncates_cleanly ──────────────────────────────────

def test_blame_large_file_truncates_cleanly(tmp_path):
    """DA4: blame with range + max_output_bytes raises GitOutputTruncatedError correctly."""
    large_file = tmp_path / "large.py"
    large_file.write_text("\n".join(f"line{i}" for i in range(5001)) + "\n", encoding="utf-8")

    # 200 bytes of fake blame output — exceeds max_output_bytes=100
    fake_blame = "abc1234 (Alice 2026-05-25 10:00:00 +0000 1) some content here\n" * 3

    with _mock_run(stdout=fake_blame):
        with pytest.raises(GitOutputTruncatedError) as exc_info:
            blame(file=str(large_file), start_line=1, end_line=10, max_output_bytes=100)

    err = exc_info.value
    assert err.partial_output is not None
    assert err.original_size_bytes > 100
    # partial_output must be ≤ 100 bytes (UTF-8)
    assert len(err.partial_output.encode("utf-8")) <= 100
    assert err.op == "blame"


# ─── 24. show_respects_max_output_bytes ──────────────────────────────────────

def test_show_respects_max_output_bytes():
    """DA4: show with max_output_bytes=50 and 5000-byte stdout raises GitOutputTruncatedError."""
    fake_out = "x" * 5000  # exactly 5000 ASCII bytes
    with _mock_run(stdout=fake_out):
        with pytest.raises(GitOutputTruncatedError) as exc_info:
            show(sha="deadbeef", max_output_bytes=50)

    err = exc_info.value
    assert len(err.partial_output.encode("utf-8")) <= 50
    assert err.original_size_bytes == 5000
    assert err.op == "show"


# ─── 25. show_default_max_output_bytes ───────────────────────────────────────

def test_show_default_max_output_bytes():
    """DA4: default cap is 10MB; below → no error; above → GitOutputTruncatedError."""
    # 5 MB — below the 10 MB default → no error
    five_mb = "y" * (5 * 1024 * 1024)
    with _mock_run(stdout=five_mb):
        result = show(sha="deadbeef")
    assert isinstance(result, dict)

    # 11 MB — above default → truncation error
    eleven_mb = "z" * (11 * 1024 * 1024)
    with _mock_run(stdout=eleven_mb):
        with pytest.raises(GitOutputTruncatedError):
            show(sha="deadbeef")


# ─── 26. cli_max_output_bytes_flag ───────────────────────────────────────────

def test_cli_max_output_bytes_flag(tmp_path):
    """DA4 CLI: show --max-output-bytes 100 --json exits 1 with structured error envelope."""
    # We need a real git SHA from the repo to pass to show
    repo_root = str(Path(__file__).resolve().parents[2])
    # Get real SHA for CLI invocation (using subprocess directly — not the tool)
    sha_result = subprocess.run(
        ["git", "-C", repo_root, "log", "--format=%H", "-n", "1"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=15,
    )
    assert sha_result.returncode == 0, f"Could not get HEAD SHA: {sha_result.stderr}"
    sha = sha_result.stdout.strip()

    result = subprocess.run(
        [
            sys.executable, "-m", "src.tools.gitarchaeology",
            "show", sha, "--max-output-bytes", "100", "--json",
            "--repo", repo_root,
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
    )
    # The show output of a real commit is almost certainly > 100 bytes
    assert result.returncode == 1, (
        f"Expected exit 1 (truncation), got {result.returncode}. stdout={result.stdout!r}"
    )
    envelope = json.loads(result.stdout.strip())
    assert "error" in envelope
    assert envelope["error"]["type"] == "GitOutputTruncatedError"
    error_msg = envelope["error"]["message"]
    assert "partial_output" in error_msg or "GitOutputTruncatedError" in envelope["error"]["type"]


# ═══════════════════════════════════════════════════════════════════
# Additional coverage tests for missed branches
# ═══════════════════════════════════════════════════════════════════


def test_safe_truncate_utf8_within_limit():
    """_safe_truncate_utf8 returns text unchanged when size is within limit."""
    from src.tools.gitarchaeology.core import _safe_truncate_utf8
    text = "hello world"
    result = _safe_truncate_utf8(text, max_bytes=1000)
    assert result == text


def test_git_with_repo_option(tmp_path):
    """_git passes -C repo to argv when repo is provided."""
    captured_args = []

    def _capture(args, **kwargs):
        captured_args.extend(args)
        return _completed(stdout="abc\tAlice\t2026-05-25 10:00:00 +0000\tmsg")

    repo_dir = str(tmp_path)
    with patch("src.tools.gitarchaeology.core._subprocess_run", side_effect=_capture):
        log(repo=repo_dir)

    assert "-C" in captured_args
    idx = captured_args.index("-C")
    assert captured_args[idx + 1] == repo_dir


def test_log_invalid_format_columns_last_entry():
    """log() raises GitArgError when format_columns last entry is not subject/body/message."""
    with patch("src.tools.gitarchaeology.core._subprocess_run") as mock_run:
        with pytest.raises(GitArgError, match="format_columns last entry"):
            log(
                format="%H%x09%an%x09%ae",
                format_columns=["sha", "author", "email"],  # last = 'email' - invalid
            )
        mock_run.assert_not_called()


def test_log_skips_empty_lines():
    """log() skips empty lines in output without raising."""
    fake_out = "abc123\tAlice\t2026-05-25\tfix msg\n\n\nbbb456\tBob\t2026-05-25\tchore\n"
    with _mock_run(stdout=fake_out):
        result = log()
    assert len(result) == 2


def test_blame_oserror_reading_file(tmp_path):
    """blame() on a nonexistent file falls back to line_count=0 without raising."""
    missing_file = str(tmp_path / "ghost.py")

    with _mock_run(stdout=""):
        result = blame(file=missing_file)
    assert result == []


def test_blame_no_paren_line(tmp_path):
    """blame() handles lines without ')' using fallback path."""
    small_file = tmp_path / "weird.py"
    small_file.write_text("x\n" * 5, encoding="utf-8")

    fake_out = "abc1234 no-paren-here content\n"
    with _mock_run(stdout=fake_out):
        result = blame(file=str(small_file))
    assert len(result) == 1
    assert result[0]["sha"] == ""
    assert result[0]["content"] == "abc1234 no-paren-here content"


def test_blame_skips_empty_lines(tmp_path):
    """blame() skips empty lines in output."""
    small_file = tmp_path / "code.py"
    small_file.write_text("x\n" * 5, encoding="utf-8")

    fake_out = "abc1234 (Alice 2026-05-25 10:00:00 +0000 1) line1\n\n\n"
    with _mock_run(stdout=fake_out):
        result = blame(file=str(small_file))
    assert len(result) == 1


def test_show_body_parsing():
    """show() correctly captures multi-line body."""
    fake_out = textwrap.dedent("""\
        commit abc123abc123abc123abc123abc123abc123abc123
        Author: Bob <bob@example.com>
        Date:   Tue May 25 12:00:00 2026 +0000

            feat: add new feature

            This is the body.
            Second body line.

        diff --git a/x.py b/x.py
        --- a/x.py
        +++ b/x.py
    """)
    with _mock_run(stdout=fake_out):
        result = show(sha="abc123")
    assert "This is the body" in result["body"]
    assert "Second body line" in result["body"]


def test_diff_with_path():
    """diff(ref_a, ref_b, path=...) includes '--' and path in argv."""
    captured_args = []

    def _capture(args, **kwargs):
        captured_args.extend(args)
        return _completed(stdout="+new line\n")

    with patch("src.tools.gitarchaeology.core._subprocess_run", side_effect=_capture):
        diff("abc", "def", path="src/tools/core.py")

    assert "--" in captured_args
    assert "src/tools/core.py" in captured_args


def test_rev_list_with_limit_and_path():
    """rev_list with limit= and path= includes both in argv."""
    captured_args = []

    def _capture(args, **kwargs):
        captured_args.extend(args)
        return _completed(stdout="sha1\nsha2\n")

    with patch("src.tools.gitarchaeology.core._subprocess_run", side_effect=_capture):
        rev_list("HEAD~10..HEAD", limit=5, path="src/")

    assert "-n" in captured_args
    assert "5" in captured_args
    assert "--" in captured_args
    assert "src/" in captured_args


def test_rev_list_skips_empty_lines():
    """rev_list skips empty lines in output."""
    fake_out = "sha1\n\n\nsha2\n\n"
    with _mock_run(stdout=fake_out):
        result = rev_list("HEAD~2..HEAD")
    assert result == [{"sha": "sha1"}, {"sha": "sha2"}]


def test_tag_l_with_pattern():
    """tag_l(pattern=...) includes pattern in argv."""
    captured_args = []

    def _capture(args, **kwargs):
        captured_args.extend(args)
        return _completed(stdout="v0.1.0\n")

    with patch("src.tools.gitarchaeology.core._subprocess_run", side_effect=_capture):
        tag_l(pattern="v0.*")

    assert "v0.*" in captured_args


def test_blame_author_single_part(tmp_path):
    """blame() handles inner with rsplit giving only 1 part (no trailing line_no)."""
    small_file = tmp_path / "s.py"
    small_file.write_text("x\n" * 5, encoding="utf-8")

    # "(Author)" — inner after rsplit has only 1 element → falls into else branch
    fake_out = "abc1234 (Author) content\n"
    with _mock_run(stdout=fake_out):
        result = blame(file=str(small_file))
    assert len(result) == 1


def test_show_body_line_in_header():
    """show() covers the in_body path where subject already set and blank line follows."""
    # This covers the body_lines append path (line ~408 / ~373)
    fake_out = textwrap.dedent("""\
        commit abc123abc123abc123abc123abc123abc123abc123
        Author: Carol <carol@example.com>
        Date:   Wed May 25 13:00:00 2026 +0000

            refactor: rename stuff

            First body paragraph.

            Second body paragraph.
    """)
    with _mock_run(stdout=fake_out):
        result = show(sha="abc123")
    assert "First body paragraph" in result["body"]
    assert "Second body paragraph" in result["body"]
