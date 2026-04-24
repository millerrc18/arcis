"""Local-API auth dependency (#576).

Pre-#576, all 7 POST endpoints in src/api/routes/actions.py were
unauthenticated. Mitigation existed at the network layer (127.0.0.1
binding) but there was no route-level gate. The audit flagged this as a
defense-in-depth gap.

This module provides an OPT-IN local token dep:

- If `ARCIS_LOCAL_API_TOKEN` env var is unset (default), `verify_local_token`
  is a no-op — preserves the existing localhost-only mode for the dashboard.
- If `ARCIS_LOCAL_API_TOKEN` is set, the dep requires clients to send
  `Authorization: Bearer <token>` matching exactly (constant-time compare).

This means the operator can flip on hardening without changing route code or
breaking the localhost dashboard.
"""

from __future__ import annotations

import hmac
import os

from fastapi import Header, HTTPException


def verify_local_token(authorization: str | None = Header(default=None)) -> None:
    """FastAPI dependency that enforces a local-API bearer token if configured.

    Reads `ARCIS_LOCAL_API_TOKEN` from the environment at each request so
    operators can rotate the token without restarting the service.
    """
    expected = os.environ.get("ARCIS_LOCAL_API_TOKEN", "").strip()
    if not expected:
        # Opt-in mode: no token configured → no-op (preserves pre-#576 behavior).
        return
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=401,
            detail="Missing Authorization: Bearer <token> header",
        )
    presented = authorization.split(None, 1)[1].strip()
    if not hmac.compare_digest(presented, expected):
        raise HTTPException(status_code=401, detail="Invalid local API token")
