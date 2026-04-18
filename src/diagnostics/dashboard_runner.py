"""Runs diagnostic scripts for the cloud dashboard and persists results.

Orchestrates the full lifecycle: subprocess invocation, report read,
plot scanning + base64 encoding, SQLite writes for status transitions
and plot inserts. Handlers in src.commands.executor delegate here.

Called by: src.commands.executor (via _handle_run_regime_diagnostic, etc.)
Calls: src.diagnostics.summary_extractor
Owns tables: diagnostic_runs, diagnostic_run_plots (writes)
Config keys: none
Tests: tests/diagnostics/test_dashboard_runner.py
"""

from __future__ import annotations

import base64
import json
import logging
import sqlite3
import subprocess
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Callable
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")
STDERR_TAIL_BYTES = 2048


def _now_iso() -> str:
    return datetime.now(ET).isoformat()


def _update_run_status(
    conn: sqlite3.Connection,
    run_id: str,
    *,
    status: str,
    started_at: str | None = None,
    completed_at: str | None = None,
    exit_code: int | None = None,
    report_markdown: str | None = None,
    summary_json: str | None = None,
    stderr_tail: str | None = None,
) -> None:
    """Merge-style UPDATE on diagnostic_runs; INSERT if row absent.

    The API-side inserts the row with status='queued' in Postgres; by the
    time the local handler runs, render_sync may or may not have pulled
    it down to SQLite. This helper handles both cases.
    """
    now = _now_iso()
    existing = conn.execute(
        "SELECT run_id FROM diagnostic_runs WHERE run_id = ?",
        (run_id,),
    ).fetchone()
    if existing is None:
        conn.execute(
            "INSERT INTO diagnostic_runs "
            "(run_id, diagnostic_type, status, trigger_source, triggered_by, "
            "started_at, completed_at, exit_code, report_markdown, "
            "summary_json, stderr_tail, created_at, updated_at) "
            "VALUES (?, 'unknown', ?, 'dashboard', 'system', ?, ?, ?, ?, ?, ?, ?, ?)",
            (run_id, status, started_at, completed_at, exit_code,
             report_markdown, summary_json, stderr_tail, now, now),
        )
        return

    sets = ["status = ?", "updated_at = ?"]
    params: list = [status, now]
    for col, val in [
        ("started_at", started_at),
        ("completed_at", completed_at),
        ("exit_code", exit_code),
        ("report_markdown", report_markdown),
        ("summary_json", summary_json),
        ("stderr_tail", stderr_tail),
    ]:
        if val is not None:
            sets.append(f"{col} = ?")
            params.append(val)
    params.append(run_id)
    conn.execute(
        f"UPDATE diagnostic_runs SET {', '.join(sets)} WHERE run_id = ?",
        tuple(params),
    )


def _insert_plots(conn: sqlite3.Connection, run_id: str, plot_dir: Path) -> int:
    """Scan plot_dir for PNGs, base64-encode each, and insert rows."""
    now = _now_iso()
    png_files = sorted(plot_dir.glob("*.png"))
    for idx, png_path in enumerate(png_files):
        content = png_path.read_bytes()
        b64 = base64.b64encode(content).decode("ascii")
        conn.execute(
            "INSERT INTO diagnostic_run_plots "
            "(plot_id, run_id, filename, content_b64, sort_order, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (str(uuid.uuid4()), run_id, png_path.name, b64, idx, now),
        )
    return len(png_files)


def run_diagnostic(
    *,
    run_id: str,
    script_path: str,
    script_args: list[str],
    report_parser: Callable[[str], dict],
    report_path: str,
    plot_dir: str,
    db_path: str,
    timeout_s: int = 900,
) -> dict:
    """Execute a diagnostic script and persist the result.

    Lifecycle: queued (seeded by API) -> running -> completed | failed.
    Returns a summary dict suitable for command_results.result_json.
    """
    started = _now_iso()
    with sqlite3.connect(db_path) as conn:
        _update_run_status(conn, run_id, status="running", started_at=started)
        conn.commit()

    cmd = [sys.executable, script_path, "--output", report_path,
           "--plot-dir", plot_dir] + list(script_args)

    try:
        completed = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout_s,
        )
    except subprocess.TimeoutExpired:
        stderr_tail = f"Timed out after {timeout_s}s"
        with sqlite3.connect(db_path) as conn:
            _update_run_status(
                conn, run_id, status="failed",
                completed_at=_now_iso(),
                exit_code=-1, stderr_tail=stderr_tail,
            )
            conn.commit()
        return {"status": "failed", "exit_code": -1, "stderr_tail": stderr_tail}

    if completed.returncode != 0:
        stderr_tail = (completed.stderr or "")[-STDERR_TAIL_BYTES:]
        with sqlite3.connect(db_path) as conn:
            _update_run_status(
                conn, run_id, status="failed",
                completed_at=_now_iso(),
                exit_code=completed.returncode, stderr_tail=stderr_tail,
            )
            conn.commit()
        return {
            "status": "failed",
            "exit_code": completed.returncode,
            "stderr_tail": stderr_tail,
        }

    report_markdown = Path(report_path).read_text(encoding="utf-8")
    summary = report_parser(report_markdown)
    summary_json = json.dumps(summary)

    with sqlite3.connect(db_path) as conn:
        plot_count = _insert_plots(conn, run_id, Path(plot_dir))
        _update_run_status(
            conn, run_id, status="completed",
            completed_at=_now_iso(), exit_code=0,
            report_markdown=report_markdown,
            summary_json=summary_json,
        )
        conn.commit()

    logger.info(
        "[DIAG] run %s completed (%d plots, summary keys=%s)",
        run_id, plot_count, list(summary.keys()),
    )
    return {
        "status": "completed",
        "exit_code": 0,
        "summary": summary,
        "plot_count": plot_count,
    }
