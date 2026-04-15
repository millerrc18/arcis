"""One-shot fix: model name/status + stale collector timestamps.

Run once from repo root:
    python scripts/fix_training_page.py

Fixes:
1. Model name halcyon-v1.0.0 → arcis:v1.0.0 (SQLite + Postgres)
2. Model status ROLLED_BACK → active (SQLite + Postgres)
3-4. Stale collector timestamps — clears Postgres rows so next sync re-inserts fresh data
"""
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from dotenv import load_dotenv

load_dotenv()

DB_PATH = os.environ.get("ARCIS_DB_PATH", "C:/arcis/data/ai_research_desk.sqlite3")
DATABASE_URL = os.environ.get("DATABASE_URL", "")

# ── Fix 1-2: SQLite model name + status ──────────────────────────
print("=== SQLite fixes ===")
with sqlite3.connect(DB_PATH) as conn:
    changed = conn.execute(
        "UPDATE model_versions SET version_name='arcis:v1.0.0', status='active' "
        "WHERE version_name='halcyon-v1.0.0'"
    ).rowcount
    print(f"  model_versions: {changed} rows updated (halcyon→arcis, ROLLED_BACK→active)")
    conn.commit()

# ── Fix 3-4: Postgres stale collector timestamps ─────────────────
if not DATABASE_URL:
    print("\n⚠  DATABASE_URL not set — skipping Postgres fixes.")
    print("   Add DATABASE_URL to .env and re-run, or fix manually via Render PSQL.")
    sys.exit(0)

print("\n=== Postgres fixes ===")
try:
    import psycopg2
    conn = psycopg2.connect(DATABASE_URL, connect_timeout=10)
    cur = conn.cursor()

    # Fix 1-2 in Postgres too
    cur.execute(
        "UPDATE model_versions SET version_name='arcis:v1.0.0', status='active' "
        "WHERE version_name='halcyon-v1.0.0'"
    )
    print(f"  model_versions: {cur.rowcount} rows updated")

    # Fix 3-4: Clear stale collector tables — next sync cycle re-inserts fresh data
    stale_tables = [
        "earnings_calendar",
        "edgar_filings",
        "insider_transactions",
        "fed_communications",
    ]
    for table in stale_tables:
        try:
            cur.execute(f"DELETE FROM {table}")
            print(f"  {table}: cleared {cur.rowcount} rows (will re-sync in ~60s)")
        except Exception as exc:
            print(f"  {table}: skip ({exc})")
            conn.rollback()
            cur = conn.cursor()

    conn.commit()
    conn.close()
    print("\n✓ Done. Next render_sync cycle will push fresh data.")

except ImportError:
    print("  psycopg2 not installed — run: pip install psycopg2-binary")
except Exception as exc:
    print(f"  Postgres connection failed: {exc}")
