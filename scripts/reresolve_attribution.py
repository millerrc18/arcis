"""Re-run the (fixed) resolver against rows tagged v1_multiindex_bug.

Writes new values into ranker_only_outcome / ranker_only_pnl_pct and sets
resolution_version = 'v2_fixed'. Preserves the old values in two archive
columns for forensic comparison: ranker_only_outcome_v1, ranker_only_pnl_pct_v1.

Idempotent — re-running after first pass shows `reresolved=0` because no
v1_multiindex_bug rows with a complete resolution window remain.

Authority: docs/research/attribution-resolver-audit.md (SD#41 REVISED D2)
Sprint: docs/sprints/sprint-attribution-resolver-fix.md

Hotfix bugs (fixed when Ryan ran the initial script locally):

1. **NULL resolution_version at script start.** The v0.22.0 schema migration
   added resolution_version as a new TEXT column. Existing resolved rows had
   `resolution_version IS NULL` at the moment the column landed. The
   snapshot step filtered on `resolution_version = 'v1_multiindex_bug'` and
   matched zero rows. Fix: `_tag_null_as_v1` back-tags every resolved row
   with NULL resolution_version as 'v1_multiindex_bug' BEFORE snapshotting.

2. **Future-window lookups.** The resolver computes the 7-day window as
   `scan_timestamp + 1 day` through `+ 8 days`. For recent scans (last ~8
   days) the end date is in the future, which makes yfinance return empty
   and the row stay pending — fine in isolation, but the script was
   re-resolving 1,600 rows sequentially including those future-window rows
   (wasted API calls and time). Fix: when resetting v1 rows to 'pending',
   only reset rows where `DATE(scan_timestamp, '+8 days') <= DATE('now')`.
   Rows whose window hasn't fully elapsed stay v1-tagged with their
   original outcome; the nightly `resolve_pending_outcomes` picks them up
   naturally once their window closes.

Usage:
    python scripts/reresolve_attribution.py            # normal run
    python scripts/reresolve_attribution.py --dry-run  # pre-tag + snapshot only, no reset/rewrite
"""

from __future__ import annotations

import argparse
import logging
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.attribution.logger import resolve_pending_outcomes  # noqa: E402
from src.config import DB_PATH  # noqa: E402
from src.utils.db import connect_db  # noqa: E402

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
)
logger = logging.getLogger(__name__)


def _tag_null_as_v1(conn: sqlite3.Connection) -> int:
    """Hotfix bug 1 — back-tag resolved rows whose resolution_version is NULL.

    The column was added by the v0.22.0 migration AFTER those rows were
    written, so they have NULL. This is the canonical back-tag step and is
    idempotent (second run matches zero rows).
    """
    return conn.execute(
        """
        UPDATE attribution_trades
        SET resolution_version = 'v1_multiindex_bug'
        WHERE ranker_only_outcome != 'pending'
          AND resolution_version IS NULL
        """
    ).rowcount


def reresolve(dry_run: bool = False) -> dict:
    """Snapshot v1, reset v1-tagged rows to 'pending', re-resolve, tag v2_fixed.

    Returns a summary dict with pre_tagged / snapshotted / reset /
    reresolved / tagged counts.
    """
    with connect_db(DB_PATH) as conn:
        # Bug 1 fix — back-tag NULL resolution_version rows before anything else.
        n_pre_tag = _tag_null_as_v1(conn)
        conn.commit()
        logger.info("Pre-tagged %d rows with NULL resolution_version as v1_multiindex_bug", n_pre_tag)

        # Snapshot v1 values (first-run only; idempotent because the v1 columns
        # are only set when ranker_only_outcome_v1 IS NULL).
        n_snap = conn.execute(
            """
            UPDATE attribution_trades
            SET ranker_only_outcome_v1 = ranker_only_outcome,
                ranker_only_pnl_pct_v1 = CAST(ranker_only_pnl_pct AS TEXT)
            WHERE resolution_version = 'v1_multiindex_bug'
              AND ranker_only_outcome_v1 IS NULL
            """
        ).rowcount
        conn.commit()
        logger.info("Snapshotted v1 values on %d rows", n_snap)

        if dry_run:
            return {
                "pre_tagged": n_pre_tag, "snapshotted": n_snap,
                "reset": 0, "reresolved": 0, "tagged": 0, "dry_run": True,
            }

        # Bug 2 fix — only reset rows whose 7-day window has fully elapsed.
        # Rows scanned in the last ~8 days stay v1-tagged with their original
        # (buggy) outcome. The nightly resolve_pending_outcomes picks them up
        # once their window closes. Avoids wasted yfinance calls on future dates.
        n_reset = conn.execute(
            """
            UPDATE attribution_trades SET ranker_only_outcome='pending'
            WHERE resolution_version='v1_multiindex_bug'
              AND DATE(scan_timestamp, '+8 days') <= DATE('now')
            """
        ).rowcount
        conn.commit()
        logger.info("Reset %d elapsed-window v1 rows to 'pending' for re-resolution", n_reset)

    # Call the fixed resolver (no connection held across the potentially-slow
    # yfinance loop).
    n_resolved = resolve_pending_outcomes(DB_PATH)

    # Tag the newly-resolved rows as v2_fixed. Any that failed to resolve
    # (yfinance empty/delisted) remain resolution_version='v1_multiindex_bug'
    # with outcome='pending' — eligible for retry on next run.
    with connect_db(DB_PATH) as conn:
        n_tagged = conn.execute(
            """
            UPDATE attribution_trades SET resolution_version='v2_fixed'
            WHERE resolution_version='v1_multiindex_bug'
              AND ranker_only_outcome != 'pending'
            """
        ).rowcount
        conn.commit()

    result = {
        "pre_tagged": n_pre_tag,
        "snapshotted": n_snap,
        "reset": n_reset,
        "reresolved": n_resolved,
        "tagged": n_tagged,
    }
    logger.info("Re-resolution complete: %s", result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true",
                        help="pre-tag + snapshot only; skip reset/re-resolve/tag")
    args = parser.parse_args()
    reresolve(dry_run=args.dry_run)
