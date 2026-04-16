"""Backfill spy_return_over_hold, excess_return, realized_sector for
every closed trade in shadow_trades.

Idempotent — re-runs skip rows that already have all three fields set.
SPY fetch failures count as skipped_no_spy, not as data; re-running
after yfinance recovers will complete them.

Authority: docs/research/SD-41-REVISED-diagnostic-first-plan.md
Sprint: docs/sprints/sprint-D1-spy-excess-instrumentation.md

Usage:
    python scripts/backfill_spy_excess.py              # normal run
    python scripts/backfill_spy_excess.py --dry-run    # print, no writes
    python scripts/backfill_spy_excess.py --force      # re-write existing rows
"""

from __future__ import annotations

import argparse
import logging
import os
import sqlite3
import sys

# Project convention — scripts prepend the repo root so `from src...` works
# whether invoked via `python scripts/foo.py` or `python -m scripts.foo`.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.analytics.spy_benchmark import (
    excess_return,
    get_sector,
    spy_return_over_range,
)
from src.config import DB_PATH

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
)
logger = logging.getLogger(__name__)


def backfill(dry_run: bool = False, force: bool = False) -> dict:
    """Update shadow_trades rows with SPY-matched excess data.

    Returns a summary dict with counts of updated/skipped/unknown_sectors.
    """
    updated = skipped_existing = skipped_no_spy = 0
    unknown_sectors = []

    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT trade_id, ticker, actual_entry_time, actual_exit_time, "
            "pnl_pct, spy_return_over_hold, excess_return, realized_sector "
            "FROM shadow_trades "
            "WHERE actual_exit_time IS NOT NULL AND pnl_pct IS NOT NULL"
        ).fetchall()
        logger.info("Candidates: %d closed trades", len(rows))

        for row in rows:
            all_present = (
                row["spy_return_over_hold"] is not None
                and row["excess_return"] is not None
                and row["realized_sector"] is not None
            )
            if not force and all_present:
                skipped_existing += 1
                continue

            spy_ret = spy_return_over_range(
                row["actual_entry_time"], row["actual_exit_time"]
            )
            if spy_ret is None:
                skipped_no_spy += 1
                continue

            # pnl_pct can land as str or float depending on how it was written.
            try:
                pnl_pct_f = float(row["pnl_pct"])
            except (TypeError, ValueError):
                skipped_no_spy += 1
                continue
            excess = excess_return(pnl_pct_f, spy_ret)
            sector = get_sector(row["ticker"]) or "Unknown"
            if sector == "Unknown":
                unknown_sectors.append(row["ticker"])

            if dry_run:
                logger.info(
                    "[DRY] %s pnl=%.2f%% spy=%.2f%% excess=%.2f%% sector=%s",
                    row["ticker"], pnl_pct_f, spy_ret * 100, excess, sector,
                )
            else:
                conn.execute(
                    "UPDATE shadow_trades "
                    "SET spy_return_over_hold=?, excess_return=?, realized_sector=? "
                    "WHERE trade_id=?",
                    (spy_ret, excess, sector, row["trade_id"]),
                )
                updated += 1

        if not dry_run:
            conn.commit()

    result = dict(
        updated=updated,
        skipped_existing=skipped_existing,
        skipped_no_spy=skipped_no_spy,
        unknown_sectors=unknown_sectors,
    )
    logger.info("Backfill complete: %s", result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument(
        "--dry-run", action="store_true", help="print actions without writes"
    )
    parser.add_argument(
        "--force", action="store_true",
        help="re-write rows that already have all three fields",
    )
    args = parser.parse_args()
    backfill(dry_run=args.dry_run, force=args.force)
