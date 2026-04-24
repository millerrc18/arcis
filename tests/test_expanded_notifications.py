"""Tests for expanded Telegram notification functions."""

import sqlite3
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock
from zoneinfo import ZoneInfo

import pytest

ET = ZoneInfo("America/New_York")


# ── Notification formatting tests ─────────────────────────────────────────


class TestPremarketBrief:
    """Test notify_premarket_brief formatting."""

    @patch("src.notifications.telegram.send_telegram")
    def test_basic_format(self, mock_send):
        mock_send.return_value = True
        from src.notifications.telegram import notify_premarket_brief

        result = notify_premarket_brief(
            vix=25.33, vix_change=1.2, regime="TRANSITION",
            spy_futures_pct=-0.3, ten_year=4.28,
            earnings_today=["NKE (AMC)"],
            fomc_days=8, nfp_days=7,
            council_consensus="DEFENSIVE", council_confidence=73,
            open_paper=3, open_live=1,
        )
        assert result is True
        msg = mock_send.call_args[0][0]
        assert "PRE-MARKET BRIEF" in msg
        assert "25.33" in msg
        assert "TRANSITION" in msg
        assert "NKE" in msg
        assert "FOMC in 8 days" in msg
        assert "DEFENSIVE" in msg
        assert "3 paper, 1 live" in msg

    @patch("src.notifications.telegram.send_telegram")
    def test_no_events(self, mock_send):
        mock_send.return_value = True
        from src.notifications.telegram import notify_premarket_brief

        notify_premarket_brief(
            vix=18.0, vix_change=-0.5, regime="BULL_LOW_VOL",
            spy_futures_pct=0.2, ten_year=3.95,
            earnings_today=[],
            fomc_days=None, nfp_days=None,
            council_consensus="BULLISH", council_confidence=85,
            open_paper=0, open_live=0,
        )
        msg = mock_send.call_args[0][0]
        assert "No major events" in msg
        assert "None" in msg  # No earnings

    @patch("src.notifications.telegram.send_telegram")
    def test_643_small_moves_render_with_two_decimals(self, mock_send):
        """#643 regression: pre-merge, quiet pre-market mornings rendered
        S&P futures of -0.04% as `-0.0%`, which operators read as broken data.

        With 2-decimal precision, sub-0.05% moves are visible.
        """
        mock_send.return_value = True
        from src.notifications.telegram import notify_premarket_brief

        notify_premarket_brief(
            vix=18.92, vix_change=-0.6, regime="TRANSITION",
            spy_futures_pct=-0.04, ten_year=4.32,
            earnings_today=["CHTR", "PG"],
            fomc_days=5, nfp_days=7,
            council_consensus="BEARISH", council_confidence=51,
            open_paper=6, open_live=4,
        )
        msg = mock_send.call_args[0][0]
        # Pre-fix this would be "-0.0%" — the bug under test.
        assert "S&amp;P Futures: -0.04%" in msg, (
            f"Expected 2-decimal precision on S&P futures; got: {msg!r}"
        )
        # VIX change should also use 2 decimals for consistency.
        assert "(-0.60)" in msg, (
            f"Expected 2-decimal precision on VIX change; got: {msg!r}"
        )
        # 10Y unchanged at 2 decimals.
        assert "10Y: 4.32%" in msg

    @patch("src.notifications.telegram.send_telegram")
    def test_643_positive_zero_distinct_from_negative_small(self, mock_send):
        """#643 — the leading-sign rendering must distinguish a true zero
        (default-on-fetch-failure) from a tiny-but-real negative move.

        With `:+.2f`, exact 0.0 renders as `+0.00%` (clearly intentional)
        while -0.04 renders as `-0.04%` (clearly real data).
        """
        mock_send.return_value = True
        from src.notifications.telegram import notify_premarket_brief

        # Case 1: exact zero (yfinance default fallback)
        notify_premarket_brief(
            vix=18.0, vix_change=0.0, regime="NEUTRAL",
            spy_futures_pct=0.0, ten_year=4.30,
            earnings_today=[], fomc_days=None, nfp_days=None,
            council_consensus="NEUTRAL", council_confidence=50,
            open_paper=0, open_live=0,
        )
        msg_zero = mock_send.call_args[0][0]
        assert "S&amp;P Futures: +0.00%" in msg_zero
        assert "(+0.00)" in msg_zero  # vix_change

        # Case 2: tiny real negative — must NOT collapse to +0.00
        notify_premarket_brief(
            vix=18.0, vix_change=-0.03, regime="NEUTRAL",
            spy_futures_pct=-0.02, ten_year=4.30,
            earnings_today=[], fomc_days=None, nfp_days=None,
            council_consensus="NEUTRAL", council_confidence=50,
            open_paper=0, open_live=0,
        )
        msg_tiny = mock_send.call_args[0][0]
        assert "S&amp;P Futures: -0.02%" in msg_tiny
        assert "(-0.03)" in msg_tiny


