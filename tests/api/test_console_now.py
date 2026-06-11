"""Tests for the NOW-region + honest-header endpoints (T6 — Founder Console P1).

Covers all 7 endpoints in src.api.cloud_routes.console_now:
  /api/console/header        — version / PAPER / bootcamp-OFF / market / clock
  /api/console/now/gate      — north-star gate metrics via the metric registry
  /api/console/now/signals   — integrity/liveness; law-#4 missing-source alarm
  /api/console/now/positions — open positions via the TradingState canonical source
  /api/console/now/attention — pending-decision COUNT + desk_healthy bool
  /api/console/now/since      — delta band honouring ?hours=N
  /api/console/now/devteam    — AI dev-team activity + this-week stats

Design-law assertions enforced:
  law #1  — gate metrics come from src.metrics.registry, never computed inline.
  law #4  — a MISSING signal is rendered as an explicit unknown/alarmed state,
            NEVER as healthy/green (the load-bearing test_signals_missing_*).
  law #9  — reconciliation signal sources retained break events (break-rate),
            not post-backfill state.
  envelope — every metric value carries {value, n, as_of, cohort, unit, state}
             and NO raw sentinel (999 / -1 / NaN / inf) ever leaks.

External sources are mocked; no real DB / NSSM / Alpaca access is required, so
these tests run without TEST_DATABASE_URL.
"""
from __future__ import annotations

import math
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient


def _make_client():
    """FastAPI TestClient around the console_now router (verify_auth left no-op)."""
    from src.api.cloud_routes.console_now import router

    app = FastAPI()
    app.include_router(router, prefix="/api")
    return TestClient(app, raise_server_exceptions=True)


