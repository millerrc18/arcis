"""Schema validator — compares live databases against the registry."""

import json
import logging
import sqlite3
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
    conn = sqlite3.connect(db_path)

    existing_tables = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }

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
            row[1]: row[2]
            for row in conn.execute(f"PRAGMA table_info({name})").fetchall()
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
    """Auto-fix: create missing tables, add missing columns. Returns actions."""
    if not db_path:
        return []
    from src.schema.sqlite import create_all_tables, ensure_columns

    actions = []
    missing_tables = [i for i in issues if i.issue_type == "missing_table"]
    if missing_tables:
        create_all_tables(db_path)
        actions.append(f"Created {len(missing_tables)} missing tables")
    added = ensure_columns(db_path)
    if added:
        actions.append(f"Added {len(added)} columns: {added}")
    return actions
