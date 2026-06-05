"""Tests for the unified decision-queue service (Founder Console P2-T2).

Covers src.console.decisions — the §8 module that (A) aggregates pending
decision items live from real sources, (B) records approve/reject/defer
verdicts into console_decisions + audit-logs them, (C) computes the
recently-decided trail + override-rate.

Design-law assertions enforced:
  honest-degradation — a failing/empty source degrades to source_state=
      "degraded" with ZERO items; it NEVER fabricates items.
  law #1  — capital_advance gate metrics come from src.metrics.registry,
            never recomputed inline.
  law #8 / FINSABER (load-bearing) — record_decision persists the human
            verdict ONLY; it MUST NOT invoke any promotion/execution/
            sizing/risk pipeline.

DB pattern mirrors tests/test_console_pause.py: each service call gets a fresh
PostgresConnectionWrapper via patch(connect_db, side_effect=_make_pg_wrapper)
(the wrapper is closed on __exit__/.close() by the service). An autouse fixture
provisions + wipes the three tables this module touches before AND after every
test so committed rows never leak across tests. The module skips cleanly when
TEST_DATABASE_URL is unset.
"""
from __future__ import annotations

import json
import os
from unittest.mock import patch

import pytest

from src.console import decisions as svc

# ── Skip whole module if TEST_DATABASE_URL is absent ─────────────────────────

TEST_PG_URL = os.environ.get("TEST_DATABASE_URL", "")

pytestmark = pytest.mark.skipif(
    not TEST_PG_URL.startswith("postgres"),
    reason="integration(authoritative-coverage:pg-tests)",
)


# ── Connection + table helpers ────────────────────────────────────────────────

def _make_pg_wrapper():
    """Return a fresh PostgresConnectionWrapper against the test PG."""
    import psycopg2
    import psycopg2.extras
    from src.utils.db import PostgresConnectionWrapper

    raw = psycopg2.connect(TEST_PG_URL, cursor_factory=psycopg2.extras.RealDictCursor)
    raw.autocommit = False
    return PostgresConnectionWrapper(raw)


def _provision_tables(w) -> None:
    """Create the three tables this module reads/writes via the registry DDL."""
    from src.schema.postgres import generate_create_sql
    from src.schema.registry import TABLES

    for name in ("console_decisions", "strategy_promotion_events", "audit_reports"):
        w.execute(generate_create_sql(TABLES[name]))
    w.commit()


def _wipe_tables(w) -> None:
    for name in ("console_decisions", "strategy_promotion_events", "audit_reports"):
        w.execute(f"DELETE FROM {name}")
    w.commit()


@pytest.fixture(autouse=True)
def _clean_tables():
    """Provision + wipe before each test; wipe after."""
    w = _make_pg_wrapper()
    _provision_tables(w)
    _wipe_tables(w)
    w.close()

    yield

    w2 = _make_pg_wrapper()
    _wipe_tables(w2)
    w2.close()


@pytest.fixture
def patched_db():
    """Route every connect_db() inside the service to a fresh test-PG wrapper.

    Both modules open their own connections (decisions.py for the dedupe set +
    record/read/override-rate; decision_sources.py for the per-source reads), so
    both namespaces' connect_db must be patched.
    """
    with patch("src.console.decisions.connect_db", side_effect=_make_pg_wrapper), \
         patch("src.console.decision_sources.connect_db", side_effect=_make_pg_wrapper):
        yield


# ── seed helpers (commit via a fresh wrapper) ─────────────────────────────────

def _seed_promotion_event(*, event_id, decision, triggered_by="gate_proposal",
                          strategy_id="strat-A"):
    gate_json = json.dumps({
        "methodology_gate": {"decision": decision},
        "dsr": 0.91, "pbo": 0.03, "walkforward": "pass",
    })
    w = _make_pg_wrapper()
    w.execute(
        "INSERT INTO strategy_promotion_events "
        "(event_id, strategy_id, from_status, to_status, triggered_by, "
        " gate_result_json, timestamp) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (event_id, strategy_id, "candidate", "candidate", triggered_by,
         gate_json, "2026-06-01T12:00:00+00:00"),
    )
    w.commit()
    w.close()


def _seed_audit(*, audit_id, assessment, flags=None):
    w = _make_pg_wrapper()
    w.execute(
        "INSERT INTO audit_reports "
        "(audit_id, created_at, audit_date, overall_assessment, summary, flags) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (audit_id, "2026-06-04T16:15:00+00:00", "2026-06-04", assessment,
         "drawdown breach detected", json.dumps(flags or [])),
    )
    w.commit()
    w.close()


