"""One-time backfill of NULL ``model_version`` on the recommendations table.

Ralph-loop Pass 3 caught this: fixing ``get_active_model_name()`` alone does
nothing for existing recommendations that already have ``model_version=NULL``.
Model Performance dashboard groups trades by recommendation.model_version, so
those NULL rows all fall into the "base" bucket.

Backfills both local SQLite and Render Postgres. Defaults to
``halcyon-v1.0.0`` (the model that has been active since 2026-03-25). Pass
``--version`` to override.

Usage:
    python scripts/backfill_model_version.py
    python scripts/backfill_model_version.py --dry-run
    DATABASE_URL="postgres://..." python scripts/backfill_model_version.py
"""
from __future__ import annotations

import argparse
import logging
import os
import sqlite3
import sys

from src.config import DB_PATH
from src.utils.db import connect_db

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("backfill_model_version")

DEFAULT_VERSION = "halcyon-v1.0.0"


def _backfill_sqlite(db_path: str, version: str, dry_run: bool) -> int:
    with connect_db(db_path) as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM recommendations WHERE model_version IS NULL"
        ).fetchone()[0]
        logger.info("SQLite: %d recommendations with NULL model_version", count)
        if dry_run or count == 0:
            return count
        updated = conn.execute(
            "UPDATE recommendations SET model_version = ? WHERE model_version IS NULL",
            (version,),
        ).rowcount
        conn.commit()
        logger.info("SQLite: updated %d rows", updated)
        return updated


def _backfill_postgres(version: str, dry_run: bool) -> int | None:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        try:
            import yaml
            with open("config/settings.local.yaml", "r", encoding="utf-8") as fh:
                cfg = yaml.safe_load(fh) or {}
            database_url = (cfg.get("render") or {}).get("database_url")
        except Exception as exc:
            logger.debug("settings.local.yaml unavailable: %s", exc)
    if not database_url:
        logger.warning("DATABASE_URL not set — skipping Postgres backfill")
        return None

    import psycopg2
    with psycopg2.connect(database_url) as pg_conn:
        with pg_conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM recommendations WHERE model_version IS NULL"
            )
            count = cur.fetchone()[0]
        logger.info("Postgres: %d recommendations with NULL model_version", count)
        if dry_run or count == 0:
            return count
        with pg_conn.cursor() as cur:
            cur.execute(
                "UPDATE recommendations SET model_version = %s WHERE model_version IS NULL",
                (version,),
            )
            updated = cur.rowcount
        pg_conn.commit()
    logger.info("Postgres: updated %d rows", updated)
    return updated


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", default=DEFAULT_VERSION,
                        help=f"Model version to assign (default: {DEFAULT_VERSION})")
    parser.add_argument("--dry-run", action="store_true", help="Print counts only, no writes")
    parser.add_argument("--db-path", default=DB_PATH, help="Local SQLite path")
    parser.add_argument("--skip-postgres", action="store_true", help="Backfill SQLite only")
    args = parser.parse_args()

    try:
        _backfill_sqlite(args.db_path, args.version, args.dry_run)
    except Exception as exc:
        logger.error("SQLite backfill failed: %s", exc)
        return 1

    if not args.skip_postgres:
        try:
            _backfill_postgres(args.version, args.dry_run)
        except Exception as exc:
            logger.error("Postgres backfill failed: %s", exc)
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
