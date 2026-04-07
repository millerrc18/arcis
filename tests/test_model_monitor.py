"""Tests for model performance monitoring and regression detection."""

import sqlite3
import tempfile
import os
import math

import pytest

from src.evaluation.model_monitor import (
    _compute_metrics,
    _build_equity_curve,
    _build_comparison,
    _build_canary_comparison,
    get_model_performance,
    check_model_regression,
)


def _create_test_db(model_versions, trades):
    """Create a temporary database with model_versions, recommendations, and shadow_trades."""
    fd, db_path = tempfile.mkstemp(suffix=".sqlite3")
    os.close(fd)
    conn = sqlite3.connect(db_path)

    conn.execute("""CREATE TABLE model_versions (
        version_id TEXT PRIMARY KEY, version_name TEXT NOT NULL,
        created_at TEXT NOT NULL, training_examples_count INTEGER,
        holdout_score REAL, status TEXT NOT NULL DEFAULT 'active',
        notes TEXT, holdout_details TEXT,
        synthetic_examples_count INTEGER, outcome_examples_count INTEGER,
        model_file_path TEXT
    )""")

    conn.execute("""CREATE TABLE recommendations (
        recommendation_id TEXT PRIMARY KEY, ticker TEXT, model_version TEXT,
        created_at TEXT NOT NULL, llm_conviction INTEGER, canary_score INTEGER
    )""")

    conn.execute("""CREATE TABLE shadow_trades (
        trade_id TEXT PRIMARY KEY, recommendation_id TEXT, ticker TEXT NOT NULL,
        status TEXT DEFAULT 'pending', pnl_dollars REAL, pnl_pct REAL,
        exit_reason TEXT, duration_days INTEGER, actual_exit_time TEXT,
        created_at TEXT NOT NULL, updated_at TEXT NOT NULL
    )""")

    for mv in model_versions:
        conn.execute(
            "INSERT INTO model_versions (version_id, version_name, created_at, "
            "training_examples_count, holdout_score, status) VALUES (?, ?, ?, ?, ?, ?)",
            mv,
        )

    for i, (rec_id, ticker, model_ver, trade_id, pnl_d, pnl_p, exit_r, dur, exit_t) in enumerate(trades):
        conn.execute(
            "INSERT INTO recommendations (recommendation_id, ticker, model_version, created_at) "
            "VALUES (?, ?, ?, ?)",
            (rec_id, ticker, model_ver, f"2026-03-{20 + i:02d}"),
        )
        conn.execute(
            "INSERT INTO shadow_trades (trade_id, recommendation_id, ticker, status, "
            "pnl_dollars, pnl_pct, exit_reason, duration_days, actual_exit_time, "
            "created_at, updated_at) VALUES (?, ?, ?, 'closed', ?, ?, ?, ?, ?, ?, ?)",
            (trade_id, rec_id, ticker, pnl_d, pnl_p, exit_r, dur, exit_t,
             f"2026-03-{20 + i:02d}", f"2026-03-{20 + i:02d}"),
        )

    conn.commit()
    conn.close()
    return db_path


class TestComputeMetrics:
    def test_empty_trades(self):
        result = _compute_metrics([])
        assert result["trades"] == 0
        assert result["win_rate"] == 0.0
        assert result["sharpe_ratio"] == 0.0

    def test_basic_metrics(self):
        trades = [
            {"pnl_dollars": 100, "pnl_pct": 2.0, "exit_reason": "target_1", "duration_days": 3},
            {"pnl_dollars": -50, "pnl_pct": -1.0, "exit_reason": "stop", "duration_days": 2},
            {"pnl_dollars": 75, "pnl_pct": 1.5, "exit_reason": "target_1", "duration_days": 5},
        ]
        result = _compute_metrics(trades)
        assert result["trades"] == 3
        assert result["wins"] == 2
        assert result["losses"] == 1
        assert result["win_rate"] == round(2 / 3, 3)
        assert result["profit_factor"] == round(175 / 50, 2)
        assert result["expectancy_dollars"] == round(125 / 3, 2)
        assert result["total_pnl_dollars"] == 125.0

    def test_all_winners_profit_factor(self):
        trades = [
            {"pnl_dollars": 100, "pnl_pct": 2.0, "exit_reason": "target_1", "duration_days": 3},
            {"pnl_dollars": 50, "pnl_pct": 1.0, "exit_reason": "target_1", "duration_days": 2},
        ]
        result = _compute_metrics(trades)
        assert result["profit_factor"] == 999.0  # Capped at 999

    def test_timeout_count(self):
        trades = [
            {"pnl_dollars": -20, "pnl_pct": -0.5, "exit_reason": "timeout", "duration_days": 15},
            {"pnl_dollars": 10, "pnl_pct": 0.3, "exit_reason": "timeout", "duration_days": 15},
        ]
        result = _compute_metrics(trades)
        assert result["timeouts"] == 2

    def test_max_drawdown(self):
        trades = [
            {"pnl_dollars": 100, "pnl_pct": 5.0, "exit_reason": "target", "duration_days": 2},
            {"pnl_dollars": -60, "pnl_pct": -3.0, "exit_reason": "stop", "duration_days": 1},
            {"pnl_dollars": -40, "pnl_pct": -2.0, "exit_reason": "stop", "duration_days": 1},
        ]
        result = _compute_metrics(trades)
        # Peak at 5%, then drops to 0% → DD = 5%
        assert result["max_drawdown_pct"] == 5.0


