# Purpose: CLI + render tests for src/tools/tradingstate/__main__.py + render.py.
# Called by: pytest tests/tools/test_tradingstate_cli.py
# Calls: subprocess python -m src.tools.tradingstate, psycopg2 against real test PG
# Owns tables: none (creates + drops fixture rows in real test PG at 127.0.0.1:5434)
# Config keys: none (DSN passed explicitly per spec §4.9 network-discipline)
# Tests: (this file is the test)
"""CLI + render integration tests for src/tools/tradingstate.

Four cases per Task 7 TEST_STRATEGY:
  (a) Without --json: stdout contains 3-section markdown headers. Exit 0.
  (b) With --json: stdout parses as JSON with expected keys. Exit 0.
  (c) Forced failure + --json: stdout matches error envelope. Exit 1.
  (d) Forced failure without --json: stderr has output; stdout empty; exit 1.

Verify-by-mutation comments are inline.
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import psycopg2
import pytest

_TEST_DSN = (
    os.environ.get("TEST_DATABASE_URL")
    or "host=127.0.0.1 port=5434 dbname=halcyon user=test password=test"
)

_BAD_PORT_DSN = "host=127.0.0.1 port=1 dbname=halcyon user=test password=test"

_EXPECTED_JSON_KEYS = {"open_positions", "most_recent_audit", "gpu_health", "data_source", "as_of_et"}


# ── DDL helpers (replicated from test_tradingstate_integration.py) ────────────

def _pg_conn():
    return psycopg2.connect(_TEST_DSN, connect_timeout=5)


def _ensure_tables():
    conn = _pg_conn()
    try:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS recommendations (
                recommendation_id TEXT PRIMARY KEY,
                ticker TEXT NOT NULL,
                thesis_text TEXT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS shadow_trades (
                trade_id TEXT PRIMARY KEY,
                recommendation_id TEXT REFERENCES recommendations(recommendation_id),
                ticker TEXT NOT NULL,
                source TEXT DEFAULT 'paper',
                status TEXT DEFAULT 'pending',
                entry_price REAL,
                actual_entry_time TIMESTAMPTZ,
                quarantined INTEGER DEFAULT 0,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS audit_reports (
                audit_id TEXT PRIMARY KEY,
                created_at TIMESTAMPTZ NOT NULL,
                audit_date TEXT NOT NULL,
                overall_assessment TEXT NOT NULL,
                summary TEXT,
                flags TEXT,
                metrics_to_watch TEXT,
                model_health TEXT,
                full_report TEXT
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS schedule_metrics (
                id SERIAL PRIMARY KEY,
                metric_date DATE NOT NULL,
                metric_name TEXT NOT NULL,
                metric_value REAL,
                details TEXT
            )
        """)
        conn.commit()
    finally:
        conn.close()


def _pg_delete_fixture(conn, trade_ids, audit_ids, metric_ids, rec_ids):
    try:
        cur = conn.cursor()
        if trade_ids:
            cur.execute(
                "DELETE FROM shadow_trades WHERE trade_id = ANY(%s)", (list(trade_ids),)
            )
        if audit_ids:
            cur.execute(
                "DELETE FROM audit_reports WHERE audit_id = ANY(%s)", (list(audit_ids),)
            )
        if metric_ids:
            cur.execute(
                "DELETE FROM schedule_metrics WHERE id = ANY(%s)", (list(metric_ids),)
            )
        if rec_ids:
            cur.execute(
                "DELETE FROM recommendations WHERE recommendation_id = ANY(%s)", (list(rec_ids),)
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise


# ── Fixture loader ─────────────────────────────────────────────────────────────

def _load_minimal_fixture():
    """Insert 1 open position, 1 audit, 2 GPU metrics. Returns cleanup IDs."""
    conn = _pg_conn()
    rec_id = str(uuid.uuid4())
    trade_id = str(uuid.uuid4())
    audit_id = str(uuid.uuid4())
    today_str = date.today().isoformat()
    now_utc = datetime.now(timezone.utc)
    entry_time = now_utc - timedelta(minutes=5)
    audit_created = now_utc - timedelta(hours=1)
    metric_ids = []

    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO recommendations (recommendation_id, ticker, thesis_text) VALUES (%s,%s,%s)",
            (rec_id, "AAPL", "CLI test thesis"),
        )
        cur.execute(
            """INSERT INTO shadow_trades
               (trade_id, recommendation_id, ticker, source, status, entry_price,
                actual_entry_time, quarantined)
               VALUES (%s,%s,%s,'live','open',150.0,%s,0)""",
            (trade_id, rec_id, "AAPL", entry_time),
        )
        cur.execute(
            """INSERT INTO audit_reports
               (audit_id, created_at, audit_date, overall_assessment)
               VALUES (%s,%s,%s,'STABLE')""",
            (audit_id, audit_created, today_str),
        )
        cur.execute(
            """INSERT INTO schedule_metrics (metric_date, metric_name, metric_value)
               VALUES (%s,'gpu_health_ollama_ok',1.0) RETURNING id""",
            (today_str,),
        )
        metric_ids.append(cur.fetchone()[0])
        cur.execute(
            """INSERT INTO schedule_metrics (metric_date, metric_name, metric_value)
               VALUES (%s,'gpu_health_training_ok',0.0) RETURNING id""",
            (today_str,),
        )
        metric_ids.append(cur.fetchone()[0])
        conn.commit()
    except Exception:
        conn.rollback()
        conn.close()
        raise

    return conn, rec_id, trade_id, audit_id, metric_ids


