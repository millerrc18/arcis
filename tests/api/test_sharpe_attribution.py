"""Tests for sharpe_attribution 3-tuple unpack — Sprint 4 T9.

Verifies that the sharpe_attribution endpoint correctly unpacks the new 3-tuple
from _desk_clause and that behavior is unchanged for non-live desks.

Test strategy:
  4. tuple unpack compiles: sharpe_attribution endpoint returns 200 for non-live desk
  5. GREP regression: verified separately (documented in sibling_search_post)
"""
from __future__ import annotations

from unittest.mock import MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.cloud_routes.trades import create_router, _desk_clause


# ── Runtime mock helpers ──────────────────────────────────────────────────────


def _make_runtime_with_trades(rows: list | None = None):
    """Build a minimal mock runtime for sharpe_attribution tests."""
    import pytz

    runtime = MagicMock()
    runtime.logger = MagicMock()
    runtime.et = pytz.timezone("US/Eastern")

    if rows is None:
        rows = [
            {"pnl_pct": 5.0, "spy_return_over_hold": 2.0, "excess_return": 3.0},
            {"pnl_pct": -2.5, "spy_return_over_hold": 1.0, "excess_return": -3.5},
            {"pnl_pct": 3.0, "spy_return_over_hold": 1.5, "excess_return": 1.5},
        ]

    runtime.query.return_value = rows
    return runtime


def _make_client(runtime):
    app = FastAPI()

    def verify_auth():
        return True

    router = create_router(runtime, verify_auth)
    app.include_router(router)
    return TestClient(app, raise_server_exceptions=True)


# ── Test 4: tuple unpack compiles, behavior unchanged for non-live ────────────


def test_sharpe_attribution_non_live_desk_returns_200():
    """sharpe_attribution with desk=swing compiles the 3-tuple unpack and returns 200.

    This test verifies that the _desk_clause refactor to 3-tuple didn't break the
    sharpe_attribution endpoint's tuple unpack.
    """
    runtime = _make_runtime_with_trades()
    client = _make_client(runtime)

    resp = client.get("/api/shadow/sharpe-attribution?desk=swing")
    assert resp.status_code == 200, f"Got {resp.status_code}: {resp.text}"
    data = resp.json()

    assert "error" not in data, f"Endpoint returned error: {data.get('error')}"
    assert "raw_sharpe" in data, f"Expected raw_sharpe in response, got keys: {list(data.keys())}"


def test_sharpe_attribution_default_desk_returns_200():
    """sharpe_attribution with no desk param compiles the 3-tuple unpack and returns 200."""
    runtime = _make_runtime_with_trades()
    client = _make_client(runtime)

    resp = client.get("/api/shadow/sharpe-attribution")
    assert resp.status_code == 200, f"Got {resp.status_code}: {resp.text}"
    data = resp.json()

    assert "error" not in data, f"Endpoint returned error: {data.get('error')}"


def test_sharpe_attribution_all_desk_returns_200():
    """sharpe_attribution with desk=all compiles the 3-tuple unpack and returns 200."""
    runtime = _make_runtime_with_trades()
    client = _make_client(runtime)

    resp = client.get("/api/shadow/sharpe-attribution?desk=all")
    assert resp.status_code == 200, f"Got {resp.status_code}: {resp.text}"
    data = resp.json()

    assert "error" not in data, f"Endpoint returned error: {data.get('error')}"


# ── Test 5 (structural): _desk_clause returns 3-tuple for all branches ────────


def test_desk_clause_returns_3_tuple_for_all_branches():
    """_desk_clause must return exactly 3-tuple (sql_frag, params, cohort_id) for all inputs.

    This is the structural GREP regression: verifies the helper itself emits a
    3-tuple across all 4 branches (None/swing, 'all', wildcard, exact non-live).
    """
    inputs = [None, "swing", "all", "research_*", "research_lazy_prices_v1"]
    for desk in inputs:
        result = _desk_clause(desk)
        assert isinstance(result, tuple), f"_desk_clause({desk!r}) must return a tuple"
        assert len(result) == 3, (
            f"_desk_clause({desk!r}) must return 3-tuple (sql, params, cohort_id), "
            f"got {len(result)}-tuple: {result}"
        )
        sql_frag, params, cohort_id = result
        assert isinstance(sql_frag, str), f"sql_frag must be str, got {type(sql_frag)}"
        assert isinstance(params, list), f"params must be list, got {type(params)}"
        assert isinstance(cohort_id, str), f"cohort_id must be str, got {type(cohort_id)}"
        assert cohort_id == "trades.all_closed", (
            f"Non-live desk {desk!r} must emit cohort_id='trades.all_closed', got {cohort_id!r}"
        )


def test_desk_clause_live_returns_3_tuple_with_live_only_cohort():
    """_desk_clause('live') must return 3-tuple with cohort_id='trades.live_only'."""
    result = _desk_clause("live")
    assert isinstance(result, tuple) and len(result) == 3, (
        f"_desk_clause('live') must return 3-tuple, got {result!r}"
    )
    sql_frag, params, cohort_id = result
    assert "source" in sql_frag, (
        f"SQL fragment for desk='live' must reference source column, got: {sql_frag!r}"
    )
    assert "live" in params, (
        f"params for desk='live' must include 'live', got: {params!r}"
    )
    assert cohort_id == "trades.live_only", (
        f"cohort_id for desk='live' must be 'trades.live_only', got {cohort_id!r}"
    )
