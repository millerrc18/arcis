"""Tests for CUSUM change detection in evaluation/change_detector.py."""

import sqlite3

import pytest

from src.evaluation.change_detector import cusum_detect, check_performance_drift
from src.journal.store import initialize_database


class TestCusumDetect:
    """Tests for the symmetric CUSUM filter."""

    def test_stable_series_no_alarms(self):
        """Stable PnL series around 0 should produce no alarms."""
        pnl = [0.5, -0.3, 0.2, -0.1, 0.4, -0.5, 0.3, -0.2, 0.1, -0.4]
        result = cusum_detect(pnl, threshold=2.0)
        assert result["total_positive_alarms"] == 0
        assert result["total_negative_alarms"] == 0
        assert result["alarms"] == []

    def test_trending_down_triggers_negative_alarm(self):
        """Consistently negative PnL should trigger negative alarms."""
        pnl = [-3.0] * 20
        result = cusum_detect(pnl, threshold=2.0)
        assert result["total_negative_alarms"] > 0

    def test_trending_up_triggers_positive_alarm(self):
        """Consistently positive PnL should trigger positive alarms."""
        pnl = [5.0] * 20
        result = cusum_detect(pnl, threshold=2.0)
        assert result["total_positive_alarms"] > 0

    def test_empty_series(self):
        result = cusum_detect([], threshold=2.0)
        assert result["total_positive_alarms"] == 0
        assert result["total_negative_alarms"] == 0
        assert result["alarms"] == []

    def test_single_element(self):
        result = cusum_detect([1.0], threshold=2.0)
        assert result["total_positive_alarms"] == 0

    def test_threshold_sensitivity(self):
        """Lower threshold should be more sensitive."""
        pnl = [-2.0, -2.0, -2.0, -2.0, -2.0]
        high_thresh = cusum_detect(pnl, threshold=10.0)
        low_thresh = cusum_detect(pnl, threshold=1.0)
        assert low_thresh["total_negative_alarms"] >= high_thresh["total_negative_alarms"]

    def test_drift_parameter(self):
        """With drift=1.0, returns of 1.0 are expected → fewer alarms."""
        pnl = [1.0] * 20
        result_with_drift = cusum_detect(pnl, threshold=2.0, drift=1.0)
        result_no_drift = cusum_detect(pnl, threshold=2.0, drift=0.0)
        assert result_no_drift["total_positive_alarms"] >= result_with_drift["total_positive_alarms"]

    def test_alarms_have_index_and_direction(self):
        pnl = [0.0] * 10 + [-5.0] * 20
        result = cusum_detect(pnl, threshold=2.0)
        for alarm in result["alarms"]:
            assert "index" in alarm
            assert "direction" in alarm
            assert alarm["direction"] in ("positive", "negative")

    def test_return_keys(self):
        result = cusum_detect([1.0, -1.0], threshold=2.0)
        assert "total_positive_alarms" in result
        assert "total_negative_alarms" in result
        assert "alarms" in result
        assert "current_s_pos" in result
        assert "current_s_neg" in result


class TestCheckPerformanceDrift:
    """Tests for check_performance_drift with real SQLite DB."""

    @pytest.fixture
    def db_path(self, tmp_path):
        path = str(tmp_path / "test.sqlite3")
        initialize_database(path)
        return path

    def test_insufficient_data(self, db_path):
        with sqlite3.connect(db_path) as conn:
            for i in range(5):
                conn.execute(
                    "INSERT INTO shadow_trades (trade_id, ticker, status, pnl_pct, "
                    "actual_exit_time, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (f"t{i}", "AAPL", "closed", 2.0, "2026-03-27", "2026-03-27", "2026-03-27"),
                )
        result = check_performance_drift(db_path)
        assert result["sufficient_data"] is False

    def test_stable_performance(self, db_path):
        with sqlite3.connect(db_path) as conn:
            for i in range(30):
                pnl = 2.0 if i % 2 == 0 else -1.5
                conn.execute(
                    "INSERT INTO shadow_trades (trade_id, ticker, status, pnl_pct, "
                    "actual_exit_time, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (f"t{i}", "AAPL", "closed", pnl, "2026-03-27", "2026-03-27", "2026-03-27"),
                )
        result = check_performance_drift(db_path)
        assert result["sufficient_data"] is True
        assert "overall_win_rate" in result
        assert "recent_win_rate" in result

    def test_empty_db(self, db_path):
        result = check_performance_drift(db_path)
        assert result["sufficient_data"] is False

    def test_reconciled_stale_excluded_from_cusum_input(self, db_path):
        """Filter active: 5 real-closed + 5 reconciled_stale → 5 visible → sufficient_data=False.

        Without filter, the CUSUM input would be 10 rows (passes the >=10 gate)
        and sufficient_data=True; reconciled_stale rows (synthetic-zero pnl_pct)
        would corrupt the drift signal.
        """
        with sqlite3.connect(db_path) as conn:
            # 5 real strategy outcomes
            for i in range(5):
                conn.execute(
                    "INSERT INTO shadow_trades (trade_id, ticker, status, pnl_pct, exit_reason, "
                    "actual_exit_time, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (f"r{i}", "AAPL", "closed", 2.0, "target_1", "2026-03-27", "2026-03-27", "2026-03-27"),
                )
            # 5 reconciled_stale rows (synthetic-zero pnl_pct — would corrupt CUSUM)
            for i in range(5):
                conn.execute(
                    "INSERT INTO shadow_trades (trade_id, ticker, status, pnl_pct, exit_reason, "
                    "actual_exit_time, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (f"s{i}", "AAPL", "closed", 0.0, "reconciled_stale", "2026-03-27", "2026-03-27", "2026-03-27"),
                )
        result = check_performance_drift(db_path)
        assert result["sufficient_data"] is False, (
            "Filter must exclude reconciled_stale; only 5 real rows remain (<10 gate)"
        )
        assert result["trade_count"] == 5

    def test_reconciled_stale_excluded_sanity_with_only_real_closures(self, db_path):
        """Sanity: 12 real-closed + 0 reconciled_stale → 12 visible → sufficient_data=True."""
        with sqlite3.connect(db_path) as conn:
            for i in range(12):
                conn.execute(
                    "INSERT INTO shadow_trades (trade_id, ticker, status, pnl_pct, exit_reason, "
                    "actual_exit_time, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (f"r{i}", "AAPL", "closed", 2.0 if i % 2 == 0 else -1.0, "target_1", "2026-03-27", "2026-03-27", "2026-03-27"),
                )
        result = check_performance_drift(db_path)
        assert result["sufficient_data"] is True
        assert "overall_win_rate" in result
