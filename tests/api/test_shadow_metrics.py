"""Tests for /api/shadow/metrics cohort-id logic — Sprint 4 T9.

Verifies that shadow_metrics emits the correct cohort in _meta based on the
desk parameter, and that the SQL filter is applied correctly for the 'live' desk.

Test strategy:
  1. desk=live  -> _meta.cohort='trades.live_only'; SQL contains source = 'live'
  2. desk=swing -> _meta.cohort='trades.all_closed'
  3. desk=all   -> _meta.cohort='trades.all_closed'; no source filter
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.cloud_routes.trades import create_router


# ── Runtime mock helpers ──────────────────────────────────────────────────────


def _make_runtime(rows: list | None = None):
    """Build a minimal mock runtime for shadow_metrics tests."""
    import pytz

    runtime = MagicMock()
    runtime.logger = MagicMock()
    runtime.et = pytz.timezone("US/Eastern")

    if rows is None:
        rows = [
            {"pnl_dollars": 100.0, "pnl_pct": 5.0},
            {"pnl_dollars": -50.0, "pnl_pct": -2.5},
        ]

    captured_sql: list[str] = []

    def _query_side(sql, *args, **kwargs):
        captured_sql.append(sql)
        return rows

    runtime.query.side_effect = _query_side
    runtime._captured_sql = captured_sql
    return runtime


def _make_client(runtime):
    app = FastAPI()

    def verify_auth():
        return True

    router = create_router(runtime, verify_auth)
    app.include_router(router)
    return TestClient(app, raise_server_exceptions=True)


# ── T9 test 1: desk=live -> cohort='trades.live_only'; SQL has source='live' ──


def test_shadow_metrics_live_desk_cohort_is_live_only():
    """desk=live -> _meta.cohort='trades.live_only'.

    The SQL sent to the DB must contain source = %s (with param 'live') so
    that only broker-originated live trades are counted.
    """
    runtime = _make_runtime()
    client = _make_client(runtime)

    resp = client.get("/api/shadow/metrics?desk=live")
    assert resp.status_code == 200, f"Got {resp.status_code}: {resp.text}"
    data = resp.json()

    assert "_meta" in data, f"Response missing _meta: {data}"
    assert data["_meta"]["cohort"] == "trades.live_only", (
        f"Expected cohort='trades.live_only' for desk=live, "
        f"got '{data['_meta']['cohort']}'"
    )


def test_shadow_metrics_live_desk_sql_has_source_filter():
    """desk=live -> SQL must contain 'source = %s' fragment."""
    runtime = _make_runtime()
    client = _make_client(runtime)

    resp = client.get("/api/shadow/metrics?desk=live")
    assert resp.status_code == 200

    # Check that at least one query call used the source filter
    captured = runtime._captured_sql
    assert any("source = %s" in sql for sql in captured), (
        f"Expected SQL to contain 'source = %s' for desk=live. "
        f"Captured SQL calls: {captured}"
    )


# ── T9 test 2: desk=swing -> cohort='trades.all_closed' ──────────────────────


def test_shadow_metrics_swing_desk_cohort_is_all_closed():
    """desk=swing -> _meta.cohort='trades.all_closed'.

    Non-live desks must not emit the live_only cohort.
    """
    runtime = _make_runtime()
    client = _make_client(runtime)

    resp = client.get("/api/shadow/metrics?desk=swing")
    assert resp.status_code == 200, f"Got {resp.status_code}: {resp.text}"
    data = resp.json()

    assert "_meta" in data, f"Response missing _meta: {data}"
    assert data["_meta"]["cohort"] == "trades.all_closed", (
        f"Expected cohort='trades.all_closed' for desk=swing, "
        f"got '{data['_meta']['cohort']}'"
    )


# ── T9 test 3: desk=all -> cohort='trades.all_closed'; no source filter ───────


def test_shadow_metrics_all_desk_cohort_is_all_closed():
    """desk=all -> _meta.cohort='trades.all_closed'; no source='live' filter."""
    runtime = _make_runtime()
    client = _make_client(runtime)

    resp = client.get("/api/shadow/metrics?desk=all")
    assert resp.status_code == 200, f"Got {resp.status_code}: {resp.text}"
    data = resp.json()

    assert "_meta" in data, f"Response missing _meta: {data}"
    assert data["_meta"]["cohort"] == "trades.all_closed", (
        f"Expected cohort='trades.all_closed' for desk=all, "
        f"got '{data['_meta']['cohort']}'"
    )


def test_shadow_metrics_all_desk_no_source_filter_in_sql():
    """desk=all -> SQL must NOT contain 'source = %s' (no source filter)."""
    runtime = _make_runtime()
    client = _make_client(runtime)

    resp = client.get("/api/shadow/metrics?desk=all")
    assert resp.status_code == 200

    captured = runtime._captured_sql
    assert not any("source = %s" in sql for sql in captured), (
        f"Expected no 'source = %s' in SQL for desk=all. "
        f"Captured SQL calls: {captured}"
    )


# ── T9 test extra: default (no desk) -> cohort='trades.all_closed' ────────────


def test_shadow_metrics_default_desk_cohort_is_all_closed():
    """No desk param -> _meta.cohort='trades.all_closed' (default swing behavior)."""
    runtime = _make_runtime()
    client = _make_client(runtime)

    resp = client.get("/api/shadow/metrics")
    assert resp.status_code == 200, f"Got {resp.status_code}: {resp.text}"
    data = resp.json()

    assert "_meta" in data, f"Response missing _meta: {data}"
    assert data["_meta"]["cohort"] == "trades.all_closed", (
        f"Expected cohort='trades.all_closed' for default desk, "
        f"got '{data['_meta']['cohort']}'"
    )
