"""Notes CRUD API routes (local mode, SQLite).

Called by: api.app
Calls: none
Owns tables: none (reads/writes user_notes)
Config keys: none
Tests: tests/test_local_routes.py
"""

import json
import logging
import sqlite3
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from src.config import DB_PATH

router = APIRouter(tags=["notes"])
logger = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")


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


def _normalize_tags(tags) -> list[str]:
    """Accept list or comma-separated string, return list."""
    if isinstance(tags, list):
        return tags
    if isinstance(tags, str):
        return [t.strip() for t in tags.split(",") if t.strip()]
    return []


def _parse_note(row: dict) -> dict:
    """Parse a note row into the API response shape."""
    tags = row.get("tags", "[]")
    if isinstance(tags, str):
        try:
            tags = json.loads(tags)
        except (json.JSONDecodeError, TypeError):
            tags = []
    return {
        "note_id": row["note_id"],
        "title": row["title"],
        "content": row["content"],
        "tags": tags if isinstance(tags, list) else [],
        "pinned": bool(row.get("pinned")),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


@router.get("/notes")
def list_notes():
    """List all notes, pinned first."""
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                "SELECT * FROM user_notes ORDER BY pinned DESC, updated_at DESC"
            ).fetchall()
            return {"notes": [_parse_note(dict(r)) for r in rows]}
        finally:
            conn.close()
    except Exception as exc:
        logger.error("[API] notes list failed: %s", exc)
        return {"notes": [], "error": str(exc)}


@router.post("/notes", status_code=201)
def create_note(payload: NoteCreatePayload):
    """Create a new note."""
    try:
        now = datetime.now(ET).isoformat()
        note_id = str(uuid.uuid4())
        tags_json = json.dumps(_normalize_tags(payload.tags))
        conn = sqlite3.connect(DB_PATH)
        try:
            conn.execute(
                "INSERT INTO user_notes "
                "(note_id, title, content, tags, pinned, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (note_id, payload.title or "Untitled Note",
                 payload.content or "", tags_json,
                 1 if payload.pinned else 0, now, now),
            )
            conn.commit()
        finally:
            conn.close()
        return _parse_note({
            "note_id": note_id,
            "title": payload.title or "Untitled Note",
            "content": payload.content or "",
            "tags": tags_json,
            "pinned": payload.pinned,
            "created_at": now,
            "updated_at": now,
        })
    except Exception as exc:
        logger.error("[API] note create failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.put("/notes/{note_id}")
def update_note(note_id: str, payload: NoteUpdatePayload):
    """Update an existing note."""
    try:
        updates = payload.model_dump(exclude_unset=True)
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        try:
            if not updates:
                existing = conn.execute(
                    "SELECT * FROM user_notes WHERE note_id = ?", (note_id,)
                ).fetchone()
                if not existing:
                    raise HTTPException(status_code=404, detail="Note not found")
                return _parse_note(dict(existing))

            fields = []
            values = []
            if "title" in updates:
                fields.append("title = ?")
                values.append(updates["title"] or "Untitled Note")
            if "content" in updates:
                fields.append("content = ?")
                values.append(updates["content"] or "")
            if "tags" in updates:
                fields.append("tags = ?")
                values.append(json.dumps(_normalize_tags(updates["tags"])))
            if "pinned" in updates:
                fields.append("pinned = ?")
                values.append(1 if updates["pinned"] else 0)
            fields.append("updated_at = ?")
            values.append(datetime.now(ET).isoformat())
            values.append(note_id)

            cursor = conn.execute(
                f"UPDATE user_notes SET {', '.join(fields)} WHERE note_id = ?",
                tuple(values),
            )
            if cursor.rowcount == 0:
                raise HTTPException(status_code=404, detail="Note not found")
            conn.commit()

            updated = conn.execute(
                "SELECT * FROM user_notes WHERE note_id = ?", (note_id,)
            ).fetchone()
            return _parse_note(dict(updated))
        finally:
            conn.close()
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("[API] note update failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.delete("/notes/{note_id}", status_code=204)
def delete_note(note_id: str):
    """Delete a note by ID."""
    try:
        conn = sqlite3.connect(DB_PATH)
        try:
            cursor = conn.execute(
                "DELETE FROM user_notes WHERE note_id = ?", (note_id,)
            )
            if cursor.rowcount == 0:
                raise HTTPException(status_code=404, detail="Note not found")
            conn.commit()
        finally:
            conn.close()
        return None
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("[API] note delete failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))
