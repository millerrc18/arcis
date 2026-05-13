"""Structural test: no git conflict markers may ship to main.

Called by: none (test suite)
Calls: none
Owns tables: none
Config keys: none
Tests: self

Scans repo for `<<<<<<<`, `=======`, `>>>>>>>` outside fixture/allowlist paths.
Closes tracker #109 — twice in 24h (2026-05-12) markers shipped to origin/main
because Edit-tool failed silently on multi-line old_string matches during rebase.
This test runs at CI time and catches the class regardless of which tool produced
the marker.
"""

import re
from pathlib import Path

# Files allowed to contain literal conflict-marker strings (this test file
# itself, plus any test fixtures that intentionally exercise marker handling).
ALLOWLIST = {
    "tests/test_no_conflict_markers_in_repo.py",
    # Add others as needed (none currently expected).
}

# Match start-of-line markers only (not embedded in docs prose).
# The 7-character marker is git's canonical form.
_HEAD_RE = re.compile(r"^<{7}", re.MULTILINE)
_MID_RE = re.compile(r"^={7}$", re.MULTILINE)
_TAIL_RE = re.compile(r"^>{7}", re.MULTILINE)

# Directories worth scanning. .git is excluded automatically by Path iteration.
_SCAN_DIRS = ("src", "tests", "scripts", "docs", "config", ".github")
_REPO_ROOT = Path(__file__).resolve().parent.parent

# Binary-ish extensions to skip.
_SKIP_SUFFIXES = {
    ".pyc", ".png", ".jpg", ".jpeg", ".gif", ".pdf",
    ".sqlite3", ".db", ".bin", ".whl", ".gz", ".zip",
}


def _scan_directory(d: Path):
    """Yield (rel, lineno, kind) tuples for every conflict marker found."""
    for p in d.rglob("*"):
        if not p.is_file():
            continue
        if p.suffix.lower() in _SKIP_SUFFIXES:
            continue
        rel = p.relative_to(_REPO_ROOT).as_posix()
        if rel in ALLOWLIST:
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except (UnicodeDecodeError, PermissionError):
            continue
        for kind, pattern in (
            ("HEAD <<<<<<<", _HEAD_RE),
            ("MID =======", _MID_RE),
            ("TAIL >>>>>>>", _TAIL_RE),
        ):
            for match in pattern.finditer(text):
                lineno = text[: match.start()].count("\n") + 1
                yield rel, lineno, kind


def test_no_conflict_markers_in_repo():
    """No git conflict markers may exist anywhere in the tracked source/docs/test/config dirs."""
    findings = []
    for d in _SCAN_DIRS:
        path = _REPO_ROOT / d
        if not path.exists():
            continue
        for rel, lineno, kind in _scan_directory(path):
            findings.append(f"  {rel}:{lineno} -- {kind}")

    assert not findings, (
        "Git conflict markers detected in the repo. These indicate an "
        "incomplete merge/rebase resolution. Fix them before merging:\n"
        + "\n".join(findings)
    )
