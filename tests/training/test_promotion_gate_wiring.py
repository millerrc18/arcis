"""Tests for the promotion_gate wiring into the post-train flow.

Verifies that after run_fine_tune() completes:
  - The gate fires automatically
  - model_versions.status transitions to 'promoted' on a gate pass
  - model_versions.status transitions to 'rejected_by_gate' on a gate fail
  - The CLI subcommand cmd_run_promotion_gate exists and can be called
  - The CLI subcommand updates status against an existing version

Sprint 1.B Wave B (#49)
"""
from __future__ import annotations

import os
import sqlite3
import tempfile
import uuid
from unittest.mock import MagicMock, patch

from src.training.versioning import init_training_tables


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _tmp_db() -> str:
    fd, path = tempfile.mkstemp(suffix=".sqlite3")
    os.close(fd)
    return path


def _get_version_status(db_path: str, version_id: str) -> str | None:
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT status FROM model_versions WHERE version_id = ?", (version_id,)
        ).fetchone()
    return row[0] if row else None


PROMOTE_RESULT = {
    "decision": "promote",
    "votes": {},
    "n_obs": 100,
    "mintrl": 50,
    "details": {"n_pass": 4, "n_fail": 1, "n_abstentions": 0},
}
REJECT_RESULT = {
    "decision": "reject",
    "votes": {},
    "n_obs": 100,
    "mintrl": 50,
    "details": {"n_pass": 2, "n_fail": 3, "n_abstentions": 0},
}
DEFER_RESULT = {
    "decision": "defer",
    "votes": {},
    "n_obs": 5,
    "mintrl": 50,
    "details": {"n_pass": 0, "n_fail": 0, "n_abstentions": 0},
}


def _insert_version(db_path: str, version_name: str = "halcyon-v1.0.0", status: str = "active") -> str:
    init_training_tables(db_path)
    version_id = str(uuid.uuid4())
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """INSERT INTO model_versions
               (version_id, version_name, created_at, training_examples_count,
                synthetic_examples_count, outcome_examples_count,
                model_file_path, status)
               VALUES (?, ?, datetime('now'), 10, 0, 0, 'test.gguf', ?)""",
            (version_id, version_name, status),
        )
        conn.commit()
    return version_id


# ---------------------------------------------------------------------------
# Test: run_promotion_gate_for_version records 'promoted' on pass
# ---------------------------------------------------------------------------

def test_post_train_runs_gate_synthetic_pass():
    """A promote decision sets status='promoted'."""
    db = _tmp_db()
    version_id = _insert_version(db)

    with patch("src.training.trainer.promotion_gate", return_value=PROMOTE_RESULT), \
         patch("src.training.trainer._resolve_returns_for_gate", return_value=[0.01] * 50):
        from src.training.trainer import run_promotion_gate_for_version
        run_promotion_gate_for_version(
            version_id=version_id,
            version_name="halcyon-v1.0.0",
            db_path=db,
        )

    status = _get_version_status(db, version_id)
    assert status == "promoted", f"Expected 'promoted', got {status!r}"


def test_post_train_runs_gate_synthetic_fail():
    """A reject decision sets status='rejected_by_gate'."""
    db = _tmp_db()
    version_id = _insert_version(db)

    with patch("src.training.trainer.promotion_gate", return_value=REJECT_RESULT), \
         patch("src.training.trainer._resolve_returns_for_gate", return_value=[0.01] * 50):
        from src.training.trainer import run_promotion_gate_for_version
        run_promotion_gate_for_version(
            version_id=version_id,
            version_name="halcyon-v1.0.0",
            db_path=db,
        )

    status = _get_version_status(db, version_id)
    assert status == "rejected_by_gate", f"Expected 'rejected_by_gate', got {status!r}"


def test_post_train_runs_gate_defer_sets_pending_review():
    """A defer decision sets status='pending_review'."""
    db = _tmp_db()
    version_id = _insert_version(db)

    with patch("src.training.trainer.promotion_gate", return_value=DEFER_RESULT), \
         patch("src.training.trainer._resolve_returns_for_gate", return_value=[0.01] * 5):
        from src.training.trainer import run_promotion_gate_for_version
        run_promotion_gate_for_version(
            version_id=version_id,
            version_name="halcyon-v1.0.0",
            db_path=db,
        )

    status = _get_version_status(db, version_id)
    assert status == "pending_review", f"Expected 'pending_review', got {status!r}"


def test_post_train_gate_no_returns_skips_gate():
    """When no returns are available, gate is skipped and status unchanged."""
    db = _tmp_db()
    version_id = _insert_version(db)

    with patch("src.training.trainer._resolve_returns_for_gate", return_value=[]):
        from src.training.trainer import run_promotion_gate_for_version
        result = run_promotion_gate_for_version(
            version_id=version_id,
            version_name="halcyon-v1.0.0",
            db_path=db,
        )

    assert result["decision"] == "skipped"
    status = _get_version_status(db, version_id)
    assert status == "active", f"Status should remain 'active' when no returns, got {status!r}"


# ---------------------------------------------------------------------------
# Test: CLI subcommand exists and is callable
# ---------------------------------------------------------------------------

def test_cmd_run_promotion_gate_exists():
    """cmd_run_promotion_gate is importable from src.cli.commands."""
    from src.cli.commands import cmd_run_promotion_gate
    assert callable(cmd_run_promotion_gate)


def test_cmd_run_promotion_gate_calls_underlying_fn():
    """cmd_run_promotion_gate calls run_promotion_gate_for_version."""
    db = _tmp_db()
    version_id = _insert_version(db, version_name="halcyon-test-v1")

    from src.cli.commands import cmd_run_promotion_gate

    args = MagicMock()
    args.version_name = "halcyon-test-v1"
    args.n_trials = 1

    with patch("src.cli.commands.DB_PATH", db), \
         patch("src.training.trainer.promotion_gate", return_value=PROMOTE_RESULT), \
         patch("src.training.trainer._resolve_returns_for_gate", return_value=[0.01] * 50):
        cmd_run_promotion_gate(args)

    status = _get_version_status(db, version_id)
    assert status == "promoted", f"Expected 'promoted' after CLI call, got {status!r}"


def test_main_run_promotion_gate_subcommand():
    """python -m src.main run-promotion-gate --help exits 0 and mentions version arg."""
    import subprocess
    import sys
    result = subprocess.run(
        [sys.executable, "-m", "src.main", "run-promotion-gate", "--help"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, f"Exit code {result.returncode}: {result.stderr}"
    combined = result.stdout + result.stderr
    assert "version" in combined.lower(), \
        f"Help text should mention version argument: {combined}"
