"""Render sync reconcile helpers.

Called by: src.sync.render_sync
Calls: src.schema.sync_config, src.schema.registry
Owns tables: none
Config keys: none
Tests: tests/test_render_reconcile.py

Reconcile removes ghost rows — rows in Postgres that no longer exist in
the local SQLite source of truth. The canonical invariant is:

    count_pg(table) <= count_sqlite(table)

Forward-direction lag (SQLite > PG) is expected and normal: the sync
cursor is catching up. Reverse-direction lag (PG > SQLite) is the
ghost-row class that this module detects and removes.
"""

import logging
import sqlite3

logger = logging.getLogger(__name__)


def is_eligible(table_name: str, entry: dict) -> tuple[bool, str]:
    """Return (eligible, reason) based on registry field.

    Eligibility is determined solely by the sync_reconcile field from
    the registry (exposed via generate_sync_tables() entries).
    Runtime SQLite probing and BIDIRECTIONAL_TABLES sets have been removed.
    """
    if entry.get("sync_reconcile", False):
        return True, ""
    return False, "not in sync_reconcile allowlist"


def topo_sort_reconcile_tables(tables: dict) -> list[str]:
    """Return table names in FK-safe order (children first = reversed topo).

    Wraps _topo_sort_tables with a precondition check that the registry
    is populated. If TABLES is empty/uninitialized the helper would
    silently produce FK-unaware output — we raise instead.

    Args:
        tables: Dict of table_name -> entry from generate_sync_tables().

    Returns:
        List of table names in child-first order (reversed insert order).

    Raises:
        RuntimeError: If the global TABLES registry is empty.
        SyncConfigError: If a FK cycle is detected.
    """
    from src.schema.registry import TABLES
    from src.schema.sync_config import _topo_sort_tables

    if not tables:
        raise RuntimeError(
            "Cannot sort an empty tables dict — registry may not be populated. "
            "Ensure TABLES is initialized before calling topo_sort_reconcile_tables()."
        )

    if len(TABLES) == 0:
        raise RuntimeError(
            "Schema registry TABLES is empty — cannot produce FK-aware sort order. "
            "Ensure src.schema.registry is fully initialized before reconciling."
        )

    ordered = _topo_sort_tables(tables)
    return list(reversed(ordered))


def assert_no_ghost_rows(pg_conn, table: str, db_path: str) -> tuple[bool, str]:
    """Check the PG <= SQLite row-count invariant for a single table.

    Ghost rows are rows that exist in Postgres but have already been
    deleted from the local SQLite source of truth. They arise when a
    delete in SQLite is not replicated to Postgres (the sync is
    push-only for most tables).

    Args:
        pg_conn: Open psycopg2 connection to Render Postgres.
        table: Table name to check.
        db_path: Path to the local SQLite database.

    Returns:
        (True, message) when count_pg <= count_sqlite (clean).
        (False, message) when count_pg > count_sqlite (ghost rows detected).
    """
    try:
        with pg_conn.cursor() as cur:
            cur.execute(f"SELECT COUNT(*) FROM {table}")
            pg_count = cur.fetchone()[0]
    except Exception as exc:
        msg = f"assert_no_ghost_rows: PG query failed for {table}: {exc}"
        logger.warning(msg)
        return False, msg

    try:
        conn = sqlite3.connect(db_path, timeout=10)
        conn.execute("PRAGMA busy_timeout = 10000")
        row = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
        conn.close()
        sqlite_count = row[0]
    except Exception as exc:
        msg = f"assert_no_ghost_rows: SQLite query failed for {table}: {exc}"
        logger.warning(msg)
        return False, msg

    if pg_count <= sqlite_count:
        return True, (
            f"{table}: PG={pg_count} <= SQLite={sqlite_count} (clean)"
        )

    ghost_count = pg_count - sqlite_count
    msg = (
        f"{table}: ghost rows detected — PG={pg_count} > SQLite={sqlite_count} "
        f"({ghost_count} ghost rows)"
    )
    return False, msg


def reconcile_all(pg_conn, db_path: str) -> dict:
    """Run reconcile across all eligible tables (children first).

    Iterates reconcile-eligible tables in FK-safe child-first order,
    deleting rows in Postgres that no longer exist in SQLite.

    Args:
        pg_conn: Open psycopg2 connection to Render Postgres.
        db_path: Path to the local SQLite database.

    Returns:
        Dict with keys: tables_checked, ghost_rows_deleted, errors.
    """
    from src.schema.sync_config import generate_sync_tables

    sync_tables = generate_sync_tables()
    eligible = {
        name: entry
        for name, entry in sync_tables.items()
        if is_eligible(name, entry)[0]
    }

    if not eligible:
        logger.debug("reconcile_all: no eligible tables")
        return {"tables_checked": 0, "ghost_rows_deleted": 0, "errors": []}

    try:
        ordered = topo_sort_reconcile_tables(eligible)
    except Exception as exc:
        logger.error("reconcile_all: topo sort failed: %s", exc)
        return {"tables_checked": 0, "ghost_rows_deleted": 0, "errors": [str(exc)]}

    tables_checked = 0
    ghost_rows_deleted = 0
    errors = []

    for table_name in ordered:
        entry = eligible[table_name]
        pk = entry.get("pk", "id")
        try:
            deleted = _reconcile_table(pg_conn, table_name, pk, db_path)
            tables_checked += 1
            ghost_rows_deleted += deleted
            if deleted > 0:
                logger.info(
                    "reconcile_all: deleted %d ghost rows from %s",
                    deleted,
                    table_name,
                )
        except Exception as exc:
            logger.error(
                "reconcile_all: failed for %s: %s", table_name, exc
            )
            errors.append(f"{table_name}: {exc}")

    return {
        "tables_checked": tables_checked,
        "ghost_rows_deleted": ghost_rows_deleted,
        "errors": errors,
    }


def _reconcile_table(pg_conn, table: str, pk: str, db_path: str) -> int:
    """Delete ghost rows from Postgres for one table.

    A ghost row is a PK that exists in PG but not in SQLite.

    Returns:
        Number of rows deleted from Postgres.
    """
    try:
        conn = sqlite3.connect(db_path, timeout=10)
        conn.execute("PRAGMA busy_timeout = 10000")
        rows = conn.execute(f"SELECT {pk} FROM {table}").fetchall()
        conn.close()
        sqlite_pks = {r[0] for r in rows}
    except Exception as exc:
        raise RuntimeError(f"SQLite read failed for {table}.{pk}: {exc}") from exc

    try:
        with pg_conn.cursor() as cur:
            cur.execute(f"SELECT {pk} FROM {table}")
            pg_pks = {r[0] for r in cur.fetchall()}
    except Exception as exc:
        raise RuntimeError(f"PG read failed for {table}.{pk}: {exc}") from exc

    ghost_pks = pg_pks - sqlite_pks
    if not ghost_pks:
        return 0

    try:
        with pg_conn.cursor() as cur:
            for ghost_pk in ghost_pks:
                cur.execute(f"DELETE FROM {table} WHERE {pk} = %s", (ghost_pk,))
        pg_conn.commit()
    except Exception as exc:
        try:
            pg_conn.rollback()
        except Exception:
            pass
        raise RuntimeError(f"PG delete failed for {table}: {exc}") from exc

    return len(ghost_pks)
