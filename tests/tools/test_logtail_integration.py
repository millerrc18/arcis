"""Integration tests for src/tools/logtail — multi-line awareness + rotation safety.

Called by: pytest tests/tools/test_logtail_integration.py
Tests cover:
  (a) multi-line grouping returns 4 entries (3 INFO + 1 ERROR+traceback)
  (b) level filter returns only ERROR entry
  (c) grep filter returns matched entries
  (d) missing file raises LogTailError + logs 'error' event
  (e) empty file returns [] + logs 'success' event
  (f) rotation mid-read raises LogTailError (DA5 monkey-patch)
  (g) CLI envelope for missing file outputs JSON error + exit 1
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest


# ── Fixtures ──────────────────────────────────────────────────────────


SAMPLE_LOG = textwrap.dedent("""\
2026-05-24 09:00:00,001 [main] INFO: system startup complete
2026-05-24 09:01:00,002 [executor] INFO: executor thread started with pool_size=4
2026-05-24 09:02:00,003 [watchdog] INFO: watchdog heartbeat ok
2026-05-24 09:03:00,004 [main] ERROR: unhandled exception in task runner
Traceback (most recent call last):
  File "src/main.py", line 42, in run
    result = task.execute()
  File "src/tasks.py", line 19, in execute
    raise ValueError("bad state")
ValueError: bad state
""")


@pytest.fixture()
def log_file(tmp_path: Path) -> Path:
    p = tmp_path / "arcis.log"
    p.write_text(SAMPLE_LOG, encoding="utf-8")
    return p


@pytest.fixture()
def empty_log_file(tmp_path: Path) -> Path:
    p = tmp_path / "arcis_empty.log"
    p.write_text("", encoding="utf-8")
    return p


def _make_tail(log_path_override: Path):
    """Construct a fresh tail() function with the execution log redirected to tmp_path."""
    from src.tools._safety import safe_op
    from src.tools.logtail.core import _tail_impl

    @safe_op(name="logtail", mutates=False, log_path=log_path_override)
    def _tail(*, lines: int = 100, log_path=None, level=None, grep=None):
        return _tail_impl(lines=lines, log_path=log_path, level=level, grep=grep)

    return _tail


def _read_exec_events(exec_log: Path) -> list[dict]:
    if not exec_log.exists():
        return []
    events = []
    for line in exec_log.read_text(encoding="utf-8").splitlines():
        if line.strip():
            events.append(json.loads(line))
    return events


# ── Test (a): multi-line grouping → 4 entries ─────────────────────────
# Verify-by-mutation: Fails if ENTRY_START regex is loosened to also match
# traceback continuation lines — the ERROR's traceback would split into 4
# separate entries.


def test_tail_multiline_grouping(log_file: Path, tmp_path: Path) -> None:
    tail = _make_tail(tmp_path / "exec.log")
    entries = tail(lines=10, log_path=log_file)
    assert len(entries) == 4, f"expected 4 entries, got {len(entries)}: {entries}"

    error_entry = next(e for e in entries if "ERROR" in e)
    assert "Traceback" in error_entry
    assert "ValueError: bad state" in error_entry


# ── Test (b): level filter → only ERROR entry ─────────────────────────


def test_tail_level_filter_error(log_file: Path, tmp_path: Path) -> None:
    tail = _make_tail(tmp_path / "exec.log")
    entries = tail(level="ERROR", log_path=log_file)
    assert len(entries) == 1
    assert "ERROR" in entries[0]
    assert "unhandled exception" in entries[0]


# ── Test (c): grep filter → matched entries ───────────────────────────


def test_tail_grep_filter(log_file: Path, tmp_path: Path) -> None:
    tail = _make_tail(tmp_path / "exec.log")
    entries = tail(grep="executor", log_path=log_file)
    assert len(entries) >= 1
    for e in entries:
        assert "executor" in e


# ── Test (d): missing file raises LogTailError + logs 'error' event ──


def test_tail_missing_file_raises(tmp_path: Path) -> None:
    from src.tools.logtail.core import LogTailError

    exec_log = tmp_path / "exec.log"
    tail = _make_tail(exec_log)
    nonexistent = tmp_path / "nonexistent.log"
    with pytest.raises(LogTailError):
        tail(log_path=nonexistent)

    events = _read_exec_events(exec_log)
    assert any(e["result"] == "error" and e["tool_name"] == "logtail" for e in events)


# ── Test (e): empty file returns [] + logs 'success' event ───────────


def test_tail_empty_file(empty_log_file: Path, tmp_path: Path) -> None:
    exec_log = tmp_path / "exec.log"
    tail = _make_tail(exec_log)
    entries = tail(log_path=empty_log_file)
    assert entries == []

    events = _read_exec_events(exec_log)
    assert any(e["result"] == "success" and e["tool_name"] == "logtail" for e in events)


# ── Test (f): rotation mid-read raises LogTailError (DA5) ─────────────
# Verify-by-mutation: Fails if the post-read os.fstat check is removed —
# the test never raises and the assertion fails.


def test_tail_rotation_mid_read(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from src.tools.logtail.core import LogTailError

    tail = _make_tail(tmp_path / "exec.log")

    # Create a 200KB log file with valid entries
    big_log = tmp_path / "big.log"
    entry_line = "2026-05-24 09:00:00,001 [main] INFO: padding entry for large file test\n"
    with big_log.open("w", encoding="utf-8") as f:
        while f.tell() < 200 * 1024:
            f.write(entry_line)

    # Monkey-patch os.fstat: call 1 returns real result, call 2 returns fake smaller size
    real_fstat = os.fstat
    call_count = [0]

    def _patched_fstat(fd: int):
        call_count[0] += 1
        real_result = real_fstat(fd)
        if call_count[0] == 1:
            return real_result
        # Synthesize a stat_result with a smaller st_size to simulate rotation
        real_seq = list(real_result)
        real_seq[6] = real_result.st_size - 1  # st_size field (index 6) shrunk
        return os.stat_result(real_seq)

    monkeypatch.setattr(os, "fstat", _patched_fstat)

    with pytest.raises(LogTailError) as exc_info:
        tail(log_path=big_log)

    assert "rotated" in str(exc_info.value).lower() or "truncated" in str(exc_info.value).lower()


# ── Test (g): CLI envelope → JSON error + exit 1 ─────────────────────


def test_cli_envelope_missing_file(tmp_path: Path) -> None:
    nonexistent = tmp_path / "missing.log"
    result = subprocess.run(
        [sys.executable, "-m", "src.tools.logtail", "--log-path", str(nonexistent), "--json"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    data = json.loads(result.stdout)
    assert "error" in data
    assert data["error"]["type"] == "LogTailError"
    assert data["error"]["tool"] == "logtail"
    assert "message" in data["error"]
