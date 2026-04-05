#!/usr/bin/env python3
"""Verify MASTER.md counts match actual code/DB state.

When to run:
    After every sprint, or as part of CI. Catches drift between the
    documented counts in MASTER.md and the actual codebase.

What it reads:
    - MASTER.md (regex-extracts Python files, Tests, Dashboard pages,
      Research docs counts from both bold-format and table-format)
    - Filesystem counts under src/, tests/, frontend/src/pages/, docs/research/

What it writes:
    - Nothing — stdout drift report. Exit 1 if any count mismatches.

Prerequisites:
    - MASTER.md must exist in repo root

Usage:
    python scripts/verify_docs.py
"""

import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATE_FILE = ROOT / "MASTER.md"


def _read_state():
    return STATE_FILE.read_text(encoding="utf-8")


def _extract_number(text, pattern):
    """Extract first integer from a regex match in text."""
    match = re.search(pattern, text)
    if not match:
        return None
    digits = re.search(r"[\d,]+", match.group())
    if not digits:
        return None
    return int(digits.group().replace(",", ""))


def check_python_files(state_text):
    """Count .py files in src/ and compare to documented count."""
    # Supports both old (**Python files:** N) and new (| Python files | N |) formats
    documented = _extract_number(state_text, r"\*\*Python files:\*\*\s*([\d,]+)")
    if documented is None:
        documented = _extract_number(state_text, r"\|\s*Python files\s*\|\s*([\d,]+)")
    actual = len(list((ROOT / "src").rglob("*.py")))
    return "Python files", documented, actual


def check_test_count(state_text):
    """Count test functions and compare to documented count."""
    documented = _extract_number(state_text, r"\*\*Tests:\*\*\s*([\d,]+)")
    if documented is None:
        documented = _extract_number(state_text, r"\|\s*Tests\s*\|\s*([\d,]+)")
    actual = 0
    for f in (ROOT / "tests").rglob("*.py"):
        try:
            content = f.read_text(encoding="utf-8", errors="ignore")
            actual += len(re.findall(r"^\s*def test_", content, re.MULTILINE))
        except Exception:
            pass
    return "Test functions", documented, actual


def check_dashboard_pages(state_text):
    """Count .jsx pages and compare to documented count."""
    documented = _extract_number(state_text, r"\*\*Dashboard pages:\*\*\s*([\d,]+)")
    if documented is None:
        documented = _extract_number(state_text, r"\|\s*Dashboard pages\s*\|\s*([\d,]+)")
    pages_dir = ROOT / "frontend" / "src" / "pages"
    actual = len(list(pages_dir.glob("*.jsx"))) if pages_dir.exists() else 0
    return "Dashboard pages", documented, actual


def check_research_docs(state_text):
    """Count research docs and compare to documented count."""
    documented = _extract_number(state_text, r"\*\*Research docs:\*\*\s*([\d,]+)")
    if documented is None:
        documented = _extract_number(state_text, r"\|\s*Research docs\s*\|\s*([\d,]+)")
    research_dir = ROOT / "docs" / "research"
    actual = len(list(research_dir.glob("*.md"))) if research_dir.exists() else 0
    return "Research docs", documented, actual


def check_test_files(state_text):
    """Count test files and compare to documented count."""
    documented = _extract_number(state_text, r"([\d,]+)\s*test files")
    actual = len(list((ROOT / "tests").rglob("test_*.py")))
    return "Test files", documented, actual


def main():
    if not STATE_FILE.exists():
        print(f"ERROR: {STATE_FILE} not found (expected MASTER.md)")
        sys.exit(1)

    state_text = _read_state()
    checks = [
        check_python_files,
        check_test_count,
        check_test_files,
        check_dashboard_pages,
        check_research_docs,
    ]

    passed = 0
    warned = 0
    skipped = 0

    print("=" * 60)
    print("  Documentation Drift Report")
    print("  Source: MASTER.md")
    print("=" * 60)
    print()

    for check_fn in checks:
        name, documented, actual = check_fn(state_text)
        if documented is None:
            print(f"  SKIP  {name}: not found in MASTER.md")
            skipped += 1
        elif documented == actual:
            print(f"  PASS  {name}: {actual}")
            passed += 1
        else:
            diff = actual - documented
            direction = "+" if diff > 0 else ""
            print(f"  WARN  {name}: documented={documented}, actual={actual} ({direction}{diff})")
            warned += 1

    print()
    print(f"  Results: {passed} passed, {warned} warnings, {skipped} skipped")
    print()

    if warned:
        print("  Update MASTER.md Section 2 to fix warnings.")
        print("  (This is the only file that needs count updates.)")

    return 1 if warned else 0


if __name__ == "__main__":
    sys.exit(main())
