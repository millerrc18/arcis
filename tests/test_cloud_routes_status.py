"""T8 — /api/status open_count alignment test.

Verifies that /api/status returns open_positions matching the count from
/api/shadow/open (all non-quarantined open trades, no source='live' filter).
"""
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def runtime():
    rt = MagicMock()
    rt.et = __import__("zoneinfo").ZoneInfo("America/New_York")
    rt.logger = MagicMock()
    return rt


@pytest.fixture
def router(runtime):
    from src.api.cloud_routes.core import create_router
    verify_auth = MagicMock(return_value=None)
    return create_router(runtime, verify_auth)


def _get_status_handler(router):
    """Extract the /api/status route handler from the router."""
    for route in router.routes:
        if hasattr(route, "path") and route.path == "/api/status":
            return route.endpoint
    raise AssertionError("/api/status route not found in router")


class TestStatusOpenCount:
    """T8 — /api/status open_positions must count all open trades not just source='live'."""

    def test_status_open_positions_counts_all_open_trades(self, runtime):
        """open_positions should count trades with status='open' without source='live' filter."""
        runtime.query.side_effect = [
            [{"count": 28}],   # open_trades query
            [{"count": 16}],   # closed_trades query
        ]
        runtime.query_one.side_effect = [
            {"version_name": "v0.36.0", "created_at": "2026-05-01", "status": "active"},
            {"overall_assessment": "green", "created_at": "2026-05-01"},
            {"c": 500},
        ]

        from src.api.cloud_routes.core import create_router
        verify_auth = MagicMock(return_value=None)
        router = create_router(runtime, verify_auth)
        handler = _get_status_handler(router)

        result = handler()

        assert result["open_positions"] == 28, (
            f"Expected 28 open positions, got {result['open_positions']}. "
            "The status endpoint must NOT filter by source='live' — it should count all "
            "non-quarantined open trades to match /api/shadow/open."
        )

    def test_status_open_positions_sql_does_not_filter_source_live(self, runtime):
        """The SQL for open_positions must not include 'source = live' predicate.

        Instead it should use desk = 'swing' to match /api/shadow/open default.
        """
        captured_sql = []

        def capture_query(sql, params=()):
            captured_sql.append(sql)
            return [{"count": 5}]

        runtime.query.side_effect = capture_query
        runtime.query_one.side_effect = [
            {"version_name": "v0.36.0", "created_at": "2026-05-01", "status": "active"},
            {"overall_assessment": "green", "created_at": "2026-05-01"},
            {"c": 100},
        ]

        from src.api.cloud_routes.core import create_router
        verify_auth = MagicMock(return_value=None)
        router = create_router(runtime, verify_auth)
        handler = _get_status_handler(router)
        handler()

        open_query = captured_sql[0] if captured_sql else ""
        assert "source = 'live'" not in open_query, (
            f"open_positions SQL must NOT include source='live' filter, got: {open_query!r}"
        )
        assert "desk" in open_query.lower(), (
            f"open_positions SQL must include desk filter to match /api/shadow/open, got: {open_query!r}"
        )

    def test_status_includes_meta_for_open_positions(self, runtime):
        """_meta.open_positions must be present in status response."""
        runtime.query.side_effect = [
            [{"count": 28}],
            [{"count": 16}],
        ]
        runtime.query_one.side_effect = [
            {"version_name": "v0.36.0", "created_at": "2026-05-01", "status": "active"},
            {"overall_assessment": "green", "created_at": "2026-05-01"},
            {"c": 500},
        ]

        from src.api.cloud_routes.core import create_router
        verify_auth = MagicMock(return_value=None)
        router = create_router(runtime, verify_auth)
        handler = _get_status_handler(router)

        result = handler()

        assert "_meta" in result
        assert "open_positions" in result["_meta"]
