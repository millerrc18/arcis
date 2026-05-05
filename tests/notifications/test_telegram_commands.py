"""Tests for telegram_commands.py closed-trade counters excluding reconciled_stale.

Module: tests.notifications.test_telegram_commands
Purpose: Verify that the three closed-trade query sites in telegram_commands.py
         (milestone counter at :126, closed P&L win_rate at :425, live closed at :438)
         exclude reconciled_stale rows.
Called by: pytest
Owns tables: none
Config keys: none
"""

import sqlite3

import pytest

from tests._helpers.seed_closed_trades import seed_closed_trades, _make_conn


class TestTelegramMilestoneCounter:
    """telegram_commands.py:126 — milestone counter excludes reconciled_stale."""

    def test_filter_active_milestone_excludes_stale(self):
        """10 normal + 5 stale: milestone counter sees 12, NOT 17."""
        conn = _make_conn()
        seed_closed_trades(conn, n_normal=10, n_reconciled_stale=5, n_reconciled=2)
        conn.row_factory = sqlite3.Row

        from src.shadow_trading.exit_reason import outcome_stats_filter_sql
        closed = conn.execute(
            "SELECT COUNT(*) as c FROM shadow_trades WHERE status = 'closed'"
            f" AND COALESCE(quarantined, 0) = 0 {outcome_stats_filter_sql()}"
        ).fetchone()
        closed_count = closed["c"] if closed else 0
        assert closed_count == 12

    def test_sanity_milestone_counter_normal_only(self):
        """10 normal + 0 stale: milestone counter sees 10."""
        conn = _make_conn()
        seed_closed_trades(conn, n_normal=10, n_reconciled_stale=0, n_reconciled=0)
        conn.row_factory = sqlite3.Row

        from src.shadow_trading.exit_reason import outcome_stats_filter_sql
        closed = conn.execute(
            "SELECT COUNT(*) as c FROM shadow_trades WHERE status = 'closed'"
            f" AND COALESCE(quarantined, 0) = 0 {outcome_stats_filter_sql()}"
        ).fetchone()
        closed_count = closed["c"] if closed else 0
        assert closed_count == 10


class TestTelegramClosedPnlWinRate:
    """telegram_commands.py:425 — closed P&L win_rate excludes reconciled_stale."""

    def test_filter_active_win_rate_excludes_stale(self):
        """10 normal (pnl>0) + 5 stale (pnl=0): win_rate with filter = 1.0 (all included are winners)."""
        conn = _make_conn()
        seed_closed_trades(conn, n_normal=10, n_reconciled_stale=5, n_reconciled=2)
        conn.row_factory = sqlite3.Row

        from src.shadow_trading.exit_reason import outcome_stats_filter_sql
        closed_row = conn.execute(
            "SELECT COUNT(*) as cnt, COALESCE(SUM(pnl_dollars), 0) as total_pnl,"
            " COALESCE(AVG(CASE WHEN pnl_dollars > 0 THEN 1.0 ELSE 0.0 END), 0) as win_rate"
            " FROM shadow_trades WHERE status = 'closed'"
            f" AND COALESCE(quarantined, 0) = 0 {outcome_stats_filter_sql()}"
        ).fetchone()
        assert closed_row["cnt"] == 12
        # All 10 normal + 2 reconciled have pnl > 0 → win_rate = 1.0
        assert abs(closed_row["win_rate"] - 1.0) < 0.01

    def test_sanity_win_rate_normal_only(self):
        """10 normal + 0 stale: cnt=10, win_rate=1.0."""
        conn = _make_conn()
        seed_closed_trades(conn, n_normal=10, n_reconciled_stale=0, n_reconciled=0)
        conn.row_factory = sqlite3.Row

        from src.shadow_trading.exit_reason import outcome_stats_filter_sql
        closed_row = conn.execute(
            "SELECT COUNT(*) as cnt, COALESCE(SUM(pnl_dollars), 0) as total_pnl,"
            " COALESCE(AVG(CASE WHEN pnl_dollars > 0 THEN 1.0 ELSE 0.0 END), 0) as win_rate"
            " FROM shadow_trades WHERE status = 'closed'"
            f" AND COALESCE(quarantined, 0) = 0 {outcome_stats_filter_sql()}"
        ).fetchone()
        assert closed_row["cnt"] == 10
        assert abs(closed_row["win_rate"] - 1.0) < 0.01


class TestTelegramLiveClosedPnl:
    """telegram_commands.py:438 — live closed P&L excludes reconciled_stale."""

    def test_filter_active_live_closed_excludes_stale(self):
        """Seed live trades: 10 normal + 5 stale. Filtered live_closed = 12."""
        conn = _make_conn()
        # Seed all as 'live' source
        seed_closed_trades(conn, n_normal=10, n_reconciled_stale=5, n_reconciled=2)
        # Update source to 'live'
        conn.execute("UPDATE shadow_trades SET source = 'live'")
        conn.commit()
        conn.row_factory = sqlite3.Row

        from src.shadow_trading.exit_reason import outcome_stats_filter_sql
        live_closed = conn.execute(
            "SELECT COUNT(*) as cnt, COALESCE(SUM(pnl_dollars), 0) as total_pnl,"
            " COALESCE(AVG(CASE WHEN pnl_dollars > 0 THEN 1.0 ELSE 0.0 END), 0) as win_rate"
            " FROM shadow_trades WHERE status = 'closed' AND source = 'live'"
            f" AND COALESCE(quarantined, 0) = 0 {outcome_stats_filter_sql()}"
        ).fetchone()
        assert live_closed["cnt"] == 12

    def test_sanity_live_closed_normal_only(self):
        """10 live normal + 0 stale: live_closed.cnt = 10."""
        conn = _make_conn()
        seed_closed_trades(conn, n_normal=10, n_reconciled_stale=0, n_reconciled=0)
        conn.execute("UPDATE shadow_trades SET source = 'live'")
        conn.commit()
        conn.row_factory = sqlite3.Row

        from src.shadow_trading.exit_reason import outcome_stats_filter_sql
        live_closed = conn.execute(
            "SELECT COUNT(*) as cnt, COALESCE(SUM(pnl_dollars), 0) as total_pnl,"
            " COALESCE(AVG(CASE WHEN pnl_dollars > 0 THEN 1.0 ELSE 0.0 END), 0) as win_rate"
            " FROM shadow_trades WHERE status = 'closed' AND source = 'live'"
            f" AND COALESCE(quarantined, 0) = 0 {outcome_stats_filter_sql()}"
        ).fetchone()
        assert live_closed["cnt"] == 10
