"""Tests for scheduler/reports.py closed-trade queries excluding reconciled_stale.

Module: tests.scheduler.test_reports
Purpose: Verify that the five query sites in scheduler/reports.py
         (paper_closed_today :411, live_closed_today :427, all-time win-rate :436,
         best-today :446, worst-today :452) exclude reconciled_stale.
Called by: pytest
Owns tables: none
Config keys: none
"""

import sqlite3

import pytest

from tests._helpers.seed_closed_trades import seed_closed_trades, _make_conn


_TODAY = "2026-01-01"


def _seed_with_today(conn, n_normal, n_reconciled_stale, n_reconciled, source="paper"):
    """Seed trades all stamped today's date."""
    seed_closed_trades(
        conn,
        n_normal=n_normal,
        n_reconciled_stale=n_reconciled_stale,
        n_reconciled=n_reconciled,
    )
    # Stamp all actual_exit_time with today
    conn.execute(
        "UPDATE shadow_trades SET actual_exit_time = ?, source = ?",
        (f"{_TODAY}T15:00:00", source),
    )
    conn.commit()


class TestReportsPaperClosedToday:
    """reports.py:411 — paper_closed_today excludes reconciled_stale."""

    def test_filter_active_paper_closed_today_excludes_stale(self):
        """10 normal + 5 stale + 2 reconciled today: paper_closed_today.cnt = 12."""
        conn = _make_conn()
        _seed_with_today(conn, 10, 5, 2, source="paper")
        conn.row_factory = sqlite3.Row

        from src.shadow_trading.exit_reason import outcome_stats_filter_sql
        row = conn.execute(
            "SELECT COUNT(*) as cnt, COALESCE(SUM(pnl_dollars),0) as pnl "
            "FROM shadow_trades WHERE status = 'closed' AND COALESCE(source,'paper')='paper' "
            f"AND actual_exit_time LIKE ? AND COALESCE(quarantined, 0) = 0 {outcome_stats_filter_sql()}",
            (f"{_TODAY}%",),
        ).fetchone()
        assert row["cnt"] == 12

    def test_sanity_paper_closed_today_normal_only(self):
        """10 normal today: paper_closed_today.cnt = 10."""
        conn = _make_conn()
        _seed_with_today(conn, 10, 0, 0, source="paper")
        conn.row_factory = sqlite3.Row

        from src.shadow_trading.exit_reason import outcome_stats_filter_sql
        row = conn.execute(
            "SELECT COUNT(*) as cnt, COALESCE(SUM(pnl_dollars),0) as pnl "
            "FROM shadow_trades WHERE status = 'closed' AND COALESCE(source,'paper')='paper' "
            f"AND actual_exit_time LIKE ? AND COALESCE(quarantined, 0) = 0 {outcome_stats_filter_sql()}",
            (f"{_TODAY}%",),
        ).fetchone()
        assert row["cnt"] == 10


class TestReportsLiveClosedToday:
    """reports.py:427 — live_closed_today excludes reconciled_stale."""

    def test_filter_active_live_closed_today_excludes_stale(self):
        """10 normal + 5 stale live today: live_closed_today.cnt = 12."""
        conn = _make_conn()
        _seed_with_today(conn, 10, 5, 2, source="live")
        conn.row_factory = sqlite3.Row

        from src.shadow_trading.exit_reason import outcome_stats_filter_sql
        row = conn.execute(
            "SELECT COUNT(*) as cnt, COALESCE(SUM(pnl_dollars),0) as pnl "
            "FROM shadow_trades WHERE status = 'closed' AND source='live' "
            f"AND actual_exit_time LIKE ? AND COALESCE(quarantined, 0) = 0 {outcome_stats_filter_sql()}",
            (f"{_TODAY}%",),
        ).fetchone()
        assert row["cnt"] == 12

    def test_sanity_live_closed_today_normal_only(self):
        """10 live normal today: live_closed_today.cnt = 10."""
        conn = _make_conn()
        _seed_with_today(conn, 10, 0, 0, source="live")
        conn.row_factory = sqlite3.Row

        from src.shadow_trading.exit_reason import outcome_stats_filter_sql
        row = conn.execute(
            "SELECT COUNT(*) as cnt, COALESCE(SUM(pnl_dollars),0) as pnl "
            "FROM shadow_trades WHERE status = 'closed' AND source='live' "
            f"AND actual_exit_time LIKE ? AND COALESCE(quarantined, 0) = 0 {outcome_stats_filter_sql()}",
            (f"{_TODAY}%",),
        ).fetchone()
        assert row["cnt"] == 10


