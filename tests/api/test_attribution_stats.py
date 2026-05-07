"""Tests for /api/attribution/stats paired-overlap gate.

Sprint 3 T2 — E6 Attribution paired-overlap gate fix.
Verifies that statistical_power is gated on paired-overlap count (trades resolved
by BOTH arms), NOT on min(rr, lr) (marginal counts).
"""
from __future__ import annotations

from unittest.mock import MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.cloud_routes.analytics import create_router


# ── Runtime mock helpers ──────────────────────────────────────────────────────

def _make_runtime_with_attribution(
    total_pairs: int,
    ranker_resolved: int,
    ranker_wins: int,
    llm_resolved: int,
    llm_wins: int,
    paired_overlap: int,
    by_action: dict | None = None,
    by_pair: dict | None = None,
):
    """Build a mock runtime for attribution_stats tests.

    Parameters are intentionally explicit so tests can specify rr/lr margins
    independently from paired overlap — the exact disambiguation the test strategy
    requires.
    """
    runtime = MagicMock()
    runtime.logger = MagicMock()

    import pytz
    runtime.et = pytz.timezone("US/Eastern")

    by_action = by_action or {}
    by_pair = by_pair or {}

    def query_one_side_effect(sql, *args, **kwargs):
        sql_stripped = sql.strip()
        if "COUNT(*) as c FROM attribution_trades" in sql_stripped:
            if "ranker_only_outcome != 'pending'" in sql_stripped and "llm_portfolio_outcome IS NOT NULL" in sql_stripped:
                return {"c": paired_overlap}
            if "ranker_only_outcome != 'pending'" in sql_stripped:
                return {"c": ranker_resolved}
            if "ranker_only_outcome = 'win'" in sql_stripped:
                return {"c": ranker_wins}
            if "llm_portfolio_outcome IS NOT NULL" in sql_stripped:
                return {"c": llm_resolved}
            if "llm_portfolio_outcome = 'win'" in sql_stripped:
                return {"c": llm_wins}
            return {"c": total_pairs}
        return None

    def query_side_effect(sql, *args, **kwargs):
        if "GROUP BY llm_action" in sql:
            return [{"llm_action": k, "cnt": v} for k, v in by_action.items()]
        if "GROUP BY pair_type" in sql:
            return [{"pair_type": k, "cnt": v} for k, v in by_pair.items()]
        return []

    runtime.query_one.side_effect = query_one_side_effect
    runtime.query.side_effect = query_side_effect
    return runtime


def _make_client(runtime):
    app = FastAPI()

    def verify_auth():
        return True

    router = create_router(runtime, verify_auth)
    app.include_router(router)
    return TestClient(app, raise_server_exceptions=True)


# ── Test 1: disambiguating fixture ────────────────────────────────────────────

def test_paired_overlap_gate_uses_overlap_not_marginal_min():
    """paired_n=10 even when rr=300, lr=300 marginal → power='insufficient'.

    This is the critical disambiguation test. If the gate used min(rr, lr)=300,
    power would be 'adequate'. Correct behavior: gate on paired_overlap=10 → 'insufficient'.
    """
    runtime = _make_runtime_with_attribution(
        total_pairs=300,
        ranker_resolved=300,
        ranker_wins=150,
        llm_resolved=300,
        llm_wins=150,
        paired_overlap=10,
    )
    client = _make_client(runtime)

    resp = client.get("/api/attribution/stats")
    assert resp.status_code == 200, f"Got {resp.status_code}: {resp.text}"
    data = resp.json()

    assert "error" not in data, f"Endpoint error: {data.get('error')}"
    assert data["paired_n"] == 10, (
        f"paired_n should be 10 (overlap), got {data.get('paired_n')}. "
        "Gate is using marginal count instead of paired overlap."
    )
    assert data["statistical_power"] == "insufficient", (
        f"statistical_power should be 'insufficient' for paired_n=10, "
        f"got '{data.get('statistical_power')}'. "
        "Gate is using min(rr,lr)=300 instead of paired_n=10."
    )


# ── Test 2: both arms 300 paired → adequate ───────────────────────────────────

