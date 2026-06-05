"""Tests for the KNOW-region endpoints (P3-T3 — Founder Console Phase 3, Wave A).

Covers all 5 endpoints in src.api.cloud_routes.console_know:
  /api/console/know/ladder        — fund ladder, returned VERBATIM from the service
  /api/console/know/system-map    — system map, returned VERBATIM from the service
  /api/console/know/track-record  — audit-grade headline stats THROUGH the registry
  /api/console/know/ledgers       — open/closed trade ledgers w/ q-search + limit
  /api/console/know/calibration   — recommendation-confidence -> outcome calibration

Design-law assertions enforced:
  law #1  — Sharpe / PSR / win-rate math come from the metric registry or existing
            pure helpers, never recomputed inline.
  law #4  — a source that RAISES degrades to unknown / no_data, NEVER green.
  calibration — REUSES src.evaluation.cto_report._compute_confidence_calibration;
                fail-closed to state='no_data' with EMPTY buckets (NOT zeros) when
                the recommendation_id join yields nothing.

External sources are mocked at the console_know binding site; the only test that
touches the DB is the registration smoke test (mounted real app), which is why the
suite is run with TEST_DATABASE_URL pointing at halcyon-pg-test (never prod).
"""
from __future__ import annotations

from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient


def _make_client():
    """FastAPI TestClient around the console_know router (verify_auth left no-op)."""
    from src.api.cloud_routes import console_know as console_know_route

    app = FastAPI()
    app.dependency_overrides[console_know_route.verify_auth] = lambda: None
    app.include_router(console_know_route.router, prefix="/api")
    return TestClient(app, raise_server_exceptions=True)


# Three closed trades with a recommendation_id so calibration can join, plus the
# fields the registry + pure helpers consume (pnl_pct / pnl_dollars / spy / times).
def _seed_trades():
    return [
        {"trade_id": 1, "recommendation_id": "r1", "ticker": "AAPL",
         "pnl_pct": 1.0, "pnl_dollars": 100.0, "spy_return_over_hold": 0.2,
         "exit_reason": "target_hit", "status": "closed",
         "actual_entry_time": "2026-06-01T10:00:00+00:00",
         "actual_exit_time": "2026-06-01T15:00:00+00:00"},
        {"trade_id": 2, "recommendation_id": "r2", "ticker": "TSLA",
         "pnl_pct": -0.5, "pnl_dollars": -50.0, "spy_return_over_hold": 0.1,
         "exit_reason": "stop_hit", "status": "closed",
         "actual_entry_time": "2026-06-02T10:00:00+00:00",
         "actual_exit_time": "2026-06-02T15:00:00+00:00"},
        {"trade_id": 3, "recommendation_id": "r3", "ticker": "AAPL",
         "pnl_pct": 2.0, "pnl_dollars": 200.0, "spy_return_over_hold": -0.1,
         "exit_reason": "target_hit", "status": "closed",
         "actual_entry_time": "2026-06-03T10:00:00+00:00",
         "actual_exit_time": "2026-06-03T15:00:00+00:00"},
    ]


def _seed_recommendations():
    # High / mid / low conviction so calibration bands populate.
    return [
        {"recommendation_id": "r1", "llm_conviction": 9},
        {"recommendation_id": "r2", "llm_conviction": 6},
        {"recommendation_id": "r3", "llm_conviction": 9},
    ]


# ── /api/console/know/ladder ─────────────────────────────────────────────────

class TestLadder:

    def test_ladder_200(self):
        client = _make_client()
        resp = client.get("/api/console/know/ladder")
        assert resp.status_code == 200

    def test_ladder_returned_verbatim_from_service(self):
        """The route returns generate_fund_ladder() VERBATIM (no reshape)."""
        sentinel = {"ladder": [], "current_phase": 1, "generation_ok": True,
                    "failed_sources": [], "source_sha": "deadbee", "as_of": "X"}
        client = _make_client()
        with patch(
            "src.api.cloud_routes.console_know.generate_fund_ladder",
            return_value=sentinel,
        ) as mock_gen:
            data = client.get("/api/console/know/ladder").json()
        assert mock_gen.called
        assert data == sentinel, "ladder must be the service envelope verbatim"


