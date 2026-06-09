"""Agent-task outcome recorder and scorecard aggregator for the Founder Console KNOW region.

Called by: src.api.cloud_routes (KNOW scorecards — a later task), CLI
Calls: src.utils.db.connect_db, src.utils.activity_logger.log_activity
Owns tables: none (writes agent_task_outcomes, owned by the schema registry;
             this module never issues DDL)
Config keys: none
Tests: tests/test_agent_outcomes.py

(A) RECORDS one row per agent-task execution into agent_task_outcomes.
    Validates role + outcome at write time — fail-closed, never silently stores
    garbage (unknown role/outcome raises ValueError before any DB write).
(B) AGGREGATES per-role + per-task-type scorecards for the KNOW scorecards panel.
    Honest-empty contract: empty table returns state='no_data' with per_role=={};
    a role absent from the table is absent from per_role (never fabricates 0.0
    rates — mirrors compute_override_rate returning None at n==0).
(C) CLI: python -m src.console.agent_outcomes record --run-id ... --role ... ...
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from src.utils.activity_logger import log_activity
from src.utils.db import connect_db

logger = logging.getLogger(__name__)

_VALID_ROLES = frozenset({
    "planner", "developer", "qa_reviewer", "security_reviewer",
    "performance_reviewer", "integrator", "documentarian",
})
_VALID_OUTCOMES = frozenset({"success", "rework", "escalation", "blocked"})


def _now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _insert_outcome_row(row: dict) -> None:
    """Write one validated row dict to agent_task_outcomes. Caller must validate first."""
    conn = connect_db()
    try:
        conn.execute(
            "INSERT INTO agent_task_outcomes "
            "(created_at, run_id, task_id, agent_role, task_type, outcome, "
            " rework_count, scope_violation, review_cycles, model) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (row["created_at"], row["run_id"], row["task_id"],
             row["agent_role"], row["task_type"], row["outcome"],
             row["rework_count"], row["scope_violation"],
             row["review_cycles"], row["model"]),
        )
        conn.commit()
    finally:
        conn.close()


def record_agent_outcome(
    run_id: str,
    task_id: str,
    agent_role: str,
    outcome: str,
    task_type: str | None = None,
    rework_count: int = 0,
    scope_violation: bool = False,
    review_cycles: int = 0,
    model: str | None = None,
) -> dict:
    """Insert one row into agent_task_outcomes and write the audit trail.

    Validates agent_role and outcome against their allowed sets; raises
    ValueError on unknown values (fail-closed — never silently stores garbage).
    Returns the inserted row as a dict.

    Plain telemetry only — does NOT call any promotion/execution/training pipeline.
    """
    if agent_role not in _VALID_ROLES:
        raise ValueError(
            f"Unknown agent_role {agent_role!r}. "
            f"Must be one of: {sorted(_VALID_ROLES)}"
        )
    if outcome not in _VALID_OUTCOMES:
        raise ValueError(
            f"Unknown outcome {outcome!r}. "
            f"Must be one of: {sorted(_VALID_OUTCOMES)}"
        )

    row = {
        "created_at": _now_utc_iso(),
        "run_id": run_id,
        "task_id": task_id,
        "agent_role": agent_role,
        "task_type": task_type,
        "outcome": outcome,
        "rework_count": rework_count,
        "scope_violation": 1 if scope_violation else 0,
        "review_cycles": review_cycles,
        "model": model,
    }
    _insert_outcome_row(row)
    log_activity(
        "agent_outcome",
        f"{agent_role} {outcome} ({run_id}/{task_id})",
        metadata={"run_id": run_id, "task_id": task_id,
                  "agent_role": agent_role, "outcome": outcome,
                  "task_type": task_type},
    )
    return row


def _empty_bucket() -> dict:
    return {"n": 0, "success": 0, "rework": 0,
            "escalation": 0, "blocked": 0,
            "scope_violations": 0, "review_cycles_sum": 0}


def _accumulate_row(buckets: dict, key: str, oc: str, sv: int, rc: int) -> None:
    if key not in buckets:
        buckets[key] = _empty_bucket()
    b = buckets[key]
    b["n"] += 1
    if oc in _VALID_OUTCOMES:
        b[oc] += 1
    if sv:
        b["scope_violations"] += 1
    b["review_cycles_sum"] += rc


def _bucket_to_metrics(b: dict) -> dict:
    n = b["n"]
    return {
        "n": n,
        "success_rate": b["success"] / n,
        "rework_rate": b["rework"] / n,
        "escalation_rate": b["escalation"] / n,
        "blocked_rate": b["blocked"] / n,
        "scope_violations": b["scope_violations"],
        "avg_review_cycles": b["review_cycles_sum"] / n,
    }


def get_agent_scorecards() -> dict:
    """Aggregate agent_task_outcomes into per-role + per-task-type scorecards.

    Honest-empty contract: empty table returns state='no_data', per_role=={}.
    A role absent from the table is absent from per_role — never fabricated.
    """
    conn = connect_db()
    try:
        rows = conn.execute(
            "SELECT agent_role, task_type, outcome, scope_violation, review_cycles "
            "FROM agent_task_outcomes"
        ).fetchall()
    finally:
        conn.close()

    total = len(rows)
    if total == 0:
        return {
            "per_role": {},
            "per_task_type": {},
            "scope_drift": {"total_scope_violations": 0, "n": 0},
            "n": 0,
            "state": "no_data",
            "as_of": _now_utc_iso(),
        }

    role_buckets: dict[str, dict] = {}
    type_buckets: dict[str, dict] = {}
    for r in rows:
        sv = r["scope_violation"] or 0
        rc = r["review_cycles"] or 0
        oc = r["outcome"]
        _accumulate_row(role_buckets, r["agent_role"], oc, sv, rc)
        if r["task_type"] is not None:
            _accumulate_row(type_buckets, r["task_type"], oc, sv, rc)

    total_sv = sum(1 for r in rows if r["scope_violation"])
    return {
        "per_role": {k: _bucket_to_metrics(b) for k, b in role_buckets.items()},
        "per_task_type": {k: _bucket_to_metrics(b) for k, b in type_buckets.items()},
        "scope_drift": {"total_scope_violations": total_sv, "n": total},
        "n": total,
        "state": "ok",
        "as_of": _now_utc_iso(),
    }


# ── CLI ───────────────────────────────────────────────────────────────────────


def _build_arg_parser():
    import argparse

    parser = argparse.ArgumentParser(
        prog="python -m src.console.agent_outcomes",
        description="Agent-outcome telemetry recorder for the Founder Console.",
    )
    sub = parser.add_subparsers(dest="command")

    rec = sub.add_parser("record", help="Record one agent-task outcome row.")
    rec.add_argument("--run-id", required=True, help="Coding-team run identifier.")
    rec.add_argument("--task-id", required=True, help="Task ID within the run.")
    rec.add_argument("--role", required=True, dest="agent_role",
                     help=f"Agent role. One of: {sorted(_VALID_ROLES)}")
    rec.add_argument("--outcome", required=True,
                     help=f"Outcome. One of: {sorted(_VALID_OUTCOMES)}")
    rec.add_argument("--task-type", default=None, help="Optional task type label.")
    rec.add_argument("--rework-count", type=int, default=0,
                     help="Number of rework iterations (default 0).")
    rec.add_argument("--scope-violation", action="store_true",
                     help="Flag this task as a scope violation.")
    rec.add_argument("--review-cycles", type=int, default=0,
                     help="Number of review cycles (default 0).")
    rec.add_argument("--model", default=None, help="Model ID used for this task.")
    return parser


if __name__ == "__main__":
    import sys

    parser = _build_arg_parser()
    args = parser.parse_args()
    if args.command == "record":
        try:
            row = record_agent_outcome(
                run_id=args.run_id,
                task_id=args.task_id,
                agent_role=args.agent_role,
                outcome=args.outcome,
                task_type=args.task_type,
                rework_count=args.rework_count,
                scope_violation=args.scope_violation,
                review_cycles=args.review_cycles,
                model=args.model,
            )
            print(
                f"recorded: {row['agent_role']} {row['outcome']} "
                f"({row['run_id']}/{row['task_id']}) at {row['created_at']}"
            )
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            sys.exit(1)
    else:
        parser.print_help()
        sys.exit(1)