def _seed_decision(*, decision_key, decision_type, action, risk_tier="high",
                   created_at="2026-06-04T17:00:00+00:00"):
    w = _make_pg_wrapper()
    w.execute(
        "INSERT INTO console_decisions "
        "(created_at, decision_key, decision_type, action, risk_tier, "
        " reason, decided_by, evidence_json, decided_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (created_at, decision_key, decision_type, action, risk_tier,
         None, "operator", None, created_at),
    )
    w.commit()
    w.close()


def _count_decisions(decision_key) -> int:
    w = _make_pg_wrapper()
    n = w.execute(
        "SELECT COUNT(*) FROM console_decisions WHERE decision_key = ?",
        (decision_key,),
    ).fetchone()[0]
    w.close()
    return int(n)


def _read_decision(decision_key) -> dict | None:
    w = _make_pg_wrapper()
    row = w.execute(
        "SELECT decision_key, decision_type, action, risk_tier, reason, "
        "decided_by, evidence_json, decided_at FROM console_decisions "
        "WHERE decision_key = ?",
        (decision_key,),
    ).fetchone()
    result = dict(row) if row is not None else None
    w.close()
    return result


# ── module constants (no DB) ──────────────────────────────────────────────────

class TestModuleConstants:

    def test_auto_run_tiers_is_low_only(self):
        """medium/high MUST route to the human — only 'low' may auto-run."""
        assert svc.AUTO_RUN_TIERS == frozenset({"low"})
        assert "medium" not in svc.AUTO_RUN_TIERS
        assert "high" not in svc.AUTO_RUN_TIERS

    def test_gate_targets_single_source(self):
        """gate_targets.py is the single-source dict the capital_advance source reads."""
        from src.console.gate_targets import GATE_TARGETS
        assert GATE_TARGETS == {
            "closed_trade_count": 100,
            "excess_sharpe_vs_spy": 0.5,
            "sharpe_t_stat": 2.0,
            "max_drawdown": 0.20,
        }


# ── pending-item contract ─────────────────────────────────────────────────────

_CONTRACT_KEYS = {
    "decision_key", "decision_type", "title", "risk_tier", "evidence",
    "intent", "blast_radius", "rollback", "as_of", "source_state",
}


class TestPendingContract:

    def test_envelope_shape(self, patched_db):
        """get_pending_decisions returns the documented top-level shape."""
        out = svc.get_pending_decisions()
        assert set(out.keys()) == {"items", "count", "degraded_sources", "as_of"}
        assert out["count"] == len(out["items"])
        assert out["as_of"]

    def test_every_item_matches_contract_keys(self, patched_db):
        _seed_promotion_event(event_id=501, decision="defer")
        out = svc.get_pending_decisions()
        assert out["items"], "expected at least the seeded promotion item"
        for item in out["items"]:
            assert set(item.keys()) == _CONTRACT_KEYS, (
                f"item keys {set(item.keys())} != contract {_CONTRACT_KEYS}"
            )
            assert item["risk_tier"] in ("low", "medium", "high")
            assert item["source_state"] in ("ok", "degraded")
            assert "label" in item["evidence"]
            assert isinstance(item["evidence"]["items"], list)


# ── strategy_promotion (REAL) ─────────────────────────────────────────────────

class TestStrategyPromotion:

    def test_defer_event_becomes_pending_item(self, patched_db):
        _seed_promotion_event(event_id=601, decision="defer")
        out = svc.get_pending_decisions()
        keys = [i["decision_key"] for i in out["items"]]
        assert "strategy_promotion:601" in keys
        item = next(i for i in out["items"] if i["decision_key"] == "strategy_promotion:601")
        assert item["decision_type"] == "strategy_promotion"
        assert item["risk_tier"] in ("medium", "high")
        # evidence is sourced from gate_result_json (DSR/PBO/walkforward)
        labels = {e["label"].lower() for e in item["evidence"]["items"]}
        assert any("dsr" in l or "pbo" in l or "walkforward" in l for l in labels)

    def test_promote_to_production_is_high_tier(self, patched_db):
        _seed_promotion_event(event_id=602, decision="promote")
        out = svc.get_pending_decisions()
        item = next(i for i in out["items"] if i["decision_key"] == "strategy_promotion:602")
        assert item["risk_tier"] == "high"

    def test_already_decided_event_is_deduped(self, patched_db):
        """A decision_key already in console_decisions must NOT be re-listed."""
        _seed_promotion_event(event_id=603, decision="defer")
        _seed_decision(decision_key="strategy_promotion:603",
                       decision_type="strategy_promotion", action="approve")
        out = svc.get_pending_decisions()
        keys = [i["decision_key"] for i in out["items"]]
        assert "strategy_promotion:603" not in keys, "decided item must be deduped"

    def test_non_gate_proposal_rows_ignored(self, patched_db):
        """Only triggered_by='gate_proposal' rows are surfaced."""
        _seed_promotion_event(event_id=604, decision="defer",
                              triggered_by="operator_confirm")
        out = svc.get_pending_decisions()
        keys = [i["decision_key"] for i in out["items"]]
        assert "strategy_promotion:604" not in keys


