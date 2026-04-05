"""SQLite connection helper with busy_timeout.

Called by: scheduler.watch, shadow_trading.executor, sync.render_sync, and others
Calls: none
Owns tables: none
Config keys: none
Tests: tests/test_db_util.py

The busy_timeout is critical because multiple threads (watch loop, sync thread,
FastAPI workers) all access the same SQLite database file. Without it, a thread
that tries to write while another is in a transaction gets an immediate
"database is locked" error. With busy_timeout=5000ms, SQLite retries for up to
5 seconds before giving up.

Row factory is set to sqlite3.Row globally so that results are accessible by
column name (dict-like) rather than tuple index. This prevents bugs when columns
are reordered in the schema registry.
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
