"""Unified decision-queue service for the Founder Console DECIDE region (§8).

Called by: src.api.cloud_routes (DECIDE read/action routes — a later task)
Calls: src.console.decision_sources (the per-source helpers),
       src.utils.db.connect_db, src.utils.activity_logger.log_activity,
       src.api.cloud_routes.kpis_compute._fetch_closed_trades (re-exported for
       the capital_advance source's test seam),
       src.metrics.registry (re-exported; gate metrics are law #1)
Owns tables: none (writes console_decisions, owned by the schema registry;
             this module never issues DDL)
Config keys: none
Tests: tests/test_console_decisions.py

(A) AGGREGATES pending decision items live from real sources (decision_sources).
    Each source is isolated: a failing/unavailable source degrades to
    source_state="degraded" with ZERO items — it NEVER fabricates one
    (honest-degradation law). An unmet-but-healthy gate (capital_advance)
    contributes nothing while staying "ok" — legitimate emptiness.
(B) RECORDS approve/reject/defer verdicts into console_decisions + writes the
    audit trail. See record_decision for the LAW #8 / FINSABER contract.
(C) Computes the recently-decided trail + override-rate.

The source helpers live in src.console.decision_sources (split to keep both
files under the 400-line guardrail); they are re-exported here under their
private aliases so callers and tests interact with one service surface.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

# Re-exported for the test seam + so this module is the single service surface.
from src.api.cloud_routes.kpis_compute import _fetch_closed_trades  # noqa: F401
from src.console import decision_sources as _sources
from src.metrics import registry as metric_registry  # noqa: F401
from src.utils.activity_logger import log_activity
from src.utils.db import connect_db

logger = logging.getLogger(__name__)

# Only low-risk items may ever auto-run. medium/high MUST route to the human; no
# auto-run path is wired this phase — every item surfaces for an explicit
# operator verdict regardless of tier. The frozenset documents the intended
# future boundary, not a live behaviour.
AUTO_RUN_TIERS = frozenset({"low"})

# Private aliases so tests can patch a single service surface (patch.object on
# this module) and so get_pending_decisions resolves the sources via this
# module's namespace.
_source_strategy_promotion = _sources.source_strategy_promotion
_source_capital_advance = _sources.source_capital_advance
_source_auditor_halt = _sources.source_auditor_halt
_source_model_challenger = _sources.source_model_challenger
_source_ai_dev_approval = _sources.source_ai_dev_approval


def _now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _decided_keys() -> set[str]:
    """decision_keys already recorded in console_decisions (for dedupe)."""
    conn = connect_db()
    try:
        rows = conn.execute("SELECT decision_key FROM console_decisions").fetchall()
    finally:
        conn.close()
    return {r["decision_key"] for r in rows}


def get_pending_decisions() -> dict:
    """Aggregate the live pending-decision queue across all sources.

    Returns {"items", "count", "degraded_sources", "as_of"}. Each source is
    isolated: a raising real source is recorded in degraded_sources and
    contributes ZERO items (never fabricated); sources with no queryable store
    are degraded by construction.
    """
    decided = _decided_keys()
    sources = (
        ("strategy_promotion", lambda: _source_strategy_promotion(decided)),
        ("capital_advance", lambda: _source_capital_advance(decided)),
        ("auditor_halt", lambda: _source_auditor_halt(decided)),
        ("model_challenger", _source_model_challenger),
        ("ai_dev_approval", _source_ai_dev_approval),
    )

    items: list[dict] = []
    degraded_sources: list[str] = []
    for name, fn in sources:
        try:
            state, source_items = fn()
        except Exception as exc:  # noqa: BLE001 — any source failure degrades, never crashes
            logger.warning("[console-decide] source %s unavailable: %s", name, exc)
            degraded_sources.append(name)
            continue
        if state == "degraded":
            degraded_sources.append(name)
        items.extend(source_items)

    return {
        "items": items,
        "count": len(items),
        "degraded_sources": degraded_sources,
        "as_of": _now_utc_iso(),
    }


def record_decision(
    decision_key: str,
    decision_type: str,
    action: str,
    risk_tier: str,
    reason: str | None = None,
    evidence: dict | None = None,
    decided_by: str | None = None,
) -> dict:
    """Record a human approve/reject/defer verdict into console_decisions.

    Inserts one row (decided_at = now) and writes the audit trail via
    log_activity. Returns the inserted row as a dict.

    LAW #8 / FINSABER (critical): this records the HUMAN VERDICT ONLY. It MUST
    NOT call any promotion / execution / sizing / risk pipeline. Wiring a
    verdict into an actual promotion/execution pipeline is explicitly a future
    phase — this function deliberately stops at persisting the verdict + audit
    trail.
    """
    now = _now_utc_iso()
    row = {
        "created_at": now,
        "decision_key": decision_key,
        "decision_type": decision_type,
        "action": action,
        "risk_tier": risk_tier,
        "reason": reason,
        "decided_by": decided_by,
        "evidence_json": json.dumps(evidence) if evidence is not None else None,
        "decided_at": now,
    }
    cols = list(row)
    conn = connect_db()
    try:
        conn.execute(
            f"INSERT INTO console_decisions ({', '.join(cols)}) "
            f"VALUES ({', '.join('?' * len(cols))})",
            tuple(row[c] for c in cols),
        )
        conn.commit()
    finally:
        conn.close()

    # Audit trail only — NOT a promotion/execution trigger (law #8).
    log_activity(
        "console_decision",
        f"{action} {decision_type} ({decision_key})",
        metadata={"decision_key": decision_key, "action": action,
                  "risk_tier": risk_tier, "decided_by": decided_by},
    )
    return row


def get_recently_decided(limit: int = 50) -> dict:
    """Most-recently decided records, newest-first.

    Returns {"items", "as_of"}. Reads console_decisions only — the
    recently-decided trail is the persisted verdict log.
    """
    cols = ("id", "created_at", "decision_key", "decision_type", "action",
            "risk_tier", "reason", "decided_by", "evidence_json", "decided_at")
    conn = connect_db()
    try:
        rows = conn.execute(
            f"SELECT {', '.join(cols)} FROM console_decisions "
            "ORDER BY created_at DESC, id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    finally:
        conn.close()

    items = [{c: r[c] for c in cols} for r in rows]
    return {"items": items, "as_of": _now_utc_iso()}


def compute_override_rate() -> dict:
    """Override rate = count(action == 'reject') / total decided over the window.

    Returns {"value", "n", "as_of"}. value is None (honest "no data", NOT 0.0)
    when n == 0, so an empty trail is never reported as a 0% override rate.
    """
    conn = connect_db()
    try:
        rows = conn.execute("SELECT action FROM console_decisions").fetchall()
    finally:
        conn.close()

    total = len(rows)
    if total == 0:
        return {"value": None, "n": 0, "as_of": _now_utc_iso()}
    rejects = sum(1 for r in rows if r["action"] == "reject")
    return {"value": rejects / total, "n": total, "as_of": _now_utc_iso()}
