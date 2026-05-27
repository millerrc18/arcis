"""
Tests for scripts/dump_watchloop.ps1 and docs/runbooks/stack-dump.md.
Verify-by-mutation: tests must fail without the implementation present.
"""
import pathlib
import shutil
import subprocess

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "dump_watchloop.ps1"
RUNBOOK_PATH = REPO_ROOT / "docs" / "runbooks" / "stack-dump.md"


def _script_text() -> str:
    return SCRIPT_PATH.read_text(encoding="utf-8")


def _runbook_text() -> str:
    return RUNBOOK_PATH.read_text(encoding="utf-8")


def test_script_file_exists():
    assert SCRIPT_PATH.exists(), f"Missing script: {SCRIPT_PATH}"


def test_script_contains_start_process():
    assert "Start-Process" in _script_text(), "Script must contain 'Start-Process'"


def test_script_contains_verb_runas():
    assert "-Verb RunAs" in _script_text(), "Script must contain '-Verb RunAs'"


def test_script_contains_pyspy_dump():
    assert "py-spy dump" in _script_text(), "Script must contain 'py-spy dump'"


def test_script_references_logs_path():
    text = _script_text()
    assert "halcyon-lab/logs" in text or "halcyon-lab\\logs" in text, (
        "Script must reference halcyon-lab/logs (or halcyon-lab\\logs)"
    )


def test_runbook_file_exists():
    assert RUNBOOK_PATH.exists(), f"Missing runbook: {RUNBOOK_PATH}"


def test_runbook_references_script():
    text = _runbook_text()
    assert "dump_watchloop.ps1" in text, "Runbook must reference dump_watchloop.ps1"


def test_script_does_not_use_pid_automatic_variable():
    """Ensure the script uses $ProcessId, not $Pid (PowerShell automatic variable).

    $Pid is a read-only automatic variable in PowerShell (Options=Constant,AllScope).
    Declaring `param([int]$Pid = 0)` or assigning `$Pid = ...` crashes with:
      Cannot overwrite variable Pid because it is read-only or constant.
    """
    text = _script_text()
    assert "$Pid" not in text, (
        "Script must not use $Pid (PowerShell automatic variable — read-only). "
        "Rename to $ProcessId or another non-reserved identifier."
    )


def test_live_invocation_no_readonly_variable_crash():
    """Live pwsh smoke test: script must not crash with 'Cannot overwrite variable'.

    Passes -ProcessId 999999 (an obviously-invalid PID).  The script should fail
    cleanly (py-spy not installed, process not found, etc.) but NOT with the
    read-only-variable error that would occur if $Pid were still used as the param.

    Skips gracefully if pwsh is not available on the runner.
    """
    if shutil.which("pwsh") is None:
        pytest.skip("pwsh not available on this runner")

    result = subprocess.run(
        ["pwsh", "-NoProfile", "-File", str(SCRIPT_PATH), "-ProcessId", "999999"],
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert "Cannot overwrite variable" not in result.stderr, (
        f"Script crashed with read-only variable error. stderr={result.stderr!r}"
    )
    assert "Cannot overwrite variable" not in result.stdout, (
        f"Script crashed with read-only variable error. stdout={result.stdout!r}"
    )
    assert "read-only" not in result.stderr.lower(), (
        f"Script crashed with read-only error. stderr={result.stderr!r}"
    )
