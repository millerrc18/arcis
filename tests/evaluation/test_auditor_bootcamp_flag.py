"""Tests for auditor bootcamp_mode flag excluding reconciled_stale.

Module: tests.evaluation.test_auditor_bootcamp_flag
Purpose: Verify that the bootcamp_mode gate counter in auditor.py excludes
         reconciled_stale rows, so the 50-trade threshold reflects real trades.
Called by: pytest
Owns tables: none
Config keys: none
"""

import sqlite3
import tempfile
import os

import pytest

from tests._helpers.seed_closed_trades import seed_closed_trades, _make_conn, _CREATE_SHADOW_TRADES


def _db_from_conn(conn: sqlite3.Connection, tmp_path_str: str) -> str:
    """Write in-memory DB to a temp file and return path."""
    db_path = os.path.join(tmp_path_str, "test.sqlite3")
    backup = sqlite3.connect(db_path)
    conn.backup(backup)
    backup.close()
    return db_path


class TestAuditorBootcampFlag:
    """auditor.py:266 — bootcamp_mode gate excludes reconciled_stale."""

    def test_filter_active_still_bootcamp_when_stale_would_push_over(self, tmp_path):
        """49 normal + 5 stale = 54 total, but filter gives 49: still bootcamp."""
        conn = _make_conn()
        seed_closed_trades(conn, n_normal=49, n_reconciled_stale=5, n_reconciled=0)
        db_path = _db_from_conn(conn, str(tmp_path))

        from src.shadow_trading.exit_reason import outcome_stats_filter_sql
        with sqlite3.connect(db_path) as c:
            c.row_factory = sqlite3.Row
            row = c.execute(
                "SELECT COUNT(*) as c FROM shadow_trades WHERE status = 'closed'"
                f" AND COALESCE(quarantined, 0) = 0 {outcome_stats_filter_sql()}"
            ).fetchone()
            closed_count = row[0] if row else 0
        bootcamp_mode = closed_count < 50
        assert bootcamp_mode is True, (
            f"Expected bootcamp_mode=True with 49 real trades, got closed_count={closed_count}"
        )

    def test_filter_active_not_bootcamp_with_50_real_trades(self, tmp_path):
        """50 normal + 0 stale = 50 real trades: NOT bootcamp."""
        conn = _make_conn()
        seed_closed_trades(conn, n_normal=50, n_reconciled_stale=0, n_reconciled=0)
        db_path = _db_from_conn(conn, str(tmp_path))

        from src.shadow_trading.exit_reason import outcome_stats_filter_sql
        with sqlite3.connect(db_path) as c:
            c.row_factory = sqlite3.Row
            row = c.execute(
                "SELECT COUNT(*) as c FROM shadow_trades WHERE status = 'closed'"
                f" AND COALESCE(quarantined, 0) = 0 {outcome_stats_filter_sql()}"
            ).fetchone()
            closed_count = row[0] if row else 0
        bootcamp_mode = closed_count < 50
        assert bootcamp_mode is False, (
            f"Expected bootcamp_mode=False with 50 real trades, got closed_count={closed_count}"
        )
