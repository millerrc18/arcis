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
from src.tools._subprocess import GitMissingError  # noqa: F401 (re-exported)
from src.tools.gitarchaeology._errors import (  # noqa: F401 (re-exported)
    GitArchaeologyError,
    GitArgError,
    GitInvocationError,
    GitOutputTruncatedError,
    GitParseError,
)
from src.tools.gitarchaeology._helpers import (  # noqa: F401 (used by ops)
    _git,
    _parse_show_output,
    _parse_standard_blame_output,
)


# Log format defaults (DA3): default 4-column TSV; custom format requires paired columns.
_DEFAULT_LOG_FORMAT = "%H%x09%an%x09%ai%x09%s"
_DEFAULT_LOG_COLUMNS = ["sha", "author", "date", "subject"]


def _resolve_log_format(
    format: str, format_columns: Optional[list[str]]
) -> list[str]:
    """DA3: validate format / format_columns pairing; return resolved columns."""
    if format_columns is None:
        if format != _DEFAULT_LOG_FORMAT:
            raise GitArgError("custom format= requires format_columns= kwarg")
        format_columns = _DEFAULT_LOG_COLUMNS
    if format_columns[-1] not in {"subject", "body", "message"}:
        raise GitArgError(
            f"format_columns last entry must be subject/body/message, "
            f"got {format_columns[-1]!r}"
        )
    return format_columns


def _parse_log_output(stdout: str, format_columns: list[str]) -> list[dict]:
    """DA3: parse tab-separated git-log output with explicit maxsplit."""
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
    format_columns = _resolve_log_format(format, format_columns)
    if max_output_bytes is None:
        max_output_bytes = limit * 200

    argv = ["log", f"--format={format}", "-n", str(limit)]
    if range is not None:
        argv.append(range)
    if path is not None:
        argv.extend(["--", path])

    stdout = _git(argv, timeout_s=timeout_s, repo=repo, max_output_bytes=max_output_bytes, op_name="log")
    return _parse_log_output(stdout, format_columns)


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
    return _parse_standard_blame_output(stdout, start_line)


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
    return _parse_show_output(stdout, sha)


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
