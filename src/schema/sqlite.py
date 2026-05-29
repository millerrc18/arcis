"""SQLite schema operations driven by the registry.

Called by: src.schema.validator
Calls: src.schema.registry
Owns tables: none (generates DDL for SQLite)
Config keys: none
Tests: tests/test_schema.py
"""

import logging
import sqlite3

from src.schema.registry import TABLES, ColumnDef, TableDef

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


def _sqlite_only_connect(db_path: str) -> sqlite3.Connection:
    """Open a raw sqlite3 connection — bypasses the engine-aware shim.

    This file is named `sqlite.py` for a reason: every operation here uses
    SQLite-specific syntax (`PRAGMA index_list`, `PRAGMA index_info`, etc.).
    `src.utils.db.connect_db` was rerouted in the 2026-05-10 Modified-A
    cutover to return a Postgres wrapper when DATABASE_URL is set, which
    breaks PRAGMA calls (Postgres rejects with `syntax error at or near
    "PRAGMA"`). Schema migration of the local SQLite mirror always needs
    a real sqlite3.Connection regardless of DATABASE_URL.

    Applies the same `busy_timeout=30000` + `row_factory=sqlite3.Row`
    defaults that the shim used to apply on the SQLite path, so call
    sites don't observe a behavior diff vs the pre-cutover code.
    """
    conn = sqlite3.connect(db_path, timeout=30.0)
    conn.execute("PRAGMA busy_timeout=30000")
    conn.row_factory = sqlite3.Row
    return conn


def _sqlite_index_signature(conn: sqlite3.Connection, table_name: str, index_name: str) -> tuple[bool, list[str]] | None:
    """Return (unique, columns) for a SQLite index, or None if missing."""
    rows = conn.execute(f"PRAGMA index_list({table_name})").fetchall()
    for row in rows:
        if row[1] != index_name:
            continue
        unique = bool(row[2])
        cols = [info[2] for info in conn.execute(f"PRAGMA index_info({index_name})").fetchall()]
        return unique, cols
    return None


def _reconcile_indexes(conn: sqlite3.Connection, table: TableDef) -> None:
    """Drop/recreate same-name indexes whose definition drifted from the registry."""
    for idx in table.indexes:
        signature = _sqlite_index_signature(conn, table.name, idx.name)
        if signature is None:
            continue
        existing_unique, existing_cols = signature
        if existing_unique == idx.unique and existing_cols == idx.columns:
            continue
        logger.info(
            "[SCHEMA] Replacing drifted SQLite index %s on %s: unique=%s cols=%s -> unique=%s cols=%s",
            idx.name,
            table.name,
            existing_unique,
            existing_cols,
            idx.unique,
            idx.columns,
        )
        conn.execute(f"DROP INDEX IF EXISTS {idx.name}")
        unique = "UNIQUE " if idx.unique else ""
        idx_cols = ", ".join(idx.columns)
        conn.execute(
            f"CREATE {unique}INDEX IF NOT EXISTS {idx.name} "
            f"ON {table.name}({idx_cols})"
        )


def _render_column(c: ColumnDef, inline_pk_col: str | None) -> str:
    """Render one column's DDL fragment. AUTOINCREMENT is only emitted
    when the column is also the inline INTEGER PRIMARY KEY (#580)."""
    parts = [c.name, c.type]
    if not c.nullable:
        parts.append("NOT NULL")
    if c.name == inline_pk_col:
        parts.append("PRIMARY KEY")
        if getattr(c, "autoincrement", False):
            parts.append("AUTOINCREMENT")
    if c.default is not None:
        parts.append(f"DEFAULT {_format_default(c.default)}")
    # #110 (T0) — inline CHECK constraint (e.g. enum enforcement).
    if getattr(c, "check", None):
        parts.append(f"CHECK ({c.check})")
    return " ".join(parts)


