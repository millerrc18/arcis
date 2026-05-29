"""Tests for C2/C3/C4/C5: local route parity — routes that existed only in
cloud_routes must also be reachable via the local FastAPI app.

C2: /ib-shadow/summary, /ib-shadow/log, /ib-shadow/health
C3: /strategy-detail/{type}
C4: /system/index  (GET) and /system/index/{name}/mark-reviewed (POST)
C5: /projections/live

PR-690 O14 — value-validation tests below the existence/shape tests pin
mathematical correctness against canonical formulas. Pure-shape tests
(does the endpoint return 200? does it have key X?) cannot catch the
"someone changes the Sharpe formula tomorrow" regression — that's the
explicit O14 finding from the operator review.
"""
from __future__ import annotations

import sqlite3
import tempfile
import os
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from src.analytics.canonical_sharpe import raw_sharpe, rf_adjusted_excess_sharpe


def _noop_auth():
    return None


@pytest.fixture(scope="module")
def client():
    from src.api.app import app, verify_auth
    import src.api.cloud_routes.kpis as kpis_route
    app.dependency_overrides[verify_auth] = _noop_auth
    app.dependency_overrides[kpis_route.verify_auth] = _noop_auth
    yield TestClient(app, raise_server_exceptions=False)
    app.dependency_overrides.pop(verify_auth, None)
    app.dependency_overrides.pop(kpis_route.verify_auth, None)


# ── C2: IB Shadow routes ─────────────────────────────────────────────────────

def test_ib_shadow_summary_exists(client):
    """GET /api/ib-shadow/summary must return 200, not 404."""
    resp = client.get("/api/ib-shadow/summary")
    assert resp.status_code == 200, f"/api/ib-shadow/summary returned {resp.status_code}"


def test_ib_shadow_summary_shape(client):
    """GET /api/ib-shadow/summary must return a dict (not array, not 404 body)."""
    resp = client.get("/api/ib-shadow/summary")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, dict)
    assert "total_shadows" in data


def test_ib_shadow_log_exists(client):
    """GET /api/ib-shadow/log must return 200, not 404."""
    resp = client.get("/api/ib-shadow/log")
    assert resp.status_code == 200, f"/api/ib-shadow/log returned {resp.status_code}"


def test_ib_shadow_log_shape(client):
    """GET /api/ib-shadow/log must return a dict with entries key."""
    resp = client.get("/api/ib-shadow/log")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, dict)
    assert "entries" in data
    assert isinstance(data["entries"], list)


def test_ib_shadow_health_exists(client):
    """GET /api/ib-shadow/health must return 200, not 404."""
    resp = client.get("/api/ib-shadow/health")
    assert resp.status_code == 200, f"/api/ib-shadow/health returned {resp.status_code}"


def test_ib_shadow_health_shape(client):
    """GET /api/ib-shadow/health must return a dict with shadow_mode_enabled key."""
    resp = client.get("/api/ib-shadow/health")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, dict)
    assert "shadow_mode_enabled" in data


# ── C3: Strategy detail route ─────────────────────────────────────────────────

def test_strategy_detail_pullback_exists(client):
    """GET /api/strategy-detail/pullback must return 200, not 404."""
    resp = client.get("/api/strategy-detail/pullback")
    assert resp.status_code == 200, f"/api/strategy-detail/pullback returned {resp.status_code}"


def test_strategy_detail_shape(client):
    """GET /api/strategy-detail/{type} must return dict with trades key."""
    resp = client.get("/api/strategy-detail/pullback")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, dict)
    assert "trades" in data
    assert isinstance(data["trades"], list)


def test_strategy_detail_mean_reversion_exists(client):
    """GET /api/strategy-detail/mean_reversion must return 200, not 404."""
    resp = client.get("/api/strategy-detail/mean_reversion")
    assert resp.status_code == 200, f"/api/strategy-detail/mean_reversion returned {resp.status_code}"


# ── C4: System index route ────────────────────────────────────────────────────

