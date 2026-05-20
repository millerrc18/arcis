"""Postgres schema operations driven by the registry.

Called by: scripts/render_migrate.py
Calls: src.schema.registry
Owns tables: none (generates DDL for Postgres mirrors)
Config keys: none
Tests: tests/test_repo_structure.py
"""

import logging
from collections.abc import Callable

from src.schema.registry import TABLES, TableDef, ColumnDef, ForeignKeyDef

logger = logging.getLogger(__name__)

_SQL_FUNCTION_DEFAULTS = frozenset({
    "CURRENT_TIMESTAMP",
    "CURRENT_DATE",
    "CURRENT_TIME",
    "LOCALTIMESTAMP",
    "LOCALTIME",
    "NOW()",
    "NOW",
})


def _format_default(value) -> str:
    if not isinstance(value, str):
        return str(value)
    if value.upper() in _SQL_FUNCTION_DEFAULTS:
        return value.upper()
    return f"'{value}'"


# SQLite -> Postgres type mapping
_TYPE_MAP = {
    "INTEGER": "INTEGER",
    # BIGINT (PG int64) for columns whose values can exceed int32's 2.1B
    # ceiling — e.g. aggregated institutional share counts (v0.36.33).
    # SQLite stores both as INTEGER affinity (full int64); only PG needs
    # the distinct type.
    "BIGINT": "BIGINT",
    "REAL": "REAL",
    "TEXT": "TEXT",
    "BLOB": "BYTEA",
}


def _pg_index_signature(cur, table_name: str, index_name: str) -> tuple[bool, list[str]] | None:
    """Return (unique, columns) for a Postgres index, or None if missing."""
    cur.execute(
        """
        SELECT i.indisunique,
               array_agg(a.attname ORDER BY ord.ord)
        FROM pg_class t
        JOIN pg_index i ON t.oid = i.indrelid
        JOIN pg_class ix ON ix.oid = i.indexrelid
        JOIN unnest(i.indkey) WITH ORDINALITY AS ord(attnum, ord) ON TRUE
        JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = ord.attnum
        WHERE t.relname = %s
          AND ix.relname = %s
        GROUP BY i.indisunique
        """,
        (table_name, index_name),
    )
    row = cur.fetchone()
    if row is None:
        return None
    return bool(row[0]), list(row[1] or [])


def _reconcile_pg_index(cur, table: TableDef) -> None:
    """Drop/recreate same-name Postgres indexes whose definition drifted."""
    for idx in table.indexes:
        signature = _pg_index_signature(cur, table.name, idx.name)
        if signature is None:
            continue
        existing_unique, existing_cols = signature
        if existing_unique == idx.unique and existing_cols == idx.columns:
            continue
        logger.info(
            "[SCHEMA] Replacing drifted Postgres index %s on %s: unique=%s cols=%s -> unique=%s cols=%s",
            idx.name,
            table.name,
            existing_unique,
            existing_cols,
            idx.unique,
            idx.columns,
        )
        cur.execute(f"DROP INDEX IF EXISTS {idx.name}")


def generate_create_table_sql(table: TableDef) -> str:
    """Generate CREATE TABLE IF NOT EXISTS SQL for Postgres (no indexes)."""
    cols = []
    pk = (
        table.primary_key
        if isinstance(table.primary_key, str)
        else table.primary_key[0]
    )

    for c in table.columns:
        pg_type = _TYPE_MAP.get(c.type, c.type)
        if c.name == pk and pg_type == "INTEGER":
            pg_type = "SERIAL"
        parts = [c.name, pg_type]
        if not c.nullable:
            parts.append("NOT NULL")
        if c.default is not None:
            parts.append(f"DEFAULT {_format_default(c.default)}")
        cols.append(" ".join(parts))

    pk_names = (
        table.primary_key
        if isinstance(table.primary_key, list)
        else [table.primary_key]
    )
    cols.append(f"PRIMARY KEY ({', '.join(pk_names)})")

    body = ",\n    ".join(cols)
    return f"CREATE TABLE IF NOT EXISTS {table.name} (\n    {body}\n);\n"


def generate_create_indexes_sql(table: TableDef) -> str:
    """Generate CREATE INDEX IF NOT EXISTS SQL for all indexes on a table."""
    sql = ""
    for idx in table.indexes:
        unique = "UNIQUE " if idx.unique else ""
        idx_cols = ", ".join(idx.columns)
        sql += (
            f"CREATE {unique}INDEX IF NOT EXISTS {idx.name} "
            f"ON {table.name}({idx_cols});\n"
        )
    return sql


def generate_create_sql(table: TableDef) -> str:
    """Backwards-compatible: CREATE TABLE + indexes in one string.

    Note: new callers should use generate_create_table_sql + ensure_columns +
    generate_create_indexes_sql in that order, so newly-added columns can
    have indexes created after an ALTER TABLE ADD COLUMN.
    """
    return generate_create_table_sql(table) + generate_create_indexes_sql(table)


