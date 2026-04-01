"""Rebuild local SQLite database from Render Postgres.

Usage:
    python scripts/recover_from_postgres.py

Reads DATABASE_URL from .env, pulls all synced tables from Postgres,
and writes them into a fresh local SQLite database.
"""

import os
import sqlite3
import sys

def main():
    # Load .env
    from dotenv import load_dotenv
    load_dotenv()

    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        print("ERROR: DATABASE_URL not set in .env")
        sys.exit(1)

    try:
        import psycopg2
        import psycopg2.extras
    except ImportError:
        print("ERROR: psycopg2 not installed. Run: pip install psycopg2-binary")
        sys.exit(1)

    LOCAL_DB = "ai_research_desk.sqlite3"

    # Back up existing (corrupted) file
    if os.path.exists(LOCAL_DB):
        backup = LOCAL_DB + ".pre_recovery"
        if not os.path.exists(backup):
            os.rename(LOCAL_DB, backup)
            print(f"Backed up existing DB to {backup}")
        else:
            os.remove(LOCAL_DB)
            print(f"Removed existing {LOCAL_DB} (backup already exists)")

    # Remove WAL/SHM files
    for ext in ["-wal", "-shm"]:
        f = LOCAL_DB + ext
        if os.path.exists(f):
            os.remove(f)
            print(f"Removed {f}")

    # Connect to Postgres
    print(f"\nConnecting to Postgres...")
    pg = psycopg2.connect(database_url)
    pg_cur = pg.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    # Get list of tables in Postgres
    pg_cur.execute("""
        SELECT table_name FROM information_schema.tables
        WHERE table_schema = 'public'
        ORDER BY table_name
    """)
    pg_tables = [row["table_name"] for row in pg_cur.fetchall()]
    print(f"Found {len(pg_tables)} tables in Postgres\n")

    # Create fresh SQLite and initialize schema
    print("Initializing local SQLite schema...")
    # Import and run initialize_database to create all tables
    try:
        from src.journal.store import initialize_database
        initialize_database(LOCAL_DB)
        print("Schema initialized via initialize_database()")
    except Exception as e:
        print(f"WARNING: initialize_database() failed: {e}")
        print("Will create tables from Postgres schema instead")

    sq = sqlite3.connect(LOCAL_DB)
    sq.execute("PRAGMA journal_mode=WAL")
    sq.execute("PRAGMA busy_timeout=5000")

    total_rows = 0
    tables_recovered = 0
    tables_failed = 0

    for table in pg_tables:
        if table in ("sync_state",):
            continue  # Skip sync metadata

        try:
            # Get column info from Postgres
            pg_cur.execute(f"SELECT * FROM {table} LIMIT 0")
            columns = [desc[0] for desc in pg_cur.description]

            # Skip 'id' column if it's a Postgres SERIAL (auto-increment)
            # SQLite has its own ROWID
            skip_id = False
            if "id" in columns:
                pg_cur.execute(f"""
                    SELECT column_default FROM information_schema.columns
                    WHERE table_name = %s AND column_name = 'id'
                """, (table,))
                default_row = pg_cur.fetchone()
                if default_row and default_row.get("column_default", ""):
                    default_val = str(default_row["column_default"])
                    if "nextval" in default_val:
                        skip_id = True

            # Fetch all rows
            pg_cur.execute(f"SELECT * FROM {table}")
            rows = pg_cur.fetchall()

            if not rows:
                print(f"  {table}: 0 rows (empty)")
                continue

            # Filter columns if skipping serial id
            if skip_id:
                columns = [c for c in columns if c != "id"]

            # Ensure table exists in SQLite
            try:
                sq.execute(f"SELECT * FROM {table} LIMIT 0")
            except sqlite3.OperationalError:
                # Table doesn't exist in SQLite — create it
                col_defs = ", ".join(f'"{c}" TEXT' for c in columns)
                sq.execute(f"CREATE TABLE IF NOT EXISTS {table} ({col_defs})")
                print(f"  Created missing table: {table}")

            # Get SQLite columns
            sq_cur = sq.execute(f"SELECT * FROM {table} LIMIT 0")
            sq_columns = [desc[0] for desc in sq_cur.description]

            # Only insert columns that exist in both
            common_columns = [c for c in columns if c in sq_columns]
            if not common_columns:
                print(f"  {table}: no common columns, skipping")
                tables_failed += 1
                continue

            # Clear existing data
            sq.execute(f"DELETE FROM {table}")

            # Insert rows
            placeholders = ", ".join(["?"] * len(common_columns))
            col_names = ", ".join(f'"{c}"' for c in common_columns)
            insert_sql = f'INSERT OR IGNORE INTO {table} ({col_names}) VALUES ({placeholders})'

            batch = []
            for row in rows:
                values = tuple(row.get(c) for c in common_columns)
                batch.append(values)

            sq.executemany(insert_sql, batch)
            sq.commit()

            count = len(batch)
            total_rows += count
            tables_recovered += 1
            print(f"  {table}: {count:,} rows recovered")

        except Exception as e:
            tables_failed += 1
            print(f"  {table}: FAILED — {e}")

    # Also ensure additional tables from initialize_database exist
    # (ones not in Postgres but needed locally)
    try:
        from src.journal.store import initialize_database
        initialize_database(LOCAL_DB)
    except Exception:
        pass

    sq.close()
    pg.close()

    print(f"\n{'='*50}")
    print(f"RECOVERY COMPLETE")
    print(f"  Tables recovered: {tables_recovered}")
    print(f"  Tables failed:    {tables_failed}")
    print(f"  Total rows:       {total_rows:,}")
    print(f"  Output:           {LOCAL_DB}")
    print(f"  Size:             {os.path.getsize(LOCAL_DB):,} bytes")
    print(f"\nNext steps:")
    print(f"  1. Verify: python -c \"import sqlite3; c=sqlite3.connect('{LOCAL_DB}'); print(c.execute('SELECT COUNT(*) FROM shadow_trades').fetchone())\"")
    print(f"  2. Restart watch loop: python -m src.main watch --email-mode digest --overnight")


if __name__ == "__main__":
    main()
