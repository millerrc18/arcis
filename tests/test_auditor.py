"""Tests for the auditor agent."""

import json
import sqlite3
import pytest
from datetime import datetime
from unittest.mock import patch
from pathlib import Path

from tests.conftest import init_test_db


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

    @patch("src.training.claude_client.generate_training_example")
    @patch("src.evaluation.cto_report.generate_cto_report")
    def test_deterministic_unknown_exit_ratio_forces_red(self, mock_cto, mock_claude, tmp_path):
        from src.evaluation.auditor import run_daily_audit
        from src.journal.store import initialize_database

        db_path = str(tmp_path / "audit.sqlite3")
        initialize_database(db_path)
        now = datetime.now().isoformat()
        with sqlite3.connect(db_path) as conn:
            for i in range(8):
                conn.execute(
                    "INSERT INTO shadow_trades "
                    "(trade_id, ticker, status, exit_reason, actual_exit_time, created_at, updated_at) "
                    "VALUES (?, 'AAPL', 'closed', 'unknown', ?, ?, ?)",
                    (f"unknown-{i}", now, now, now),
                )
            for i in range(2):
                conn.execute(
                    "INSERT INTO shadow_trades "
                    "(trade_id, ticker, status, exit_reason, actual_exit_time, created_at, updated_at) "
                    "VALUES (?, 'MSFT', 'closed', 'target_1', ?, ?, ?)",
                    (f"known-{i}", now, now, now),
                )
            conn.commit()

        mock_cto.return_value = {"trade_summary": {}, "by_model_version": {}}
        mock_claude.return_value = json.dumps({
            "overall_assessment": "green",
            "summary": "All systems normal.",
            "flags": [],
            "metrics_to_watch": [],
            "model_health": "healthy",
        })

        result = run_daily_audit(db_path=db_path)

        assert result["overall_assessment"] == "red"
        deterministic = result["deterministic_prechecks"]
        assert any(f["metric"] == "unknown_exit_reason_ratio" for f in deterministic)

    def test_deterministic_bracket_coverage_precheck(self, tmp_path):
        from src.evaluation.auditor import _collect_deterministic_precheck_flags
        from src.journal.store import initialize_database

        db_path = str(tmp_path / "audit.sqlite3")
        initialize_database(db_path)
        now = datetime.now().isoformat()
        with sqlite3.connect(db_path) as conn:
            conn.execute(
                "INSERT INTO shadow_trades "
                "(trade_id, ticker, status, stop_price, target_1, created_at, updated_at) "
                "VALUES ('open-no-bracket', 'AAPL', 'open', NULL, 110.0, ?, ?)",
                (now, now),
            )
            conn.commit()

        flags = _collect_deterministic_precheck_flags(db_path, {"trade_summary": {}})

        assert any(
            f["metric"] == "missing_bracket_coverage" and f["severity"] == "critical"
            for f in flags
        )

    def test_deterministic_critical_audit_blocks_new_entries_only(self, tmp_path, monkeypatch):
        from src.risk import governor as gov_module
        from src.risk.governor import RiskGovernor
        from src.training.versioning import init_training_tables

        db_path = str(tmp_path / "audit.sqlite3")
        init_training_tables(db_path)
        halt_file = str(tmp_path / "halt")
        monkeypatch.setattr(gov_module, "_HALT_FILE", halt_file)

        full_report = {
            "deterministic_prechecks": [{
                "severity": "critical",
                "source": "deterministic_precheck",
                "description": "Unknown exit reasons are 80% of recent closed trades.",
            }]
        }
        with sqlite3.connect(db_path) as conn:
            conn.execute(
                "INSERT INTO audit_reports "
                "(audit_id, created_at, audit_date, overall_assessment, summary, "
                "flags, metrics_to_watch, model_health, full_report) "
                "VALUES ('a1', ?, '2026-05-16', 'red', 'critical', '[]', '[]', 'degrading', ?)",
                (datetime.now().isoformat(), json.dumps(full_report)),
            )
            conn.commit()

        result = RiskGovernor({"risk_governor": {"enabled": True}}).check_trade(
            ticker="AAPL",
            allocation_dollars=1000.0,
            features={},
            portfolio={"db_path": db_path},
        )

        assert result["approved"] is False
        assert "deterministic audit is critical" in result["rejection_reason"]
        assert not Path(halt_file).exists()


