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


def _seed_trades_5():
    """Five closed trades — enough observations for psr()/dsr() (>=5 obs)."""
    pcts = [1.0, -0.5, 2.0, 0.8, -0.3]
    out = []
    for i, p in enumerate(pcts, start=1):
        out.append({
            "trade_id": i, "recommendation_id": f"r{i}", "ticker": "AAPL",
            "pnl_pct": p, "pnl_dollars": p * 100.0,
            "spy_return_over_hold": 0.1, "exit_reason": "target_hit",
            "status": "closed",
            "actual_entry_time": f"2026-06-0{i}T10:00:00+00:00",
            "actual_exit_time": f"2026-06-0{i}T15:00:00+00:00",
        })
    return out


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
            "src.api.cloud_routes.console_know_metrics.psr_fn", return_value=0.77,
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
            "src.api.cloud_routes.console_know_metrics.psr_fn",
            side_effect=ValueError("need >=5 obs"),
        ):
            data = client.get("/api/console/know/track-record").json()
        psr_env = data["metrics"]["psr"]
        assert psr_env["value"] is None
        assert psr_env["state"] in ("no_data", "unknown")

    def test_track_record_dsr_is_a_real_metric_not_unavailable(self):
        """dsr is now a real headline metric (honest no_data when uncomputable)."""
        client = _make_client()
        with patch(
            "src.api.cloud_routes.console_know._fetch_closed_trades",
            return_value=_seed_trades(),
        ):
            data = client.get("/api/console/know/track-record").json()
        assert "dsr" not in data["unavailable"]
        assert "dsr" in data["metrics"]
        env = data["metrics"]["dsr"]
        for k in ("value", "n", "as_of", "cohort", "unit", "state"):
            assert k in env, f"dsr envelope missing key {k}"

    def test_track_record_dsr_ok_when_enough_trades_and_trials(self):
        """>=5 trades + positive n_trials -> dsr state='ok', value in (0,1)."""
        client = _make_client()
        with patch(
            "src.api.cloud_routes.console_know._fetch_closed_trades",
            return_value=_seed_trades_5(),
        ), patch(
            "src.api.cloud_routes.console_know.sum_n_trials", return_value=7,
        ):
            data = client.get("/api/console/know/track-record").json()
        env = data["metrics"]["dsr"]
        assert env["state"] == "ok"
        assert env["value"] is not None
        assert 0.0 < env["value"] < 1.0
        assert env["unit"] == "probability"

    def test_track_record_dsr_no_data_when_too_few_trades(self):
        """<5 trades -> dsr() raises -> honest no_data with value None (not fabricated)."""
        client = _make_client()
        with patch(
            "src.api.cloud_routes.console_know._fetch_closed_trades",
            return_value=_seed_trades(),  # only 3 trades
        ), patch(
            "src.api.cloud_routes.console_know.sum_n_trials", return_value=7,
        ):
            data = client.get("/api/console/know/track-record").json()
        env = data["metrics"]["dsr"]
        assert env["value"] is None
        assert env["state"] == "no_data"

    def test_track_record_dsr_no_data_when_empty_trials(self):
        """Empty trials_registry (sum=0) -> n_trials<1 -> honest no_data, value None."""
        client = _make_client()
        with patch(
            "src.api.cloud_routes.console_know._fetch_closed_trades",
            return_value=_seed_trades_5(),
        ), patch(
            "src.api.cloud_routes.console_know.sum_n_trials", return_value=0,
        ):
            data = client.get("/api/console/know/track-record").json()
        env = data["metrics"]["dsr"]
        assert env["value"] is None
        assert env["state"] == "no_data"

    def test_track_record_dsr_uses_n_trials_sum_not_count(self):
        """n_trials is SUM(n_params_searched), not COUNT(*): the value passed to
        dsr() must be the summed parameter count (20 for two 10-param trials)."""
        client = _make_client()
        captured = {}

        def _capture_dsr(returns, n_trials):
            captured["n_trials"] = n_trials
            return 0.6

        with patch(
            "src.api.cloud_routes.console_know._fetch_closed_trades",
            return_value=_seed_trades_5(),
        ), patch(
            "src.api.cloud_routes.console_know.sum_n_trials", return_value=20,
        ), patch(
            "src.api.cloud_routes.console_know_metrics.dsr_fn", side_effect=_capture_dsr,
        ):
            data = client.get("/api/console/know/track-record").json()
        assert captured["n_trials"] == 20, "dsr must receive SUM(n_params_searched)=20"
        assert data["metrics"]["dsr"]["value"] == 0.6

    def test_track_record_dsr_unknown_when_trade_source_raises(self):
        """law #4: a dead trade source makes dsr unknown too (in the fail-closed branch)."""
        client = _make_client()
        with patch(
            "src.api.cloud_routes.console_know._fetch_closed_trades",
            side_effect=RuntimeError("journal down"),
        ):
            data = client.get("/api/console/know/track-record").json()
        assert "dsr" in data["metrics"]
        assert data["metrics"]["dsr"]["state"] in ("unknown", "no_data")
        assert data["metrics"]["dsr"]["value"] is None

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


# ── /api/console/know/scorecards ─────────────────────────────────────────────

