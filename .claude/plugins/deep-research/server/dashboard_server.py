"""Live research dashboard -- HTTP + SSE server.

Spawned by the MCP server on startup. Serves the dashboard SPA
and pushes real-time updates via Server-Sent Events.
"""

from __future__ import annotations

import asyncio
import json
import socket
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from starlette.applications import Starlette
from starlette.responses import HTMLResponse, JSONResponse, StreamingResponse
from starlette.routing import Route

import uvicorn

from server.session import ResearchContext, log

# How long (seconds) with no emitted events before auto-shutdown
_INACTIVITY_TIMEOUT = 30 * 60  # 30 minutes


def _find_available_port() -> int:
    """Bind to port 0 and return the OS-assigned port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        return s.getsockname()[1]


def _serialize_context(ctx: ResearchContext) -> dict[str, Any]:
    """Serialize the full ResearchContext to a JSON-safe dict."""
    data = ctx.get_context(section="all")
    # Add extra fields the dashboard uses
    data["topic"] = getattr(ctx, "topic", "")
    data["status"] = getattr(ctx, "status", "running")
    data["phase"] = getattr(ctx, "phase", "CLASSIFY")
    data["start_time"] = getattr(ctx, "start_time", None)
    data["sub_questions"] = getattr(ctx, "sub_questions", [])
    data["findings"] = getattr(ctx, "findings", [])
    data["agents"] = getattr(ctx, "agents", [])
    return data


@dataclass
class DashboardServer:
    """Holds server state: context ref, connected clients, port."""

    ctx: ResearchContext
    port: int = 0
    _client_queues: set[asyncio.Queue] = field(default_factory=set)
    _server_task: asyncio.Task | None = None
    _uvicorn_server: uvicorn.Server | None = None
    _last_event_time: float = field(default_factory=time.monotonic)

    @property
    def url(self) -> str:
        return f"http://localhost:{self.port}"

    def _broadcast(self, payload: str) -> None:
        """Push a payload string to every connected SSE client queue."""
        dead: list[asyncio.Queue] = []
        for q in self._client_queues:
            try:
                q.put_nowait(payload)
            except asyncio.QueueFull:
                dead.append(q)
        for q in dead:
            self._client_queues.discard(q)

    async def _shutdown_checker(self) -> None:
        """Periodically check for inactivity and shut down if idle."""
        while True:
            await asyncio.sleep(60)
            elapsed = time.monotonic() - self._last_event_time
            if elapsed >= _INACTIVITY_TIMEOUT:
                log(f"Dashboard idle for {int(elapsed)}s -- shutting down")
                if self._uvicorn_server is not None:
                    self._uvicorn_server.should_exit = True
                return


def _build_app(dashboard: DashboardServer) -> Starlette:
    """Build the Starlette ASGI app with all routes."""

    _html_path = Path(__file__).resolve().parent / "dashboard" / "index.html"

    async def homepage(request):
        try:
            html = _html_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            html = "<h1>Dashboard HTML not found</h1><p>Expected at: {}</p>".format(
                _html_path
            )
        return HTMLResponse(html)

    async def api_state(request):
        data = _serialize_context(dashboard.ctx)
        return JSONResponse(data)

    async def api_events(request):
        q: asyncio.Queue[str] = asyncio.Queue(maxsize=256)
        dashboard._client_queues.add(q)

        async def event_generator():
            try:
                # Send initial keepalive
                yield ": connected\n\n"
                while True:
                    try:
                        payload = await asyncio.wait_for(q.get(), timeout=30)
                        yield payload
                    except asyncio.TimeoutError:
                        # Send keepalive comment to prevent connection drop
                        yield ": keepalive\n\n"
            except asyncio.CancelledError:
                pass
            finally:
                dashboard._client_queues.discard(q)

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
                "Access-Control-Allow-Origin": "*",
            },
        )

    routes = [
        Route("/", homepage),
        Route("/api/state", api_state),
        Route("/api/events", api_events),
    ]

    return Starlette(routes=routes)


def emit_event(server: DashboardServer, event_type: str, data: dict[str, Any]) -> None:
    """Push an SSE event to all connected dashboard clients.

    Event types:
        phase_transition, source_registered, finding_added,
        search_executed, agent_spawned, agent_completed,
        council_round, quality_score_update
    """
    server._last_event_time = time.monotonic()
    payload_obj = {
        "type": event_type,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "data": data,
    }
    line = f"data: {json.dumps(payload_obj)}\n\n"
    server._broadcast(line)


async def start_dashboard(ctx: ResearchContext) -> DashboardServer:
    """Create and start the dashboard HTTP server in a background task.

    Returns a DashboardServer with .port and .url ready to use.
    """
    port = _find_available_port()
    dashboard = DashboardServer(ctx=ctx, port=port)

    app = _build_app(dashboard)

    config = uvicorn.Config(
        app=app,
        host="127.0.0.1",
        port=port,
        log_level="warning",
        access_log=False,
    )
    server = uvicorn.Server(config)
    dashboard._uvicorn_server = server

    async def _run():
        try:
            await server.serve()
        except Exception as exc:
            log(f"Dashboard server error: {exc}")

    dashboard._server_task = asyncio.create_task(_run())
    # Also start the inactivity checker
    asyncio.create_task(dashboard._shutdown_checker())

    # Give uvicorn a moment to bind
    await asyncio.sleep(0.3)

    log(f"Dashboard running at {dashboard.url}")
    return dashboard
