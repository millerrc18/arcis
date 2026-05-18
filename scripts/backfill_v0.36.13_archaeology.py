"""One-shot data-archaeology cleanup for v0.36.13.

Run manually after v0.36.13 release. Not auto-scheduled.

Removes sentinel duration_days=999 from 11 'unknown' + 3 'manual' trades that
were polluting the audit's avg-hold-period calculation (137d vs realistic
1.5d). Leaves exit_reason='unknown' as-is — we don't know what happened.

Best-effort regime backfill for shadow_trades.regime_at_entry IS NULL — only
if a daily-grain regime table exists in the schema.

Usage:
    python scripts/backfill_v0.36.13_archaeology.py             # interactive
    python scripts/backfill_v0.36.13_archaeology.py --dry-run   # smoke test
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ---------------------------------------------------------------------------
# Regime table probe: known candidate names from src/schema/registry.py
# ---------------------------------------------------------------------------

_REGIME_TABLE_CANDIDATES = [
    "market_regime",
    "regime_state",
    "daily_regime",
]


def _probe_regime_table(conn) -> str | None:
    """Return the name of a daily-grain regime table, or None if absent.

    Probes candidate table names via information_schema (PG-safe — doesn't
    trigger the transaction-abort cascade that bare `SELECT FROM <table>`
    would on a missing relation in PG).

    W21 P1-1 fix: previous version did `SELECT 1 FROM <name> LIMIT 1` and
    caught the error in a generic except. On PG, the failed query aborts
    the surrounding transaction, causing all subsequent queries to fail
    with "current transaction is aborted". information_schema.tables
    succeeds regardless of whether the candidate exists.
    """
    for name in _REGIME_TABLE_CANDIDATES:
        try:
            row = conn.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_name = ? LIMIT 1",
                (name,),
            ).fetchone()
            if row is not None:
                return name
        except Exception:
            # SQLite path: information_schema doesn't exist; fall back to
            # sqlite_master probe (also recoverable, no tx-abort on SQLite).
            try:
                row = conn.execute(
                    f"SELECT 1 FROM {name} LIMIT 1"
                ).fetchone()
                if row is not None or row is None:
                    # The query succeeded (even if 0 rows). Table exists.
                    return name
            except Exception:
                continue
    return None


def _print_pre_counts(conn) -> None:
    def _count(sql):
        row = conn.execute(sql).fetchone()
        if row is None:
            return 0
        return row[0]

    c1 = _count(
        "SELECT COUNT(*) FROM shadow_trades "
        "WHERE exit_reason='unknown' AND duration_days=999"
    )
    c2 = _count(
        "SELECT COUNT(*) FROM shadow_trades "
        "WHERE exit_reason='manual' AND duration_days=999"
    )
    c3 = _count(
        "SELECT COUNT(*) FROM shadow_trades "
        "WHERE regime_at_entry IS NULL"
    )
    print(f"[PRE]  exit_reason='unknown' AND duration_days=999  → {c1}")
    print(f"[PRE]  exit_reason='manual'  AND duration_days=999  → {c2}")
    print(f"[PRE]  regime_at_entry IS NULL                      → {c3}  (informational)")


def _print_post_counts(conn) -> None:
    def _count(sql):
        row = conn.execute(sql).fetchone()
        if row is None:
            return 0
        return row[0]

    c1 = _count(
        "SELECT COUNT(*) FROM shadow_trades "
        "WHERE exit_reason='unknown' AND duration_days=999"
    )
    c2 = _count(
        "SELECT COUNT(*) FROM shadow_trades "
        "WHERE exit_reason='manual' AND duration_days=999"
    )
    c3 = _count(
        "SELECT COUNT(*) FROM shadow_trades "
        "WHERE regime_at_entry IS NULL"
    )
    print(f"[POST] exit_reason='unknown' AND duration_days=999  → {c1}")
    print(f"[POST] exit_reason='manual'  AND duration_days=999  → {c2}")
    print(f"[POST] regime_at_entry IS NULL                      → {c3}  (informational)")


def _run_updates(conn) -> None:
    conn.execute(
        "UPDATE shadow_trades "
        "SET duration_days=NULL, actual_entry_time=NULL "
        "WHERE exit_reason='unknown' AND duration_days=999"
    )
    conn.execute(
        "UPDATE shadow_trades "
        "SET duration_days=NULL, actual_entry_time=NULL "
        "WHERE exit_reason='manual' AND duration_days=999"
    )


def _attempt_regime_backfill(conn) -> None:
    regime_table = _probe_regime_table(conn)
    if regime_table is None:
        print("[REGIME] Backfill skipped — no daily regime history available.")
        return
    try:
        conn.execute(
            f"UPDATE shadow_trades "
            f"SET regime_at_entry = ("
            f"  SELECT regime FROM {regime_table} "
            f"  WHERE date <= actual_entry_time "
            f"  ORDER BY date DESC LIMIT 1"
            f") "
            f"WHERE regime_at_entry IS NULL AND actual_entry_time IS NOT NULL"
        )
        print(f"[REGIME] Backfill attempted from table '{regime_table}'.")
    except Exception as exc:
        print(f"[REGIME] Backfill skipped — query error: {exc}")


def main(argv: list[str] | None = None, *, conn=None) -> int:
    """Entry point. Returns exit code (0 = success, 1 = unexpected error).

    The optional `conn` parameter allows tests to inject a sqlite3 connection
    instead of opening a real Postgres connection.
    """
    parser = argparse.ArgumentParser(
        description="One-shot archaeology cleanup for v0.36.13."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Force rollback regardless of input; skip the prompt.",
    )
    parser.add_argument(
        "--db-url",
        default=None,
        help="Override DATABASE_URL.",
    )
    args = parser.parse_args(argv)

    _owns_conn = False
    try:
        if conn is None:
            _owns_conn = True
            db_url = args.db_url or os.environ.get("DATABASE_URL", "")
            if not db_url:
                print(
                    "ERROR: DATABASE_URL is not set. "
                    "Pass --db-url or set the DATABASE_URL environment variable.",
                    file=sys.stderr,
                )
                return 1
            try:
                import psycopg2
                import psycopg2.extras
            except ImportError:
                print("Run: pip install psycopg2-binary", file=sys.stderr)
                return 1
            # W21 P1-1 fix: wrap with PostgresConnectionWrapper so the script's
            # `conn.execute(...)` calls work uniformly across psycopg2 and
            # sqlite3 (psycopg2 connection objects don't expose top-level
            # execute()). The wrapper also handles the `?`->`%s` rewrite.
            from src.utils.db import PostgresConnectionWrapper
            raw = psycopg2.connect(
                db_url, cursor_factory=psycopg2.extras.RealDictCursor
            )
            raw.autocommit = False
            conn = PostgresConnectionWrapper(raw)

        _print_pre_counts(conn)
        print()

        _run_updates(conn)
        _attempt_regime_backfill(conn)

        print()
        _print_post_counts(conn)
        print()

        if args.dry_run:
            conn.rollback()
            print("[DRY-RUN] Transaction rolled back. No changes applied.")
            return 0

        answer = input("Type 'COMMIT' to commit, anything else to ROLLBACK: ").strip()
        if answer == "COMMIT":
            conn.commit()
            print("[DONE] Transaction committed. Sentinel rows cleaned up.")
        else:
            conn.rollback()
            print("[CANCELLED] Transaction rolled back. No changes applied.")

        return 0

    except Exception as exc:
        print(f"[ERROR] Unexpected exception: {exc}", file=sys.stderr)
        if conn is not None:
            try:
                conn.rollback()
            except Exception:
                pass
        return 1
    finally:
        if _owns_conn and conn is not None:
            try:
                conn.close()
            except Exception:
                pass


if __name__ == "__main__":
    sys.exit(main())
