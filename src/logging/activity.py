"""Persistent activity logging for the Halcyon Lab system.

Writes structured activity log entries to SQLite for auditing,
debugging, and the /log Telegram command.
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
    timestamp TEXT NOT NULL,
    category TEXT NOT NULL,
    event TEXT NOT NULL,
    detail TEXT,
    source TEXT DEFAULT 'system'
);
"""

_CREATE_INDEXES_SQL = [
    "CREATE INDEX IF NOT EXISTS idx_activity_log_timestamp ON activity_log(timestamp);",
    "CREATE INDEX IF NOT EXISTS idx_activity_log_category ON activity_log(category);",
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
    timestamp = datetime.now(ET).isoformat()
    detail_json = json.dumps(detail) if detail is not None else None

    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute(
                "INSERT INTO activity_log (timestamp, category, event, detail, source) "
                "VALUES (?, ?, ?, ?, ?)",
                (timestamp, category, event, detail_json, source),
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
                    "SELECT * FROM activity_log WHERE category = ? "
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
            entry = dict(row)
            # Parse detail JSON back to dict
            if entry.get("detail"):
                try:
                    entry["detail"] = json.loads(entry["detail"])
                except (json.JSONDecodeError, TypeError):
                    pass
            results.append(entry)
        return results

    except Exception as e:
        logger.warning("[ACTIVITY] Failed to query activity: %s", e)
        return []
