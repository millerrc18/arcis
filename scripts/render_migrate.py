"""Migrate Render Postgres schema to match the schema registry.

When to run:
    After any change to src/schema/registry.py that adds tables or columns.
    Also run after deploying a new Render instance. See CLAUDE.md
    "Postgres sync (after schema changes)" section.

What it reads:
    - DATABASE_URL environment variable (Render external Postgres URL)
    - src/schema/registry.py via src/schema/postgres module

What it writes:
    - Creates missing tables and adds missing columns in Render Postgres.
      Never drops or renames anything — additive only.

Prerequisites:
    - psycopg2-binary installed
    - DATABASE_URL set to the Render external connection string
    - Schema registry (src/schema/registry.py) is the source of truth (#207)

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
    # The sync thread in src/sync/ pushes data from local SQLite to Postgres
    # on a ~2-minute cycle, so new tables will be populated shortly.
    print("The sync thread will populate data on the next cycle (within 2 minutes).")


if __name__ == "__main__":
    main()