def generate_create_sql(table: TableDef) -> str:
    """Generate CREATE TABLE IF NOT EXISTS SQL for one table.

    IMPORTANT: When the primary key is a single INTEGER column named 'id',
    it MUST be declared inline as 'id INTEGER NOT NULL PRIMARY KEY' —
    NOT as a separate 'PRIMARY KEY (id)' constraint. In SQLite, only the
    inline form makes the column a ROWID alias with auto-increment.
    The separate constraint form creates a regular column where INSERTs
    without an explicit id get NULL — which breaks Postgres sync.
    """
    pk = table.primary_key
    if isinstance(pk, str):
        pk = [pk]

    # Detect if we should use inline PRIMARY KEY (single INTEGER id column)
    inline_pk_col = None
    if len(pk) == 1:
        pk_name = pk[0]
        for c in table.columns:
            if c.name == pk_name and c.type.upper() == "INTEGER":
                inline_pk_col = pk_name
                break

    cols = [_render_column(c, inline_pk_col) for c in table.columns]

    # Only add separate PRIMARY KEY constraint for composite or non-inline keys
    if inline_pk_col is None:
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
    """Create all tables defined in the registry. Idempotent.

    Creates tables first, then indexes separately — existing tables may
    be missing columns that indexes reference. ensure_columns() fills
    the gaps, so indexes are retried after column migration.
    """
    deferred_indexes: list[tuple[str, str]] = []
    with _sqlite_only_connect(db_path) as conn:
        for table in TABLES.values():
            sql = generate_create_sql(table)
            # Split CREATE TABLE from CREATE INDEX to handle schema drift
            for statement in sql.split(";\n"):
                statement = statement.strip()
                if not statement:
                    continue
                try:
                    conn.execute(statement)
                except sqlite3.OperationalError as e:
                    if "no such column" in str(e) and "INDEX" in statement.upper():
                        deferred_indexes.append((table.name, statement))
                    else:
                        logger.warning("[SCHEMA] %s: %s", table.name, e)
            _reconcile_indexes(conn, table)
        conn.commit()

    # Retry deferred indexes after ensure_columns has a chance to run
    if deferred_indexes:
        logger.debug(
            "[SCHEMA] %d indexes deferred (missing columns)",
            len(deferred_indexes),
        )

    logger.info("[SCHEMA] Created/verified %d tables in %s", len(TABLES), db_path)


def ensure_columns(db_path: str) -> list[str]:
    """Add any columns in registry that are missing from SQLite.

    Returns list of 'table.column' strings for columns added.
    """
    added = []
    with _sqlite_only_connect(db_path) as conn:
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
                if col.name in existing:
                    continue
                migration_default = _migration_default(col)
                default_clause = (
                    f" DEFAULT {_format_default(migration_default)}"
                    if migration_default is not None else ""
                )
                notnull_clause = " NOT NULL" if not col.nullable else ""
                check_clause = f" CHECK ({col.check})" if getattr(col, "check", None) else ""  # #110 (T0)
                try:
                    conn.execute(
                        f"ALTER TABLE {table.name} ADD COLUMN "
                        f"{col.name} {col.type}{notnull_clause}{default_clause}{check_clause}"
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
    _retry_deferred_indexes(db_path)
    return added


def _migration_default(col):
    """DEFAULT to use when ALTER-ADDing a column onto a populated SQLite table.

    SQLite refuses `ADD COLUMN ... NOT NULL` without a DEFAULT ("Cannot add a
    NOT NULL column with default value NULL"). For a NOT NULL column lacking a
    registry default, synthesize a type-appropriate value so legacy rows get one
    and the NOT NULL constraint is preserved (matches the fresh-create schema).
    Returns the registry default unchanged when the column is nullable or already
    has a default.

    CAVEAT: a NOT NULL column that ALSO has a CHECK constraint the synthesized
    default would violate (e.g. backtest_results.provenance_kind, a 3-state enum)
    still can't be ALTER-added onto a populated table — the ALTER fails and
    ensure_columns logs a warning + skips it. This is non-regressive (the prior
    code failed identically) and never persists a constraint-violating value.
    """
    if col.default is not None or col.nullable:
        return col.default
    _t = (col.type or "").upper()
    return 0 if any(k in _t for k in ("INT", "REAL", "FLOAT", "NUM", "DOUBLE", "BOOL")) else ""


def _retry_deferred_indexes(db_path: str) -> None:
    """Re-create indexes deferred during create_all_tables — they failed when
    their columns were still missing, which ensure_columns has now added."""
    for table in TABLES.values():
        for idx in table.indexes:
            unique = "UNIQUE " if idx.unique else ""
            idx_cols = ", ".join(idx.columns)
            try:
                conn_retry = sqlite3.connect(db_path)
                conn_retry.execute(
                    f"CREATE {unique}INDEX IF NOT EXISTS {idx.name} "
                    f"ON {table.name}({idx_cols})"
                )
                conn_retry.commit()
                conn_retry.close()
            except sqlite3.OperationalError:
                pass  # Column still missing or index already exists
