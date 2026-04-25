"""Sweep shadow_trades pre-#651 and mark quarantined=1.

Background (audit-2026-04-27 §F-1, T1.01):
The April 10 cascade left a window of compromised shadow_trades rows whose
entries occurred before commit #651 landed (the live-trades real-bracket fix,
PR https://github.com/arcis/halcyon/pull/651). Records inside that window
must be marked `quarantined=1` so analytics filters
(`COALESCE(quarantined, 0) = 0`) exclude them.

Cutoff verification (run at task start, 2026-04-25):
    git log -1 --format=%aI 1d2fece   ->  2026-04-24T08:13:05-04:00 (merge commit
    of #652, which carried #651). The audit-issued spec cutoff
    `2026-04-22T20:00:00-04:00` predates the merge by ~2 days; that earlier
    instant is when bad-state writes BEGAN entering the system, not when the
    fix landed. We sweep against the spec cutoff (the start of the bad window),
    which is the conservative choice and matches the audit text.

Sweep predicate:
  - actual_entry_time IS NOT NULL
  - actual_entry_time <= '2026-04-22T20:00:00-04:00'   (boundary inclusive)
  - COALESCE(quarantined, 0) = 0

This naturally captures the in-flight case: an entry at 2026-04-21 with
exit at 2026-04-24 is swept because the entry is pre-cutoff. NULL entry
times are excluded (manual triage required).

Operational guardrails (per task spec):
  - Run during Sat 06:00-08:00 ET maintenance window OR with exclusive
    write lock on the SQLite DB. The script does not enforce the window
    (operator responsibility); the busy_timeout in connect_db gives 30s
    of slack against external-tool locks.
  - Idempotent: re-runs change zero rows.
  - Dry-run by default. `--apply` required to write.
  - Batched commits (BATCH_SIZE=50, per backfill memory pattern).
  - Post-task: re-run identical SELECT predicate; assert zero new matches.
"""

from __future__ import annotations

import argparse
import logging
from typing import Iterable

from src.utils.db import connect_db

logger = logging.getLogger(__name__)

# Spec cutoff (audit-2026-04-27 §F-1). Boundary is inclusive: a row whose
# entry is *exactly* this instant is treated as pre-cutoff and swept.
CUTOFF_ISO = "2026-04-22T20:00:00-04:00"

# Batch size per backfill memory pattern (>=50 rows per commit).
BATCH_SIZE = 50


def find_quarantine_candidates(conn) -> list[str]:
    """Return [trade_id, ...] of shadow_trades rows that need quarantined=1.

    Predicate:
      - actual_entry_time IS NOT NULL
      - actual_entry_time <= CUTOFF_ISO
      - COALESCE(quarantined, 0) = 0
    """
    rows = conn.execute(
        """
        SELECT trade_id
        FROM shadow_trades
        WHERE actual_entry_time IS NOT NULL
          AND actual_entry_time <= ?
          AND COALESCE(quarantined, 0) = 0
        """,
        (CUTOFF_ISO,),
    ).fetchall()
    return [r["trade_id"] for r in rows]


def apply_quarantine(conn, trade_ids: Iterable[str]) -> int:
    """Set quarantined=1 on the given trade_ids in batches. Returns rows updated."""
    ids = list(trade_ids)
    total = 0
    for i in range(0, len(ids), BATCH_SIZE):
        batch = ids[i:i + BATCH_SIZE]
        placeholders = ",".join("?" * len(batch))
        cur = conn.execute(
            f"UPDATE shadow_trades SET quarantined = 1 "
            f"WHERE trade_id IN ({placeholders})",
            batch,
        )
        total += cur.rowcount
        conn.commit()
    return total


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Mark quarantined=1 on shadow_trades rows whose "
                    "actual_entry_time is at or before the pre-#651 cutoff "
                    f"({CUTOFF_ISO})."
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
        candidates = find_quarantine_candidates(conn)
        n = len(candidates)
        logger.info(
            "[quarantine_pre_651] Cutoff %s — found %d shadow_trades needing quarantined=1",
            CUTOFF_ISO, n,
        )

        if n == 0:
            logger.info(
                "[quarantine_pre_651] Nothing to do (idempotent re-run or no pre-cutoff rows)."
            )
            return 0

        if not args.apply:
            sample = ", ".join(candidates[:5])
            more = "" if n <= 5 else f" ... and {n - 5} more"
            logger.info(
                "[quarantine_pre_651] DRY-RUN — sample trade_ids: %s%s", sample, more,
            )
            logger.info("[quarantine_pre_651] Re-run with --apply to write.")
            return 0

        updated = apply_quarantine(conn, candidates)
        logger.info(
            "[quarantine_pre_651] APPLIED — updated %d shadow_trades rows", updated,
        )

        # Post-task assertion: re-run identical SELECT, expect zero.
        residual = find_quarantine_candidates(conn)
        if residual:
            logger.error(
                "[quarantine_pre_651] WARNING: %d candidates remain after apply — "
                "should have been zero. Investigate.", len(residual),
            )
            return 1
        logger.info(
            "[quarantine_pre_651] Verified idempotent: zero residual candidates."
        )
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
