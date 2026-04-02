"""SQLite schema operations driven by the registry."""

import logging
import sqlite3

from src.schema.registry import TABLES, TableDef

logger = logging.getLogger(__name__)


def generate_create_sql(table: TableDef) -> str:
    """Generate CREATE TABLE IF NOT EXISTS SQL for one table."""
    cols = []
    for c in table.columns:
        parts = [c.name, c.type]
        if not c.nullable:
            parts.append("NOT NULL")
        if c.default is not None:
            parts.append(f"DEFAULT '{c.default}'")
        cols.append(" ".join(parts))

    pk = table.primary_key
    if isinstance(pk, str):
        pk = [pk]
    cols.append(f"PRIMARY KEY ({', '.join(pk)})")

    for fk in table.foreign_keys:
        cols.append(
            f"FOREIGN KEY ({fk.column}) REFERENCES "
            f"{fk.references_table}({fk.references_column})"
        )

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


def create_all_tables(db_path: str) -> None:
    """Create all tables defined in the registry. Idempotent."""
    with sqlite3.connect(db_path) as conn:
        for table in TABLES.values():
            conn.executescript(generate_create_sql(table))
        conn.commit()
    logger.info("[SCHEMA] Created/verified %d tables in %s", len(TABLES), db_path)


def ensure_columns(db_path: str) -> list[str]:
    """Add any columns in registry that are missing from SQLite.

    Returns list of 'table.column' strings for columns added.
    """
    added = []
    with sqlite3.connect(db_path) as conn:
        for table in TABLES.values():
            try:
                existing = {
                    row[1]
                    for row in conn.execute(
                        f"PRAGMA table_info({table.name})"
                    ).fetchall()
                }
            except sqlite3.OperationalError as e:
                logger.debug("[SCHEMA] Skipping %s: %s", table.name, e)
                continue
            for col in table.columns:
                if col.name not in existing:
                    default_clause = (
                        f" DEFAULT '{col.default}'" if col.default else ""
                    )
                    try:
                        conn.execute(
                            f"ALTER TABLE {table.name} ADD COLUMN "
                            f"{col.name} {col.type}{default_clause}"
                        )
                        added.append(f"{table.name}.{col.name}")
                    except sqlite3.OperationalError as e:
                        if "duplicate column" in str(e).lower():
                            pass  # Expected race condition
                        else:
                            logger.warning(
                                "[SCHEMA] Failed to add %s.%s: %s",
                                table.name, col.name, e,
                            )
        conn.commit()
    if added:
        logger.info("[SCHEMA] Added %d columns: %s", len(added), added)
    return added