# ── /api/console/know/system-map ─────────────────────────────────────────────

class TestSystemMap:

    def test_system_map_200(self):
        client = _make_client()
        resp = client.get("/api/console/know/system-map")
        assert resp.status_code == 200

    def test_system_map_returned_verbatim_from_service(self):
        sentinel = {"capabilities": {"state": "ok"}, "schema": {"state": "ok"},
                    "generation_ok": True, "source_sha": "cafe", "as_of": "Y"}
        client = _make_client()
        with patch(
            "src.api.cloud_routes.console_know.generate_system_map",
            return_value=sentinel,
        ) as mock_gen:
            data = client.get("/api/console/know/system-map").json()
        assert mock_gen.called
        assert data == sentinel, "system-map must be the service envelope verbatim"


# ── /api/console/know/track-record ───────────────────────────────────────────

class TestTrackRecord:

    def test_track_record_200(self):
        client = _make_client()
        with patch(
            "src.api.cloud_routes.console_know._fetch_closed_trades", return_value=[]
        ):
            resp = client.get("/api/console/know/track-record")
        assert resp.status_code == 200

    def test_track_record_metrics_carry_full_envelope(self):
        """Every wired metric carries {value,n,as_of,cohort,unit,state}."""
        client = _make_client()
        with patch(
            "src.api.cloud_routes.console_know._fetch_closed_trades",
            return_value=_seed_trades(),
        ):
            data = client.get("/api/console/know/track-record").json()
        metrics = data["metrics"]
        # Registry-sourced headline stats must be present.
        for mid in ("rf_adjusted_sharpe", "excess_sharpe_vs_spy", "win_rate",
                    "max_drawdown", "closed_trade_count"):
            assert mid in metrics, f"missing track-record metric {mid}"
            env = metrics[mid]
            for k in ("value", "n", "as_of", "cohort", "unit", "state"):
                assert k in env, f"{mid} envelope missing key {k}"

    def test_track_record_shape(self):
        """Top-level shape: metrics / unavailable / equity_curve / cto link / as_of."""
        client = _make_client()
        with patch(
            "src.api.cloud_routes.console_know._fetch_closed_trades",
            return_value=_seed_trades(),
        ):
            data = client.get("/api/console/know/track-record").json()
        assert isinstance(data["metrics"], dict)
        assert isinstance(data["unavailable"], list)
        assert data["cto_report_link"] == "/api/cto-report"
        assert "as_of" in data
        # equity_curve is a list of {t, equity} or null.
        ec = data["equity_curve"]
        assert ec is None or isinstance(ec, list)
        if isinstance(ec, list) and ec:
            assert "t" in ec[0] and "equity" in ec[0]

    def test_track_record_psr_through_pure_helper(self):
        """PSR is wired via the pure src.methods.psr.psr helper (law #1), not inline.

        Patching the helper at the console_know binding must flow through.
        """
        client = _make_client()
        with patch(
            "src.api.cloud_routes.console_know._fetch_closed_trades",
            return_value=_seed_trades(),
        ), patch(
            "src.api.cloud_routes.console_know.psr_fn", return_value=0.77,
        ) as mock_psr:
            data = client.get("/api/console/know/track-record").json()
        assert mock_psr.called, "PSR must be sourced from the pure psr() helper"
        assert data["metrics"]["psr"]["value"] == 0.77

    def test_track_record_psr_degrades_when_helper_raises(self):
        """PSR helper raising (e.g. <5 obs) -> no_data, never a fabricated number."""
        client = _make_client()
        with patch(
            "src.api.cloud_routes.console_know._fetch_closed_trades",
            return_value=_seed_trades(),
        ), patch(
            "src.api.cloud_routes.console_know.psr_fn",
            side_effect=ValueError("need >=5 obs"),
        ):
            data = client.get("/api/console/know/track-record").json()
        psr_env = data["metrics"]["psr"]
        assert psr_env["value"] is None
        assert psr_env["state"] in ("no_data", "unknown")

    def test_track_record_dsr_is_unavailable(self):
        """dsr has no independent single-source headline -> honest unavailable list."""
        client = _make_client()
        with patch(
            "src.api.cloud_routes.console_know._fetch_closed_trades",
            return_value=_seed_trades(),
        ):
            data = client.get("/api/console/know/track-record").json()
        assert "dsr" in data["unavailable"]
        assert "dsr" not in data["metrics"]

    def test_track_record_degrades_to_unknown_when_source_raises(self):
        """law #4: trade source raising -> degraded, never green."""
        client = _make_client()
        with patch(
            "src.api.cloud_routes.console_know._fetch_closed_trades",
            side_effect=RuntimeError("journal down"),
        ):
            resp = client.get("/api/console/know/track-record")
        assert resp.status_code == 200
        data = resp.json()
        # Every present metric must be unknown/no_data; nothing healthy/green.
        for env in data["metrics"].values():
            assert env["state"] in ("unknown", "no_data")
        assert data["equity_curve"] is None


