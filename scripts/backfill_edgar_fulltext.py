"""Backfill full_text for edgar_filings rows that are NULL.

Rate limit: ~3 req/sec (conservative under SEC's 10/sec limit).
Expected runtime: ~3362 rows / 3 = ~20 minutes.

Run manually by the operator:
    python scripts/backfill_edgar_fulltext.py
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
import time

# Project convention — scripts prepend the repo root so `from src...` works
# whether invoked via `python scripts/foo.py` or `python -m scripts.foo`.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.config import DB_PATH
from src.data_collection.edgar_collector import _fetch_filing_text
from src.utils.db import connect_db

RATE_LIMIT_SEC = 1 / 3  # 3 requests per second


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--db-path", default=DB_PATH)
    p.add_argument("--limit", type=int, default=None,
                   help="Optional cap on rows to process (for smoke-testing).")
    p.add_argument("--dry-run", action="store_true",
                   help="Count rows that would be processed; do not fetch.")
    args = p.parse_args()

    conn = connect_db(args.db_path)
    q = "SELECT cik, accession_number FROM edgar_filings WHERE full_text IS NULL"
    if args.limit:
        q += f" LIMIT {args.limit}"
    rows = conn.execute(q).fetchall()
    total = len(rows)
    print(f"[EDGAR] Backfill target: {total} rows")

    if args.dry_run:
        conn.close()
        print("[EDGAR] --dry-run — exiting without fetching")
        return 0

    success = fail = 0
    for i, row in enumerate(rows, 1):
        text = _fetch_filing_text(row["cik"], row["accession_number"])
        if text:
            conn.execute(
                "UPDATE edgar_filings SET full_text = ? "
                "WHERE accession_number = ?",
                (text, row["accession_number"]),
            )
            success += 1
        else:
            fail += 1
        if i % 50 == 0:
            conn.commit()
            print(f"[EDGAR] progress {i}/{total} "
                  f"(success={success}, fail={fail})")
        time.sleep(RATE_LIMIT_SEC)
    conn.commit()
    conn.close()
    coverage_pct = (success / total * 100) if total else 0
    print(f"[EDGAR] Done. success={success}, fail={fail}, "
          f"total={total}, coverage={coverage_pct:.1f}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
