"""One-shot data migration: copy schema-registry tables from SQLite to Postgres.

Usage:
    python scripts/sqlite_to_pg_migrate.py [--tables a,b,c] [--dry-run] [--vacuum-after]

Required env vars:
    DATABASE_URL  — destination Postgres URL (must start with "postgres")

Optional env vars:
    ARCIS_DB_PATH — source SQLite path (default C:/arcis/data/ai_research_desk.sqlite3)

Size gate: file must stay <=400 lines (test_repo_structure.py enforces this).
"""

import argparse
import os
import re
import sqlite3
import sys
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    import psycopg2
    from psycopg2 import sql
    from psycopg2.extras import execute_values
except ImportError:
    print("ERROR: psycopg2 not installed. Run: pip install psycopg2-binary")
    sys.exit(1)

from src.config import DB_PATH
from src.schema.registry import TABLES

_CHUNK_SIZE = 1000
_DEFAULT_SQLITE_PATH = "C:/arcis/data/ai_research_desk.sqlite3"


def _validate_database_url(database_url: str) -> None:
    if not database_url:
        print("ERROR: DATABASE_URL is not set or empty. Aborting.", file=sys.stderr)
        sys.exit(1)
    if not database_url.startswith("postgres"):
        print(
            f"ERROR: DATABASE_URL must start with 'postgres', got: {database_url!r}. Aborting.",
            file=sys.stderr,
        )
        sys.exit(1)


def _resolve_primary_key_columns(table) -> list[str]:
    """Return PK column names as a list — single-col PKs return [col]; composite PKs return all cols."""
    pk = table.primary_key
    return [pk] if isinstance(pk, str) else list(pk)


def _redact_password(database_url: str) -> str:
    """Mask the password in a DSN-style URL for safe logging.

    `postgresql://user:secret@host:port/db` → `postgresql://user:<redacted>@host:port/db`.
    Used to prevent password fragments from landing in committed log files (the
    untimely committed migration-dry-run.log on 2026-05-10 leaked 19 chars of
    the PG password; this redaction prevents recurrence).
    """
    return re.sub(r"://([^:/?#]+):[^@]+@", r"://\1:<redacted>@", database_url)


def _get_sync_tables(table_filter: Optional[list[str]]):
    sync_tables = [t for t in TABLES.values() if t.sync_to_postgres]
    if table_filter:
        filter_set = set(table_filter)
        sync_tables = [t for t in sync_tables if t.name in filter_set]
    return sync_tables


def _print_dry_run_plan(sqlite_path: str, sync_tables: list) -> None:
    print(f"DRY RUN — Migration plan (source: {sqlite_path})")
    print(f"{'Table':<45} {'SQLite rows':>12}")
    print("-" * 58)
    sqlite_conn = sqlite3.connect(sqlite_path)
    total = 0
    for table in sync_tables:
        try:
            cur = sqlite_conn.cursor()
            cur.execute(f"SELECT COUNT(*) FROM {table.name}")
            row = cur.fetchone()
            count = row[0] if row else 0
        except sqlite3.OperationalError:
            count = 0
        print(f"  {table.name:<43} {count:>12}")
        total += count
    sqlite_conn.close()
    print("-" * 58)
    print(f"  {'TOTAL':<43} {total:>12}")
    print(f"\nDRY RUN complete. {len(sync_tables)} tables would be migrated.")


def _build_insert_sql_template(table_name: str, col_names: list[str], pk_cols: list[str]) -> str:
    """Build an `INSERT … ON CONFLICT (…) DO NOTHING` template for execute_values.

    `pk_cols` is a list of column names — single-element for single-column PKs,
    multi-element for composite PKs. Composite PKs must include ALL their columns
    in the ON CONFLICT target, because Postgres requires the conflict target to
    match an exact UNIQUE/PRIMARY KEY constraint — a single-column target against
    a composite PK raises:
        ERROR: there is no unique or exclusion constraint matching the ON
        CONFLICT specification

    Affected sync tables (verified against registry 2026-05-10):
        minute_bars                        ['ticker', 'timestamp']         435K rows
        sp100_historical_constituents      ['ticker', 'added_date']        0 rows today
        correlation_matrices               5-col composite                 0 rows today
        factor_loadings                    4-col composite                 0 rows today
    """
    cols_sql = ", ".join(col_names)
    pk_cols_sql = ", ".join(pk_cols)
    return (
        f"INSERT INTO {table_name} ({cols_sql}) VALUES %s "
        f"ON CONFLICT ({pk_cols_sql}) DO NOTHING"
    )


def _advance_sequence_after_bulk(pg_conn, table_name: str, pk_col: str) -> None:
    """Advance the PG sequence for an integer PK to MAX(id) + 1 post-bulk-load.

    Postgres SERIAL/IDENTITY columns have an associated sequence (e.g.,
    activity_log_id_seq). Bulk INSERTs that specify explicit id values do NOT
    advance the sequence. Subsequent INSERTs that omit id rely on the sequence
    and will collide with existing rows.
    """
    with pg_conn.cursor() as cur:
        cur.execute("SELECT pg_get_serial_sequence(%s, %s)", (table_name, pk_col))
        seq_row = cur.fetchone()
        if not seq_row or not seq_row[0]:
            return  # not a serial column — UUID, composite, or no sequence
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
    pg_conn.commit()


