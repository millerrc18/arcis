"""Tests for email/digest_builder.py closed-trade queries excluding reconciled_stale.

Module: tests.email.test_digest_builder
Purpose: Verify that the four closed-trade query sites in digest_builder.py
         (:153 closed_yesterday in premarket, :226 closed_today in midday,
         :292 all_closed in eod, :356 closed_total in evening)
         exclude reconciled_stale rows.
         digest_builder.py:219 and :290 are reclassified per M11 as do-NOT-filter
         (open-trade counters).
Called by: pytest
Owns tables: none
Config keys: none
"""

import sqlite3

import pytest

from tests._helpers.seed_closed_trades import seed_closed_trades, _make_conn


_YESTERDAY = "2026-01-01"


class TestDigestClosedYesterday:
    """digest_builder.py:153 — closed_yesterday in build_premarket_digest excludes stale."""

    def test_filter_active_closed_yesterday_excludes_stale(self):
        """10 normal + 5 stale + 2 reconciled yesterday: closed_yesterday has 12 rows."""
        conn = _make_conn()
        seed_closed_trades(conn, n_normal=10, n_reconciled_stale=5, n_reconciled=2)
        conn.execute(
            "UPDATE shadow_trades SET actual_exit_time = ?",
            (f"{_YESTERDAY}T15:00:00",),
        )
        conn.commit()
        conn.row_factory = sqlite3.Row

        from src.shadow_trading.exit_reason import outcome_stats_filter_sql
        rows = conn.execute(
            "SELECT ticker, pnl_dollars, pnl_pct, exit_reason "
            "FROM shadow_trades WHERE status = 'closed' AND date(actual_exit_time) = ?"
            f" AND COALESCE(quarantined, 0) = 0 {outcome_stats_filter_sql()}",
            (_YESTERDAY,),
        ).fetchall()
        assert len(rows) == 12

    def test_sanity_closed_yesterday_normal_only(self):
        """10 normal yesterday: closed_yesterday = 10 rows."""
        conn = _make_conn()
        seed_closed_trades(conn, n_normal=10, n_reconciled_stale=0, n_reconciled=0)
        conn.execute(
            "UPDATE shadow_trades SET actual_exit_time = ?",
            (f"{_YESTERDAY}T15:00:00",),
        )
        conn.commit()
        conn.row_factory = sqlite3.Row

        from src.shadow_trading.exit_reason import outcome_stats_filter_sql
        rows = conn.execute(
            "SELECT ticker, pnl_dollars, pnl_pct, exit_reason "
            "FROM shadow_trades WHERE status = 'closed' AND date(actual_exit_time) = ?"
            f" AND COALESCE(quarantined, 0) = 0 {outcome_stats_filter_sql()}",
            (_YESTERDAY,),
        ).fetchall()
        assert len(rows) == 10


class TestDigestClosedToday:
    """digest_builder.py:226 — closed_today in build_midday_digest excludes stale."""

    def test_filter_active_closed_today_excludes_stale(self):
        """10 normal + 5 stale + 2 reconciled today: closed_today has 12 rows."""
        conn = _make_conn()
        today = "2026-01-15"
        seed_closed_trades(conn, n_normal=10, n_reconciled_stale=5, n_reconciled=2)
        conn.execute(
            "UPDATE shadow_trades SET actual_exit_time = ?",
            (f"{today}T12:00:00",),
        )
        conn.commit()
        conn.row_factory = sqlite3.Row

        from src.shadow_trading.exit_reason import outcome_stats_filter_sql
        rows = conn.execute(
            "SELECT ticker, pnl_dollars, pnl_pct, exit_reason "
            "FROM shadow_trades WHERE status = 'closed' AND date(actual_exit_time) = ?"
            f" AND COALESCE(quarantined, 0) = 0 {outcome_stats_filter_sql()}",
            (today,),
        ).fetchall()
        assert len(rows) == 12

    def test_sanity_closed_today_normal_only(self):
        """10 normal today: closed_today = 10 rows."""
        conn = _make_conn()
        today = "2026-01-15"
        seed_closed_trades(conn, n_normal=10, n_reconciled_stale=0, n_reconciled=0)
        conn.execute(
            "UPDATE shadow_trades SET actual_exit_time = ?",
            (f"{today}T12:00:00",),
        )
        conn.commit()
        conn.row_factory = sqlite3.Row

        from src.shadow_trading.exit_reason import outcome_stats_filter_sql
        rows = conn.execute(
            "SELECT ticker, pnl_dollars, pnl_pct, exit_reason "
            "FROM shadow_trades WHERE status = 'closed' AND date(actual_exit_time) = ?"
            f" AND COALESCE(quarantined, 0) = 0 {outcome_stats_filter_sql()}",
            (today,),
        ).fetchall()
        assert len(rows) == 10


