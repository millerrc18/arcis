"""Shared test fixtures and helpers.

Provides init_test_db() to create all schema tables in a temp database,
replacing the per-module CREATE TABLE statements removed during the
schema registry migration (PR #189).
"""

import sqlite3

from src.schema.registry import TABLES
from src.schema.sqlite import generate_create_sql


def init_test_db(db_path: str, tables: list[str] | None = None) -> None:
    """Create schema tables in a test database.

    Args:
        db_path: Path to the SQLite database file.
        tables: Optional list of table names to create. If None, creates all.
    """
    with sqlite3.connect(db_path) as conn:
        if tables is None:
            for tdef in TABLES.values():
                conn.executescript(generate_create_sql(tdef))
        else:
            for name in tables:
                if name in TABLES:
                    conn.executescript(generate_create_sql(TABLES[name]))
