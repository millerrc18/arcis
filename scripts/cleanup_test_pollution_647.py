"""Cleanup historical test-pollution rows in prod activity_log (#650).

Removes kill_switch_halt + kill_switch_resume rows whose `detail` field
matches one of the known test-fixture signatures from pre-#647 leakage.
Default is --dry-run; --apply requires explicit operator opt-in.

Safety design:
  - DENY-BY-DEFAULT: only deletes rows matching a hard-coded whitelist of
    known test signatures. A novel signature (e.g. a new test fixture
    leaking with a different source string) is NEVER deleted automatically.
  - CUTOFF TIMESTAMP: --cutoff (default = #647 PR merge time) excludes any
    rows created after the fix landed. Preserves post-fix legitimate halts
    even if they happen to share a signature.
  - PER-SIGNATURE DRY-RUN OUTPUT: prints count + sample row for each
    signature so the operator can review before --apply.

Usage:
    python scripts/cleanup_test_pollution_647.py                   # dry run
    python scripts/cleanup_test_pollution_647.py --apply           # delete
    python scripts/cleanup_test_pollution_647.py --apply --db-path <path>
    python scripts/cleanup_test_pollution_647.py --cutoff 2026-04-24T12:00:00
"""
import argparse
import os
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.utils.db import connect_db

# #647 (PR #648) merged at 2026-04-24T11:57:33Z. Anything older than this
# AND matching a known test signature is safe to delete. Use ET ISO format
# matching activity_log.created_at column convention.
DEFAULT_CUTOFF = "2026-04-24T08:00:00"  # ET, conservative buffer

# Known test-fixture signatures from tests/test_kill_switch.py,
# tests/test_risk_governor.py, and tests/test_auditor.py — verified by
# count analysis (99/99/99 + 91/91/91/92) and string match against
# test source.
SIGNATURES = {
    "kill_switch_halt": [
        "source=unknown, reason=",
        "source=test, reason=unit test",
        "source=test, reason=",
        "source=telegram, reason=manual halt",
        "source=auditor, reason=Halt command ignored",
        "source=auditor, reason=Governor check bypassed",
        "source=auditor, reason=Catastrophic loss detected",
    ],
    "kill_switch_resume": [
        "source=unknown, reason=",
        "source=test, reason=",
        "source=test, reason=unit test",
        "source=telegram, reason=",
    ],
}


def _resolve_db_path(arg_path: str | None) -> str:
    """Match scripts/statusline.py's resolution: env var > .env > default."""
    if arg_path:
        return arg_path
    env_path = os.environ.get("ARCIS_DB_PATH")
    if env_path:
        return env_path
    repo_root = Path(__file__).resolve().parent.parent
    env_file = repo_root / ".env"
    if env_file.exists():
        try:
            for line in env_file.read_text().splitlines():
                line = line.strip()
                if line.startswith("ARCIS_DB_PATH="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
        except OSError:
            pass
    return str(repo_root / "data" / "ai_research_desk.sqlite3")


def main():
    parser = argparse.ArgumentParser(
        description="Delete historical test-pollution rows from activity_log (#650)"
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually DELETE matching rows. Without this flag, runs in dry-run mode.",
    )
    parser.add_argument(
        "--db-path",
        help="Override DB path. Default: resolved from ARCIS_DB_PATH or .env.",
    )
    parser.add_argument(
        "--cutoff",
        default=DEFAULT_CUTOFF,
        help=f"ISO timestamp: don't delete rows newer than this. Default: {DEFAULT_CUTOFF}",
    )
    args = parser.parse_args()

    db_path = _resolve_db_path(args.db_path)
    if not Path(db_path).exists():
        print(f"ERROR: DB not found at {db_path}", file=sys.stderr)
        return 1

    mode = "APPLY" if args.apply else "DRY RUN"
    print(f"=== {mode} ===")
    print(f"DB:     {db_path}")
    print(f"Cutoff: {args.cutoff}  (rows newer than this are preserved)")
    print()

    total_to_delete = 0
    sql_per_event = []

    with connect_db(db_path) as conn:
        for event_type, sigs in SIGNATURES.items():
            placeholders = ",".join("?" * len(sigs))
            params = (*sigs, args.cutoff)
            count = conn.execute(
                f"SELECT COUNT(*) FROM activity_log "
                f"WHERE event_type=? AND detail IN ({placeholders}) "
                f"AND created_at < ?",
                (event_type, *params),
            ).fetchone()[0]
            print(f"  {event_type}: {count} rows match")
            for sig in sigs:
                sub = conn.execute(
                    "SELECT COUNT(*) FROM activity_log "
                    "WHERE event_type=? AND detail=? AND created_at < ?",
                    (event_type, sig, args.cutoff),
                ).fetchone()[0]
                if sub:
                    print(f"    {sub:5d}  detail={sig!r}")
            sql_per_event.append((event_type, sigs, params, count))
            total_to_delete += count

        print()
        print(f"TOTAL to delete: {total_to_delete}")

        if not args.apply:
            print()
            print("DRY RUN - no rows changed. Re-run with --apply to delete.")
            return 0

        if total_to_delete == 0:
            print("Nothing to delete.")
            return 0

        # Apply phase
        print()
        for event_type, sigs, params, expected in sql_per_event:
            placeholders = ",".join("?" * len(sigs))
            cur = conn.execute(
                f"DELETE FROM activity_log "
                f"WHERE event_type=? AND detail IN ({placeholders}) "
                f"AND created_at < ?",
                (event_type, *params),
            )
            print(f"  Deleted {cur.rowcount} from {event_type} (expected {expected})")
        conn.commit()
        print()
        print("Committed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