class TestScorecards:

    def test_scorecards_returns_aggregator_verbatim(self):
        """The route returns get_agent_scorecards() VERBATIM (no reshape)."""
        sentinel = {
            "per_role": {"developer": {"n": 3, "success_rate": 0.67,
                                       "rework_rate": 0.33, "escalation_rate": 0.0,
                                       "blocked_rate": 0.0, "scope_violations": 1,
                                       "avg_review_cycles": 1.0}},
            "per_task_type": {},
            "scope_drift": {"total_scope_violations": 1, "n": 3},
            "n": 3, "state": "ok", "as_of": "2026-06-08T00:00:00+00:00",
        }
        client = _make_client()
        with patch(
            "src.api.cloud_routes.console_know.get_agent_scorecards",
            return_value=sentinel,
        ) as mock_sc:
            resp = client.get("/api/console/know/scorecards")
        assert resp.status_code == 200
        assert mock_sc.called
        assert resp.json() == sentinel, "scorecards must be the aggregator dict verbatim"

    def test_scorecards_degrades_to_unknown_when_source_raises(self):
        """law #4: aggregator raising -> state='unknown', never green/empty-OK."""
        client = _make_client()
        with patch(
            "src.api.cloud_routes.console_know.get_agent_scorecards",
            side_effect=RuntimeError("agent_task_outcomes down"),
        ):
            resp = client.get("/api/console/know/scorecards")
        assert resp.status_code == 200
        data = resp.json()
        assert data["state"] == "unknown"
        assert data["per_role"] == {}
        assert data["per_task_type"] == {}
        assert data["scope_drift"] == {"total_scope_violations": 0, "n": 0}
        assert data["n"] == 0
        assert "as_of" in data


# ── /api/console/know/rigor-metrics ──────────────────────────────────────────

class TestRigorMetrics:

    def test_rigor_metrics_canonical_envelopes(self):
        """psr / dsr / pbo each carry the canonical {value,n,as_of,cohort,unit,state}."""
        client = _make_client()
        with patch(
            "src.api.cloud_routes.console_know._fetch_closed_trades",
            return_value=_seed_trades_5(),
        ), patch(
            "src.api.cloud_routes.console_know.sum_n_trials", return_value=7,
        ):
            resp = client.get("/api/console/know/rigor-metrics")
        assert resp.status_code == 200
        data = resp.json()
        for key in ("psr", "dsr", "pbo"):
            assert key in data, f"rigor-metrics missing {key}"
            env = data[key]
            for k in ("value", "n", "as_of", "cohort", "unit", "state"):
                assert k in env, f"{key} envelope missing key {k}"
        assert "as_of" in data
        # psr/dsr computed from 5 obs -> ok with a real probability.
        assert data["psr"]["state"] == "ok"
        assert 0.0 < data["psr"]["value"] < 1.0
        assert data["dsr"]["state"] == "ok"
        assert 0.0 < data["dsr"]["value"] < 1.0

    def test_rigor_metrics_pbo_insufficient_configs_path(self):
        """PBO with 0 backtested configs -> insufficient_configs, value None (not fabricated)."""
        client = _make_client()
        pbo_env = {
            "value": None, "n": 0, "as_of": "2026-06-08T00:00:00+00:00",
            "cohort": "rigor", "unit": "probability",
            "state": "insufficient_configs",
        }
        with patch(
            "src.api.cloud_routes.console_know._fetch_closed_trades",
            return_value=_seed_trades_5(),
        ), patch(
            "src.api.cloud_routes.console_know.sum_n_trials", return_value=7,
        ), patch(
            "src.api.cloud_routes.console_know.build_pbo_envelope",
            return_value=pbo_env,
        ) as mock_pbo:
            data = client.get("/api/console/know/rigor-metrics").json()
        assert mock_pbo.called, "PBO must be sourced from build_pbo_envelope() verbatim"
        assert data["pbo"]["state"] in ("insufficient_configs", "no_data")
        assert data["pbo"]["value"] is None

    def test_rigor_metrics_pbo_returned_verbatim(self):
        """build_pbo_envelope() result flows through unchanged (law #1: no reshape)."""
        client = _make_client()
        pbo_env = {
            "value": 0.42, "n": 4, "as_of": "2026-06-08T00:00:00+00:00",
            "cohort": "rigor", "unit": "probability", "state": "ok",
        }
        with patch(
            "src.api.cloud_routes.console_know._fetch_closed_trades",
            return_value=_seed_trades_5(),
        ), patch(
            "src.api.cloud_routes.console_know.sum_n_trials", return_value=7,
        ), patch(
            "src.api.cloud_routes.console_know.build_pbo_envelope",
            return_value=pbo_env,
        ):
            data = client.get("/api/console/know/rigor-metrics").json()
        assert data["pbo"] == pbo_env

    def test_rigor_metrics_dsr_no_data_when_trade_source_raises(self):
        """law #4: trade source raising -> psr/dsr degrade to no_data, never green."""
        client = _make_client()
        with patch(
            "src.api.cloud_routes.console_know._fetch_closed_trades",
            side_effect=RuntimeError("journal down"),
        ), patch(
            "src.api.cloud_routes.console_know.build_pbo_envelope",
            return_value={"value": None, "n": 0, "as_of": "X", "cohort": "rigor",
                          "unit": "probability", "state": "insufficient_configs"},
        ):
            resp = client.get("/api/console/know/rigor-metrics")
        assert resp.status_code == 200
        data = resp.json()
        assert data["psr"]["value"] is None
        assert data["psr"]["state"] in ("no_data", "unknown")
        assert data["dsr"]["value"] is None
        assert data["dsr"]["state"] in ("no_data", "unknown")
