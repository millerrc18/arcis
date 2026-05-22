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
The activity_log table is synced to Render Postgres so cloud users see
the same feed. Retention: 30 days (see retention.py).

Failures are swallowed (logger.debug, not raise) because activity logging
is observability infrastructure — it should never crash the operation it's
observing.
"""

import json
import logging
import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo

from src.config import DB_PATH
from src.utils.db import connect_db

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
GPU_HEALTH = "gpu_health"
RISK_ALERT = "risk_alert"
SYSTEM_EVENT = "system_event"
RESEARCH_PAPERS = "research_papers"
RESEARCH_DIGEST = "research_digest"


def log_activity(event_type: str, detail: str, metadata: dict | None = None,
                 db_path: str = DB_PATH) -> None:
    """Log a structured activity event for dashboard display."""
    # #613 — Guard against test fixtures that forget to monkeypatch DB_PATH.
    # Pre-fix, tests/test_kill_switch.py and tests/test_auditor.py wrote 540
    # fake kill_switch_halt rows into the prod ai_research_desk.sqlite3
    # because they patched _HALT_FILE but not the activity_logger DB path.
    # Tests that intentionally need to write should monkeypatch DB_PATH AND
    # opt in via ARCIS_LOG_ACTIVITY_IN_PYTEST=1.
    import os
    if os.environ.get("PYTEST_CURRENT_TEST"):
        if not os.environ.get("ARCIS_LOG_ACTIVITY_IN_PYTEST"):
            return
        # #647 — Defense-in-depth: even if a test opts in via the env var, it
        # MUST redirect db_path away from the prod DB. Pre-#647, tests/test_
        # risk_governor.py had an autouse fixture setting ARCIS_LOG_ACTIVITY_
        # IN_PYTEST=1 without redirecting DB_PATH, leaking 562+ rows into prod
        # over weeks. Raising loudly here forces future contributors to fix
        # the same shape immediately instead of polluting silently.
        if db_path == DB_PATH or (isinstance(db_path, str) and "ai_research_desk" in db_path):
            raise RuntimeError(
                f"log_activity called from pytest with "
                f"ARCIS_LOG_ACTIVITY_IN_PYTEST=1 but db_path={db_path!r} is the "
                f"production DB. Tests opting into writes MUST also redirect "
                f"db_path to a tmp file (e.g. via tmp_path fixture)."
            )
    try:
        now = datetime.now(ET).isoformat()
        with connect_db(db_path) as conn:
            conn.execute(
                "INSERT INTO activity_log (event_type, detail, created_at) "
                "VALUES (?, ?, ?)",
                (event_type, detail if not metadata else f"{detail} | {json.dumps(metadata)}", now),
            )
    except Exception as exc:
        logger.debug("[ACTIVITY] Failed to log event %s: %s", event_type, exc)
