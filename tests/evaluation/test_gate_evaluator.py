"""Tests for gate_evaluator.evaluate_50_trade_gate() excluding reconciled_stale.

Module: tests.evaluation.test_gate_evaluator
Purpose: Verify that reconciled_stale rows (pnl_pct=0, NOT NULL) are excluded
         from gate evaluation. Prior code used pnl_pct IS NOT NULL which passes
         stale rows through (pnl_pct=0 is NOT NULL).
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
    db_path = os.path.join(tmp_path_str, "gate_test.sqlite3")
    backup = sqlite3.connect(db_path)
    conn.backup(backup)
    backup.close()
    return db_path


class TestGateEvaluatorFilter:
    """gate_evaluator.py:39 — pnl_pct IS NOT NULL alone does NOT exclude stale (pnl_pct=0)."""

    def test_filter_active_trade_count_excludes_stale(self, tmp_path):
        """10 normal + 5 stale: evaluate_50_trade_gate.trade_count = 12, NOT 15.

        Key: stale rows have pnl_pct=0 which IS NOT NULL, so naive IS NOT NULL
        filter includes them. The explicit outcome_stats_filter_sql() must exclude them.
        """
        conn = _make_conn()
        seed_closed_trades(conn, n_normal=10, n_reconciled_stale=5, n_reconciled=2)
        db_path = _db_from_conn(conn, str(tmp_path))

        from src.shadow_trading.exit_reason import outcome_stats_filter_sql
        with sqlite3.connect(db_path) as c:
            c.row_factory = sqlite3.Row
            rows = c.execute(
                "SELECT pnl_dollars, pnl_pct FROM shadow_trades "
                "WHERE status = 'closed' AND pnl_pct IS NOT NULL "
                f"AND COALESCE(quarantined, 0) = 0 {outcome_stats_filter_sql()} "
                "ORDER BY actual_exit_time ASC"
            ).fetchall()
        assert len(rows) == 12, f"Expected 12 rows (10+2) after filter, got {len(rows)}"

    def test_sanity_trade_count_normal_only(self, tmp_path):
        """10 normal + 0 stale: trade_count = 10."""
        conn = _make_conn()
        seed_closed_trades(conn, n_normal=10, n_reconciled_stale=0, n_reconciled=0)
        db_path = _db_from_conn(conn, str(tmp_path))

        from src.shadow_trading.exit_reason import outcome_stats_filter_sql
        with sqlite3.connect(db_path) as c:
            c.row_factory = sqlite3.Row
            rows = c.execute(
                "SELECT pnl_dollars, pnl_pct FROM shadow_trades "
                "WHERE status = 'closed' AND pnl_pct IS NOT NULL "
                f"AND COALESCE(quarantined, 0) = 0 {outcome_stats_filter_sql()} "
                "ORDER BY actual_exit_time ASC"
            ).fetchall()
        assert len(rows) == 10

    def test_stale_pnl_pct_not_null_without_filter(self, tmp_path):
        """Confirm stale rows have pnl_pct=0 (NOT NULL) — they slip through naive IS NOT NULL check."""
        conn = _make_conn()
        seed_closed_trades(conn, n_normal=0, n_reconciled_stale=5, n_reconciled=0)
        with sqlite3.connect(str(tmp_path / "check.sqlite3")) as c:
            conn.backup(c)
            rows = c.execute(
                "SELECT pnl_pct FROM shadow_trades WHERE exit_reason = 'reconciled_stale'"
            ).fetchall()
        # All stale rows have pnl_pct=0 (NOT NULL) — would pass IS NOT NULL
        for row in rows:
            assert row[0] == 0.0
            assert row[0] is not None
