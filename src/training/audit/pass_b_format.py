"""Pass B — format drift detector (stub; real implementation in commit 5).

The stub returns no decisions so Commit 4 tests for Pass A can exercise
the full run_audit() pipeline without needing Pass B logic yet.

Called by: src.training.audit.core
Calls: src.training.audit.taxonomy
Owns tables: none
Tests: tests/training/test_pass_b.py (added in commit 5)
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PassBDecision:
    example_id: str
    quarantine: bool
    reason_code: str | None


def run_pass_b(rows: list[dict]) -> list[PassBDecision]:
    """Stub — replaced in commit 5 with real XML + label drift checks."""
    return []
