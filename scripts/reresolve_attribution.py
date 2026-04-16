"""Re-run the (fixed) resolver against rows tagged v1_multiindex_bug.

Writes new values into ranker_only_outcome / ranker_only_pnl_pct and sets
resolution_version = 'v2_fixed'. Preserves the old values in two archive
columns for forensic comparison: ranker_only_outcome_v1, ranker_only_pnl_pct_v1.

Idempotent — re-running after first pass shows `reresolved=0` because no
v1_multiindex_bug rows remain.

Authority: docs/research/attribution-resolver-audit.md (SD#41 REVISED D2)
Sprint: docs/sprints/sprint-attribution-resolver-fix.md

Usage:
    python scripts/reresolve_attribution.py            # normal run
    python scripts/reresolve_attribution.py --dry-run  # snapshot only, no reset/rewrite
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

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
)
logger = logging.getLogger(__name__)


def reresolve(dry_run: bool = False) -> dict:
    """Snapshot v1, reset v1-tagged rows to 'pending', re-resolve, tag v2_fixed.

    Returns a summary dict with snapshotted / reset / reresolved / tagged counts.
    """
    with sqlite3.connect(DB_PATH) as conn:
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
            return {"snapshotted": n_snap, "reset": 0, "reresolved": 0, "tagged": 0, "dry_run": True}

        # Reset v1-tagged rows to pending so resolve_pending_outcomes picks them up.
        n_reset = conn.execute(
            """
            UPDATE attribution_trades SET ranker_only_outcome='pending'
            WHERE resolution_version='v1_multiindex_bug'
            """
        ).rowcount
        conn.commit()
        logger.info("Reset %d v1-tagged rows to 'pending' for re-resolution", n_reset)

    # Call the fixed resolver (no connection held across the potentially-slow
    # yfinance loop).
    n_resolved = resolve_pending_outcomes(DB_PATH)

    # Tag the newly-resolved rows as v2_fixed. Any that failed to resolve
    # (yfinance empty/delisted) remain resolution_version='v1_multiindex_bug'
    # with outcome='pending' — eligible for retry on next run.
    with sqlite3.connect(DB_PATH) as conn:
        n_tagged = conn.execute(
            """
            UPDATE attribution_trades SET resolution_version='v2_fixed'
            WHERE resolution_version='v1_multiindex_bug'
              AND ranker_only_outcome != 'pending'
            """
        ).rowcount
        conn.commit()

    result = {
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
                        help="snapshot only; skip reset/re-resolve/tag")
    args = parser.parse_args()
    reresolve(dry_run=args.dry_run)