def test_system_index_exists(client):
    """GET /api/system/index must return 200, not 404."""
    resp = client.get("/api/system/index")
    assert resp.status_code == 200, f"/api/system/index returned {resp.status_code}"


def test_system_index_shape(client):
    """GET /api/system/index must return a dict with expected top-level keys."""
    resp = client.get("/api/system/index")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, dict)
    assert "actions" in data
    assert "states" in data
    assert "systems" in data
    assert "decisions" in data
    assert "counts" in data


# ── C5: Projections live route ────────────────────────────────────────────────

def test_projections_live_exists(client):
    """GET /api/projections/live must return 200, not 404."""
    resp = client.get("/api/projections/live")
    assert resp.status_code == 200, f"/api/projections/live returned {resp.status_code}"


def test_projections_live_shape(client):
    """GET /api/projections/live must return a dict with trades key."""
    resp = client.get("/api/projections/live")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, dict)
    assert "trades" in data


# ── PR-690 O14: Route-parity VALUE-VALIDATION tests ───────────────────────────
#
# Pre-O14, the route-parity tests above only confirmed that endpoints exist
# and return 200 with the expected shape. A future change could silently
# replace the Sharpe formula (the very B5 regression that introduced the
# non-canonical mean/std without annualization) and these tests would
# happily pass. The tests below pin numerical outputs against canonical
# formulas applied to fixed input vectors so any silent formula change
# fails CI immediately.

# Reuse the test_kpis.py 35-element returns vector verbatim — keeps the
# value-pinning visible from the same expected-Sharpe value used elsewhere
# in the test suite.
_RETURNS_35_FOR_KPIS = [
    0.012, -0.005, 0.023, 0.008, -0.003, 0.015, 0.019, -0.002,
    0.011, 0.007, -0.006, 0.018, 0.013, -0.001, 0.022, 0.009,
    0.014, -0.004, 0.017, 0.006, 0.021, -0.008, 0.016, 0.010,
    -0.002, 0.020, 0.005, 0.013, -0.003, 0.018, 0.009, 0.014,
    0.007, -0.001, 0.016,
]


def _build_trades_for_kpis(returns: list[float]) -> list[dict]:
    """Build the minimal trade dicts /api/kpis needs to compute Sharpe.

    Each trade carries:
      - pnl_pct → returns[i] * 100 (kpis divides by 100 internally)
      - actual_entry_time / actual_exit_time → satisfy is_fully_instrumented
      - excess_return → satisfy is_fully_instrumented
      - instrumentation_version=3 → pass the v3 filter
      - spy_return_over_hold=None → keep n_spy=0 so the SPY-Sharpe path
        stays in the 'unknown' branch and only rf-Sharpe is value-pinned

    Entry 2026-03-02 / exit 2026-03-04 = 3 trading-days hold; with
    placeholder rf=0.0001 per day, per-trade rf becomes 0.0003.
    """
    return [
        {
            "trade_id": f"t-{i}",
            "pnl_pct": ret * 100.0,
            "actual_entry_time": "2026-03-02T10:00:00",
            "actual_exit_time": "2026-03-04T15:00:00",
            "excess_return": ret * 100.0 - 0.5,
            "instrumentation_version": 3,
            "spy_return_over_hold": None,
        }
        for i, ret in enumerate(returns)
    ]