# ── /api/console/know/ledgers ────────────────────────────────────────────────

class TestLedgers:

    def test_ledgers_closed_200(self):
        client = _make_client()
        with patch(
            "src.api.cloud_routes.console_know._fetch_closed_trades",
            return_value=_seed_trades(),
        ):
            resp = client.get("/api/console/know/ledgers?status=closed")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "closed"
        assert data["n"] == 3
        assert len(data["rows"]) == 3

    def test_ledgers_q_search_filters_by_ticker(self):
        """Server-side q filter is case-insensitive on ticker."""
        client = _make_client()
        with patch(
            "src.api.cloud_routes.console_know._fetch_closed_trades",
            return_value=_seed_trades(),
        ):
            data = client.get("/api/console/know/ledgers?status=closed&q=aapl").json()
        assert data["n"] == 2
        assert all(r["ticker"] == "AAPL" for r in data["rows"])

    def test_ledgers_limit_respected(self):
        client = _make_client()
        with patch(
            "src.api.cloud_routes.console_know._fetch_closed_trades",
            return_value=_seed_trades(),
        ):
            data = client.get("/api/console/know/ledgers?status=closed&limit=1").json()
        assert len(data["rows"]) == 1

    def test_ledgers_open_reads_tradingstate(self):
        """Open ledger reads the canonical TradingState source (#134 paper book)."""
        client = _make_client()
        snapshot = {
            "as_of_et": "2026-06-05T10:00:00-04:00",
            "open_positions": [{"ticker": "NVDA", "trade_id": 9, "status": "open"}],
            "data_source": "test_pg",
        }
        with patch(
            "src.api.cloud_routes.console_know.tradingstate_state",
            return_value=snapshot,
        ) as mock_state:
            data = client.get("/api/console/know/ledgers?status=open").json()
        assert mock_state.called, "open ledger must read the TradingState canonical source"
        assert data["status"] == "open"
        assert data["rows"][0]["ticker"] == "NVDA"

    def test_ledgers_all_combines_open_and_closed(self):
        client = _make_client()
        snapshot = {
            "as_of_et": "2026-06-05T10:00:00-04:00",
            "open_positions": [{"ticker": "NVDA", "trade_id": 9, "status": "open"}],
            "data_source": "test_pg",
        }
        with patch(
            "src.api.cloud_routes.console_know._fetch_closed_trades",
            return_value=_seed_trades(),
        ), patch(
            "src.api.cloud_routes.console_know.tradingstate_state",
            return_value=snapshot,
        ):
            data = client.get("/api/console/know/ledgers?status=all").json()
        assert data["status"] == "all"
        assert data["n"] == 4

    def test_ledgers_open_unavailable_degrades(self):
        """law #4: TradingState raising -> degraded, not an empty 'all good' list."""
        client = _make_client()
        with patch(
            "src.api.cloud_routes.console_know.tradingstate_state",
            side_effect=RuntimeError("state unavailable"),
        ):
            resp = client.get("/api/console/know/ledgers?status=open")
        assert resp.status_code == 200
        data = resp.json()
        assert data["rows"] == []
        assert data.get("state") in ("unknown", "no_data")


