"""Create all missing tables from the schema registry.

When to run:
    After adding new TableDefs to src/schema/registry.py, or when setting
    up a fresh database. Equivalent to `validate-schema --fix` but faster
    because it skips the drift check. See #207 for DDL centralization.

What it reads:
    - src/schema/registry.py (all 49 table definitions)

What it writes:
    - Creates missing tables and adds missing columns in the local SQLite DB
    - Idempotent — safe to run multiple times

Prerequisites:
    - Database path configured in src/config.DB_PATH

Usage:
    python scripts/create_missing_tables.py
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.config import DB_PATH
from src.schema.sqlite import create_all_tables, ensure_columns


def main():
    print(f"Creating tables from schema registry in {DB_PATH}...")
    create_all_tables(DB_PATH)
    added = ensure_columns(DB_PATH)
    if added:
        print(f"Added {len(added)} columns: {added}")
    print("Done.")


if __name__ == "__main__":
    main()
