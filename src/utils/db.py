"""SQLite connection helper with busy_timeout.

Called by: scheduler.watch, shadow_trading.executor, sync.render_sync, and others
Calls: none
Owns tables: none
Config keys: none
Tests: tests/test_db_util.py
"""

import sqlite3

from src.config import DB_PATH

DEFAULT_DB = DB_PATH
BUSY_TIMEOUT_MS = 5000


def connect_db(db_path: str = DEFAULT_DB) -> sqlite3.Connection:
    """Open a SQLite connection with busy_timeout and Row factory.

    Every module that opens a database connection should use this helper
    to ensure consistent busy_timeout and row factory settings.
    """
    conn = sqlite3.connect(db_path)
    conn.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
    conn.row_factory = sqlite3.Row
    return conn
