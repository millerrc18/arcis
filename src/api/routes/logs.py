"""Logs and command queue API routes (local mode).

Called by: api.app
Calls: none
Owns tables: none (reads log_entries, pending_commands, command_results)
Config keys: none
Tests: tests/test_local_routes.py
"""

import json
import logging
import sqlite3
import uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.config import DB_PATH

router = APIRouter(tags=["logs"])
logger = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")

LEVEL_ORDER = {"DEBUG": 0, "INFO": 1, "WARNING": 2, "ERROR": 3, "CRITICAL": 4}


class CommandSubmission(BaseModel):
    command_name: str
    command_type: str = "action"
    payload: dict = {}
    priority: int = 0


@router.get("/logs/recent")
def recent_logs(level: str = "INFO", limit: int = 100, source: str = None):
    """Query log_entries table with level filtering."""
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        try:
            params = []
            where_clauses = []

            if level and level != "ALL":
                min_level = LEVEL_ORDER.get(level.upper(), 1)
                allowed = [k for k, v in LEVEL_ORDER.items() if v >= min_level]
                placeholders = ", ".join(["?"] * len(allowed))
                where_clauses.append(f"log_level IN ({placeholders})")
                params.extend(allowed)

            if source:
                where_clauses.append("source = ?")
                params.append(source)

            where = " AND ".join(where_clauses) if where_clauses else "1=1"
            params.append(min(limit, 500))

            rows = conn.execute(
                f"SELECT * FROM log_entries WHERE {where} "
                f"ORDER BY created_at DESC LIMIT ?",
                tuple(params),
            ).fetchall()
            logs = [dict(r) for r in rows]
            return {"logs": logs, "count": len(logs)}
        finally:
            conn.close()
    except Exception as exc:
        logger.error("[API] logs/recent failed: %s", exc)
        return {"logs": [], "count": 0, "error": str(exc)}


@router.post("/commands/submit")
def submit_command(body: CommandSubmission):
    """Submit a command to the local command queue."""
    try:
        command_id = str(uuid.uuid4())
        now = datetime.now(ET)
        expires_at = (now + timedelta(minutes=5)).isoformat()

        conn = sqlite3.connect(DB_PATH)
        try:
            conn.execute(
                "INSERT INTO pending_commands "
                "(command_id, command_type, command_name, payload_json, "
                "status, priority, created_at, expires_at, created_by) "
                "VALUES (?, ?, ?, ?, 'pending', ?, ?, ?, 'dashboard')",
                (command_id, body.command_type, body.command_name,
                 json.dumps(body.payload), body.priority,
                 now.isoformat(), expires_at),
            )
            conn.commit()
        finally:
            conn.close()

        return {
            "command_id": command_id,
            "status": "pending",
            "expires_at": expires_at,
        }
    except Exception as exc:
        logger.error("Command submission failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/commands/{command_id}/status")
def command_status(command_id: str):
    """Check command + result status."""
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        try:
            cmd = conn.execute(
                "SELECT * FROM pending_commands WHERE command_id = ?",
                (command_id,),
            ).fetchone()
            if not cmd:
                raise HTTPException(status_code=404, detail="Command not found")

            result = conn.execute(
                "SELECT * FROM command_results WHERE command_id = ? "
                "ORDER BY created_at DESC LIMIT 1",
                (command_id,),
            ).fetchone()
            return {
                "command": dict(cmd),
                "result": dict(result) if result else None,
            }
        finally:
            conn.close()
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Command status error: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/commands/recent")
def recent_commands(limit: int = 20):
    """Last N commands with their results."""
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                "SELECT c.*, r.status as result_status, r.result_json, "
                "r.error_message, r.execution_ms "
                "FROM pending_commands c "
                "LEFT JOIN command_results r ON c.command_id = r.command_id "
                "ORDER BY c.created_at DESC LIMIT ?",
                (min(limit, 50),),
            ).fetchall()
            commands = [dict(r) for r in rows]
            return {"commands": commands, "count": len(commands)}
        finally:
            conn.close()
    except Exception as exc:
        logger.error("Recent commands error: %s", exc)
        return {"commands": [], "count": 0, "error": str(exc)}
