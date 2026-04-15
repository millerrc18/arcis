"""Postgres schema operations driven by the registry.

Called by: scripts/render_migrate.py
Calls: src.schema.registry
Owns tables: none (generates DDL for Postgres mirrors)
Config keys: none
Tests: tests/test_repo_structure.py
"""

import logging

from src.schema.registry import TABLES, TableDef, ColumnDef

logger = logging.getLogger(__name__)

# SQLite -> Postgres type mapping
_TYPE_MAP = {
    "INTEGER": "INTEGER",
    "REAL": "REAL",
    "TEXT": "TEXT",
    "BLOB": "BYTEA",
}


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
            parts.append(f"DEFAULT '{c.default}'")
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
    default_clause = f" DEFAULT '{col.default}'" if col.default else ""
    return (
        f"DO $$ BEGIN\n"
        f"    ALTER TABLE {table_name} ADD COLUMN "
        f"{col.name} {pg_type}{default_clause};\n"
        f"EXCEPTION WHEN duplicate_column THEN NULL;\n"
        f"END $$;\n"
    )


def create_all_tables(database_url: str, *, connect_timeout: int | None = None) -> None:
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
    """
    import psycopg2

    kwargs = {"connect_timeout": connect_timeout} if connect_timeout else {}
    conn = psycopg2.connect(database_url, **kwargs)
    cur = conn.cursor()
    for table in TABLES.values():
        if table.sync_to_postgres:
            cur.execute(generate_create_table_sql(table))
    conn.commit()
    # Phase 2: add missing columns before creating indexes
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
    conn.commit()
    # Phase 3: indexes (column now guaranteed present)
    for table in TABLES.values():
        if table.sync_to_postgres:
            idx_sql = generate_create_indexes_sql(table)
            if idx_sql:
                cur.execute(idx_sql)
    conn.commit()
    cur.close()
    conn.close()
    logger.info("[SCHEMA] Postgres: created/verified tables + columns + indexes")


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