def generate_ensure_column_sql(table_name: str, col: ColumnDef) -> str:
    """Generate idempotent ALTER TABLE ADD COLUMN for Postgres (PL/pgSQL)."""
    pg_type = _TYPE_MAP.get(col.type, col.type)
    default_clause = f" DEFAULT {_format_default(col.default)}" if col.default else ""
    return (
        f"DO $$ BEGIN\n"
        f"    ALTER TABLE {table_name} ADD COLUMN "
        f"{col.name} {pg_type}{default_clause};\n"
        f"EXCEPTION WHEN duplicate_column THEN NULL;\n"
        f"END $$;\n"
    )


def generate_fk_constraint_sql(table_name: str, fk: ForeignKeyDef) -> str:
    """Generate ADD CONSTRAINT ... FOREIGN KEY ... NOT VALID for Postgres.

    Per Decision 24: NOT VALID skips the upfront table scan so there is no
    AccessExclusiveLock on the referencing table during migration. The
    operator runs VALIDATE CONSTRAINT off-hours to verify existing rows.
    """
    constraint_name = f"{table_name}_{fk.column}_fkey"
    return (
        f"ALTER TABLE {table_name} "
        f"ADD CONSTRAINT {constraint_name} "
        f"FOREIGN KEY ({fk.column}) "
        f"REFERENCES {fk.references_table}({fk.references_column}) "
        f"NOT VALID;"
    )


def create_all_tables(
    database_url: str,
    *,
    connect_timeout: int | None = None,
    lock_timeout_ms: int | None = None,
    progress: Callable[[str], None] | None = None,
) -> list[str]:
    """Create all Postgres tables from registry. Idempotent.

    Runs DDL in three phases so a newly-added column with an index doesn't
    fail when the table already existed without that column:
      1. CREATE TABLE IF NOT EXISTS (skips existing tables)
      2. ALTER TABLE ADD COLUMN for each missing column (idempotent via DO $$)
      3. CREATE INDEX IF NOT EXISTS for each index (column guaranteed present)

    connect_timeout: TCP connect timeout in seconds. Default None waits
    indefinitely — appropriate for manual migrations where the caller wants
    to sit through a cold Render free-tier wake-up. Startup paths pass a
    small value (e.g. 5) so an unreachable DB fails fast.

    lock_timeout_ms: Optional Postgres lock timeout for DDL statements. When
    set, CREATE INDEX / ALTER TABLE waits fail fast instead of appearing hung
    behind long-lived writer transactions.

    progress: Optional callback for lightweight human-readable progress
    messages during manual migrations.
    """
    import psycopg2

    sync_tables = [table for table in TABLES.values() if table.sync_to_postgres]
    added_columns: list[str] = []
    kwargs = {"connect_timeout": connect_timeout} if connect_timeout else {}
    conn = psycopg2.connect(database_url, **kwargs)
    cur = conn.cursor()
    if lock_timeout_ms:
        cur.execute("SET lock_timeout = %s", (f"{lock_timeout_ms}ms",))

    if progress:
        progress(f"Phase 1/3: verifying {len(sync_tables)} Postgres tables")
    for table in sync_tables:
        cur.execute(generate_create_table_sql(table))
    conn.commit()
    # Phase 2: add missing columns before creating indexes
    if progress:
        progress("Phase 2/3: ensuring missing columns")
    for table in sync_tables:
        cur.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = %s",
            (table.name,),
        )
        existing = {row[0] for row in cur.fetchall()}
        for col in table.columns:
            if col.name not in existing:
                cur.execute(generate_ensure_column_sql(table.name, col))
                added_columns.append(f"{table.name}.{col.name}")
    conn.commit()
    # Phase 3: indexes (column now guaranteed present)
    if progress:
        progress("Phase 3/3: ensuring indexes")
    for table in sync_tables:
        _reconcile_pg_index(cur, table)
        idx_sql = generate_create_indexes_sql(table)
        if idx_sql:
            cur.execute(idx_sql)
    conn.commit()
    cur.close()
    conn.close()
    logger.info("[SCHEMA] Postgres: created/verified tables + columns + indexes")
    if added_columns:
        logger.info("[SCHEMA] Postgres: added %d columns during create_all_tables", len(added_columns))
    return added_columns


def ensure_columns(database_url: str, *, connect_timeout: int | None = None) -> list[str]:
    """Add missing columns to Postgres tables. Idempotent.

    connect_timeout: see create_all_tables() for semantics.
    """
    import psycopg2

    added = []
    kwargs = {"connect_timeout": connect_timeout} if connect_timeout else {}
    conn = psycopg2.connect(database_url, **kwargs)
    cur = conn.cursor()
    for table in TABLES.values():
        if not table.sync_to_postgres:
            continue
        cur.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = %s",
            (table.name,),
        )
        existing = {row[0] for row in cur.fetchall()}
        for col in table.columns:
            if col.name not in existing:
                cur.execute(generate_ensure_column_sql(table.name, col))
                added.append(f"{table.name}.{col.name}")
    conn.commit()
    cur.close()
    conn.close()
    if added:
        logger.info("[SCHEMA] Postgres: added %d columns: %s", len(added), added)
    return added
