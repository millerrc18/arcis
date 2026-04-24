"""Council session API routes (local mode).

Called by: api.app
Calls: none
Owns tables: none (reads council_sessions, council_votes)
Config keys: none
Tests: tests/test_local_routes.py

Endpoints:
    GET /council/latest              - Most recent session with votes
    GET /council/history?days=30     - Session list within date range
    GET /council/session/{id}        - Single session detail with votes

The AI Council is a multi-agent deliberation system where 5 specialized
agents (tactical, strategic, red team, innovation, macro) vote on market
direction. Sessions and votes are stored separately because votes link
to sessions via session_id, and a single session may span multiple rounds
if consensus is contested.
"""

import json
import logging
import sqlite3
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Query

from src.config import DB_PATH
from src.utils.db import connect_db

router = APIRouter(tags=["council"])
logger = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")


def _parse_json_fields(row: dict, fields: list[str]) -> dict:
    """Parse JSON string fields in a row dict."""
    for field in fields:
        val = row.get(field)
        if isinstance(val, str):
            try:
                row[field] = json.loads(val)
            except (json.JSONDecodeError, TypeError):
                pass
    return row


@router.get("/council/latest")
def council_latest():
    """Return the most recent council session with votes."""
    try:
        conn = connect_db(DB_PATH)
        conn.row_factory = sqlite3.Row
        try:
            session = conn.execute(
                "SELECT * FROM council_sessions ORDER BY created_at DESC LIMIT 1"
            ).fetchone()

            if not session:
                return {"session": None}

            session = _parse_json_fields(dict(session), ["result_json"])
            votes = [
                _parse_json_fields(dict(v), ["key_data_points", "risk_flags"])
                for v in conn.execute(
                    "SELECT * FROM council_votes WHERE session_id = ? "
                    "ORDER BY round, agent_name",
                    (session["session_id"],),
                ).fetchall()
            ]
            session["votes"] = votes
            return session
        finally:
            conn.close()
    except Exception as exc:
        logger.error("Council latest error: %s", exc)
        return {"session": None, "error": str(exc)}


@router.get("/council/history")
def council_history(days: int = Query(default=30, ge=1, le=365)):
    """Return council sessions within date range."""
    try:
        cutoff = (datetime.now(ET) - timedelta(days=days)).isoformat()
        conn = connect_db(DB_PATH)
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                "SELECT * FROM council_sessions WHERE created_at >= ? "
                "ORDER BY created_at DESC",
                (cutoff,),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()
    except Exception as exc:
        logger.error("Council history error: %s", exc)
        return []


@router.get("/council/session/{session_id}")
def council_session_detail(session_id: str):
    """Return a specific council session with its votes."""
    try:
        conn = connect_db(DB_PATH)
        conn.row_factory = sqlite3.Row
        try:
            session = conn.execute(
                "SELECT * FROM council_sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()

            if not session:
                raise HTTPException(status_code=404, detail="Session not found")

            session = _parse_json_fields(dict(session), ["result_json"])
            votes = [
                _parse_json_fields(dict(v), ["key_data_points", "risk_flags"])
                for v in conn.execute(
                    "SELECT * FROM council_votes WHERE session_id = ? "
                    "ORDER BY round, agent_name",
                    (session_id,),
                ).fetchall()
            ]
            return {"session": session, "votes": votes}
        finally:
            conn.close()
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Council session detail error: %s", exc)
        return {"session": None, "votes": [], "error": str(exc)}
