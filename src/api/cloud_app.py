"""Stripped-down read-only FastAPI for Render cloud deployment.

Reads exclusively from Postgres (no SQLite, no Ollama dependency).
Auth: optional bearer token via API_SECRET env var.
"""

import json
import logging
import os
from contextlib import contextmanager
from types import SimpleNamespace
from typing import Optional
from zoneinfo import ZoneInfo

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from src.api.cloud_routes.analytics import create_router as create_analytics_router
from src.api.cloud_routes.core import create_router as create_core_router
from src.api.cloud_routes.council import create_router as create_council_router
from src.api.cloud_routes.notes import create_router as create_notes_router
from src.api.cloud_routes.trades import create_router as create_trades_router
from src.api.cloud_routes.training import create_router as create_training_router
from src.sync.render_sync import SYNC_TABLES

logger = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")
DIAGNOSTIC_TABLES = tuple(SYNC_TABLES.keys())

API_SECRET = os.environ.get("API_SECRET", "")
DATABASE_URL = os.environ.get("DATABASE_URL", "")
security = HTTPBearer(auto_error=False)

USER_NOTES_SCHEMA = """
CREATE TABLE IF NOT EXISTS user_notes (
    note_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    content TEXT DEFAULT '',
    tags TEXT DEFAULT '[]',
    pinned INTEGER DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""

CLOUD_ACTION_MSG = {
    "error": "cloud_mode",
    "message": "This action is only available on the local dashboard.",
}


app = FastAPI(
    title="Halcyon Lab Cloud API",
    version="1.0.0",
    description="Read-only cloud API for the Halcyon Lab trading system",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)


def verify_auth(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> None:
    """Verify bearer token if API_SECRET is set. No-op if unset."""
    if not API_SECRET:
        logger.warning(
            "[AUTH] API_SECRET is empty — authentication disabled. "
            "Set API_SECRET env var to enable auth."
        )
        return
    if not credentials or credentials.credentials != API_SECRET:
        raise HTTPException(status_code=401, detail="Invalid or missing API token")


@contextmanager
def get_pg(readonly: bool = True):
    """Yield a Postgres connection."""
    import psycopg2

    if not DATABASE_URL:
        raise HTTPException(status_code=503, detail="DATABASE_URL not configured")

    conn = None
    try:
        conn = psycopg2.connect(DATABASE_URL)
        conn.set_session(readonly=readonly, autocommit=readonly)
        yield conn
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Postgres connection error: %s", exc)
        raise HTTPException(status_code=503, detail="Database unavailable")
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


def _query(sql: str, params: tuple = ()) -> list[dict]:
    """Execute a read query and return rows as dicts."""
    import psycopg2.extras

    with get_pg(readonly=True) as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            return [dict(row) for row in cur.fetchall()]


def _query_one(sql: str, params: tuple = ()) -> dict | None:
    """Execute a read query and return one row."""
    rows = _query(sql, params)
    return rows[0] if rows else None


def _parse_json_fields(row: dict, fields: list[str]) -> dict:
    """Attempt to parse JSON string fields into dicts/lists."""
    for field in fields:
        val = row.get(field)
        if val and isinstance(val, str):
            try:
                row[field] = json.loads(val)
            except (json.JSONDecodeError, TypeError):
                pass
    return row


def _normalize_tags(tags: list[str] | str | None) -> list[str]:
    """Normalize note tags into a clean string list."""
    if tags is None:
        return []
    raw = tags.split(",") if isinstance(tags, str) else tags
    return [str(tag).strip() for tag in raw if str(tag).strip()]


def _ensure_user_notes_table() -> None:
    """Create the user_notes table if it is missing."""
    with get_pg(readonly=False) as conn:
        with conn.cursor() as cur:
            cur.execute(USER_NOTES_SCHEMA)
            conn.commit()


def _parse_note_row(row: dict) -> dict:
    """Normalize a note row for API responses."""
    parsed = _parse_json_fields(dict(row), ["tags"])
    if not isinstance(parsed.get("tags"), list):
        parsed["tags"] = _normalize_tags(parsed.get("tags"))
    parsed["pinned"] = bool(parsed.get("pinned"))
    return parsed


def _build_runtime() -> SimpleNamespace:
    """Build route helpers while preserving cloud_app patch points for tests."""

    def query(sql: str, params: tuple = ()) -> list[dict]:
        return _query(sql, params)

    def query_one(sql: str, params: tuple = ()) -> dict | None:
        return _query_one(sql, params)

    def open_pg(readonly: bool = True):
        return get_pg(readonly=readonly)

    def ensure_user_notes_table() -> None:
        _ensure_user_notes_table()

    return SimpleNamespace(
        cloud_action_msg=CLOUD_ACTION_MSG,
        diagnostic_tables=DIAGNOSTIC_TABLES,
        ensure_user_notes_table=ensure_user_notes_table,
        et=ET,
        get_pg=open_pg,
        logger=logger,
        normalize_tags=_normalize_tags,
        parse_json_fields=_parse_json_fields,
        parse_note_row=_parse_note_row,
        query=query,
        query_one=query_one,
    )


_runtime = _build_runtime()
for factory in (
    create_core_router,
    create_trades_router,
    create_training_router,
    create_notes_router,
    create_council_router,
    create_analytics_router,
):
    app.include_router(factory(_runtime, verify_auth))
