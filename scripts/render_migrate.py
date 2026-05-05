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

import argparse
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

from src.schema.postgres import create_all_tables
from src.schema.registry import TABLES


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Additive Postgres schema sync for the Render dashboard."
    )
    parser.add_argument(
        "--connect-timeout",
        type=int,
        default=15,
        help="Postgres connect timeout in seconds (default: 15).",
    )
    parser.add_argument(
        "--lock-timeout-ms",
        type=int,
        default=15000,
        help="DDL lock wait timeout in milliseconds (default: 15000).",
    )
    return parser.parse_args()


def main():
    args = _parse_args()
    sync_tables = [table for table in TABLES.values() if table.sync_to_postgres]
    total_columns = sum(len(table.columns) for table in sync_tables)
    total_indexes = sum(len(table.indexes) for table in sync_tables)

    print(
        f"Connecting to Postgres (connect_timeout={args.connect_timeout}s, "
        f"lock_timeout={args.lock_timeout_ms}ms)...",
        flush=True,
    )
    print(
        f"Sync plan: {len(sync_tables)} tables, {total_columns} columns, "
        f"{total_indexes} indexes",
        flush=True,
    )
    try:
        added = create_all_tables(
            DATABASE_URL,
            connect_timeout=args.connect_timeout,
            lock_timeout_ms=args.lock_timeout_ms,
            progress=lambda msg: print(msg, flush=True),
        )
    except Exception as exc:  # noqa: BLE001
        pgcode = getattr(exc, "pgcode", None)
        if pgcode == "55P03":
            print(
                "Migration stopped on a Postgres lock timeout. Another writer "
                "is using one of the target tables; pause sync/collection and rerun.",
                file=sys.stderr,
                flush=True,
            )
        else:
            print(f"Migration failed: {exc}", file=sys.stderr, flush=True)
        raise
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
