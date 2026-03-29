"""SQLite schema reporter for Halcyon Lab.

Emits every table, column, and index from the configured SQLite database.
Used by docs/architecture.md and sprint verification gates.
"""

from __future__ import annotations

import argparse
import sqlite3
from datetime import datetime, UTC
from pathlib import Path


def format_default(value: object) -> str:
    if value is None:
        return ""
    return f" DEFAULT {value}"


def collect_schema(db_path: Path) -> tuple[list[dict], dict[str, list[dict]]]:
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        tables = conn.execute(
            """
            SELECT name, type, sql
            FROM sqlite_master
            WHERE type IN ('table', 'view')
              AND name NOT LIKE 'sqlite_%'
            ORDER BY type, name
            """
        ).fetchall()

        indexes_by_table: dict[str, list[dict]] = {}
        for table in tables:
            if table["type"] != "table":
                continue
            rows = conn.execute(f"PRAGMA index_list('{table['name']}')").fetchall()
            indexes: list[dict] = []
            for row in rows:
                cols = conn.execute(f"PRAGMA index_info('{row['name']}')").fetchall()
                indexes.append(
                    {
                        "name": row["name"],
                        "unique": bool(row["unique"]),
                        "origin": row["origin"],
                        "columns": [col["name"] for col in cols],
                    }
                )
            indexes_by_table[table["name"]] = indexes

    return [dict(row) for row in tables], indexes_by_table


def render_schema(db_path: Path) -> str:
    tables, indexes_by_table = collect_schema(db_path)
    generated_at = datetime.now(UTC).isoformat()
    lines = [
        "# Schema Report",
        "",
        f"- Database: `{db_path}`",
        f"- Generated: `{generated_at}`",
        f"- Objects: `{len(tables)}`",
        "",
    ]

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        for table in tables:
            name = table["name"]
            obj_type = table["type"]
            lines.append(f"## {obj_type.title()}: `{name}`")
            lines.append("")

            if obj_type == "table":
                columns = conn.execute(f"PRAGMA table_info('{name}')").fetchall()
                lines.append("| Column | Type | Not Null | Default | PK |")
                lines.append("|---|---|---:|---|---:|")
                for col in columns:
                    lines.append(
                        f"| `{col['name']}` | `{col['type'] or 'TEXT'}` | "
                        f"{int(bool(col['notnull']))} | `{col['dflt_value'] or ''}` | {col['pk']} |"
                    )
                lines.append("")

                indexes = indexes_by_table.get(name, [])
                if indexes:
                    lines.append("Indexes:")
                    for index in indexes:
                        uniqueness = "UNIQUE" if index["unique"] else "NON-UNIQUE"
                        columns_text = ", ".join(f"`{col}`" for col in index["columns"]) or "(expression)"
                        lines.append(
                            f"- `{index['name']}` ({uniqueness}, {index['origin']}): {columns_text}"
                        )
                else:
                    lines.append("Indexes:")
                    lines.append("- None")
                lines.append("")
            else:
                lines.append("```sql")
                lines.append(table["sql"] or "")
                lines.append("```")
                lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Render a markdown SQLite schema report.")
    parser.add_argument(
        "--db",
        default="ai_research_desk.sqlite3",
        help="Path to the SQLite database (default: ai_research_desk.sqlite3)",
    )
    parser.add_argument(
        "--output",
        help="Optional output path. If omitted, prints to stdout.",
    )
    args = parser.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        raise SystemExit(f"Database not found: {db_path}")

    report = render_schema(db_path)
    if args.output:
        Path(args.output).write_text(report, encoding="utf-8")
        print(f"Wrote schema report to {args.output}")
    else:
        print(report, end="")


if __name__ == "__main__":
    main()
