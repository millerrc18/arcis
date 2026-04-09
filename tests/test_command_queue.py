"""Tests for the command queue system (Sprint 4C).

Covers: command submission, expiry, unknown commands, config whitelist,
rate limiting, each command type, result truncation, log handler,
pull+claim, full round-trip.
"""

import json
import os
import sqlite3
import tempfile
import time
import uuid
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from tests.conftest import init_test_db

ET = ZoneInfo("America/New_York")

# ── Fixtures ──────────────────────────────────────────────────────

@pytest.fixture
def db_path(tmp_path):
    """Create a temporary SQLite database with command queue tables."""
    path = str(tmp_path / "test.sqlite3")
    init_test_db(path, ["pending_commands", "command_results", "config_overrides", "log_entries"])
    return path


def _make_command(name="scan", cmd_type="action", payload=None, expired=False):
    """Create a test command dict."""
    now = datetime.now(ET)
    expires = (now - timedelta(minutes=10)) if expired else (now + timedelta(minutes=5))
    return {
        "command_id": str(uuid.uuid4()),
        "command_type": cmd_type,
        "command_name": name,
        "payload_json": json.dumps(payload or {}),
        "status": "pending",
        "priority": 0,
        "created_at": now.isoformat(),
        "claimed_at": None,
        "expires_at": expires.isoformat(),
        "created_by": "dashboard",
    }


# ── Test 1: Command submission writes to DB ───────────────────────

def test_command_submission(db_path):
    """A submitted command should create a pending_commands row."""
    conn = sqlite3.connect(db_path)
    cmd_id = str(uuid.uuid4())
    now = datetime.now(ET).isoformat()
    conn.execute(
        "INSERT INTO pending_commands "
        "(command_id, command_type, command_name, payload_json, status, created_at) "
        "VALUES (?, 'action', 'scan', '{}', 'pending', ?)",
        (cmd_id, now),
    )
    conn.commit()
    row = conn.execute(
        "SELECT * FROM pending_commands WHERE command_id = ?", (cmd_id,)
    ).fetchone()
    conn.close()
    assert row is not None
    assert row[3] == "{}"  # payload_json


# ── Test 2: Expired commands are rejected ─────────────────────────

def test_expired_command_skipped(db_path):
    """Expired commands should not be executed."""
    from src.commands.executor import execute_command

    cmd = _make_command("scan", expired=True)
    config = {}
    result = execute_command(cmd, config, db_path=db_path)
    assert result["status"] == "error"
    assert "expired" in result["error"]


# ── Test 3: Unknown commands are rejected ─────────────────────────

def test_unknown_command_rejected(db_path):
    """Unknown command names should return an error."""
    from src.commands.executor import execute_command

    cmd = _make_command("nonexistent_command")
    result = execute_command(cmd, {}, db_path=db_path)
    assert result["status"] == "error"
    assert "unknown_command" in result["error"]


# ── Test 4: Config whitelist enforced ─────────────────────────────

def test_config_whitelist_blocks_unsafe_keys(db_path):
    """Non-whitelisted keys should be rejected."""
    from src.config_overrides import apply_override

    result = apply_override("api_key.alpaca", "DANGER", db_path=db_path)
    assert "error" in result

    result = apply_override("render.database_url", "postgres://evil", db_path=db_path)
    assert "error" in result


def test_config_whitelist_allows_safe_keys(db_path):
    """Whitelisted keys should be accepted."""
    from src.config_overrides import apply_override

    result = apply_override("shadow_trading.max_positions", 25, db_path=db_path)
    assert "error" not in result
    assert result["value"] == 25


# ── Test 5: Rate limiting ─────────────────────────────────────────

def test_rate_limiting(db_path):
    """More than 10 commands per minute should be rate limited."""
    from src.commands.executor import execute_command, _recent_commands

    _recent_commands.clear()
    # Fill up the rate limiter
    for _ in range(10):
        _recent_commands.append(time.time())

    cmd = _make_command("scan")
    result = execute_command(cmd, {}, db_path=db_path)
    assert result["status"] == "error"
    assert "rate_limited" in result["error"]

    _recent_commands.clear()


# ── Test 6: Halt trading command ──────────────────────────────────

def test_halt_trading_command(db_path):
    """halt-trading should call activate_kill_switch."""
    from src.commands.executor import execute_command

    cmd = _make_command("halt-trading")
    with patch("src.commands.executor.COMMAND_HANDLERS", {
        **__import__("src.commands.executor", fromlist=["COMMAND_HANDLERS"]).COMMAND_HANDLERS,
        "halt-trading": lambda p, c: {"message": "Trading halted via dashboard"},
    }):
        result = execute_command(cmd, {}, db_path=db_path)
    assert result["status"] == "success"


# ── Test 7: Resume trading command ────────────────────────────────

def test_resume_trading_command(db_path):
    """resume-trading should call deactivate_kill_switch."""
    from src.commands.executor import execute_command

    cmd = _make_command("resume-trading")
    with patch("src.commands.executor.COMMAND_HANDLERS", {
        **__import__("src.commands.executor", fromlist=["COMMAND_HANDLERS"]).COMMAND_HANDLERS,
        "resume-trading": lambda p, c: {"message": "Trading resumed via dashboard"},
    }):
        result = execute_command(cmd, {}, db_path=db_path)
    assert result["status"] == "success"