class TestDigestAllClosed:
    """digest_builder.py:292 — all_closed in build_eod_digest excludes stale."""

    def test_filter_active_all_closed_excludes_stale(self):
        """10 normal + 5 stale + 2 reconciled: all_closed has 12 rows."""
        conn = _make_conn()
        seed_closed_trades(conn, n_normal=10, n_reconciled_stale=5, n_reconciled=2)
        conn.row_factory = sqlite3.Row

        from src.shadow_trading.exit_reason import outcome_stats_filter_sql
        rows = conn.execute(
            "SELECT pnl_dollars, pnl_pct FROM shadow_trades WHERE status = 'closed'"
            f" AND COALESCE(quarantined, 0) = 0 {outcome_stats_filter_sql()}"
        ).fetchall()
        assert len(rows) == 12

    def test_sanity_all_closed_normal_only(self):
        """10 normal: all_closed = 10 rows."""
        conn = _make_conn()
        seed_closed_trades(conn, n_normal=10, n_reconciled_stale=0, n_reconciled=0)
        conn.row_factory = sqlite3.Row

        from src.shadow_trading.exit_reason import outcome_stats_filter_sql
        rows = conn.execute(
            "SELECT pnl_dollars, pnl_pct FROM shadow_trades WHERE status = 'closed'"
            f" AND COALESCE(quarantined, 0) = 0 {outcome_stats_filter_sql()}"
        ).fetchall()
        assert len(rows) == 10


class TestDigestClosedTotal:
    """digest_builder.py:356 — closed_total in build_evening_digest excludes stale."""

    def test_filter_active_closed_total_excludes_stale(self):
        """10 normal + 5 stale + 2 reconciled: closed_total.c = 12."""
        conn = _make_conn()
        seed_closed_trades(conn, n_normal=10, n_reconciled_stale=5, n_reconciled=2)
        conn.row_factory = sqlite3.Row

        from src.shadow_trading.exit_reason import outcome_stats_filter_sql
        closed_total = conn.execute(
            "SELECT COUNT(*) as c FROM shadow_trades WHERE status = 'closed'"
            f" AND COALESCE(quarantined, 0) = 0 {outcome_stats_filter_sql()}"
        ).fetchone()
        assert closed_total["c"] == 12

    def test_sanity_closed_total_normal_only(self):
        """10 normal: closed_total.c = 10."""
        conn = _make_conn()
        seed_closed_trades(conn, n_normal=10, n_reconciled_stale=0, n_reconciled=0)
        conn.row_factory = sqlite3.Row

        from src.shadow_trading.exit_reason import outcome_stats_filter_sql
        closed_total = conn.execute(
            "SELECT COUNT(*) as c FROM shadow_trades WHERE status = 'closed'"
            f" AND COALESCE(quarantined, 0) = 0 {outcome_stats_filter_sql()}"
        ).fetchone()
        assert closed_total["c"] == 10


class TestPremarketConfidenceFormatter:
    """digest_builder.py:198 — confidence_weighted_score is stored 0-100, not 0-1.

    Regression: 2026-05-05 operator brief showed 'Confidence: 6140%' because
    the code used `:.0%` (multiplies by 100) on a value already in 0-100 scale.
    See `src/council/aggregation.py:237` for the storage convention:
        confidence_weighted_score = round(abs(aggregated_score) * 100, 1)
    The formatter must use `:.0f}%` to render a 0-100 value as a percentage,
    NOT `:.0%}` which expects a 0-1 fraction.
    """

    def test_confidence_60_renders_as_60_percent_not_6000_percent(self, tmp_path, monkeypatch):
        """Council with confidence_weighted_score=61.4 renders 'Confidence: 61%' not '6140%'."""
        db_path = str(tmp_path / "test.sqlite3")
        from tests.conftest import init_test_db
        init_test_db(db_path)

        with sqlite3.connect(db_path) as conn:
            conn.execute(
                """INSERT INTO council_sessions (
                    session_id, session_type, trigger_reason, rounds_completed, total_cost, created_at,
                    consensus, confidence_weighted_score, is_contested
                ) VALUES (?, 'daily', 'test', 1, 0.0, ?, 'bearish', 61.4, 0)""",
                ("test-session", "2026-05-05T08:00:00"),
            )
            conn.commit()

        from src.email.digest_builder import build_premarket_digest
        _subject, body = build_premarket_digest(db_path=db_path)

        assert "Confidence: 61%" in body, (
            f"Expected 'Confidence: 61%' (renders 61.4 as 61%); body contains:\n"
            f"{[line for line in body.split(chr(10)) if 'Confidence' in line]}"
        )
        assert "Confidence: 6140%" not in body, (
            "Bug regression: :.0% was used on already-percent value, producing 6140%"
        )

    def test_confidence_zero_omits_line(self, tmp_path):
        """confidence_weighted_score=0 → no 'Confidence:' line emitted."""
        db_path = str(tmp_path / "test.sqlite3")
        from tests.conftest import init_test_db
        init_test_db(db_path)

        with sqlite3.connect(db_path) as conn:
            conn.execute(
                """INSERT INTO council_sessions (
                    session_id, session_type, trigger_reason, rounds_completed, total_cost, created_at,
                    consensus, confidence_weighted_score, is_contested
                ) VALUES (?, 'daily', 'test', 1, 0.0, ?, 'neutral', 0.0, 0)""",
                ("test-session-zero", "2026-05-05T08:00:00"),
            )
            conn.commit()

        from src.email.digest_builder import build_premarket_digest
        _subject, body = build_premarket_digest(db_path=db_path)
        assert "Confidence:" not in body, "Zero-confidence council session should not emit Confidence line"
