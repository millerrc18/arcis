"""One-time migration: mark existing failed trades as failed_permanent.

Usage: python scripts/mark_failed_trades.py [--dry-run]
"""

import sqlite3
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.config import DB_PATH


def main():
    dry_run = "--dry-run" in sys.argv
    with sqlite3.connect(DB_PATH) as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM shadow_trades WHERE status = 'failed'"
        ).fetchone()[0]
        print(f"Found {count} trades with status='failed'")

        if dry_run:
            print("DRY RUN — no changes made")
            return

        conn.execute(
            "UPDATE shadow_trades SET status = 'failed_permanent' WHERE status = 'failed'"
        )
        print(f"Updated {count} trades to status='failed_permanent'")


if __name__ == "__main__":
    main()
