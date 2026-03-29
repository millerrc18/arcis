"""Tests for the auditor agent."""

import json
import sqlite3
import pytest
from unittest.mock import patch
from pathlib import Path


@pytest.fixture
def db_path(tmp_path):
    db = str(tmp_path / "test.sqlite3")
    from src.training.versioning import init_training_tables
    init_training_tables(db)
    return db


class TestDailyAudit:
    @patch("src.training.claude_client.generate_training_example")
    @patch("src.evaluation.cto_report.generate_cto_report")
    def test_generates_assessment(self, mock_cto, mock_claude, db_path):
        from src.evaluation.auditor import run_daily_audit

        mock_cto.return_value = {"trade_summary": {"trades_closed": 5}}
        mock_claude.return_value = json.dumps({
            "overall_assessment": "green",
            "summary": "All systems normal.",
            "flags": [],
            "metrics_to_watch": [],
            "model_health": "healthy",
        })

        result = run_daily_audit(db_path=db_path)
        assert result["overall_assessment"] == "green"
        assert result["model_health"] == "healthy"

    @patch("src.training.claude_client.generate_training_example")
    @patch("src.evaluation.cto_report.generate_cto_report")
    def test_stores_in_database(self, mock_cto, mock_claude, db_path):
        from src.evaluation.auditor import run_daily_audit

        mock_cto.return_value = {}
        mock_claude.return_value = json.dumps({
            "overall_assessment": "yellow",
            "summary": "Minor concern.",
            "flags": [{"severity": "warning", "category": "drift",
                        "description": "test", "recommendation": "test"}],
            "metrics_to_watch": ["win_rate"],
            "model_health": "healthy",
        })

        run_daily_audit(db_path=db_path)

        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM audit_reports").fetchone()

        assert row is not None
        assert row["overall_assessment"] == "yellow"

    @patch("src.training.claude_client.generate_training_example")
    @patch("src.evaluation.cto_report.generate_cto_report")
    def test_handles_claude_unavailable(self, mock_cto, mock_claude, db_path):
        from src.evaluation.auditor import run_daily_audit

        mock_cto.return_value = {}
        mock_claude.return_value = None  # API unavailable

        result = run_daily_audit(db_path=db_path)
        assert result["overall_assessment"] == "green"  # Default safe


class TestEscalation:
    def test_critical_flag_halts_trading(self, tmp_path, monkeypatch):
        from src.evaluation.auditor import check_escalation
        from src.risk import governor as gov_module

        halt_file = str(tmp_path / "halt")
        monkeypatch.setattr(gov_module, "_HALT_FILE", halt_file)

        # Create a DB with 50+ closed trades so we exit bootcamp mode
        db_path = str(tmp_path / "test.sqlite3")
        import sqlite3
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE shadow_trades (trade_id TEXT, status TEXT)")
        for i in range(55):
            conn.execute("INSERT INTO shadow_trades VALUES (?, 'closed')", (f"t{i}",))
        conn.commit()
        conn.close()

        # Mock email to prevent actual sending
        with patch("src.email.notifier.send_email", return_value=True):
            audit = {
                "flags": [{
                    "severity": "critical",
                    "category": "anomaly",
                    "description": "Catastrophic loss detected",
                    "recommendation": "Halt immediately",
                }],
            }
            actions = check_escalation(audit, db_path=db_path)

        assert any(a["action"] == "halt_trading" for a in actions)
        assert Path(halt_file).exists()

    def test_alert_flag_sends_email_only(self):
        from src.evaluation.auditor import check_escalation

        with patch("src.email.notifier.send_email", return_value=True):
            audit = {
                "flags": [{
                    "severity": "alert",
                    "category": "drift",
                    "description": "Strategy drift detected",
                    "recommendation": "Review trades",
                }],
            }
            actions = check_escalation(audit)

        assert any(a["action"] == "email_alert" for a in actions)
        assert not any(a["action"] == "halt_trading" for a in actions)

    def test_warning_flag_logs_only(self):
        from src.evaluation.auditor import check_escalation

        audit = {
            "flags": [{
                "severity": "warning",
                "category": "concentration",
                "description": "Slight concentration",
                "recommendation": "Monitor",
            }],
        }
        actions = check_escalation(audit)
        assert all(a["action"] == "log_only" for a in actions)
