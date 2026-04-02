"""Schedule metrics tracking for the 24/7 compute scheduler.

Called by: api.routes.system
Calls: none
Owns tables: schedule_metrics
Config keys: none
Tests: none

Tracks GPU utilization, scoring throughput, VRAM handoff success,
and other operational metrics for the compute schedule.
"""

import json
import logging
import sqlite3
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from src.config import DB_PATH

logger = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")

# Table creation handled by src/schema/registry.py


def init_schedule_metrics(db_path: str = DB_PATH) -> None:
    """No-op: table creation handled by src/schema/registry.py at startup."""
    pass


def record_metric(metric_name: str, metric_value: float,
                  details: str | None = None,
                  db_path: str = DB_PATH) -> None:
    """Record a single schedule metric for today."""
    init_schedule_metrics(db_path)
    metric_date = datetime.now(ET).strftime("%Y-%m-%d")
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO schedule_metrics (metric_date, metric_name, metric_value, details) "
            "VALUES (?, ?, ?, ?)",
            (metric_date, metric_name, metric_value, details),
        )
        conn.commit()


def upsert_daily_metric(metric_name: str, metric_value: float,
                        details: str | None = None,
                        db_path: str = DB_PATH) -> None:
    """Insert or update a metric for today (replaces existing value)."""
    init_schedule_metrics(db_path)
    metric_date = datetime.now(ET).strftime("%Y-%m-%d")
    with sqlite3.connect(db_path) as conn:
        existing = conn.execute(
            "SELECT id FROM schedule_metrics "
            "WHERE metric_date = ? AND metric_name = ?",
            (metric_date, metric_name),
        ).fetchone()
        if existing:
            conn.execute(
                "UPDATE schedule_metrics SET metric_value = ?, details = ? "
                "WHERE id = ?",
                (metric_value, details, existing[0]),
            )
        else:
            conn.execute(
                "INSERT INTO schedule_metrics "
                "(metric_date, metric_name, metric_value, details) "
                "VALUES (?, ?, ?, ?)",
                (metric_date, metric_name, metric_value, details),
            )
        conn.commit()


def get_metrics(days: int = 30,
                db_path: str = DB_PATH) -> list[dict]:
    """Get schedule metrics for the last N days."""
    init_schedule_metrics(db_path)
    cutoff = (datetime.now(ET) - timedelta(days=days)).strftime("%Y-%m-%d")
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT metric_date, metric_name, metric_value, details "
            "FROM schedule_metrics "
            "WHERE metric_date >= ? "
            "ORDER BY metric_date DESC, metric_name",
            (cutoff,),
        ).fetchall()

    # Group by date
    by_date: dict[str, dict] = {}
    for row in rows:
        date = row["metric_date"]
        if date not in by_date:
            by_date[date] = {"date": date}
        by_date[date][row["metric_name"]] = row["metric_value"]
        if row["details"]:
            by_date[date][f"{row['metric_name']}_details"] = row["details"]

    return sorted(by_date.values(), key=lambda x: x["date"], reverse=True)


def get_todays_metrics(db_path: str = DB_PATH) -> dict:
    """Get today's running metric totals."""
    init_schedule_metrics(db_path)
    today = datetime.now(ET).strftime("%Y-%m-%d")
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT metric_name, metric_value FROM schedule_metrics "
            "WHERE metric_date = ?",
            (today,),
        ).fetchall()

    result = {"date": today}
    for row in rows:
        result[row["metric_name"]] = row["metric_value"]
    return result