class TestFirstScanSummary:
    """Test notify_first_scan_summary formatting."""

    @patch("src.notifications.telegram.send_telegram")
    def test_basic_format(self, mock_send):
        mock_send.return_value = True
        from src.notifications.telegram import notify_first_scan_summary

        result = notify_first_scan_summary(
            total_scanned=102, packet_worthy=18, watchlist=11,
            trades_opened_paper=3, trades_opened_live=1,
            top_setups=[("DUK", 97), ("BMY", 97), ("EXC", 97)],
            setup_type_counts={"pullback": 14, "breakout": 3, "momentum": 1},
            llm_success=6, llm_total=8, llm_fallback=2,
        )
        assert result is True
        msg = mock_send.call_args[0][0]
        assert "FIRST SCAN COMPLETE" in msg
        assert "102" in msg
        assert "DUK(97)" in msg
        assert "14 pullback" in msg
        assert "6/8" in msg
        assert "2 template fallback" in msg


class TestEodReport:
    """Test notify_eod_report formatting."""

    @patch("src.notifications.telegram.send_telegram")
    def test_basic_format(self, mock_send):
        mock_send.return_value = True
        from src.notifications.telegram import notify_eod_report

        result = notify_eod_report(
            paper_open=5, paper_open_pnl=23.40,
            paper_closed_today=1, paper_closed_pnl=8.20,
            live_open=1, live_open_pnl=-0.80,
            live_closed_today=0, live_closed_pnl=0.0,
            win_rate=0.62, wins=8, losses=5,
            best_ticker="CAT", best_pct=3.2,
            worst_ticker="FDX", worst_pct=-1.8,
            regime="TRANSITION", vix=24.8, vix_change=-0.5,
        )
        assert result is True
        msg = mock_send.call_args[0][0]
        assert "END OF DAY" in msg
        assert "Paper:" in msg
        assert "Live:" in msg
        assert "62%" in msg
        assert "CAT" in msg
        assert "TRANSITION" in msg


class TestDataAssetReport:
    """Test notify_data_asset_report formatting."""

    @patch("src.notifications.telegram.send_telegram")
    def test_with_flywheel(self, mock_send):
        mock_send.return_value = True
        from src.notifications.telegram import notify_data_asset_report

        notify_data_asset_report(
            training_total=979, training_today=3, training_target=2800,
            signal_zoo_total=45, signal_zoo_today=20,
            scoring_backlog=0, quality_avg=3.8,
            flywheel_count=3,
        )
        msg = mock_send.call_args[0][0]
        assert "DATA ASSET REPORT" in msg
        assert "979" in msg
        assert "target 2,800" in msg or "target 2800" in msg
        assert "Flywheel: ✅" in msg

    @patch("src.notifications.telegram.send_telegram")
    def test_no_flywheel(self, mock_send):
        mock_send.return_value = True
        from src.notifications.telegram import notify_data_asset_report

        notify_data_asset_report(
            training_total=100, training_today=0, training_target=2800,
            signal_zoo_total=10, signal_zoo_today=0,
            scoring_backlog=5, quality_avg=3.5,
            flywheel_count=0,
        )
        msg = mock_send.call_args[0][0]
        assert "Flywheel: ⏸️" in msg


