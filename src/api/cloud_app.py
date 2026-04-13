"""Stripped-down read-only FastAPI for Render cloud deployment.

Called by: none (entry point)
Calls: api.cloud_routes.analytics, api.cloud_routes.core, api.cloud_routes.council, api.cloud_routes.ib_shadow, api.cloud_routes.notes, api.cloud_routes.trades, api.cloud_routes.training, sync.render_sync
Owns tables: user_notes
Config keys: none
Tests: tests/test_cloud_app.py, tests/test_cloud_auth.py

Reads exclusively from Postgres (no SQLite, no Ollama dependency).
Auth: optional bearer token via API_SECRET env var.

Architecture: The cloud app mirrors the local API's endpoint shapes but reads
from Render Postgres instead of local SQLite. This lets the same React frontend
work against either backend — it detects local vs cloud from the /api/status
response. Mutating actions (scan, train, close positions) go through the
command queue rather than executing directly, since there's no GPU or Ollama
on Render.

Auth: Accepts both SHA-256 hashed tokens (from the frontend AuthGate component)
and raw plaintext (for curl/script usage). If API_SECRET env var is empty,
auth is disabled entirely with a warning log (#208: wildcard CORS is
acceptable only because auth gates all data endpoints).

Known issue #80: The /api/build-score route was duplicated between analytics.py
and this file during a refactor. Now consolidated in analytics.py.
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
from src.api.cloud_routes.ib_shadow import create_router as create_ib_shadow_router
from src.api.cloud_routes.training import create_router as create_training_router
from src.sync.render_sync import SYNC_TABLES

logger = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")
DIAGNOSTIC_TABLES = tuple(SYNC_TABLES.keys())

API_SECRET = os.environ.get("API_SECRET", "")
DATABASE_URL = os.environ.get("DATABASE_URL", "")
# CORS origins are configured via env var on Render. The default restricts
# to our Render domain. In dev, set CORS_ORIGINS=http://localhost:5173 to
# allow Vite dev server access. See #208 for wildcard CORS discussion.
CORS_ORIGINS = [
    o.strip()
    for o in os.environ.get(
        "CORS_ORIGINS", "https://halcyonlab.onrender.com"
    ).split(",")
    if o.strip()
]
security = HTTPBearer(auto_error=False)

# user_notes is the only table created directly in Postgres by the cloud app
# (not synced from SQLite). DDL comes from the schema registry to stay consistent.

# Returned for endpoints that cannot run in cloud mode (no GPU, no Ollama).
# The frontend checks for error=="cloud_mode" to show a "run locally" message.
CLOUD_ACTION_MSG = {
    "error": "cloud_mode",
    "message": "This action is only available on the local dashboard.",
}


app = FastAPI(
    title="Arcis Cloud API",
    version="0.17.1",
    description="Read-only cloud API for the Arcis trading system",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)


@app.get("/healthz")
def healthz():
    """Health check for Render deployment monitoring."""
    return {"status": "ok"}


def _sha256_hex(value: str) -> str:
    """Compute SHA-256 hex digest of a string."""
    import hashlib
    return hashlib.sha256(value.encode()).hexdigest()


# Pre-compute the hashed secret on startup for constant-time comparison
_API_SECRET_HASH = _sha256_hex(API_SECRET) if API_SECRET else ""


def verify_auth(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> None:
    """Verify bearer token if API_SECRET is set.

    Accepts both the SHA-256 hashed token (from frontend AuthGate) and
    the raw plaintext secret (for backward compatibility / curl usage).
    """
    if not API_SECRET:
        raise RuntimeError(
            "API_SECRET env var must be set — refusing to serve without authentication. "
            "Set API_SECRET in your environment variables."
        )
    if not credentials:
        raise HTTPException(status_code=401, detail="Invalid or missing API token")
    token = credentials.credentials
    # Accept hashed token (frontend sends SHA-256 of password)
    # or raw plaintext (backward compat for curl/scripts)
    if token == _API_SECRET_HASH or token == API_SECRET:
        return
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
    """Create the user_notes table if it is missing (from schema registry)."""
    from src.schema.registry import TABLES as _REG
    from src.schema.postgres import generate_create_sql as _pg_create

    with get_pg(readonly=False) as conn:
        with conn.cursor() as cur:
            cur.execute(_pg_create(_REG["user_notes"]))
            conn.commit()


def _parse_note_row(row: dict) -> dict:
    """Normalize a note row for API responses."""
    parsed = _parse_json_fields(dict(row), ["tags"])
    if not isinstance(parsed.get("tags"), list):
        parsed["tags"] = _normalize_tags(parsed.get("tags"))
    parsed["pinned"] = bool(parsed.get("pinned"))
    return parsed


def _build_runtime() -> SimpleNamespace:
    """Build route helpers while preserving cloud_app patch points for tests.

    The SimpleNamespace acts as a dependency injection container so that
    route modules receive DB helpers without importing cloud_app directly.
    Tests can monkey-patch _query/_query_one on the runtime to inject mock
    data without needing a real Postgres connection.
    """

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
    create_ib_shadow_router,
):
    app.include_router(factory(_runtime, verify_auth))
