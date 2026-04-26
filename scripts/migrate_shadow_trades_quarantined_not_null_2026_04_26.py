"""Migrate shadow_trades.quarantined to NOT NULL DEFAULT 0 (PR-690 O7).

Background (PR-690 O7, 2026-04-26):
The `quarantined` flag on `shadow_trades` was originally added (#651, April 10
cascade) as `INTEGER DEFAULT 0` — nullable. Sibling columns
`attribution_trades.quarantined` and `walkforward_trades.quarantined` (T1.05)
inherited the same shape. Operator review of PR #690 flagged that semantically
every row must carry an explicit 0/1 quarantined flag — `NULL` is undefined
behaviour and the integration test in `tests/integration/test_track_1_5_full_pipeline.py`
was previously accepting both `0` and `NULL` ("schema drift").

This migration:
  1. Backfills any existing NULL → 0 in batches of >=50 rows (per CLAUDE.md
     backfill memory pattern).
  2. Performs a SQLite table-rebuild to enforce `NOT NULL DEFAULT 0` at the
     DDL level. SQLite cannot ALTER the nullability of an existing column
     in-place; the canonical workaround is the 12-step ALTER TABLE procedure
     condensed here as: PRAGMA foreign_keys=OFF → BEGIN → CREATE NEW →
     INSERT SELECT → DROP OLD → RENAME → recreate indexes → COMMIT →
     PRAGMA foreign_keys=ON → integrity check.
     See https://sqlite.org/lang_altertable.html#otheralter for the full
     reference.

The new schema for `shadow_trades` is generated from the registry, so this
script stays in sync if other columns are added between now and when an
operator runs it on a stale DB.

Idempotent:
  - If the column is already NOT NULL, both phases short-circuit.
  - Re-running after success is a no-op (zero rows backfilled, no rebuild).

Usage:
    python scripts/migrate_shadow_trades_quarantined_not_null_2026_04_26.py
        # Dry-run (default): reports what would change. No writes.

    python scripts/migrate_shadow_trades_quarantined_not_null_2026_04_26.py --apply
        # Actually run the migration.

    python scripts/migrate_shadow_trades_quarantined_not_null_2026_04_26.py --apply --db /path/to/test.db
        # Run against an alternate DB (used in tests / staging).

Operational guardrails:
  - Run during a maintenance window with no concurrent writers (watch loop
    stopped). The table-rebuild phase takes an exclusive write lock and a
    concurrent INSERT during the rebuild would fail with `database is locked`.
  - busy_timeout is set to 30s by `connect_db` (ride through external-tool
    locks, not concurrent watch-loop writes).
  - On any error during the rebuild, the BEGIN/COMMIT wrapping rolls back
    so the original `shadow_trades` table is preserved unmodified.

Tests:
    tests/scripts/test_migrate_shadow_trades_quarantined_not_null.py
"""

from __future__ import annotations

import argparse
import logging
import os
import sys

# Make src importable when running this script directly.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.schema.registry import TABLES
from src.schema.sqlite import generate_create_sql
from src.utils.db import connect_db

logger = logging.getLogger(__name__)

BATCH_SIZE = 50  # CLAUDE.md backfill memory pattern: >=50 rows per commit.


# ---------------------------------------------------------------------------
# Phase 1: Backfill NULL → 0
# ---------------------------------------------------------------------------

def find_null_quarantined_trade_ids(conn) -> list[str]:
    """Return list of trade_ids where quarantined IS NULL.

    Mark-attempted pattern (CLAUDE.md): we set 0, NOT NULL, so this query is
    the authoritative source of "rows that need backfilling".
    """
    rows = conn.execute(
        "SELECT trade_id FROM shadow_trades WHERE quarantined IS NULL"
    ).fetchall()
    return [r["trade_id"] for r in rows]


def backfill_null_quarantined(conn, trade_ids: list[str]) -> int:
    """Set quarantined=0 on the given trade_ids in batches. Returns rows updated.

    Commits per batch (>=50 rows) so a long-running migration is incrementally
    durable — interrupting halfway leaves the already-backfilled rows persisted.
    """
    total = 0
    for i in range(0, len(trade_ids), BATCH_SIZE):
        batch = trade_ids[i:i + BATCH_SIZE]
        placeholders = ",".join("?" * len(batch))
        cur = conn.execute(
            f"UPDATE shadow_trades SET quarantined = 0 "
            f"WHERE trade_id IN ({placeholders})",
            batch,
        )
        total += cur.rowcount
        conn.commit()
    return total


