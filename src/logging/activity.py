"""Persistent activity logging for the Halcyon Lab system.

Called by: api.routes.system, notifications.telegram, scheduler.watch
Calls: none
Owns tables: activity_log
Config keys: none
Tests: tests/test_activity_log.py
"""

import json
import logging
import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")

DB_PATH = "ai_research_desk.sqlite3"

_table_created = False

VALID_CATEGORIES = {
    "scan", "trade", "data_collection", "council",
    "training", "system", "error",
}

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS activity_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type TEXT NOT NULL,
    detail TEXT,
    created_at TEXT NOT NULL
);
"""

_CREATE_INDEXES_SQL = [
    "CREATE INDEX IF NOT EXISTS idx_activity_log_created_at ON activity_log(created_at);",
    "CREATE INDEX IF NOT EXISTS idx_activity_log_event_type ON activity_log(event_type);",
]


def _ensure_table():
    """Create the activity_log table if it doesn't exist yet."""
    global _table_created
    if _table_created:
        return
    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute(_CREATE_TABLE_SQL)
            for idx_sql in _CREATE_INDEXES_SQL:
                conn.execute(idx_sql)
        _table_created = True
    except Exception as e:
        logger.warning("[ACTIVITY] Table creation failed: %s", e)


def log_activity(
    category: str,
    event: str,
    detail: dict | None = None,
    source: str = "system",
) -> None:
    """Write a structured activity log entry.

    Args:
        category: One of scan, trade, data_collection, council,
                  training, system, error.
        event: Short description of the event.
        detail: Optional dict of extra data (stored as JSON).
        source: Originating subsystem (default "system").
    """
    _ensure_table()
    created_at = datetime.now(ET).isoformat()
    payload = json.dumps(
        {
            "event": event,
            "detail": detail,
            "source": source,
        }
    )

    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute(
                "INSERT INTO activity_log (event_type, detail, created_at) "
                "VALUES (?, ?, ?)",
                (category, payload, created_at),
            )
    except Exception as e:
        logger.warning("[ACTIVITY] Failed to log activity: %s", e)


def get_recent_activity(
    limit: int = 10,
    category: str | None = None,
) -> list[dict]:
    """Query recent activity log entries.

    Args:
        limit: Max entries to return (default 10).
        category: Optional category filter.

    Returns:
        List of dicts with id, timestamp, category, event, detail, source.
    """
    _ensure_table()
    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            if category:
                rows = conn.execute(
                    "SELECT * FROM activity_log WHERE event_type = ? "
                    "ORDER BY id DESC LIMIT ?",
                    (category, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM activity_log ORDER BY id DESC LIMIT ?",
                    (limit,),
                ).fetchall()

        results = []
        for row in rows:
            raw = dict(row)
            payload = {}
            if raw.get("detail"):
                try:
                    parsed = json.loads(raw["detail"])
                    if isinstance(parsed, dict):
                        payload = parsed
                    else:
                        payload = {"detail": parsed}
                except (json.JSONDecodeError, TypeError):
                    payload = {"detail": raw["detail"]}
            entry = {
                "id": raw["id"],
                "timestamp": raw["created_at"],
                "category": raw["event_type"],
                "event": payload.get("event") or raw["event_type"],
                "detail": payload.get("detail"),
                "source": payload.get("source", "system"),
            }
            results.append(entry)
        return results

    except Exception as e:
        logger.warning("[ACTIVITY] Failed to query activity: %s", e)
        return []
