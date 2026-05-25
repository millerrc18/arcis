"""PID-scoped force-stop escalation for ProcessManager.

Mirrors src/scheduler/ollama_watchdog.py:180-260 pattern.
NEVER /im. NEVER Stop-Process -Name. PID-scoped only per DD-2.

Called by: src.tools.processmanager.core (future kill_service expansion)
Calls: src.tools._subprocess
Owns tables: none
Config keys: none
Tests: tests/tools/test_processmanager_integration.py (case k)
"""

from __future__ import annotations

import subprocess

from src.tools import _subprocess


def find_pids(exe_name: str) -> list[int]:
    """Discover PIDs for the given executable name via tasklist /fo csv.

    Returns a deduped list. Used to PID-terminate processes — NEVER drives a name-kill.
    """
    result = _subprocess.run(
        ["tasklist", "/fo", "csv", "/nh", "/fi", f"imagename eq {exe_name}"],
        timeout=10,
    )
    pids: list[int] = []
    for line in result.stdout.strip().splitlines():
        parts = [p.strip().strip('"') for p in line.split(",")]
        if len(parts) >= 2:
            try:
                pids.append(int(parts[1]))
            except ValueError:
                continue
    seen: set[int] = set()
    unique: list[int] = []
    for pid in pids:
        if pid not in seen:
            seen.add(pid)
            unique.append(pid)
    return unique


def kill_pid(pid: int) -> subprocess.CompletedProcess:
    """PID-scoped force-stop. Mirrors ollama_watchdog.py:240-260 pattern verbatim.

    Windows escalation: taskkill /f /t /pid -> PowerShell Stop-Process -Id (NEVER -Name).
    NEVER /im. NEVER Stop-Process -Name. PID-scoped only.
    """
    result = _subprocess.run(["taskkill", "/f", "/t", "/pid", str(pid)], timeout=10)
    if result.returncode != 0:
        result = _subprocess.run(
            ["powershell", "-NoProfile", "-Command", f"Stop-Process -Id {pid} -Force"],
            timeout=10,
        )
    return result
