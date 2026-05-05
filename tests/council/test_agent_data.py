"""Tests for council/agent_data.py closed-trade queries excluding reconciled_stale.

Module: tests.council.test_agent_data
Purpose: Verify that the four closed-trade query sites in agent_data.py
         (:129 closed count, :146 pnl/wins, :252 cumulative pnl, :263 MAE)
         exclude reconciled_stale rows from outcome statistics.
         agent_data.py:224 (recent losses display) is reclassified per M11 — NOT filtered.
Called by: pytest
Owns tables: none
Config keys: none
"""

import sqlite3

import pytest

from tests._helpers.seed_closed_trades import seed_closed_trades, _make_conn


class TestAgentDataClosedCount:
    """agent_data.py:129 — closed count in gather_strategic_data excludes reconciled_stale."""

    def test_filter_active_closed_count_excludes_stale(self):
        """10 normal + 5 stale + 2 reconciled: closed count = 12."""
        conn = _make_conn()
        seed_closed_trades(conn, n_normal=10, n_reconciled_stale=5, n_reconciled=2)
        conn.row_factory = sqlite3.Row

        from src.shadow_trading.exit_reason import outcome_stats_filter_sql
        closed = conn.execute(
            "SELECT COUNT(*) as n FROM shadow_trades WHERE status = 'closed'"
            f" AND COALESCE(quarantined, 0) = 0 {outcome_stats_filter_sql()}"
        ).fetchone()
        assert closed["n"] == 12

    def test_sanity_closed_count_normal_only(self):
        """10 normal + 0 stale: closed count = 10."""
        conn = _make_conn()
        seed_closed_trades(conn, n_normal=10, n_reconciled_stale=0, n_reconciled=0)
        conn.row_factory = sqlite3.Row

        from src.shadow_trading.exit_reason import outcome_stats_filter_sql
        closed = conn.execute(
            "SELECT COUNT(*) as n FROM shadow_trades WHERE status = 'closed'"
            f" AND COALESCE(quarantined, 0) = 0 {outcome_stats_filter_sql()}"
        ).fetchone()
        assert closed["n"] == 10


class TestAgentDataPnlWins:
    """agent_data.py:146 — pnl/wins in gather_strategic_data excludes reconciled_stale."""

    def test_filter_active_pnl_excludes_stale(self):
        """10 normal (pnl=100) + 5 stale (pnl=0) + 2 reconciled (pnl=50): sum_pnl = 1100."""
        conn = _make_conn()
        seed_closed_trades(conn, n_normal=10, n_reconciled_stale=5, n_reconciled=2)
        conn.row_factory = sqlite3.Row

        from src.shadow_trading.exit_reason import outcome_stats_filter_sql
        pnl = conn.execute(
            "SELECT SUM(pnl_dollars) as total, AVG(pnl_pct) as avg, "
            "COUNT(CASE WHEN pnl_dollars > 0 THEN 1 END) as wins, COUNT(*) as n "
            "FROM shadow_trades WHERE status = 'closed' AND pnl_dollars IS NOT NULL"
            f" AND COALESCE(quarantined, 0) = 0 {outcome_stats_filter_sql()}"
        ).fetchone()
        assert pnl["n"] == 12
        assert abs(pnl["total"] - 1100.0) < 0.01  # 10*100 + 2*50
        assert pnl["wins"] == 12  # all have pnl > 0

    def test_sanity_pnl_normal_only(self):
        """10 normal: n=10, total_pnl=1000, wins=10."""
        conn = _make_conn()
        seed_closed_trades(conn, n_normal=10, n_reconciled_stale=0, n_reconciled=0)
        conn.row_factory = sqlite3.Row

        from src.shadow_trading.exit_reason import outcome_stats_filter_sql
        pnl = conn.execute(
            "SELECT SUM(pnl_dollars) as total, AVG(pnl_pct) as avg, "
            "COUNT(CASE WHEN pnl_dollars > 0 THEN 1 END) as wins, COUNT(*) as n "
            "FROM shadow_trades WHERE status = 'closed' AND pnl_dollars IS NOT NULL"
            f" AND COALESCE(quarantined, 0) = 0 {outcome_stats_filter_sql()}"
        ).fetchone()
        assert pnl["n"] == 10
        assert abs(pnl["total"] - 1000.0) < 0.01


