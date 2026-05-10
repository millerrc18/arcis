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
import sqlite3
import sys
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    import psycopg2
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


def _resolve_primary_key(table) -> str:
    pk = table.primary_key
    return pk if isinstance(pk, str) else pk[0]


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


def _fetch_sqlite_rows(sqlite_conn, table_name: str, col_names: list[str]) -> list[tuple]:
    cur = sqlite_conn.cursor()
    cols_sql = ", ".join(col_names)
    cur.execute(f"SELECT {cols_sql} FROM {table_name}")
    return cur.fetchall()


def _filter_null_pk_rows(rows: list[tuple], pk_idx: int) -> tuple[list[tuple], int]:
    valid = [r for r in rows if r[pk_idx] is not None]
    skipped = len(rows) - len(valid)
    return valid, skipped


def _build_insert_sql(table_name: str, col_names: list[str], pk_name: str) -> str:
    cols_sql = ", ".join(col_names)
    placeholders = ", ".join("%s" for _ in col_names)
    return (
        f"INSERT INTO {table_name} ({cols_sql}) VALUES ({placeholders}) "
        f"ON CONFLICT ({pk_name}) DO NOTHING"
    )


def _insert_chunks(pg_cur, insert_sql: str, rows: list[tuple]) -> int:
    inserted = 0
    for i in range(0, len(rows), _CHUNK_SIZE):
        chunk = rows[i : i + _CHUNK_SIZE]
        pg_cur.executemany(insert_sql, chunk)
        rc = pg_cur.rowcount
        inserted += rc if rc >= 0 else len(chunk)
    return inserted


def _migrate_table(sqlite_conn, pg_conn, table, vacuum_after: bool) -> dict:
    table_name = table.name
    pk_name = _resolve_primary_key(table)
    col_names = [c.name for c in table.columns]
    pk_idx = col_names.index(pk_name)

    sqlite_cur = sqlite_conn.cursor()
    try:
        sqlite_cur.execute(f"SELECT COUNT(*) FROM {table_name}")
        row = sqlite_cur.fetchone()
        source_count = row[0] if row else 0
    except sqlite3.OperationalError:
        source_count = 0

    all_rows, null_pk_skipped = _filter_null_pk_rows(
        _fetch_sqlite_rows(sqlite_conn, table_name, col_names),
        pk_idx,
    )

    insert_sql = _build_insert_sql(table_name, col_names, pk_name)

    pg_cur = pg_conn.cursor()
    inserted = _insert_chunks(pg_cur, insert_sql, all_rows)
    conflict_skipped = len(all_rows) - inserted

    pg_conn.commit()

    if vacuum_after:
        pg_cur.execute(f"VACUUM ANALYZE {table_name}")
        pg_conn.commit()

    pg_cur.close()

    print(
        f"  {table_name:<45} src={source_count:>7}  inserted={inserted:>7}"
        f"  conflict_skip={conflict_skipped:>6}  null_pk_skip={null_pk_skipped:>4}"
    )
    return {
        "source": source_count,
        "inserted": inserted,
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

    for table in sync_tables:
        pg_conn = psycopg2.connect(database_url)
        try:
            result = _migrate_table(sqlite_conn, pg_conn, table, vacuum_after)
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
    print(f"Destination PG: {database_url[:40]}..." if len(database_url) > 40 else f"Destination PG: {database_url}")

    run_migration(
        sqlite_path=str(sqlite_path),
        database_url=database_url,
        table_filter=table_filter,
        dry_run=args.dry_run,
        vacuum_after=args.vacuum_after,
    )


if __name__ == "__main__":
    main()
