"""Schema registry — single source of truth for all database tables."""

from src.schema.registry import TABLES, TableDef, ColumnDef, IndexDef, ForeignKeyDef

__all__ = ["TABLES", "TableDef", "ColumnDef", "IndexDef", "ForeignKeyDef"]
