"""Tests for build_score _compute_phase_progress() excluding reconciled_stale.

Module: tests.evaluation.test_build_score
Purpose: Verify that the 50-trade gate progress counter in build_score.py
         excludes reconciled_stale rows from the closed trade count.
Called by: pytest
Owns tables: none
Config keys: none
"""

import sqlite3
import os

import pytest

from tests._helpers.seed_closed_trades import seed_closed_trades, _make_conn


def _db_from_conn(conn: sqlite3.Connection, tmp_path_str: str) -> str:
    """Write in-memory DB to a temp file and return path."""
    db_path = os.path.join(tmp_path_str, "build_score_test.sqlite3")
    backup = sqlite3.connect(db_path)
    conn.backup(backup)
    backup.close()
    return db_path


class TestBuildScorePhaseProgress:
    """build_score.py:296 — 50-trade gate progress counter excludes reconciled_stale."""

    def test_filter_active_progress_counter_excludes_stale(self, tmp_path):
        """10 normal + 5 stale: progress counter = 10, NOT 15."""
        conn = _make_conn()
        seed_closed_trades(conn, n_normal=10, n_reconciled_stale=5, n_reconciled=2)
        db_path = _db_from_conn(conn, str(tmp_path))

        from src.shadow_trading.exit_reason import outcome_stats_filter_sql
        with sqlite3.connect(db_path) as c:
            c.row_factory = sqlite3.Row
            cur = c.execute(
                "SELECT COUNT(*) FROM shadow_trades WHERE status = 'closed'"
                f" AND COALESCE(quarantined, 0) = 0 {outcome_stats_filter_sql()}"
            )
            closed = cur.fetchone()[0] or 0
        assert closed == 12, f"Expected 12 (10+2), got {closed}"

    def test_sanity_progress_counter_normal_only(self, tmp_path):
        """10 normal + 0 stale: progress counter = 10."""
        conn = _make_conn()
        seed_closed_trades(conn, n_normal=10, n_reconciled_stale=0, n_reconciled=0)
        db_path = _db_from_conn(conn, str(tmp_path))

        from src.shadow_trading.exit_reason import outcome_stats_filter_sql
        with sqlite3.connect(db_path) as c:
            c.row_factory = sqlite3.Row
            cur = c.execute(
                "SELECT COUNT(*) FROM shadow_trades WHERE status = 'closed'"
                f" AND COALESCE(quarantined, 0) = 0 {outcome_stats_filter_sql()}"
            )
            closed = cur.fetchone()[0] or 0
        assert closed == 10
