"""Cloud notes routes and payload models for the Notes dashboard.

Called by: api.cloud_app
Calls: none
Owns tables: none
Config keys: none
Tests: none

Endpoints:
    GET    /api/notes           - List all notes (pinned first)
    POST   /api/notes           - Create note
    PUT    /api/notes/{id}      - Update note
    DELETE /api/notes/{id}      - Delete note

Notes are the only entity that supports full CRUD directly in Postgres
(not via command queue). This is because notes are user content, not system
actions — there's no GPU or local-only dependency. The ensure_user_notes_table()
call on every request is defensive: the sync thread creates the table, but
if someone accesses notes before the first sync, the table might not exist yet.
"""

import json
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field


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


def create_router(runtime, verify_auth):
    """Build the cloud notes router."""
    router = APIRouter()

    @router.get("/api/notes", dependencies=[Depends(verify_auth)])
    def list_notes():
        try:
            runtime.ensure_user_notes_table()
            rows = runtime.query(
                "SELECT * FROM user_notes ORDER BY pinned DESC, updated_at DESC"
            )
            return {"notes": [runtime.parse_note_row(row) for row in rows]}
        except HTTPException:
            raise
        except Exception as exc:
            runtime.logger.error("[API] notes list failed: %s", exc)
            return {"notes": [], "error": str(exc)}

    @router.post("/api/notes", status_code=201, dependencies=[Depends(verify_auth)])
    def create_note(payload: NoteCreatePayload):
        try:
            runtime.ensure_user_notes_table()
            now = datetime.now(runtime.et).isoformat()
            note_id = str(uuid.uuid4())
            tags_json = json.dumps(runtime.normalize_tags(payload.tags))
            with runtime.get_pg(readonly=False) as conn:
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
            return runtime.parse_note_row(
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
            runtime.logger.error("[API] note create failed: %s", exc)
            raise HTTPException(status_code=500, detail=str(exc))

    @router.put("/api/notes/{note_id}", dependencies=[Depends(verify_auth)])
    def update_note(note_id: str, payload: NoteUpdatePayload):
        try:
            runtime.ensure_user_notes_table()
            updates = payload.model_dump(exclude_unset=True)
            if not updates:
                existing = runtime.query_one(
                    "SELECT * FROM user_notes WHERE note_id = %s",
                    (note_id,),
                )
                if not existing:
                    raise HTTPException(status_code=404, detail="Note not found")
                return runtime.parse_note_row(existing)

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
                values.append(json.dumps(runtime.normalize_tags(updates["tags"])))
            if "pinned" in updates:
                fields.append("pinned = %s")
                values.append(1 if updates["pinned"] else 0)
            fields.append("updated_at = %s")
            values.append(datetime.now(runtime.et).isoformat())
            values.append(note_id)

            with runtime.get_pg(readonly=False) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        f"UPDATE user_notes SET {', '.join(fields)} WHERE note_id = %s",
                        tuple(values),
                    )
                    if cur.rowcount == 0:
                        raise HTTPException(status_code=404, detail="Note not found")
                    conn.commit()

            updated = runtime.query_one(
                "SELECT * FROM user_notes WHERE note_id = %s",
                (note_id,),
            )
            if not updated:
                raise HTTPException(status_code=404, detail="Note not found")
            return runtime.parse_note_row(updated)
        except HTTPException:
            raise
        except Exception as exc:
            runtime.logger.error("[API] note update failed: %s", exc)
            raise HTTPException(status_code=500, detail=str(exc))

    @router.delete("/api/notes/{note_id}", status_code=204, dependencies=[Depends(verify_auth)])
    def delete_note(note_id: str):
        try:
            runtime.ensure_user_notes_table()
            with runtime.get_pg(readonly=False) as conn:
                with conn.cursor() as cur:
                    cur.execute("DELETE FROM user_notes WHERE note_id = %s", (note_id,))
                    if cur.rowcount == 0:
                        raise HTTPException(status_code=404, detail="Note not found")
                    conn.commit()
            return None
        except HTTPException:
            raise
        except Exception as exc:
            runtime.logger.error("[API] note delete failed: %s", exc)
            raise HTTPException(status_code=500, detail=str(exc))

    return router
