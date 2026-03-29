"""Stripped-down read-only FastAPI for Render cloud deployment.

Reads exclusively from Postgres (no SQLite, no Ollama dependency).
Auth: optional bearer token via API_SECRET env var.
"""

import json
import logging
import os
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")

# ── App setup ────────────────────────────────────────────────────────

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

# ── Auth ─────────────────────────────────────────────────────────────

API_SECRET = os.environ.get("API_SECRET", "")
security = HTTPBearer(auto_error=False)


def verify_auth(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> None:
    """Verify bearer token if API_SECRET is set. No-op if unset."""
    if not API_SECRET:
        import logging
        logging.getLogger(__name__).warning(
            "[AUTH] API_SECRET is empty — authentication disabled. "
            "Set API_SECRET env var to enable auth."
        )
        return  # Auth disabled — warn but allow (local dev / cold start)
    if not credentials or credentials.credentials != API_SECRET:
        raise HTTPException(status_code=401, detail="Invalid or missing API token")


# ── Database connection ──────────────────────────────────────────────

DATABASE_URL = os.environ.get("DATABASE_URL", "")

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


class NoteCreatePayload(BaseModel):
    title: str = "Untitled Note"
    content: str = ""
    tags: list[str] | str = Field(default_factory=list)
    pinned: bool = False


class NoteUpdatePayload(BaseModel):
    title: str | None = None
    content: str | None = None
    tags: list[str] | str | None = None
    pinned: bool | None = None


@contextmanager
def get_pg(readonly: bool = True):
    """Yield a Postgres connection. Caller must NOT commit (read-only)."""
    import psycopg2
    import psycopg2.extras

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
    """Execute a read query and return list of dicts."""
    import psycopg2.extras

    with get_pg(readonly=True) as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
            return [dict(r) for r in rows]


def _query_one(sql: str, params: tuple = ()) -> dict | None:
    """Execute a read query and return one dict or None."""
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
    """Normalize incoming note tags into a clean string list."""
    if tags is None:
        return []
    if isinstance(tags, str):
        raw = tags.split(",")
    else:
        raw = tags
    return [str(tag).strip() for tag in raw if str(tag).strip()]


def _ensure_user_notes_table() -> None:
    """Create the user_notes table if it is missing."""
    with get_pg(readonly=False) as conn:
        with conn.cursor() as cur:
            cur.execute(USER_NOTES_SCHEMA)
            conn.commit()


def _parse_note_row(row: dict) -> dict:
    """Normalize a note row for API responses."""
    parsed = dict(row)
    parsed = _parse_json_fields(parsed, ["tags"])
    if not isinstance(parsed.get("tags"), list):
        parsed["tags"] = _normalize_tags(parsed.get("tags"))
    parsed["pinned"] = bool(parsed.get("pinned"))
    return parsed


# ── Endpoints ────────────────────────────────────────────────────────

@app.get("/healthz")
def healthz():
    """Unauthenticated health check for Render."""
    return {"status": "ok"}

@app.get("/api/diagnostics", dependencies=[Depends(verify_auth)])
def diagnostics():
    """Test every DB table the dashboard needs. Returns pass/fail per table."""
    tables = [
        "shadow_trades", "recommendations", "options_metrics", "vix_term_structure",
        "macro_snapshots", "api_costs", "training_examples", "setup_signals",
        "council_sessions", "council_votes", "scan_metrics", "canary_evaluations",
        "quality_drift_metrics", "activity_log", "research_docs", "model_versions",
        "edgar_filings", "insider_transactions", "short_interest", "analyst_estimates",
        "research_papers", "research_digests", "schedule_metrics",
    ]
    results = {}
    for table in tables:
        try:
            row = _query_one(f"SELECT COUNT(*) as c FROM {table}")  # noqa: S608 — table names are hardcoded
            results[table] = {"status": "ok", "rows": row["c"] if row else 0}
        except Exception as e:
            results[table] = {"status": "error", "error": str(e)}

    failed = [t for t, r in results.items() if r["status"] == "error"]
    return {
        "status": "healthy" if not failed else "degraded",
        "tables": results,
        "failed_count": len(failed),
        "failed_tables": failed,
    }


@app.get("/api/auth", dependencies=[Depends(verify_auth)])
def auth_check():
    """Verify auth token without touching the database.

    Used by AuthGate to validate password on login.
    Returns 200 if token is valid, 401 if not.
    """
    return {"authenticated": True}

@app.get("/api/status", dependencies=[Depends(verify_auth)])
def status():
    """System status overview from cloud data."""
    try:
        open_trades = _query(
            "SELECT COUNT(*) as count FROM shadow_trades WHERE status = 'open'"
        )
        closed_trades = _query(
            "SELECT COUNT(*) as count FROM shadow_trades WHERE status = 'closed'"
        )
        latest_model = _query_one(
            "SELECT version_name, created_at, status FROM model_versions "
            "ORDER BY created_at DESC LIMIT 1"
        )
        latest_audit = _query_one(
            "SELECT overall_assessment, created_at FROM audit_reports "
            "ORDER BY created_at DESC LIMIT 1"
        )

        model_name = latest_model["version_name"] if latest_model else "base"

        # Count training examples
        try:
            te = _query_one("SELECT COUNT(*) as c FROM training_examples")
            example_count = te["c"] if te else 0
        except Exception as exc:
            logger.warning("[API] training_examples count failed: %s", exc)
            example_count = 0

        return {
            "environment": "cloud",
            "open_positions": open_trades[0]["count"] if open_trades else 0,
            "closed_trades": closed_trades[0]["count"] if closed_trades else 0,
            "latest_model": latest_model,
            "latest_audit": latest_audit,
            "llm_available": False,
            "model_version": model_name,
            "training_examples": example_count,
            "alpaca_equity": 0,
            "timestamp": datetime.now(ET).isoformat(),
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Status endpoint error: %s", exc)
        return {
            "environment": "cloud",
            "error": str(exc),
            "timestamp": datetime.now(ET).isoformat(),
        }


@app.get("/api/shadow/open", dependencies=[Depends(verify_auth)])
def shadow_open():
    """Open shadow trades."""
    try:
        rows = _query(
            "SELECT * FROM shadow_trades WHERE status = 'open' ORDER BY created_at DESC"
        )
        # Compute account equity from closed P&L
        closed_pnl_row = _query_one(
            "SELECT COALESCE(SUM(pnl_dollars), 0) as total FROM shadow_trades WHERE status = 'closed'"
        )
        closed_pnl = closed_pnl_row["total"] if closed_pnl_row else 0
        starting_capital = 100000
        equity = starting_capital + (closed_pnl or 0)

        return {
            "trades": rows,
            "open_trades": rows,
            "count": len(rows),
            "open_count": len(rows),
            "account_equity": round(equity, 2),
            "total_unrealized_pnl": 0,
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Shadow open error: %s", exc)
        return {"trades": [], "open_trades": [], "count": 0, "open_count": 0,
                "account_equity": 100000, "total_unrealized_pnl": 0, "error": str(exc)}


@app.get("/api/shadow/closed", dependencies=[Depends(verify_auth)])
def shadow_closed(days: int = 30):
    """Closed shadow trades for the last N days."""
    try:
        cutoff = (datetime.now(ET) - timedelta(days=days)).isoformat()
        rows = _query(
            "SELECT * FROM shadow_trades WHERE status = 'closed' "
            "AND actual_exit_time >= %s ORDER BY actual_exit_time DESC",
            (cutoff,),
        )
        # Compute inline metrics the frontend expects
        pnls = [r.get("pnl_dollars", 0) or 0 for r in rows]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p <= 0]
        total_pnl = sum(pnls)
        metrics = {
            "total_trades": len(rows),
            "win_rate": round(len(wins) / len(rows) * 100, 1) if rows else 0,
            "avg_gain": round(sum(wins) / len(wins), 2) if wins else 0,
            "avg_loss": round(sum(losses) / len(losses), 2) if losses else 0,
            "expectancy": round(total_pnl / len(rows), 2) if rows else 0,
            "total_pnl": round(total_pnl, 2),
        }
        return {"trades": rows, "count": len(rows), "days": days, "metrics": metrics}
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Shadow closed error: %s", exc)
        return {"trades": [], "count": 0, "metrics": {}, "error": str(exc)}


@app.get("/api/shadow/metrics", dependencies=[Depends(verify_auth)])
def shadow_metrics(days: int = 30):
    """Computed metrics from closed trades."""
    try:
        cutoff = (datetime.now(ET) - timedelta(days=days)).isoformat()
        rows = _query(
            "SELECT pnl_dollars, pnl_pct FROM shadow_trades "
            "WHERE status = 'closed' AND actual_exit_time >= %s",
            (cutoff,),
        )
        if not rows:
            return {"total_trades": 0}

        pnls = [r["pnl_dollars"] or 0 for r in rows]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p <= 0]
        total_pnl = sum(pnls)

        return {
            "total_trades": len(rows),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": round(len(wins) / len(rows), 3) if rows else 0,
            "total_pnl": round(total_pnl, 2),
            "avg_win": round(sum(wins) / len(wins), 2) if wins else 0,
            "avg_loss": round(sum(losses) / len(losses), 2) if losses else 0,
            "expectancy": round(total_pnl / len(rows), 2) if rows else 0,
            "days": days,
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Shadow metrics error: %s", exc)
        return {"total_trades": 0, "error": str(exc)}


@app.get("/api/packets", dependencies=[Depends(verify_auth)])
def packets(days: int = 7):
    """Recent recommendations / trade packets."""
    try:
        cutoff = (datetime.now(ET) - timedelta(days=days)).isoformat()
        rows = _query(
            "SELECT * FROM recommendations WHERE created_at >= %s "
            "ORDER BY created_at DESC",
            (cutoff,),
        )
        return rows
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Packets error: %s", exc)
        return []


@app.get("/api/training/status", dependencies=[Depends(verify_auth)])
def training_status():
    """Training pipeline status from cloud data."""
    try:
        active_model = _query_one(
            "SELECT * FROM model_versions WHERE status = 'active' "
            "ORDER BY created_at DESC LIMIT 1"
        )
        total_versions = _query(
            "SELECT COUNT(*) as count FROM model_versions"
        )
        # Count training examples by source
        total_examples = _query_one("SELECT COUNT(*) as c FROM training_examples")
        win_examples = _query_one("SELECT COUNT(*) as c FROM training_examples WHERE outcome = 'win' OR source = 'blinded_win'")
        loss_examples = _query_one("SELECT COUNT(*) as c FROM training_examples WHERE outcome = 'loss' OR source = 'blinded_loss'")
        synthetic_examples = _query_one("SELECT COUNT(*) as c FROM training_examples WHERE source = 'synthetic_claude' OR source = 'synthetic'")

        dataset_total = total_examples["c"] if total_examples else 0
        dataset_wins = win_examples["c"] if win_examples else 0
        dataset_losses = loss_examples["c"] if loss_examples else 0
        dataset_synthetic = synthetic_examples["c"] if synthetic_examples else 0
        model_name = active_model["version_name"] if active_model else "base"

        return {
            "active_model": active_model,
            "total_versions": total_versions[0]["count"] if total_versions else 0,
            # Fields the Training page expects
            "model_name": model_name,
            "dataset_total": dataset_total,
            "dataset_wins": dataset_wins,
            "dataset_losses": dataset_losses,
            "dataset_synthetic": dataset_synthetic,
            "new_since_last_train": 0,
            "train_queued": False,
            "train_reason": "Cloud mode — training runs locally",
            "rollback_status": "n/a (cloud mode)",
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Training status error: %s", exc)
        return {"active_model": None, "model_name": "base", "dataset_total": 0,
                "dataset_wins": 0, "dataset_losses": 0, "dataset_synthetic": 0,
                "new_since_last_train": 0, "train_queued": False, "error": str(exc)}


@app.get("/api/training/versions", dependencies=[Depends(verify_auth)])
def training_versions():
    """All model versions."""
    try:
        rows = _query(
            "SELECT * FROM model_versions ORDER BY created_at DESC"
        )
        return {"versions": rows}
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Training versions error: %s", exc)
        return {"versions": []}


@app.get("/api/metrics/history", dependencies=[Depends(verify_auth)])
def metrics_history(days: int = 90):
    """Metric snapshots for trending charts."""
    try:
        cutoff = (datetime.now(ET) - timedelta(days=days)).isoformat()
        rows = _query(
            "SELECT * FROM metric_snapshots WHERE created_at >= %s "
            "ORDER BY snapshot_date ASC",
            (cutoff,),
        )
        for r in rows:
            _parse_json_fields(r, ["metrics_json"])
        return rows
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Metrics history error: %s", exc)
        return []


@app.get("/api/schedule-metrics", dependencies=[Depends(verify_auth)])
def schedule_metrics(days: int = 30):
    """Compute schedule metrics."""
    try:
        cutoff = (datetime.now(ET) - timedelta(days=days)).strftime("%Y-%m-%d")
        rows = _query(
            "SELECT * FROM schedule_metrics WHERE metric_date >= %s "
            "ORDER BY metric_date DESC",
            (cutoff,),
        )
        return rows
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Schedule metrics error: %s", exc)
        return []


@app.get("/api/earnings", dependencies=[Depends(verify_auth)])
def earnings(days: int = 14):
    """Upcoming earnings from the earnings calendar."""
    try:
        today = datetime.now(ET).strftime("%Y-%m-%d")
        future = (datetime.now(ET) + timedelta(days=days)).strftime("%Y-%m-%d")
        rows = _query(
            "SELECT * FROM earnings_calendar "
            "WHERE earnings_date >= %s AND earnings_date <= %s "
            "ORDER BY earnings_date ASC",
            (today, future),
        )
        return {
            "days_ahead": days,
            "count": len(rows),
            "earnings": rows,
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Earnings error: %s", exc)
        return {"days_ahead": days, "count": 0, "earnings": [], "error": str(exc)}


@app.get("/api/audit/latest", dependencies=[Depends(verify_auth)])
def audit_latest():
    """Most recent daily audit report."""
    try:
        row = _query_one(
            "SELECT * FROM audit_reports ORDER BY created_at DESC LIMIT 1"
        )
        if not row:
            return {"audit": None}
        _parse_json_fields(row, ["flags", "metrics_to_watch"])
        return row
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Audit latest error: %s", exc)
        return {"audit": None, "error": str(exc)}


@app.get("/api/docs", dependencies=[Depends(verify_auth)])
def docs_list():
    """Documentation listing from research_docs table."""
    try:
        rows = _query(
            "SELECT id, filename, title, category, size_kb, updated_at "
            "FROM research_docs ORDER BY category, title"
        )
        return [
            {
                "id": r["id"],
                "filename": r.get("filename", ""),
                "title": r["title"],
                "category": r.get("category", "Uncategorized"),
                "size_kb": r.get("size_kb", 0),
                "available": True,
            }
            for r in rows
        ]
    except Exception as exc:
        logger.error("Docs list error: %s", exc)
        return []


@app.get("/api/docs/{doc_id}", dependencies=[Depends(verify_auth)])
def get_doc(doc_id: str):
    """Individual doc content from research_docs table."""
    try:
        row = _query_one(
            "SELECT id, title, category, content FROM research_docs WHERE id = %s",
            (doc_id,),
        )
        if row:
            return {
                "id": row["id"],
                "title": row["title"],
                "category": row.get("category", ""),
                "content": row["content"],
            }
        return {
            "id": doc_id,
            "title": doc_id,
            "content": f"# {doc_id}\n\nDocument not found. It may not have been synced yet.",
        }
    except Exception as exc:
        logger.error("Docs read error: %s", exc)
        return {
            "id": doc_id,
            "title": doc_id,
            "content": f"# Error\n\nFailed to load document: {exc}",
        }


@app.get("/api/health/hshs", dependencies=[Depends(verify_auth)])
def health_hshs():
    """Compute and return the live Halcyon System Health Score."""
    try:
        from src.evaluation.hshs_live import compute_hshs
        return compute_hshs()
    except Exception as e:
        import logging
        logging.getLogger(__name__).error("[API] HSHS computation failed: %s", e)
        return {"hshs": 0, "dimensions": {}, "error": str(e)}


@app.get("/api/notes", dependencies=[Depends(verify_auth)])
def list_notes():
    """List all notes for the Notes page."""
    try:
        _ensure_user_notes_table()
        rows = _query(
            "SELECT * FROM user_notes ORDER BY pinned DESC, updated_at DESC"
        )
        return {"notes": [_parse_note_row(row) for row in rows]}
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("[API] notes list failed: %s", exc)
        return {"notes": [], "error": str(exc)}


@app.post("/api/notes", status_code=201, dependencies=[Depends(verify_auth)])
def create_note(payload: NoteCreatePayload):
    """Create a new note."""
    try:
        _ensure_user_notes_table()
        now = datetime.now(ET).isoformat()
        note_id = str(uuid.uuid4())
        tags_json = json.dumps(_normalize_tags(payload.tags))
        with get_pg(readonly=False) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO user_notes "
                    "(note_id, title, content, tags, pinned, created_at, updated_at) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                    (
                        note_id,
                        payload.title or "Untitled Note",
                        payload.content or "",
                        tags_json,
                        1 if payload.pinned else 0,
                        now,
                        now,
                    ),
                )
                conn.commit()
        return _parse_note_row(
            {
                "note_id": note_id,
                "title": payload.title or "Untitled Note",
                "content": payload.content or "",
                "tags": tags_json,
                "pinned": payload.pinned,
                "created_at": now,
                "updated_at": now,
            }
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("[API] note create failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@app.put("/api/notes/{note_id}", dependencies=[Depends(verify_auth)])
def update_note(note_id: str, payload: NoteUpdatePayload):
    """Update a note in place."""
    try:
        _ensure_user_notes_table()
        updates = payload.model_dump(exclude_unset=True)
        if not updates:
            existing = _query_one("SELECT * FROM user_notes WHERE note_id = %s", (note_id,))
            if not existing:
                raise HTTPException(status_code=404, detail="Note not found")
            return _parse_note_row(existing)

        fields = []
        values: list[object] = []
        if "title" in updates:
            fields.append("title = %s")
            values.append(updates["title"] or "Untitled Note")
        if "content" in updates:
            fields.append("content = %s")
            values.append(updates["content"] or "")
        if "tags" in updates:
            fields.append("tags = %s")
            values.append(json.dumps(_normalize_tags(updates["tags"])))
        if "pinned" in updates:
            fields.append("pinned = %s")
            values.append(1 if updates["pinned"] else 0)
        fields.append("updated_at = %s")
        values.append(datetime.now(ET).isoformat())
        values.append(note_id)

        with get_pg(readonly=False) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"UPDATE user_notes SET {', '.join(fields)} WHERE note_id = %s",
                    tuple(values),
                )
                if cur.rowcount == 0:
                    raise HTTPException(status_code=404, detail="Note not found")
                conn.commit()

        updated = _query_one("SELECT * FROM user_notes WHERE note_id = %s", (note_id,))
        if not updated:
            raise HTTPException(status_code=404, detail="Note not found")
        return _parse_note_row(updated)
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("[API] note update failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@app.delete("/api/notes/{note_id}", status_code=204, dependencies=[Depends(verify_auth)])
def delete_note(note_id: str):
    """Delete a note."""
    try:
        _ensure_user_notes_table()
        with get_pg(readonly=False) as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM user_notes WHERE note_id = %s", (note_id,))
                if cur.rowcount == 0:
                    raise HTTPException(status_code=404, detail="Note not found")
                conn.commit()
        return None
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("[API] note delete failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/council/latest", dependencies=[Depends(verify_auth)])
def council_latest():
    """Latest council session with votes."""
    try:
        session = _query_one(
            "SELECT * FROM council_sessions ORDER BY created_at DESC LIMIT 1"
        )
        if not session:
            return {"session": None}

        session = _parse_json_fields(session, ["result_json"])

        votes = _query(
            "SELECT * FROM council_votes WHERE session_id = %s ORDER BY round, agent_name",
            (session["session_id"],),
        )
        for v in votes:
            _parse_json_fields(v, ["key_data_points", "risk_flags"])

        session["votes"] = votes
        return session
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Council latest error: %s", exc)
        return {"session": None, "error": str(exc)}


@app.get("/api/council/history", dependencies=[Depends(verify_auth)])
def council_history(days: int = 30):
    """Council session history."""
    try:
        cutoff = (datetime.now(ET) - timedelta(days=days)).isoformat()
        rows = _query(
            "SELECT * FROM council_sessions WHERE created_at >= %s "
            "ORDER BY created_at DESC",
            (cutoff,),
        )
        return rows
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Council history error: %s", exc)
        return []


@app.get("/api/council/session/{session_id}", dependencies=[Depends(verify_auth)])
def council_session_detail(session_id: str):
    """Get full council session details including all agent votes."""
    try:
        session = _query_one(
            "SELECT * FROM council_sessions WHERE session_id = %s",
            (session_id,),
        )
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")

        session = _parse_json_fields(session, ["result_json"])

        votes = _query(
            "SELECT * FROM council_votes WHERE session_id = %s ORDER BY round, agent_name",
            (session_id,),
        )
        for v in votes:
            _parse_json_fields(v, ["key_data_points", "risk_flags"])

        return {"session": session, "votes": votes}
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Council session detail error: %s", exc)
        return {"session": None, "votes": [], "error": str(exc)}


@app.get("/api/activity/feed", dependencies=[Depends(verify_auth)])
def activity_feed(limit: int = 50, event_type: str = None):
    """Get recent activity log entries."""
    try:
        if event_type:
            rows = _query(
                "SELECT * FROM activity_log WHERE category = %s "
                "ORDER BY created_at DESC LIMIT %s",
                (event_type, limit),
            )
        else:
            rows = _query(
                "SELECT * FROM activity_log ORDER BY created_at DESC LIMIT %s",
                (limit,),
            )
        return rows
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Activity feed error: %s", exc)
        return []


@app.post("/api/council/strategic", dependencies=[Depends(verify_auth)])
def council_strategic():
    """Cloud deployment cannot run strategic council sessions directly."""
    return {
        "error": "cloud_mode",
        "message": "Strategic council questions must be run from the local dashboard/API.",
    }


# ── New endpoints — Categories 1-3 ────────────────────────────────


@app.get("/api/config", dependencies=[Depends(verify_auth)])
def get_config():
    """Return system config for the Settings page. Cloud mode: static config."""
    return {
        "risk": {"starting_capital": 100000, "planned_risk_pct_min": 0.005, "planned_risk_pct_max": 0.01, "max_open_positions": 50},
        "shadow_trading": {"enabled": True, "max_positions": 50, "timeout_days": 15},
        "llm": {"enabled": True, "model": "halcyonlatest", "temperature": 0.7},
        "bootcamp": {"enabled": True, "phase": 1, "qualification_threshold": 40, "email_mode": "daily_summary"},
        "automation": {"morning_watchlist_hour_et": 8, "eod_recap_hour_et": 16, "scan_interval_minutes": 30},
        "training": {"enabled": True, "claude_model": "claude-sonnet-4-20250514", "auto_train_threshold": 50},
        "environment": "cloud",
    }


@app.get("/api/halt-status", dependencies=[Depends(verify_auth)])
def halt_status():
    """Trading halt status. Cloud mode: always report not halted."""
    return {"halted": False, "reason": None, "halted_at": None}


@app.get("/api/costs", dependencies=[Depends(verify_auth)])
def costs(days: int = 30):
    """API cost summary from api_costs table."""
    try:
        cutoff = (datetime.now(ET) - timedelta(days=days)).isoformat()
        rows = _query(
            "SELECT model, purpose, SUM(input_tokens) as total_input, "
            "SUM(output_tokens) as total_output, SUM(estimated_cost) as total_cost, "
            "COUNT(*) as call_count "
            "FROM api_costs WHERE created_at >= %s "
            "GROUP BY model, purpose ORDER BY total_cost DESC",
            (cutoff,),
        )
        total = sum(r.get("total_cost", 0) or 0 for r in rows)
        return {"days": days, "total_cost": round(total, 4), "breakdown": rows}
    except Exception as exc:
        logger.error("[API] costs failed: %s", exc, exc_info=True)
        return {"days": days, "total_cost": 0, "breakdown": [], "error": str(exc)}


@app.get("/api/health/score", dependencies=[Depends(verify_auth)])
def health_score():
    """HSHS health score. All 5 dimensions computed from cloud data."""
    try:
        # ── Data queries ──
        closed_trades = _query(
            "SELECT pnl_dollars, pnl_pct FROM shadow_trades WHERE status = 'closed'"
        )
        closed_count = len(closed_trades)
        open_count_row = _query_one("SELECT COUNT(*) as c FROM shadow_trades WHERE status = 'open'")
        open_count = open_count_row["c"] if open_count_row else 0

        examples = _query_one("SELECT COUNT(*) as count FROM training_examples")
        example_count = examples["count"] if examples else 0

        model = _query_one("SELECT version_name, status FROM model_versions ORDER BY created_at DESC LIMIT 1")
        canary = _query_one("SELECT verdict, perplexity, distinct_2 FROM canary_evaluations ORDER BY created_at DESC LIMIT 1")

        # Source diversity
        source_counts = _query(
            "SELECT source, COUNT(*) as cnt FROM training_examples GROUP BY source"
        )
        source_map = {r["source"]: r["cnt"] for r in source_counts}

        # Scan metrics for template fallback rate
        scan = _query_one(
            "SELECT llm_success, llm_total FROM scan_metrics ORDER BY created_at DESC LIMIT 1"
        )

        # Regime coverage (distinct regime labels)
        regime_row = _query_one(
            "SELECT COUNT(DISTINCT regime_label) as cnt FROM training_examples WHERE regime_label IS NOT NULL"
        )

        # Ticker coverage
        ticker_row = _query_one(
            "SELECT COUNT(DISTINCT ticker) as cnt FROM training_examples WHERE ticker IS NOT NULL"
        )

        # ── Performance dimension (weight: 0.10) ──
        perf_metrics = {}
        if closed_count >= 2:
            pnls = [t.get("pnl_pct", 0) or 0 for t in closed_trades]
            pnl_dollars = [t.get("pnl_dollars", 0) or 0 for t in closed_trades]
            wins = [p for p in pnls if p > 0]
            losses = [p for p in pnls if p <= 0]
            win_rate = len(wins) / closed_count
            avg_win = sum(wins) / len(wins) if wins else 0
            avg_loss = abs(sum(losses) / len(losses)) if losses else 0.01
            profit_factor = (sum(wins) / abs(sum(losses))) if losses and sum(losses) != 0 else 99
            mean_pnl = sum(pnls) / len(pnls)
            std_pnl = max((sum((p - mean_pnl) ** 2 for p in pnls) / len(pnls)) ** 0.5, 0.001)
            sharpe = mean_pnl / std_pnl
            # Max drawdown from running peak
            running = 0
            peak = 0
            max_dd = 0
            for p in pnl_dollars:
                running += p
                if running > peak:
                    peak = running
                dd = peak - running
                if dd > max_dd:
                    max_dd = dd
            max_dd_pct = (max_dd / 100000) * 100 if max_dd > 0 else 0
            net_pnl = sum(pnl_dollars)

            perf_metrics = {
                "win_rate": round(win_rate, 3),
                "sharpe": round(sharpe, 2),
                "profit_factor": round(min(profit_factor, 99), 2),
                "max_drawdown_pct": round(max_dd_pct, 2),
                "net_pnl": round(net_pnl, 2),
                "trade_count": closed_count,
            }
            # Score: weighted avg of normalized metrics
            wr_score = min(100, win_rate * 200)  # 50% = 100
            sharpe_score = min(100, max(0, sharpe * 50))  # 2.0 = 100
            dd_score = max(0, 100 - max_dd_pct * 5)  # 20% DD = 0
            perf_score = round(wr_score * 0.35 + sharpe_score * 0.35 + dd_score * 0.30, 1)
        else:
            perf_score = 0
            perf_metrics = {"status": "Insufficient data", "trade_count": closed_count, "target": 50}

        # ── Model Quality dimension (weight: 0.25) ──
        mq_metrics = {}
        # Template fallback rate
        fallback_rate = 0
        if scan and scan.get("llm_total") and scan["llm_total"] > 0:
            success = scan.get("llm_success", 0) or 0
            total = scan["llm_total"]
            fallback_rate = round(1 - success / total, 3)
        mq_metrics["template_fallback_rate"] = fallback_rate

        # Canary eval
        if canary:
            mq_metrics["canary_verdict"] = canary.get("verdict", "unknown")
            if canary.get("perplexity"):
                mq_metrics["perplexity"] = round(canary["perplexity"], 2)
            if canary.get("distinct_2"):
                mq_metrics["distinct_2"] = round(canary["distinct_2"], 4)
        else:
            mq_metrics["status"] = "Awaiting first retrain"

        # Score
        fallback_score = max(0, 100 - fallback_rate * 200)  # 0% = 100, 50% = 0
        canary_score = 80 if (canary and canary.get("verdict") == "pass") else 40 if canary else 0
        mq_score = round(fallback_score * 0.5 + canary_score * 0.5, 1)

        # ── Data Asset dimension (weight: 0.35) ──
        data_asset_score = min(100, (example_count / 2800) * 100) if example_count else 0
        da_metrics = {
            "example_count": example_count,
            "target": 2800,
            "progress_pct": round(data_asset_score, 1),
        }

        # ── Flywheel Velocity dimension (weight: 0.20) ──
        flywheel_score = min(100, (closed_count / 50) * 100) if closed_count else 0
        fw_metrics = {
            "closed_trades": closed_count,
            "target": 50,
            "open_trades": open_count,
        }

        # ── Defensibility dimension (weight: 0.10) ──
        regime_count = regime_row["cnt"] if regime_row else 0
        ticker_count = ticker_row["cnt"] if ticker_row else 0
        source_diversity = len(source_map)

        def_score_parts = [
            min(100, (example_count / 2800) * 100) * 0.30,
            min(100, source_diversity * 25) * 0.20,  # 4 sources = 100
            min(100, (regime_count / 33) * 100) * 0.25,
            min(100, (ticker_count / 50) * 100) * 0.25,
        ]
        def_score = round(sum(def_score_parts), 1)
        def_metrics = {
            "example_count": example_count,
            "source_diversity": source_map,
            "regime_coverage": regime_count,
            "regime_target": 33,
            "ticker_coverage": ticker_count,
        }
        if example_count < 100:
            def_metrics["status"] = "Building data asset"

        # ── Overall ──
        weights = {
            "performance": 0.10,
            "model_quality": 0.25,
            "data_asset": 0.35,
            "flywheel_velocity": 0.20,
            "defensibility": 0.10,
        }
        overall = round(
            perf_score * weights["performance"]
            + mq_score * weights["model_quality"]
            + data_asset_score * weights["data_asset"]
            + flywheel_score * weights["flywheel_velocity"]
            + def_score * weights["defensibility"],
            1,
        )

        return {
            "score": {
                "overall": overall,
                "dimensions": {
                    "performance": round(perf_score, 1),
                    "model_quality": round(mq_score, 1),
                    "data_asset": round(data_asset_score, 1),
                    "flywheel_velocity": round(flywheel_score, 1),
                    "defensibility": round(def_score, 1),
                },
                "dimension_metrics": {
                    "performance": perf_metrics,
                    "model_quality": mq_metrics,
                    "data_asset": da_metrics,
                    "flywheel_velocity": fw_metrics,
                    "defensibility": def_metrics,
                },
                "weights": weights,
                "phase": "early",
            },
            "closed_trades": closed_count,
            "training_examples": example_count,
            "model": model,
            "canary": canary,
            "history": [],
        }
    except Exception as exc:
        logger.error("[API] health_score failed: %s", exc, exc_info=True)
        return {"score": {"overall": 0, "dimensions": {}, "weights": {}, "phase": "early"}, "history": [], "error": str(exc)}


@app.get("/api/live/trades", dependencies=[Depends(verify_auth)])
def live_trades():
    """Get all live trades (source='live' in shadow_trades)."""
    try:
        open_trades = _query(
            "SELECT * FROM shadow_trades WHERE source = 'live' AND status = 'open' ORDER BY created_at DESC"
        )
        closed_trades = _query(
            "SELECT * FROM shadow_trades WHERE source = 'live' AND status = 'closed' ORDER BY actual_exit_time DESC"
        )
        return {"open": open_trades, "closed": closed_trades}
    except Exception as exc:
        logger.error("Live trades error: %s", exc)
        return {"open": [], "closed": [], "error": str(exc)}


@app.get("/api/live/summary", dependencies=[Depends(verify_auth)])
def live_summary():
    """Live account summary metrics."""
    try:
        closed = _query(
            "SELECT pnl_dollars, pnl_pct FROM shadow_trades WHERE source = 'live' AND status = 'closed'"
        )
        open_count = _query_one(
            "SELECT COUNT(*) as c FROM shadow_trades WHERE source = 'live' AND status = 'open'"
        )
        starting_capital = 100  # Live account starts at $100
        closed_pnl = sum(t.get("pnl_dollars", 0) or 0 for t in closed)
        wins = [t for t in closed if (t.get("pnl_dollars", 0) or 0) > 0]

        return {
            "starting_capital": starting_capital,
            "current_equity": round(starting_capital + closed_pnl, 2),
            "total_pnl": round(closed_pnl, 2),
            "total_pnl_pct": round((closed_pnl / starting_capital) * 100, 2) if starting_capital else 0,
            "open_positions": open_count["c"] if open_count else 0,
            "closed_trades": len(closed),
            "win_rate": round(len(wins) / len(closed), 3) if closed else None,
        }
    except Exception as exc:
        logger.error("Live summary error: %s", exc)
        return {"starting_capital": 100, "current_equity": 100, "error": str(exc)}


@app.get("/api/settings", dependencies=[Depends(verify_auth)])
def get_settings():
    """Return current config values (safe subset only)."""
    return {
        "risk": {
            "max_position_pct": 0.25,
            "max_open_positions": 50,
            "max_sector_pct": 0.22,
        },
        "bootcamp": {
            "max_packets_per_scan": 20,
            "min_score": 40,
        },
        "trading": {
            "email_mode": "daily_summary",
        },
        "schedule": {
            "between_scan_scoring": True,
            "overnight_schedule": True,
        },
        "system": {
            "model_version": "halcyonlatest",
            "python_version": "3.12",
            "environment": "cloud",
        },
    }


@app.post("/api/settings", dependencies=[Depends(verify_auth)])
def update_settings():
    """Update config values. Cloud mode: not available."""
    return {"error": "cloud_mode", "message": "Settings can only be changed on the local machine."}


@app.post("/api/live/reconcile", dependencies=[Depends(verify_auth)])
def live_reconcile():
    """Trigger live trade reconciliation. Must be run locally."""
    return {"error": "cloud_mode", "message": "Reconciliation must be run locally via CLI: python -m src.main reconcile-live"}


@app.get("/api/shadow/account", dependencies=[Depends(verify_auth)])
def shadow_account():
    """Shadow trading account summary."""
    try:
        open_trades = _query(
            "SELECT entry_price, planned_shares, pnl_dollars FROM shadow_trades WHERE status = 'open'"
        )
        closed_trades = _query(
            "SELECT pnl_dollars, pnl_pct FROM shadow_trades WHERE status = 'closed'"
        )
        starting_capital = 100000
        closed_pnl = sum(t.get("pnl_dollars", 0) or 0 for t in closed_trades)
        open_alloc = sum((t.get("entry_price", 0) or 0) * (t.get("planned_shares", 0) or 0) for t in open_trades)

        wins = [t for t in closed_trades if (t.get("pnl_dollars", 0) or 0) > 0]
        losses = [t for t in closed_trades if (t.get("pnl_dollars", 0) or 0) <= 0]

        return {
            "starting_capital": starting_capital,
            "equity": starting_capital + closed_pnl,
            "cash": starting_capital + closed_pnl - open_alloc,
            "open_positions": len(open_trades),
            "closed_pnl": round(closed_pnl, 2),
            "unrealized_pnl": 0,
            "win_rate": round(len(wins) / len(closed_trades), 3) if closed_trades else None,
            "total_closed": len(closed_trades),
            "wins": len(wins),
            "losses": len(losses),
        }
    except Exception as exc:
        logger.error("[API] shadow_account failed: %s", exc, exc_info=True)
        return {"starting_capital": 100000, "equity": 100000, "error": str(exc)}


@app.get("/api/cto-report", dependencies=[Depends(verify_auth)])
def cto_report(days: int = 7):
    """Generate CTO report from cloud data."""
    try:
        cutoff = (datetime.now(ET) - timedelta(days=days)).isoformat()

        open_count = _query_one("SELECT COUNT(*) as c FROM shadow_trades WHERE status = 'open'")
        closed_recent = _query(
            "SELECT ticker, pnl_dollars, pnl_pct, exit_reason FROM shadow_trades "
            "WHERE status = 'closed' AND actual_exit_time >= %s ORDER BY actual_exit_time DESC",
            (cutoff,),
        )
        packet_count = _query_one("SELECT COUNT(*) as c FROM recommendations WHERE created_at >= %s", (cutoff,))
        latest_audit = _query_one("SELECT overall_assessment, summary FROM audit_reports ORDER BY created_at DESC LIMIT 1")

        # Compute basic KPIs
        pnls = [t.get("pnl_pct", 0) or 0 for t in closed_recent]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p <= 0]
        win_rate = len(wins) / len(pnls) if pnls else 0
        total_pnl = sum(t.get("pnl_dollars", 0) or 0 for t in closed_recent)

        # Compute Sharpe from trade returns
        import statistics
        sharpe = 0
        if len(pnls) >= 2:
            avg_r = statistics.mean(pnls)
            std_r = statistics.stdev(pnls)
            sharpe = round(avg_r / std_r, 3) if std_r > 0 else 0

        # Profit factor
        gross_wins = sum(wins) if wins else 0
        gross_losses = abs(sum(losses)) if losses else 0
        profit_factor = round(gross_wins / gross_losses, 2) if gross_losses > 0 else (999 if gross_wins > 0 else 0)

        # Max drawdown from cumulative P&L
        max_dd = 0
        if pnls:
            cumulative = 0
            peak = 0
            for p in pnls:
                cumulative += p
                peak = max(peak, cumulative)
                dd = peak - cumulative
                max_dd = max(max_dd, dd)

        # Expectancy per trade
        expectancy = round(total_pnl / len(closed_recent), 2) if closed_recent else 0

        return {
            "report_period": {
                "start": cutoff[:10],
                "end": datetime.now(ET).strftime("%Y-%m-%d"),
            },
            "headline_kpis": {
                "sharpe_ratio": sharpe,
                "win_rate": win_rate,
                "max_drawdown_pct": round(max_dd, 2),
                "confidence_calibration": 0,
                "avg_rubric_score": None,
            },
            "trade_summary": {
                "trades_closed": len(closed_recent),
                "trades_open": open_count["c"] if open_count else 0,
                "win_rate": win_rate,
                "sharpe_ratio": sharpe,
                "profit_factor": profit_factor,
                "expectancy_dollars": expectancy,
                "max_drawdown_pct": round(max_dd, 2),
                "total_pnl": round(total_pnl, 2),
                "avg_winner_pct": round(sum(wins) / len(wins), 1) if wins else None,
                "avg_loser_pct": round(sum(losses) / len(losses), 1) if losses else None,
                "max_consecutive_losses": 0,
            },
            "fund_metrics": {
                "psr": None,
                "calmar_ratio": None,
                "dsr": None,
                "information_ratio": None,
            },
            "system_status": {
                "model_version": "cloud",
                "dataset_size": 0,
            },
            "period_days": days,
            "packets_generated": packet_count["c"] if packet_count else 0,
            "latest_audit": latest_audit,
            "generated_at": datetime.now(ET).isoformat(),
        }
    except Exception as exc:
        logger.error("[API] cto_report failed: %s", exc, exc_info=True)
        return {"error": str(exc)}


@app.get("/api/scan/latest", dependencies=[Depends(verify_auth)])
def scan_latest():
    """Latest scan results."""
    try:
        latest = _query(
            "SELECT * FROM recommendations ORDER BY created_at DESC LIMIT 10"
        )
        return {"recommendations": latest, "count": len(latest)}
    except Exception as exc:
        logger.error("[API] scan_latest failed: %s", exc, exc_info=True)
        return {"recommendations": [], "count": 0, "error": str(exc)}


@app.get("/api/review/pending", dependencies=[Depends(verify_auth)])
def review_pending():
    """Trades pending review."""
    try:
        rows = _query(
            "SELECT * FROM shadow_trades WHERE status = 'closed' "
            "AND (exit_reason IS NOT NULL) ORDER BY actual_exit_time DESC LIMIT 20"
        )
        return rows
    except Exception as exc:
        logger.error("[API] review_pending failed: %s", exc, exc_info=True)
        return []


@app.get("/api/review/scorecard", dependencies=[Depends(verify_auth)])
def review_scorecard(weeks: int = 4):
    """Review scorecard."""
    return {"weeks": weeks, "scorecard": []}


@app.get("/api/review/postmortems", dependencies=[Depends(verify_auth)])
def review_postmortems():
    """Recent postmortems."""
    return []


@app.get("/api/audit/history", dependencies=[Depends(verify_auth)])
def audit_history(days: int = 30):
    """Audit report history."""
    try:
        cutoff = (datetime.now(ET) - timedelta(days=days)).isoformat()
        rows = _query(
            "SELECT * FROM audit_reports WHERE created_at >= %s ORDER BY created_at DESC",
            (cutoff,),
        )
        return rows
    except Exception as exc:
        logger.error("[API] audit_history failed: %s", exc, exc_info=True)
        return []


@app.get("/api/training/report", dependencies=[Depends(verify_auth)])
def training_report():
    """Training pipeline report."""
    try:
        total = _query_one("SELECT COUNT(*) as c FROM training_examples")
        scored = _query_one("SELECT COUNT(*) as c FROM training_examples WHERE quality_score IS NOT NULL")
        avg_score = _query_one("SELECT AVG(quality_score) as avg FROM training_examples WHERE quality_score IS NOT NULL")
        return {
            "total_examples": total["c"] if total else 0,
            "scored": scored["c"] if scored else 0,
            "unscored": (total["c"] if total else 0) - (scored["c"] if scored else 0),
            "avg_quality_score": round(avg_score["avg"], 2) if avg_score and avg_score["avg"] else None,
        }
    except Exception as exc:
        logger.error("[API] training_report failed: %s", exc, exc_info=True)
        return {"total_examples": 0, "scored": 0, "unscored": 0, "error": str(exc)}


@app.get("/api/metric-history", dependencies=[Depends(verify_auth)])
def metric_history(days: int = 90):
    """Alias for metrics/history — some frontend pages use this path."""
    return metrics_history(days)


# ── POST action stubs (cloud mode) ──────────────────────────────

CLOUD_ACTION_MSG = {"error": "cloud_mode", "message": "This action is only available on the local dashboard."}


@app.post("/api/actions/scan", dependencies=[Depends(verify_auth)])
def action_scan():
    return CLOUD_ACTION_MSG


@app.post("/api/actions/cto-report", dependencies=[Depends(verify_auth)])
def action_cto_report():
    return CLOUD_ACTION_MSG


@app.post("/api/actions/collect-training", dependencies=[Depends(verify_auth)])
def action_collect_training():
    return CLOUD_ACTION_MSG


@app.post("/api/actions/train-pipeline", dependencies=[Depends(verify_auth)])
def action_train_pipeline():
    return CLOUD_ACTION_MSG


@app.post("/api/actions/score", dependencies=[Depends(verify_auth)])
def action_score():
    return CLOUD_ACTION_MSG


@app.post("/api/actions/council", dependencies=[Depends(verify_auth)])
def action_council():
    return CLOUD_ACTION_MSG


@app.post("/api/halt-trading", dependencies=[Depends(verify_auth)])
def halt_trading():
    return CLOUD_ACTION_MSG


@app.post("/api/resume-trading", dependencies=[Depends(verify_auth)])
def resume_trading():
    return CLOUD_ACTION_MSG


@app.post("/api/training/train", dependencies=[Depends(verify_auth)])
def action_train():
    return CLOUD_ACTION_MSG


@app.post("/api/training/bootstrap", dependencies=[Depends(verify_auth)])
def action_bootstrap():
    return CLOUD_ACTION_MSG


@app.post("/api/training/rollback", dependencies=[Depends(verify_auth)])
def action_rollback():
    return CLOUD_ACTION_MSG


@app.post("/api/shadow/close/{ticker}", dependencies=[Depends(verify_auth)])
def action_close_trade(ticker: str):
    return CLOUD_ACTION_MSG


# ── Additional GET endpoints ─────────────────────────────────────


@app.get("/api/market/overview", dependencies=[Depends(verify_auth)])
def market_overview():
    """Market overview — VIX, regime, macro summary."""
    try:
        vix = _query_one("SELECT * FROM vix_term_structure ORDER BY collected_date DESC LIMIT 1")
        macro = _query(
            "SELECT series_id, series_name, value, change_pct FROM macro_snapshots "
            "WHERE collected_date = (SELECT MAX(collected_date) FROM macro_snapshots)"
        )
        return {"vix": vix, "macro": macro}
    except Exception as exc:
        logger.error("[API] market_overview failed: %s", exc, exc_info=True)
        return {"vix": None, "macro": [], "error": str(exc)}


@app.get("/api/data-asset/growth", dependencies=[Depends(verify_auth)])
def data_asset_growth():
    """Data asset growth over time."""
    try:
        rows = _query(
            "SELECT DATE(created_at) as date, COUNT(*) as count "
            "FROM training_examples GROUP BY DATE(created_at) ORDER BY date"
        )
        return {"daily_counts": rows}
    except Exception as exc:
        logger.error("[API] data_asset_growth failed: %s", exc, exc_info=True)
        return {"daily_counts": [], "error": str(exc)}


@app.get("/api/journal", dependencies=[Depends(verify_auth)])
def trade_journal(days: int = 90):
    """Trade journal — closed trades with recommendation context."""
    try:
        cutoff = (datetime.now(ET) - timedelta(days=days)).isoformat()
        rows = _query(
            "SELECT st.*, r.thesis_text, r.setup_type "
            "FROM shadow_trades st LEFT JOIN recommendations r "
            "ON st.recommendation_id = r.recommendation_id "
            "WHERE st.status = 'closed' AND st.actual_exit_time >= %s "
            "ORDER BY st.actual_exit_time DESC",
            (cutoff,),
        )
        return {"trades": rows, "count": len(rows)}
    except Exception as exc:
        return {"trades": [], "count": 0, "error": str(exc)}


@app.get("/api/signal-zoo", dependencies=[Depends(verify_auth)])
def signal_zoo(days: int = 7):
    """Signal zoo — setup signals with optional filters."""
    try:
        cutoff = (datetime.now(ET) - timedelta(days=days)).isoformat()
        rows = _query(
            "SELECT * FROM setup_signals WHERE created_at >= %s ORDER BY created_at DESC",
            (cutoff,),
        )
        for r in rows:
            _parse_json_fields(r, ["features_json"])
        return {"signals": rows, "count": len(rows)}
    except Exception as exc:
        logger.error("[API] signal_zoo failed: %s", exc, exc_info=True)
        return {"signals": [], "count": 0, "error": str(exc)}


@app.get("/api/macro/dashboard", dependencies=[Depends(verify_auth)])
def macro_dashboard():
    """Macro dashboard — latest values for each FRED series."""
    try:
        rows = _query(
            "SELECT DISTINCT ON (series_id) series_id, series_name, value, "
            "previous_value, change_pct, collected_date "
            "FROM macro_snapshots ORDER BY series_id, collected_date DESC"
        )
        return {"series": rows}
    except Exception as exc:
        logger.error("[API] macro_dashboard failed: %s", exc, exc_info=True)
        return {"series": [], "error": str(exc)}


@app.get("/api/research/papers", dependencies=[Depends(verify_auth)])
def research_papers(days: int = 7, min_score: float = 0.4):
    """Recent research papers."""
    try:
        cutoff = (datetime.now(ET) - timedelta(days=days)).isoformat()
        rows = _query(
            "SELECT id, source, title, authors, abstract, url, published_date, "
            "relevance_score, relevance_reason, actionable, collected_at "
            "FROM research_papers WHERE collected_at >= %s AND relevance_score >= %s "
            "ORDER BY relevance_score DESC",
            (cutoff, min_score),
        )
        return {"papers": rows, "count": len(rows)}
    except Exception as exc:
        logger.error("[API] research_papers failed: %s", exc, exc_info=True)
        return {"papers": [], "count": 0, "error": str(exc)}


@app.get("/api/research/digest", dependencies=[Depends(verify_auth)])
def research_digest():
    """Latest weekly research digest."""
    try:
        row = _query_one(
            "SELECT * FROM research_digests ORDER BY created_at DESC LIMIT 1"
        )
        return row or {"digest": None}
    except Exception as exc:
        logger.error("[API] research_digest failed: %s", exc, exc_info=True)
        return {"digest": None, "error": str(exc)}


@app.get("/api/training/quality", dependencies=[Depends(verify_auth)])
def training_quality():
    """Training data quality stats."""
    try:
        total = _query_one("SELECT COUNT(*) as c FROM training_examples")
        by_source = _query(
            "SELECT source, COUNT(*) as count FROM training_examples GROUP BY source"
        )
        by_stage = _query(
            "SELECT curriculum_stage, COUNT(*) as count FROM training_examples GROUP BY curriculum_stage"
        )
        by_outcome = _query(
            "SELECT outcome, COUNT(*) as count FROM training_examples GROUP BY outcome"
        )
        return {
            "total": total["c"] if total else 0,
            "by_source": by_source,
            "by_stage": by_stage,
            "by_outcome": by_outcome,
        }
    except Exception as exc:
        logger.error("[API] training_quality failed: %s", exc, exc_info=True)
        return {"total": 0, "by_source": [], "by_stage": [], "by_outcome": [], "error": str(exc)}


@app.get("/api/scan/metrics", dependencies=[Depends(verify_auth)])
def scan_metrics_latest():
    """Latest scan pipeline metrics."""
    try:
        row = _query_one(
            "SELECT * FROM scan_metrics ORDER BY created_at DESC LIMIT 1"
        )
        return row or {}
    except Exception as exc:
        logger.error("[API] scan_metrics_latest failed: %s", exc, exc_info=True)
        return {"error": str(exc)}


@app.get("/api/projections/live", dependencies=[Depends(verify_auth)])
def projections_live():
    """Live performance metrics for the revenue projection model."""
    try:
        closed = _query(
            "SELECT pnl_dollars, pnl_pct FROM shadow_trades "
            "WHERE status = 'closed' AND pnl_pct IS NOT NULL "
            "ORDER BY actual_exit_time ASC"
        )
        if not closed:
            return {"trades": 0}

        pnl_pcts = [float(r.get("pnl_pct", 0) or 0) for r in closed]
        pnl_dollars = [float(r.get("pnl_dollars", 0) or 0) for r in closed]
        wins = [p for p in pnl_dollars if p > 0]
        losses = [p for p in pnl_dollars if p <= 0]

        import statistics
        avg_return = statistics.mean(pnl_pcts) if pnl_pcts else 0
        std_return = statistics.stdev(pnl_pcts) if len(pnl_pcts) > 1 else 1
        sharpe = avg_return / std_return if std_return > 0 else 0

        # Max drawdown from equity curve
        equity = []
        cumulative = 100000
        peak = cumulative
        max_dd = 0
        for pnl in pnl_dollars:
            cumulative += pnl
            equity.append(cumulative)
            peak = max(peak, cumulative)
            dd = (peak - cumulative) / peak * 100 if peak > 0 else 0
            max_dd = max(max_dd, dd)

        pf = abs(sum(wins) / sum(losses)) if losses and sum(losses) != 0 else 0

        return {
            "trades": len(closed),
            "winRate": round(len(wins) / len(closed), 3) if closed else 0,
            "sharpe": round(sharpe, 3),
            "profitFactor": round(pf, 2),
            "maxDD": round(max_dd, 1),
            "netPnl": round(sum(pnl_dollars), 2),
            "avgReturn": round(avg_return, 3),
        }
    except Exception as exc:
        return {"trades": 0, "error": str(exc)}
