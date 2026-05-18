"""FastAPI application for the Arcis dashboard.

Called by: none (entry point)
Calls: api.routes, api.websocket, journal.store, log_config
Owns tables: none
Config keys: API_SECRET (env)
Tests: tests/api/test_app.py

Authentication
--------------

Pre-cutover (≤ 2026-05-09): this app bound to 127.0.0.1 only and ran without
auth. Cloud_app.py (deployed on Render) handled all internet-facing traffic
behind API_SECRET-based bearer-token auth.

Post-cutover (≥ 2026-05-10): this app is exposed to the public internet via
Cloudflare Tunnel (`halcyonlab.app` → `localhost:8000`). Every API route now
requires bearer-token authentication (the `verify_auth` dependency below).
The token model + hash-or-plaintext compare is lifted verbatim from
cloud_app.py:153-176 to preserve the behavior the frontend already knows
how to talk to (frontend reads VITE_API_SECRET and sends as Authorization
header).

`/healthz` is intentionally exempt from auth — used by curl smoke tests
during the cutover and by any future external monitoring.

The /ws/live WebSocket is NOT yet authenticated. Tracking as a follow-up
once the HTTP cutover is verified stable.
"""
import hashlib
import hmac
import os
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from src.api.cloud_routes import broker_exceptions as broker_exceptions_route
from src.api.cloud_routes import kpis as kpis_route
from src.api.cloud_routes import notifications as notifications_route
from src.api.cloud_routes import platform as platform_module
from src.api.cloud_routes import preflight as preflight_route
from src.api.cloud_routes import walkforward as walkforward_module
from src.api.routes import (
    actions,
    council,
    diagnostic,
    docs,
    health,
    ib_shadow,
    ib_status,
    live,
    logs,
    notes,
    packets,
    projections,
    review,
    scan,
    shadow,
    strategy_detail,
    system,
    system_index,
    training,
)
from src.api.websocket import manager
from src.version import VERSION


API_SECRET = os.environ.get("API_SECRET", "")


def _sha256_hex(value: str) -> str:
    """Compute SHA-256 hex digest of a string."""
    return hashlib.sha256(value.encode()).hexdigest()


# Pre-compute on import for constant-time comparison; keeps verify_auth cheap.
_API_SECRET_HASH = _sha256_hex(API_SECRET) if API_SECRET else ""

security = HTTPBearer(auto_error=False)