class TestRegimeAlert:
    """Test notify_regime_alert and VIX threshold crossing logic."""

    @patch("src.notifications.telegram.send_telegram")
    def test_format(self, mock_send):
        mock_send.return_value = True
        from src.notifications.telegram import notify_regime_alert

        notify_regime_alert(
            vix_now=31.2, vix_prev=28.5, threshold_crossed=30,
            regime_old="TRANSITION", regime_new="CORRECTION",
            qual_old=40, qual_new=65,
            sizing_old=100, sizing_new=60,
        )
        msg = mock_send.call_args[0][0]
        assert "REGIME ALERT" in msg
        assert "30" in msg
        assert "TRANSITION → CORRECTION" in msg
        assert "Tighter" in msg


class TestResearchPapers:
    """Test notify_research_papers formatting and type safety."""

    @patch("src.notifications.telegram.send_telegram")
    def test_string_score_is_coerced(self, mock_send):
        mock_send.return_value = True
        from src.notifications.telegram import notify_research_papers

        result = notify_research_papers(
            total_new=3,
            top_paper="A useful paper title",
            top_score="0.83",
        )

        assert result is True
        msg = mock_send.call_args[0][0]
        assert "3 new research papers" in msg
        assert "relevance: 0.8" in msg


class TestVixThresholdCrossing:
    """Test the VIX threshold crossing logic in watch loop."""

    def test_upward_crossing(self):
        """VIX going from 28 to 31 should cross 30."""
        prev = 28.0
        now = 31.0
        thresholds = [20, 25, 30, 35, 40, 60]
        crossed = None
        for t in thresholds:
            if prev < t <= now:
                crossed = t
            elif prev > t >= now:
                crossed = t
            elif prev >= t > now:
                crossed = t
        assert crossed == 30

    def test_downward_crossing(self):
        """VIX going from 31 to 24 should detect crossing (30 is last found)."""
        prev = 31.0
        now = 24.0
        thresholds = [20, 25, 30, 35, 40, 60]
        crossed = None
        for t in thresholds:
            if prev < t <= now:
                crossed = t
            elif prev > t >= now:
                crossed = t
            elif prev >= t > now:
                crossed = t
        # Loop iterates in order; 30 is checked after 25, so 30 wins
        assert crossed == 30

    def test_small_downward_crossing(self):
        """VIX going from 26 to 24 should cross 25."""
        prev = 26.0
        now = 24.0
        thresholds = [20, 25, 30, 35, 40, 60]
        crossed = None
        for t in thresholds:
            if prev < t <= now:
                crossed = t
            elif prev > t >= now:
                crossed = t
            elif prev >= t > now:
                crossed = t
        assert crossed == 25

    def test_no_crossing(self):
        """VIX moving within the same band shouldn't trigger."""
        prev = 22.0
        now = 23.5
        thresholds = [20, 25, 30, 35, 40, 60]
        crossed = None
        for t in thresholds:
            if prev < t <= now:
                crossed = t
            elif prev > t >= now:
                crossed = t
            elif prev >= t > now:
                crossed = t
        assert crossed is None

    def test_exact_threshold(self):
        """VIX moving to exactly a threshold value."""
        prev = 19.5
        now = 20.0
        thresholds = [20, 25, 30, 35, 40, 60]
        crossed = None
        for t in thresholds:
            if prev < t <= now:
                crossed = t
            elif prev > t >= now:
                crossed = t
            elif prev >= t > now:
                crossed = t
        assert crossed == 20


