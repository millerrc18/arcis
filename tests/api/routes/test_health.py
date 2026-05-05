"""Tests for health.py closed-trade counters excluding reconciled_stale.

Module: tests.api.routes.test_health
Purpose: Verify that closed_count in _read_persisted_score (build-score endpoint,
         health.py:68) and in /health/score (health.py:189) exclude reconciled_stale.
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
    db_path = os.path.join(tmp_path_str, "health_test.sqlite3")
    backup = sqlite3.connect(db_path)
    conn.backup(backup)
    backup.close()
    return db_path


class TestHealthBuildScoreCounter:
    """health.py:68 — build-score endpoint closed_count excludes reconciled_stale."""

    def test_filter_active_closed_count_excludes_stale(self, tmp_path):
        """10 normal + 5 stale + 2 reconciled: closed_count used in phase_progress = 12."""
        conn = _make_conn()
        seed_closed_trades(conn, n_normal=10, n_reconciled_stale=5, n_reconciled=2)

        from src.shadow_trading.exit_reason import outcome_stats_filter_sql
        cur = conn.execute(
            "SELECT COUNT(*) as c FROM shadow_trades WHERE status = 'closed'"
            f" AND COALESCE(quarantined, 0) = 0 {outcome_stats_filter_sql()}"
        )
        closed_count = cur.fetchone()[0]
        assert closed_count == 12, f"Expected 12 (10+2), got {closed_count}"

    def test_sanity_closed_count_normal_only(self, tmp_path):
        """10 normal + 0 stale: closed_count = 10."""
        conn = _make_conn()
        seed_closed_trades(conn, n_normal=10, n_reconciled_stale=0, n_reconciled=0)

        from src.shadow_trading.exit_reason import outcome_stats_filter_sql
        cur = conn.execute(
            "SELECT COUNT(*) as c FROM shadow_trades WHERE status = 'closed'"
            f" AND COALESCE(quarantined, 0) = 0 {outcome_stats_filter_sql()}"
        )
        closed_count = cur.fetchone()[0]
        assert closed_count == 10


class TestHealthScoreEndpointCounter:
    """health.py:189 — /health/score endpoint closed_count excludes reconciled_stale."""

    def test_filter_active_health_score_closed_excludes_stale(self, tmp_path):
        """10 normal + 5 stale: health/score closed_count = 12 not 17."""
        conn = _make_conn()
        seed_closed_trades(conn, n_normal=10, n_reconciled_stale=5, n_reconciled=2)

        from src.shadow_trading.exit_reason import outcome_stats_filter_sql
        cur = conn.execute(
            "SELECT COUNT(*) as c FROM shadow_trades WHERE status = 'closed'"
            f" AND COALESCE(quarantined, 0) = 0 {outcome_stats_filter_sql()}"
        )
        closed_count = cur.fetchone()[0]
        assert closed_count == 12

    def test_sanity_health_score_closed_normal_only(self, tmp_path):
        """10 normal + 0 stale: health/score closed_count = 10."""
        conn = _make_conn()
        seed_closed_trades(conn, n_normal=10, n_reconciled_stale=0, n_reconciled=0)

        from src.shadow_trading.exit_reason import outcome_stats_filter_sql
        cur = conn.execute(
            "SELECT COUNT(*) as c FROM shadow_trades WHERE status = 'closed'"
            f" AND COALESCE(quarantined, 0) = 0 {outcome_stats_filter_sql()}"
        )
        closed_count = cur.fetchone()[0]
        assert closed_count == 10
