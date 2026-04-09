"""Tests for CTO performance report generation."""

from unittest.mock import patch, MagicMock

import pytest


def _make_closed_trades(n: int, win_pct: float = 0.5) -> list[dict]:
    """Generate mock closed trade dicts."""
    trades = []
    wins = int(n * win_pct)
    for i in range(n):
        is_win = i < wins
        trades.append({
            "trade_id": f"trade-{i}",
            "ticker": f"T{i % 10}",
            "recommendation_id": f"rec-{i}",
            "actual_entry_price": 100.0,
            "actual_exit_price": 103.0 if is_win else 97.0,
            "pnl_dollars": 3.0 if is_win else -3.0,
            "pnl_pct": 3.0 if is_win else -3.0,
            "exit_reason": "target_1_hit" if is_win else "stop_hit",
            "duration_days": 5,
            "max_favorable_excursion": 4.0 if is_win else 1.0,
            "max_adverse_excursion": -1.0 if is_win else -4.0,
            "planned_shares": 5,
            "earnings_adjacent": 0,
            "status": "closed",
            "order_type": "bracket",
        })
    return trades


def _make_recommendations(n: int) -> list[dict]:
    """Generate mock recommendation dicts."""
    return [
        {
            "recommendation_id": f"rec-{i}",
            "ticker": f"T{i % 10}",
            "priority_score": 70 + (i % 30),
            "confidence_score": 7 + (i % 3),
            "trend_state": "uptrend" if i % 2 == 0 else "strong_uptrend",
            "relative_strength_state": "outperformer",
            "pullback_depth_pct": -5.0 - (i % 5),
            "volume_state": "contracting" if i % 3 == 0 else "normal",
            "market_regime": "calm_uptrend",
            "model_version": "halcyon-v1" if i % 2 == 0 else "base",
        }
        for i in range(n)
    ]


def _patch_cto_deps():
    """Return a dict of patch targets for CTO report dependencies."""
    return {
        "closed": patch("src.journal.store.get_closed_shadow_trades"),
        "open": patch("src.journal.store.get_open_shadow_trades"),
        "all": patch("src.journal.store.get_all_shadow_trades"),
        "recs": patch("src.journal.store.get_recommendations_in_period"),
        "model": patch("src.training.versioning.get_active_model_name"),
        "counts": patch("src.training.versioning.get_training_example_counts"),
        "config": patch("src.config.load_config"),
    }


class TestCTOReportGeneration:
    @patch("src.config.load_config", return_value={"bootcamp": {"enabled": False}})
    @patch("src.training.versioning.get_training_example_counts", return_value={"total": 500, "live": 50, "backfill": 450})
    @patch("src.training.versioning.get_active_model_name", return_value="halcyon-v1")
    @patch("src.journal.store.get_recommendations_in_period")
    @patch("src.journal.store.get_all_shadow_trades")
    @patch("src.journal.store.get_open_shadow_trades")
    @patch("src.journal.store.get_closed_shadow_trades")
    def test_report_structure(self, mock_closed, mock_open, mock_all, mock_recs,
                               mock_model, mock_counts, mock_config):
        from src.evaluation.cto_report import generate_cto_report

        mock_closed.return_value = _make_closed_trades(18, win_pct=0.556)
        mock_open.return_value = _make_closed_trades(5)
        mock_all.return_value = _make_closed_trades(23)
        mock_recs.return_value = _make_recommendations(23)

        report = generate_cto_report(days=7)

        assert "report_period" in report
        assert "system_status" in report
        assert "trade_summary" in report
        assert "by_exit_reason" in report
        assert "by_score_band" in report
        assert "by_sector" in report
        assert "execution_analysis" in report
        assert "signal_quality" in report
        assert "feature_correlations" in report
        assert "training_status" in report

    @patch("src.config.load_config", return_value={"bootcamp": {"enabled": False}})
    @patch("src.training.versioning.get_training_example_counts", return_value={"total": 100, "live": 10, "backfill": 90})
    @patch("src.training.versioning.get_active_model_name", return_value="base")
    @patch("src.journal.store.get_recommendations_in_period")
    @patch("src.journal.store.get_all_shadow_trades")
    @patch("src.journal.store.get_open_shadow_trades")
    @patch("src.journal.store.get_closed_shadow_trades")
    def test_trade_summary_math(self, mock_closed, mock_open, mock_all, mock_recs,
                                 mock_model, mock_counts, mock_config):
        from src.evaluation.cto_report import generate_cto_report

        closed = _make_closed_trades(10, win_pct=0.6)
        mock_closed.return_value = closed
        mock_open.return_value = []
        mock_all.return_value = closed
        mock_recs.return_value = _make_recommendations(10)

        report = generate_cto_report(days=7)
        ts = report["trade_summary"]

        assert ts["trades_closed"] == 10
        assert ts["trades_open"] == 0
        assert ts["win_rate"] == 0.6
        assert ts["total_pnl"] == 6 * 3.0 + 4 * (-3.0)  # 18 - 12 = 6

    @patch("src.config.load_config", return_value={"bootcamp": {"enabled": False}})
    @patch("src.training.versioning.get_training_example_counts", return_value={"total": 0, "live": 0, "backfill": 0})
    @patch("src.training.versioning.get_active_model_name", return_value="base")
    @patch("src.journal.store.get_recommendations_in_period")
    @patch("src.journal.store.get_all_shadow_trades")
    @patch("src.journal.store.get_open_shadow_trades")
    @patch("src.journal.store.get_closed_shadow_trades")
    def test_zero_trades(self, mock_closed, mock_open, mock_all, mock_recs,
                          mock_model, mock_counts, mock_config):
        from src.evaluation.cto_report import generate_cto_report

        mock_closed.return_value = []
        mock_open.return_value = []
        mock_all.return_value = []
        mock_recs.return_value = []

        report = generate_cto_report(days=7)
        ts = report["trade_summary"]

        assert ts["trades_closed"] == 0
        assert ts["win_rate"] == 0
        assert ts["total_pnl"] == 0

    @patch("src.config.load_config", return_value={"bootcamp": {"enabled": False}})
    @patch("src.training.versioning.get_training_example_counts", return_value={"total": 50, "live": 5, "backfill": 45})
    @patch("src.training.versioning.get_active_model_name", return_value="base")
    @patch("src.journal.store.get_recommendations_in_period")
    @patch("src.journal.store.get_all_shadow_trades")
    @patch("src.journal.store.get_open_shadow_trades")
    @patch("src.journal.store.get_closed_shadow_trades")
    def test_all_wins(self, mock_closed, mock_open, mock_all, mock_recs,
                       mock_model, mock_counts, mock_config):
        from src.evaluation.cto_report import generate_cto_report

        closed = _make_closed_trades(5, win_pct=1.0)
        mock_closed.return_value = closed
        mock_open.return_value = []
        mock_all.return_value = closed
        mock_recs.return_value = _make_recommendations(5)

        report = generate_cto_report(days=7)
        assert report["trade_summary"]["win_rate"] == 1.0