class TestMilestoneNotification:
    """Test notify_milestone formatting."""

    @patch("src.notifications.telegram.send_telegram")
    def test_format(self, mock_send):
        mock_send.return_value = True
        from src.notifications.telegram import notify_milestone

        notify_milestone(
            "10th closed trade!",
            "40 more to Phase 1 gate (50 trades).\nCurrent win rate: 60% (6W / 4L)"
        )
        msg = mock_send.call_args[0][0]
        assert "MILESTONE" in msg
        assert "10th closed trade" in msg


class TestStreakAlert:
    """Test notify_streak_alert formatting."""

    @patch("src.notifications.telegram.send_telegram")
    def test_format(self, mock_send):
        mock_send.return_value = True
        from src.notifications.telegram import notify_streak_alert

        notify_streak_alert(
            streak_length=3,
            recent_trades=[("FDX", -1.8), ("COST", -2.1), ("CAT", -0.5)],
            max_drawdown_pct=-2.1,
            risk_governor_status="NORMAL",
            historical_max_streak=4,
        )
        msg = mock_send.call_args[0][0]
        assert "STREAK ALERT" in msg
        assert "3 consecutive losses" in msg
        assert "FDX" in msg
        assert "Historical streak max: 4" in msg


class TestWeeklyDigest:
    """Test notify_weekly_digest formatting."""

    @patch("src.notifications.telegram.send_telegram")
    def test_format(self, mock_send):
        mock_send.return_value = True
        from src.notifications.telegram import notify_weekly_digest

        notify_weekly_digest(
            period_start="Mar 21", period_end="Mar 26",
            opened_paper=12, opened_live=4,
            closed_paper=8, closed_live=2,
            win_rate=0.62, expectancy=4.30,
            best_ticker="CAT", best_pct=5.2,
            worst_ticker="FDX", worst_pct=-3.1,
            pnl_paper=45.20, pnl_live=3.80,
            training_start=979, training_end=1012,
            signal_start=45, signal_end=185,
            scoring_backlog=0, quality_avg=3.8,
            canary_status="STABLE", llm_success_rate=0.78,
            regime="TRANSITION", vix=24.8,
            vix_range_low=22.1, vix_range_high=28.3,
            spy_weekly_pct=-1.2,
            council_sessions=5,
            council_consensus="DEFENSIVE",
            council_avg_confidence=71,
            earnings_next_week=["AAPL", "MSFT"],
            events_next_week=["NFP Friday"],
        )
        msg = mock_send.call_args[0][0]
        assert "WEEKLY DIGEST" in msg
        assert "TRADES:" in msg
        assert "DATA ASSET:" in msg
        assert "MODEL:" in msg
        assert "MARKET:" in msg
        assert "COUNCIL:" in msg
        assert "NEXT WEEK:" in msg
        assert "AAPL" in msg


class TestRetrainReport:
    """Test notify_retrain_report formatting."""

    @patch("src.notifications.telegram.send_telegram")
    def test_format(self, mock_send):
        mock_send.return_value = True
        from src.notifications.telegram import notify_retrain_report

        notify_retrain_report(
            model_name="halcyon-v1.1",
            training_examples=1012, prev_examples=976,
            new_this_week=36, new_paper=28, new_live=8,
            canary_status="STABLE",
            perplexity=2.34, prev_perplexity=2.31,
            distinct2=0.82, prev_distinct2=0.83,
            champion_challenger="PENDING — will evaluate on Monday",
        )
        msg = mock_send.call_args[0][0]
        assert "SATURDAY RETRAIN" in msg
        assert "halcyon-v1.1" in msg
        assert "1012" in msg
        assert "STABLE" in msg
        assert "2.34" in msg


class TestCollectionFailure:
    """Test notify_collection_failure formatting."""

    @patch("src.notifications.telegram.send_telegram")
    def test_format(self, mock_send):
        mock_send.return_value = True
        from src.notifications.telegram import notify_collection_failure

        notify_collection_failure(
            collector_name="options",
            consecutive_failures=3,
            last_error="ConnectionTimeout after 60s",
            last_success_ago="2 hours ago",
            other_collectors={
                "metrics": True, "vix": True, "cboe": True,
                "macro": True, "trends": True, "earnings": True,
            },
        )
        msg = mock_send.call_args[0][0]
        assert "COLLECTION ALERT" in msg
        assert "options" in msg
        assert "3 consecutive" in msg
        assert "✅ metrics" in msg


