"""Command executor for dashboard-submitted commands.

Processes commands pulled from the cloud command queue.
Safety: commands expire after 5 min, rate-limited to 10/min,
results truncated to 10KB.

Called by: scheduler.watch
Calls: services.scan_service, council.engine, training.trainer, shadow_trading.executor, config.overrides
Owns tables: command_results
Config keys: none
Tests: tests/test_executor_import.py
"""

import json
import logging
import sqlite3
import time
import uuid
from collections import deque
from datetime import datetime
from zoneinfo import ZoneInfo

from src.config import DB_PATH

logger = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")
LOCAL_DB = DB_PATH
MAX_RESULT_SIZE = 10 * 1024  # 10KB
EXPIRY_SECONDS = 300  # 5 minutes
MAX_COMMANDS_PER_MINUTE = 10

# Rate limiter: track recent command timestamps
_recent_commands: deque = deque(maxlen=100)


def _is_rate_limited() -> bool:
    """Check if we've exceeded 10 commands per minute."""
    now = time.time()
    # Prune old entries
    while _recent_commands and now - _recent_commands[0] > 60:
        _recent_commands.popleft()
    return len(_recent_commands) >= MAX_COMMANDS_PER_MINUTE


def _truncate_result(data: str) -> str:
    """Truncate result JSON to MAX_RESULT_SIZE."""
    if len(data) <= MAX_RESULT_SIZE:
        return data
    return data[:MAX_RESULT_SIZE - 50] + '..."truncated": true}'


def _store_result(
    command_id: str,
    status: str,
    result: dict | None = None,
    error: str | None = None,
    execution_ms: int = 0,
    db_path: str = LOCAL_DB,
) -> None:
    """Write a command result to the local command_results table."""
    result_json = _truncate_result(json.dumps(result or {}))
    result_id = str(uuid.uuid4())
    now = datetime.now(ET).isoformat()

    try:
        with sqlite3.connect(db_path) as conn:
            conn.execute(
                "INSERT INTO command_results "
                "(result_id, command_id, status, result_json, error_message, "
                "execution_ms, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (result_id, command_id, status, result_json, error, execution_ms, now),
            )
            # Update local pending_commands status
            conn.execute(
                "UPDATE pending_commands SET status = ? WHERE command_id = ?",
                ("completed" if status == "success" else "failed", command_id),
            )
            conn.commit()
    except Exception as exc:
        logger.error("Failed to store command result: %s", exc)


def _is_expired(cmd: dict) -> bool:
    """Check if a command has expired."""
    expires_at = cmd.get("expires_at")
    if not expires_at:
        return False
    now = datetime.now(ET).isoformat()
    return now > expires_at


# ── Command handlers ──────────────────────────────────────────────

def _handle_scan(payload: dict, config: dict) -> dict:
    """Trigger a manual scan cycle."""
    from src.services.scan_service import run_scan_cycle
    result = run_scan_cycle(config)
    return {"message": "Scan completed", "packets": result.get("packets_generated", 0)}


def _handle_council(payload: dict, config: dict) -> dict:
    """Run a council session."""
    from src.council.engine import run_council_session
    session_type = payload.get("session_type", "strategic")
    question = payload.get("question")
    result = run_council_session(
        config=config,
        session_type=session_type,
        question=question,
    )
    return {
        "message": "Council session completed",
        "session_id": result.get("session_id", ""),
        "consensus": result.get("consensus", ""),
    }


def _handle_collect_data(payload: dict, config: dict) -> dict:
    """Trigger all data collectors."""
    from src.data_collection.options_collector import collect_options_data
    from src.data_collection.vix_collector import collect_vix_term_structure
    from src.data_collection.macro_collector import collect_macro_data
    results = {}
    for name, fn in [
        ("options", collect_options_data),
        ("vix", collect_vix_term_structure),
        ("macro", collect_macro_data),
    ]:
        try:
            fn()
            results[name] = "success"
        except Exception as exc:
            results[name] = f"error: {exc}"
    return {"message": "Data collection completed", "results": results}


def _handle_collect_training(payload: dict, config: dict) -> dict:
    """Trigger training data collection."""
    from src.training.scoring import score_pending_examples
    scored = score_pending_examples(config)
    return {"message": "Training collection completed", "scored": scored}


def _handle_train_pipeline(payload: dict, config: dict) -> dict:
    """Run the training pipeline."""
    from src.training.boot import run_training_pipeline
    result = run_training_pipeline(config)
    return {"message": "Training pipeline completed", "result": str(result)}


def _handle_halt_trading(payload: dict, config: dict) -> dict:
    """Activate the kill switch."""
    from src.risk.governor import activate_kill_switch
    activate_kill_switch(reason="Dashboard command")
    return {"message": "Trading halted via dashboard"}


def _handle_resume_trading(payload: dict, config: dict) -> dict:
    """Deactivate the kill switch."""
    from src.risk.governor import deactivate_kill_switch
    deactivate_kill_switch()
    return {"message": "Trading resumed via dashboard"}


def _handle_close_position(payload: dict, config: dict) -> dict:
    """Close a specific position."""
    ticker = payload.get("ticker")
    if not ticker or not isinstance(ticker, str) or len(ticker) > 10:
        return {"error": "Invalid or missing ticker in payload"}
    from src.shadow_trading.executor import close_position
    result = close_position(ticker, reason="Dashboard command")
    return {"message": f"Close position request sent for {ticker}", "result": str(result)}


def _handle_update_setting(payload: dict, config: dict) -> dict:
    """Update a whitelisted config value via config_overrides."""
    from src.config_overrides import apply_override
    key = payload.get("key")
    value = payload.get("value")
    if not key:
        return {"error": "Missing 'key' in payload"}
    result = apply_override(key, value)
    return result


