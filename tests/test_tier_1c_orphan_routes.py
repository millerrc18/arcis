"""Tier 1.C regression-lock: orphan cloud_routes are registered with app.

Pre-fix: kpis.py, broker_exceptions.py, preflight.py existed in cloud_routes/
but were never wired into app.py — frontend got 404 on /api/kpis,
/api/broker-exceptions/recent, /api/broker-exceptions/summary, /api/preflight/latest.
"""
def test_orphan_routes_are_registered():
    from src.api.app import app
    paths = {route.path for route in app.routes}
    assert "/api/kpis" in paths, "Tier 1.C regression: /api/kpis missing"
    assert "/api/broker-exceptions/recent" in paths, "Tier 1.C regression: /api/broker-exceptions/recent missing"
    assert "/api/broker-exceptions/summary" in paths, "Tier 1.C regression: /api/broker-exceptions/summary missing"
    assert "/api/preflight/latest" in paths, "Tier 1.C regression: /api/preflight/latest missing"
