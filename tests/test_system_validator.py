"""Tests for the system validation engine."""

import json
import os
import sqlite3
import tempfile
from unittest.mock import patch, MagicMock

import pytest


@pytest.fixture
def tmp_db():
    """Create a temporary SQLite database with core schema from registry."""
    fd, path = tempfile.mkstemp(suffix=".sqlite3")
    os.close(fd)
    from tests.conftest import init_test_db
    init_test_db(path)  # create all tables from registry
    conn = sqlite3.connect(path)
    # Insert some sample data
    conn.execute(
        "INSERT INTO recommendations (recommendation_id, created_at, ticker) VALUES ('rec1', '2026-03-28T10:00:00', 'AAPL')"
    )
    conn.execute(
        "INSERT INTO shadow_trades (trade_id, recommendation_id, ticker, status, created_at, updated_at) VALUES ('t1', 'rec1', 'AAPL', 'closed', '2026-03-27T10:00:00', '2026-03-28T10:00:00')"
    )
    for i in range(150):
        conn.execute(
            "INSERT INTO training_examples (example_id, created_at, source, instruction, input_text, output_text, quality_score_auto) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (f"ex{i}", "2026-03-28T10:00:00", "backfill", "evaluate", "input", "output", 75.0 + (i % 20)),
        )
    conn.execute(
        "INSERT INTO model_versions (version_id, version_name, status, created_at) VALUES ('v1', 'halcyon-v1.0.0', 'released', '2026-03-25T10:00:00')"
    )
    conn.commit()
    conn.close()
    yield path
    try:
        os.unlink(path)
    except PermissionError:
        pass


@pytest.fixture
def mock_config():
    return {
        "alpaca": {"api_key": "test_key", "api_secret": "test_secret"},
        "shadow_trading": {"enabled": True, "max_positions": 10, "timeout_days": 10},
        "live_trading": {"enabled": False},
        "risk_governor": {"enabled": True},
        "risk": {"starting_capital": 100000},
        "training": {"enabled": True, "anthropic_api_key": "sk-ant-test-key-1234567890"},
        "llm": {"enabled": True, "model": "qwen3:8b", "base_url": "http://localhost:11434"},
        "telegram": {"enabled": False},
        "email": {},
        "render": {"enabled": False},
        "data_enrichment": {"finnhub_api_key": "test", "fred_api_key": "test"},
    }


class TestCheckDatabase:
    def test_existing_db(self, tmp_db):
        from src.evaluation.system_validator import _check_database
        checks = _check_database(tmp_db)
        assert len(checks) >= 4
        assert checks[0]["status"] == "pass"  # file exists
        assert checks[1]["status"] == "pass"  # file size

    def test_missing_db(self):
        from src.evaluation.system_validator import _check_database
        checks = _check_database("/nonexistent/path.sqlite3")
        assert checks[0]["status"] == "fail"
        assert "not found" in checks[0]["detail"]

    def test_data_in_tables(self, tmp_db):
        from src.evaluation.system_validator import _check_database
        checks = _check_database(tmp_db)
        names = {c["name"] for c in checks}
        assert "db_recommendations_data" in names
        rec_check = next(c for c in checks if c["name"] == "db_recommendations_data")
        assert rec_check["status"] == "pass"
        assert "1 rows" in rec_check["detail"]


class TestCheckTrading:
    @patch("src.evaluation.system_validator.load_config")
    def test_risk_config_ok(self, mock_load, tmp_db, mock_config):
        mock_load.return_value = mock_config
        from src.evaluation.system_validator import _check_trading
        # Mock Alpaca call to avoid real API
        with patch("src.shadow_trading.alpaca_adapter.get_account_info",
                    side_effect=Exception("No API")):
            checks = _check_trading(tmp_db, mock_config)
        names = {c["name"] for c in checks}
        assert "trading_risk_config" in names
        risk_check = next(c for c in checks if c["name"] == "trading_risk_config")
        assert risk_check["status"] == "pass"

    @patch("src.evaluation.system_validator.load_config")
    def test_no_zombie_trades(self, mock_load, tmp_db, mock_config):
        mock_load.return_value = mock_config
        from src.evaluation.system_validator import _check_trading
        with patch("src.shadow_trading.alpaca_adapter.get_account_info",
                    side_effect=Exception("No API")):
            checks = _check_trading(tmp_db, mock_config)
        zombie_check = next(c for c in checks if c["name"] == "trading_zombie_trades")
        assert zombie_check["status"] == "pass"


