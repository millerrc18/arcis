"""Safe production DB migration — adds missing columns and tables.

When to run:
    After pulling changes that add new columns or tables to the schema
    registry. Also used during initial setup of a production database.
    Prefer `validate-schema --fix` for new setups; this script handles
    both registry-based and legacy hardcoded column migrations.

What it reads:
    - src/schema/registry.py (for table creation)
    - COLUMN_MIGRATIONS list in this file (for legacy column additions)

What it writes:
    - Creates missing tables and adds missing columns in the target SQLite DB
    - Idempotent: safe to run multiple times. Never drops or modifies existing data.

Prerequisites:
    - Target database must already exist (will not create a new file)

Usage:
    python scripts/migrate_production_db.py                    # default DB
    python scripts/migrate_production_db.py path/to/other.db   # custom path
"""

import os
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.config import DB_PATH

DEFAULT_DB = DB_PATH


def get_existing_columns(conn: sqlite3.Connection, table: str) -> list[str]:
    """Return list of column names for a table (empty if table doesn't exist)."""
    try:
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
        return [r[1] for r in rows]
    except Exception:
        return []


def table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone()
    return row[0] > 0


# ── Column migrations (ALTER TABLE) ──────────────────────────────────────

COLUMN_MIGRATIONS = [
    ("shadow_trades", "strategy_type", "TEXT DEFAULT 'pullback'"),
    ("training_examples", "outcome_type", "TEXT"),
    ("training_examples", "regime", "TEXT"),
    ("activity_log", "level", "TEXT DEFAULT 'INFO'"),
]


def migrate_columns(conn: sqlite3.Connection) -> list[str]:
    """Add missing columns. Returns list of actions taken."""
    actions = []
    for table, column, col_type in COLUMN_MIGRATIONS:
        if not table_exists(conn, table):
            actions.append(f"SKIP: table '{table}' does not exist (column {column})")
            continue
        existing = get_existing_columns(conn, table)
        if column in existing:
            actions.append(f"OK: {table}.{column} already exists")
        else:
            sql = f"ALTER TABLE {table} ADD COLUMN {column} {col_type}"
            conn.execute(sql)
            actions.append(f"ADDED: {table}.{column} ({col_type})")
    conn.commit()
    return actions


# ── Table migrations (CREATE TABLE IF NOT EXISTS) ────────────────────────

def migrate_tables(conn: sqlite3.Connection) -> list[str]:
    """Create missing tables from the schema registry."""
    from src.schema.registry import TABLES
    from src.schema.sqlite import generate_create_sql

    actions = []

    for table in TABLES.values():
        sql = generate_create_sql(table)
        try:
            conn.executescript(sql)
            actions.append(f"TABLE: {table.name} (created or already exists)")
        except Exception as e:
            actions.append(f"ERROR: {table.name}: {e}")

    conn.commit()
    return actions


def main():
    db_path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_DB

    if not Path(db_path).exists():
        print(f"ERROR: Database not found at {db_path}")
        sys.exit(1)

    print(f"Migrating: {db_path}")
    print(f"DB size: {Path(db_path).stat().st_size / 1024:.0f} KB")
    print()

    conn = sqlite3.connect(db_path)

    # 1. Create missing tables first so ALTER TABLE has targets.
    # Order matters: column migrations reference tables that may not exist yet.
    print("=== Creating missing tables ===")
    table_actions = migrate_tables(conn)
    for a in table_actions:
        print(f"  {a}")
    print()

    # 2. Add missing columns
    print("=== Adding missing columns ===")
    col_actions = migrate_columns(conn)
    for a in col_actions:
        print(f"  {a}")
    print()

    # 3. Verify
    print("=== Verification ===")
    errors = []
    for table, column, _ in COLUMN_MIGRATIONS:
        if not table_exists(conn, table):
            errors.append(f"TABLE MISSING: {table}")
        elif column not in get_existing_columns(conn, table):
            errors.append(f"COLUMN MISSING: {table}.{column}")

    if errors:
        print("FAILURES:")
        for e in errors:
            print(f"  ✗ {e}")
        sys.exit(1)
    else:
        print("  [OK] All expected columns verified")

    conn.close()
    print("\nMigration complete.")


if __name__ == "__main__":
    main()