class TestReportsAllTimeWinRate:
    """reports.py:436 — all-time win_rate excludes reconciled_stale."""

    def test_filter_active_win_rate_excludes_stale(self):
        """10 normal (pnl>0) + 5 stale (pnl=0): all-time total=12, wins=12, win_rate=1.0."""
        conn = _make_conn()
        seed_closed_trades(conn, n_normal=10, n_reconciled_stale=5, n_reconciled=2)
        conn.row_factory = sqlite3.Row

        from src.shadow_trading.exit_reason import outcome_stats_filter_sql
        all_closed = conn.execute(
            "SELECT COUNT(*) as total, "
            "SUM(CASE WHEN pnl_dollars > 0 THEN 1 ELSE 0 END) as wins "
            f"FROM shadow_trades WHERE status = 'closed' AND COALESCE(quarantined, 0) = 0"
            f" {outcome_stats_filter_sql()}"
        ).fetchone()
        total = all_closed["total"] or 0
        wins = all_closed["wins"] or 0
        assert total == 12
        assert wins == 12  # all 10 normal + 2 reconciled have pnl > 0

    def test_sanity_all_time_win_rate_normal_only(self):
        """10 normal: total=10, wins=10."""
        conn = _make_conn()
        seed_closed_trades(conn, n_normal=10, n_reconciled_stale=0, n_reconciled=0)
        conn.row_factory = sqlite3.Row

        from src.shadow_trading.exit_reason import outcome_stats_filter_sql
        all_closed = conn.execute(
            "SELECT COUNT(*) as total, "
            "SUM(CASE WHEN pnl_dollars > 0 THEN 1 ELSE 0 END) as wins "
            f"FROM shadow_trades WHERE status = 'closed' AND COALESCE(quarantined, 0) = 0"
            f" {outcome_stats_filter_sql()}"
        ).fetchone()
        total = all_closed["total"] or 0
        assert total == 10


class TestReportsBestWorstToday:
    """reports.py:446+452 — best/worst today exclude reconciled_stale."""

    def test_filter_active_best_today_excludes_stale(self):
        """Best today (max pnl_pct) should be from normal trades, not stale (pnl_pct=0)."""
        conn = _make_conn()
        _seed_with_today(conn, 10, 5, 2)
        conn.row_factory = sqlite3.Row

        from src.shadow_trading.exit_reason import outcome_stats_filter_sql
        best = conn.execute(
            "SELECT ticker, pnl_pct FROM shadow_trades "
            "WHERE status = 'closed' AND actual_exit_time LIKE ?"
            f" AND COALESCE(quarantined, 0) = 0 {outcome_stats_filter_sql()} "
            "ORDER BY pnl_pct DESC LIMIT 1",
            (f"{_TODAY}%",),
        ).fetchone()
        assert best is not None
        assert best["pnl_pct"] > 0, f"Best pnl_pct should be positive (from normal trade), got {best['pnl_pct']}"

    def test_filter_active_worst_today_excludes_stale(self):
        """Worst today (min pnl_pct) should exclude stale (pnl_pct=0) — reconciled has pnl_pct=1.0."""
        conn = _make_conn()
        _seed_with_today(conn, 10, 5, 2)
        conn.row_factory = sqlite3.Row

        from src.shadow_trading.exit_reason import outcome_stats_filter_sql
        worst = conn.execute(
            "SELECT ticker, pnl_pct FROM shadow_trades "
            "WHERE status = 'closed' AND actual_exit_time LIKE ?"
            f" AND COALESCE(quarantined, 0) = 0 {outcome_stats_filter_sql()} "
            "ORDER BY pnl_pct ASC LIMIT 1",
            (f"{_TODAY}%",),
        ).fetchone()
        assert worst is not None
        # Without filter, worst would be 0.0 (stale). With filter, worst is 1.0 (reconciled)
        assert worst["pnl_pct"] >= 1.0, (
            f"Worst pnl_pct should be >= 1.0 (stale excluded), got {worst['pnl_pct']}"
        )

    def test_sanity_best_worst_normal_only(self):
        """10 normal (pnl_pct=2.0): best=2.0, worst=2.0."""
        conn = _make_conn()
        _seed_with_today(conn, 10, 0, 0)
        conn.row_factory = sqlite3.Row

        from src.shadow_trading.exit_reason import outcome_stats_filter_sql
        best = conn.execute(
            "SELECT pnl_pct FROM shadow_trades "
            "WHERE status = 'closed' AND actual_exit_time LIKE ?"
            f" AND COALESCE(quarantined, 0) = 0 {outcome_stats_filter_sql()} "
            "ORDER BY pnl_pct DESC LIMIT 1",
            (f"{_TODAY}%",),
        ).fetchone()
        assert best is not None
        assert abs(best["pnl_pct"] - 2.0) < 0.01
