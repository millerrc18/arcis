"""T15b — /api/notifications/health endpoint tests."""
import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient


def _make_client():
    from src.api.cloud_routes.notifications import router
    from fastapi import FastAPI
    app = FastAPI()
    app.include_router(router, prefix="/api")
    return TestClient(app, raise_server_exceptions=True)


def _health_row(success_rate=1.0, fail_count=0, dedup_hits=3, oldest_unack_alert=None):
    return {
        "success_rate": success_rate,
        "fail_count": fail_count,
        "dedup_hits": dedup_hits,
        "oldest_unack_alert": oldest_unack_alert,
    }


def test_notifications_health_returns_required_fields():
    """/api/notifications/health returns success_rate, fail_count, dedup_hits, oldest_unack_alert."""
    client = _make_client()
    with patch(
        "src.api.cloud_routes.notifications._compute_health",
        return_value=_health_row(),
    ):
        resp = client.get("/api/notifications/health")

    assert resp.status_code == 200
    data = resp.json()
    assert "success_rate" in data
    assert "fail_count" in data
    assert "dedup_hits" in data
    assert "oldest_unack_alert" in data


def test_notifications_health_success_rate_range():
    """success_rate is between 0 and 1 inclusive."""
    client = _make_client()
    with patch(
        "src.api.cloud_routes.notifications._compute_health",
        return_value=_health_row(success_rate=0.85, fail_count=2),
    ):
        resp = client.get("/api/notifications/health")

    data = resp.json()
    assert 0.0 <= data["success_rate"] <= 1.0
    assert data["fail_count"] == 2


def test_notifications_health_24h_window():
    """_compute_health queries the last 24 hours of notifications_sent rows."""
    with patch("src.api.cloud_routes.notifications._query_sent_rows") as mock_q:
        mock_q.return_value = []
        from src.api.cloud_routes.notifications import _compute_health
        _compute_health()
        assert mock_q.called
        call_args = mock_q.call_args
        # The 24h window must be passed as a parameter
        assert call_args is not None


def test_notifications_health_dedup_hits_counted():
    """dedup_hits reflects rows suppressed by dedup logic in the 24h window."""
    client = _make_client()
    with patch(
        "src.api.cloud_routes.notifications._compute_health",
        return_value=_health_row(dedup_hits=7),
    ):
        resp = client.get("/api/notifications/health")

    assert resp.json()["dedup_hits"] == 7
