"""End-to-end smoke test: handler -> subprocess -> report stored inline.

Uses a fake subprocess to avoid the 3-5 min real diagnostic runtime.
Verifies the complete data flow from executor dispatch to
diagnostic_runs row transition + diagnostic_run_plots inserts.
"""

import json
import sqlite3
import subprocess
from pathlib import Path

import pytest

from src.commands.executor import COMMAND_HANDLERS
from tests.conftest import init_test_db


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "test.sqlite3"
    init_test_db(
        str(path),
        tables=[
            "diagnostic_runs", "diagnostic_run_plots",
            "pending_commands", "command_results",
        ],
    )
    conn = sqlite3.connect(str(path))
    conn.execute(
        "INSERT INTO diagnostic_runs "
        "(run_id, diagnostic_type, status, trigger_source, triggered_by, "
        "payload_json, created_at, updated_at) VALUES "
        "('smoke-1', 'regime', 'queued', 'dashboard', 'test@local', "
        "'{}', '2026-04-18T10:00:00-04:00', '2026-04-18T10:00:00-04:00')"
    )
    conn.commit()
    conn.close()
    return str(path)


def test_end_to_end_regime_run(db, tmp_path, monkeypatch):
    """Handler-dispatched regime run persists report + plots end-to-end."""
    # Handler writes to relative paths under docs/diagnostics/ — isolate via
    # cwd-pivot so tests don't pollute the real working tree.
    monkeypatch.chdir(tmp_path)

    def fake_subprocess(cmd, **kwargs):
        output = plot_dir = None
        for i, arg in enumerate(cmd):
            if arg == "--output": output = cmd[i + 1]
            if arg == "--plot-dir": plot_dir = cmd[i + 1]
        Path(output).parent.mkdir(parents=True, exist_ok=True)
        Path(output).write_text(
            "## Executive Summary\n\n**Decision:** PENDING\n\n"
            "**N = 88**\n\nMean excess return: 0.0005\n",
            encoding="utf-8",
        )
        Path(plot_dir).mkdir(parents=True, exist_ok=True)
        (Path(plot_dir) / "p1.png").write_bytes(b"fake1")
        (Path(plot_dir) / "p2.png").write_bytes(b"fake2")
        return subprocess.CompletedProcess(
            cmd, returncode=0, stdout="", stderr="",
        )

    monkeypatch.setattr(subprocess, "run", fake_subprocess)

    handler = COMMAND_HANDLERS["run-regime-diagnostic"]
    result = handler(
        {"run_id": "smoke-1", "db_path": db},
        config={},
    )

    assert result["status"] == "completed"
    assert result["plot_count"] == 2

    conn = sqlite3.connect(db)
    row = conn.execute(
        "SELECT status, summary_json FROM diagnostic_runs "
        "WHERE run_id='smoke-1'"
    ).fetchone()
    assert row[0] == "completed"
    summary = json.loads(row[1])
    assert summary["decision"] == "PENDING"
    assert summary["n_total"] == 88

    plot_count = conn.execute(
        "SELECT COUNT(*) FROM diagnostic_run_plots WHERE run_id='smoke-1'"
    ).fetchone()[0]
    assert plot_count == 2
    conn.close()


def test_end_to_end_forensic_run(db, tmp_path, monkeypatch):
    """Forensic handler → completed row with parsed summary."""
    monkeypatch.chdir(tmp_path)
    # Re-seed with forensic type
    conn = sqlite3.connect(db)
    conn.execute("DELETE FROM diagnostic_runs")
    conn.execute(
        "INSERT INTO diagnostic_runs "
        "(run_id, diagnostic_type, status, trigger_source, triggered_by, "
        "payload_json, created_at, updated_at) VALUES "
        "('smoke-f', 'forensic', 'queued', 'dashboard', 'test@local', "
        "'{}', '2026-04-18T10:00:00-04:00', '2026-04-18T10:00:00-04:00')"
    )
    conn.commit()
    conn.close()

    def fake_subprocess(cmd, **kwargs):
        output = plot_dir = None
        for i, arg in enumerate(cmd):
            if arg == "--output": output = cmd[i + 1]
            if arg == "--plot-dir": plot_dir = cmd[i + 1]
        Path(output).parent.mkdir(parents=True, exist_ok=True)
        Path(output).write_text(
            "## Executive Summary\n\n"
            "Analyzed **88** closed trades.\n\n"
            "### 3 Most Surprising Findings\n\n"
            "- Finding one\n- Finding two\n- Finding three\n",
            encoding="utf-8",
        )
        Path(plot_dir).mkdir(parents=True, exist_ok=True)
        return subprocess.CompletedProcess(
            cmd, returncode=0, stdout="", stderr="",
        )

    monkeypatch.setattr(subprocess, "run", fake_subprocess)

    handler = COMMAND_HANDLERS["run-forensic-audit"]
    result = handler({"run_id": "smoke-f", "db_path": db}, config={})

    assert result["status"] == "completed"
    summary = result["summary"]
    assert summary["n_total"] == 88
    assert "Finding one" in summary["findings_raw"]
