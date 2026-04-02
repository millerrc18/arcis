"""Postgres schema operations driven by the registry."""

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


def generate_create_sql(table: TableDef) -> str:
    """Generate CREATE TABLE IF NOT EXISTS SQL for Postgres."""
    cols = []
    pk = (
        table.primary_key
        if isinstance(table.primary_key, str)
        else table.primary_key[0]
    )

    for c in table.columns:
        pg_type = _TYPE_MAP.get(c.type, c.type)
        # Auto-increment integer PKs use SERIAL
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
    sql = f"CREATE TABLE IF NOT EXISTS {table.name} (\n    {body}\n);\n"

    for idx in table.indexes:
        unique = "UNIQUE " if idx.unique else ""
        idx_cols = ", ".join(idx.columns)
        sql += (
            f"CREATE {unique}INDEX IF NOT EXISTS {idx.name} "
            f"ON {table.name}({idx_cols});\n"
        )

    return sql


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


def create_all_tables(database_url: str) -> None:
    """Create all Postgres tables from registry. Idempotent."""
    import psycopg2

    conn = psycopg2.connect(database_url)
    cur = conn.cursor()
    for table in TABLES.values():
        if table.sync_to_postgres:
            cur.execute(generate_create_sql(table))
    conn.commit()
    cur.close()
    conn.close()
    logger.info("[SCHEMA] Postgres: created/verified tables")


def ensure_columns(database_url: str) -> list[str]:
    """Add missing columns to Postgres tables. Idempotent."""
    import psycopg2

    added = []
    conn = psycopg2.connect(database_url)
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
