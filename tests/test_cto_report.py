"""Tests for CTO performance report generation."""

from unittest.mock import patch, MagicMock

import pytest
import pytz
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _make_closed_trades(n: int, win_pct: float = 0.5) -> list[dict]:
    """Generate mock closed trade dicts."""
    trades = []
    wins = int(n * win_pct)
    for i in range(n):
        is_win = i < wins
        trades.append({
            "trade_id": f"trade-{i}",
            "ticker": f"T{i % 10}",
            "recommendation_id": f"rec-{i}",
            "actual_entry_price": 100.0,
            "actual_exit_price": 103.0 if is_win else 97.0,
            "pnl_dollars": 3.0 if is_win else -3.0,
            "pnl_pct": 3.0 if is_win else -3.0,
            "exit_reason": "target_1_hit" if is_win else "stop_hit",
            "duration_days": 5,
            "max_favorable_excursion": 4.0 if is_win else 1.0,
            "max_adverse_excursion": -1.0 if is_win else -4.0,
            "planned_shares": 5,
            "earnings_adjacent": 0,
            "status": "closed",
            "order_type": "bracket",
        })
    return trades


def _make_recommendations(n: int) -> list[dict]:
    """Generate mock recommendation dicts."""
    return [
        {
            "recommendation_id": f"rec-{i}",
            "ticker": f"T{i % 10}",
            "priority_score": 70 + (i % 30),
            "confidence_score": 7 + (i % 3),
            "trend_state": "uptrend" if i % 2 == 0 else "strong_uptrend",
            "relative_strength_state": "outperformer",
            "pullback_depth_pct": -5.0 - (i % 5),
            "volume_state": "contracting" if i % 3 == 0 else "normal",
            "market_regime": "calm_uptrend",
            "model_version": "halcyon-v1" if i % 2 == 0 else "base",
        }
        for i in range(n)
    ]


def _patch_cto_deps():
    """Return a dict of patch targets for CTO report dependencies."""
    return {
        "closed": patch("src.journal.store.get_closed_shadow_trades"),
        "open": patch("src.journal.store.get_open_shadow_trades"),
        "all": patch("src.journal.store.get_all_shadow_trades"),
        "recs": patch("src.journal.store.get_recommendations_in_period"),
        "model": patch("src.training.versioning.get_active_model_name"),
        "counts": patch("src.training.versioning.get_training_example_counts"),
        "config": patch("src.config.load_config"),
    }