def _migrate_table(sqlite_conn, pg_conn, table, vacuum_after: bool) -> dict:
    table_name = table.name
    pk_cols = _resolve_primary_key_columns(table)
    col_names = [c.name for c in table.columns]
    # Resolve PK columns to indexes so the NULL filter doesn't have to lookup
    # column names per row. For composite PKs we filter rows where ANY PK
    # column is NULL (matches PG's NOT NULL behavior on PK columns).
    pk_indexes = [col_names.index(c) for c in pk_cols]

    sqlite_cur = sqlite_conn.cursor()
    try:
        sqlite_cur.execute(f"SELECT COUNT(*) FROM {table_name}")
        row = sqlite_cur.fetchone()
        source_count = row[0] if row else 0
    except sqlite3.OperationalError:
        source_count = 0

    insert_sql = _build_insert_sql_template(table_name, col_names, pk_cols)

    sqlite_cur.execute(f"SELECT {', '.join(col_names)} FROM {table_name}")

    pg_cur = pg_conn.cursor()
    total_inserted = 0
    null_pk_skipped = 0

    while True:
        chunk = sqlite_cur.fetchmany(_CHUNK_SIZE)
        if not chunk:
            break
        # ANY PK column NULL → skip (matches PG NOT NULL on PK columns).
        valid_chunk = [r for r in chunk if all(r[i] is not None for i in pk_indexes)]
        null_pk_skipped += len(chunk) - len(valid_chunk)
        if not valid_chunk:
            continue
        execute_values(pg_cur, insert_sql, valid_chunk, page_size=_CHUNK_SIZE)
        total_inserted += len(valid_chunk)

    conflict_skipped = source_count - null_pk_skipped - total_inserted

    if vacuum_after:
        pg_cur.execute(f"VACUUM ANALYZE {table_name}")

    pg_cur.close()

    print(
        f"  {table_name:<45} src={source_count:>7}  inserted={total_inserted:>7}"
        f"  conflict_skip={conflict_skipped:>6}  null_pk_skip={null_pk_skipped:>4}"
    )
    return {
        "source": source_count,
        "inserted": total_inserted,
        "conflict_skipped": conflict_skipped,
        "null_pk_skipped": null_pk_skipped,
        "error": False,
    }


def run_migration(
    sqlite_path: str,
    database_url: str,
    table_filter: Optional[list[str]] = None,
    dry_run: bool = False,
    vacuum_after: bool = False,
) -> None:
    _validate_database_url(database_url)

    sync_tables = _get_sync_tables(table_filter)

    if dry_run:
        _print_dry_run_plan(sqlite_path, sync_tables)
        return

    sqlite_conn = sqlite3.connect(sqlite_path)
    sqlite_conn.row_factory = None

    total_rows = 0
    total_errors = 0

    pg_conn = psycopg2.connect(database_url)
    try:
        for table in sync_tables:
            try:
                result = _migrate_table(sqlite_conn, pg_conn, table, vacuum_after)
                pg_conn.commit()
                pk = table.primary_key
                if isinstance(pk, str):
                    _advance_sequence_after_bulk(pg_conn, table.name, pk)
                total_rows += result["inserted"]
                if result["error"]:
                    total_errors += 1
            except Exception as exc:
                print(f"  ERROR migrating {table.name}: {exc}", file=sys.stderr)
                try:
                    pg_conn.rollback()
                except Exception:
                    pass
                total_errors += 1
    finally:
        pg_conn.close()

    sqlite_conn.close()
    print(
        f"\nMIGRATION COMPLETE: {len(sync_tables)} tables, "
        f"{total_rows} rows total, {total_errors} errors"
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="One-shot SQLite -> Postgres data migration for schema-registry tables."
    )
    parser.add_argument(
        "--tables",
        type=str,
        default=None,
        help="Comma-separated list of tables to migrate (default: all sync tables).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print migration plan without writing to Postgres.",
    )
    parser.add_argument(
        "--vacuum-after",
        action="store_true",
        help="Issue VACUUM ANALYZE after each table insert.",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    database_url = os.environ.get("DATABASE_URL", "")
    sqlite_path = os.environ.get("ARCIS_DB_PATH", "") or DB_PATH or _DEFAULT_SQLITE_PATH
    table_filter = [t.strip() for t in args.tables.split(",")] if args.tables else None

    print(f"Source SQLite: {sqlite_path}")
    print(f"Destination PG: {_redact_password(database_url)}")

    run_migration(
        sqlite_path=str(sqlite_path),
        database_url=database_url,
        table_filter=table_filter,
        dry_run=args.dry_run,
        vacuum_after=args.vacuum_after,
    )


if __name__ == "__main__":
    main()
