"""Cloud API route for command lifecycle operations.

Called by: api.cloud_app
Calls: src.commands.maintenance.expire_stale_commands
Owns tables: none (mutates pending_commands.status)
Config keys: none
Tests: tests/api/test_commands_route.py

Endpoints:
    POST /api/commands/expire-stale  - Sweep aged pending_commands

Mirrors the local-mode endpoint at src/api/routes/logs.py:177 so the
dashboard's "Clear stale" button works against both local FastAPI and
the cloud Render deployment. Tier 1.E of the #807 dashboard audit (#54).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException


def create_router(runtime, verify_auth):
    """Build the commands router."""
    router = APIRouter()

    @router.post("/api/commands/expire-stale", dependencies=[Depends(verify_auth)])
    def expire_stale_commands_endpoint():
        """Sweep aged pending_commands rows; mark them 'expired'.

        Returns {"expired": N} where N is the count of rows transitioned this
        call (0 is the steady-state).
        """
        try:
            from src.commands.maintenance import expire_stale_commands
            count = expire_stale_commands()
            return {"expired": count}
        except Exception as exc:
            runtime.logger.error("/api/commands/expire-stale failed: %s", exc)
            raise HTTPException(status_code=500, detail=str(exc))

    return router
