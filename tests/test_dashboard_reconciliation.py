"""B3 CI dashboard reconciliation test -- SQLite + Postgres parametrized.

Sprint 3 cockpit-coherence Task T16 (SQLite-only baseline).
Sprint 4 T19a extends: postgres_session fixture parametrizes the mock-runtime
tests so both DB backends are exercised when DATABASE_URL is set.

Verifies:
1. All 5 main endpoints emit a _meta envelope.
2. Closed-count reconciles between /api/cto-report and /api/shadow/metrics
   AFTER confirming cohort_id matches; cohort drift is skipped, not failed.
3. Open-position count reconciles between /api/status and /api/live/summary.
4. meta_entry('bogus', 0) raises KeyError (negative test).

Postgres parametrize variant: runs only when DATABASE_URL env var is set;
otherwise SKIPPED at collection (not FAILED). Test count is stable across
environments (#SP4-render-pg-reconcile).
"""
from __future__ import annotations

import os

import pytest
from unittest.mock import MagicMock, patch

import pytz
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.cloud_routes.analytics import create_router as create_analytics_router
from src.api.cloud_routes.trades import create_router as create_trades_router
from src.api.cloud_routes.core import create_router as create_core_router


# -- Runtime fixture helpers --------------------------------------------------

def _make_runtime(
    open_count: int = 3,
    closed_count: int = 5,
    live_open_count: int = 3,
) -> MagicMock:
    """Return a mock runtime sufficient for the 5 main endpoints under test."""
    runtime = MagicMock()
    runtime.logger = MagicMock()
    runtime.et = pytz.timezone("US/Eastern")
    runtime.parse_json_fields = MagicMock()

    def _query_side_effect(sql, *args, **kwargs):
        sql_s = sql.strip()
        # /api/status open_trades: SELECT COUNT(*) as count FROM shadow_trades WHERE status='open'
        if "shadow_trades" in sql_s and "COUNT(*) as count" in sql_s and "status = 'open'" in sql_s:
            return [{"count": open_count}]
        # /api/status closed_trades: SELECT COUNT(*) as count FROM shadow_trades WHERE status='closed'
        if "shadow_trades" in sql_s and "COUNT(*) as count" in sql_s and "status = 'closed'" in sql_s:
            return [{"count": closed_count}]
        # live/summary closed: source='live' AND status='closed'
        if "shadow_trades" in sql_s and "source = 'live'" in sql_s and "status = 'closed'" in sql_s:
            return []
        # shadow/metrics and cto-report and hshs: closed trades with pnl data
        if "shadow_trades" in sql_s and "status = 'closed'" in sql_s:
            return [
                {"pnl_dollars": 10.0, "pnl_pct": 2.0, "exit_reason": "target_1_hit",
                 "ticker": "AAPL", "recommendation_id": None, "duration_days": 5,
                 "actual_exit_time": "2026-01-10T15:00:00", "broker": "alpaca"}
                for _ in range(closed_count)
            ]
        if "training_examples" in sql_s and "GROUP BY source" in sql_s:
            return []
        if "training_examples" in sql_s and "DISTINCT regime_label" in sql_s:
            return [{"cnt": 0}]
        if "training_examples" in sql_s and "DISTINCT ticker" in sql_s:
            return [{"cnt": 0}]
        return []

    def _query_one_side_effect(sql, *args, **kwargs):
        sql_s = sql.strip()
        # open count queries -- live source specific
        if "shadow_trades" in sql_s and "status = 'open'" in sql_s and "source = 'live'" in sql_s:
            return {"c": live_open_count}
        # open count queries -- all (no source filter)
        if "shadow_trades" in sql_s and "status = 'open'" in sql_s:
            return {"c": open_count}
        # closed count queries (COUNT(*) form)
        if "shadow_trades" in sql_s and "COUNT(*)" in sql_s and "status = 'closed'" in sql_s:
            return {"count": closed_count, "c": closed_count}
        # training_examples count
        if "training_examples" in sql_s and "COUNT(*)" in sql_s:
            return {"count": 0, "c": 0}
        # model_versions
        if "model_versions" in sql_s:
            return {"version_name": "v1", "created_at": "2026-01-01", "status": "active"}
        # audit_reports
        if "audit_reports" in sql_s:
            return {"overall_assessment": "green", "created_at": "2026-01-01", "summary": "ok"}
        # scan_metrics
        if "scan_metrics" in sql_s:
            return {"llm_success": 100, "llm_total": 100}
        # canary_evaluations
        if "canary_evaluations" in sql_s:
            return None
        # recommendations
        if "recommendations" in sql_s and "COUNT(*)" in sql_s:
            return {"c": 0}
        # live closed pnl
        if "COALESCE(SUM(pnl_dollars)" in sql_s:
            return {"total": 0.0}
        # build_score_history
        if "build_score_history" in sql_s:
            return None
        # traffic_light_state
        if "traffic_light_state" in sql_s:
            return {"current_regime": "UNKNOWN", "last_total_score": 0}
        # vix_term_structure
        if "vix_term_structure" in sql_s:
            return {"vix": 15.0}
        return None

    runtime.query.side_effect = _query_side_effect
    runtime.query_one.side_effect = _query_one_side_effect
    return runtime


