#!/usr/bin/env python
"""Backfill training examples for closed trades during 2026-04-13 to 2026-04-23.

Context: PR #634 added structured silent-failure detection to the
overnight training collection (issue #615). The audit window 4/13–4/23
showed the pipeline produced zero examples for 11 consecutive nights
despite 38 closed trades — the silent-failure path that #634 closed.

This one-shot script re-runs the collection logic against the missed
window so the trades retroactively land in training_examples. The
existing `collect_training_examples_from_closed_trades_detailed` function
naturally skips already-collected trades (NOT EXISTS in training_examples
clause), so re-running is idempotent — it picks up only the trades that
the broken overnight runs missed.

Usage:
    python scripts/backfill_training_4_13_to_4_23.py             # dry-run
    python scripts/backfill_training_4_13_to_4_23.py --apply     # commit

Dry-run mode counts the unprocessed trades in the window so the operator
knows what they're about to invoke. --apply runs the full self-blinding
two-stage Claude pipeline; expect ~30s per trade + Anthropic costs.

Called by: operator (manual one-shot after PR #641 merges)
Calls: src.training.data_collector.collect_training_examples_from_closed_trades_detailed,
       src.utils.db.connect_db
Owns tables: none (writes to training_examples via collection helper)
Config keys: training.enabled (must be true for the helper to act)
Tests: tests/test_tier_2_safety.py — script-presence + --dry-run flag guard
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.config import DB_PATH
from src.utils.db import connect_db

ET = ZoneInfo("America/New_York")
WINDOW_START = "2026-04-13"
WINDOW_END = "2026-04-23"


def count_pending_in_window(db_path: str) -> tuple[int, int]:
    """Return (closed_in_window, missing_from_training_examples).

    The second number is the work the --apply path would do; if zero,
    re-running is a no-op."""
    with connect_db(db_path) as conn:
        total = conn.execute(
            "SELECT COUNT(*) FROM shadow_trades "
            "WHERE status = 'closed' AND COALESCE(quarantined, 0) = 0 "
            "AND substr(actual_exit_time, 1, 10) BETWEEN ? AND ?",
            (WINDOW_START, WINDOW_END),
        ).fetchone()[0]
        missing = conn.execute(
            "SELECT COUNT(*) FROM shadow_trades st "
            "WHERE st.status = 'closed' AND COALESCE(st.quarantined, 0) = 0 "
            "AND substr(st.actual_exit_time, 1, 10) BETWEEN ? AND ? "
            "AND NOT EXISTS ("
            "    SELECT 1 FROM training_examples te "
            "    WHERE te.recommendation_id = COALESCE("
            "        st.recommendation_id, 'trade:' || st.trade_id)"
            ")",
            (WINDOW_START, WINDOW_END),
        ).fetchone()[0]
    return total, missing


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument(
        "--apply", action="store_true",
        help="Actually run the collection pipeline. Without this flag, "
             "runs in dry-run mode and only reports what would be processed.",
    )
    parser.add_argument(
        "--db-path", default=DB_PATH,
        help=f"SQLite database path (default: {DB_PATH})",
    )
    args = parser.parse_args()
    dry_run = not args.apply

    started = datetime.now(ET).isoformat()
    print(f"[BACKFILL] Started {started}")
    print(f"[BACKFILL] DB: {args.db_path}")
    print(f"[BACKFILL] Window: {WINDOW_START} to {WINDOW_END} (inclusive, ET dates)")

    try:
        total_in_window, pending = count_pending_in_window(args.db_path)
    except Exception as exc:
        print(f"[BACKFILL] Cannot read DB: {exc}")
        return 2

    print(f"[BACKFILL] Closed trades in window:    {total_in_window}")
    print(f"[BACKFILL] Already in training set:    {total_in_window - pending}")
    print(f"[BACKFILL] Pending (would be processed): {pending}")

    if pending == 0:
        print("[BACKFILL] Nothing to do — all in-window trades already collected.")
        return 0

    if dry_run:
        print(
            f"\n[DRY-RUN] Would invoke "
            f"collect_training_examples_from_closed_trades_detailed() to "
            f"process {pending} trade(s). Each runs the two-stage Claude "
            f"pipeline (~30s/trade + Anthropic API cost). Re-run with "
            f"--apply to commit."
        )
        return 0

    # --apply path
    from src.training.data_collector import (
        collect_training_examples_from_closed_trades_detailed,
    )
    print(f"\n[BACKFILL] --apply: invoking collection helper...")
    result = collect_training_examples_from_closed_trades_detailed(args.db_path)
    print(
        f"[BACKFILL] count={result.count} attempted={result.attempted} "
        f"rejected={result.rejected} stage1_failures={result.stage1_failures} "
        f"halted={result.halted}"
    )
    if result.halt_reason:
        print(f"[BACKFILL] halt_reason={result.halt_reason}")
    if result.is_silent_failure:
        print("[BACKFILL] WARNING: silent-failure indicator triggered (see #615).")
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
