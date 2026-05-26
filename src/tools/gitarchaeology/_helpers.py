"""GitArchaeology shared helpers (extracted from core.py for line-budget compliance).

Purpose: Subprocess wrapper, codepoint-safe truncation, and standard-format
         blame-output parser. Extracted from core.py to stay under the
         400-line file and 60-line function budgets while keeping the
         public API surface in core.py.

Called by: src.tools.gitarchaeology.core (all 7 ops via _git(); blame via
           _parse_standard_blame_output())
Calls:     src.tools._subprocess (resolve_exe, run, GitMissingError)
Owns tables: none
Config keys: none
Tests: tests/tools/test_gitarchaeology_integration.py (T7)
"""

from __future__ import annotations

from typing import Optional

from src.tools._subprocess import resolve_exe
from src.tools._subprocess import run as _subprocess_run
from src.tools.gitarchaeology._errors import (
    GitInvocationError,
    GitOutputTruncatedError,
)


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


def _parse_show_output(stdout: str, sha: str) -> dict:
    """Parse `git show` output into a metadata + diff dict.

    Splits stdout into header (commit/Author/Date + subject + body) and the
    `diff --git ...` trailer. Extracted from show() to keep the public op
    under the 60-line function budget.
    """
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
            result["subject"] = line.strip()
    result["body"] = "\n".join(body_lines).strip()
    return result


def _parse_standard_blame_output(stdout: str, start_line: Optional[int]) -> list[dict]:
    """Parse standard (non-porcelain) `git blame` output into list-of-dicts.

    Standard format per line: `<sha> (<author> <date> <line_no>) <content>`

    Extracted from blame() to keep the public op under the 60-line function
    budget. Returns one dict per source line with keys: sha, author, content,
    line. Malformed lines fall back to raw-content emission rather than raise.
    """
    results: list[dict] = []
    line_no = start_line if start_line is not None else 1
    for line in stdout.splitlines():
        if not line:
            continue
        paren_end = line.find(")")
        if paren_end == -1:
            results.append({"sha": "", "author": "", "content": line, "line": line_no})
            line_no += 1
            continue
        meta = line[: paren_end + 1]
        content = line[paren_end + 1 :]
        if content.startswith(" "):
            content = content[1:]
        sha = meta.split()[0] if meta else ""
        paren_start = meta.find("(")
        if paren_start != -1:
            inner = meta[paren_start + 1 : paren_end]
            parts = inner.rsplit(None, 1)
            if len(parts) == 2:
                author_date_part = parts[0].strip()
                line_no_from_blame = int(parts[1])
                author_parts = author_date_part.rsplit(None, 2)
                author = author_parts[0].strip() if len(author_parts) >= 1 else author_date_part
            else:
                author = inner.strip()
                line_no_from_blame = line_no
        else:
            author = ""
            line_no_from_blame = line_no
        results.append({"sha": sha, "author": author, "content": content, "line": line_no_from_blame})
        line_no += 1
    return results
