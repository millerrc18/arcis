"""Tests for TTL cache on cto_report route handler in analytics.py.

Tests:
1. Two consecutive calls with same days param return same object (cache hit within TTL).
2. After TTL expiry, cache miss recomputes (new object returned).
3. Different days values cache independently.
"""

import time
from unittest.mock import MagicMock, patch
import pytz
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _make_runtime():
    runtime = MagicMock()
    runtime.logger = MagicMock()
    runtime.et = pytz.timezone("US/Eastern")

    call_count = {"n": 0}

    def query_one_side_effect(sql, *args, **kwargs):
        call_count["n"] += 1
        sql_s = sql.strip()
        if "model_versions" in sql_s:
            return {"version_name": "halcyon-v1"}
        if "training_examples" in sql_s:
            return {"c": 100}
        if "audit_reports" in sql_s:
            return {"overall_assessment": "healthy", "summary": "ok"}
        if "recommendations" in sql_s:
            return {"c": 10}
        return {"c": 0, "count": 0}

    runtime.query_one.side_effect = query_one_side_effect
    runtime.query.return_value = []
    runtime._call_count = call_count
    return runtime


def _make_client(runtime):
    app = FastAPI()

    def verify_auth():
        return True

    from src.api.cloud_routes.analytics import create_router
    router = create_router(runtime, verify_auth)
    app.include_router(router)
    return TestClient(app, raise_server_exceptions=False)


class TestCTOReportCache:
    def test_same_days_same_object_within_ttl(self):
        """Two consecutive calls with same days param return identical cached result."""
        runtime = _make_runtime()
        client = _make_client(runtime)

        resp1 = client.get("/api/cto-report?days=7")
        resp2 = client.get("/api/cto-report?days=7")

        assert resp1.status_code == 200
        assert resp2.status_code == 200

        data1 = resp1.json()
        data2 = resp2.json()

        # The generated_at timestamp must be identical — proves cache hit
        assert data1.get("generated_at") == data2.get("generated_at"), (
            f"Cache miss: generated_at differs. "
            f"first={data1.get('generated_at')!r}, second={data2.get('generated_at')!r}"
        )

    def test_different_days_cached_independently(self):
        """days=7 and days=30 are cached with independent keys."""
        runtime = _make_runtime()
        client = _make_client(runtime)

        resp7 = client.get("/api/cto-report?days=7")
        resp30 = client.get("/api/cto-report?days=30")

        assert resp7.status_code == 200
        assert resp30.status_code == 200

        data7 = resp7.json()
        data30 = resp30.json()

        # period_days must differ — proves independent cache entries
        assert data7.get("period_days") == 7, f"Expected period_days=7, got {data7.get('period_days')}"
        assert data30.get("period_days") == 30, f"Expected period_days=30, got {data30.get('period_days')}"

        # Second request for each must still be cached
        resp7b = client.get("/api/cto-report?days=7")
        resp30b = client.get("/api/cto-report?days=30")
        assert resp7b.json().get("generated_at") == data7.get("generated_at"), "days=7 cache miss on second call"
        assert resp30b.json().get("generated_at") == data30.get("generated_at"), "days=30 cache miss on second call"

    def test_cache_miss_after_ttl_expiry(self):
        """After TTL expiry a new computation is performed (different generated_at)."""
        import src.api.cloud_routes.analytics as analytics_module

        runtime = _make_runtime()

        app = FastAPI()

        def verify_auth():
            return True

        # Patch TTL to 1 second so the test doesn't have to wait 5 minutes
        original_ttl = analytics_module._CTO_CACHE_TTL_SECONDS
        analytics_module._CTO_CACHE_TTL_SECONDS = 1
        # Clear any residual cache state from previous tests
        analytics_module._cto_cache.clear()

        try:
            from src.api.cloud_routes.analytics import create_router
            router = create_router(runtime, verify_auth)
            app.include_router(router)
            client = TestClient(app, raise_server_exceptions=False)

            resp1 = client.get("/api/cto-report?days=7")
            assert resp1.status_code == 200
            ts1 = resp1.json().get("generated_at")

            # Wait for TTL to expire
            time.sleep(1.1)

            resp2 = client.get("/api/cto-report?days=7")
            assert resp2.status_code == 200
            ts2 = resp2.json().get("generated_at")

            assert ts1 != ts2, (
                f"TTL expiry did not trigger recompute: both calls returned generated_at={ts1!r}"
            )
        finally:
            analytics_module._CTO_CACHE_TTL_SECONDS = original_ttl
            analytics_module._cto_cache.clear()