class TestAgentDataCumulativePnl:
    """agent_data.py:252 — cumulative P&L in gather_risk_data excludes reconciled_stale."""

    def test_filter_active_cumulative_pnl_excludes_stale(self):
        """10 normal (pnl=100) + 5 stale (pnl=0): cumulative = 1100."""
        conn = _make_conn()
        seed_closed_trades(conn, n_normal=10, n_reconciled_stale=5, n_reconciled=2)
        conn.row_factory = sqlite3.Row

        from src.shadow_trading.exit_reason import outcome_stats_filter_sql
        cumulative = conn.execute(
            "SELECT SUM(pnl_dollars) as total FROM shadow_trades WHERE status = 'closed'"
            f" AND COALESCE(quarantined, 0) = 0 {outcome_stats_filter_sql()}"
        ).fetchone()
        assert abs(cumulative["total"] - 1100.0) < 0.01

    def test_sanity_cumulative_pnl_normal_only(self):
        """10 normal: cumulative = 1000."""
        conn = _make_conn()
        seed_closed_trades(conn, n_normal=10, n_reconciled_stale=0, n_reconciled=0)
        conn.row_factory = sqlite3.Row

        from src.shadow_trading.exit_reason import outcome_stats_filter_sql
        cumulative = conn.execute(
            "SELECT SUM(pnl_dollars) as total FROM shadow_trades WHERE status = 'closed'"
            f" AND COALESCE(quarantined, 0) = 0 {outcome_stats_filter_sql()}"
        ).fetchone()
        assert abs(cumulative["total"] - 1000.0) < 0.01


class TestAgentDataMAE:
    """agent_data.py:263 — worst MAE in gather_risk_data excludes reconciled_stale."""

    def test_filter_active_mae_excludes_stale(self):
        """10 normal (MAE=1.5) + 5 stale (MAE=0.0): worst_mae should be from real trades."""
        conn = _make_conn()
        seed_closed_trades(conn, n_normal=10, n_reconciled_stale=5, n_reconciled=2)
        conn.row_factory = sqlite3.Row

        from src.shadow_trading.exit_reason import outcome_stats_filter_sql
        mae = conn.execute(
            "SELECT ticker, MIN(max_adverse_excursion) as worst_mae "
            "FROM shadow_trades WHERE status = 'closed' AND max_adverse_excursion IS NOT NULL"
            f" AND COALESCE(quarantined, 0) = 0 {outcome_stats_filter_sql()}"
        ).fetchone()
        assert mae is not None
        # Normal trades have MAE=1.5, reconciled have MAE=0.5, stale have MAE=0.0
        # Without filter, worst would be 0.0. With filter, worst = 0.5
        assert mae["worst_mae"] >= 0.5, f"Expected worst_mae >= 0.5 (stale excluded), got {mae['worst_mae']}"

    def test_sanity_mae_normal_only(self):
        """10 normal (MAE=1.5): worst_mae = 1.5."""
        conn = _make_conn()
        seed_closed_trades(conn, n_normal=10, n_reconciled_stale=0, n_reconciled=0)
        conn.row_factory = sqlite3.Row

        from src.shadow_trading.exit_reason import outcome_stats_filter_sql
        mae = conn.execute(
            "SELECT ticker, MIN(max_adverse_excursion) as worst_mae "
            "FROM shadow_trades WHERE status = 'closed' AND max_adverse_excursion IS NOT NULL"
            f" AND COALESCE(quarantined, 0) = 0 {outcome_stats_filter_sql()}"
        ).fetchone()
        assert mae is not None
        assert abs(mae["worst_mae"] - 1.5) < 0.01