def _run_cli(*args, env=None) -> subprocess.CompletedProcess:
    """Run python -m src.tools.tradingstate with given args."""
    cmd = [sys.executable, "-m", "src.tools.tradingstate"] + list(args)
    merged_env = {**os.environ}
    if env:
        merged_env.update(env)
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=30,
        env=merged_env,
    )


# ── Test (a): Markdown 3-section structure ────────────────────────────────────

def test_a_markdown_three_sections():
    """
    Without --json: stdout contains all 3 section headers. Exit 0.

    Verify-by-mutation: Fails if render_markdown removes any of the
    3 section headers ('## Positions', '## Audit', '## GPU Health').
    """
    _ensure_tables()
    conn, rec_id, trade_id, audit_id, metric_ids = _load_minimal_fixture()
    try:
        result = _run_cli("--dsn", _TEST_DSN)
        assert result.returncode == 0, (
            f"Expected exit 0, got {result.returncode}.\n"
            f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
        assert "## Positions" in result.stdout, (
            f"'## Positions' section header missing from stdout:\n{result.stdout!r}"
        )
        assert "## Audit" in result.stdout, (
            f"'## Audit' section header missing from stdout:\n{result.stdout!r}"
        )
        assert "## GPU Health" in result.stdout, (
            f"'## GPU Health' section header missing from stdout:\n{result.stdout!r}"
        )
        assert "# Trading State" in result.stdout, (
            f"Top-level '# Trading State' header missing from stdout:\n{result.stdout!r}"
        )
    finally:
        _pg_delete_fixture(
            conn,
            trade_ids=[trade_id],
            audit_ids=[audit_id],
            metric_ids=metric_ids,
            rec_ids=[rec_id],
        )
        conn.close()


# ── Test (b): JSON shape ───────────────────────────────────────────────────────

def test_b_json_output_shape():
    """
    With --json: stdout parses as JSON with all expected keys. Exit 0.

    Verify-by-mutation: Fails if render.py is mistakenly called when --json
    is present, or if any key is missing from the snapshot dict.
    """
    _ensure_tables()
    conn, rec_id, trade_id, audit_id, metric_ids = _load_minimal_fixture()
    try:
        result = _run_cli("--dsn", _TEST_DSN, "--json")
        assert result.returncode == 0, (
            f"Expected exit 0, got {result.returncode}.\n"
            f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            pytest.fail(f"stdout is not valid JSON: {exc}\nstdout={result.stdout!r}")

        missing = _EXPECTED_JSON_KEYS - set(payload.keys())
        assert not missing, (
            f"JSON output missing keys: {missing}. Got keys: {set(payload.keys())}"
        )
        # Spot-check types
        assert isinstance(payload["open_positions"], list)
        assert isinstance(payload["gpu_health"], dict)
    finally:
        _pg_delete_fixture(
            conn,
            trade_ids=[trade_id],
            audit_ids=[audit_id],
            metric_ids=metric_ids,
            rec_ids=[rec_id],
        )
        conn.close()


# ── Test (c): Error envelope with --json ──────────────────────────────────────

def test_c_error_envelope_json():
    """
    Forced failure (bad PG + nonexistent SQLite) + --json:
    stdout matches error envelope schema; exit 1.

    Verify-by-mutation: Fails if __main__.py rolls its own try/except instead
    of delegating to _cli_envelope.run_cli — a custom try/except would output
    something other than the standard envelope JSON shape.
    """
    result = _run_cli(
        "--dsn", _BAD_PORT_DSN,
        "--sqlite-path", "/nonexistent/path.db",
        "--json",
    )
    assert result.returncode == 1, (
        f"Expected exit 1, got {result.returncode}.\n"
        f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
    )
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        pytest.fail(f"stdout is not valid JSON: {exc}\nstdout={result.stdout!r}")

    assert "error" in payload, (
        f"Expected 'error' key in envelope, got keys: {list(payload.keys())}"
    )
    err = payload["error"]
    assert err.get("type") == "TradingStateError", (
        f"Expected type='TradingStateError', got: {err.get('type')!r}"
    )
    assert err.get("tool") == "tradingstate", (
        f"Expected tool='tradingstate', got: {err.get('tool')!r}"
    )
    assert "message" in err, f"'message' key missing from error envelope: {err}"


# ── Test (d): Error without --json ────────────────────────────────────────────

def test_d_error_no_json_traceback_stderr():
    """
    Forced failure without --json: traceback in stderr; stdout empty; exit 1.

    Verify-by-mutation: Fails if __main__.py swallows exceptions silently or
    prints something to stdout on failure without --json.
    """
    result = _run_cli(
        "--dsn", _BAD_PORT_DSN,
        "--sqlite-path", "/nonexistent/path.db",
    )
    assert result.returncode == 1, (
        f"Expected exit 1, got {result.returncode}.\n"
        f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
    )
    # stdout must be empty (no JSON envelope, no markdown — just re-raise)
    assert result.stdout.strip() == "", (
        f"Expected empty stdout on non-json failure, got: {result.stdout!r}"
    )
    # stderr must contain something (traceback from re-raise)
    assert result.stderr.strip() != "", (
        f"Expected traceback in stderr on non-json failure, got empty stderr"
    )
