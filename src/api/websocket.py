"""WebSocket live update manager for the dashboard."""

import logging
from datetime import datetime

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, event_type: str, data: dict):
        """Broadcast event to all connected clients.
        Event types: scan_complete, trade_opened, trade_closed, pnl_update,
                     training_update, system_status
        """
        message = {
            "type": event_type,
            "data": data,
            "timestamp": datetime.now().isoformat(),
        }
        disconnected = []
        for conn in self.active_connections:
            try:
                await conn.send_json(message)
            except Exception:
                disconnected.append(conn)
        for conn in disconnected:
            self.active_connections.remove(conn)


manager = ConnectionManager()


def broadcast_sync(event_type: str, data: dict):
    """Fire-and-forget broadcast from synchronous code."""
    try:
        import asyncio

        if not manager.active_connections:
            return

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            asyncio.run(manager.broadcast(event_type, data))
            return

        loop.create_task(manager.broadcast(event_type, data))
    except Exception as e:
        logging.getLogger(__name__).warning("broadcast_sync error: %s", e)