# ── /api/console/know/calibration ────────────────────────────────────────────

class TestCalibration:

    def test_calibration_200(self):
        client = _make_client()
        with patch(
            "src.api.cloud_routes.console_know._load_closed_for_calibration",
            return_value=_seed_trades(),
        ), patch(
            "src.api.cloud_routes.console_know._load_recommendations_for_calibration",
            return_value=_seed_recommendations(),
        ):
            resp = client.get("/api/console/know/calibration")
        assert resp.status_code == 200

    def test_calibration_uses_real_recommendation_id_join(self):
        """REUSE _compute_confidence_calibration with the real rec_id->trade join.

        Non-vacuous: the seeded join (2 high-conv wins, 1 mid-conv loss) yields
        populated bands with the documented bucket shape.
        """
        client = _make_client()
        with patch(
            "src.api.cloud_routes.console_know._load_closed_for_calibration",
            return_value=_seed_trades(),
        ), patch(
            "src.api.cloud_routes.console_know._load_recommendations_for_calibration",
            return_value=_seed_recommendations(),
        ):
            data = client.get("/api/console/know/calibration").json()
        assert data["state"] == "ok"
        assert data["join_source"] == "recommendations.recommendation_id->shadow_trades"
        buckets = data["buckets"]
        assert buckets, "buckets must be populated when the join yields rows"
        for b in buckets:
            for k in ("confidence_band", "n", "win_rate", "avg_excess_return", "state"):
                assert k in b, f"bucket missing key {k}"
        # The high-conviction band (8-10) holds the 2 winning trades.
        high = next(b for b in buckets if b["confidence_band"] == "8-10")
        assert high["n"] == 2
        assert high["win_rate"] == 1.0

    def test_calibration_no_join_is_no_data_empty_buckets_not_zeros(self):
        """Fail-closed: no joined rows -> state='no_data' with EMPTY buckets (NOT zeros)."""
        client = _make_client()
        # Recommendations with conviction but trades carry no matching rec_id ->
        # the join yields nothing measurable.
        with patch(
            "src.api.cloud_routes.console_know._load_closed_for_calibration",
            return_value=[{"trade_id": 1, "recommendation_id": None,
                           "pnl_pct": 1.0, "pnl_dollars": 100.0,
                           "exit_reason": "target_hit"}],
        ), patch(
            "src.api.cloud_routes.console_know._load_recommendations_for_calibration",
            return_value=[{"recommendation_id": "rX", "llm_conviction": 9}],
        ):
            data = client.get("/api/console/know/calibration").json()
        assert data["state"] == "no_data"
        assert data["buckets"] == [], "no-join must yield EMPTY buckets, not zero-filled bands"

    def test_calibration_degrades_to_unknown_when_source_raises(self):
        """law #4: a calibration source raising -> unknown, never green."""
        client = _make_client()
        with patch(
            "src.api.cloud_routes.console_know._load_closed_for_calibration",
            side_effect=RuntimeError("store down"),
        ):
            resp = client.get("/api/console/know/calibration")
        assert resp.status_code == 200
        data = resp.json()
        assert data["state"] == "unknown"
        assert data["buckets"] == []


# ── router registration (mounted real app) ───────────────────────────────────

class TestRegistration:

    def test_router_registered_on_app(self):
        """The KNOW router is mounted on the real app at /api/console/know/*."""
        from src.api.app import app

        client = TestClient(app, raise_server_exceptions=True)
        # With the global verify_auth overridden to the no-op in app.py's loop,
        # the route resolves (not 404). It may be 200; it must NOT be 404.
        resp = client.get("/api/console/know/ladder")
        assert resp.status_code != 404, "console_know router must be registered under /api"