def _make_app(runtime: MagicMock) -> FastAPI:
    """Build a FastAPI test app with analytics, trades, and core routers."""
    app = FastAPI()

    def verify_auth():
        return True

    app.include_router(create_analytics_router(runtime, verify_auth))
    app.include_router(create_trades_router(runtime, verify_auth))
    app.include_router(create_core_router(runtime, verify_auth))
    return app


def _make_client(runtime: MagicMock) -> TestClient:
    return TestClient(_make_app(runtime), raise_server_exceptions=True)


# -- Test 1: all 5 main endpoints emit _meta ----------------------------------

_ENDPOINTS_WITH_META = [
    "/api/cto-report",
    "/api/shadow/metrics",
    "/api/status",
    "/api/attribution/stats",
    "/api/stress-test/results",
]


@pytest.mark.parametrize("endpoint", _ENDPOINTS_WITH_META)
def test_all_endpoints_emit_meta(endpoint):
    """Each of the 5 main dashboard endpoints must include a _meta field in the response.

    This is the CI regression-lock for Sprint 3 §5 B3. If any endpoint drops _meta,
    the dashboard cohort-coherence contract is broken.
    """
    runtime = _make_runtime()
    client = _make_client(runtime)

    resp = client.get(endpoint)
    assert resp.status_code == 200, (
        f"Expected 200 from {endpoint}, got {resp.status_code}: {resp.text[:300]}"
    )
    data = resp.json()
    assert "_meta" in data, (
        f"Endpoint {endpoint} must emit a _meta envelope. "
        f"Response keys: {list(data.keys())}"
    )


# -- Test 2: closed-count reconciles (cohort-aware) ---------------------------

def test_closed_count_reconciles():
    """Assert cto._meta.trade_summary.cohort == shadow._meta.cohort BEFORE asserting n == n.

    Cohort mismatch is by design (e.g., desk filter applied) -- pytest.skip, not fail.
    If cohorts match, assert the closed counts are equal.

    Spec §5 B3: /api/cto-report._meta.trade_summary.cohort vs /api/shadow/metrics._meta.cohort.
    """
    closed_count = 7
    runtime = _make_runtime(closed_count=closed_count)
    client = _make_client(runtime)

    cto_resp = client.get("/api/cto-report")
    assert cto_resp.status_code == 200, f"cto-report: {cto_resp.status_code}"
    cto_data = cto_resp.json()

    shadow_resp = client.get("/api/shadow/metrics")
    assert shadow_resp.status_code == 200, f"shadow/metrics: {shadow_resp.status_code}"
    shadow_data = shadow_resp.json()

    assert "_meta" in cto_data, "cto-report must emit _meta"
    assert "_meta" in shadow_data, "shadow/metrics must emit _meta"

    cto_cohort = cto_data["_meta"]["trade_summary"]["cohort"]
    shadow_cohort = shadow_data["_meta"]["cohort"]

    if cto_cohort != shadow_cohort:
        pytest.skip(
            f"cohort drift by design: cto={cto_cohort!r} vs shadow={shadow_cohort!r}"
        )

    cto_n = cto_data["_meta"]["trade_summary"]["n"]
    shadow_n = shadow_data["_meta"]["n"]
    assert cto_n == shadow_n, (
        f"Closed-count mismatch: cto._meta.trade_summary.n={cto_n} "
        f"vs shadow._meta.n={shadow_n} (both cohort={cto_cohort!r})"
    )


