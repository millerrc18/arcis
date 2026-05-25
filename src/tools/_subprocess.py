"""Shared subprocess helpers for the tool suite.

Purpose: Centralise subprocess.run invocations so every tool call uses
         capture_output=True, text=True, encoding='utf-8', and NEVER
         shell=True. Provides cached exe resolution with actionable
         install hints for missing binaries.

Called by: src.tools.process_manager (T3), src.tools.pr_comments (T5)
Calls:     shutil, subprocess (stdlib only)
Owns tables: none
Config keys: none
Tests: tests/tools/test_subprocess.py  (T3/T5's responsibility)

Grep verifications (recorded at T1 implementation, consumed by Tasks 3/4/6):
  (a) safety_window @ src/tools/_safety.py:291
  (b) _sc_query_running anti-pattern siblings:
      - src/scheduler/watch.py:130-147  (function definition + body)
      - src/scheduler/watch.py:1161-1163  (call site in loop body)
  (c) TABLES @ src/schema/registry.py:90 (count=80)
  (d) cwd-relative watchdog write @ src/scheduler/watch.py:1724-1732
      statusline discovery walk @ scripts/statusline.py:63-73
"""

from __future__ import annotations

import shutil
import subprocess
from functools import lru_cache


class NssmMissingError(subprocess.SubprocessError):
    """Raised when nssm.exe cannot be located on PATH."""


class GhMissingError(subprocess.SubprocessError):
    """Raised when gh.exe cannot be located on PATH."""


@lru_cache(maxsize=4)
def resolve_exe(name: str) -> str:
    """Return the absolute path to `name` on PATH, or raise a descriptive error.

    Results are cached so repeated calls (e.g. inside a tool loop) pay no
    shutil.which cost after the first resolution.
    """
    exe = shutil.which(name)
    if not exe:
        if name == 'nssm':
            raise NssmMissingError(
                'nssm not on PATH. Install via choco install nssm or download from https://nssm.cc/'
            )
        if name == 'gh':
            raise GhMissingError(
                'gh not on PATH. Install via winget install GitHub.cli or https://cli.github.com/ '
                '(>= 2.0 required for --body-file - stdin)'
            )
        raise subprocess.SubprocessError(f'{name} not on PATH')
    return exe


def run(
    args: list[str],
    *,
    timeout: int = 10,
    check: bool = False,
    input_data: str | None = None,
) -> subprocess.CompletedProcess:
    """Standardized subprocess.run. NEVER shell=True. Always capture_output, text, utf-8."""
    return subprocess.run(
        args,
        capture_output=True,
        text=True,
        encoding='utf-8',
        timeout=timeout,
        check=check,
        input=input_data,
    )
