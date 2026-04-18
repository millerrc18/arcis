"""Tests for dashboard_runner — orchestrates diagnostic script execution."""

import base64
import sqlite3
import subprocess
from pathlib import Path

import pytest

from tests.conftest import init_test_db


@pytest.fixture
def db(tmp_path):
    """Fresh SQLite with diagnostic_runs + diagnostic_run_plots."""
    path = tmp_path / "test.sqlite3"
    init_test_db(str(path), tables=["diagnostic_runs", "diagnostic_run_plots"])
    conn = sqlite3.connect(str(path))
    # Seed a queued row (simulates API-side insert)
    conn.execute(
        "INSERT INTO diagnostic_runs "
        "(run_id, diagnostic_type, status, trigger_source, triggered_by, "
        "created_at, updated_at, payload_json) VALUES "
        "('run-001', 'regime', 'queued', 'dashboard', 'test@example.com', "
        "'2026-04-18T10:00:00-04:00', '2026-04-18T10:00:00-04:00', '{}')"
    )
    conn.commit()
    conn.close()
    return str(path)


def test_runner_transitions_running_then_completed(db, tmp_path, monkeypatch):
    """Happy path: subprocess writes report + plots, row goes queued->completed."""
    from src.diagnostics.dashboard_runner import run_diagnostic
    from src.diagnostics.summary_extractor import parse_regime_report

    report_path = tmp_path / "report.md"
    plot_dir = tmp_path / "plots"
    plot_dir.mkdir()

    def fake_subprocess(cmd, **kwargs):
        report_path.write_text(
            "## Executive Summary\n\n**Decision:** CONTAMINATED\n\n"
            "**N = 42**\n\nMean excess return: 0.0015\n",
            encoding="utf-8",
        )
        (plot_dir / "vix_regression.png").write_bytes(b"\x89PNG\r\n\x1a\nFAKE")
        return subprocess.CompletedProcess(cmd, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_subprocess)

    result = run_diagnostic(
        run_id="run-001",
        script_path="scripts/diagnostics/regime_diagnostic_v1.py",
        script_args=["--db", "dummy.sqlite3"],
        report_parser=parse_regime_report,
        report_path=str(report_path),
        plot_dir=str(plot_dir),
        db_path=db,
        timeout_s=900,
    )

    assert result["status"] == "completed"
    assert result["exit_code"] == 0

    conn = sqlite3.connect(db)
    row = conn.execute(
        "SELECT status, exit_code, summary_json FROM diagnostic_runs "
        "WHERE run_id = 'run-001'"
    ).fetchone()
    assert row[0] == "completed"
    assert row[1] == 0
    assert "CONTAMINATED" in row[2]

    plots = conn.execute(
        "SELECT filename, content_b64 FROM diagnostic_run_plots "
        "WHERE run_id = 'run-001'"
    ).fetchall()
    assert len(plots) == 1
    assert plots[0][0] == "vix_regression.png"
    expected_b64 = base64.b64encode(b"\x89PNG\r\n\x1a\nFAKE").decode("ascii")
    assert plots[0][1] == expected_b64
    conn.close()


def test_runner_records_failure_on_nonzero_exit(db, tmp_path, monkeypatch):
    from src.diagnostics.dashboard_runner import run_diagnostic
    from src.diagnostics.summary_extractor import parse_regime_report

    report_path = tmp_path / "report.md"
    plot_dir = tmp_path / "plots"
    plot_dir.mkdir()

    def failing_subprocess(cmd, **kwargs):
        return subprocess.CompletedProcess(
            cmd, returncode=1, stdout="", stderr="Boom" * 1000,
        )

    monkeypatch.setattr(subprocess, "run", failing_subprocess)

    result = run_diagnostic(
        run_id="run-001",
        script_path="scripts/diagnostics/regime_diagnostic_v1.py",
        script_args=[],
        report_parser=parse_regime_report,
        report_path=str(report_path),
        plot_dir=str(plot_dir),
        db_path=db,
        timeout_s=900,
    )
    assert result["status"] == "failed"
    assert result["exit_code"] == 1

    conn = sqlite3.connect(db)
    row = conn.execute(
        "SELECT status, stderr_tail FROM diagnostic_runs WHERE run_id = 'run-001'"
    ).fetchone()
    assert row[0] == "failed"
    assert len(row[1]) <= 2048
    conn.close()


def test_runner_records_failure_on_timeout(db, tmp_path, monkeypatch):
    from src.diagnostics.dashboard_runner import run_diagnostic
    from src.diagnostics.summary_extractor import parse_regime_report

    report_path = tmp_path / "report.md"
    plot_dir = tmp_path / "plots"
    plot_dir.mkdir()

    def timeout_subprocess(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd, 900)

    monkeypatch.setattr(subprocess, "run", timeout_subprocess)

    result = run_diagnostic(
        run_id="run-001",
        script_path="scripts/diagnostics/regime_diagnostic_v1.py",
        script_args=[],
        report_parser=parse_regime_report,
        report_path=str(report_path),
        plot_dir=str(plot_dir),
        db_path=db,
        timeout_s=900,
    )
    assert result["status"] == "failed"
    assert "Timed out" in result["stderr_tail"]
