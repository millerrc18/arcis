"""One-off scrub for validation_results rows that may contain leaked credentials.

Audit #414: raw ``str(e)[:N]`` call sites could persist tokens embedded in
exception strings (Telegram bot tokens, postgres:// URLs with creds, etc.).
Run this script once after the sanitize fix deploys to redact any historical
rows in-place.  Expected count is small (validation_results retains 90 days).

Usage:
    python scripts/scrub_validation_leaks.py [--dry-run]

Delete this script after it has been run in every environment that hosts
validation_results.
"""
from __future__ import annotations

import argparse
import sqlite3
import sys

from src.config import DB_PATH
from src.utils.secret_redact import _TOKEN_PATTERNS


def scrub(db_path: str, dry_run: bool) -> int:
    redacted = 0
    scanned = 0
    conn = sqlite3.connect(db_path, timeout=10)
    try:
        rows = conn.execute(
            "SELECT result_id, results_json FROM validation_results"
        ).fetchall()
        for result_id, blob in rows:
            scanned += 1
            if not blob:
                continue
            new_blob = blob
            for pattern in _TOKEN_PATTERNS:
                new_blob = pattern.sub("<REDACTED>", new_blob)
            if new_blob != blob:
                redacted += 1
                print(f"  redact: {result_id}")
                if not dry_run:
                    conn.execute(
                        "UPDATE validation_results SET results_json=? WHERE result_id=?",
                        (new_blob, result_id),
                    )
        if not dry_run:
            conn.commit()
    finally:
        conn.close()
    print(f"scanned={scanned} redacted={redacted} dry_run={dry_run}")
    if redacted == 0 and not dry_run:
        print(
            "No rows required redaction. The sanitize_error + sanitize_text fix "
            "has closed the leak path at write time. This script is one-shot — "
            "delete scripts/scrub_validation_leaks.py now that it has run clean."
        )
    return redacted


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true",
                        help="Report what would be redacted without writing")
    parser.add_argument("--db", default=DB_PATH,
                        help="Path to SQLite database")
    args = parser.parse_args()
    scrub(args.db, args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