class TestCTOReportGeneration:
    @patch("src.config.load_config", return_value={"bootcamp": {"enabled": False}})
    @patch("src.training.versioning.get_training_example_counts", return_value={"total": 500, "live": 50, "backfill": 450})
    @patch("src.training.versioning.get_active_model_name", return_value="halcyon-v1")
    @patch("src.journal.store.get_recommendations_in_period")
    @patch("src.journal.store.get_all_shadow_trades")
    @patch("src.journal.store.get_open_shadow_trades")
    @patch("src.journal.store.get_closed_shadow_trades")
    def test_report_structure(self, mock_closed, mock_open, mock_all, mock_recs,
                               mock_model, mock_counts, mock_config):
        from src.evaluation.cto_report import generate_cto_report

        mock_closed.return_value = _make_closed_trades(18, win_pct=0.556)
        mock_open.return_value = _make_closed_trades(5)
        mock_all.return_value = _make_closed_trades(23)
        mock_recs.return_value = _make_recommendations(23)

        report = generate_cto_report(days=7)

        assert "report_period" in report
        assert "system_status" in report
        assert "trade_summary" in report
        assert "by_exit_reason" in report
        assert "by_score_band" in report
        assert "by_sector" in report
        assert "execution_analysis" in report
        assert "signal_quality" in report
        assert "feature_correlations" in report
        assert "training_status" in report

    @patch("src.config.load_config", return_value={"bootcamp": {"enabled": False}})
    @patch("src.training.versioning.get_training_example_counts", return_value={"total": 100, "live": 10, "backfill": 90})
    @patch("src.training.versioning.get_active_model_name", return_value="base")
    @patch("src.journal.store.get_recommendations_in_period")
    @patch("src.journal.store.get_all_shadow_trades")
    @patch("src.journal.store.get_open_shadow_trades")
    @patch("src.journal.store.get_closed_shadow_trades")
    def test_trade_summary_math(self, mock_closed, mock_open, mock_all, mock_recs,
                                 mock_model, mock_counts, mock_config):
        from src.evaluation.cto_report import generate_cto_report

        closed = _make_closed_trades(10, win_pct=0.6)
        mock_closed.return_value = closed
        mock_open.return_value = []
        mock_all.return_value = closed
        mock_recs.return_value = _make_recommendations(10)

        report = generate_cto_report(days=7)
        ts = report["trade_summary"]

        assert ts["trades_closed"] == 10
        assert ts["trades_open"] == 0
        assert ts["win_rate"] == 0.6
        assert ts["total_pnl"] == 6 * 3.0 + 4 * (-3.0)  # 18 - 12 = 6

    @patch("src.config.load_config", return_value={"bootcamp": {"enabled": False}})
    @patch("src.training.versioning.get_training_example_counts", return_value={"total": 0, "live": 0, "backfill": 0})
    @patch("src.training.versioning.get_active_model_name", return_value="base")
    @patch("src.journal.store.get_recommendations_in_period")
    @patch("src.journal.store.get_all_shadow_trades")
    @patch("src.journal.store.get_open_shadow_trades")
    @patch("src.journal.store.get_closed_shadow_trades")
    def test_zero_trades(self, mock_closed, mock_open, mock_all, mock_recs,
                          mock_model, mock_counts, mock_config):
        from src.evaluation.cto_report import generate_cto_report

        mock_closed.return_value = []
        mock_open.return_value = []
        mock_all.return_value = []
        mock_recs.return_value = []

        report = generate_cto_report(days=7)
        ts = report["trade_summary"]

        assert ts["trades_closed"] == 0
        assert ts["win_rate"] == 0
        assert ts["total_pnl"] == 0

    @patch("src.config.load_config", return_value={"bootcamp": {"enabled": False}})
    @patch("src.training.versioning.get_training_example_counts", return_value={"total": 50, "live": 5, "backfill": 45})
    @patch("src.training.versioning.get_active_model_name", return_value="base")
    @patch("src.journal.store.get_recommendations_in_period")
    @patch("src.journal.store.get_all_shadow_trades")
    @patch("src.journal.store.get_open_shadow_trades")
    @patch("src.journal.store.get_closed_shadow_trades")
    def test_all_wins(self, mock_closed, mock_open, mock_all, mock_recs,
                       mock_model, mock_counts, mock_config):
        from src.evaluation.cto_report import generate_cto_report

        closed = _make_closed_trades(5, win_pct=1.0)
        mock_closed.return_value = closed
        mock_open.return_value = []
        mock_all.return_value = closed
        mock_recs.return_value = _make_recommendations(5)

        report = generate_cto_report(days=7)
        assert report["trade_summary"]["win_rate"] == 1.0


class TestStringPnlHandling:
    """Regression test for #341: SQLite returns numeric columns as strings."""

    def test_trade_summary_handles_string_pnl(self):
        from src.evaluation.cto_report import _compute_trade_summary

        # Simulate SQLite returning ALL numeric fields as strings
        winner = {
            "trade_id": "t-1",
            "ticker": "AAPL",
            "recommendation_id": "rec-1",
            "actual_entry_price": "100.0",
            "actual_exit_price": "104.25",
            "pnl_dollars": "42.5",
            "pnl_pct": "4.25",
            "exit_reason": "target_1_hit",
            "duration_days": "5",
            "max_favorable_excursion": "5.0",
            "max_adverse_excursion": "-1.0",
            "planned_shares": "10",
            "earnings_adjacent": "0",
            "status": "closed",
            "order_type": "bracket",
        }
        loser = {
            "trade_id": "t-2",
            "ticker": "MSFT",
            "recommendation_id": "rec-2",
            "actual_entry_price": "200.0",
            "actual_exit_price": "190.0",
            "pnl_dollars": "-10.0",
            "pnl_pct": "-5.0",
            "exit_reason": "stop_hit",
            "duration_days": "3",
            "max_favorable_excursion": "1.0",
            "max_adverse_excursion": "-12.0",
            "planned_shares": "5",
            "earnings_adjacent": "0",
            "status": "closed",
            "order_type": "bracket",
        }

        closed = [winner, loser]
        result = _compute_trade_summary(closed, [], closed)

        # Must not crash (the original bug) and return correct values
        assert result["win_rate"] == 0.5
        assert result["total_pnl"] == 32.5


