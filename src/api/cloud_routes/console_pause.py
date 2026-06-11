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

import logging
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

router = APIRouter()
logger = logging.getLogger(__name__)


def verify_auth() -> None:
    """Local placeholder; app.dependency_overrides[verify_auth] swaps in real auth."""
    return None


class _PauseRequest(BaseModel):
    action: Literal["pause", "resume"]
    reason: Optional[str] = None


@router.get("/console/pause", dependencies=[Depends(verify_auth)])
def get_pause_status() -> dict:
    """Return the canonical pause state envelope.

    On a source failure (e.g. the cutover Postgres unreachable) this degrades to
    an explicit ``state="unavailable"`` envelope with ``is_paused=None`` (HTTP
    200), never a 500 — design law #4 (the sole console UI must not break on a DB
    hiccup). ``is_paused`` is None (unknown), NOT False: a false "RUNNING" on a
    missing source is the never-green-on-missing violation. The scan/executor
    gate ``is_paused()`` independently fails CLOSED, so a paused desk never
    silently resumes while the source is down. Regression: 2026-06-11 PG-down.
    """
    from src.console.pause import read_pause_state

    try:
        return read_pause_state()
    except Exception as exc:  # noqa: BLE001 — any source failure -> honest unknown
        logger.warning("[console-pause] pause state source unavailable: %s", exc)
        return {
            "is_paused": None,
            "state": "unavailable",
            "paused_at": None,
            "paused_by": None,
            "reason": None,
            "resumed_at": None,
            "updated_at": None,
            "detail": "pause state source unavailable; the scan/executor gate "
                      "fails closed until it recovers",
        }


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
