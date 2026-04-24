"""Regression guards for Tier 1.5 hygiene fixes.

Each test prevents a hygiene regression from re-emerging. Tier 1.5 covers
documentation accuracy (CLAUDE.md test count), operator-safety defaults
(cleanup script --dry-run), UI conditional rendering, packet-builder
defensive defaults, route-layer connect_db migration, and helper test
coverage.
"""

from __future__ import annotations

import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# CLAUDE.md test-count baseline must reflect the current sweep size
# ---------------------------------------------------------------------------


def test_claude_md_test_count_baseline_is_current():
    """CLAUDE.md publishes a "Test count must not drop" baseline used as a
    rule-of-thumb for code review. When the actual sweep grows past the
    baseline, the number must be bumped — otherwise the rule loses bite
    (a PR could halve the test count and still satisfy "above baseline").

    This test asserts the baseline is at least the prior known sweep
    (2897 from PR #639). It does NOT auto-detect because the goal is
    "operator notices and bumps consciously" — auto-detection would
    silently follow regressions down."""
    claude_md = _read("CLAUDE.md")
    match = re.search(r"minimum of (\d+) tests", claude_md)
    assert match, "CLAUDE.md must declare a 'minimum of N tests' baseline"
    declared = int(match.group(1))
    assert declared >= 2897, (
        f"CLAUDE.md baseline ({declared}) is below the 2026-04-24 sweep size "
        f"of 2897 (PR #639). Bump the number in CLAUDE.md."
    )
