"""Tests for executor-level run-regime-diagnostic + run-forensic-audit handlers."""

import sqlite3

import pytest

from src.commands.executor import COMMAND_HANDLERS
from tests.conftest import init_test_db


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "test.sqlite3"
    init_test_db(str(path), tables=["diagnostic_runs", "diagnostic_run_plots"])
    conn = sqlite3.connect(str(path))
    conn.execute(
        "INSERT INTO diagnostic_runs "
        "(run_id, diagnostic_type, status, trigger_source, triggered_by, "
        "created_at, updated_at, payload_json) VALUES "
        "('r-1', 'regime', 'queued', 'dashboard', 'op@x.com', "
        "'2026-04-18T10:00:00-04:00', '2026-04-18T10:00:00-04:00', '{}')"
    )
    conn.commit()
    conn.close()
    return str(path)


def test_run_regime_diagnostic_handler_registered():
    assert "run-regime-diagnostic" in COMMAND_HANDLERS
    assert "run-forensic-audit" in COMMAND_HANDLERS


def test_run_regime_diagnostic_invokes_runner(db, monkeypatch):
    captured = {}

    def fake_runner(**kwargs):
        captured.update(kwargs)
        return {"status": "completed", "exit_code": 0,
                "summary": {"decision": "PENDING"}}

    monkeypatch.setattr(
        "src.diagnostics.dashboard_runner.run_diagnostic", fake_runner,
    )

    handler = COMMAND_HANDLERS["run-regime-diagnostic"]
    payload = {"run_id": "r-1", "db_path": db, "exclude_quarantined": True}
    result = handler(payload, config={})

    assert result["status"] == "completed"
    assert captured["run_id"] == "r-1"
    assert "--exclude-quarantined" in captured["script_args"]
    assert "regime_diagnostic_v1.py" in captured["script_path"]
    assert captured["db_path"] == db


def test_run_regime_diagnostic_with_bootstrap_n(db, monkeypatch):
    captured = {}

    def fake_runner(**kwargs):
        captured.update(kwargs)
        return {"status": "completed", "exit_code": 0}

    monkeypatch.setattr(
        "src.diagnostics.dashboard_runner.run_diagnostic", fake_runner,
    )
    handler = COMMAND_HANDLERS["run-regime-diagnostic"]
    handler({"run_id": "r-1", "db_path": db, "bootstrap_n": 5000}, config={})
    assert "--bootstrap-n" in captured["script_args"]
    assert "5000" in captured["script_args"]


def test_run_regime_diagnostic_missing_run_id():
    handler = COMMAND_HANDLERS["run-regime-diagnostic"]
    result = handler({}, config={})
    assert "error" in result
    assert "run_id" in result["error"]


def test_run_forensic_audit_invokes_runner(db, monkeypatch):
    captured = {}

    def fake_runner(**kwargs):
        captured.update(kwargs)
        return {"status": "completed", "exit_code": 0,
                "summary": {"n_total": 88}}

    monkeypatch.setattr(
        "src.diagnostics.dashboard_runner.run_diagnostic", fake_runner,
    )
    handler = COMMAND_HANDLERS["run-forensic-audit"]
    result = handler({"run_id": "r-1", "db_path": db}, config={})
    assert result["status"] == "completed"
    assert "forensic_trade_audit_v1.py" in captured["script_path"]


def test_run_forensic_audit_missing_run_id():
    handler = COMMAND_HANDLERS["run-forensic-audit"]
    result = handler({}, config={})
    assert "error" in result
