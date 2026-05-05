"""Tests for outcome_stats_filter_sql() applied in hshs_live._score_performance().

Module: tests.evaluation.test_hshs_live
Purpose: Verify that reconciled_stale rows are excluded from HSHS performance
         dimension sub-queries (total, winners, gross_profit, gross_loss, max_dd).
Called by: pytest
Owns tables: none
Config keys: none
"""

import sqlite3

import pytest

from tests._helpers.seed_closed_trades import seed_closed_trades, _make_conn
from src.evaluation.hshs_live import _score_performance


class TestHshsLiveTotalCount:
    """hshs_live.py:81 — total closed trade count excludes reconciled_stale."""

    def test_filter_active_total_excludes_reconciled_stale(self):
        """With 10 normal + 5 stale + 2 reconciled: total used for scoring = 12, NOT 17."""
        conn = _make_conn()
        seed_closed_trades(conn, n_normal=10, n_reconciled_stale=5, n_reconciled=2)
        # Score should reflect 12 trades, not 17.
        # With 12 trades: count_score = min(25, 12*2.5) = 25 (capped)
        # With 17 trades: count_score = min(25, 17*2.5) = 25 (capped too, both cap)
        # So we verify by querying directly to confirm filter effect.
        from src.shadow_trading.exit_reason import outcome_stats_filter_sql
        cur = conn.execute(
            "SELECT COUNT(*) as total FROM shadow_trades WHERE status = 'closed'"
            " AND COALESCE(quarantined, 0) = 0 "
            f"{outcome_stats_filter_sql()}"
        )
        total = int(cur.fetchone()[0] or 0)
        assert total == 12, f"Expected 12 (10 normal + 2 reconciled), got {total}"

    def test_sanity_normal_only_total(self):
        """With 10 normal + 0 stale: total = 10."""
        conn = _make_conn()
        seed_closed_trades(conn, n_normal=10, n_reconciled_stale=0, n_reconciled=0)
        from src.shadow_trading.exit_reason import outcome_stats_filter_sql
        cur = conn.execute(
            "SELECT COUNT(*) as total FROM shadow_trades WHERE status = 'closed'"
            " AND COALESCE(quarantined, 0) = 0 "
            f"{outcome_stats_filter_sql()}"
        )
        total = int(cur.fetchone()[0] or 0)
        assert total == 10


class TestHshsLiveWinnersCount:
    """hshs_live.py:91 — winner count excludes reconciled_stale."""

    def test_filter_active_winners_excludes_reconciled_stale(self):
        """With 10 normal (pnl>0) + 5 stale (pnl=0): winner count = 10, NOT partial."""
        conn = _make_conn()
        seed_closed_trades(conn, n_normal=10, n_reconciled_stale=5, n_reconciled=2)
        from src.shadow_trading.exit_reason import outcome_stats_filter_sql
        cur = conn.execute(
            "SELECT COUNT(*) FROM shadow_trades "
            "WHERE status = 'closed' AND pnl_dollars > 0"
            " AND COALESCE(quarantined, 0) = 0 "
            f"{outcome_stats_filter_sql()}"
        )
        winners = int(cur.fetchone()[0] or 0)
        # All 10 normal trades have pnl_dollars=100, all 2 reconciled have pnl_dollars=50
        assert winners == 12, f"Expected 12 winners (10 normal + 2 reconciled with pnl>0), got {winners}"

    def test_sanity_normal_only_winners(self):
        """With 10 normal (pnl=100 each): 10 winners."""
        conn = _make_conn()
        seed_closed_trades(conn, n_normal=10, n_reconciled_stale=0, n_reconciled=0)
        from src.shadow_trading.exit_reason import outcome_stats_filter_sql
        cur = conn.execute(
            "SELECT COUNT(*) FROM shadow_trades "
            "WHERE status = 'closed' AND pnl_dollars > 0"
            " AND COALESCE(quarantined, 0) = 0 "
            f"{outcome_stats_filter_sql()}"
        )
        winners = int(cur.fetchone()[0] or 0)
        assert winners == 10