def test_kpis_value_validation_rf_adjusted_sharpe(client):
    """/api/kpis returns a numerically-correct rf-adjusted excess Sharpe.

    PR-690 O14: pure shape tests cannot catch a formula change. This test
    feeds a fixed 35-element returns vector into the endpoint and pins the
    rf-adjusted Sharpe value to the canonical-Sharpe expectation. Any
    drift — annualization factor, ddof, rf scaling — fails the assertion.

    rf path: get_rf_rate raises KeyError → fall back to placeholder
    _RF_PERIOD=0.0001 per trading day. Hold = 3 trading days
    (2026-03-02 → 2026-03-04 inclusive end-day). rf_per_trade = 0.0003.
    excess[i] = pnl_pct/100 - 0.0003. Then S = annualized canonical Sharpe.
    """
    trades = _build_trades_for_kpis(_RETURNS_35_FOR_KPIS)

    # Compute the expected value by applying canonical_sharpe to the same
    # excess-return series the endpoint produces — this is what makes the
    # test "anti-gaming": the EXPECTED is computed from the canonical
    # module, not a hardcoded number, so if canonical_sharpe itself is
    # changed both sides move together; if the endpoint stops calling
    # canonical_sharpe, only the endpoint side moves and this fails.
    rf_per_trade = 0.0003  # _RF_PERIOD * 3 trading days
    excess = [r - rf_per_trade for r in _RETURNS_35_FOR_KPIS]
    expected_sharpe = rf_adjusted_excess_sharpe(excess, 0.0)
    assert expected_sharpe is not None, "fixture must produce defined Sharpe"

    with patch(
        "src.api.cloud_routes.kpis._fetch_closed_trades", return_value=trades,
    ), patch(
        "src.data_ingestion.risk_free_rate.get_rf_rate",
        side_effect=KeyError("no obs — force placeholder"),
    ):
        resp = client.get("/api/kpis")

    assert resp.status_code == 200
    data = resp.json()

    # Value-pin the Sharpe to canonical (rounded to 4 dp by the endpoint).
    rf_kpi = data["rf_adjusted_excess_sharpe"]
    assert rf_kpi["value"] is not None, (
        f"O14: rf_adjusted_excess_sharpe.value should not be None for a "
        f"35-trade fixture; full payload={rf_kpi!r}"
    )
    assert abs(rf_kpi["value"] - round(expected_sharpe, 4)) < 1e-3, (
        f"O14: /api/kpis rf-Sharpe={rf_kpi['value']} but canonical Sharpe="
        f"{round(expected_sharpe, 4)}. Formula has drifted from canonical_sharpe."
    )

    # n_total and n_spy populated. n_total = full instrumented count;
    # n_spy = subset with spy_return_over_hold (0 in this fixture).
    assert data["n_total"] == 35, (
        f"O14: n_total must equal len(instrumented trades)=35; got "
        f"{data['n_total']}"
    )
    assert data["n_spy"] == 0, (
        f"O14: n_spy must equal len(trades with spy_return_over_hold)=0; "
        f"got {data['n_spy']}"
    )
    assert data["n_trades"] == 35
    # rf_source must reflect the fallback path actually taken.
    assert data["rf_source"] == "placeholder", (
        f"O14: rf_source should be 'placeholder' when get_rf_rate raises; "
        f"got {data['rf_source']!r}"
    )