# ── capital_advance (DERIVED, law #1) ─────────────────────────────────────────

class TestCapitalAdvance:

    def _trades_meeting_all_targets(self):
        # 120 winning trades (>100), strong positive returns with small
        # (non-zero) dispersion vs near-flat SPY so excess Sharpe + t-stat
        # clear their bars (Sharpe is undefined for zero-variance returns)
        # while drawdown stays at 0.
        import random
        rng = random.Random(7)
        pnls = [1.2 + rng.uniform(-0.2, 0.2) for _ in range(120)]
        return [
            {"pnl_pct": p, "pnl_dollars": p * 100.0, "spy_return_over_hold": 0.001,
             "actual_exit_time": f"2026-06-01T{i % 24:02d}:00:00+00:00"}
            for i, p in enumerate(pnls)
        ]

    def test_all_targets_met_yields_one_item(self, patched_db):
        trades = self._trades_meeting_all_targets()
        with patch("src.console.decision_sources._fetch_closed_trades", return_value=trades):
            out = svc.get_pending_decisions()
        keys = [i["decision_key"] for i in out["items"]]
        assert "capital_advance:phase1" in keys
        item = next(i for i in out["items"] if i["decision_key"] == "capital_advance:phase1")
        assert item["decision_type"] == "capital_advance"
        assert item["risk_tier"] == "high"

    def test_targets_not_met_contributes_nothing_not_degraded(self, patched_db):
        """Gate not met → legitimately empty (NOT degraded)."""
        with patch("src.console.decision_sources._fetch_closed_trades", return_value=[]):
            out = svc.get_pending_decisions()
        keys = [i["decision_key"] for i in out["items"]]
        assert "capital_advance:phase1" not in keys
        # NOT degraded — an unmet gate is honest emptiness, not a broken source.
        assert "capital_advance" not in out["degraded_sources"]

    def test_capital_advance_uses_registry_not_inline(self, patched_db):
        """law #1: gate metrics must flow through src.metrics.registry."""
        from src.console import decision_sources as ds
        trades = self._trades_meeting_all_targets()
        with patch("src.console.decision_sources._fetch_closed_trades", return_value=trades), \
             patch.object(ds.metric_registry, "compute_metric",
                          wraps=ds.metric_registry.compute_metric) as spy_compute:
            svc.get_pending_decisions()
        called_metrics = {c.args[0] if c.args else c.kwargs.get("metric_id")
                          for c in spy_compute.call_args_list}
        assert {"closed_trade_count", "excess_sharpe_vs_spy",
                "sharpe_t_stat", "max_drawdown"} <= called_metrics


# ── auditor_halt (REAL, read-only) ────────────────────────────────────────────

class TestAuditorHalt:

    def test_red_audit_becomes_pending_item(self, patched_db):
        _seed_audit(audit_id="aud-red-1", assessment="red",
                    flags=[{"severity": "critical", "message": "drawdown breach"}])
        out = svc.get_pending_decisions()
        item = next(i for i in out["items"] if i["decision_key"] == "auditor_halt:aud-red-1")
        assert item["decision_type"] == "auditor_halt"
        assert item["risk_tier"] == "high"

    def test_green_audit_contributes_no_item(self, patched_db):
        _seed_audit(audit_id="aud-green-1", assessment="green")
        out = svc.get_pending_decisions()
        keys = [i["decision_key"] for i in out["items"]]
        assert "auditor_halt:aud-green-1" not in keys

    def test_decided_audit_is_deduped(self, patched_db):
        _seed_audit(audit_id="aud-red-2", assessment="red",
                    flags=[{"severity": "critical"}])
        _seed_decision(decision_key="auditor_halt:aud-red-2",
                       decision_type="auditor_halt", action="reject")
        out = svc.get_pending_decisions()
        keys = [i["decision_key"] for i in out["items"]]
        assert "auditor_halt:aud-red-2" not in keys


# ── degraded sources (honest-degradation law) ─────────────────────────────────

class TestDegradedSources:

    def test_model_challenger_is_degraded_zero_items(self):
        state, items = svc._source_model_challenger()
        assert state == "degraded"
        assert items == []

    def test_ai_dev_approval_is_degraded_zero_items(self):
        state, items = svc._source_ai_dev_approval()
        assert state == "degraded"
        assert items == []

    def test_degraded_sources_listed_in_envelope(self, patched_db):
        out = svc.get_pending_decisions()
        assert "model_challenger" in out["degraded_sources"]
        assert "ai_dev_approval" in out["degraded_sources"]

    def test_failing_real_source_degrades_not_crashes(self, patched_db):
        """A source that raises degrades to degraded — never fabricates."""
        with patch.object(svc, "_source_strategy_promotion",
                          side_effect=RuntimeError("DB down")):
            out = svc.get_pending_decisions()
        assert "strategy_promotion" in out["degraded_sources"]
        # no fabricated items from the broken source
        assert all(not i["decision_key"].startswith("strategy_promotion:")
                   for i in out["items"])


