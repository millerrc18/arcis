"""Generate canonical database schema documentation."""
import os
import sqlite3
import sys
from datetime import datetime


def main():
    db_path = "ai_research_desk.sqlite3"
    if not os.path.exists(db_path):
        print(f"Database not found: {db_path}")
        sys.exit(1)

    conn = sqlite3.connect(db_path)
    tables = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' "
        "AND name NOT LIKE 'sqlite_%' ORDER BY name"
    ).fetchall()

    os.makedirs("docs", exist_ok=True)

    with open("docs/schema.md", "w") as f:
        f.write("# Database Schema Report\n\n")
        f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n")
        f.write(f"**{len(tables)} tables** in `{db_path}`\n\n")
        f.write("---\n\n")

        for (table,) in tables:
            cols = conn.execute(f"PRAGMA table_info({table})").fetchall()
            try:
                count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            except Exception:
                count = "?"

            f.write(f"## {table} ({count} rows)\n\n")
            f.write("| # | Column | Type | Nullable | Default | PK |\n")
            f.write("|---|--------|------|----------|---------|----|\n")
            for col in cols:
                cid, name, ctype, notnull, default, pk = col
                nullable = "NO" if notnull else "YES"
                default_str = str(default) if default is not None else ""
                pk_str = "PK" if pk else ""
                f.write(f"| {cid} | {name} | {ctype or 'TEXT'} | {nullable} | {default_str} | {pk_str} |\n")
            f.write("\n")

    conn.close()
    print(f"Schema report written to docs/schema.md ({len(tables)} tables)")


if __name__ == "__main__":
    main()