class TestEscalation:
    def test_critical_flag_alerts_operator_no_auto_halt(self, tmp_path, monkeypatch):
        """Operator policy 2026-05-08: kill switch is operator-action-only.

        The auditor must NOT auto-halt on CRITICAL flags. It must escalate via
        email + logger.critical and append an `operator_action_required` action
        so the operator decides whether to halt manually.
        """
        from src.evaluation.auditor import check_escalation
        from src.risk import governor as gov_module

        halt_file = str(tmp_path / "halt")
        monkeypatch.setattr(gov_module, "_HALT_FILE", halt_file)

        # Create a DB with 50+ closed trades so we exit bootcamp mode
        db_path = str(tmp_path / "test.sqlite3")
        init_test_db(db_path, ["shadow_trades"])
        conn = sqlite3.connect(db_path)
        for i in range(55):
            conn.execute(
                "INSERT INTO shadow_trades (trade_id, ticker, status, created_at, updated_at) "
                "VALUES (?, 'TEST', 'closed', '2026-01-01T00:00:00', '2026-01-01T00:00:00')",
                (f"t{i}",),
            )
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

        # Auto-halt is disabled — halt file must NOT appear
        assert not Path(halt_file).exists(), "auditor must not auto-halt"
        # No "halt_trading" action — only "operator_action_required" + "email_alert"
        assert not any(a["action"] == "halt_trading" for a in actions)
        assert any(a["action"] == "operator_action_required" for a in actions)
        assert any(a["action"] == "email_alert" for a in actions)

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

    def test_risk_governor_breach_never_downgraded_in_bootcamp(self, tmp_path, monkeypatch):
        """Safety CRITICALs must bypass bootcamp downgrade — but never auto-halt.

        Operator policy 2026-05-08: kill switch is operator-action-only. Even
        for risk_governor_breach / emergency_halt_bypass categories that signal
        loss of containment, the auditor must NOT auto-halt — it must escalate
        via email + critical log + `operator_action_required` action so the
        operator decides whether to halt manually.

        Bootcamp downgrade still does NOT apply to _NEVER_DOWNGRADE categories
        (so the alert keeps critical severity instead of being downgraded to
        alert) — but the only path-difference is the alert text + severity tag,
        not whether trading auto-halts.
        """
        from src.evaluation.auditor import check_escalation
        from src.risk import governor as gov_module

        halt_file = str(tmp_path / "halt")
        monkeypatch.setattr(gov_module, "_HALT_FILE", halt_file)

        # Few trades → bootcamp_mode=True in check_escalation
        db_path = str(tmp_path / "test.sqlite3")
        init_test_db(db_path, ["shadow_trades"])
        conn = sqlite3.connect(db_path)
        conn.execute(
            "INSERT INTO shadow_trades (trade_id, ticker, status, created_at, updated_at) "
            "VALUES ('t1', 'TEST', 'closed', '2026-01-01T00:00:00', '2026-01-01T00:00:00')",
        )
        conn.commit()
        conn.close()

        with patch("src.email.notifier.send_email", return_value=True):
            audit = {
                "flags": [{
                    "severity": "critical",
                    "category": "risk_governor_breach",
                    "description": "Governor check bypassed",
                    "recommendation": "Halt immediately",
                }],
            }
            actions = check_escalation(audit, db_path=db_path)

        # Auto-halt is disabled — even for safety-critical categories
        assert not Path(halt_file).exists(), (
            "auditor must not auto-halt risk_governor_breach (operator-only kill-switch policy)"
        )
        assert not any(a["action"] == "halt_trading" for a in actions)
        # But severity stays critical (NOT downgraded to alert despite bootcamp mode)
        assert any(
            a["action"] == "operator_action_required" and a["severity"] == "critical"
            for a in actions
        ), "risk_governor_breach must keep critical severity even in bootcamp mode"

    def test_emergency_halt_bypass_alerts_operator_no_auto_halt(self, tmp_path, monkeypatch):
        """Operator policy 2026-05-08: emergency_halt_bypass keeps critical
        severity (not downgraded by bootcamp) but does NOT auto-halt.
        Operator decides whether to halt via CLI/dashboard/API."""
        from src.evaluation.auditor import check_escalation
        from src.risk import governor as gov_module

        halt_file = str(tmp_path / "halt")
        monkeypatch.setattr(gov_module, "_HALT_FILE", halt_file)

        db_path = str(tmp_path / "test.sqlite3")
        init_test_db(db_path, ["shadow_trades"])

        with patch("src.email.notifier.send_email", return_value=True):
            audit = {
                "flags": [{
                    "severity": "critical",
                    "category": "emergency_halt_bypass",
                    "description": "Halt command ignored",
                    "recommendation": "Investigate",
                }],
            }
            actions = check_escalation(audit, db_path=db_path)

        assert not Path(halt_file).exists(), (
            "auditor must not auto-halt emergency_halt_bypass (operator-only kill-switch policy)"
        )
        assert not any(a["action"] == "halt_trading" for a in actions)
        assert any(
            a["action"] == "operator_action_required" and a["severity"] == "critical"
            for a in actions
        ), "emergency_halt_bypass must keep critical severity despite bootcamp mode"

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

    def test_post_bootcamp_config_prevents_critical_downgrade(self, tmp_path, monkeypatch):
        """Post-bootcamp graduation override pins bootcamp_mode False permanently.

        Wave 4 H7 (2026-05-04, post Stage 1 baseline signing d651160) — operator
        declared post-bootcamp via live_trading.post_bootcamp=true in config.
        Even with closed_count < 50 (which would normally trigger
        bootcamp_mode=True and downgrade ordinary CRITICAL flags), the
        override keeps critical halts active.

        This test is the regression-lock for the Wave 4 H5 sibling effect:
        when H5 filters reconciled_stale from the closed-trade count, the
        count drops from 50 to 6 — without this override, bootcamp_mode
        would auto-flip back to True, regressing operational alert
        sensitivity post-graduation.
        """
        from src.evaluation import auditor as auditor_module
        from src.evaluation.auditor import check_escalation
        from src.risk import governor as gov_module

        halt_file = str(tmp_path / "halt")
        monkeypatch.setattr(gov_module, "_HALT_FILE", halt_file)

        # Mock load_config (bound in auditor module) to return post_bootcamp=true
        monkeypatch.setattr(
            auditor_module, "load_config",
            lambda: {"live_trading": {"post_bootcamp": True}},
        )

        # Few trades — would normally trigger bootcamp_mode=True
        db_path = str(tmp_path / "test.sqlite3")
        init_test_db(db_path, ["shadow_trades"])
        conn = sqlite3.connect(db_path)
        conn.execute(
            "INSERT INTO shadow_trades (trade_id, ticker, status, created_at, updated_at) "
            "VALUES ('t1', 'TEST', 'closed', '2026-01-01T00:00:00', '2026-01-01T00:00:00')",
        )
        conn.commit()
        conn.close()

        with patch("src.email.notifier.send_email", return_value=True):
            audit = {
                "flags": [{
                    "severity": "critical",
                    "category": "anomaly",  # Not in _NEVER_DOWNGRADE
                    "description": "Catastrophic loss detected",
                    "recommendation": "Halt immediately",
                }],
            }
            actions = check_escalation(audit, db_path=db_path)

        # post_bootcamp=True must prevent bootcamp downgrade — the flag keeps
        # critical severity. But operator policy 2026-05-08: kill switch is
        # operator-only; auditor must NOT auto-halt regardless. The regression
        # this test locks is "config override prevents severity downgrade",
        # not "auto-halt fires".
        assert not Path(halt_file).exists(), (
            "auditor must not auto-halt (operator-only kill-switch policy)"
        )
        assert not any(a["action"] == "halt_trading" for a in actions)
        assert any(
            a["action"] == "operator_action_required" and a["severity"] == "critical"
            for a in actions
        ), "post_bootcamp=true must keep critical severity even with <50 trades"

    def test_post_bootcamp_default_false_preserves_bootcamp_behavior(self, tmp_path, monkeypatch):
        """Default post_bootcamp=False preserves prior bootcamp downgrade behavior.

        Companion test to ensure adding the override doesn't accidentally break
        fresh installs (where post_bootcamp is unset / False). With <50 trades
        and post_bootcamp=False, an ordinary CRITICAL flag still gets
        downgraded to alert as before.
        """
        from src.evaluation import auditor as auditor_module
        from src.evaluation.auditor import check_escalation
        from src.risk import governor as gov_module

        halt_file = str(tmp_path / "halt")
        monkeypatch.setattr(gov_module, "_HALT_FILE", halt_file)

        # Mock load_config to return post_bootcamp=false (default)
        monkeypatch.setattr(
            auditor_module, "load_config",
            lambda: {"live_trading": {"post_bootcamp": False}},
        )

        db_path = str(tmp_path / "test.sqlite3")
        init_test_db(db_path, ["shadow_trades"])
        conn = sqlite3.connect(db_path)
        conn.execute(
            "INSERT INTO shadow_trades (trade_id, ticker, status, created_at, updated_at) "
            "VALUES ('t1', 'TEST', 'closed', '2026-01-01T00:00:00', '2026-01-01T00:00:00')",
        )
        conn.commit()
        conn.close()

        with patch("src.email.notifier.send_email", return_value=True):
            audit = {
                "flags": [{
                    "severity": "critical",
                    "category": "anomaly",
                    "description": "Strategy drift detected",
                    "recommendation": "Review trades",
                }],
            }
            actions = check_escalation(audit, db_path=db_path)

        # post_bootcamp=False with N<50 → bootcamp_mode=True → flag downgraded
        # to alert → no halt action
        assert not any(a["action"] == "halt_trading" for a in actions), (
            "post_bootcamp=false (default) preserves bootcamp downgrade for <50 trades"
        )
