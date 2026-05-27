"""
Tests for scripts/dump_watchloop.ps1 and docs/runbooks/stack-dump.md.
Verify-by-mutation: tests must fail without the implementation present.
"""
import pathlib

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
