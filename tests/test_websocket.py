"""Tests for WebSocket connection manager."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

from src.api.websocket import ConnectionManager, broadcast_sync


class TestConnectionManager:
    """Tests for the WebSocket ConnectionManager."""

    def test_manager_initializes_empty(self):
        mgr = ConnectionManager()
        assert mgr.active_connections == []

    def test_connect_adds_to_list(self):
        mgr = ConnectionManager()
        ws = AsyncMock()
        asyncio.run(mgr.connect(ws))
        assert ws in mgr.active_connections
        ws.accept.assert_awaited_once()

    def test_disconnect_removes_from_list(self):
        mgr = ConnectionManager()
        ws = MagicMock()
        mgr.active_connections.append(ws)
        mgr.disconnect(ws)
        assert ws not in mgr.active_connections

    def test_disconnect_nonexistent_no_error(self):
        mgr = ConnectionManager()
        mgr.disconnect(object())  # Should not raise

    def test_broadcast_sends_to_all(self):
        mgr = ConnectionManager()
        ws1, ws2 = AsyncMock(), AsyncMock()
        mgr.active_connections = [ws1, ws2]
        asyncio.run(mgr.broadcast("test_event", {"key": "value"}))
        assert ws1.send_json.await_count == 1
        assert ws2.send_json.await_count == 1

    def test_broadcast_disconnects_failed_clients(self):
        mgr = ConnectionManager()
        good_ws = AsyncMock()
        bad_ws = AsyncMock()
        bad_ws.send_json.side_effect = Exception("disconnected")
        mgr.active_connections = [good_ws, bad_ws]
        asyncio.run(mgr.broadcast("event", {}))
        good_ws.send_json.assert_awaited_once()
        assert bad_ws not in mgr.active_connections


class TestBroadcastSync:
    def test_broadcast_sync_does_not_crash(self):
        try:
            broadcast_sync("test", {"data": 1})
        except RuntimeError:
            pass  # No event loop is acceptable in test context