# ── record_decision (law #8 / FINSABER) ───────────────────────────────────────

class TestRecordDecision:

    def test_row_lands_in_console_decisions(self, patched_db):
        with patch.object(svc, "log_activity"):
            row = svc.record_decision(
                decision_key="strategy_promotion:701",
                decision_type="strategy_promotion",
                action="approve",
                risk_tier="high",
                reason="evidence convincing",
                evidence={"dsr": 0.9},
                decided_by="operator",
            )
        # read it back through a SEPARATE connection — non-vacuous proof.
        fetched = _read_decision("strategy_promotion:701")
        assert fetched is not None, "row must persist to console_decisions"
        assert fetched["action"] == "approve"
        assert fetched["risk_tier"] == "high"
        assert fetched["reason"] == "evidence convincing"
        assert fetched["decided_at"]
        assert json.loads(fetched["evidence_json"]) == {"dsr": 0.9}
        # returned row dict mirrors what landed.
        assert row["decision_key"] == "strategy_promotion:701"
        assert row["action"] == "approve"

    def test_record_decision_calls_log_activity(self, patched_db):
        with patch.object(svc, "log_activity") as mock_log:
            svc.record_decision(
                decision_key="auditor_halt:702",
                decision_type="auditor_halt",
                action="reject",
                risk_tier="high",
            )
        assert mock_log.called, "record_decision must write the audit trail via log_activity"

    def test_record_decision_does_not_invoke_promotion_pipeline(self, patched_db):
        """LAW #8 (load-bearing): recording a verdict MUST NOT execute / promote.

        We patch the promotion-gate + an execution-pipeline entrypoint and assert
        record_decision never reaches them. The verdict is recorded; wiring it
        into an actual promotion/execution pipeline is explicitly a future phase.
        """
        with patch.object(svc, "log_activity"), \
             patch("src.methods.promotion_gate.promotion_gate") as mock_gate, \
             patch("src.shadow_trading.executor.open_shadow_trade") as mock_exec:
            svc.record_decision(
                decision_key="strategy_promotion:703",
                decision_type="strategy_promotion",
                action="approve",
                risk_tier="high",
            )
        assert not mock_gate.called, "record_decision must NOT invoke the promotion gate (law #8)"
        assert not mock_exec.called, "record_decision must NOT invoke trade execution (law #8)"
        # and the verdict WAS recorded (the function still does its real job)
        assert _count_decisions("strategy_promotion:703") == 1


# ── get_recently_decided ──────────────────────────────────────────────────────

class TestRecentlyDecided:

    def test_newest_first(self, patched_db):
        _seed_decision(decision_key="k-old",
                       decision_type="strategy_promotion", action="approve",
                       created_at="2026-06-01T10:00:00+00:00")
        _seed_decision(decision_key="k-new",
                       decision_type="auditor_halt", action="reject",
                       created_at="2026-06-05T10:00:00+00:00")
        out = svc.get_recently_decided(limit=50)
        keys = [i["decision_key"] for i in out["items"]]
        assert keys.index("k-new") < keys.index("k-old"), "must be newest-first"
        assert out["as_of"]

    def test_limit_is_respected(self, patched_db):
        for n in range(5):
            _seed_decision(decision_key=f"lim-{n}",
                           decision_type="strategy_promotion", action="approve",
                           created_at=f"2026-06-0{n + 1}T10:00:00+00:00")
        out = svc.get_recently_decided(limit=3)
        assert len(out["items"]) <= 3


# ── compute_override_rate ─────────────────────────────────────────────────────

class TestOverrideRate:

    def test_zero_decided_is_none_not_zero(self, patched_db):
        """Honest 'no data': value is None (NOT 0.0) when nothing decided."""
        out = svc.compute_override_rate()
        assert out["n"] == 0
        assert out["value"] is None
        assert out["as_of"]

    def test_one_reject_in_four_is_quarter(self, patched_db):
        _seed_decision(decision_key="or-1",
                       decision_type="strategy_promotion", action="approve")
        _seed_decision(decision_key="or-2",
                       decision_type="strategy_promotion", action="approve")
        _seed_decision(decision_key="or-3",
                       decision_type="auditor_halt", action="defer")
        _seed_decision(decision_key="or-4",
                       decision_type="auditor_halt", action="reject")
        out = svc.compute_override_rate()
        assert out["n"] == 4
        assert out["value"] == 0.25
