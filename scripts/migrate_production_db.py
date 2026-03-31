"""Safe production DB migration — adds missing columns and tables.

Usage:
    python scripts/migrate_production_db.py                    # default DB
    python scripts/migrate_production_db.py path/to/other.db   # custom path

Idempotent: safe to run multiple times. Never drops or modifies existing data.
"""

import sqlite3
import sys
from pathlib import Path

DEFAULT_DB = "ai_research_desk.sqlite3"


def get_existing_columns(conn: sqlite3.Connection, table: str) -> list[str]:
    """Return list of column names for a table (empty if table doesn't exist)."""
    try:
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
        return [r[1] for r in rows]
    except Exception:
        return []


def table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone()
    return row[0] > 0


# ── Column migrations (ALTER TABLE) ──────────────────────────────────────

COLUMN_MIGRATIONS = [
    ("shadow_trades", "strategy_type", "TEXT DEFAULT 'pullback'"),
    ("training_examples", "outcome_type", "TEXT"),
    ("training_examples", "regime", "TEXT"),
    ("activity_log", "level", "TEXT DEFAULT 'INFO'"),
]


def migrate_columns(conn: sqlite3.Connection) -> list[str]:
    """Add missing columns. Returns list of actions taken."""
    actions = []
    for table, column, col_type in COLUMN_MIGRATIONS:
        if not table_exists(conn, table):
            actions.append(f"SKIP: table '{table}' does not exist (column {column})")
            continue
        existing = get_existing_columns(conn, table)
        if column in existing:
            actions.append(f"OK: {table}.{column} already exists")
        else:
            sql = f"ALTER TABLE {table} ADD COLUMN {column} {col_type}"
            conn.execute(sql)
            actions.append(f"ADDED: {table}.{column} ({col_type})")
    conn.commit()
    return actions


# ── Table migrations (CREATE TABLE IF NOT EXISTS) ────────────────────────

def migrate_tables(conn: sqlite3.Connection) -> list[str]:
    """Create missing tables from create_missing_tables.py + any extras."""
    from pathlib import Path
    import importlib.util

    actions = []

    # Import and run the canonical table creator
    script_dir = Path(__file__).resolve().parent
    spec = importlib.util.spec_from_file_location(
        "create_missing_tables",
        script_dir / "create_missing_tables.py",
    )
    mod = importlib.util.module_from_spec(spec)

    # Temporarily override DB_PATH so it uses our connection's DB
    import types
    spec.loader.exec_module(mod)

    for sql in mod.TABLES:
        try:
            conn.execute(sql)
            if "CREATE TABLE" in sql:
                name = sql.split("EXISTS")[1].split("(")[0].strip()
                actions.append(f"TABLE: {name} (created or already exists)")
            elif "CREATE INDEX" in sql:
                name = sql.split("EXISTS")[1].split("ON")[0].strip()
                actions.append(f"INDEX: {name} (created or already exists)")
        except Exception as e:
            actions.append(f"ERROR: {e}")

    # Extra tables/indexes not in create_missing_tables.py
    extra_tables = [
        """CREATE TABLE IF NOT EXISTS build_score_history (
            score_id TEXT PRIMARY KEY,
            score_date TEXT,
            build_score REAL,
            gate_velocity REAL,
            system_health REAL,
            data_asset_value REAL,
            model_quality REAL,
            research_velocity REAL,
            reliability REAL,
            decay_applied INTEGER DEFAULT 0,
            components_json TEXT,
            created_at TEXT)""",
    ]
    for sql in extra_tables:
        try:
            conn.execute(sql)
            name = sql.split("EXISTS")[1].split("(")[0].strip()
            actions.append(f"TABLE: {name} (created or already exists)")
        except Exception as e:
            actions.append(f"ERROR: {e}")

    conn.commit()
    return actions


def main():
    db_path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_DB

    if not Path(db_path).exists():
        print(f"ERROR: Database not found at {db_path}")
        sys.exit(1)

    print(f"Migrating: {db_path}")
    print(f"DB size: {Path(db_path).stat().st_size / 1024:.0f} KB")
    print()

    conn = sqlite3.connect(db_path)

    # 1. Create missing tables first (so ALTER TABLE has targets)
    print("=== Creating missing tables ===")
    table_actions = migrate_tables(conn)
    for a in table_actions:
        print(f"  {a}")
    print()

    # 2. Add missing columns
    print("=== Adding missing columns ===")
    col_actions = migrate_columns(conn)
    for a in col_actions:
        print(f"  {a}")
    print()

    # 3. Verify
    print("=== Verification ===")
    errors = []
    for table, column, _ in COLUMN_MIGRATIONS:
        if not table_exists(conn, table):
            errors.append(f"TABLE MISSING: {table}")
        elif column not in get_existing_columns(conn, table):
            errors.append(f"COLUMN MISSING: {table}.{column}")

    if errors:
        print("FAILURES:")
        for e in errors:
            print(f"  ✗ {e}")
        sys.exit(1)
    else:
        print("  [OK] All expected columns verified")

    conn.close()
    print("\nMigration complete.")


if __name__ == "__main__":
    main()
