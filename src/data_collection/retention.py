"""Data retention policy — prunes old rows from high-growth tables.

Called by: scheduler/watch.py (overnight schedule, after data collection)
Calls: none
Owns tables: none (operates on existing tables)
Config keys: none
Tests: tests/test_data_pipeline_robustness.py

Addresses #123 (unbounded table growth). Without retention, tables like
log_entries and scan_metrics grow indefinitely, slowing queries and
inflating the SQLite file size. The DB file is the single most important
data artifact — if it grows past ~10GB, backup and sync become painful.

Applies per-table retention windows (days). Tables not listed in
RETENTION_RULES are NEVER pruned — this includes all trade data
(shadow_trades, recommendations), training data (training_examples,
preference_pairs), and council sessions. Those are the irreplaceable
data assets that make the system valuable.

Safety: _column_exists() check prevents crashes if a table's time column
was renamed in the registry but retention.py wasn't updated.
"""

import logging
import sqlite3
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from src.config import DB_PATH

logger = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")

# Retention rules: table_name -> max age in days
# Tables NOT listed here are never pruned.
RETENTION_RULES: dict[str, int] = {
    "scan_metrics": 90,
    "log_entries": 30,
    "activity_log": 30,
    "command_results": 30,
    "council_debug_log": 60,
    "setup_signals": 180,
    "options_metrics": 90,
    "options_chains": 30,  # Fix for #260: options chains retention
}

# Time column used for age comparison per table
_TIME_COLUMNS: dict[str, str] = {
    "scan_metrics": "created_at",
    "log_entries": "created_at",
    "activity_log": "created_at",
    "command_results": "created_at",
    "council_debug_log": "created_at",
    "setup_signals": "created_at",
    "options_metrics": "collected_date",
    "options_chains": "collected_at",  # Fix for #260: options chains retention
}


def run_retention(db_path: str = DB_PATH) -> dict[str, int]:
    """Delete rows older than retention period per table.

    Returns dict of table_name -> rows_deleted.
    Skips tables that don't exist or lack the expected time column.
    """
    now = datetime.now(ET)
    deleted: dict[str, int] = {}

    with sqlite3.connect(db_path) as conn:
        existing = _get_existing_tables(conn)

        for table, max_days in RETENTION_RULES.items():
            if table not in existing:
                logger.debug("[RETENTION] Table %s does not exist, skipping", table)
                continue

            time_col = _TIME_COLUMNS.get(table, "created_at")
            if not _column_exists(conn, table, time_col):
                logger.warning("[RETENTION] %s.%s column missing, skipping", table, time_col)
                continue

            cutoff = (now - timedelta(days=max_days)).isoformat()
            try:
                cursor = conn.execute(
                    f"DELETE FROM {table} WHERE {time_col} < ?",  # noqa: S608
                    (cutoff,),
                )
                count = cursor.rowcount
                if count > 0:
                    deleted[table] = count
                    logger.info("[RETENTION] Pruned %d rows from %s (older than %d days)",
                                count, table, max_days)
            except Exception as e:
                logger.warning("[RETENTION] Failed to prune %s: %s", table, e)

    if deleted:
        logger.info("[RETENTION] Total pruned: %s", deleted)
    else:
        logger.debug("[RETENTION] No rows to prune")

    return deleted


def _get_existing_tables(conn: sqlite3.Connection) -> set[str]:
    """Return set of table names that exist in the database."""
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()
    return {r[0] for r in rows}


def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    """Check whether a column exists in a table via PRAGMA."""
    try:
        cols = conn.execute(f"PRAGMA table_info({table})").fetchall()  # noqa: S608
        return any(c[1] == column for c in cols)
    except Exception:
        return False