class TestStringPnlHandling:
    """Regression test for #341: SQLite returns numeric columns as strings."""

    def test_trade_summary_handles_string_pnl(self):
        from src.evaluation.cto_report import _compute_trade_summary

        # Simulate SQLite returning ALL numeric fields as strings
        winner = {
            "trade_id": "t-1",
            "ticker": "AAPL",
            "recommendation_id": "rec-1",
            "actual_entry_price": "100.0",
            "actual_exit_price": "104.25",
            "pnl_dollars": "42.5",
            "pnl_pct": "4.25",
            "exit_reason": "target_1_hit",
            "duration_days": "5",
            "max_favorable_excursion": "5.0",
            "max_adverse_excursion": "-1.0",
            "planned_shares": "10",
            "earnings_adjacent": "0",
            "status": "closed",
            "order_type": "bracket",
        }
        loser = {
            "trade_id": "t-2",
            "ticker": "MSFT",
            "recommendation_id": "rec-2",
            "actual_entry_price": "200.0",
            "actual_exit_price": "190.0",
            "pnl_dollars": "-10.0",
            "pnl_pct": "-5.0",
            "exit_reason": "stop_hit",
            "duration_days": "3",
            "max_favorable_excursion": "1.0",
            "max_adverse_excursion": "-12.0",
            "planned_shares": "5",
            "earnings_adjacent": "0",
            "status": "closed",
            "order_type": "bracket",
        }

        closed = [winner, loser]
        result = _compute_trade_summary(closed, [], closed)

        # Must not crash (the original bug) and return correct values
        assert result["win_rate"] == 0.5
        assert result["total_pnl"] == 32.5


class TestByExitReason:
    def test_groups_by_reason(self):
        from src.evaluation.cto_report import _compute_by_exit_reason
        closed = _make_closed_trades(10, win_pct=0.5)
        result = _compute_by_exit_reason(closed)
        assert "target_1_hit" in result
        assert "stop_hit" in result
        assert result["target_1_hit"]["count"] == 5
        assert result["stop_hit"]["count"] == 5


class TestByScoreBand:
    def test_score_bands(self):
        from src.evaluation.cto_report import _compute_by_score_band
        closed = _make_closed_trades(10, win_pct=0.5)
        recs = _make_recommendations(10)
        result = _compute_by_score_band(closed, recs)
        assert "90-100" in result
        assert "80-89" in result
        assert "70-79" in result
        assert "below_70" in result


class TestReportFormatting:
    @patch("src.config.load_config", return_value={"bootcamp": {"enabled": False}})
    @patch("src.training.versioning.get_training_example_counts", return_value={"total": 0, "live": 0, "backfill": 0})
    @patch("src.training.versioning.get_active_model_name", return_value="base")
    @patch("src.journal.store.get_recommendations_in_period", return_value=[])
    @patch("src.journal.store.get_all_shadow_trades", return_value=[])
    @patch("src.journal.store.get_open_shadow_trades", return_value=[])
    @patch("src.journal.store.get_closed_shadow_trades", return_value=[])
    def test_format_does_not_crash(self, *mocks):
        from src.evaluation.cto_report import generate_cto_report, format_cto_report

        report = generate_cto_report(days=7)
        text = format_cto_report(report)
        assert "CTO PERFORMANCE REPORT" in text
        assert "TRADE SUMMARY" in text
