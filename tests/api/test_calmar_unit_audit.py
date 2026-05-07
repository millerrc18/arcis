"""Regression-lock: fund_metrics['calmar_ratio'] must match canonical helper.

Sprint 3 T1 — E5 Calmar 1000x overshoot fix.
Locks that analytics.py:568 no longer uses the ad-hoc formula
ann_ret / (max_dd / 100000 * 100) which simplifies to ann_ret * 1000 / max_dd.
"""
from __future__ import annotations

import datetime
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.cloud_routes.analytics import create_router
from src.evaluation.statistics import calmar_ratio


# ── Fixtures ─────────────────────────────────────────────────────────────────

_FIXTURE_TRADES = [
    {
        "ticker": "AAPL",
        "pnl_pct": 2.0,
        "pnl_dollars": 200.0,
        "exit_reason": "target_1_hit",
        "duration_days": 3,
        "recommendation_id": None,
        "actual_exit_time": "2026-01-03T15:00:00",
        "updated_at": "2026-01-03T15:00:00",
        "broker": "alpaca",
    },
    {
        "ticker": "GOOG",
        "pnl_pct": -1.0,
        "pnl_dollars": -100.0,
        "exit_reason": "stop_loss",
        "duration_days": 2,
        "recommendation_id": None,
        "actual_exit_time": "2026-01-04T15:00:00",
        "updated_at": "2026-01-04T15:00:00",
        "broker": "alpaca",
    },
    {
        "ticker": "MSFT",
        "pnl_pct": 3.0,
        "pnl_dollars": 300.0,
        "exit_reason": "target_1_hit",
        "duration_days": 5,
        "recommendation_id": None,
        "actual_exit_time": "2026-01-05T15:00:00",
        "updated_at": "2026-01-05T15:00:00",
        "broker": "alpaca",
    },
]


def _make_runtime():
    runtime = MagicMock()
    runtime.logger = MagicMock()

    import pytz
    runtime.et = pytz.timezone("US/Eastern")

    def query_side_effect(sql, *args, **kwargs):
        if "shadow_trades" in sql and "closed" in sql:
            return _FIXTURE_TRADES
        return []

    def query_one_side_effect(sql, *args, **kwargs):
        if "open" in sql:
            return {"c": 0}
        if "recommendations" in sql and "created_at" in sql:
            return {"c": 0}
        if "audit_reports" in sql:
            return None
        if "training_examples" in sql:
            return {"c": 0}
        if "model_versions" in sql:
            return None
        return None

    runtime.query.side_effect = query_side_effect
    runtime.query_one.side_effect = query_one_side_effect
    return runtime


def _make_client():
    app = FastAPI()
    runtime = _make_runtime()

    def verify_auth():
        return True

    router = create_router(runtime, verify_auth)
    app.include_router(router)
    client = TestClient(app, raise_server_exceptions=True)
    return client


# ── Test: calmar_ratio matches canonical helper to 3 decimal places ───────────

def test_calmar_ratio_matches_canonical():
    """fund_metrics['calmar_ratio'] must equal calmar_ratio() canonical to 3dp.

    Fixture: pnls=[+2,-1,+3], pnl_dollars=[200,-100,300]
    max_dd (dollars) = 100 (running: 200→100→400, peak: 200→200→400, dd: 0→100→0)
    mean_ret = 4/3, ann_ret = 4/3 * 252 = 336.0
    canonical: calmar_ratio(336.0, 100) = 3.36
    """
    client = _make_client()
    resp = client.get("/api/cto-report?days=7")
    assert resp.status_code == 200, f"Unexpected status: {resp.status_code}, body: {resp.text}"
    data = resp.json()
    assert "error" not in data, f"Endpoint returned error: {data.get('error')}"

    pnls = [2.0, -1.0, 3.0]
    pnl_dollars = [200.0, -100.0, 300.0]

    mean_ret = sum(pnls) / len(pnls)
    ann_ret = mean_ret * 252
    running = 0
    peak = 0
    max_dd = 0
    for p in pnl_dollars:
        running += p
        peak = max(peak, running)
        max_dd = max(max_dd, peak - running)

    expected = calmar_ratio(annualized_return=ann_ret, max_drawdown_pct=max_dd)

    fund_metrics = data.get("fund_metrics", {})
    actual = fund_metrics.get("calmar_ratio")
    assert actual is not None, "fund_metrics['calmar_ratio'] must not be None"
    assert abs(actual - expected) < 0.001, (
        f"calmar_ratio {actual} differs from canonical {expected:.3f} by more than 0.001. "
        f"Bug: ad-hoc formula ann_ret / (max_dd / 100000 * 100) produces {round(ann_ret / (max_dd / 100000 * 100), 3)} (1000x overshoot)"
    )


def test_calmar_no_ad_hoc_formula_in_source():
    """Algebraic-equiv check: grep src/ for / 100000 * 100 pattern returns zero matches."""
    import subprocess
    import os

    src_dir = os.path.join(
        os.path.dirname(__file__), "..", "..", "src"
    )
    result = subprocess.run(
        ["git", "grep", "-rn", r"/ 100000 \* 100", src_dir],
        capture_output=True,
        text=True,
    )
    matches = [
        line for line in result.stdout.splitlines()
        if "calmar" in line.lower() or "ann_ret" in line.lower()
    ]
    assert matches == [], (
        f"Found ad-hoc calmar formula '/ 100000 * 100' in src/:\n"
        + "\n".join(matches)
    )