# ---------------------------------------------------------------------------
# Phase 2: Detect whether the column is already NOT NULL
# ---------------------------------------------------------------------------

def is_quarantined_not_null(conn) -> bool:
    """Return True if shadow_trades.quarantined already has NOT NULL constraint.

    Reads PRAGMA table_info; column 3 ('notnull') is 1 when NOT NULL is set.
    """
    rows = conn.execute("PRAGMA table_info(shadow_trades)").fetchall()
    for row in rows:
        # PRAGMA table_info columns: (cid, name, type, notnull, dflt_value, pk)
        if row["name"] == "quarantined":
            return bool(row["notnull"])
    raise RuntimeError(
        "shadow_trades.quarantined column not found — schema is unexpected"
    )


# ---------------------------------------------------------------------------
# Phase 3: Table rebuild to enforce NOT NULL
# ---------------------------------------------------------------------------

def _registered_indexes() -> list[tuple[str, list[str], bool]]:
    """Return [(idx_name, [cols], unique), ...] for shadow_trades."""
    table = TABLES["shadow_trades"]
    return [(idx.name, idx.columns, idx.unique) for idx in table.indexes]


def _registered_columns() -> list[str]:
    """Return ordered list of column names from the registry."""
    return [c.name for c in TABLES["shadow_trades"].columns]


def rebuild_shadow_trades_with_not_null(conn) -> None:
    """Run the SQLite table-rebuild dance to enforce NOT NULL on quarantined.

    Steps (per https://sqlite.org/lang_altertable.html#otheralter):
      1. PRAGMA foreign_keys = OFF
      2. BEGIN TRANSACTION
      3. CREATE shadow_trades_new (full schema from registry)
      4. INSERT INTO shadow_trades_new SELECT <cols> FROM shadow_trades
         (using the registry column list to handle ordering / future additions)
      5. DROP TABLE shadow_trades
      6. ALTER TABLE shadow_trades_new RENAME TO shadow_trades
      7. Recreate indexes
      8. PRAGMA foreign_key_check (should return zero rows)
      9. COMMIT
     10. PRAGMA foreign_keys = ON

    On any exception the transaction rolls back and the original table is
    untouched. We do NOT catch exceptions here — the caller's outer handler
    is responsible for rollback messaging.
    """
    # 1. Disable FK checks so the DROP doesn't trigger CASCADE on referrers.
    #    SQLite recommends this when doing the rename dance.
    conn.execute("PRAGMA foreign_keys = OFF")

    table = TABLES["shadow_trades"]
    # Generate the full registry DDL but rewrite the table name to _new.
    create_sql = generate_create_sql(table)
    # The DDL has both CREATE TABLE and CREATE INDEX statements separated by
    # semicolons + newlines. Pull only the CREATE TABLE statement and rewrite
    # the table name to shadow_trades_new. Indexes are recreated separately
    # AFTER the rename so the registry index names point at the renamed table.
    create_table_stmt = ""
    for statement in create_sql.split(";\n"):
        statement = statement.strip()
        if statement.startswith("CREATE TABLE"):
            create_table_stmt = statement
            break
    if not create_table_stmt:
        raise RuntimeError("Could not extract CREATE TABLE from registry DDL")

    create_new_stmt = create_table_stmt.replace(
        "CREATE TABLE IF NOT EXISTS shadow_trades",
        "CREATE TABLE shadow_trades_new",
        1,
    )

    # Defensive: drop any leftover _new from an interrupted previous run.
    # Done OUTSIDE the transaction so it doesn't poison the rebuild txn.
    conn.execute("DROP TABLE IF EXISTS shadow_trades_new")
    conn.commit()

    # 2-9: wrapped in a single atomic transaction.
    try:
        conn.execute("BEGIN")

        # 3. Create the target schema.
        conn.execute(create_new_stmt)

        # 4. Migrate data. Use the registry column list so future column
        #    additions (instrumentation_version, etc.) are handled
        #    automatically; missing columns in the source table cause
        #    SQLite to error here, which is the desired safety property.
        cols = _registered_columns()
        col_csv = ", ".join(cols)
        conn.execute(
            f"INSERT INTO shadow_trades_new ({col_csv}) "
            f"SELECT {col_csv} FROM shadow_trades"
        )

        # 5. Drop the old table.
        conn.execute("DROP TABLE shadow_trades")

        # 6. Rename the new table into place.
        conn.execute("ALTER TABLE shadow_trades_new RENAME TO shadow_trades")

        # 7. Recreate indexes from the registry (CREATE TABLE alone doesn't
        #    bring them along).
        for idx_name, idx_cols, unique in _registered_indexes():
            unique_kw = "UNIQUE " if unique else ""
            idx_csv = ", ".join(idx_cols)
            conn.execute(
                f"CREATE {unique_kw}INDEX IF NOT EXISTS {idx_name} "
                f"ON shadow_trades({idx_csv})"
            )

        # 8. FK integrity check — should report zero violations after rebuild.
        violations = conn.execute("PRAGMA foreign_key_check").fetchall()
        if violations:
            raise RuntimeError(
                f"Foreign-key violations after rebuild: {[dict(v) for v in violations]}"
            )

        # 9. Commit the transaction.
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        # 10. Re-enable FK checks regardless of success/failure so the
        #     connection is left in a sane state for any caller.
        conn.execute("PRAGMA foreign_keys = ON")


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

