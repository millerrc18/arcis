"""Pending-decision source helpers for the Founder Console DECIDE region (§8).

Called by: src.console.decisions (the aggregator + public API)
Calls: src.utils.db.connect_db, src.analytics.kpis_compute._extract_decision,
       src.api.cloud_routes.kpis_compute._fetch_closed_trades,
       src.metrics.registry (gate metrics — design law #1),
       src.console.gate_targets.GATE_TARGETS
Owns tables: none (read-only over existing tables; never issues DDL)
Config keys: none
Tests: tests/test_console_decisions.py

Each source is ISOLATED and returns ``(source_state, items)``. A failing or
unavailable source degrades to ``("degraded", [])`` — it NEVER fabricates an
item (the honest-degradation law). An unmet-but-healthy gate (capital_advance)
returns ``("ok", [])`` — legitimate emptiness, not degradation.

Split out of decisions.py to keep both modules under the 400-line guardrail
(mirrors the kpis.py / kpis_compute.py split). decisions.py owns aggregation,
record_decision (law #8), the recently-decided trail, and override-rate.
"""
from __future__ import annotations

import json
import math

from src.analytics.kpis_compute import _extract_decision
from src.api.cloud_routes.kpis_compute import _fetch_closed_trades
from src.console.gate_targets import GATE_TARGETS
from src.metrics import registry as metric_registry
from src.utils.db import connect_db


def build_item(*, decision_key, decision_type, title, risk_tier, evidence,
               intent, blast_radius, rollback, as_of=None, source_state="ok"):
    """Assemble one pending item in the canonical contract shape."""
    return {
        "decision_key": decision_key,
        "decision_type": decision_type,
        "title": title,
        "risk_tier": risk_tier,
        "evidence": evidence,
        "intent": intent,
        "blast_radius": blast_radius,
        "rollback": rollback,
        "as_of": as_of,
        "source_state": source_state,
    }


# ── strategy_promotion (REAL) ─────────────────────────────────────────────────

def source_strategy_promotion(decided: set[str]) -> tuple[str, list[dict]]:
    """Pending strategy-promotion proposals from strategy_promotion_events.

    Surfaces gate-proposal rows whose extracted methodology-gate decision is
    'defer'/'promote' and that are not already decided. Evidence is read from
    gate_result_json (DSR/PBO/walkforward). risk_tier is 'high' for a
    promote-to-production proposal, else 'medium'.
    """
    conn = connect_db()
    try:
        rows = conn.execute(
            "SELECT event_id, gate_result_json FROM strategy_promotion_events "
            "WHERE triggered_by = 'gate_proposal'"
        ).fetchall()
    finally:
        conn.close()

    items: list[dict] = []
    for row in rows:
        decision = _extract_decision(row["gate_result_json"])
        if decision not in ("defer", "promote"):
            continue
        decision_key = f"strategy_promotion:{row['event_id']}"
        if decision_key in decided:
            continue
        items.append(build_item(
            decision_key=decision_key,
            decision_type="strategy_promotion",
            title=f"Strategy promotion proposal (gate: {decision})",
            risk_tier="high" if decision == "promote" else "medium",
            evidence=_promotion_evidence(row["gate_result_json"]),
            intent=f"{decision.capitalize()} the candidate strategy per the methodology gate.",
            blast_radius="Promotes a strategy into the live candidate/production set.",
            rollback="Demote the strategy via the promotion CLI.",
        ))
    return "ok", items


def _promotion_evidence(gate_json: str | None) -> dict:
    """Evidence block from gate_result_json (DSR/PBO/walkforward)."""
    parsed: dict = {}
    if gate_json:
        try:
            loaded = json.loads(gate_json)
            parsed = loaded if isinstance(loaded, dict) else {}
        except (json.JSONDecodeError, ValueError):
            parsed = {}
    evidence_items = [
        {"label": label, "value": str(parsed[key])}
        for label, key in (("DSR", "dsr"), ("PBO", "pbo"), ("Walkforward", "walkforward"))
        if key in parsed
    ]
    return {"label": "Methodology gate", "items": evidence_items}


# ── capital_advance (DERIVED — design law #1) ─────────────────────────────────

