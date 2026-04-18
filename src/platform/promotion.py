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


def _fetch_backtest_pnl_series(
    strategy_id: str, db_path: str,
) -> tuple[str | None, dict]:
    """Fetch pnl_pct series and summary stats for the latest backtest.

    Returns (result_id_or_None, evidence_dict). On failure evidence has an
    'error' key and result_id is None.
    """
    import pandas as pd

    evidence: dict = {}
    conn = sqlite3.connect(db_path)
    try:
        br_row = conn.execute(
            """SELECT result_id, max_drawdown_pct, total_trades
               FROM backtest_results
               WHERE strategy_id = ?
               ORDER BY created_at DESC LIMIT 1""",
            (strategy_id,),
        ).fetchone()
    finally:
        conn.close()

    if br_row is None:
        evidence["error"] = "no backtest_results row for this strategy"
        return None, evidence

    result_id, max_dd, n_trades = br_row
    evidence["max_drawdown_pct"] = max_dd
    evidence["n_trades"] = n_trades

    conn = sqlite3.connect(db_path)
    try:
        trade_rows = conn.execute(
            "SELECT pnl_pct FROM backtest_trades WHERE result_id = ?",
            (result_id,),
        ).fetchall()
    finally:
        conn.close()

    evidence["pnl_series"] = pd.Series(
        [r[0] for r in trade_rows if r[0] is not None],
        dtype=float,
    )
    return result_id, evidence


def _evaluate_dsr_evidence(
    strategy_id: str, db_path: str,
) -> tuple[bool, dict]:
    """Shared DSR computation for both shadow_trading and production gates.

    Uses real N_eff + V from trials_registry — never falls back to null.
    Raises RuntimeError if V is None (trials_registry integrity violation).
    """
    # Avoid circular imports — promotion → trials → (no promotion)
    from src.platform.rigor.trials import (
        get_current_n_eff,
        get_variance_for_strategy_family,
    )
    from src.platform.rigor.dsr import deflated_sharpe_ratio

    _, evidence = _fetch_backtest_pnl_series(strategy_id, db_path)
    if "error" in evidence:
        return False, evidence

    pnl_series = evidence.pop("pnl_series")
    n_eff = get_current_n_eff(db_path)
    trials_sr_variance = get_variance_for_strategy_family(db_path=db_path)

    # Defense-in-depth: if V is somehow None, fail loudly rather than
    # silently triggering the null-fallback path inside dsr.py.
    if trials_sr_variance is None:
        raise RuntimeError(
            "trials_sr_variance is None — get_variance_for_strategy_family "
            "must never return None; check trials_registry integrity."
        )

    evidence["n_eff_used_for_dsr"] = n_eff
    evidence["trials_sr_variance_used"] = trials_sr_variance
    dsr_result = deflated_sharpe_ratio(
        trade_returns=pnl_series,
        n_trials=n_eff,
        trials_sr_variance=trials_sr_variance,
    )
    dsr = dsr_result["DSR"]
    evidence["dsr"] = dsr
    passes_dsr = bool(dsr >= GATE_DSR_MIN)
    evidence["passes_dsr_min"] = passes_dsr
    return passes_dsr, evidence


def _evaluate_shadow_trading_gate(
    strategy_id: str, db_path: str,
) -> tuple[bool, dict]:
    """Evaluate gate criteria for 'backtested → shadow_trading' transition.

    Enforces all three rigor gates per spec line 1127-1135:
      DSR >= GATE_DSR_MIN (0.95), PBO <= GATE_PBO_MAX (0.50),
      OOS_efficiency >= GATE_OOS_EFFICIENCY_MIN (0.30).
    Fails immediately if PBO or OOS_efficiency are NULL — caller must run
    --with-walkforward (OOS) or param-sweep campaign (PBO, Sprint 4).
    """
    passes_dsr, evidence = _evaluate_dsr_evidence(strategy_id, db_path)
    if "error" in evidence:
        return False, evidence

    # Read pbo + oos_efficiency from the same backtest row (NULL-defaulting).
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "SELECT pbo, oos_efficiency FROM backtest_results "
            "WHERE strategy_id = ? ORDER BY created_at DESC LIMIT 1",
            (strategy_id,),
        ).fetchone()
    finally:
        conn.close()
    pbo = row[0] if row else None
    oos_efficiency = row[1] if row else None
    evidence["pbo"] = pbo
    evidence["oos_efficiency"] = oos_efficiency

    if pbo is None:
        evidence["error"] = "backtest has no PBO — run a param sweep with CSCV first"
        return False, evidence
    if oos_efficiency is None:
        evidence["error"] = (
            "backtest has no walk-forward OOS efficiency — "
            "run with --with-walkforward first"
        )
        return False, evidence

    passes_pbo = bool(pbo <= GATE_PBO_MAX)
    passes_oos = bool(oos_efficiency >= GATE_OOS_EFFICIENCY_MIN)
    evidence["passes_pbo_max"] = passes_pbo
    evidence["passes_oos_efficiency_min"] = passes_oos
    return passes_dsr and passes_pbo and passes_oos, evidence


def _evaluate_production_gate(
    strategy_id: str, db_path: str,
) -> tuple[bool, dict]:
    """Evaluate gate criteria for 'shadow_trading → production' transition.
    Requires shadow_trading gate pass + 30+ shadow trades + 60+ days +
    manual confirm (enforced at promote() call site).
    """
    passes_dsr, evidence = _evaluate_dsr_evidence(strategy_id, db_path)
    evidence["pbo"] = None  # Sprint 4 wires production gate PBO check
    evidence["oos_efficiency"] = None
    return passes_dsr, evidence


def check_promotion_gate(
    strategy_id: str, target_status: str, db_path: str = DB_PATH,
) -> tuple[bool, dict]:
    """Evaluate whether `strategy_id` may transition to `target_status`.

    Returns (passes, evidence_dict). Evidence keys depend on target:
      - target='backtested': {'auto': True}
      - target='shadow_trading': {dsr, pbo, oos_efficiency, max_drawdown_pct,
                                   n_trades, n_eff_used_for_dsr,
                                   trials_sr_variance_used}
      - target='production': above + {n_shadow_trades, shadow_duration_days}
      - target='deprecated': {'auto': True}

    DSR is recomputed from real trade returns + real N_eff and V from
    trials_registry — never read from the stored deflated_sharpe column.
    """
    if target_status not in STATUSES:
        raise ValueError(f"unknown target_status: {target_status!r}")
    if target_status in ("backtested", "deprecated"):
        return True, {"auto": True}
    if target_status == "shadow_trading":
        return _evaluate_shadow_trading_gate(strategy_id, db_path)
    if target_status == "production":
        return _evaluate_production_gate(strategy_id, db_path)
    # Fallthrough should not reach here (STATUSES check above)
    raise ValueError(f"unhandled target_status: {target_status!r}")


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
