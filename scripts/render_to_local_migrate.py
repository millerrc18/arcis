"""Copy live data from Render Postgres to local Postgres (post-cutover finalization).

Why this exists:
    The Phase-3-revised cutover (task #88) moved the canonical DB from Render to
    local. The schema-sync side completed but the data-copy side never landed —
    a prior recovery attempt (`sqlite_to_pg_migrate.py`) shipped data BACK to
    Render (DATABASE_URL env carryover). NSSM's ArcisWatchLoop points at local
    PG, which stayed empty, and startup crashes with UndefinedTable.

What this script does:
    1. Validates SOURCE_DATABASE_URL (Render) and DATABASE_URL (local). Both
       must start with "postgres". Source != destination check.
    2. Interactive confirmation prompt (operator types 'YES' to proceed). The
       prompt redacts both URLs and shows source/destination row counts so the
       operator can sanity-check direction before any writes happen.
    3. Runs create_all_tables on destination (schema sync from registry).
    4. For each table in TABLES with sync_to_postgres=True, copies rows from
       source -> destination in chunks of 1000 with execute_values, using
       INSERT ... ON CONFLICT (pk) DO NOTHING for PK-based dedup.
    5. Advances destination sequences for SERIAL/IDENTITY columns post-bulk so
       the next caller's INSERT (without explicit id) doesn't collide.

Usage:
    PowerShell:
        $env:SOURCE_DATABASE_URL = "postgresql://halcyon:***@dpg-...render.com/halcyon_zjdk"
        $env:DATABASE_URL        = "postgresql://halcyon_app:***@localhost:5433/halcyon"
        python scripts/render_to_local_migrate.py

    Skip the interactive prompt with --yes (scripted/CI use):
        python scripts/render_to_local_migrate.py --yes

    Filter to specific tables:
        python scripts/render_to_local_migrate.py --tables shadow_trades,recommendations

Tracker context:
    Residual content-dedup (different PK + same content from pre-cutover
    dual-writes era) is NOT handled by this script. Run the follow-up dedup
    pass after this lands and the watch loop is back online.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    import psycopg2
    from psycopg2 import sql
    from psycopg2.extras import execute_values
except ImportError:
    print("ERROR: psycopg2 not installed. Run: pip install psycopg2-binary", file=sys.stderr)
    sys.exit(1)

from src.schema.postgres import create_all_tables
from src.schema.registry import TABLES

_CHUNK_SIZE = 1000


def _redact_password(url: str) -> str:
    """Mask the password segment of a DSN-style URL for safe logging."""
    return re.sub(r"://([^:/?#]+):[^@]+@", r"://\1:<redacted>@", url)


def _validate_url(url: str, label: str) -> None:
    if not url:
        print(f"ERROR: {label} is empty or unset. Aborting.", file=sys.stderr)
        sys.exit(1)
    if not url.startswith("postgres"):
        print(
            f"ERROR: {label} must start with 'postgres', got: {url!r}. Aborting.",
            file=sys.stderr,
        )
        sys.exit(1)


def _resolve_primary_key_columns(table) -> list[str]:
    pk = table.primary_key
    return [pk] if isinstance(pk, str) else list(pk)


def _get_sync_tables(table_filter: Optional[list[str]]):
    sync_tables = [t for t in TABLES.values() if t.sync_to_postgres]
    if table_filter:
        filter_set = set(table_filter)
        sync_tables = [t for t in sync_tables if t.name in filter_set]
    return sync_tables


def _build_insert_template(table_name: str, col_names: list[str], pk_cols: list[str]) -> str:
    """Build an `INSERT ... ON CONFLICT (...) DO NOTHING` template for execute_values."""
    cols_sql = ", ".join(f'"{c}"' for c in col_names)
    pk_cols_sql = ", ".join(f'"{c}"' for c in pk_cols)
    return (
        f'INSERT INTO "{table_name}" ({cols_sql}) VALUES %s '
        f"ON CONFLICT ({pk_cols_sql}) DO NOTHING"
    )


def _advance_sequence_after_bulk(dst_conn, table_name: str, pk_col: str) -> None:
    """Advance the PG sequence for an integer SERIAL PK to MAX(id)+1 after bulk load.

    Bulk INSERTs that specify explicit id values don't advance the sequence.
    Subsequent INSERTs that omit id rely on the sequence and would collide.
    """
    with dst_conn.cursor() as cur:
        cur.execute("SELECT pg_get_serial_sequence(%s, %s)", (table_name, pk_col))
        seq_row = cur.fetchone()
        if not seq_row or not seq_row[0]:
            return  # UUID / composite / no sequence — nothing to advance
        seq_name = seq_row[0]
        cur.execute(
            sql.SQL(
                "SELECT setval(%s, COALESCE(MAX({pk_col}), 0) + 1, false) FROM {tbl}"
            ).format(
                pk_col=sql.Identifier(pk_col),
                tbl=sql.Identifier(table_name),
            ),
            (seq_name,),
        )
    dst_conn.commit()


def _migrate_table(src_conn, dst_conn, table) -> dict:
    table_name = table.name
    pk_cols = _resolve_primary_key_columns(table)
    col_names = [c.name for c in table.columns]
    pk_indexes = [col_names.index(c) for c in pk_cols]

    src_cur = src_conn.cursor()
    src_cur.execute(f'SELECT COUNT(*) FROM "{table_name}"')
    source_count = src_cur.fetchone()[0]

    insert_sql = _build_insert_template(table_name, col_names, pk_cols)

    cols_sql_select = ", ".join(f'"{c}"' for c in col_names)
    src_cur.execute(f'SELECT {cols_sql_select} FROM "{table_name}"')

    dst_cur = dst_conn.cursor()
    total_inserted = 0
    null_pk_skipped = 0

    while True:
        chunk = src_cur.fetchmany(_CHUNK_SIZE)
        if not chunk:
            break
        valid_chunk = [r for r in chunk if all(r[i] is not None for i in pk_indexes)]
        null_pk_skipped += len(chunk) - len(valid_chunk)
        if not valid_chunk:
            continue
        execute_values(dst_cur, insert_sql, valid_chunk, page_size=_CHUNK_SIZE)
        total_inserted += len(valid_chunk)

    dst_cur.close()
    src_cur.close()

    print(
        f"  {table_name:<45} src={source_count:>8}  inserted={total_inserted:>8}  "
        f"null_pk_skip={null_pk_skipped:>4}"
    )
    return {
        "source": source_count,
        "inserted": total_inserted,
        "null_pk_skipped": null_pk_skipped,
    }


def _summarize_counts(url: str, sync_tables: list, label: str) -> tuple[int, int]:
    """Return (total_rows, tables_present) for the destination — used in confirmation prompt."""
    conn = psycopg2.connect(url, connect_timeout=15)
    cur = conn.cursor()
    total = 0
    present = 0
    for t in sync_tables:
        try:
            cur.execute(f'SELECT COUNT(*) FROM "{t.name}"')
            total += cur.fetchone()[0]
            present += 1
            conn.commit()
        except psycopg2.Error:
            conn.rollback()
    cur.close()
    conn.close()
    print(f"  {label}: {total:,} rows across {present}/{len(sync_tables)} tables present")
    return total, present


def _confirm(source_url: str, dest_url: str, sync_tables: list, *, auto_yes: bool) -> None:
    """Print direction + counts, require operator types 'YES' to proceed (unless --yes)."""
    print()
    print("=" * 72)
    print("RENDER -> LOCAL POSTGRES DATA MIGRATION — pre-flight summary")
    print("=" * 72)
    print(f"  SOURCE:      {_redact_password(source_url)}")
    print(f"  DESTINATION: {_redact_password(dest_url)}")
    print(f"  TABLES:      {len(sync_tables)} sync_to_postgres tables from registry")
    print()
    print("Connecting to both DBs to fetch row counts (read-only)...")
    _summarize_counts(source_url, sync_tables, "SOURCE     ")
    _summarize_counts(dest_url, sync_tables, "DESTINATION")
    print()
    print("Migration writes the source -> destination using INSERT ... ON CONFLICT")
    print("(pk) DO NOTHING per table. Existing destination rows with matching PKs")
    print("are preserved. Sequences advance to MAX(pk)+1 post-bulk.")
    print("=" * 72)

    if auto_yes:
        print("--yes flag set; skipping interactive confirmation.")
        return
    print("Type 'YES' (exact case, no quotes) to proceed, or anything else to abort:")
    response = input("> ").strip()
    if response != "YES":
        print(f"Aborted (response was {response!r}, expected 'YES').")
        sys.exit(2)
    print("Confirmed. Beginning migration.")
    print()


def run_migration(
    source_url: str,
    dest_url: str,
    table_filter: Optional[list[str]],
    auto_yes: bool,
    create_schema: bool,
) -> None:
    _validate_url(source_url, "SOURCE_DATABASE_URL")
    _validate_url(dest_url, "DATABASE_URL")
    if source_url == dest_url:
        print("ERROR: SOURCE_DATABASE_URL == DATABASE_URL. Refusing to migrate.", file=sys.stderr)
        sys.exit(1)

    sync_tables = _get_sync_tables(table_filter)
    _confirm(source_url, dest_url, sync_tables, auto_yes=auto_yes)

    if create_schema:
        print("Step 1/2: ensure destination schema (create_all_tables)...")
        # create_all_tables takes a DSN URL string, not a connection object.
        create_all_tables(dest_url)
        print("Schema sync complete.")
        print()

    print("Step 2/2: copy data Render -> local, table by table...")
    print(f"  {'table':<45} {'src':>8} {'inserted':>15} {'null_pk_skip':>12}")
    print("-" * 84)

    src_conn = psycopg2.connect(source_url)
    dst_conn = psycopg2.connect(dest_url)
    totals = {"source": 0, "inserted": 0, "null_pk_skipped": 0, "errors": 0}
    try:
        for table in sync_tables:
            try:
                result = _migrate_table(src_conn, dst_conn, table)
                dst_conn.commit()
                pk = table.primary_key
                if isinstance(pk, str):
                    _advance_sequence_after_bulk(dst_conn, table.name, pk)
                for k in ("source", "inserted", "null_pk_skipped"):
                    totals[k] += result[k]
            except Exception as exc:
                print(f"  ERROR migrating {table.name}: {exc}", file=sys.stderr)
                try:
                    dst_conn.rollback()
                except Exception:
                    pass
                totals["errors"] += 1
    finally:
        src_conn.close()
        dst_conn.close()

    print("-" * 84)
    print(
        f"MIGRATION COMPLETE: {len(sync_tables)} tables, "
        f"{totals['inserted']:,} rows inserted (source had {totals['source']:,}), "
        f"{totals['errors']} errors, {totals['null_pk_skipped']} null-PK rows skipped"
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="One-shot Render Postgres -> local Postgres data migration."
    )
    parser.add_argument(
        "--tables",
        type=str,
        default=None,
        help="Comma-separated list of tables to migrate (default: all sync_to_postgres tables).",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Skip the interactive confirmation prompt (scripted/CI use).",
    )
    parser.add_argument(
        "--no-schema",
        action="store_true",
        help="Skip the create_all_tables step (use when schema already in sync).",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    source_url = os.environ.get("SOURCE_DATABASE_URL", "")
    dest_url = os.environ.get("DATABASE_URL", "")
    table_filter = [t.strip() for t in args.tables.split(",")] if args.tables else None

    run_migration(
        source_url=source_url,
        dest_url=dest_url,
        table_filter=table_filter,
        auto_yes=args.yes,
        create_schema=not args.no_schema,
    )


if __name__ == "__main__":
    main()
