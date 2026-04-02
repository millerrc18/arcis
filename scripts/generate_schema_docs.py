"""Generate docs/database-schema.md from the schema registry.

Usage: python scripts/generate_schema_docs.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.schema.registry import TABLES


def main():
    lines = ["# Database Schema\n"]
    lines.append(f"> Auto-generated from `src/schema/registry.py` — {len(TABLES)} tables\n")
    lines.append(f"> Run `python scripts/generate_schema_docs.py` to regenerate\n")

    # Group tables by domain using description keywords
    domains = {
        "Trading Core": [],
        "Training Pipeline": [],
        "AI Council": [],
        "Data Collection": [],
        "Research": [],
        "Signals & Evaluation": [],
        "Infrastructure": [],
        "User Data": [],
    }

    for name, table in sorted(TABLES.items()):
        desc = table.description.lower()
        if any(w in desc for w in ["trade", "shadow", "recommendation", "validation", "bracket"]):
            domains["Trading Core"].append((name, table))
        elif any(w in desc for w in ["training", "model", "metric_snapshot", "api cost", "preference", "canary", "quality drift"]):
            domains["Training Pipeline"].append((name, table))
        elif "council" in desc:
            domains["AI Council"].append((name, table))
        elif any(w in desc for w in ["collect", "edgar", "insider", "short interest", "fed", "analyst", "options", "cboe", "trend", "vix", "macro", "earning"]):
            domains["Data Collection"].append((name, table))
        elif "research" in desc:
            domains["Research"].append((name, table))
        elif any(w in desc for w in ["signal", "setup", "traffic", "scan", "schedule", "build score"]):
            domains["Signals & Evaluation"].append((name, table))
        elif any(w in desc for w in ["log", "sync", "command", "config", "pending"]):
            domains["Infrastructure"].append((name, table))
        elif "note" in desc:
            domains["User Data"].append((name, table))
        else:
            domains["Infrastructure"].append((name, table))

    for domain, tables in domains.items():
        if not tables:
            continue
        lines.append(f"\n## {domain}\n")
        for name, table in tables:
            sync_info = ""
            if table.sync_to_postgres:
                sync_info = f" | Sync: {table.sync_mode}"
            lines.append(f"### `{name}`{sync_info}\n")
            lines.append(f"{table.description}\n")
            lines.append("| Column | Type | Nullable | Default | Description |")
            lines.append("|--------|------|----------|---------|-------------|")
            for col in table.columns:
                nullable = "Yes" if col.nullable else "**No**"
                default = f"`{col.default}`" if col.default else ""
                desc = col.description or ""
                lines.append(f"| `{col.name}` | {col.type} | {nullable} | {default} | {desc} |")

            if table.indexes:
                lines.append(f"\n**Indexes:** {', '.join(f'`{idx.name}`' for idx in table.indexes)}")
            if table.foreign_keys:
                fk_strs = [f"`{fk.column}` -> `{fk.references_table}.{fk.references_column}`" for fk in table.foreign_keys]
                lines.append(f"\n**Foreign Keys:** {', '.join(fk_strs)}")
            lines.append("")

    output_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs", "database-schema.md")
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"Generated {output_path} with {len(TABLES)} tables")


if __name__ == "__main__":
    main()
