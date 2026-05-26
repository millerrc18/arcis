"""GitArchaeology core — 7 read-only git ops with subprocess discipline.

Purpose: Provide a single subprocess-disciplined surface for read-only
         git CLI operations. All invocations go through _subprocess.run.
         Mutating ops are structurally absent — not present as subparsers.

Called by: src.tools.gitarchaeology.__main__ (CLI), git-historian agent (#108)
Calls:     src.tools._subprocess (resolve_exe, run, GitMissingError),
           src.tools._safety (safe_op)
Owns tables: none
Config keys: none
Tests: tests/tools/test_gitarchaeology_integration.py (T7)

FORBIDDEN ops (NOT exposed — structural defense by construction):
  git commit       — mutates history
  git push         — mutates remote
  git reset        — mutates working tree / HEAD
  git rebase       — mutates history
  git checkout     — mutates working tree (destructive variants)
  git branch -D    — destroys branches
  git clean -f     — destroys untracked files
  git cherry-pick  — mutates history
  git stash drop   — destroys stashed work
  git tag -d       — destroys tags
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from src.tools._safety import safe_op
from src.tools._subprocess import GitMissingError, resolve_exe  # noqa: F401 (re-exported)
from src.tools._subprocess import run as _subprocess_run


# ═══════════════════════════════════════════════════════════════════
# Error classes
# ═══════════════════════════════════════════════════════════════════


class GitArchaeologyError(RuntimeError):
    """Root error class for GitArchaeology ops."""


class GitInvocationError(GitArchaeologyError):
    """Raised when git subprocess exits non-zero."""


class GitArgError(GitArchaeologyError):
    """Raised on invalid arguments to a GitArchaeology API call.

    Examples:
      - blame() called with start_line > end_line
      - log() called with custom format= but no format_columns=
      - blame() called on a >5000-line file without line-range
    """


class GitParseError(GitArchaeologyError):
    """Raised when git output cannot be mapped to the expected shape (DA3).

    Fields:
      offending_line:   the raw output line that could not be parsed
      expected_columns: how many tab-separated columns were expected
      op:               which op triggered the error (e.g., 'log')
    """

    def __init__(
        self,
        message: str,
        offending_line: str,
        expected_columns: int,
        op: str,
    ) -> None:
        super().__init__(message)
        self.offending_line = offending_line
        self.expected_columns = expected_columns
        self.op = op


class GitOutputTruncatedError(GitArchaeologyError):
    """Raised when git output exceeds per-op max_output_bytes (DA4).

    Fields:
      partial_output:      first max_output_bytes of stdout (codepoint-safe)
      original_size_bytes: actual UTF-8 byte count of full output
      op:                  which op triggered the error
    """

    def __init__(
        self,
        message: str,
        partial_output: str,
        original_size_bytes: int,
        op: str,
    ) -> None:
        super().__init__(message)
        self.partial_output = partial_output
        self.original_size_bytes = original_size_bytes
        self.op = op


# ═══════════════════════════════════════════════════════════════════
# Shared helpers
# ═══════════════════════════════════════════════════════════════════

_DEFAULT_LOG_FORMAT = "%H%x09%an%x09%ai%x09%s"
_DEFAULT_LOG_COLUMNS = ["sha", "author", "date", "subject"]


def _safe_truncate_utf8(text: str, max_bytes: int) -> str:
    """Truncate `text` to at most `max_bytes` UTF-8 bytes at a codepoint boundary."""
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text
    truncated = encoded[:max_bytes]
    return truncated.decode("utf-8", errors="ignore")


def _git(
    args: list[str],
    *,
    timeout_s: int,
    repo: Optional[str],
    max_output_bytes: int,
    op_name: str,
) -> str:
    """Invoke git via _subprocess.run; enforce size limit; return stdout.

    Raises:
      GitMissingError:         git not on PATH (from resolve_exe)
      GitInvocationError:      non-zero returncode
      GitOutputTruncatedError: stdout exceeds max_output_bytes (DA4)
    """
    exe = resolve_exe("git")
    full_args: list[str] = [exe]
    if repo is not None:
        full_args.extend(["-C", repo])
    full_args.extend(args)

    result = _subprocess_run(full_args, timeout=timeout_s)

    if result.returncode != 0:
        stderr = result.stderr.strip()
        msg = f"git {args[0]} failed (exit {result.returncode}): {stderr}"
        if "fatal: detected dubious ownership" in stderr:
            msg += " (run: git config --system --add safe.directory C:/arcis/halcyon-lab)"
        raise GitInvocationError(msg)

    stdout = result.stdout
    size_bytes = len(stdout.encode("utf-8"))
    if size_bytes > max_output_bytes:
        partial = _safe_truncate_utf8(stdout, max_output_bytes)
        raise GitOutputTruncatedError(
            message=(
                f"git {op_name} output ({size_bytes} bytes) exceeds "
                f"max_output_bytes={max_output_bytes}; "
                f"partial output available via GitOutputTruncatedError.partial_output"
            ),
            partial_output=partial,
            original_size_bytes=size_bytes,
            op=op_name,
        )

    return stdout


# ═══════════════════════════════════════════════════════════════════
# Public functions
# ═══════════════════════════════════════════════════════════════════


@safe_op(name="gitarchaeology", mutates=False)
def log(
    range: Optional[str] = None,
    *,
    path: Optional[str] = None,
    format: str = _DEFAULT_LOG_FORMAT,
    format_columns: Optional[list[str]] = None,
    limit: int = 50,
    repo: Optional[str] = None,
    timeout_s: int = 30,
    max_output_bytes: Optional[int] = None,
) -> list[dict]:
    """Run `git log [--format=<format>] [-n <limit>] [<range>] [-- <path>]`.

    Returns list of dicts (one per commit). Default columns:
      sha (str, full 40-char hex)
      author (str)
      date (str, ISO 8601 with timezone)
      subject (str)

    DA3 rules enforced:
      - format=/format_columns= must be paired when format is custom.
      - format_columns[-1] must be in {'subject', 'body', 'message'}.
      - line.split('\\t', N-1) with explicit maxsplit — never unbounded.
      - Malformed lines raise GitParseError (not silently dropped).

    DA4: max_output_bytes defaults to limit * 200 if None.
    """
    if format_columns is None:
        if format != _DEFAULT_LOG_FORMAT:
            raise GitArgError("custom format= requires format_columns= kwarg")
        format_columns = _DEFAULT_LOG_COLUMNS

    if format_columns[-1] not in {"subject", "body", "message"}:
        raise GitArgError(
            f"format_columns last entry must be subject/body/message, "
            f"got {format_columns[-1]!r}"
        )

    if max_output_bytes is None:
        max_output_bytes = limit * 200

    argv = ["log", f"--format={format}", "-n", str(limit)]
    if range is not None:
        argv.append(range)
    if path is not None:
        argv.extend(["--", path])

    stdout = _git(argv, timeout_s=timeout_s, repo=repo, max_output_bytes=max_output_bytes, op_name="log")

    results: list[dict] = []
    maxsplit = len(format_columns) - 1
    for line in stdout.splitlines():
        if not line:
            continue
        parts = line.split("\t", maxsplit)
        if len(parts) < len(format_columns):
            raise GitParseError(
                message=(
                    f"git log output line has {len(parts)} fields, "
                    f"expected {len(format_columns)}"
                ),
                offending_line=line,
                expected_columns=len(format_columns),
                op="log",
            )
        results.append(dict(zip(format_columns, parts)))
    return results


@safe_op(name="gitarchaeology", mutates=False)
def blame(
    file: str,
    *,
    start_line: Optional[int] = None,
    end_line: Optional[int] = None,
    repo: Optional[str] = None,
    timeout_s: int = 60,
    max_output_bytes: Optional[int] = None,
) -> list[dict]:
    """Run `git blame [-L <start>,<end>] -- <file>`.

    Returns list of dicts (one per source line):
      sha     (str, full 40-char hex of the originating commit)
      author  (str)
      content (str, the actual source line)
      line    (int, 1-based line number in the file)

    DA4 pre-invocation gate: if start_line and end_line are both None
    and the target file has >5000 lines, raises GitArgError before
    any subprocess is spawned.
    """
    if start_line is not None and end_line is not None:
        if start_line > end_line:
            raise GitArgError(
                f"blame start_line ({start_line}) must be <= end_line ({end_line})"
            )

    if start_line is None and end_line is None:
        try:
            line_count = Path(file).read_text(encoding="utf-8").count("\n")
        except OSError:
            line_count = 0
        if line_count > 5000:
            raise GitArgError(
                "blame on >5000-line file requires start_line + end_line range"
            )

    if max_output_bytes is None:
        max_output_bytes = 2_000_000

    argv = ["blame"]
    if start_line is not None and end_line is not None:
        argv.extend(["-L", f"{start_line},{end_line}"])
    argv.extend(["--", file])

    stdout = _git(argv, timeout_s=timeout_s, repo=repo, max_output_bytes=max_output_bytes, op_name="blame")

    results: list[dict] = []
    line_no = start_line if start_line is not None else 1
    for line in stdout.splitlines():
        if not line:
            continue
        # Standard (non-porcelain) blame format: "<sha> (<author> <date> <line_no>) <content>"
        # Split on first ')' to separate metadata from content
        paren_end = line.find(")")
        if paren_end == -1:
            # Fallback: return raw line
            results.append({"sha": "", "author": "", "content": line, "line": line_no})
            line_no += 1
            continue

        meta = line[: paren_end + 1]
        content = line[paren_end + 1 :]
        if content.startswith(" "):
            content = content[1:]

        # Extract sha from start (first whitespace-delimited token)
        sha = meta.split()[0] if meta else ""

        # Extract author from inside parens
        paren_start = meta.find("(")
        if paren_start != -1:
            inner = meta[paren_start + 1 : paren_end]
            # inner = "Author Name 2026-05-25 10:00:00 +0000   42"
            # Remove trailing line number
            parts = inner.rsplit(None, 1)
            if len(parts) == 2:
                author_date_part = parts[0].strip()
                line_no_from_blame = int(parts[1])
                # Remove trailing date portion — last two tokens are date + tz
                author_parts = author_date_part.rsplit(None, 2)
                author = author_parts[0].strip() if len(author_parts) >= 1 else author_date_part
            else:
                author = inner.strip()
                line_no_from_blame = line_no
        else:
            author = ""
            line_no_from_blame = line_no

        results.append(
            {
                "sha": sha,
                "author": author,
                "content": content,
                "line": line_no_from_blame,
            }
        )
        line_no += 1

    return results


@safe_op(name="gitarchaeology", mutates=False)
def show(
    sha: str,
    *,
    path: Optional[str] = None,
    repo: Optional[str] = None,
    timeout_s: int = 30,
    max_output_bytes: Optional[int] = None,
) -> dict:
    """Run `git show <sha> [-- <path>]`.

    Returns dict:
      sha     (str)
      author  (str)
      date    (str, ISO 8601)
      subject (str)
      body    (str)
      diff    (str, unified diff text)

    DA4: max_output_bytes defaults to 10_000_000 if None.
    """
    if max_output_bytes is None:
        max_output_bytes = 10_000_000

    argv = ["show", sha]
    if path is not None:
        argv.extend(["--", path])

    stdout = _git(argv, timeout_s=timeout_s, repo=repo, max_output_bytes=max_output_bytes, op_name="show")

    result: dict = {"sha": sha, "author": "", "date": "", "subject": "", "body": "", "diff": ""}

    lines = stdout.splitlines()
    in_diff = False
    diff_lines: list[str] = []
    header_lines: list[str] = []

    for line in lines:
        if line.startswith("diff --git") or in_diff:
            in_diff = True
            diff_lines.append(line)
        else:
            header_lines.append(line)

    result["diff"] = "\n".join(diff_lines)

    # Parse commit header block
    body_lines: list[str] = []
    in_body = False
    for line in header_lines:
        if line.startswith("commit "):
            result["sha"] = line[7:].strip()
        elif line.startswith("Author:"):
            result["author"] = line[7:].strip()
        elif line.startswith("Date:"):
            result["date"] = line[5:].strip()
        elif line == "" and result["subject"]:
            in_body = True
        elif line == "" and not result["subject"]:
            pass
        elif in_body:
            body_lines.append(line.lstrip())
        elif result["date"] and not result["subject"] and line.strip():
            # First non-empty line after Date: is the subject (indented by 4 spaces in git show)
            result["subject"] = line.strip()

    result["body"] = "\n".join(body_lines).strip()
    return result


@safe_op(name="gitarchaeology", mutates=False)
def diff(
    ref_a: str,
    ref_b: str,
    *,
    path: Optional[str] = None,
    repo: Optional[str] = None,
    timeout_s: int = 30,
    max_output_bytes: Optional[int] = None,
) -> str:
    """Run `git diff <ref_a>..<ref_b> [-- <path>]`.

    Returns the unified diff text verbatim (per spec §5.1, §5.3).

    DA4: max_output_bytes defaults to 10_000_000 if None.
    """
    if max_output_bytes is None:
        max_output_bytes = 10_000_000

    argv = ["diff", f"{ref_a}..{ref_b}"]
    if path is not None:
        argv.extend(["--", path])

    stdout = _git(argv, timeout_s=timeout_s, repo=repo, max_output_bytes=max_output_bytes, op_name="diff")

    return stdout


@safe_op(name="gitarchaeology", mutates=False)
def rev_list(
    range: str,
    *,
    path: Optional[str] = None,
    limit: Optional[int] = None,
    repo: Optional[str] = None,
    timeout_s: int = 30,
    max_output_bytes: Optional[int] = None,
) -> list[dict]:
    """Run `git rev-list [<-n limit>] <range> [-- <path>]`.

    Returns list of {'sha': <sha>} dicts.

    DA4: max_output_bytes defaults to (limit * 50) if limit else 2_500_000.
    """
    if max_output_bytes is None:
        max_output_bytes = (limit * 50) if limit else 2_500_000

    argv = ["rev-list"]
    if limit is not None:
        argv.extend(["-n", str(limit)])
    argv.append(range)
    if path is not None:
        argv.extend(["--", path])

    stdout = _git(argv, timeout_s=timeout_s, repo=repo, max_output_bytes=max_output_bytes, op_name="rev_list")

    return [{"sha": line.strip()} for line in stdout.splitlines() if line.strip()]


@safe_op(name="gitarchaeology", mutates=False)
def merge_base(
    ref_a: str,
    ref_b: str,
    *,
    repo: Optional[str] = None,
    timeout_s: int = 10,
) -> str:
    """Run `git merge-base <ref_a> <ref_b>`.

    Returns the merge-base SHA as a stripped string.
    """
    argv = ["merge-base", ref_a, ref_b]
    stdout = _git(argv, timeout_s=timeout_s, repo=repo, max_output_bytes=100, op_name="merge_base")
    return stdout.strip()


@safe_op(name="gitarchaeology", mutates=False)
def tag_l(
    pattern: Optional[str] = None,
    *,
    repo: Optional[str] = None,
    timeout_s: int = 10,
) -> list[dict]:
    """Run `git tag -l [<pattern>]`.

    Returns list of {'tag': <tag_name>} dicts.
    """
    argv = ["tag", "-l"]
    if pattern is not None:
        argv.append(pattern)

    stdout = _git(argv, timeout_s=timeout_s, repo=repo, max_output_bytes=1_000_000, op_name="tag_l")

    return [{"tag": line.strip()} for line in stdout.splitlines() if line.strip()]