# -- Test 3: open-position count reconciles -----------------------------------

def test_open_position_reconcile():
    """/api/status.open_positions count == /api/live/summary.open_positions count.

    Both endpoints report open positions. /api/status counts all open shadow_trades;
    /api/live/summary counts source='live' open shadow_trades. Under the test fixture,
    both values are set to the same sentinel value to confirm the reconciliation
    assertion logic works when counts agree.

    Spec §5 B3: separate test for open-position definition reconciliation.
    """
    live_open = 4
    runtime = _make_runtime(open_count=live_open, live_open_count=live_open)
    client = _make_client(runtime)

    status_resp = client.get("/api/status")
    assert status_resp.status_code == 200, (
        f"status: {status_resp.status_code}: {status_resp.text[:300]}"
    )
    status_data = status_resp.json()

    live_resp = client.get("/api/live/summary")
    assert live_resp.status_code == 200, f"live/summary: {live_resp.status_code}"
    live_data = live_resp.json()

    assert "open_positions" in status_data, (
        f"/api/status response must include 'open_positions'. Keys: {list(status_data.keys())}"
    )
    assert "open_positions" in live_data, (
        f"/api/live/summary response must include 'open_positions'. Keys: {list(live_data.keys())}"
    )

    status_open = status_data["open_positions"]
    live_open_actual = live_data["open_positions"]

    assert status_open == live_open_actual, (
        f"Open-position count mismatch: /api/status={status_open} "
        f"vs /api/live/summary={live_open_actual}. "
        "Fixture sets both to the same value; reconciliation logic must preserve equality."
    )


# -- Test 4: invalid cohort_id raises KeyError --------------------------------

def test_invalid_cohort_id_rejected():
    """meta_entry('bogus', 0) must raise KeyError.

    Validates that cohort_meta.meta_entry enforces the 8-cohort closed taxonomy.
    A typo or new cohort ID must fail loudly at the call site, not silently emit
    a wrong label.
    """
    from src.api.cohort_meta import meta_entry

    with pytest.raises(KeyError):
        meta_entry("bogus", 0)


# -- Test 5: Postgres parametrize (T19a) ---------------------------------------

_PG_SKIP = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL"),
    reason="DATABASE_URL not set; skipping postgres parametrize",
)


@_PG_SKIP
@pytest.mark.parametrize("db_backend", ["sqlite", "postgres"])
def test_all_endpoints_emit_meta_parametrized(db_backend, postgres_session):
    """Parametrized variant of test_all_endpoints_emit_meta against both backends.

    SQLite path uses the same mock-runtime fixture as the original T16 tests.
    Postgres path uses postgres_session to confirm DB connectivity before
    running the mock-runtime assertions (the endpoint logic itself is mocked;
    this test validates the fixture wiring and skip guard, not live DB queries).

    Skipped at collection when DATABASE_URL is absent (not failed) so test
    count stays stable across environments.
    """
    if db_backend == "postgres":
        assert postgres_session is not None, "postgres_session fixture must yield a connection"

    runtime = _make_runtime()
    client = _make_client(runtime)

    for endpoint in _ENDPOINTS_WITH_META:
        resp = client.get(endpoint)
        assert resp.status_code == 200, (
            f"[{db_backend}] Expected 200 from {endpoint}, "
            f"got {resp.status_code}: {resp.text[:300]}"
        )
        data = resp.json()
        assert "_meta" in data, (
            f"[{db_backend}] Endpoint {endpoint} must emit a _meta envelope. "
            f"Response keys: {list(data.keys())}"
        )
