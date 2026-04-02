"""Persistent activity logging for the Arcis system.

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

from src.config import DB_PATH

logger = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")

_table_created = False

VALID_CATEGORIES = {
    "scan", "trade", "data_collection", "council",
    "training", "system", "error",
}

# Table creation handled by src/schema/registry.py


def _ensure_table():
    """No-op: table creation handled by src/schema/registry.py at startup."""
    global _table_created
    _table_created = True


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
