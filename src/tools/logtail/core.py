"""LogTail tool — tail the last N entries from arcis.log with multi-line awareness.

Called by: src/tools/logtail/__main__.py, operator agents
Calls: src.tools._config.load_arcis_config, src.tools._safety.safe_op
Owns tables: none
Config keys: paths.logs_runtime (for default log path)
Tests: tests/tools/test_logtail_integration.py
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Optional

from src.tools._config import load_arcis_config
from src.tools._safety import safe_op


# ── Entry-start pattern ───────────────────────────────────────────────

ENTRY_START = re.compile(
    r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}[,.]\d+ \[[^\]]+\] (DEBUG|INFO|WARNING|ERROR|CRITICAL):"
)

# ── Level hierarchy ───────────────────────────────────────────────────

_LEVEL_ORDER = {
    "DEBUG": 0,
    "INFO": 1,
    "WARNING": 2,
    "ERROR": 3,
    "CRITICAL": 4,
}

# ── Chunk size for backward read ──────────────────────────────────────

_CHUNK_SIZE = 64 * 1024  # 64 KB


# ── Error ─────────────────────────────────────────────────────────────


class LogTailError(RuntimeError):
    """Raised on I/O errors, missing file, permission errors, or rotation mid-read."""


# ── Internal helpers ──────────────────────────────────────────────────


def _group_lines_into_entries(raw_lines: list[str]) -> list[str]:
    """Group flat lines into multi-line log entries.

    Lines matching ENTRY_START begin a new entry. Lines that do NOT match
    (continuation lines such as traceback frames) are appended to the
    most-recent entry with a newline.
    """
    entries: list[list[str]] = []
    for line in raw_lines:
        if ENTRY_START.match(line):
            entries.append([line])
        elif entries:
            entries[-1].append(line)
        # Lines before the first entry-start are discarded (shouldn't happen
        # with a well-formed arcis.log, but handle gracefully).
    return ["\n".join(parts) for parts in entries]


def _extract_entry_level(entry: str) -> Optional[str]:
    """Return the level token (DEBUG/INFO/WARNING/ERROR/CRITICAL) from an entry."""
    m = ENTRY_START.match(entry)
    if m:
        return m.group(1)
    return None


def _passes_level_filter(entry: str, level: str) -> bool:
    """Return True if the entry's level is >= the requested level."""
    min_rank = _LEVEL_ORDER.get(level.upper(), 0)
    entry_level = _extract_entry_level(entry)
    if entry_level is None:
        return False
    return _LEVEL_ORDER.get(entry_level, -1) >= min_rank


def _read_lines_backward(f, file_size: int, n_entries: int) -> list[str]:
    """Read lines backwards from an open binary file handle until we have enough.

    For files < 64KB: read the whole file at once.
    For files >= 64KB: seek backwards in 64KB chunks.

    Returns raw lines in FORWARD order (oldest first), limited to enough
    lines to produce at least n_entries log entries after grouping.
    We read all lines then trim after grouping — simpler and correct.
    """
    if file_size == 0:
        return []

    if file_size < _CHUNK_SIZE:
        f.seek(0)
        content = f.read(file_size)
        return content.decode("utf-8", errors="replace").splitlines()

    # Backward chunked read
    remaining = file_size
    partial = b""
    collected_lines: list[str] = []
    enough = False

    while remaining > 0 and not enough:
        chunk_start = max(0, remaining - _CHUNK_SIZE)
        chunk_len = remaining - chunk_start
        f.seek(chunk_start)
        chunk = f.read(chunk_len)
        # Prepend any partial line from previous iteration
        chunk = chunk + partial
        remaining = chunk_start

        # Split into lines; the first element may be a partial line
        parts = chunk.split(b"\n")
        # The first part (if chunk_start > 0) may be incomplete — save for next iteration
        if chunk_start > 0:
            partial = parts[0]
            lines_this_chunk = parts[1:]
        else:
            partial = b""
            lines_this_chunk = parts

        # Decode and prepend (we're going backwards, so prepend to front)
        decoded = [p.decode("utf-8", errors="replace") for p in reversed(lines_this_chunk) if p]
        collected_lines = decoded + collected_lines

        # Check if we already have enough entries (count entry-start matches)
        entry_count = sum(1 for ln in collected_lines if ENTRY_START.match(ln))
        if entry_count >= n_entries:
            enough = True

    # Handle any remaining partial line from the very first chunk
    if partial:
        first_line = partial.decode("utf-8", errors="replace")
        if first_line:
            collected_lines = [first_line] + collected_lines

    return collected_lines


# ── Implementation (unwrapped) ────────────────────────────────────────


def _tail_impl(
    *,
    lines: int = 100,
    log_path: Optional[Path] = None,
    level: Optional[str] = None,
    grep: Optional[str] = None,
) -> list[str]:
    """Unwrapped implementation — called by the @safe_op-decorated tail() and by tests."""
    if log_path is None:
        try:
            cfg = load_arcis_config()
            log_path = cfg.paths.logs_runtime / "arcis.log"
        except Exception as exc:
            raise LogTailError(f"cannot resolve default log path: {exc}") from exc

    log_path = Path(log_path)

    try:
        with open(log_path, "rb") as f:
            initial_size = os.fstat(f.fileno()).st_size
            raw_lines = _read_lines_backward(f, initial_size, lines)
            final_size = os.fstat(f.fileno()).st_size
            if final_size < initial_size:
                raise LogTailError("file rotated/truncated mid-read; retry")
    except LogTailError:
        raise
    except FileNotFoundError as exc:
        raise LogTailError(f"log file not found: {log_path}") from exc
    except PermissionError as exc:
        raise LogTailError(f"permission denied reading log file: {log_path}") from exc
    except OSError as exc:
        raise LogTailError(f"I/O error reading log file: {exc}") from exc

    all_entries = _group_lines_into_entries(raw_lines)

    # Take the last N entries (entries are in forward/chronological order)
    recent = all_entries[-lines:] if len(all_entries) > lines else all_entries

    # Apply filters
    if level is not None:
        recent = [e for e in recent if _passes_level_filter(e, level)]

    if grep is not None:
        recent = [e for e in recent if grep in e]

    return recent


# ── Public API ────────────────────────────────────────────────────────


@safe_op(name="logtail", mutates=False)
def tail(
    *,
    lines: int = 100,
    log_path: Optional[Path] = None,
    level: Optional[str] = None,
    grep: Optional[str] = None,
) -> list[str]:
    """Tail the last N entries from arcis.log, multi-line aware.

    Opens the log file at invocation time and reads BACKWARDS in a single pass.
    The file handle is held for the duration of the call. If the file is
    rotated, renamed, or truncated by NSSM (or any external rotator) DURING
    the read, the tool detects the size shrink via os.fstat(handle).st_size
    and raises LogTailError('file rotated/truncated mid-read; retry').
    Callers should retry on this error; back-to-back retries yielding the
    same error indicate a busy rotation period — backoff.
    """
    return _tail_impl(lines=lines, log_path=log_path, level=level, grep=grep)