def _handle_get_logs(payload: dict, config: dict) -> dict:
    """Return recent log entries."""
    level = payload.get("level", "WARNING")
    limit = min(payload.get("limit", 100), 500)

    try:
        with sqlite3.connect(LOCAL_DB) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM log_entries WHERE log_level >= ? "
                "ORDER BY created_at DESC LIMIT ?",
                (level, limit),
            ).fetchall()
            return {"logs": [dict(r) for r in rows], "count": len(rows)}
    except Exception as exc:
        return {"error": str(exc)}


# ── Command dispatch table ────────────────────────────────────────

def _handle_validate_system(payload: dict, config: dict) -> dict:
    """Run full system validation."""
    from src.evaluation.system_validator import run_full_validation, save_validation_result

    result = run_full_validation(LOCAL_DB)
    save_validation_result(result, LOCAL_DB)
    return {
        "overall_status": result.get("overall_status", "unknown"),
        "checks_passed": result.get("checks_passed", 0),
        "checks_warning": result.get("checks_warning", 0),
        "checks_failed": result.get("checks_failed", 0),
    }


def _handle_cto_report(payload: dict, config: dict) -> dict:
    """Generate CTO report and compute build score."""
    from src.evaluation.build_score import persist_build_score

    result = persist_build_score()
    return {
        "build_score": result.get("build_score", 0),
        "components": result.get("components", {}),
        "status": "completed",
    }


def _handle_stress_test(payload: dict, config: dict) -> dict:
    """Run stress test across historical crisis scenarios.

    Fix for #252: Added stress-test command so the frontend StressTest page
    can trigger it via the command queue.
    """
    from scripts.stress_test import run_scenario, store_result, SCENARIOS

    results = []
    for name, dates in SCENARIOS.items():
        try:
            result = run_scenario(name, dates["start"], dates["end"])
            if "error" not in result:
                store_result(result)
                results.append({
                    "scenario": name,
                    "total_trades": result.get("total_trades", 0),
                    "win_rate": result.get("win_rate", 0),
                    "max_drawdown_pct": result.get("max_drawdown_pct", 0),
                })
            else:
                results.append({"scenario": name, "error": result["error"]})
        except Exception as e:
            results.append({"scenario": name, "error": str(e)})

    return {"status": "completed", "scenarios": results}


COMMAND_HANDLERS = {
    "scan": _handle_scan,
    "council": _handle_council,
    "collect-data": _handle_collect_data,
    "collect-training": _handle_collect_training,
    "train-pipeline": _handle_train_pipeline,
    "halt-trading": _handle_halt_trading,
    "resume-trading": _handle_resume_trading,
    "close-position": _handle_close_position,
    "update_setting": _handle_update_setting,
    "get_logs": _handle_get_logs,
    "validate-system": _handle_validate_system,
    "cto-report": _handle_cto_report,
    # Fix for #252: stress test command for frontend Run button
    "stress-test": _handle_stress_test,
}


def execute_command(cmd: dict, config: dict, db_path: str = LOCAL_DB) -> dict:
    """Execute a single command and store the result.

    Args:
        cmd: Command dict with command_id, command_name, payload_json, etc.
        config: Application config dict.
        db_path: Path to local SQLite database.

    Returns:
        Result dict with status and details.
    """
    command_id = cmd.get("command_id", "unknown")
    command_name = cmd.get("command_name", "")
    payload_str = cmd.get("payload_json", "{}")

    try:
        payload = json.loads(payload_str) if isinstance(payload_str, str) else payload_str
    except (json.JSONDecodeError, TypeError):
        payload = {}

    # Safety: check expiry
    if _is_expired(cmd):
        _store_result(command_id, "error", error="Command expired", db_path=db_path)
        logger.warning("Command %s expired, skipping", command_id)
        return {"status": "error", "error": "expired"}

    # Safety: rate limit
    if _is_rate_limited():
        _store_result(command_id, "error", error="Rate limited", db_path=db_path)
        logger.warning("Rate limited, skipping command %s", command_id)
        return {"status": "error", "error": "rate_limited"}

    _recent_commands.append(time.time())

    handler = COMMAND_HANDLERS.get(command_name)
    if not handler:
        _store_result(command_id, "error", error=f"Unknown command: {command_name}", db_path=db_path)
        logger.warning("Unknown command: %s", command_name)
        return {"status": "error", "error": f"unknown_command: {command_name}"}

    logger.info("Executing command: %s (id=%s)", command_name, command_id)
    start_ms = time.monotonic_ns() // 1_000_000

    try:
        result = handler(payload, config)
        elapsed_ms = (time.monotonic_ns() // 1_000_000) - start_ms
        _store_result(command_id, "success", result=result, execution_ms=elapsed_ms, db_path=db_path)
        logger.info("Command %s completed in %dms", command_name, elapsed_ms)
        return {"status": "success", "result": result}
    except Exception as exc:
        elapsed_ms = (time.monotonic_ns() // 1_000_000) - start_ms
        error_msg = str(exc)[:500]
        _store_result(command_id, "error", error=error_msg, execution_ms=elapsed_ms, db_path=db_path)
        logger.error("Command %s failed: %s", command_name, exc)
        return {"status": "error", "error": error_msg}


def execute_commands(commands: list[dict], config: dict, db_path: str = LOCAL_DB) -> list[dict]:
    """Execute a batch of pulled commands.

    Called by the sync thread callback when commands are pulled from cloud.
    """
    results = []
    for cmd in commands:
        result = execute_command(cmd, config, db_path)
        results.append(result)
    return results