class TestEquityCurve:
    def test_empty(self):
        assert _build_equity_curve([]) == []

    def test_cumulative(self):
        trades = [
            {"pnl_dollars": 100, "actual_exit_time": "2026-03-28T16:00:00"},
            {"pnl_dollars": -50, "actual_exit_time": "2026-03-29T16:00:00"},
            {"pnl_dollars": 75, "actual_exit_time": "2026-03-30T16:00:00"},
        ]
        curve = _build_equity_curve(trades)
        assert len(curve) == 3
        assert curve[0]["cumulative_pnl"] == 100.0
        assert curve[1]["cumulative_pnl"] == 50.0
        assert curve[2]["cumulative_pnl"] == 125.0


class TestComparison:
    def test_single_model(self):
        result = _build_comparison([("v1", {"trades": 5, "sharpe_ratio": 0.5, "win_rate": 0.6, "profit_factor": 1.5})])
        assert result["current_vs_previous"]["previous"] is None
        assert result["current_vs_previous"]["verdict"] == "insufficient_data"

    def test_two_models_improvement(self):
        current = ("v2", {"trades": 10, "sharpe_ratio": 1.2, "win_rate": 0.7, "profit_factor": 2.0})
        previous = ("v1", {"trades": 10, "sharpe_ratio": 0.5, "win_rate": 0.6, "profit_factor": 1.5})
        result = _build_comparison([current, previous])
        assert result["current_vs_previous"]["sharpe_delta"] == 0.7
        assert result["current_vs_previous"]["verdict"] == "current_improved"

    def test_two_models_regression(self):
        current = ("v2", {"trades": 10, "sharpe_ratio": 0.3, "win_rate": 0.45, "profit_factor": 0.8})
        previous = ("v1", {"trades": 10, "sharpe_ratio": 0.8, "win_rate": 0.65, "profit_factor": 1.8})
        result = _build_comparison([current, previous])
        assert result["current_vs_previous"]["verdict"] == "current_regressed"


class TestCanaryComparison:
    def test_no_data(self):
        result = _build_canary_comparison([])
        assert result["paired_trades"] == 0
        assert result["verdict"] == "insufficient_data"

    def test_small_sample(self):
        data = [{"llm_conviction": 7, "canary_score": 3, "pnl_dollars": 100}] * 5
        result = _build_canary_comparison(data)
        assert result["paired_trades"] == 5
        assert "insufficient_data" in result["verdict"]

    def test_llm_better(self):
        data = []
        for i in range(20):
            data.append({"llm_conviction": 8, "canary_score": 3, "pnl_dollars": 100})
        for i in range(5):
            data.append({"llm_conviction": 3, "canary_score": 8, "pnl_dollars": -50})
        result = _build_canary_comparison(data)
        assert result["paired_trades"] == 25
        assert result["llm_win_rate"] > result["canary_win_rate"]


