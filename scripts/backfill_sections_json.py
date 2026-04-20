"""Backfill sections_json for edgar_filings rows (v0.25.5 sprint, #537).

For every row where `full_text IS NOT NULL AND sections_json IS NULL`:
calls `parse_sections(full_text, form_type)` and writes the result.

Storage semantics (v0.25.5 decision — operator confirmed):

- Non-empty parser dict → `json.dumps(sections)`
- Empty parser dict → `'{}'` (mark attempted; distinguishes from NULL)
- Exception during parse → row skipped, appended to failure log, row stays NULL

This DIVERGES one-way from `src/data_collection/edgar_collector.py:351`,
which writes NULL for both "no full_text" and "empty dict" cases. The
backfill is explicit remediation:

  * Idempotent on re-run (same empty-dict rows skip the filter).
  * Diagnostic on upstream fetcher issue (#552): `sections_json = '{}'`
    marks rows where `_lookup_primary_document` pulled iXBRL/SGML
    instead of narrative HTML. Queryable without inspecting full_text.

Prerequisites (before running):

  1. Stop the watch loop (CLAUDE.md: DB lock coexistence).
  2. Optional: `python scripts/backfill_sections_json.py --dry-run` to count.

Run:

    python scripts/backfill_sections_json.py
    python scripts/backfill_sections_json.py --dry-run
    python scripts/backfill_sections_json.py --limit 50
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone

# Project convention — let `python scripts/foo.py` resolve `from src...`
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.config import DB_PATH
from src.data_collection.edgar_collector import parse_sections
from src.utils.db import connect_db

BATCH_SIZE_DEFAULT = 100
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FAILURE_LOG = os.path.join(REPO_ROOT, "docs", "sprints", "v0.25.5_parse_failures.log")
BASELINE_SAMPLE_SIZE = 5

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("sections_backfill")


def log_failure(log_path: str, accession: str, form_type: str,
                text_len: int, exc: BaseException) -> None:
    """Append one tab-separated failure record."""
    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
    msg = str(exc).replace("\t", " ").replace("\n", " ")[:200]
    line = f"{ts}\t{accession}\t{form_type}\t{text_len}\t{type(exc).__name__}\t{msg}\n"
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(line)


def capture_baseline(conn, sample_size: int) -> list[tuple[str, str | None]]:
    """Snapshot (accession, sections_json) for a random sample of pre-parsed rows.

    Used to verify the WHERE clause never touched already-parsed rows.
    """
    rows = conn.execute(
        "SELECT accession_number, sections_json FROM edgar_filings "
        "WHERE sections_json IS NOT NULL ORDER BY RANDOM() LIMIT ?",
        (sample_size,),
    ).fetchall()
    return [(r["accession_number"], r["sections_json"]) for r in rows]


def verify_baseline(conn, baseline: list[tuple[str, str | None]]) -> list[str]:
    """Re-read the baseline sample and return accessions that drifted."""
    drifted = []
    for acc, prev in baseline:
        r = conn.execute(
            "SELECT sections_json FROM edgar_filings WHERE accession_number = ?",
            (acc,),
        ).fetchone()
        if r is None or r["sections_json"] != prev:
            drifted.append(acc)
    return drifted


def process_row(conn, row, failure_log_path: str) -> str:
    """Parse one row and update sections_json. Returns outcome category.

    Returns one of: 'non_empty', 'empty_dict', 'failed'.
    """
    acc = row["accession_number"]
    form = row["form_type"]
    text = row["full_text"]
    try:
        sections = parse_sections(text, form)
    except Exception as e:
        log_failure(failure_log_path, acc, form, len(text) if text else 0, e)
        return "failed"

    payload = json.dumps(sections)
    conn.execute(
        "UPDATE edgar_filings SET sections_json = ? WHERE accession_number = ?",
        (payload, acc),
    )
    return "non_empty" if sections else "empty_dict"


def run_backfill(conn, batch_size: int, limit: int | None,
                 failure_log_path: str) -> dict:
    """Execute the backfill. Returns aggregate result dict."""
    q = ("SELECT accession_number, form_type, full_text FROM edgar_filings "
         "WHERE full_text IS NOT NULL AND sections_json IS NULL")
    if limit:
        q += f" LIMIT {int(limit)}"
    rows = conn.execute(q).fetchall()
    total = len(rows)
    logger.info("target rows: %d (batch_size=%d)", total, batch_size)

    outcomes = {"non_empty": 0, "empty_dict": 0, "failed": 0}
    t0 = time.perf_counter()

    for i, row in enumerate(rows, 1):
        key = process_row(conn, row, failure_log_path)
        outcomes[key] += 1
        if i % batch_size == 0:
            conn.commit()
            elapsed = time.perf_counter() - t0
            logger.info(
                "progress %d/%d (non_empty=%d, empty=%d, failed=%d, %.1fs)",
                i, total, outcomes["non_empty"], outcomes["empty_dict"],
                outcomes["failed"], elapsed,
            )
    conn.commit()  # final batch

    elapsed = time.perf_counter() - t0
    outcomes["total_attempted"] = total
    outcomes["runtime_sec"] = round(elapsed, 2)
    return outcomes


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--db-path", default=DB_PATH)
    p.add_argument("--limit", type=int, default=None,
                   help="Optional cap on rows to process (smoke test).")
    p.add_argument("--batch-size", type=int, default=BATCH_SIZE_DEFAULT)
    p.add_argument("--dry-run", action="store_true",
                   help="Count rows that would be processed; do not write.")
    p.add_argument("--failure-log", default=FAILURE_LOG)
    args = p.parse_args()

    conn = connect_db(args.db_path)

    # Dry-run: just count.
    if args.dry_run:
        (n,) = conn.execute(
            "SELECT COUNT(*) FROM edgar_filings "
            "WHERE full_text IS NOT NULL AND sections_json IS NULL"
        ).fetchone()
        logger.info("--dry-run: %d rows would be processed", n)
        conn.close()
        return 0

    # Capture baseline for post-run verification (defense-in-depth).
    baseline = capture_baseline(conn, BASELINE_SAMPLE_SIZE)
    logger.info("captured baseline: %d pre-parsed rows snapshotted",
                len(baseline))

    outcomes = run_backfill(
        conn, args.batch_size, args.limit, args.failure_log
    )

    # Verify pre-parsed rows untouched.
    drifted = verify_baseline(conn, baseline)
    conn.close()

    logger.info("=== FINAL ===")
    logger.info("attempted     : %d", outcomes["total_attempted"])
    logger.info("non_empty dict: %d", outcomes["non_empty"])
    logger.info("empty dict {} : %d", outcomes["empty_dict"])
    logger.info("failed        : %d", outcomes["failed"])
    logger.info("runtime       : %.2f s", outcomes["runtime_sec"])
    if drifted:
        logger.error("BASELINE DRIFT on %d rows: %s", len(drifted), drifted)
        return 2
    logger.info("baseline verified: 0 drift on %d pre-parsed rows", len(baseline))
    if outcomes["failed"]:
        logger.info("failure log   : %s", args.failure_log)
    return 0


if __name__ == "__main__":
    sys.exit(main())
