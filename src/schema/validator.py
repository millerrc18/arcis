"""Schema validator — validates database schema against registry.

Called by: cli.commands, scheduler.watch
Calls: schema.registry
Owns tables: none
Config keys: none
Tests: tests/test_schema.py
"""

import json
import logging
import sqlite3
from src.utils.db import connect_db, engine_aware_column_info, engine_aware_table_list
from dataclasses import dataclass
from pathlib import Path

from src.schema.registry import TABLES

logger = logging.getLogger(__name__)


@dataclass
class SchemaIssue:
    severity: str  # error, warning
    issue_type: str  # missing_table, missing_column, type_mismatch, codebase_violation
    table: str
    column: str | None = None
    detail: str = ""

    def __str__(self):
        col = f".{self.column}" if self.column else ""
        return f"[{self.severity}] {self.issue_type}: {self.table}{col} — {self.detail}"


def validate_sqlite(db_path: str) -> list[SchemaIssue]:
    """Compare local SQLite schema against registry."""
    issues = []
    conn = connect_db(db_path)

    existing_tables = set(engine_aware_table_list(conn))

    for name, table in TABLES.items():
        if name not in existing_tables:
            issues.append(
                SchemaIssue(
                    "error",
                    "missing_table",
                    name,
                    detail=f"Table {name} not found in database",
                )
            )
            continue

        existing_cols = {
            row["name"]: row["type"]
            for row in engine_aware_column_info(conn, name)
        }
        for col in table.columns:
            if col.name not in existing_cols:
                issues.append(
                    SchemaIssue(
                        "error",
                        "missing_column",
                        name,
                        col.name,
                        detail=f"Column {col.name} ({col.type}) missing",
                    )
                )

    conn.close()
    return issues


def validate_codebase() -> list[SchemaIssue]:
    """Scan Python files for raw CREATE TABLE / ALTER TABLE outside src/schema/."""
    issues = []
    known_path = Path("config/known_schema_violations.json")
    allowed = set()
    if known_path.exists():
        data = json.loads(known_path.read_text())
        for entry in data.get("allowed_create_table", []):
            allowed.add(entry["file"].replace("\\", "/"))
        for entry in data.get("allowed_alter_table", []):
            allowed.add(entry["file"].replace("\\", "/"))

    src_root = Path("src")
    for py_file in src_root.rglob("*.py"):
        rel = str(py_file).replace("\\", "/")
        if "schema" in rel or "__pycache__" in rel:
            continue
        if rel in allowed:
            continue
        text = py_file.read_text(errors="ignore")
        for i, line in enumerate(text.splitlines(), 1):
            stripped = line.lstrip()
            if stripped.startswith("#"):
                continue
            if "CREATE TABLE" in line:
                issues.append(
                    SchemaIssue(
                        "warning",
                        "codebase_violation",
                        "n/a",
                        detail=f"{rel}:{i} — CREATE TABLE outside schema/",
                    )
                )

    return issues


def fix_issues(
    issues: list[SchemaIssue], db_path: str | None = None
) -> list[str]:
    """Auto-fix: create/repair tables and indexes, add missing columns."""
    if not db_path:
        return []
    from src.schema.sqlite import create_all_tables, ensure_columns

    actions = []
    create_all_tables(db_path)
    actions.append("Created/verified tables and repaired drifted indexes")
    added = ensure_columns(db_path)
    if added:
        actions.append(f"Added {len(added)} columns: {added}")
    return actions