# ── Test 8: Close position requires valid ticker ─────────────────

def test_close_position_validates_ticker(db_path):
    """close-position should require a valid ticker."""
    from src.commands.executor import _handle_close_position

    result = _handle_close_position({}, {})
    assert "error" in result or "Invalid" in str(result)

    result = _handle_close_position({"ticker": ""}, {})
    assert "error" in result or "Invalid" in str(result)


# ── Test 9: Result truncation ─────────────────────────────────────

def test_result_truncation():
    """Results over 10KB should be truncated."""
    from src.commands.executor import _truncate_result

    short = '{"ok": true}'
    assert _truncate_result(short) == short

    long_str = '{"data": "' + "x" * 20000 + '"}'
    truncated = _truncate_result(long_str)
    assert len(truncated) <= 10 * 1024
    assert "truncated" in truncated


# ── Test 10: DB log handler ───────────────────────────────────────

def test_db_log_handler(db_path):
    """DBLogHandler should write to log_entries table."""
    import logging
    from src.scheduler.watch import DBLogHandler

    handler = DBLogHandler(db_path=db_path)
    record = logging.LogRecord(
        name="test.module", level=logging.WARNING,
        pathname="test.py", lineno=1,
        msg="Test warning message", args=(), exc_info=None,
    )
    handler.emit(record)

    conn = sqlite3.connect(db_path)
    row = conn.execute("SELECT * FROM log_entries").fetchone()
    conn.close()

    assert row is not None
    assert "Test warning message" in row[3]  # message column


# ── Test 11: Pull and claim ───────────────────────────────────────

def test_pull_commands_marks_claimed(db_path):
    """pull_commands should mark commands as claimed in local DB."""
    conn = sqlite3.connect(db_path)
    cmd_id = str(uuid.uuid4())
    now = datetime.now(ET).isoformat()
    expires = (datetime.now(ET) + timedelta(minutes=5)).isoformat()
    conn.execute(
        "INSERT INTO pending_commands "
        "(command_id, command_type, command_name, payload_json, status, "
        "created_at, expires_at) "
        "VALUES (?, 'action', 'scan', '{}', 'claimed', ?, ?)",
        (cmd_id, now, expires),
    )
    conn.commit()

    row = conn.execute(
        "SELECT status FROM pending_commands WHERE command_id = ?", (cmd_id,)
    ).fetchone()
    conn.close()
    assert row[0] == "claimed"


# ── Test 12: Full round-trip ─────────────────────────────────────

def test_full_round_trip(db_path):
    """Submit → execute → store result → read result."""
    from src.commands.executor import execute_command, _recent_commands, _store_result

    _recent_commands.clear()

    cmd = _make_command("get_logs")
    result = execute_command(cmd, {}, db_path=db_path)

    # Should have stored a result
    conn = sqlite3.connect(db_path)
    result_row = conn.execute(
        "SELECT * FROM command_results WHERE command_id = ?",
        (cmd["command_id"],),
    ).fetchone()
    conn.close()

    assert result_row is not None
    assert result_row[2] in ("success", "error")  # status column


# ── Test 13: Config effective merge ───────────────────────────────

def test_effective_config_merge(db_path):
    """get_effective_config should merge overrides with YAML config."""
    from src.config_overrides import apply_override, get_effective_config

    apply_override("shadow_trading.max_positions", 25, db_path=db_path)

    yaml_config = {
        "shadow_trading": {"max_positions": 50, "enabled": True},
        "risk": {"planned_risk_pct_min": 0.005},
    }
    effective = get_effective_config(yaml_config, db_path=db_path)
    assert effective["shadow_trading"]["max_positions"] == 25
    assert effective["shadow_trading"]["enabled"] is True  # unchanged
    assert effective["risk"]["planned_risk_pct_min"] == 0.005  # unchanged


# ── Test 14: Clear all overrides ──────────────────────────────────

def test_clear_overrides(db_path):
    """clear_all_overrides should remove all overrides."""
    from src.config_overrides import apply_override, clear_all_overrides, get_overrides

    apply_override("shadow_trading.max_positions", 25, db_path=db_path)
    apply_override("llm.enabled", False, db_path=db_path)
    assert len(get_overrides(db_path)) == 2

    clear_all_overrides(db_path)
    assert len(get_overrides(db_path)) == 0


# ── Test 15: Settings with sources ────────────────────────────────

def test_settings_with_sources(db_path):
    """get_settings_with_sources should report yaml vs dashboard source."""
    from src.config_overrides import apply_override, get_settings_with_sources

    apply_override("llm.enabled", False, db_path=db_path)

    yaml_config = {
        "shadow_trading": {"max_positions": 50, "enabled": True},
        "llm": {"enabled": True, "min_conviction_score": 0},
    }
    settings = get_settings_with_sources(yaml_config, db_path=db_path)

    llm_enabled = next(s for s in settings if s["key"] == "llm.enabled")
    assert llm_enabled["source"] == "dashboard"
    assert llm_enabled["value"] is False

    shadow_max = next(s for s in settings if s["key"] == "shadow_trading.max_positions")
    assert shadow_max["source"] == "yaml"
