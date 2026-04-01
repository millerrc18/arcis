"""Structured activity logger for dashboard display and observability.

Called by: scheduler.watch, shadow_trading.executor
Calls: none
Owns tables: none
Config keys: none
Tests: tests/test_activity_logger.py

Writes to the activity_log SQLite table. Each event has:
- event_type: category of event (scan_complete, trade_opened, etc.)
- detail: human-readable description
- metadata: optional JSON dict with structured data

This feeds the Notification Center, Activity Feed, and cloud dashboard.
"""

import json
import logging
import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo

from src.config import DB_PATH

logger = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")

# Event type constants
SCAN_COMPLETE = "scan_complete"
TRADE_OPENED = "trade_opened"
TRADE_CLOSED = "trade_closed"
LLM_GENERATION = "llm_generation"
TRAINING_COLLECTION = "training_collection"
TRAINING_RETRAIN = "training_retrain"
DATA_COLLECTION = "data_collection"
VRAM_HANDOFF = "vram_handoff"
RISK_ALERT = "risk_alert"
SYSTEM_EVENT = "system_event"
RESEARCH_PAPERS = "research_papers"
RESEARCH_DIGEST = "research_digest"


def log_activity(event_type: str, detail: str, metadata: dict | None = None,
                 db_path: str = DB_PATH) -> None:
    """Log a structured activity event for dashboard display."""
    try:
        now = datetime.now(ET).isoformat()
        with sqlite3.connect(db_path) as conn:
            conn.execute(
                "INSERT INTO activity_log (event_type, detail, created_at) "
                "VALUES (?, ?, ?)",
                (event_type, detail if not metadata else f"{detail} | {json.dumps(metadata)}", now),
            )
    except Exception as exc:
        logger.debug("[ACTIVITY] Failed to log event %s: %s", event_type, exc)
