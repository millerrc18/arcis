"""DECIDE-region endpoints for the Founder Console (P2-T3).

Called by: src.api.app (router registered at /api/console/decide/*)
Calls: src.console.decisions (get_pending_decisions, record_decision,
       get_recently_decided, compute_override_rate, _decided_keys)
Owns tables: none (delegates entirely to src.console.decisions)
Config keys: none
Tests: tests/api/test_console_decide.py

Thin HTTP surface only — all logic lives in src.console.decisions (P2-T2).

LAW #8 reminder: this router ONLY records the human verdict via the service.
It MUST NOT call any promotion/execution/sizing/risk pipeline.

The override_rate envelope is built inline from compute_override_rate() matching
the Phase-1 metric-envelope shape {value, n, as_of, cohort, unit, state}:
  - when value is None → state="no_data" (honest empty trail, NOT 0.0)
  - else state="ok"
No cohort-taxonomy change is needed; cohort="decisions.all" is fixed here.
"""
from __future__ import annotations

from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from src.console import decisions

router = APIRouter()


def verify_auth() -> None:
    """Local placeholder; app.dependency_overrides[verify_auth] swaps in real auth."""
    return None


class _DecisionRequest(BaseModel):
    decision_key: str
    decision_type: str
    action: Literal["approve", "reject", "defer"]
    risk_tier: Literal["low", "medium", "high"]
    reason: Optional[str] = None
    evidence: Optional[dict] = None


@router.get("/console/decide/pending", dependencies=[Depends(verify_auth)])
def get_pending() -> dict:
    """Return the live pending-decision queue verbatim from the service.

    Response: {items, count, degraded_sources, as_of}
    Each item carries: {decision_key, decision_type, title, risk_tier,
    evidence:{label, items:[{label,value}]}, intent, blast_radius, rollback,
    as_of, source_state}.
    """
    return decisions.get_pending_decisions()


@router.post("/console/decide/action", dependencies=[Depends(verify_auth)])
def post_action(body: _DecisionRequest) -> dict:
    """Record a human approve/reject/defer verdict via the service.

    Returns {recorded: true, decision: <row dict>, as_of: iso}.
    HTTP 409 if the decision_key is already decided (duplicate guard).
    HTTP 422 from FastAPI automatically for invalid action/risk_tier values.

    LAW #8: records the verdict only — never calls promotion/execution pipeline.
    """
    already_decided = decisions._decided_keys()
    if body.decision_key in already_decided:
        raise HTTPException(
            status_code=409,
            detail=f"decision_key '{body.decision_key}' has already been decided",
        )
    row = decisions.record_decision(
        decision_key=body.decision_key,
        decision_type=body.decision_type,
        action=body.action,
        risk_tier=body.risk_tier,
        reason=body.reason,
        evidence=body.evidence,
        decided_by=None,
    )
    from datetime import datetime, timezone
    return {
        "recorded": True,
        "decision": row,
        "as_of": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/console/decide/decided", dependencies=[Depends(verify_auth)])
def get_decided() -> dict:
    """Return recently-decided trail + override_rate envelope.

    Response: {items, override_rate: {value, n, as_of, cohort, unit, state}, as_of}
    override_rate.state == 'no_data' when n==0 (honest empty trail, NOT 0.0).
    override_rate.state == 'ok' when numeric value exists.
    """
    from datetime import datetime, timezone

    recently = decisions.get_recently_decided(limit=50)
    raw_rate = decisions.compute_override_rate()
    rate_value = raw_rate.get("value")
    override_rate = {
        "value": rate_value,
        "n": raw_rate.get("n", 0),
        "as_of": raw_rate.get("as_of"),
        "cohort": "decisions.all",
        "unit": "ratio",
        "state": "no_data" if rate_value is None else "ok",
    }
    return {
        "items": recently.get("items", []),
        "override_rate": override_rate,
        "as_of": datetime.now(timezone.utc).isoformat(),
    }
