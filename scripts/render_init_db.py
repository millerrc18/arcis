"""Initialize Render Postgres tables from the schema registry.

Usage:
    DATABASE_URL=postgresql://... python scripts/render_init_db.py

Creates all tables that the sync thread pushes to. Uses IF NOT EXISTS
so it's safe to run multiple times.
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
