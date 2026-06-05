"""PAUSE status and toggle endpoints for the Founder Console (T5).

Called by: src.api.app (router registered at /api/console/pause)
Calls: src.console.pause (read_pause_state, set_pause, clear_pause)
Owns tables: none (delegates entirely to src.console.pause)
Config keys: none
Tests: tests/api/test_console_pause_route.py

Thin HTTP surface only — pause logic lives in src.console.pause (T4).
Audit logging is handled by the T4 engine; this router does not duplicate it.
"""
from __future__ import annotations

from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

router = APIRouter()


def verify_auth() -> None:
    """Local placeholder; app.dependency_overrides[verify_auth] swaps in real auth."""
    return None


class _PauseRequest(BaseModel):
    action: Literal["pause", "resume"]
    reason: Optional[str] = None


@router.get("/console/pause", dependencies=[Depends(verify_auth)])
def get_pause_status() -> dict:
    """Return the canonical pause state envelope."""
    from src.console.pause import read_pause_state
    return read_pause_state()


@router.post("/console/pause", dependencies=[Depends(verify_auth)])
def post_pause_toggle(body: _PauseRequest) -> dict:
    """Engage or clear the graceful pause.

    action='pause'  → calls set_pause(reason, source='api')
    action='resume' → calls clear_pause(source='api')

    Returns the canonical state from read_pause_state() after the mutation.
    """
    from src.console.pause import clear_pause, read_pause_state, set_pause

    source = "api"
    if body.action == "pause":
        set_pause(reason=body.reason or "", source=source)
    else:
        clear_pause(source=source)

    return read_pause_state()
