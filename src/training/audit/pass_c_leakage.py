"""Pass C — TF-IDF leakage detector (stub; real implementation in commit 6).

The stub returns None accuracy so Commit 4 tests for Pass A can
exercise run_audit() without needing the real detector yet.

Called by: src.training.audit.core
Calls: src.training.leakage_detector (real implementation; commit 6)
Owns tables: none
Tests: tests/training/test_pass_c.py (added in commit 6)
"""
from __future__ import annotations


def run_pass_c(rows: list[dict], *, db_path: str) -> dict:
    """Stub — replaced in commit 6 with real TF-IDF leakage probe."""
    _ = rows, db_path
    return {
        "balanced_accuracy": None,
        "majority_baseline": None,
        "n_examples": 0,
        "suspect_example_ids": [],
    }
