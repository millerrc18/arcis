"""CLI command for operator-driven strategy promotion confirmation.

Called by: src.main (confirm-promotion subcommand)
Calls: src.platform.promotion.promote
Owns tables: none (delegates all DB writes to promote())
Config keys: none
Tests: tests/test_cli_confirm_promotion.py

Design constraint (Critical-1, spec §1.3 + Decision 5):
  This module is a THIN FRONT-END. All gate logic, audit-row writing, and
  justification enforcement are in platform.promotion.promote(). The CLI only
  adds operator-ergonomic pre-checks (justification length, proposal staleness,
  reject guard, y/N prompt).

  Bypass prohibition: the synthetic-outcome path (direct gate_outcome application)
  is FORBIDDEN here. All writes go through promote().
  Do not write strategy_promotion_events rows directly from this module.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone

from src.config import DB_PATH
from src.utils.db import connect_db

_JUSTIFICATION_MIN_CHARS = 40
_PROPOSAL_STALENESS_HOURS = 24


def build_confirm_promotion_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="confirm-promotion",
        description="Confirm a gate_proposal and promote a strategy via promote().",
    )
    parser.add_argument("--strategy", required=True, help="strategy_id to confirm")
    parser.add_argument(
        "--justification", required=True,
        help=f"Justification note (>= {_JUSTIFICATION_MIN_CHARS} chars)",
    )
    parser.add_argument(
        "--target-status", default="shadow_trading",
        help="Target status (default: shadow_trading)",
    )
    parser.add_argument(
        "--yes", "-y", action="store_true",
        help="Skip y/N confirmation prompt",
    )
    parser.add_argument("--db-path", default=DB_PATH, help=argparse.SUPPRESS)
    return parser


def _load_gate_proposal(strategy_id: str, db_path: str) -> tuple[dict | None, int]:
    """Load latest gate_proposal row. Returns (row_dict_or_None, exit_code).

    exit_code 0 = success; 4 = missing or stale.
    """
    conn = connect_db(db_path)
    try:
        row = conn.execute(
            """SELECT event_id, gate_result_json, timestamp
               FROM strategy_promotion_events
               WHERE strategy_id = ? AND triggered_by = 'gate_proposal'
               ORDER BY timestamp DESC LIMIT 1""",
            (strategy_id,),
        ).fetchone()
    finally:
        conn.close()

    if row is None:
        print(
            f"ERROR: No gate_proposal row found for strategy '{strategy_id}'. "
            "Run the daily gate first (watch loop or run-promotion-gate).",
            file=sys.stderr,
        )
        return None, 4

    event_id = row["event_id"] if hasattr(row, "keys") else row[0]
    gate_result_json = row["gate_result_json"] if hasattr(row, "keys") else row[1]
    proposal_ts = row["timestamp"] if hasattr(row, "keys") else row[2]

    try:
        proposal_dt = datetime.fromisoformat(proposal_ts.replace("Z", "+00:00"))
        if proposal_dt.tzinfo is None:
            proposal_dt = proposal_dt.replace(tzinfo=timezone.utc)
    except (ValueError, AttributeError):
        print(f"ERROR: Cannot parse proposal timestamp: {proposal_ts!r}", file=sys.stderr)
        return None, 4

    age_hours = (datetime.now(timezone.utc) - proposal_dt).total_seconds() / 3600
    if age_hours > _PROPOSAL_STALENESS_HOURS:
        print(
            f"ERROR: gate_proposal row is {age_hours:.1f}h old "
            f"(limit: {_PROPOSAL_STALENESS_HOURS}h). "
            "The proposal is stale — re-run the daily gate to generate a fresh proposal.",
            file=sys.stderr,
        )
        return None, 4

    try:
        gate_result = json.loads(gate_result_json) if gate_result_json else {}
    except json.JSONDecodeError:
        gate_result = {}

    return {"event_id": event_id, "timestamp": proposal_ts, "gate_result": gate_result}, 0


def _display_proposal_and_prompt(
    strategy_id: str, proposal: dict, target_status: str,
    justification: str, skip_prompt: bool,
) -> int:
    """Print evidence summary and y/N prompt. Returns exit_code (0=proceed, 1=aborted)."""
    gr = proposal["gate_result"]
    print(f"\n=== Gate Proposal for '{strategy_id}' ===")
    print(f"  Event ID (proposal): {proposal['event_id']}")
    print(f"  Timestamp:           {proposal['timestamp']}")
    print(f"  Decision:            {gr.get('decision', 'unknown')}")
    print(f"  Composed pass:       {gr.get('composed_pass', False)}")
    print(f"  Walkforward status:  {gr.get('walkforward_status', 'n/a')}")
    print(f"  Threshold used:      {gr.get('threshold_used', 'n/a')}")
    votes = gr.get("votes", {})
    if votes:
        print(f"  Votes:               {votes}")
    print(f"\n  Target status:   {target_status}")
    print(f"  Justification:   {justification}\n")

    if not skip_prompt:
        try:
            answer = input("Confirm promotion? [y/N] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            answer = ""
        if answer != "y":
            print("Aborted by operator.", file=sys.stderr)
            return 1
    return 0


def _print_confirm_result(strategy_id: str, db_path: str) -> None:
    """Query and print the just-written operator_confirm event row."""
    conn = connect_db(db_path)
    try:
        row = conn.execute(
            """SELECT event_id, to_status FROM strategy_promotion_events
               WHERE strategy_id = ? AND triggered_by = 'operator_confirm'
               ORDER BY timestamp DESC LIMIT 1""",
            (strategy_id,),
        ).fetchone()
    finally:
        conn.close()

    if row is not None:
        ev_id = row["event_id"] if hasattr(row, "keys") else row[0]
        final_status = row["to_status"] if hasattr(row, "keys") else row[1]
        print(f"Promotion confirmed. event_id={ev_id} final_status={final_status}")
    else:
        print("Promotion confirmed.")


def cmd_confirm_promotion(args) -> int:
    """Operator confirmation step for gate_proposal rows.

    Pre-checks (ergonomic): justification length, proposal existence + staleness,
    Decision-4 reject guard, y/N prompt. Delegates to promote() for all writes.
    """
    strategy_id = args.strategy
    justification = args.justification
    target_status = getattr(args, "target_status", "shadow_trading")
    skip_prompt = getattr(args, "yes", False)
    db_path = getattr(args, "db_path", DB_PATH)

    if not justification or len(justification.strip()) < _JUSTIFICATION_MIN_CHARS:
        print(
            f"ERROR: --justification must be >= {_JUSTIFICATION_MIN_CHARS} characters "
            f"(got {len(justification.strip() if justification else '')}). "
            "Provide a meaningful operator note.",
            file=sys.stderr,
        )
        return 4

    proposal, exit_code = _load_gate_proposal(strategy_id, db_path)
    if exit_code != 0:
        return exit_code

    decision = proposal["gate_result"].get("decision", "unknown")
    if decision == "reject":
        print(
            f"ERROR: Latest gate_proposal for '{strategy_id}' has decision='reject' — "
            "reject is not overridable via this CLI (Decision 4). "
            "Only 'defer' proposals can be confirmed by the operator.",
            file=sys.stderr,
        )
        return 4

    prompt_rc = _display_proposal_and_prompt(
        strategy_id, proposal, target_status, justification, skip_prompt,
    )
    if prompt_rc != 0:
        return prompt_rc

    from src.platform.promotion import promote

    try:
        promote(
            strategy_id=strategy_id,
            target_status=target_status,
            triggered_by="operator_confirm",
            justification_note=justification,
            db_path=db_path,
        )
    except ValueError as exc:
        print(f"ERROR: promote() rejected the request: {exc}", file=sys.stderr)
        return 1

    _print_confirm_result(strategy_id, db_path)
    return 0