def test_kpis_value_validation_t_stat_and_ci(client):
    """/api/kpis t_stat and CI computations are numerically pinned.

    PR-690 O14 extension. The Decision-4 traffic-light maps t_stat and
    ci_lower onto GREEN/HOLD/HALT — drift in either of those without a
    drift in S would silently change the operator's deploy decision.
    Pin all three values together.

    PR-690 I3: SE picks up the Lo (2002) autocorrelation factor on the
    rf-excess diff series (q=4). We compute the expected SE by calling
    the same `_lo_2002_autocorr_factor` helper the endpoint uses, so this
    test catches "someone replaced the SE formula" but does NOT lock in
    a magic number that would silently rot if the canonical helper itself
    were updated.

    Sprint-0 Wave 4b KPIS-SE-UNITS: SE is now annualization-corrected
    (Lo 2002 change-of-variable). Expected SE form is now
    sqrt((T + 0.5 * S^2) / N) where T = 252 — was sqrt((1 + 0.5 * S^2) / N)
    pre-fix (units mismatch — pre-fix SE was understated by ~sqrt(252)).
    """
    import math
    from src.api.cloud_routes.kpis import _lo_2002_autocorr_factor, _N_PER_YEAR

    trades = _build_trades_for_kpis(_RETURNS_35_FOR_KPIS)
    with patch(
        "src.api.cloud_routes.kpis._fetch_closed_trades", return_value=trades,
    ), patch(
        "src.data_ingestion.risk_free_rate.get_rf_rate",
        side_effect=KeyError("no obs"),
    ):
        resp = client.get("/api/kpis")

    rf_kpi = resp.json()["rf_adjusted_excess_sharpe"]
    S = rf_kpi["value"]
    n = 35
    # Lo (2002) annualization-corrected IID SE * autocorr factor (q=4) —
    # matches kpis._sharpe_t_stat_and_ci with the rf-excess diff series.
    rf_per_trade = 0.0003  # _RF_PERIOD * 3 trading days
    diff_series = [r - rf_per_trade for r in _RETURNS_35_FOR_KPIS]
    # Wave-4b: annualization-corrected SE form (T + 0.5 S^2)/N rather than
    # the un-annualized (1 + 0.5 S^2)/N — see KPIS-SE-UNITS task brief.
    iid_se = math.sqrt((_N_PER_YEAR + 0.5 * S ** 2) / n)
    se = iid_se * _lo_2002_autocorr_factor(diff_series, q=4)
    expected_t = S / se
    expected_ci_lower = S - 1.96 * se
    expected_ci_upper = S + 1.96 * se

    # The endpoint reports rounded(4) values — compare with appropriate tol.
    assert abs(rf_kpi["ci_lower"] - round(expected_ci_lower, 4)) < 1e-3, (
        f"O14: ci_lower={rf_kpi['ci_lower']} but canonical SE form gives "
        f"{round(expected_ci_lower, 4)}"
    )
    assert abs(rf_kpi["ci_upper"] - round(expected_ci_upper, 4)) < 1e-3, (
        f"O14: ci_upper={rf_kpi['ci_upper']} but canonical SE form gives "
        f"{round(expected_ci_upper, 4)}"
    )
    # p-value must be small for this large S; pin to round(p, 4).
    from math import erfc, sqrt
    expected_p = round(float(erfc(abs(expected_t) / sqrt(2.0))), 4)
    assert rf_kpi["p_value"] == expected_p, (
        f"O14: p_value={rf_kpi['p_value']} but expected={expected_p}"
    )

    # Pin the I3 SE-method markers so a future revert to plain Jobson-Korkie
    # without bumping the marker fails immediately.
    assert rf_kpi.get("se_assumes_iid") is False, (
        f"O14/I3: se_assumes_iid must be False (Lo correction applied); "
        f"got {rf_kpi.get('se_assumes_iid')!r}"
    )
    assert rf_kpi.get("se_method") == "lo_2002_autocorr_corrected_q4", (
        f"O14/I3: se_method must be 'lo_2002_autocorr_corrected_q4'; got "
        f"{rf_kpi.get('se_method')!r}"
    )