def source_capital_advance(decided: set[str]) -> tuple[str, list[dict]]:
    """One pending item when EVERY north-star gate metric meets its target.

    Gate values are computed the SAME way the Phase-1 /now/gate route computes
    them: fetch closed trades, build returns / SPY-aligned series, pass them to
    the REGISTERED metrics in src.metrics.registry (design law #1 — no inline
    Sharpe / t-stat / drawdown here), then compare each envelope value to
    GATE_TARGETS. Gate met → one item (capital_advance:phase1, high risk). Gate
    NOT met → nothing, while staying "ok" (legitimate emptiness, not a broken
    source).
    """
    decision_key = "capital_advance:phase1"
    if decision_key in decided:
        return "ok", []

    trades = _fetch_closed_trades()
    returns = [float(t.get("pnl_pct") or 0) / 100.0 for t in trades]
    spy_with_data = [t for t in trades if t.get("spy_return_over_hold") is not None]
    spy_aligned = [float(t.get("pnl_pct") or 0) / 100.0 for t in spy_with_data]
    spy_returns = [float(t.get("spy_return_over_hold") or 0) for t in spy_with_data]

    envelopes = {
        "closed_trade_count": metric_registry.compute_metric(
            "closed_trade_count", trades=trades),
        "excess_sharpe_vs_spy": metric_registry.compute_metric(
            "excess_sharpe_vs_spy", returns=spy_aligned, spy_returns=spy_returns),
        "sharpe_t_stat": metric_registry.compute_metric(
            "sharpe_t_stat", returns=returns),
        "max_drawdown": metric_registry.compute_metric(
            "max_drawdown", returns=returns),
    }
    if not _all_targets_met(envelopes):
        return "ok", []

    evidence_items = [
        {"label": mid, "value": f"{envelopes[mid].get('value')} (target {target})"}
        for mid, target in GATE_TARGETS.items()
    ]
    item = build_item(
        decision_key=decision_key,
        decision_type="capital_advance",
        title="Advance Phase-1 capital — all north-star gates met",
        risk_tier="high",
        evidence={"label": "North-star gate vs targets", "items": evidence_items},
        intent="Advance committed capital past the Phase-1 allocation.",
        blast_radius="Increases capital at risk across the live book.",
        rollback="Revert the allocation to the prior Phase-1 cap.",
    )
    return "ok", [item]


def _all_targets_met(envelopes: dict[str, dict]) -> bool:
    """True iff every gate metric has an ok value meeting its target.

    max_drawdown is lower-is-better (value <= target); every other gate metric
    is higher-is-better (value >= target). A None / non-numeric / NaN / inf
    value fails the gate (a missing metric is never treated as a pass).
    """
    for metric_id, target in GATE_TARGETS.items():
        value = (envelopes.get(metric_id) or {}).get("value")
        if value is None or isinstance(value, bool) or not isinstance(value, (int, float)):
            return False
        if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
            return False
        if metric_id == "max_drawdown":
            if value > target:
                return False
        elif value < target:
            return False
    return True


# ── auditor_halt (REAL, read-only) ────────────────────────────────────────────

def source_auditor_halt(decided: set[str]) -> tuple[str, list[dict]]:
    """Surface the latest audit_reports row when it recommends a halt.

    These are auditor RECOMMENDATIONS to approve/override — distinct from the
    header-owned global PAUSE, which the DECIDE region does NOT own. A halt is
    recommended when overall_assessment == 'red' (driven by a critical flag).
    """
    conn = connect_db()
    try:
        row = conn.execute(
            "SELECT audit_id, overall_assessment, summary, flags "
            "FROM audit_reports ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
    finally:
        conn.close()

    if row is None or (row["overall_assessment"] or "").lower() != "red":
        return "ok", []
    decision_key = f"auditor_halt:{row['audit_id']}"
    if decision_key in decided:
        return "ok", []

    item = build_item(
        decision_key=decision_key,
        decision_type="auditor_halt",
        title="Auditor recommends a halt",
        risk_tier="high",
        evidence=_auditor_evidence(row["summary"], row["flags"]),
        intent="Approve or override the auditor's halt recommendation.",
        blast_radius="Approving halts trading activity per the auditor's finding.",
        rollback="Resume via the operator controls once the finding is addressed.",
    )
    return "ok", [item]


def _auditor_evidence(summary: str | None, flags_json: str | None) -> dict:
    """Evidence block from the audit summary + flags column."""
    evidence_items: list[dict] = []
    if summary:
        evidence_items.append({"label": "Summary", "value": str(summary)})
    if flags_json:
        try:
            flags = json.loads(flags_json)
        except (json.JSONDecodeError, ValueError):
            flags = None
        if isinstance(flags, list):
            for flag in flags:
                if isinstance(flag, dict):
                    evidence_items.append({
                        "label": str(flag.get("severity") or "flag"),
                        "value": str(flag.get("message") or flag.get("summary") or flag),
                    })
    return {"label": "Auditor findings", "items": evidence_items}


# ── degraded sources (honest-degradation law) ─────────────────────────────────

def source_model_challenger() -> tuple[str, list[dict]]:
    """DEGRADED: no queryable pending-challenger-promotion store exists in-repo.

    Honest-degradation law: return ("degraded", []) rather than fabricating a
    challenger decision. FOLLOW-UP: wire a pending-challenger-promotion store
    (or query the model registry for staged challengers) so this can surface
    real items.
    """
    return "degraded", []


def source_ai_dev_approval() -> tuple[str, list[dict]]:
    """DEGRADED: no queryable merge-ask store exists in-repo.

    Honest-degradation law: return ("degraded", []) rather than fabricating a
    merge-approval decision. FOLLOW-UP: surface AI dev-team merge asks once they
    are persisted to a queryable store (currently transient activity events
    only).
    """
    return "degraded", []