def verify_auth(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> None:
    """Verify bearer token if API_SECRET is set.

    Accepts both the SHA-256 hashed token (from frontend AuthGate) and
    the raw plaintext secret (for backward compatibility / curl usage).
    Lifted verbatim from cloud_app.py:153-176 — when both apps coexisted
    they shared this exact behavior; preserving it for the cutover means
    the frontend (which sends `Authorization: Bearer <hashed>`) keeps
    working without a rebuild for the auth model.
    """
    if not API_SECRET:
        raise RuntimeError(
            "API_SECRET env var must be set — refusing to serve without authentication. "
            "Set API_SECRET in your environment variables."
        )
    if not credentials:
        raise HTTPException(status_code=401, detail="Invalid or missing API token")
    token = credentials.credentials
    # #440 — hmac.compare_digest is constant-time; prevents timing attacks
    # against the bearer token (regular `==` short-circuits on first mismatch).
    if (hmac.compare_digest(token, _API_SECRET_HASH)
            or hmac.compare_digest(token, API_SECRET)):
        return
    raise HTTPException(status_code=401, detail="Invalid or missing API token")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Startup/shutdown hook replacing the deprecated on_event("startup")."""
    from src.journal.store import initialize_database
    from src.log_config import setup_logging
    setup_logging()
    initialize_database()
    yield


app = FastAPI(title="Arcis", version=VERSION.lstrip("v"), lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    # localhost:5173 / :3000 are the frontend dev server origins. Production
    # serves from same-origin (StaticFiles mount below) so CORS doesn't apply.
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/healthz")
def healthz():
    """Unauthenticated health probe — used by curl smoke tests + external monitoring."""
    return {"status": "ok"}


# Native local routers — bare include calls historically; now require auth
# at the include_router level since the tunnel exposes them publicly.
_AUTH_DEP = [Depends(verify_auth)]
app.include_router(system.router, prefix="/api", dependencies=_AUTH_DEP)
app.include_router(scan.router, prefix="/api", dependencies=_AUTH_DEP)
app.include_router(shadow.router, prefix="/api", dependencies=_AUTH_DEP)
app.include_router(training.router, prefix="/api", dependencies=_AUTH_DEP)
app.include_router(review.router, prefix="/api", dependencies=_AUTH_DEP)
app.include_router(packets.router, prefix="/api", dependencies=_AUTH_DEP)
app.include_router(docs.router, prefix="/api", dependencies=_AUTH_DEP)
app.include_router(actions.router, prefix="/api", dependencies=_AUTH_DEP)
app.include_router(health.router, prefix="/api", dependencies=_AUTH_DEP)
app.include_router(council.router, prefix="/api", dependencies=_AUTH_DEP)
app.include_router(notes.router, prefix="/api", dependencies=_AUTH_DEP)
app.include_router(live.router, prefix="/api", dependencies=_AUTH_DEP)
app.include_router(logs.router, prefix="/api", dependencies=_AUTH_DEP)
app.include_router(ib_status.router, prefix="/api", dependencies=_AUTH_DEP)
app.include_router(ib_shadow.router, prefix="/api", dependencies=_AUTH_DEP)
app.include_router(strategy_detail.router, prefix="/api", dependencies=_AUTH_DEP)
app.include_router(system_index.router, dependencies=_AUTH_DEP)
app.include_router(projections.router, prefix="/api", dependencies=_AUTH_DEP)
app.include_router(diagnostic.router, prefix="/api", dependencies=_AUTH_DEP)

# cloud_routes/* routers each define a placeholder `verify_auth` dependency
# at route-level (e.g. `@router.get("/api/x", dependencies=[Depends(verify_auth)])`).
# Override the placeholder with the real one before mounting. This is the
# same pattern cloud_app.py uses (cloud_app.py:316-340) and avoids circular
# import between this module and cloud_routes.*.
for route_module in (
    kpis_route,
    broker_exceptions_route,
    preflight_route,
    notifications_route,
    platform_module,
    walkforward_module,
):
    app.dependency_overrides[route_module.verify_auth] = verify_auth

app.include_router(kpis_route.router, prefix="/api")
app.include_router(broker_exceptions_route.router, prefix="/api")
app.include_router(preflight_route.router, prefix="/api")
app.include_router(notifications_route.router, prefix="/api")
# platform + walkforward routers carry their own /api prefix in their @router.get
# decorators, so include them WITHOUT prefix (matches cloud_app.py:330, 341).
app.include_router(platform_module.router)
app.include_router(walkforward_module.router)


# WebSocket for live updates (uses shared manager from websocket.py).
#
# Auth: token query-parameter — `wss://halcyonlab.app/ws/live?token=<api_secret>`.
# WebSockets don't support bearer headers cleanly (browser WebSocket API doesn't
# expose a way to set custom request headers), so we use the standard query-
# parameter pattern. Token check mirrors the HTTP verify_auth: accept either the
# SHA-256 hashed token (frontend's AuthGate flow) or the raw plaintext (curl /
# scripts). Constant-time compare via hmac.compare_digest. On mismatch, close
# with code 1008 (Policy Violation) before connect.
#
# Why this matters: pre-cutover the FastAPI bound to 127.0.0.1 only and the
# WebSocket was network-isolated. Post-cutover (Cloudflare Tunnel exposing
# `wss://halcyonlab.app/ws/live`), an unauthenticated WS would leak trade
# signals to any internet observer — the broadcast payload includes
# `trade_opened` events with ticker/side/shares (see
# `src/shadow_trading/executor.py` broadcast_sync call sites). That's a
# front-running surface for the quant strategy. This token check closes it.
@app.websocket("/ws/live")
async def websocket_endpoint(websocket: WebSocket, token: str = ""):
    if not API_SECRET:
        # Fail closed — refuse to serve WS without auth configured.
        await websocket.close(code=1008)
        return
    if not (
        hmac.compare_digest(token, _API_SECRET_HASH)
        or hmac.compare_digest(token, API_SECRET)
    ):
        await websocket.close(code=1008)
        return
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)


# Serve React build (static files) — MUST be last so /api/* routes match first.
# Post-cutover this is the production frontend host (the dashboard at
# halcyonlab.app loads from here through the Cloudflare Tunnel).
frontend_dist = os.path.join(os.path.dirname(__file__), "..", "..", "frontend", "dist")
_index_html = os.path.join(frontend_dist, "index.html")
if os.path.exists(frontend_dist):
    # SPA fallback: any non-/api/* path that returns 404 from StaticFiles serves
    # index.html so React Router can resolve the route client-side. Without this,
    # direct URLs (/shadow, /health, /diagnostics, ...) and page refreshes return
    # FastAPI's default {"detail":"Not Found"} JSON. /api/* and /ws/* paths still
    # 404 normally — that's the API surface, not the SPA.
    #
    # Non-SPA exceptions must return a Response (not re-raise) — re-raising from
    # inside an exception handler bubbles to uvicorn and becomes a 500, which
    # masked 401 responses pre-v0.36.21 and broke the frontend AuthGate
    # redirect-on-401 path in `frontend/src/api.js`.
    @app.exception_handler(StarletteHTTPException)
    async def _spa_fallback_404(request: Request, exc: StarletteHTTPException):
        if (
            exc.status_code == 404
            and request.method == "GET"
            and not request.url.path.startswith(("/api/", "/ws/", "/healthz"))
            and os.path.exists(_index_html)
        ):
            return FileResponse(_index_html)
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail},
            headers=getattr(exc, "headers", None) or None,
        )

    app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="frontend")