class TestByExitReason:
    def test_groups_by_reason(self):
        from src.evaluation.cto_report import _compute_by_exit_reason
        closed = _make_closed_trades(10, win_pct=0.5)
        result = _compute_by_exit_reason(closed)
        assert "target_1_hit" in result
        assert "stop_hit" in result
        assert result["target_1_hit"]["count"] == 5
        assert result["stop_hit"]["count"] == 5


class TestByScoreBand:
    def test_score_bands(self):
        from src.evaluation.cto_report import _compute_by_score_band
        closed = _make_closed_trades(10, win_pct=0.5)
        recs = _make_recommendations(10)
        result = _compute_by_score_band(closed, recs)
        assert "90-100" in result
        assert "80-89" in result
        assert "70-79" in result
        assert "below_70" in result


class TestReportFormatting:
    @patch("src.config.load_config", return_value={"bootcamp": {"enabled": False}})
    @patch("src.training.versioning.get_training_example_counts", return_value={"total": 0, "live": 0, "backfill": 0})
    @patch("src.training.versioning.get_active_model_name", return_value="base")
    @patch("src.journal.store.get_recommendations_in_period", return_value=[])
    @patch("src.journal.store.get_all_shadow_trades", return_value=[])
    @patch("src.journal.store.get_open_shadow_trades", return_value=[])
    @patch("src.journal.store.get_closed_shadow_trades", return_value=[])
    def test_format_does_not_crash(self, *mocks):
        from src.evaluation.cto_report import generate_cto_report, format_cto_report

        report = generate_cto_report(days=7)
        text = format_cto_report(report)
        assert "CTO PERFORMANCE REPORT" in text
        assert "TRADE SUMMARY" in text


# ── T9 — A1.B _meta envelope tests for remaining endpoints ───────────────────


def _make_runtime_meta(queries: dict | None = None):
    """Build a minimal mock runtime suitable for _meta endpoint tests."""
    runtime = MagicMock()
    runtime.logger = MagicMock()
    runtime.et = pytz.timezone("US/Eastern")
    queries = queries or {}

    def query_one_side_effect(sql, *args, **kwargs):
        for key, val in queries.items():
            if key in sql:
                return val
        return {"c": 0, "count": 0, "cnt": 0,
                "llm_success": 0, "llm_total": 0,
                "verdict": None, "perplexity": None, "distinct_2": None,
                "build_score": 0, "gate_velocity": 0, "system_health": 0,
                "data_asset_value": 0, "model_quality": 0,
                "research_velocity": 0, "reliability": 0,
                "decay_applied": False, "created_at": ""}

    def query_side_effect(sql, *args, **kwargs):
        return []

    runtime.query_one.side_effect = query_one_side_effect
    runtime.query.side_effect = query_side_effect
    return runtime


def _make_app_client(runtime, module="analytics"):
    app = FastAPI()

    def verify_auth():
        return True

    if module == "analytics":
        from src.api.cloud_routes.analytics import create_router
    elif module == "trades":
        from src.api.cloud_routes.trades import create_router
    elif module == "training":
        from src.api.cloud_routes.training import create_router

    router = create_router(runtime, verify_auth)
    app.include_router(router)
    return TestClient(app, raise_server_exceptions=False)


