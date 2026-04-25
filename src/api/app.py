"""FastAPI application for the Arcis dashboard.

Called by: none (entry point)
Calls: api.routes, api.websocket, journal.store, log_config
Owns tables: none
Config keys: none
Tests: none
"""
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

from src.api.routes import system, scan, shadow, training, review, packets, docs, actions, health, council, notes, live, logs, ib_status, ib_shadow, strategy_detail, system_index, projections
from src.api.websocket import manager


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Startup/shutdown hook replacing the deprecated on_event("startup")."""
    from src.journal.store import initialize_database
    from src.log_config import setup_logging
    setup_logging()
    initialize_database()
    yield


app = FastAPI(title="Arcis", version="0.17.1", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(system.router, prefix="/api")
app.include_router(scan.router, prefix="/api")
app.include_router(shadow.router, prefix="/api")
app.include_router(training.router, prefix="/api")
app.include_router(review.router, prefix="/api")
app.include_router(packets.router, prefix="/api")
app.include_router(docs.router, prefix="/api")
app.include_router(actions.router, prefix="/api")
app.include_router(health.router, prefix="/api")
app.include_router(council.router, prefix="/api")
app.include_router(notes.router, prefix="/api")
app.include_router(live.router, prefix="/api")
app.include_router(logs.router, prefix="/api")
app.include_router(ib_status.router, prefix="/api")
app.include_router(ib_shadow.router, prefix="/api")
app.include_router(strategy_detail.router, prefix="/api")
app.include_router(system_index.router)
app.include_router(projections.router, prefix="/api")


# WebSocket for live updates (uses shared manager from websocket.py)
@app.websocket("/ws/live")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)


# Serve React build (static files) — MUST be last
frontend_dist = os.path.join(os.path.dirname(__file__), "..", "..", "frontend", "dist")
if os.path.exists(frontend_dist):
    app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="frontend")
