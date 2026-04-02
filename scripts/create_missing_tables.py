"""Create all missing tables from the schema registry.

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