class TestT9MetaEnvelopes:
    """T9 — A1.B: verify each remaining endpoint emits a valid _meta envelope."""

    def test_shadow_metrics_default_emits_all_closed(self):
        """No desk param → cohort='trades.all_closed'."""
        runtime = _make_runtime_meta()
        runtime.query.side_effect = None
        runtime.query.return_value = [
            {"pnl_dollars": 10.0, "pnl_pct": 1.0},
            {"pnl_dollars": -5.0, "pnl_pct": -0.5},
        ]
        client = _make_app_client(runtime, module="trades")

        resp = client.get("/api/shadow/metrics")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert "_meta" in data, f"_meta missing from /api/shadow/metrics; keys: {list(data)}"
        assert data["_meta"]["cohort"] == "trades.all_closed", (
            f"Expected 'trades.all_closed', got {data['_meta']['cohort']}"
        )

    def test_shadow_metrics_per_desk_cohort(self):
        """§2.3 cohort (Sprint 4 T9 / #SP4-shadow-metrics-live-cohort): _desk_clause now
        returns a 3-tuple `(frag, params, cohort_id)`. desk='live' wires `source='live'`
        SQL filter and emits cohort='trades.live_only'; all other desks emit
        'trades.all_closed'.

        Updated from the Sprint 3 lock that asserted ALL desks emit 'trades.all_closed' —
        that lock was self-marked as a Sprint 4 follow-up target.
        """
        expected_cohort_per_desk = {
            None: "trades.all_closed",
            "swing": "trades.all_closed",
            "live": "trades.live_only",
            "all": "trades.all_closed",
            "research_a": "trades.all_closed",
        }
        for desk, expected_cohort in expected_cohort_per_desk.items():
            runtime = _make_runtime_meta()
            runtime.query.side_effect = None
            runtime.query.return_value = [
                {"pnl_dollars": 10.0, "pnl_pct": 1.0},
            ]
            client = _make_app_client(runtime, module="trades")

            url = "/api/shadow/metrics" if desk is None else f"/api/shadow/metrics?desk={desk}"
            resp = client.get(url)
            assert resp.status_code == 200, f"desk={desk!r}: {resp.text}"
            data = resp.json()
            assert "_meta" in data, (
                f"desk={desk!r}: _meta missing from response; keys: {list(data)}"
            )
            assert data["_meta"]["cohort"] == expected_cohort, (
                f"desk={desk!r}: Expected {expected_cohort!r}, got {data['_meta']['cohort']!r}."
            )

    def test_attribution_stats_emits_attribution_pairs(self):
        """/api/attribution/stats emits cohort='attribution.pairs', n=paired_n."""
        runtime = MagicMock()
        runtime.logger = MagicMock()
        runtime.et = pytz.timezone("US/Eastern")

        def query_one_side_effect(sql, *args, **kwargs):
            sql_s = sql.strip()
            if "ranker_only_outcome != 'pending'" in sql_s and "llm_portfolio_outcome IS NOT NULL" in sql_s:
                return {"c": 7}
            if "ranker_only_outcome != 'pending'" in sql_s:
                return {"c": 10}
            if "ranker_only_outcome = 'win'" in sql_s:
                return {"c": 6}
            if "llm_portfolio_outcome IS NOT NULL" in sql_s:
                return {"c": 10}
            if "llm_portfolio_outcome = 'win'" in sql_s:
                return {"c": 5}
            return {"c": 10}

        runtime.query_one.side_effect = query_one_side_effect
        runtime.query.return_value = []
        client = _make_app_client(runtime, module="analytics")

        resp = client.get("/api/attribution/stats")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert "_meta" in data, f"_meta missing from /api/attribution/stats; keys: {list(data)}"
        assert data["_meta"]["cohort"] == "attribution.pairs", (
            f"Expected 'attribution.pairs', got {data['_meta']['cohort']}"
        )
        assert data["_meta"]["n"] == 7, (
            f"Expected n=paired_n=7, got n={data['_meta']['n']}"
        )

    def test_strategy_detail_emits_trades_strategy(self):
        """/api/strategy-detail/pullback emits cohort='trades.strategy'."""
        runtime = _make_runtime_meta()
        runtime.query.return_value = []
        client = _make_app_client(runtime, module="analytics")

        resp = client.get("/api/strategy-detail/pullback")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert "_meta" in data, f"_meta missing from /api/strategy-detail/pullback; keys: {list(data)}"
        assert data["_meta"]["cohort"] == "trades.strategy", (
            f"Expected 'trades.strategy', got {data['_meta']['cohort']}"
        )

    def test_model_performance_emits_trades_model(self):
        """/api/model-performance emits cohort='trades.model'."""
        runtime = _make_runtime_meta()
        runtime.query.return_value = []
        client = _make_app_client(runtime, module="training")

        resp = client.get("/api/model-performance")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert "_meta" in data, f"_meta missing from /api/model-performance; keys: {list(data)}"
        assert data["_meta"]["cohort"] == "trades.model", (
            f"Expected 'trades.model', got {data['_meta']['cohort']}"
        )

    def test_build_score_emits_cohort_none(self):
        """/api/build-score emits cohort='none' (uniform envelope pattern)."""
        runtime = _make_runtime_meta()
        runtime.query.return_value = []
        client = _make_app_client(runtime, module="analytics")

        resp = client.get("/api/build-score")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert "_meta" in data, f"_meta missing from /api/build-score; keys: {list(data)}"
        assert data["_meta"]["cohort"] == "none", (
            f"Expected 'none', got {data['_meta']['cohort']}"
        )

    def test_health_hshs_per_section_meta(self):
        """/api/health/hshs emits per-section _meta: overall=none, performance=trades.all_closed."""
        runtime = _make_runtime_meta()
        runtime.query.return_value = []
        client = _make_app_client(runtime, module="analytics")

        resp = client.get("/api/health/hshs")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert "_meta" in data, f"_meta missing from /api/health/hshs; keys: {list(data)}"
        assert "overall" in data["_meta"], f"_meta.overall missing; _meta keys: {list(data['_meta'])}"
        assert "performance" in data["_meta"], f"_meta.performance missing; _meta keys: {list(data['_meta'])}"
        assert data["_meta"]["overall"]["cohort"] == "none", (
            f"Expected overall cohort='none', got {data['_meta']['overall']['cohort']}"
        )
        assert data["_meta"]["performance"]["cohort"] == "trades.all_closed", (
            f"Expected performance cohort='trades.all_closed', got {data['_meta']['performance']['cohort']}"
        )

    def test_stress_test_results_emits_stress_scenario(self):
        """/api/stress-test/results per-scenario _meta with cohort='stress.scenario'."""
        import json
        runtime = _make_runtime_meta()
        runtime.query.side_effect = None
        runtime.query.return_value = [
            {"scenario_name": "bear_2022", "total_return_pct": -15.0,
             "max_drawdown_pct": -20.0, "sharpe_ratio": -0.5,
             "monthly_returns_json": json.dumps([1.0, -2.0]),
             "regime_breakdown_json": None, "equity_curve_json": None,
             "trade_count": 10, "win_rate": 0.4, "created_at": "2026-01-01"},
        ]
        client = _make_app_client(runtime, module="analytics")

        resp = client.get("/api/stress-test/results")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert "_meta" in data, f"_meta missing from /api/stress-test/results; keys: {list(data)}"
        assert data["_meta"]["cohort"] == "stress.scenario", (
            f"Expected 'stress.scenario', got {data['_meta']['cohort']}"
        )

    def test_simulation_results_emits_cohort_none(self):
        """/api/simulation/results emits cohort='none' (synthetic data)."""
        runtime = _make_runtime_meta()
        runtime.query.return_value = []
        client = _make_app_client(runtime, module="analytics")

        resp = client.get("/api/simulation/results")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert "_meta" in data, f"_meta missing from /api/simulation/results; keys: {list(data)}"
        assert data["_meta"]["cohort"] == "none", (
            f"Expected 'none', got {data['_meta']['cohort']}"
        )