def test_paired_overlap_adequate_when_300_paired():
    """Both arms resolved for 300 trades → paired_n=300, power='adequate'."""
    runtime = _make_runtime_with_attribution(
        total_pairs=300,
        ranker_resolved=300,
        ranker_wins=150,
        llm_resolved=300,
        llm_wins=160,
        paired_overlap=300,
    )
    client = _make_client(runtime)

    resp = client.get("/api/attribution/stats")
    assert resp.status_code == 200, f"Got {resp.status_code}: {resp.text}"
    data = resp.json()

    assert "error" not in data, f"Endpoint error: {data.get('error')}"
    assert data["paired_n"] == 300, (
        f"paired_n should be 300, got {data.get('paired_n')}"
    )
    assert data["statistical_power"] == "adequate", (
        f"statistical_power should be 'adequate' for paired_n=300, "
        f"got '{data.get('statistical_power')}'"
    )


# ── Test 3: backward-compat — existing keys still present ────────────────────

def test_existing_response_keys_preserved():
    """Existing keys total_pairs, by_action, by_pair_type, ranker_only, llm_portfolio
    must remain in response (backward-compatibility, scope fence)."""
    runtime = _make_runtime_with_attribution(
        total_pairs=50,
        ranker_resolved=50,
        ranker_wins=25,
        llm_resolved=50,
        llm_wins=28,
        paired_overlap=40,
        by_action={"take": 30, "skip": 20},
        by_pair={"both_taken": 30, "llm_rejected": 20},
    )
    client = _make_client(runtime)

    resp = client.get("/api/attribution/stats")
    assert resp.status_code == 200
    data = resp.json()

    assert "total_pairs" in data
    assert "by_action" in data
    assert "by_pair_type" in data
    assert "ranker_only" in data
    assert "llm_portfolio" in data
    assert "statistical_power" in data
    assert "paired_n" in data, "paired_n must be present (additive field)"


# ── Test 4: _meta envelope passthrough (skip if Task 8/9 not landed) ──────────

def test_meta_envelope_passthrough_if_shipped():
    """If Task 8/9 have shipped cohort_meta, /api/attribution/stats should include _meta.

    Spec Task 9: /api/attribution/stats emits cohort='attribution.pairs'.
    This test is intentionally lenient — skip if _meta key absent (T8/T9 not yet merged).
    """
    runtime = _make_runtime_with_attribution(
        total_pairs=10,
        ranker_resolved=10,
        ranker_wins=5,
        llm_resolved=10,
        llm_wins=6,
        paired_overlap=8,
    )
    client = _make_client(runtime)

    resp = client.get("/api/attribution/stats")
    assert resp.status_code == 200
    data = resp.json()

    if "_meta" in data:
        assert data["_meta"].get("cohort") == "attribution.pairs", (
            f"_meta.cohort should be 'attribution.pairs', got {data['_meta'].get('cohort')}"
        )


# ── Test 5: Frontend source snapshot — label uses pairedN not total ───────────

def test_frontend_label_uses_paired_n_variable():
    """Attribution.jsx powerLabel must interpolate pairedN (not total) when insufficient.

    Source-level snapshot: verifies the JSX template literal reads
    `Insufficient (${pairedN}/200)` — i.e., uses the paired-overlap variable,
    not the total_pairs variable.
    """
    import pathlib
    jsx_path = pathlib.Path(__file__).parents[2] / "frontend" / "src" / "pages" / "Attribution.jsx"
    assert jsx_path.exists(), f"Attribution.jsx not found at {jsx_path}"
    source = jsx_path.read_text(encoding="utf-8")

    assert "pairedN}/200)" in source, (
        "Attribution.jsx label should use `pairedN` variable for the /200 threshold display. "
        f"Found label snippet: {[l.strip() for l in source.splitlines() if '/200' in l]}"
    )
    assert "${total}/200)" not in source, (
        "Attribution.jsx label must not use `total` for the /200 threshold (was the pre-fix bug). "
        "The gate must use paired-overlap count (pairedN), not total_pairs."
    )