def test_projections_live_value_validation_sharpe_and_drawdown(client):
    """/api/projections/live numerical outputs match canonical formulas.

    PR-690 O14 — the operator's exact concern: this is the endpoint where
    "the non-canonical Sharpe in B5 would not be caught — anyone could
    change the formula tomorrow and nothing breaks." Test pins:
      - sharpe → canonical_sharpe.raw_sharpe(pnl_pcts), rounded(3)
      - winRate → wins/total (count-based)
      - netPnl → sum(pnl_dollars)
      - avgReturn → mean(pnl_pcts), rounded(3)
      - maxDD → manually-computed peak-to-trough, rounded(1)

    PR-690 I6 added `_resolve_equity_baseline()` which calls Alpaca first
    for the DD baseline. We force the normalized $100K fallback via a
    raised exception so the DD math is reproducible in CI.
    """
    pnl_pcts = [1.5, -0.8, 2.3, 1.1, -0.4, 0.9, 1.7, -0.2, 1.3, 0.5]
    pnl_dollars = [p * 100.0 for p in pnl_pcts]  # $100/pct keeps DD math clean

    fd, db_path = tempfile.mkstemp(suffix=".sqlite3", prefix="parity_proj_")
    os.close(fd)
    try:
        conn = sqlite3.connect(db_path)
        try:
            conn.execute(
                "CREATE TABLE shadow_trades ("
                "  trade_id TEXT PRIMARY KEY,"
                "  status TEXT,"
                "  pnl_dollars REAL,"
                "  pnl_pct REAL,"
                "  quarantined INTEGER DEFAULT 0,"
                "  actual_exit_time TEXT,"
                "  exit_reason TEXT"
                ")"
            )
            for i, (pct, dollars) in enumerate(zip(pnl_pcts, pnl_dollars)):
                conn.execute(
                    "INSERT INTO shadow_trades (trade_id, status, pnl_dollars, "
                    "pnl_pct, quarantined, actual_exit_time) VALUES (?, ?, ?, ?, ?, ?)",
                    (f"p-{i}", "closed", dollars, pct, 0,
                     f"2026-04-{i+1:02d}T15:00:00"),
                )
            conn.commit()
        finally:
            conn.close()

        # Force the normalized-baseline path so DD math is reproducible.
        with patch("src.api.routes.projections.DB_PATH", db_path), patch(
            "src.shadow_trading.alpaca_adapter.get_account_info",
            side_effect=RuntimeError("alpaca offline — pinning DD to baseline"),
        ):
            resp = client.get("/api/projections/live")

        assert resp.status_code == 200
        data = resp.json()

        # Sharpe — canonical raw_sharpe applied to the exact pnl_pcts vector.
        expected_sharpe = raw_sharpe(pnl_pcts)
        assert expected_sharpe is not None
        assert data["sharpe"] == round(expected_sharpe, 3), (
            f"O14: projections sharpe={data['sharpe']} but canonical "
            f"raw_sharpe={round(expected_sharpe, 3)}. Formula drift detected."
        )

        # winRate — count-based, exact.
        n_wins = sum(1 for p in pnl_dollars if p > 0)
        expected_wr = round(n_wins / len(pnl_dollars), 3)
        assert data["winRate"] == expected_wr, (
            f"O14: projections winRate={data['winRate']} expected {expected_wr}"
        )

        # netPnl — exact sum.
        expected_pnl = round(sum(pnl_dollars), 2)
        assert data["netPnl"] == expected_pnl, (
            f"O14: projections netPnl={data['netPnl']} expected {expected_pnl}"
        )

        # avgReturn — mean of pnl_pcts, rounded(3).
        import statistics
        expected_avg = round(statistics.mean(pnl_pcts), 3)
        assert data["avgReturn"] == expected_avg, (
            f"O14: projections avgReturn={data['avgReturn']} expected "
            f"{expected_avg}"
        )

        # maxDD — peak-to-trough vs starting equity 100000.
        cumulative = 100_000.0
        peak = cumulative
        expected_max_dd = 0.0
        for pnl in pnl_dollars:
            cumulative += pnl
            peak = max(peak, cumulative)
            dd = (peak - cumulative) / peak * 100 if peak > 0 else 0
            expected_max_dd = max(expected_max_dd, dd)
        assert data["maxDD"] == round(expected_max_dd, 1), (
            f"O14: projections maxDD={data['maxDD']} expected "
            f"{round(expected_max_dd, 1)}"
        )

        # trades — count.
        assert data["trades"] == len(pnl_pcts)

        # PR-690 I6 contract: when Alpaca is down, baseline source must be
        # 'normalized_baseline' so the dashboard can flag fallback DD.
        assert data["equitySource"] == "normalized_baseline", (
            f"O14/I6: equitySource must be 'normalized_baseline' when Alpaca "
            f"is down; got {data.get('equitySource')!r}"
        )
        assert data["startingEquity"] == 100_000.0, (
            f"O14/I6: startingEquity must be the named constant when Alpaca "
            f"is down; got {data.get('startingEquity')}"
        )
    finally:
        try:
            os.unlink(db_path)
        except OSError:
            pass
