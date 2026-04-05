"""Initialize Render Postgres tables from the schema registry.

When to run:
    Once when provisioning a new Render Postgres instance, or after
    a destructive database reset. After initial setup, use render_migrate.py
    for incremental schema updates.

What it reads:
    - DATABASE_URL environment variable (Render external Postgres URL)
    - src/schema/registry.py via src/schema/postgres module

What it writes:
    - Creates all tables in Postgres using IF NOT EXISTS (idempotent)
    - Adds any missing columns to existing tables

Prerequisites:
    - psycopg2-binary installed
    - DATABASE_URL set to the Render external connection string

Usage:
    DATABASE_URL=postgresql://... python scripts/render_init_db.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.schema.postgres import create_all_tables, ensure_columns


def init_postgres(database_url: str) -> None:
    """Connect to Postgres and create all tables from the registry."""
    print("Connecting to Postgres...")
    try:
        create_all_tables(database_url)
        added = ensure_columns(database_url)
        print("All tables created successfully.")
        if added:
            print(f"Added {len(added)} columns: {added}")
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)


def main():
    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url:
        print("ERROR: Set DATABASE_URL environment variable.", file=sys.stderr)
        print("  Example: DATABASE_URL=postgresql://user:pass@host:5432/halcyon", file=sys.stderr)
        sys.exit(1)

    init_postgres(database_url)


if __name__ == "__main__":
    main()