def run_migration(conn, apply: bool) -> dict:
    """Run the migration end-to-end. Returns a result dict.

    If apply=False, only reports counts; no writes.
    """
    null_ids = find_null_quarantined_trade_ids(conn)
    n_null = len(null_ids)
    already_not_null = is_quarantined_not_null(conn)

    result = {
        "null_rows": n_null,
        "already_not_null": already_not_null,
        "backfilled": 0,
        "rebuilt": False,
    }

    logger.info(
        "[migrate_quarantined_not_null] State: null_rows=%d already_not_null=%s",
        n_null, already_not_null,
    )

    if n_null == 0 and already_not_null:
        logger.info(
            "[migrate_quarantined_not_null] Nothing to do — column is already "
            "NOT NULL and no NULL rows exist (idempotent re-run)."
        )
        return result

    if not apply:
        logger.info(
            "[migrate_quarantined_not_null] DRY-RUN — would backfill %d rows "
            "and rebuild=%s. Re-run with --apply to write.",
            n_null, not already_not_null,
        )
        return result

    # Phase 1: backfill (always safe; sets 0 not NULL).
    if n_null > 0:
        n_backfilled = backfill_null_quarantined(conn, null_ids)
        logger.info(
            "[migrate_quarantined_not_null] APPLIED phase 1 — "
            "backfilled %d NULL → 0", n_backfilled,
        )
        result["backfilled"] = n_backfilled

    # Phase 2: short-circuit if NOT NULL is already enforced.
    if already_not_null:
        logger.info(
            "[migrate_quarantined_not_null] Skipping phase 2 — column is "
            "already NOT NULL (no rebuild needed)."
        )
        return result

    # Phase 3: table rebuild to enforce NOT NULL.
    logger.info(
        "[migrate_quarantined_not_null] APPLIED phase 2 — rebuilding "
        "shadow_trades to enforce NOT NULL on quarantined ..."
    )
    rebuild_shadow_trades_with_not_null(conn)
    result["rebuilt"] = True

    # Post-condition: NOT NULL must now be set, and zero NULL rows.
    if not is_quarantined_not_null(conn):
        raise RuntimeError(
            "Post-rebuild assertion failed: quarantined still nullable"
        )
    residual = find_null_quarantined_trade_ids(conn)
    if residual:
        raise RuntimeError(
            f"Post-rebuild assertion failed: {len(residual)} NULL rows remain"
        )

    logger.info(
        "[migrate_quarantined_not_null] Verified: column is NOT NULL and "
        "zero NULL rows remain."
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Enforce NOT NULL DEFAULT 0 on shadow_trades.quarantined "
            "(PR-690 O7). Backfills NULL → 0 then rebuilds the table "
            "with the NOT NULL constraint."
        )
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
        run_migration(conn, apply=args.apply)
        return 0
    except Exception as e:
        logger.exception("[migrate_quarantined_not_null] FAILED: %s", e)
        return 1
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
