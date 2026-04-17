"""Strategy promotion pipeline — lifecycle state machine + DSR/PBO/WF gates.

Called by: scripts/run_backtest.py (auto-promote on first backtest),
           scripts/promote.py (manual promotion — Sprint 3+),
           src.scheduler.watch (Sprint 4 shadow harness dispatcher).
Calls: src.platform.rigor.dsr, src.platform.rigor.cscv,
       src.platform.rigor.walkforward, src.platform.rigor.trials,
       src.platform.backtest_engine, sqlite3.
Owns tables: strategy_registry, strategy_promotion_events.
Config keys: none.
Tests: tests/platform/test_promotion.py.

Gates (per spec line 1126-1148, locked in Sprint 2):
  proposed → backtested:   automatic on first backtest completion.
  backtested → shadow_trading:  DSR >= 0.95 AND PBO <= 0.50 AND
                                OOS_efficiency >= 0.30.
  shadow_trading → production:  above + n_shadow_trades >= 30 + 24h
                                delay + manual confirm + justification
                                note >= 40 chars.
  any → deprecated:        always allowed via demote() with reason
                           >= 20 chars.

pause() distinct from demote(): pause moves to 'backtested' (emergency
halt, does NOT close positions). demote moves to 'deprecated' (halts
AND closes positions via research Alpaca client — Sprint 4 wires the
actual close path).
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any

from src.config import DB_PATH

STATUSES = {"proposed", "backtested", "shadow_trading", "production", "deprecated"}

# Gate thresholds per authoritative spec.
GATE_DSR_MIN = 0.95
GATE_PBO_MAX = 0.50
GATE_OOS_EFFICIENCY_MIN = 0.30
GATE_SHADOW_TRADES_MIN = 30
GATE_JUSTIFICATION_MIN_CHARS = 40
GATE_DEMOTION_REASON_MIN_CHARS = 20


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _get_strategy_status(
    strategy_id: str, db_path: str = DB_PATH,
) -> str | None:
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "SELECT current_status FROM strategy_registry "
            "WHERE strategy_id = ?",
            (strategy_id,),
        ).fetchone()
    finally:
        conn.close()
    return row[0] if row else None


def check_promotion_gate(
    strategy_id: str, target_status: str, db_path: str = DB_PATH,
) -> tuple[bool, dict]:
    """Evaluate whether `strategy_id` may transition to `target_status`.

    Returns (passes, evidence_dict). Evidence keys depend on target:
      - target='backtested': {'auto': True}
      - target='shadow_trading': {dsr, pbo, oos_efficiency, max_dd,
                                   n_trades, n_eff_used_for_dsr}
      - target='production': above + {n_shadow_trades, shadow_duration_days}
      - target='deprecated': {'auto': True}
    """
    if target_status not in STATUSES:
        raise ValueError(f"unknown target_status: {target_status!r}")

    if target_status in ("backtested", "deprecated"):
        return True, {"auto": True}

    # For shadow_trading / production, caller wires DSR/PBO/WF results
    # into the evidence dict (Task 5-carryover follows).
    # Stub returns: gate reads latest numbers from backtest_results +
    # walks forward. Full plumbing is Task 5-carryover.
    from src.platform.rigor.trials import get_current_n_eff  # avoid cycles
    evidence: dict = {}
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            """SELECT deflated_sharpe, max_drawdown_pct, total_trades
               FROM backtest_results
               WHERE strategy_id = ?
               ORDER BY created_at DESC LIMIT 1""",
            (strategy_id,),
        ).fetchone()
    finally:
        conn.close()

    if row is None:
        evidence["error"] = "no backtest_results row for this strategy"
        return False, evidence
    dsr, max_dd, n_trades = row
    evidence["dsr"] = dsr
    evidence["max_drawdown_pct"] = max_dd
    evidence["n_trades"] = n_trades
    evidence["n_eff_used_for_dsr"] = get_current_n_eff(db_path)
    # PBO and OOS_efficiency columns on backtest_results land in
    # Task 5-carryover. For now, mark as missing evidence.
    evidence["pbo"] = None  # filled by Task 5-carryover
    evidence["oos_efficiency"] = None  # filled by Task 5-carryover

    # Basic gate check — full gate requires PBO + OOS_efficiency
    # (filled by Task 5-carryover). For now, DSR-only check:
    if dsr is None:
        evidence["error"] = "backtest did not populate deflated_sharpe"
        return False, evidence

    passes_dsr = dsr >= GATE_DSR_MIN
    evidence["passes_dsr_min"] = passes_dsr
    return bool(passes_dsr), evidence


def _write_promotion_event(
    conn: sqlite3.Connection,
    strategy_id: str, from_status: str | None, to_status: str,
    triggered_by: str, evidence: dict, justification_note: str | None,
) -> None:
    conn.execute(
        """INSERT INTO strategy_promotion_events
           (strategy_id, from_status, to_status, triggered_by,
            gate_result_json, justification_note, timestamp)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (strategy_id, from_status, to_status, triggered_by,
         json.dumps(evidence), justification_note, _now_iso()),
    )