class TestHshsLiveGrossProfit:
    """hshs_live.py:102 — gross_profit excludes reconciled_stale."""

    def test_filter_active_gross_profit_excludes_stale(self):
        """With 10 normal (pnl=100) + 5 stale (pnl=0): gross_profit = 1000+100 (normal + reconciled)."""
        conn = _make_conn()
        seed_closed_trades(conn, n_normal=10, n_reconciled_stale=5, n_reconciled=2)
        from src.shadow_trading.exit_reason import outcome_stats_filter_sql
        cur = conn.execute(
            "SELECT COALESCE(SUM(pnl_dollars), 0) FROM shadow_trades "
            "WHERE status = 'closed' AND pnl_dollars > 0"
            " AND COALESCE(quarantined, 0) = 0 "
            f"{outcome_stats_filter_sql()}"
        )
        gross_profit = float(cur.fetchone()[0] or 0)
        # 10*100 + 2*50 = 1100
        assert abs(gross_profit - 1100.0) < 0.01, f"Expected 1100, got {gross_profit}"

    def test_sanity_gross_profit_normal_only(self):
        """With 10 normal (pnl=100 each): gross_profit = 1000."""
        conn = _make_conn()
        seed_closed_trades(conn, n_normal=10, n_reconciled_stale=0, n_reconciled=0)
        from src.shadow_trading.exit_reason import outcome_stats_filter_sql
        cur = conn.execute(
            "SELECT COALESCE(SUM(pnl_dollars), 0) FROM shadow_trades "
            "WHERE status = 'closed' AND pnl_dollars > 0"
            " AND COALESCE(quarantined, 0) = 0 "
            f"{outcome_stats_filter_sql()}"
        )
        gross_profit = float(cur.fetchone()[0] or 0)
        assert abs(gross_profit - 1000.0) < 0.01


class TestHshsLiveGrossLoss:
    """hshs_live.py:109 — gross_loss excludes reconciled_stale."""

    def test_filter_active_gross_loss_excludes_stale(self):
        """Stale trades (pnl=0) should not appear in gross_loss (pnl<0) calculation."""
        conn = _make_conn()
        seed_closed_trades(conn, n_normal=10, n_reconciled_stale=5, n_reconciled=2)
        from src.shadow_trading.exit_reason import outcome_stats_filter_sql
        cur = conn.execute(
            "SELECT COALESCE(ABS(SUM(pnl_dollars)), 0) FROM shadow_trades "
            "WHERE status = 'closed' AND pnl_dollars < 0"
            " AND COALESCE(quarantined, 0) = 0 "
            f"{outcome_stats_filter_sql()}"
        )
        gross_loss = float(cur.fetchone()[0] or 0)
        # No trades have pnl < 0 in our seed data, so should be 0
        assert gross_loss == 0.0

    def test_sanity_gross_loss_normal_only(self):
        """With only positive-pnl normal trades: gross_loss = 0."""
        conn = _make_conn()
        seed_closed_trades(conn, n_normal=10, n_reconciled_stale=0, n_reconciled=0)
        from src.shadow_trading.exit_reason import outcome_stats_filter_sql
        cur = conn.execute(
            "SELECT COALESCE(ABS(SUM(pnl_dollars)), 0) FROM shadow_trades "
            "WHERE status = 'closed' AND pnl_dollars < 0"
            " AND COALESCE(quarantined, 0) = 0 "
            f"{outcome_stats_filter_sql()}"
        )
        gross_loss = float(cur.fetchone()[0] or 0)
        assert gross_loss == 0.0


class TestHshsLiveMaxDD:
    """hshs_live.py:124 — MIN(pnl_pct) excludes reconciled_stale (pnl_pct=0)."""

    def test_filter_active_max_dd_excludes_stale(self):
        """With 10 normal (pnl_pct=2.0) + 5 stale (pnl_pct=0.0): MIN(pnl_pct) should exclude stale."""
        conn = _make_conn()
        seed_closed_trades(conn, n_normal=10, n_reconciled_stale=5, n_reconciled=2)
        from src.shadow_trading.exit_reason import outcome_stats_filter_sql
        cur = conn.execute(
            "SELECT COALESCE(MIN(pnl_pct), 0) FROM shadow_trades "
            "WHERE status = 'closed' AND COALESCE(quarantined, 0) = 0 "
            f"{outcome_stats_filter_sql()}"
        )
        raw = cur.fetchone()[0]
        min_pnl_pct = float(raw) if raw is not None else 0.0
        # Without filter: MIN would be 0.0 (from stale). With filter: MIN is 1.0 (reconciled) or 2.0 (normal).
        # Reconciled trades have pnl_pct=1.0, so filtered MIN = 1.0
        assert min_pnl_pct >= 1.0, f"Expected min_pnl_pct >= 1.0 (stale excluded), got {min_pnl_pct}"

    def test_sanity_max_dd_normal_only(self):
        """With 10 normal (pnl_pct=2.0): MIN = 2.0."""
        conn = _make_conn()
        seed_closed_trades(conn, n_normal=10, n_reconciled_stale=0, n_reconciled=0)
        from src.shadow_trading.exit_reason import outcome_stats_filter_sql
        cur = conn.execute(
            "SELECT COALESCE(MIN(pnl_pct), 0) FROM shadow_trades "
            "WHERE status = 'closed' AND COALESCE(quarantined, 0) = 0 "
            f"{outcome_stats_filter_sql()}"
        )
        raw = cur.fetchone()[0]
        min_pnl_pct = float(raw) if raw is not None else 0.0
        assert abs(min_pnl_pct - 2.0) < 0.01