def _all_envelopes(obj):
    """Yield every dict that looks like a metric/signal envelope (has 'state')."""
    if isinstance(obj, dict):
        if "state" in obj and "value" in obj:
            yield obj
        for v in obj.values():
            yield from _all_envelopes(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _all_envelopes(v)


def _assert_no_sentinel_leaks(payload):
    """No envelope value may be a raw sentinel (999/-1/NaN/inf)."""
    for env in _all_envelopes(payload):
        val = env.get("value")
        if isinstance(val, float):
            assert not math.isnan(val), f"NaN leaked: {env}"
            assert not math.isinf(val), f"inf leaked: {env}"
        if isinstance(val, (int, float)) and not isinstance(val, bool):
            assert val not in (999, -1), f"sentinel {val} leaked: {env}"


# ── /api/console/header ──────────────────────────────────────────────────────

class TestHeader:

    def test_header_200(self):
        client = _make_client()
        resp = client.get("/api/console/header")
        assert resp.status_code == 200

    def test_header_has_version_flags_market_clock(self):
        from src.version import VERSION
        client = _make_client()
        resp = client.get("/api/console/header")
        data = resp.json()
        assert data["version"] == VERSION
        # PAPER + bootcamp-OFF flags present and boolean.
        assert isinstance(data["paper"], bool)
        assert isinstance(data["bootcamp_off"], bool)
        # market state + server clock present.
        assert "market_open" in data
        assert isinstance(data["market_open"], bool)
        assert data["server_clock"], "server_clock must be a non-empty timestamp"

    def test_header_flags_read_from_config_not_hardcoded(self):
        """bootcamp_off must invert config bootcamp.enabled (proves config read)."""
        client = _make_client()
        with patch(
            "src.api.cloud_routes.console_now.load_config",
            return_value={"bootcamp": {"enabled": True}, "live_trading": {"enabled": False}},
        ):
            data = client.get("/api/console/header").json()
        assert data["bootcamp_off"] is False, "bootcamp.enabled=True must yield bootcamp_off=False"
        assert data["paper"] is True, "live_trading.enabled=False must yield paper=True"


# ── /api/console/now/gate ────────────────────────────────────────────────────

class TestGate:

    def test_gate_200(self):
        client = _make_client()
        with patch(
            "src.api.cloud_routes.console_now._fetch_closed_trades", return_value=[]
        ):
            resp = client.get("/api/console/now/gate")
        assert resp.status_code == 200

    def test_gate_degrades_to_unknown_when_source_unavailable(self):
        """DB/source unavailable (e.g. cutover PG down) → HTTP 200 with EVERY gate
        metric in 'unknown' state, NEVER a 500 (design law #4: the sole console
        UI must not break on a DB hiccup). Regression-locks the 2026-06-11 PG-down
        incident where /now/gate 500'd the north-star hero. Boundary-touch: drives
        the real connect_db failure mode (psycopg2.OperationalError)."""
        import psycopg2

        client = _make_client()
        with patch(
            "src.api.cloud_routes.console_now._fetch_closed_trades",
            side_effect=psycopg2.OperationalError("connection to server ... refused"),
        ):
            resp = client.get("/api/console/now/gate")
        assert resp.status_code == 200, (
            f"gate must degrade, not 500, on source failure — got {resp.status_code}"
        )
        body = resp.json()
        for mid in ("closed_trade_count", "excess_sharpe_vs_spy", "sharpe_t_stat", "max_drawdown"):
            assert body["metrics"][mid]["state"] == "unknown", (
                f"{mid} must be 'unknown' on source failure, got {body['metrics'][mid]}"
            )
        # targets still present so the UI can render the bar shell honestly.
        assert body["targets"], "targets must remain present in the degraded envelope"

    def test_gate_metrics_are_registry_sourced_envelopes(self):
        """Each gate metric is a canonical envelope with cohort/unit/state keys."""
        client = _make_client()
        trades = [
            {"pnl_pct": 1.0, "pnl_dollars": 100.0, "spy_return_over_hold": 0.2,
             "actual_exit_time": "2026-06-01T15:00:00+00:00"},
            {"pnl_pct": -0.5, "pnl_dollars": -50.0, "spy_return_over_hold": 0.1,
             "actual_exit_time": "2026-06-02T15:00:00+00:00"},
            {"pnl_pct": 2.0, "pnl_dollars": 200.0, "spy_return_over_hold": -0.1,
             "actual_exit_time": "2026-06-03T15:00:00+00:00"},
        ]
        with patch(
            "src.api.cloud_routes.console_now._fetch_closed_trades", return_value=trades
        ):
            data = client.get("/api/console/now/gate").json()
        metrics = data["metrics"]
        # the four north-star gate metrics must be present.
        for mid in ("closed_trade_count", "excess_sharpe_vs_spy", "sharpe_t_stat", "max_drawdown"):
            assert mid in metrics, f"missing gate metric {mid}"
            env = metrics[mid]
            for k in ("value", "n", "as_of", "cohort", "unit", "state"):
                assert k in env, f"{mid} envelope missing key {k}"
            assert env["cohort"], f"{mid} cohort must be populated"

    def test_gate_as_of_is_real_not_none(self):
        """law/T2-seam: gate metric as_of must be threaded (not None) when data exists."""
        client = _make_client()
        trades = [
            {"pnl_pct": 1.0, "pnl_dollars": 100.0, "spy_return_over_hold": 0.2,
             "actual_exit_time": "2026-06-01T15:00:00+00:00"},
            {"pnl_pct": 2.0, "pnl_dollars": 200.0, "spy_return_over_hold": 0.1,
             "actual_exit_time": "2026-06-03T15:00:00+00:00"},
        ]
        with patch(
            "src.api.cloud_routes.console_now._fetch_closed_trades", return_value=trades
        ):
            data = client.get("/api/console/now/gate").json()
        assert data["metrics"]["closed_trade_count"]["as_of"] is not None

    def test_gate_targets_present(self):
        client = _make_client()
        with patch(
            "src.api.cloud_routes.console_now._fetch_closed_trades", return_value=[]
        ):
            data = client.get("/api/console/now/gate").json()
        assert "targets" in data
        assert "closed_trade_count" in data["targets"]

    def test_gate_no_sentinel_leaks(self):
        client = _make_client()
        with patch(
            "src.api.cloud_routes.console_now._fetch_closed_trades", return_value=[]
        ):
            data = client.get("/api/console/now/gate").json()
        _assert_no_sentinel_leaks(data)


# ── /api/console/now/signals ─────────────────────────────────────────────────

class TestSignals:

    def _healthy_probe(self):
        return {
            "services": {
                "ArcisWatchLoop": {
                    "service": "ArcisWatchLoop", "state": "RUNNING",
                    "heartbeat_fresh": True, "heartbeat_reason": None,
                    "port_listening": None, "recent_error_count": 0, "verdict": "OK",
                },
            },
            "overall": "OK",
            "as_of_et": "2026-06-05T10:00:00-04:00",
        }

    def test_signals_200_healthy(self):
        client = _make_client()
        with patch("src.api.cloud_routes.console_now.healthprobe_check",
                   return_value=self._healthy_probe()), \
             patch("src.api.cloud_routes.console_now.get_break_events", return_value=[]), \
             patch("src.api.cloud_routes.console_now._governor_signal",
                   return_value={"value": 3, "n": 1, "as_of": "2026-06-05T10:00:00+00:00"}):
            resp = client.get("/api/console/now/signals")
        assert resp.status_code == 200

    def test_signals_each_carries_as_of(self):
        client = _make_client()
        with patch("src.api.cloud_routes.console_now.healthprobe_check",
                   return_value=self._healthy_probe()), \
             patch("src.api.cloud_routes.console_now.get_break_events", return_value=[]), \
             patch("src.api.cloud_routes.console_now._governor_signal",
                   return_value={"value": 3, "n": 1, "as_of": "2026-06-05T10:00:00+00:00"}):
            data = client.get("/api/console/now/signals").json()
        for name, sig in data["signals"].items():
            assert "as_of" in sig, f"signal {name} missing as_of"

    def test_signals_missing_heartbeat_is_alarmed_not_green(self):
        """LAW #4 (load-bearing): a missing/unavailable signal source must be
        flagged unknown/alarmed and MUST NOT be reported healthy/green."""
        client = _make_client()
        # healthprobe raises -> heartbeat / feed sources are unavailable.
        with patch("src.api.cloud_routes.console_now.healthprobe_check",
                   side_effect=RuntimeError("probe unavailable")), \
             patch("src.api.cloud_routes.console_now.get_break_events", return_value=[]), \
             patch("src.api.cloud_routes.console_now._governor_signal",
                   return_value={"value": 3, "n": 1, "as_of": "2026-06-05T10:00:00+00:00"}):
            data = client.get("/api/console/now/signals").json()
        hb = data["signals"]["heartbeat"]
        assert hb["state"] in ("unknown", "no_data", "alarmed"), (
            f"missing heartbeat must be unknown/alarmed, got {hb}"
        )
        assert hb.get("healthy") is not True, "missing heartbeat must NOT be healthy"
        assert hb["value"] is None

    def test_signals_missing_governor_is_alarmed_not_green(self):
        """LAW #4: governor source unavailable -> unknown, not healthy."""
        client = _make_client()
        with patch("src.api.cloud_routes.console_now.healthprobe_check",
                   return_value=self._healthy_probe()), \
             patch("src.api.cloud_routes.console_now.get_break_events", return_value=[]), \
             patch("src.api.cloud_routes.console_now._governor_signal",
                   side_effect=RuntimeError("governor down")):
            data = client.get("/api/console/now/signals").json()
        gov = data["signals"]["risk_limits"]
        assert gov["state"] in ("unknown", "no_data", "alarmed")
        assert gov.get("healthy") is not True

    def test_signals_break_rate_uses_get_break_events(self):
        """law #9: reconciliation signal counts retained break events."""
        client = _make_client()
        breaks = [
            {"id": 2, "created_at": "2026-06-05T09:00:00+00:00", "break_type": "orphan",
             "symbol": "AAPL", "detected_at": "2026-06-05T09:00:00+00:00"},
            {"id": 1, "created_at": "2026-06-04T09:00:00+00:00", "break_type": "stale",
             "symbol": "TSLA", "detected_at": "2026-06-04T09:00:00+00:00"},
        ]
        with patch("src.api.cloud_routes.console_now.healthprobe_check",
                   return_value=self._healthy_probe()), \
             patch("src.api.cloud_routes.console_now.get_break_events",
                   return_value=breaks) as mock_breaks, \
             patch("src.api.cloud_routes.console_now._governor_signal",
                   return_value={"value": 3, "n": 1, "as_of": "2026-06-05T10:00:00+00:00"}):
            data = client.get("/api/console/now/signals").json()
        assert mock_breaks.called, "signals must source breaks via get_break_events"
        recon = data["signals"]["reconciliation"]
        assert recon["value"] == 2

    def test_signals_no_sentinel_leaks(self):
        client = _make_client()
        with patch("src.api.cloud_routes.console_now.healthprobe_check",
                   return_value=self._healthy_probe()), \
             patch("src.api.cloud_routes.console_now.get_break_events", return_value=[]), \
             patch("src.api.cloud_routes.console_now._governor_signal",
                   return_value={"value": 3, "n": 1, "as_of": "2026-06-05T10:00:00+00:00"}):
            data = client.get("/api/console/now/signals").json()
        _assert_no_sentinel_leaks(data)


# ── /api/console/now/positions ───────────────────────────────────────────────

class TestPositions:

    def test_positions_reads_tradingstate_canonical_source(self):
        client = _make_client()
        snapshot = {
            "as_of_et": "2026-06-05T10:00:00-04:00",
            "open_positions": [
                {"ticker": "AAPL", "trade_id": 1, "source": "paper", "status": "open",
                 "entry_price": 150.0, "entry_time": "2026-06-01T10:00:00", "quarantined": False},
            ],
            "data_source": "test_pg",
        }
        with patch("src.api.cloud_routes.console_now.tradingstate_state",
                   return_value=snapshot) as mock_state:
            resp = client.get("/api/console/now/positions")
        assert resp.status_code == 200
        assert mock_state.called, "positions must read via the TradingState canonical source"
        data = resp.json()
        assert data["positions"][0]["ticker"] == "AAPL"
        assert data["as_of"] is not None

    def test_positions_unavailable_is_unknown_not_empty_green(self):
        client = _make_client()
        with patch("src.api.cloud_routes.console_now.tradingstate_state",
                   side_effect=RuntimeError("both PG and SQLite unavailable")):
            data = client.get("/api/console/now/positions").json()
        assert data["state"] in ("unknown", "no_data", "alarmed")
        assert data["positions"] is None


# ── /api/console/now/attention ───────────────────────────────────────────────

class TestAttention:

    def test_attention_returns_count_and_desk_healthy(self):
        client = _make_client()
        with patch("src.api.cloud_routes.console_now._pending_decision_count",
                   return_value={"value": 4, "n": 4, "as_of": "2026-06-05T10:00:00+00:00"}):
            resp = client.get("/api/console/now/attention")
        assert resp.status_code == 200
        data = resp.json()
        assert data["pending_count"]["value"] == 4
        assert isinstance(data["desk_healthy"], bool)

    def test_attention_has_no_queue_or_actions(self):
        """SCOPE FENCE: attention is count-only — no decision queue/actions."""
        client = _make_client()
        with patch("src.api.cloud_routes.console_now._pending_decision_count",
                   return_value={"value": 0, "n": 0, "as_of": "2026-06-05T10:00:00+00:00"}):
            data = client.get("/api/console/now/attention").json()
        assert "queue" not in data
        assert "decisions" not in data
        assert "actions" not in data

    def test_attention_single_sourced_from_decisions_service(self):
        """P2-T4(A): pending_count must equal the unified decision-queue count.

        Non-vacuous: seeding decisions service with K=7 must yield
        pending_count.value==7 (different from K=4 in the sibling test above).
        Patch at console_now's binding (where it was imported) to prove
        _pending_decision_count calls get_pending_decisions, not an old source.
        """
        client = _make_client()
        fake_result = {
            "items": [{}] * 7,
            "count": 7,
            "degraded_sources": [],
            "as_of": "2026-06-05T12:00:00+00:00",
        }
        with patch(
            "src.api.cloud_routes.console_now.get_pending_decisions",
            return_value=fake_result,
        ):
            resp = client.get("/api/console/now/attention")
        assert resp.status_code == 200
        data = resp.json()
        assert data["pending_count"]["value"] == 7, (
            f"pending_count.value should equal decisions queue count (7), got {data['pending_count']['value']}"
        )
        assert data["pending_count"]["n"] == 7
        assert data["desk_healthy"] is False  # 7 > 0 => not healthy

    def test_attention_degradation_preserved_when_decisions_service_raises(self):
        """P2-T4(A): when decisions service raises, attention returns unknown
        envelope + desk_healthy=False (honest degradation, design law #4).
        """
        client = _make_client()
        with patch(
            "src.api.cloud_routes.console_now.get_pending_decisions",
            side_effect=RuntimeError("decisions service unavailable"),
        ):
            resp = client.get("/api/console/now/attention")
        assert resp.status_code == 200
        data = resp.json()
        assert data["desk_healthy"] is False, "degraded source must set desk_healthy=False"
        pc = data["pending_count"]
        assert pc["value"] is None, "degraded source must yield unknown envelope (value=None)"
        assert pc.get("state") == "unknown"


class TestGateTargetsSingleSourced:
    """P2-T4(B): /now/gate targets must come from src.console.gate_targets.GATE_TARGETS."""

    def test_gate_targets_use_canonical_values(self):
        """/now/gate targets match the canonical GATE_TARGETS values exactly."""
        client = _make_client()
        with patch(
            "src.api.cloud_routes.console_now._fetch_closed_trades", return_value=[]
        ):
            data = client.get("/api/console/now/gate").json()
        targets = data["targets"]
        assert targets["closed_trade_count"] == 100
        assert targets["excess_sharpe_vs_spy"] == 0.5
        assert targets["sharpe_t_stat"] == 2.0
        assert targets["max_drawdown"] == 0.20

    def test_gate_targets_sourced_from_gate_targets_module(self):
        """P2-T4(B): console_now imports GATE_TARGETS from src.console.gate_targets.

        Mutating the module-level GATE_TARGETS dict must flow through to the
        endpoint (proves single-source, not a local copy).
        """
        import src.console.gate_targets as _gt
        import src.api.cloud_routes.console_now as _cn
        # The module-level object in console_now must be the same object as
        # GATE_TARGETS in gate_targets — same id() proves import, not copy.
        assert _cn.GATE_TARGETS is _gt.GATE_TARGETS, (
            "console_now.GATE_TARGETS must be the same object as "
            "src.console.gate_targets.GATE_TARGETS (import, not local copy)"
        )


# ── /api/console/now/since ───────────────────────────────────────────────────

class TestSince:

    def test_since_respects_hours_param(self):
        client = _make_client()
        with patch("src.api.cloud_routes.console_now._delta_since") as mock_delta:
            mock_delta.return_value = {"opened": 0, "closed": 0, "alerts_raised": 0,
                                       "alerts_resolved": 0, "audit_changes": 0, "deploys": 0}
            resp = client.get("/api/console/now/since?hours=6")
        assert resp.status_code == 200
        assert mock_delta.called
        # the hours param must flow through to the delta computation.
        _, kwargs = mock_delta.call_args
        passed_hours = kwargs.get("hours")
        if passed_hours is None and mock_delta.call_args[0]:
            passed_hours = mock_delta.call_args[0][0]
        assert passed_hours == 6
        assert resp.json()["hours"] == 6

    def test_since_default_hours(self):
        client = _make_client()
        with patch("src.api.cloud_routes.console_now._delta_since") as mock_delta:
            mock_delta.return_value = {"opened": 0, "closed": 0, "alerts_raised": 0,
                                       "alerts_resolved": 0, "audit_changes": 0, "deploys": 0}
            data = client.get("/api/console/now/since").json()
        assert "hours" in data
        assert data["hours"] > 0


# ── /api/console/now/devteam ─────────────────────────────────────────────────

class TestDevteam:

    def test_devteam_returns_activity(self):
        client = _make_client()
        with patch("src.api.cloud_routes.console_now.get_recent_activity",
                   return_value=[{"id": 1, "category": "dev", "event": "merged PR"}]):
            resp = client.get("/api/console/now/devteam")
        assert resp.status_code == 200
        data = resp.json()
        assert "activity" in data
        assert "this_week" in data

    def test_devteam_this_week_has_pr_regression_scope_keys(self):
        client = _make_client()
        with patch("src.api.cloud_routes.console_now.get_recent_activity",
                   return_value=[]):
            data = client.get("/api/console/now/devteam").json()
        for k in ("prs", "regressions", "scope_violations"):
            assert k in data["this_week"], f"this_week missing {k}"