def promote(
    strategy_id: str, target_status: str,
    triggered_by: str = "manual",
    justification_note: str | None = None,
    db_path: str = DB_PATH,
) -> None:
    """Promote strategy. Raises on gate failure or missing justification.

    For manual promotions (triggered_by='manual'), `justification_note`
    is required and must be >= 40 characters. Automatic promotions
    (triggered_by='auto_gate') are exempt.
    """
    if triggered_by == "manual":
        if not justification_note or len(justification_note) < GATE_JUSTIFICATION_MIN_CHARS:
            raise ValueError(
                f"manual promotion requires justification_note "
                f">= {GATE_JUSTIFICATION_MIN_CHARS} chars"
            )

    passes, evidence = check_promotion_gate(strategy_id, target_status, db_path)
    if not passes:
        raise ValueError(
            f"promotion gate failed for {strategy_id} → {target_status}: "
            f"{evidence}"
        )

    from_status = _get_strategy_status(strategy_id, db_path)
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """UPDATE strategy_registry
               SET current_status = ?, last_status_change = ?
               WHERE strategy_id = ?""",
            (target_status, _now_iso(), strategy_id),
        )
        _write_promotion_event(
            conn, strategy_id, from_status, target_status,
            triggered_by, evidence, justification_note,
        )
        conn.commit()
    finally:
        conn.close()


def demote(
    strategy_id: str, reason: str, db_path: str = DB_PATH,
) -> None:
    """Move strategy to 'deprecated'. Reason must be >= 20 chars.
    (Sprint 4 wires the position-close flow; this sprint just records
    the state transition.)"""
    if not reason or len(reason) < GATE_DEMOTION_REASON_MIN_CHARS:
        raise ValueError(
            f"demote requires reason >= {GATE_DEMOTION_REASON_MIN_CHARS} chars"
        )
    from_status = _get_strategy_status(strategy_id, db_path)
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """UPDATE strategy_registry
               SET current_status = 'deprecated', last_status_change = ?
               WHERE strategy_id = ?""",
            (_now_iso(), strategy_id),
        )
        _write_promotion_event(
            conn, strategy_id, from_status, "deprecated",
            "manual", {"reason": reason}, reason,
        )
        conn.commit()
    finally:
        conn.close()


def pause(strategy_id: str, db_path: str = DB_PATH) -> None:
    """Emergency halt: move strategy back to 'backtested'. Does NOT
    close open positions (use demote() for that)."""
    from_status = _get_strategy_status(strategy_id, db_path)
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """UPDATE strategy_registry
               SET current_status = 'backtested', last_status_change = ?
               WHERE strategy_id = ?""",
            (_now_iso(), strategy_id),
        )
        _write_promotion_event(
            conn, strategy_id, from_status, "backtested",
            "manual", {"action": "pause"}, None,
        )
        conn.commit()
    finally:
        conn.close()


def get_strategies_by_status(
    statuses: list[str], db_path: str = DB_PATH,
) -> list[str]:
    """Return strategy_ids currently in any of the given statuses."""
    if not statuses:
        return []
    placeholders = ",".join("?" * len(statuses))
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            f"SELECT strategy_id FROM strategy_registry "
            f"WHERE current_status IN ({placeholders})",
            statuses,
        ).fetchall()
    finally:
        conn.close()
    return [r[0] for r in rows]


def register_strategy(
    strategy_id: str, display_name: str, spec_source: str,
    spec_hash: str, db_path: str = DB_PATH,
    survivorship_haircut_bps: int = 75,
    expected_factor_profile_json: str | None = None,
    notes: str | None = None,
) -> None:
    """Create a new row in strategy_registry at status='proposed'."""
    now = _now_iso()
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """INSERT INTO strategy_registry
               (strategy_id, display_name, spec_source, current_status,
                current_spec_hash, expected_factor_profile_json,
                survivorship_haircut_bps, created_at, last_status_change,
                notes)
               VALUES (?, ?, ?, 'proposed', ?, ?, ?, ?, ?, ?)""",
            (strategy_id, display_name, spec_source, spec_hash,
             expected_factor_profile_json, survivorship_haircut_bps,
             now, now, notes),
        )
        conn.commit()
    finally:
        conn.close()
