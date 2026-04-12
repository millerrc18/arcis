"""One-time sync of quarantine flags from local SQLite to Render Postgres.

The standard sync is incremental — it only pushes rows where
``updated_at > last_synced_at``. Quarantine UPDATEs run by
``scripts/quarantine_april10.py`` did not touch ``updated_at``, so the
``quarantined=1`` flag never reached Postgres. Every cloud route uses
``COALESCE(quarantined, 0) = 0`` as its filter, so Postgres was serving
compromised rows as if they were clean.

This script issues direct UPDATEs to Postgres for every locally-quarantined
trade. It is safe to re-run; the UPDATE is idempotent.

Run once after deploy, then verify counts match between SQLite and Postgres.

Usage:
    DATABASE_URL="postgres://..." python scripts/sync_quarantine_to_postgres.py
    DATABASE_URL="postgres://..." python scripts/sync_quarantine_to_postgres.py --dry-run
"""
from __future__ import annotations

import argparse
import logging
import os
import sqlite3
import sys

from src.config import DB_PATH

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("sync_quarantine")


def _resolve_database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if url:
        return url
    try:
        import yaml
        with open("config/settings.local.yaml", "r", encoding="utf-8") as fh:
            cfg = yaml.safe_load(fh) or {}
        url = (cfg.get("render") or {}).get("database_url")
        if url:
            return url
    except Exception as exc:
        logger.debug("settings.local.yaml unavailable: %s", exc)
    raise RuntimeError(
        "DATABASE_URL not set and render.database_url missing from config/settings.local.yaml"
    )


def _fetch_local_quarantined(db_path: str) -> list[str]:
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT trade_id FROM shadow_trades WHERE COALESCE(quarantined, 0) = 1"
        ).fetchall()
    return [r["trade_id"] for r in rows]


def sync_quarantine_flags(db_path: str = DB_PATH, dry_run: bool = False) -> dict:
    """Push quarantine flags from local SQLite to Postgres. Returns summary dict."""
    trade_ids = _fetch_local_quarantined(db_path)
    logger.info("Found %d quarantined trades in local SQLite", len(trade_ids))
    if not trade_ids:
        return {"local_quarantined": 0, "postgres_updated": 0, "dry_run": dry_run}

    if dry_run:
        logger.info("[DRY-RUN] Would UPDATE %d rows in Postgres shadow_trades", len(trade_ids))
        return {"local_quarantined": len(trade_ids), "postgres_updated": 0, "dry_run": True}

    import psycopg2
    database_url = _resolve_database_url()
    updated = 0
    with psycopg2.connect(database_url) as pg_conn:
        with pg_conn.cursor() as cur:
            for tid in trade_ids:
                cur.execute(
                    "UPDATE shadow_trades SET quarantined = 1 WHERE trade_id = %s",
                    (tid,),
                )
                updated += cur.rowcount
        pg_conn.commit()

        with pg_conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM shadow_trades WHERE COALESCE(quarantined, 0) = 1"
            )
            pg_total = cur.fetchone()[0]

    logger.info("Updated %d rows (rowcount). Postgres total quarantined now: %d",
                updated, pg_total)
    return {
        "local_quarantined": len(trade_ids),
        "postgres_updated": updated,
        "postgres_total_quarantined": pg_total,
        "dry_run": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Print counts only, no writes")
    parser.add_argument("--db-path", default=DB_PATH, help="Local SQLite path")
    args = parser.parse_args()

    try:
        result = sync_quarantine_flags(db_path=args.db_path, dry_run=args.dry_run)
    except Exception as exc:
        logger.error("Quarantine sync failed: %s", exc)
        return 1
    logger.info("Result: %s", result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