class TestExposureAlert:
    """Test notify_exposure_alert formatting."""

    @patch("src.notifications.telegram.send_telegram")
    def test_format(self, mock_send):
        mock_send.return_value = True
        from src.notifications.telegram import notify_exposure_alert

        notify_exposure_alert(
            sector="Utilities", count=3,
            tickers=["DUK", "EXC", "SO"],
            exposure_pct=60.0, limit_pct=30.0,
        )
        msg = mock_send.call_args[0][0]
        assert "EXPOSURE ALERT" in msg
        assert "Utilities" in msg
        assert "DUK" in msg
        assert "60%" in msg


class TestPositionEarningsWarning:
    """Test notify_position_earnings_warning formatting."""

    @patch("src.notifications.telegram.send_telegram")
    def test_with_expected_move(self, mock_send):
        mock_send.return_value = True
        from src.notifications.telegram import notify_position_earnings_warning

        notify_position_earnings_warning(
            ticker="CAT", days_until=2,
            earnings_date="2026-03-28", earnings_time="before_market",
            current_pnl=12.40, current_pnl_pct=1.8,
            expected_move_pct=4.2,
        )
        msg = mock_send.call_args[0][0]
        assert "EARNINGS WARNING" in msg
        assert "CAT" in msg
        assert "2 days" in msg
        assert "4.2%" in msg

    @patch("src.notifications.telegram.send_telegram")
    def test_without_expected_move(self, mock_send):
        mock_send.return_value = True
        from src.notifications.telegram import notify_position_earnings_warning

        notify_position_earnings_warning(
            ticker="MSFT", days_until=1,
            earnings_date="2026-03-27", earnings_time="after_market",
            current_pnl=-5.00, current_pnl_pct=-0.5,
        )
        msg = mock_send.call_args[0][0]
        assert "MSFT" in msg
        assert "Expected move" not in msg


# ── Milestone detection tests ─────────────────────────────────────────────


class TestMilestoneDetection:
    """Test milestone detection logic in executor."""

    @patch("src.notifications.telegram.is_telegram_enabled", return_value=True)
    @patch("src.notifications.telegram.notify_milestone")
    def test_first_paper_trade(self, mock_notify, mock_enabled, tmp_path):
        """First paper trade should trigger milestone."""
        db_path = str(tmp_path / "test.db")
        _create_test_db(db_path)

        # Insert one paper trade
        with sqlite3.connect(db_path) as conn:
            conn.execute(
                "INSERT INTO shadow_trades (trade_id, ticker, status, source, created_at, updated_at) "
                "VALUES ('t1', 'AAPL', 'open', 'paper', '2026-03-20T10:00:00', '2026-03-20T10:00:00')"
            )

        from src.shadow_trading.executor import _check_open_milestones
        _check_open_milestones(db_path, source="paper")

        mock_notify.assert_called_once()
        assert "First paper trade" in mock_notify.call_args[0][0]

    @patch("src.notifications.telegram.is_telegram_enabled", return_value=True)
    @patch("src.notifications.telegram.notify_milestone")
    def test_tenth_close_milestone(self, mock_notify, mock_enabled, tmp_path):
        """10th closed trade should trigger milestone."""
        db_path = str(tmp_path / "test.db")
        _create_test_db(db_path)

        # Insert 10 closed trades
        with sqlite3.connect(db_path) as conn:
            for i in range(10):
                pnl = 10.0 if i % 2 == 0 else -5.0
                conn.execute(
                    "INSERT INTO shadow_trades "
                    "(trade_id, ticker, status, source, pnl_dollars, pnl_pct, "
                    "actual_exit_time, duration_days, created_at, updated_at) "
                    "VALUES (?, ?, 'closed', 'paper', ?, ?, ?, ?, '2026-03-15T10:00:00', '2026-03-15T10:00:00')",
                    (f"t{i}", f"TICK{i}", pnl, pnl / 100, f"2026-03-{20+i}", 5),
                )

        from src.shadow_trading.executor import _check_close_milestones
        _check_close_milestones(db_path)

        # Should be called for 10th trade milestone
        calls = mock_notify.call_args_list
        milestone_names = [c[0][0] for c in calls]
        assert any("10th" in m for m in milestone_names)


