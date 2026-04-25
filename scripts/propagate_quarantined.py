"""Propagate quarantined flag from shadow_trades to attribution_trades.

Background (audit-2026-04-27 §F-1, T1.05):
The `quarantined` flag on `shadow_trades` (added April 10 cascade) is used by
analytics filters to exclude compromised records. Both `attribution_trades` and
`walkforward_trades` now carry the same column (T1.05 schema extension), but
only `attribution_trades` has a meaningful propagation path: it links to
`shadow_trades` via `recommendation_id`. `walkforward_trades` simulates trades
inside fold windows; its `trade_id` namespace is per-run and shares no link
with shadow_trades, so its `quarantined` column is manual-only.

This script propagates `quarantined=1` from shadow_trades to attribution_trades
where the JOIN on `recommendation_id` matches. It is:
  - Idempotent: re-runs change zero rows.
  - Dry-run by default: requires `--apply` to write.
  - Batched: commits in chunks of >=50 rows (per backfill memory pattern).
"""

from __future__ import annotations

import argparse
import logging
from typing import Iterable

from src.utils.db import connect_db

logger = logging.getLogger(__name__)

BATCH_SIZE = 50


def find_propagation_candidates(conn) -> list[tuple[str, str]]:
    """Return [(attribution_id, recommendation_id), ...] needing quarantined=1.

    Matches: attribution_trades rows whose recommendation_id corresponds to a
    shadow_trades row with quarantined=1, AND the attribution_trades row is not
    already quarantined.
    """
    rows = conn.execute(
        """
        SELECT a.attribution_id, a.recommendation_id
        FROM attribution_trades a
        INNER JOIN shadow_trades s ON s.recommendation_id = a.recommendation_id
        WHERE s.quarantined = 1
          AND COALESCE(a.quarantined, 0) = 0
        """
    ).fetchall()
    return [(r["attribution_id"], r["recommendation_id"]) for r in rows]


def apply_quarantine(conn, attribution_ids: Iterable[str]) -> int:
    """Set quarantined=1 on the given attribution_ids in batches. Returns rows updated."""
    ids = list(attribution_ids)
    total = 0
    for i in range(0, len(ids), BATCH_SIZE):
        batch = ids[i:i + BATCH_SIZE]
        placeholders = ",".join("?" * len(batch))
        cur = conn.execute(
            f"UPDATE attribution_trades SET quarantined = 1 "
            f"WHERE attribution_id IN ({placeholders})",
            batch,
        )
        total += cur.rowcount
        conn.commit()
    return total


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Propagate quarantined=1 from shadow_trades to attribution_trades "
                    "via recommendation_id JOIN."
    )
    parser.add_argument(
        "--apply", action="store_true",
        help="Actually write changes. Default is dry-run (read-only).",
    )
    parser.add_argument(
        "--db", default=None,
        help="Override DB path (default: src.config.DB_PATH).",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    conn = connect_db(args.db) if args.db else connect_db()

    try:
        candidates = find_propagation_candidates(conn)
        n = len(candidates)
        logger.info("[propagate_quarantined] Found %d attribution_trades needing quarantined=1", n)

        if n == 0:
            logger.info("[propagate_quarantined] Nothing to do (idempotent re-run or no quarantined shadow_trades).")
            return 0

        if not args.apply:
            sample = ", ".join(c[0] for c in candidates[:5])
            more = "" if n <= 5 else f" ... and {n - 5} more"
            logger.info("[propagate_quarantined] DRY-RUN — sample attribution_ids: %s%s", sample, more)
            logger.info("[propagate_quarantined] Re-run with --apply to write.")
            return 0

        attribution_ids = [c[0] for c in candidates]
        updated = apply_quarantine(conn, attribution_ids)
        logger.info("[propagate_quarantined] APPLIED — updated %d attribution_trades rows", updated)

        # Idempotency check: re-run the candidate query, expect zero.
        residual = find_propagation_candidates(conn)
        if residual:
            logger.error(
                "[propagate_quarantined] WARNING: %d candidates remain after apply — "
                "should have been zero. Investigate.", len(residual),
            )
            return 1
        logger.info("[propagate_quarantined] Verified idempotent: zero residual candidates.")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
