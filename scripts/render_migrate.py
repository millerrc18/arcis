"""Migrate Render Postgres schema to match the schema registry.

Usage:
    $env:DATABASE_URL = "your-external-database-url"
    python scripts/render_migrate.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    import psycopg2
except ImportError:
    print("Run: pip install psycopg2-binary")
    sys.exit(1)

DATABASE_URL = os.environ.get("DATABASE_URL", "")
if not DATABASE_URL:
    print("ERROR: Set DATABASE_URL environment variable first.")
    print("  PowerShell: $env:DATABASE_URL = \"your-external-url\"")
    sys.exit(1)

from src.schema.postgres import create_all_tables, ensure_columns


def main():
    print("Connecting to Postgres...")
    create_all_tables(DATABASE_URL)
    added = ensure_columns(DATABASE_URL)
    print(f"Schema sync complete. {len(added)} columns added.")
    if added:
        for col in added:
            print(f"  [+] {col}")
    print("\nDone! Render Postgres schema is up to date.")
    print("The sync thread will populate data on the next cycle (within 2 minutes).")


if __name__ == "__main__":
    main()