# ── Loss streak detection tests ───────────────────────────────────────────


class TestLossStreakDetection:
    """Test loss streak detection logic."""

    @patch("src.notifications.telegram.is_telegram_enabled", return_value=True)
    @patch("src.notifications.telegram.notify_streak_alert")
    def test_three_consecutive_losses(self, mock_notify, mock_enabled, tmp_path):
        """3 consecutive losses should trigger streak alert."""
        db_path = str(tmp_path / "test.db")
        _create_test_db(db_path)

        with sqlite3.connect(db_path) as conn:
            # A win, then 3 losses
            conn.execute(
                "INSERT INTO shadow_trades "
                "(trade_id, ticker, status, source, pnl_dollars, pnl_pct, actual_exit_time, created_at, updated_at) "
                "VALUES ('t0', 'WIN1', 'closed', 'paper', 10.0, 1.0, '2026-03-20', '2026-03-19T10:00:00', '2026-03-20T10:00:00')"
            )
            for i in range(1, 4):
                conn.execute(
                    "INSERT INTO shadow_trades "
                    "(trade_id, ticker, status, source, pnl_dollars, pnl_pct, actual_exit_time, created_at, updated_at) "
                    "VALUES (?, ?, 'closed', 'paper', ?, ?, ?, '2026-03-19T10:00:00', '2026-03-20T10:00:00')",
                    (f"t{i}", f"LOSS{i}", -10.0 * i, -1.0 * i, f"2026-03-2{i}"),
                )

        from src.shadow_trading.executor import _check_loss_streak
        _check_loss_streak(db_path)

        mock_notify.assert_called_once()
        assert mock_notify.call_args[1]["streak_length"] == 3

    @patch("src.notifications.telegram.is_telegram_enabled", return_value=True)
    @patch("src.notifications.telegram.notify_streak_alert")
    def test_two_losses_no_alert(self, mock_notify, mock_enabled, tmp_path):
        """2 consecutive losses should NOT trigger alert."""
        db_path = str(tmp_path / "test.db")
        _create_test_db(db_path)

        with sqlite3.connect(db_path) as conn:
            conn.execute(
                "INSERT INTO shadow_trades "
                "(trade_id, ticker, status, source, pnl_dollars, pnl_pct, actual_exit_time, created_at, updated_at) "
                "VALUES ('t0', 'WIN1', 'closed', 'paper', 10.0, 1.0, '2026-03-20', '2026-03-19T10:00:00', '2026-03-20T10:00:00')"
            )
            for i in range(1, 3):
                conn.execute(
                    "INSERT INTO shadow_trades "
                    "(trade_id, ticker, status, source, pnl_dollars, pnl_pct, actual_exit_time, created_at, updated_at) "
                    "VALUES (?, ?, 'closed', 'paper', -5.0, -0.5, ?, '2026-03-19T10:00:00', '2026-03-20T10:00:00')",
                    (f"t{i}", f"LOSS{i}", f"2026-03-2{i}"),
                )

        from src.shadow_trading.executor import _check_loss_streak
        _check_loss_streak(db_path)

        mock_notify.assert_not_called()


# ── Helper to create test database ────────────────────────────────────────


def _create_test_db(db_path: str):
    """Create a minimal test database with required tables."""
    from tests.conftest import init_test_db
    init_test_db(db_path, ["shadow_trades", "recommendations"])