class TestGetModelPerformance:
    def test_with_data(self):
        trades = [
            ("r1", "AAPL", "halcyon-v1.0.0", "t1", 100, 2.0, "target_1", 3, "2026-03-28T16:00"),
            ("r2", "MSFT", "halcyon-v1.0.0", "t2", -50, -1.0, "stop", 2, "2026-03-29T16:00"),
            ("r3", "GOOG", "halcyon-v1.0.0", "t3", 75, 1.5, "target_1", 5, "2026-03-30T16:00"),
        ]
        db_path = _create_test_db(
            [("v1", "halcyon-v1.0.0", "2026-03-27", 979, 0.72, "active")],
            trades,
        )
        try:
            result = get_model_performance(db_path)
            assert "models" in result
            assert "comparison" in result
            assert "canary_comparison" in result
            assert len(result["models"]) >= 1

            model = next(m for m in result["models"] if m["version"] == "halcyon-v1.0.0")
            assert model["live_metrics"]["trades"] == 3
            assert model["live_metrics"]["wins"] == 2
            assert model["live_metrics"]["win_rate"] == round(2 / 3, 3)
            assert len(model["equity_curve"]) == 3
        finally:
            os.unlink(db_path)

    def test_empty_db(self):
        db_path = _create_test_db([], [])
        try:
            result = get_model_performance(db_path)
            assert result["models"] == []
            assert result["canary_comparison"]["paired_trades"] == 0
        finally:
            os.unlink(db_path)

    def test_model_with_zero_trades(self):
        db_path = _create_test_db(
            [("v1", "halcyon-v1.0.0", "2026-03-27", 979, 0.72, "active")],
            [],
        )
        try:
            result = get_model_performance(db_path)
            assert len(result["models"]) == 1
            assert result["models"][0]["live_metrics"]["trades"] == 0
        finally:
            os.unlink(db_path)


class TestCheckModelRegression:
    def test_single_model_no_alert(self):
        trades = [
            (f"r{i}", "AAPL", "v1", f"t{i}", 100 if i % 2 == 0 else -50,
             2.0 if i % 2 == 0 else -1.0, "target_1" if i % 2 == 0 else "stop",
             3, f"2026-03-{20 + i:02d}T16:00")
            for i in range(12)
        ]
        db_path = _create_test_db(
            [("vid1", "v1", "2026-03-27", 979, 0.72, "active")],
            trades,
        )
        try:
            result = check_model_regression(db_path)
            assert result["status"] == "ok"
            assert result["previous_model"] is None
        finally:
            os.unlink(db_path)

    def test_two_models_no_regression(self):
        trades_v1 = [
            (f"r1_{i}", "AAPL", "v1", f"t1_{i}", 80 if i % 2 == 0 else -40,
             1.5 if i % 2 == 0 else -0.8, "target_1" if i % 2 == 0 else "stop",
             3, f"2026-03-{10 + i:02d}T16:00")
            for i in range(12)
        ]
        trades_v2 = [
            (f"r2_{i}", "MSFT", "v2", f"t2_{i}", 100 if i % 2 == 0 else -30,
             2.0 if i % 2 == 0 else -0.6, "target_1" if i % 2 == 0 else "stop",
             3, f"2026-03-{25 + i:02d}T16:00")
            for i in range(12)
        ]
        db_path = _create_test_db(
            [("vid1", "v1", "2026-03-01", 500, 0.68, "retired"),
             ("vid2", "v2", "2026-03-20", 979, 0.72, "active")],
            trades_v1 + trades_v2,
        )
        try:
            result = check_model_regression(db_path)
            assert result["status"] in ("ok", "warning")
            assert result["current_model"] is not None
            assert result["previous_model"] is not None
            assert "details" in result
        finally:
            os.unlink(db_path)

    def test_insufficient_trades(self):
        trades = [
            ("r1", "AAPL", "v1", "t1", 100, 2.0, "target_1", 3, "2026-03-28T16:00"),
            ("r2", "MSFT", "v2", "t2", -50, -1.0, "stop", 2, "2026-03-29T16:00"),
        ]
        db_path = _create_test_db(
            [("vid1", "v1", "2026-03-01", 500, 0.68, "retired"),
             ("vid2", "v2", "2026-03-20", 979, 0.72, "active")],
            trades,
        )
        try:
            result = check_model_regression(db_path, min_trades_per_model=10)
            assert result["status"] == "ok"
            assert "Insufficient" in result["message"]
        finally:
            os.unlink(db_path)