class TestCheckTraining:
    def test_training_checks(self, tmp_db, mock_config):
        from src.evaluation.system_validator import _check_training
        checks = _check_training(tmp_db, mock_config)
        assert len(checks) >= 5
        names = {c["name"] for c in checks}
        assert "training_example_count" in names
        assert "training_claude_api" in names
        count_check = next(c for c in checks if c["name"] == "training_example_count")
        assert count_check["status"] == "pass"
        assert "150" in count_check["detail"]


class TestRunFullValidation:
    @patch("src.evaluation.system_validator.load_config")
    def test_returns_expected_shape(self, mock_load, tmp_db, mock_config):
        mock_load.return_value = mock_config
        from src.evaluation.system_validator import run_full_validation
        with patch("src.shadow_trading.alpaca_adapter.get_account_info",
                    side_effect=Exception("No API")):
            result = run_full_validation(db_path=tmp_db)
        assert "timestamp" in result
        assert "overall_status" in result
        assert result["overall_status"] in ("healthy", "degraded", "critical")
        assert "checks_passed" in result
        assert "checks_failed" in result
        assert "checks_warning" in result
        assert "checks_total" in result
        assert "categories" in result
        assert set(result["categories"].keys()) == {
            "database", "trading", "training", "api",
            "collectors", "notifications", "scheduler", "llm",
        }
        assert result["checks_total"] == (
            result["checks_passed"] + result["checks_failed"] + result["checks_warning"]
        )


class TestSaveValidationResult:
    def test_save_and_retrieve(self, tmp_db):
        from src.evaluation.system_validator import save_validation_result
        result = {
            "timestamp": "2026-03-28T16:30:00",
            "overall_status": "healthy",
            "checks_passed": 40,
            "checks_failed": 0,
            "checks_warning": 5,
            "categories": {},
        }
        rid = save_validation_result(result, db_path=tmp_db)
        assert rid
        conn = sqlite3.connect(tmp_db)
        row = conn.execute(
            "SELECT * FROM validation_results WHERE result_id = ?", (rid,)
        ).fetchone()
        conn.close()
        assert row is not None
        assert row[2] == "healthy"  # overall_status


class TestNotifyValidationSummary:
    def test_silent_on_all_pass(self):
        from src.notifications.telegram import notify_validation_summary
        with patch("src.notifications.telegram.is_telegram_enabled", return_value=True):
            result = {
                "checks_passed": 50, "checks_failed": 0, "checks_warning": 0,
                "checks_total": 50, "overall_status": "healthy", "categories": {},
            }
            ok = notify_validation_summary(result)
            assert ok is True  # silent success

    def test_sends_on_failures(self):
        from src.notifications.telegram import notify_validation_summary
        with patch("src.notifications.telegram.is_telegram_enabled", return_value=True), \
             patch("src.notifications.telegram.send_telegram", return_value=True) as mock_send:
            result = {
                "checks_passed": 40, "checks_failed": 2, "checks_warning": 3,
                "checks_total": 45, "overall_status": "critical",
                "categories": {
                    "database": [
                        {"name": "db_test", "status": "fail", "detail": "test failure", "last_verified": ""},
                    ],
                },
            }
            ok = notify_validation_summary(result)
            assert ok is True
            mock_send.assert_called_once()
            msg = mock_send.call_args[0][0]
            assert "SYSTEM VALIDATION" in msg
            assert "CRITICAL" in msg
