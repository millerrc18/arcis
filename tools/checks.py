#!/usr/bin/env python3
"""Run every check locally, exactly as CI does.

ruff, mypy --strict (src/), the ledger/size/hygiene checks, then pytest.
Exits 0 only if everything passes.
"""
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TOOLS = REPO / "tools"


def run(label: str, cmd: list[str]) -> bool:
    print(f"--- {label}: {' '.join(cmd)}")
    try:
        proc = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True)
    except OSError as e:
        print(f"{label}: could not start ({e})")
        return False
    if proc.stdout.strip():
        print(proc.stdout.rstrip())
    if proc.returncode != 0:
        if proc.stderr.strip():
            print(proc.stderr.rstrip())
        print(f"{label}: FAILED")
        return False
    print(f"{label}: ok")
    return True


def has_python_sources() -> bool:
    return any((REPO / "src").rglob("*.py"))


def main() -> int:
    py = sys.executable
    steps: list[tuple[str, list[str]]] = [
        ("ruff", [py, "-m", "ruff", "check", "."]),
        ("ledger", [py, str(TOOLS / "check_ledger.py")]),
        ("size", [py, str(TOOLS / "check_size.py")]),
        ("hygiene", [py, str(TOOLS / "check_hygiene.py")]),
        ("pytest", [py, "-m", "pytest"]),
    ]
    if has_python_sources():
        steps.insert(1, ("mypy", [py, "-m", "mypy", "src"]))
    else:
        print("--- mypy: no Python sources under src/, skipped")
    results = [run(label, cmd) for label, cmd in steps]
    print("---")
    if all(results):
        print("all checks passed")
        return 0
    failed = [label for (label, _), ok in zip(steps, results, strict=True) if not ok]
    print(f"FAILED: {', '.join(failed)}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
