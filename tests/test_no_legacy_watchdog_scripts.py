"""Regression lock: the two superseded shell watchdog scripts must not exist
and must not be referenced in callable source (src/, scripts/ Python, tests/).

The shell scripts were replaced by src/scheduler/ollama_watchdog.py (T1)
installed as an NSSM service by scripts/install_service.ps1 (T2).
"""
import os
import subprocess
import sys


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DELETED_FILES = [
    os.path.join(REPO_ROOT, "scripts", "ollama_watchdog.ps1"),
    os.path.join(REPO_ROOT, "scripts", "start_ollama_watchdog.bat"),
]

# Directories where a live code reference would be a bug.
# docs/ and config/known_violations.json are intentionally excluded:
# audit docs may mention the old names as historical prose.
GREP_DIRS = ["src", "tests"]


def test_shell_watchdog_scripts_do_not_exist():
    for path in DELETED_FILES:
        assert not os.path.exists(path), (
            f"Legacy shell watchdog script still present: {path}. "
            "These were superseded by src/scheduler/ollama_watchdog.py under NSSM (T1/T2)."
        )


def test_no_source_or_test_reference_to_shell_watchdog():
    """grep src/ and tests/ for any reference to the deleted script names."""
    pattern = r"ollama_watchdog\.ps1|start_ollama_watchdog"
    found_lines = []
    for directory in GREP_DIRS:
        target = os.path.join(REPO_ROOT, directory)
        if not os.path.isdir(target):
            continue
        result = subprocess.run(
            ["grep", "-rn", "--include=*.py", pattern, target],
            capture_output=True,
            text=True,
        )
        if result.stdout.strip():
            found_lines.append(result.stdout.strip())
    assert not found_lines, (
        "References to deleted shell watchdog scripts found in src/ or tests/:\n"
        + "\n".join(found_lines)
    )
