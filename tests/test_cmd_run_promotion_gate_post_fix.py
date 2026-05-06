"""T3 regression tests: CLI cmd_run_promotion_gate post-fix behavior.

DA major fix 6: CLI path transitively receives dates+directions kwargs after
the trainer.py:1039 fix. Tests verify:
- cmd_run_promotion_gate end-to-end produces a deterministic FAIL outcome
  (Choice A — long-only system cannot promote)
- kwargs flow through from cmd_run_promotion_gate → run_promotion_gate_for_version
  → promotion_gate

Sprint 2 T3 — spec §1.3.1, DA major fix 6.
"""
from __future__ import annotations

import os
import sqlite3
import tempfile
import uuid
from datetime import date
from unittest.mock import MagicMock, patch

from src.training.versioning import init_training_tables


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _tmp_db() -> str:
    fd, path = tempfile.mkstemp(suffix=".sqlite3")
    os.close(fd)
    return path


def _insert_version(db_path: str, version_name: str = "cli-test-v1") -> str:
    init_training_tables(db_path)
    version_id = str(uuid.uuid4())
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """INSERT INTO model_versions
               (version_id, version_name, created_at, training_examples_count,
                synthetic_examples_count, outcome_examples_count,
                model_file_path, status)
               VALUES (?, ?, datetime('now'), 10, 0, 0, 'test.gguf', 'active')""",
            (version_id, version_name),
        )
        conn.commit()
    return version_id


def _seed_shadow_trade(
    db_path: str,
    pnl_pct: float,
    actual_entry_time: str,
    status: str = "closed",
) -> None:
    from src.journal.store import initialize_database
    initialize_database(db_path)
    trade_id = str(uuid.uuid4())
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """INSERT INTO shadow_trades
               (trade_id, ticker, status, pnl_pct, actual_entry_time, created_at, updated_at)
               VALUES (?, 'AAPL', ?, ?, ?, datetime('now'), datetime('now'))""",
            (trade_id, status, pnl_pct, actual_entry_time),
        )
        conn.commit()


# ---------------------------------------------------------------------------
# Test: CLI end-to-end produces FAIL outcome (Choice A regression-lock)
# ---------------------------------------------------------------------------

def test_cmd_run_promotion_gate_post_fix_behavior():
    """cmd_run_promotion_gate with healthy returns must produce reject or defer (not promote).

    Choice A: long-only system cannot promote because MC-perm always fails (p=1.0).
    This test exercises the full CLI → trainer path end-to-end without mocking
    the gate itself.
    """
    db = _tmp_db()
    _insert_version(db, "cli-test-v1")

    # Seed enough healthy returns with valid timestamps
    for i in range(60):
        _seed_shadow_trade(db, 3.5, f"2024-02-{(i % 28) + 1:02d}T10:00:00")

    from src.cli.commands import cmd_run_promotion_gate

    args = MagicMock()
    args.version_name = "cli-test-v1"
    args.n_trials = 1

    with patch("src.cli.commands.DB_PATH", db):
        cmd_run_promotion_gate(args)

    # Verify status is NOT 'promoted'
    with sqlite3.connect(db) as conn:
        row = conn.execute(
            "SELECT status FROM model_versions WHERE version_name = ?",
            ("cli-test-v1",)
        ).fetchone()

    status = row[0] if row else None
    assert status in {"rejected_by_gate", "pending_review"}, (
        f"Choice A violation: CLI path must produce reject/defer, not promote. "
        f"Got status={status!r}"
    )


# ---------------------------------------------------------------------------
# Test: dates+directions flow through from CLI → trainer → promotion_gate
# ---------------------------------------------------------------------------

def test_cmd_run_promotion_gate_passes_dates_directions():
    """dates= and directions= kwargs must flow through CLI → run_promotion_gate_for_version → promotion_gate."""
    db = _tmp_db()
    _insert_version(db, "cli-kwargs-v1")

    entry_time = "2024-05-15T09:30:00"
    _seed_shadow_trade(db, 2.0, entry_time)

    expected_date = date.fromisoformat(entry_time[:10])
    captured_kwargs = {}

    def mock_gate(returns, n_trials, **kwargs):
        captured_kwargs.update(kwargs)
        return {
            "decision": "reject",
            "votes": {
                "cpcv": False,
                "block_bootstrap": False,
                "mc_perm": False,
                "psr_dsr": False,
                "white_rc": None,
            },
            "n_obs": len(returns),
            "mintrl": 50,
            "details": {"n_pass": 0, "n_fail": 4, "n_abstentions": 1},
        }

    from src.cli.commands import cmd_run_promotion_gate

    args = MagicMock()
    args.version_name = "cli-kwargs-v1"
    args.n_trials = 1

    with patch("src.cli.commands.DB_PATH", db), \
         patch("src.training.trainer.promotion_gate", side_effect=mock_gate):
        cmd_run_promotion_gate(args)

    assert "dates" in captured_kwargs, (
        "dates= not received by promotion_gate via CLI path. "
        "Transitive fix from trainer.py:1039 did not propagate."
    )
    assert "directions" in captured_kwargs, (
        "directions= not received by promotion_gate via CLI path."
    )
    assert captured_kwargs["dates"] == [expected_date], (
        f"Expected dates=[{expected_date!r}], got {captured_kwargs['dates']!r}"
    )
    assert captured_kwargs["directions"] == [1], (
        f"Expected directions=[1], got {captured_kwargs['directions']!r}"
    )
