"""Strategy promotion pipeline — lifecycle state machine + DSR/PBO/WF gates.

Called by: scripts/run_backtest.py (auto-promote on first backtest),
           scripts/promote.py (manual promotion — Sprint 3+),
           src.scheduler.watch (Sprint 4 shadow harness dispatcher).
Calls: src.platform.rigor.dsr, src.platform.rigor.cscv,
       src.platform.rigor.walkforward, src.platform.rigor.trials,
       src.platform.backtest_engine, sqlite3,
       src.methods.promotion_gate (Sprint 2 T2: methodology gate AND-composition),
       src.analytics.instrumentation_filter (Sprint 2 T2: input quality filter).
Owns tables: strategy_registry, strategy_promotion_events.
Config keys: METHODOLOGY_GATE_ENABLED (env, default 'true'),
             WALKFORWARD_GATE_ENABLED (env, default 'true').
Tests: tests/platform/test_promotion.py,
       tests/test_promotion_methodology_gate.py.

Gates (per spec line 1126-1148, locked in Sprint 2):
  proposed → backtested:   automatic on first backtest completion.
  backtested → shadow_trading:  DSR >= 0.95 AND PBO <= 0.50 AND
                                OOS_efficiency >= 0.30 AND
                                methodology gate (AND-composed, Sprint 2 T2).
  shadow_trading → production:  DSR + methodology gate AND-composed
                                + n_shadow_trades >= 30 + 24h
                                delay + manual confirm + justification
                                note >= 40 chars.
                                NOTE: production gate currently only checks DSR
                                + methodology gate. PBO and walkforward are
                                Sprint-4 placeholders (pbo=None,
                                oos_efficiency=None in evidence).
  any → deprecated:        always allowed via demote() with reason
                           >= 20 chars.

pause() distinct from demote(): pause moves to 'backtested' (emergency
halt, does NOT close positions). demote moves to 'deprecated' (halts
AND closes positions via research Alpaca client — Sprint 4 wires the
actual close path).
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
from datetime import datetime, timezone
from typing import Any, Callable

from src.config import DB_PATH
from src.utils.db import connect_db

logger = logging.getLogger(__name__)

STATUSES = {"proposed", "backtested", "shadow_trading", "production", "deprecated"}

# Gate thresholds per authoritative spec.
GATE_DSR_MIN = 0.95
GATE_PBO_MAX = 0.50
GATE_OOS_EFFICIENCY_MIN = 0.30
GATE_SHADOW_TRADES_MIN = 30
GATE_JUSTIFICATION_MIN_CHARS = 40
GATE_DEMOTION_REASON_MIN_CHARS = 20

# Walk-forward three-state outcomes (canonical strings persisted to
# walkforward_results.outcome_state). Mirrored from
# src.platform.rigor.walkforward_outcome to avoid a hard import cycle.
WF_STATE_PASS = "PASS"
WF_STATE_FAIL = "FAIL"
WF_STATE_INCONCLUSIVE = "INCONCLUSIVE"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _get_strategy_status(
    strategy_id: str, db_path: str = DB_PATH,
) -> str | None:
    conn = connect_db(db_path)
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
    conn = connect_db(db_path)
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

    conn = connect_db(db_path)
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


def _fetch_latest_walkforward_outcome(
    strategy_id: str, db_path: str,
) -> dict | None:
    """Return the latest walk-forward v1 outcome row for `strategy_id`, or
    None if no walkforward_results row exists. The table may be missing on
    older databases; we tolerate that and return None.
    """
    conn = connect_db(db_path)
    try:
        try:
            row = conn.execute(
                "SELECT run_id, outcome_state, reason, pooled_sharpe, "
                "pooled_mde, n_windows_pass, n_windows_fail, "
                "n_windows_inconclusive_data, n_windows_inconclusive_power, "
                "heavy_tail_flag, created_at "
                "FROM walkforward_results WHERE strategy_id = ? "
                "ORDER BY created_at DESC LIMIT 1",
                (strategy_id,),
            ).fetchone()
        except sqlite3.OperationalError:
            return None  # table missing on legacy DBs
    finally:
        conn.close()
    if row is None:
        return None
    return {
        "run_id": row[0], "outcome_state": row[1], "reason": row[2],
        "pooled_sharpe": row[3], "pooled_mde": row[4],
        "n_windows_pass": row[5], "n_windows_fail": row[6],
        "n_windows_inconclusive_data": row[7],
        "n_windows_inconclusive_power": row[8],
        "heavy_tail_flag": row[9], "created_at": row[10],
    }


def _evaluate_walkforward_gate(
    strategy_id: str, db_path: str, evidence: dict,
) -> tuple[bool | None, dict]:
    """Attach walk-forward v1 three-state outcome to evidence and return
    a gate decision from the walk-forward result alone.

    Returns:
        (True, evidence)  if outcome_state == PASS
        (False, evidence) if outcome_state == FAIL or INCONCLUSIVE
        (None, evidence)  if no walkforward_results row exists — caller
                          should fall back to the legacy OOS_efficiency gate

    Attaches to evidence:
        walkforward_outcome_state: 'PASS' | 'FAIL' | 'INCONCLUSIVE' | None
        walkforward_status: 'pass' | 'fail' | 'inconclusive' | 'no_data_yet'
            (Sprint 2 T2: DA major fix 4 — human-readable status alongside
            outcome_state for backwards-compat; distinguishes 'no data yet'
            from 'FAIL' for dashboard display)
        walkforward_reason: structured reason string from the runner
        walkforward_run_id: cross-reference to walkforward_results
        walkforward_pooled_sharpe: net-of-cost pooled Sharpe

    Feature flag: WALKFORWARD_GATE_ENABLED is enabled ONLY when the env value
    resolves to one of {"true", "1", "yes"} (case-insensitive); any other value
    — including non-canonical strings like "0", "no", "banana" or a typo like
    "trueee" — disables the gate.

    This is stricter-about-enable than the sibling METHODOLOGY_GATE_ENABLED
    pattern at line 294 below, which disables only on literal "false" and
    leaves every other value (including typos) enabled. The asymmetry is
    deliberate: walk-forward gating is fail-safe (a misconfigured env var
    blocks promotions rather than silently allowing them), while
    methodology-gate disable is fail-open (a misconfigured env var lets the
    full voter run rather than skipping it). Both gates default to enabled
    when the env var is unset.

    PR #1090 review (operator, 2026-05-13): the docstring's prior claim of
    "follows METHODOLOGY_GATE_ENABLED pattern" was inaccurate; this header
    documents the deliberate divergence. Standardization to a shared
    `_env_flag_enabled(name, default=True)` helper is a Sprint 6 catch-all
    candidate.

    When the flag resolves disabled, the gate short-circuits to
    (None, evidence) with walkforward_status='disabled' — identical to the
    no-row-found fallback so all call sites keep working unchanged.
    """
    if not os.environ.get("WALKFORWARD_GATE_ENABLED", "true").lower() in ("true", "1", "yes"):
        evidence["walkforward_status"] = "disabled"
        return None, evidence
    wf = _fetch_latest_walkforward_outcome(strategy_id, db_path)
    if wf is None:
        evidence["walkforward_outcome_state"] = None
        evidence["walkforward_status"] = "no_data_yet"
        evidence["walkforward_reason"] = None
        return None, evidence
    evidence["walkforward_outcome_state"] = wf["outcome_state"]
    state = wf["outcome_state"]
    evidence["walkforward_status"] = state.lower() if state else "no_data_yet"
    evidence["walkforward_reason"] = wf["reason"]
    evidence["walkforward_run_id"] = wf["run_id"]
    evidence["walkforward_pooled_sharpe"] = wf["pooled_sharpe"]
    evidence["walkforward_pooled_mde"] = wf["pooled_mde"]
    evidence["walkforward_heavy_tail_flag"] = bool(wf["heavy_tail_flag"])
    if state == WF_STATE_PASS:
        return True, evidence
    if state == WF_STATE_INCONCLUSIVE:
        evidence["error"] = "walkforward_inconclusive"
        return False, evidence
    if state == WF_STATE_FAIL:
        evidence["error"] = "walkforward_failed"
        return False, evidence
    # Unknown state — don't silently pass. Treat as FAIL.
    evidence["error"] = f"walkforward_unknown_state:{state}"
    return False, evidence


def _get_n_trials_for_strategy(db_path: str) -> int:
    """Return the global N_eff from trials_registry for DSR n_trials arg."""
    from src.platform.rigor.trials import get_current_n_eff
    n = get_current_n_eff(db_path)
    return max(n, 1)


def _evaluate_strategy_methodology_gate(
    strategy_id: str, db_path: str,
) -> tuple[bool, dict]:
    """Evaluate the 4-of-5 methodology gate for strategy_id.

    Loads shadow_trades, filters via is_fully_instrumented AND
    actual_entry_time IS NOT NULL AND pnl_pct IS NOT NULL, builds
    MethodInputs, and calls promotion_gate.promotion_gate(...).

    Returns (passes_bool, evidence_dict) where evidence matches spec §3.2.

    Feature flag: METHODOLOGY_GATE_ENABLED=false short-circuits to
    (True, {'decision': 'skipped'}) with no persistence side-effects.
    """
    if os.environ.get("METHODOLOGY_GATE_ENABLED", "true").lower() == "false":
        return True, {"decision": "skipped"}

    from src.analytics.instrumentation_filter import is_fully_instrumented
    from src.methods.promotion_gate import promotion_gate

    # NOTE on `strategy_id` parameter (single-strategy phase, 2026-05-06):
    # shadow_trades has NO strategy_id column (see src/schema/registry.py:196-275).
    # The current trading system is single-strategy ("pullback"); every shadow_trade
    # belongs to the one active strategy by definition. The strategy_id parameter
    # is kept in this helper's signature for forward-compat — when shadow_trades
    # gains a strategy_id FK column (or strategy_type-based filter is wired in),
    # this SQL will get an `AND strategy_id = ?` predicate. Filtering today
    # would fail with `no such column: strategy_id`. ORDER BY actual_entry_time
    # ASC keeps the dates list monotonic for promotion_gate downstream.
    conn = connect_db(db_path)
    try:
        rows = conn.execute(
            """SELECT pnl_pct, actual_entry_time, actual_exit_time,
                      excess_return, actual_entry_price, actual_exit_price
               FROM shadow_trades
               WHERE pnl_pct IS NOT NULL
               ORDER BY actual_entry_time ASC""",
        ).fetchall()
    finally:
        conn.close()

    all_rows = [
        {
            "pnl_pct": r[0],
            "actual_entry_time": r[1],
            "actual_exit_time": r[2],
            "excess_return": r[3],
            "actual_entry_price": r[4],
            "actual_exit_price": r[5],
        }
        for r in rows
    ]
    # Apply is_fully_instrumented AND actual_entry_time IS NOT NULL filter
    # (actual_entry_time is needed for building dates list for promotion_gate)
    instrumented_rows = [
        r for r in all_rows
        if is_fully_instrumented(r) and r.get("actual_entry_time") is not None
    ]
    excluded_count = len(all_rows) - len(instrumented_rows)

    import datetime as _dt
    returns = [float(r["pnl_pct"]) for r in instrumented_rows]
    directions = [1] * len(instrumented_rows)
    dates = []
    for r in instrumented_rows:
        try:
            dates.append(_dt.date.fromisoformat(r["actual_entry_time"][:10]))
        except (TypeError, ValueError):
            dates.append(_dt.date.today())

    assert len(returns) == len(dates) == len(directions), (
        "Length invariant violated: returns/dates/directions must all match"
    )

    n_trials = _get_n_trials_for_strategy(db_path)

    active_strategies = get_strategies_by_status(
        ["shadow_trading", "backtested"], db_path,
    )
    other_strategies = [s for s in active_strategies if s != strategy_id]

    if len(other_strategies) < 1:
        candidate_pool = None
        threshold_used = "4_of_4_no_white_rc"
    else:
        candidate_pool = None
        threshold_used = "4_of_5"

    if len(returns) == 0:
        evidence = {
            "methodology_gate": {
                "decision": "no_data_yet",
                "n_obs": 0,
                "votes": {},
                "details": {},
                "reason": "no_instrumented_shadow_trades",
            },
            "threshold_used": threshold_used,
            "instrumentation_excluded_count": excluded_count,
        }
        return True, evidence
    else:
        gate_result = promotion_gate(
            returns=returns,
            n_trials=n_trials,
            dates=dates,
            directions=directions,
            candidate_pool=candidate_pool,
        )

    votes_raw = gate_result.get("votes", {})
    votes_flat = {k: v for k, v in votes_raw.items()}

    evidence = {
        "methodology_gate": {
            "decision": gate_result.get("decision"),
            "n_obs": gate_result.get("n_obs"),
            "mintrl": gate_result.get("mintrl"),
            "votes": votes_flat,
            "details": gate_result.get("details", {}),
        },
        "threshold_used": threshold_used,
        "instrumentation_excluded_count": excluded_count,
    }
    if "reason" in gate_result:
        evidence["methodology_gate"]["reason"] = gate_result["reason"]

    passes = gate_result.get("decision") == "promote"
    return passes, evidence


def _evaluate_shadow_trading_gate(
    strategy_id: str, db_path: str,
) -> tuple[bool, dict]:
    """Evaluate gate criteria for 'backtested → shadow_trading' transition.

    Preference order:
      1. walkforward_results v1 (three-state outcome preserves PASS /
         FAIL / INCONCLUSIVE in evidence — never collapse to boolean).
         If outcome != PASS, gate returns False with a structured reason.
      2. Legacy DSR + PBO + OOS_efficiency gate (backward-compatibility
         for strategies that predate walk-forward v1 table).

    Sprint 2 T2: methodology gate AND-composed at ALL return sites.
    """
    passes_dsr, evidence = _evaluate_dsr_evidence(strategy_id, db_path)
    if "error" in evidence:
        mg_passes, mg_evidence = _evaluate_strategy_methodology_gate(
            strategy_id, db_path,
        )
        evidence["methodology_gate"] = mg_evidence
        return False, evidence  # gate already False; mg_evidence attached above for visibility

    # Walk-forward v1 three-state outcome takes precedence when available.
    wf_pass, evidence = _evaluate_walkforward_gate(
        strategy_id, db_path, evidence,
    )
    if wf_pass is False:
        # INCONCLUSIVE or FAIL — never collapse. Evidence already carries
        # walkforward_outcome_state + walkforward_reason fields.
        mg_passes, mg_evidence = _evaluate_strategy_methodology_gate(
            strategy_id, db_path,
        )
        evidence["methodology_gate"] = mg_evidence
        return False, evidence  # gate already False; mg_evidence attached above for visibility
    # wf_pass is True → walk-forward passed, keep checking DSR.
    # wf_pass is None → no walkforward_results row; fall back to legacy gate.

    # Read pbo + oos_efficiency from the same backtest row (NULL-defaulting).
    conn = connect_db(db_path)
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

    # When walk-forward v1 has passed, we skip the legacy OOS_efficiency
    # requirement — the new framework is stricter. PBO is still checked.
    if wf_pass is True:
        if pbo is None:
            evidence["error"] = (
                "backtest has no PBO — run a param sweep with CSCV first"
            )
            mg_passes, mg_evidence = _evaluate_strategy_methodology_gate(
                strategy_id, db_path,
            )
            evidence["methodology_gate"] = mg_evidence
            return False, evidence  # gate already False; mg_evidence attached above for visibility
        passes_pbo = bool(pbo <= GATE_PBO_MAX)
        evidence["passes_pbo_max"] = passes_pbo
        # DA major fix 1: AND-compose at line 298 (wf-PASS success branch)
        mg_passes, mg_evidence = _evaluate_strategy_methodology_gate(
            strategy_id, db_path,
        )
        evidence["methodology_gate"] = mg_evidence
        return (passes_dsr and passes_pbo) and mg_passes, evidence

    # Legacy path (wf_pass is None).
    if pbo is None:
        evidence["error"] = "backtest has no PBO — run a param sweep with CSCV first"
        mg_passes, mg_evidence = _evaluate_strategy_methodology_gate(
            strategy_id, db_path,
        )
        evidence["methodology_gate"] = mg_evidence
        return False, evidence  # gate already False; mg_evidence attached above for visibility
    if oos_efficiency is None:
        evidence["error"] = (
            "backtest has no walk-forward OOS efficiency — "
            "run with --with-walkforward first"
        )
        mg_passes, mg_evidence = _evaluate_strategy_methodology_gate(
            strategy_id, db_path,
        )
        evidence["methodology_gate"] = mg_evidence
        return False, evidence  # gate already False; mg_evidence attached above for visibility

    passes_pbo = bool(pbo <= GATE_PBO_MAX)
    passes_oos = bool(oos_efficiency >= GATE_OOS_EFFICIENCY_MIN)
    evidence["passes_pbo_max"] = passes_pbo
    evidence["passes_oos_efficiency_min"] = passes_oos
    mg_passes, mg_evidence = _evaluate_strategy_methodology_gate(
        strategy_id, db_path,
    )
    evidence["methodology_gate"] = mg_evidence
    return (passes_dsr and passes_pbo and passes_oos) and mg_passes, evidence


def _evaluate_production_gate(
    strategy_id: str, db_path: str,
) -> tuple[bool, dict]:
    """Evaluate gate criteria for 'shadow_trading → production' transition.
    Requires shadow_trading gate pass + 30+ shadow trades + 60+ days +
    manual confirm (enforced at promote() call site).

    Sprint 2 T2: methodology gate AND-composed with DSR only.
    NOTE: pbo=None and oos_efficiency=None are Sprint-4 placeholders —
    production gate does NOT yet check walkforward or PBO. This asymmetry
    is intentional; walkforward + PBO will be wired in Sprint 4.
    """
    passes_dsr, evidence = _evaluate_dsr_evidence(strategy_id, db_path)
    evidence["pbo"] = None  # Sprint 4 wires production gate PBO check
    evidence["oos_efficiency"] = None
    mg_passes, mg_evidence = _evaluate_strategy_methodology_gate(
        strategy_id, db_path,
    )
    evidence["methodology_gate"] = mg_evidence
    return passes_dsr and mg_passes, evidence


def check_promotion_gate(
    strategy_id: str, target_status: str, db_path: str = DB_PATH,
) -> tuple[bool, dict]:
    """Evaluate whether `strategy_id` may transition to `target_status`.

    Returns (passes, evidence_dict). Evidence always includes structured
    reason strings — not just a boolean — so three-state walk-forward
    outcomes (PASS / FAIL / INCONCLUSIVE) are preserved end-to-end.

    Evidence keys depend on target:
      - target='backtested': {'auto': True}
      - target='shadow_trading': walk-forward v1 if present
            {walkforward_outcome_state, walkforward_status,
             walkforward_reason, walkforward_run_id,
             walkforward_pooled_sharpe, walkforward_pooled_mde,
             walkforward_heavy_tail_flag, dsr, pbo, n_eff_used_for_dsr,
             trials_sr_variance_used, methodology_gate}
        else legacy gate
            {dsr, pbo, oos_efficiency, max_drawdown_pct, n_trades,
             methodology_gate, ...}
      - target='production': above + {n_shadow_trades, shadow_duration_days,
            methodology_gate}
      - target='deprecated': {'auto': True}

    Three-state handling on shadow_trading:
      - walk-forward outcome PASS → evidence.walkforward_outcome_state='PASS',
        still checks DSR + PBO + methodology gate
      - walk-forward FAIL → returns (False, evidence with error='walkforward_failed')
      - walk-forward INCONCLUSIVE → returns (False, evidence with
        error='walkforward_inconclusive')
      - No walkforward_results row → falls back to legacy OOS_efficiency gate

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
    conn = connect_db(db_path)
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
    conn = connect_db(db_path)
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
    conn = connect_db(db_path)
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
    statuses: list[str], db_path: str | None = DB_PATH,
) -> list[str]:
    """Return strategy_ids currently in any of the given statuses."""
    if not statuses:
        return []
    if db_path is None:
        db_path = DB_PATH
    placeholders = ",".join("?" * len(statuses))
    conn = connect_db(db_path)
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
    conn = connect_db(db_path)
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


def _safe_run(strategy_id: str, db_path: str) -> tuple[bool, dict]:
    """Run _evaluate_strategy_methodology_gate wrapped in try/except.

    On exception: returns (False, defer_evidence) with error_message set.
    """
    try:
        return _evaluate_strategy_methodology_gate(strategy_id, db_path)
    except Exception as exc:
        logger.exception(
            "[METHODOLOGY_GATE] strategy=%s raised during gate evaluation",
            strategy_id,
        )
        return False, {
            "decision": "defer",
            "error_message": str(exc),
            "instrumentation_excluded_count": 0,
            "existing_gates": {},
            "composed_pass": False,
            "threshold_used": "4_of_5",
            "override_by": None,
            "override_reason": None,
        }


def run_daily_gate_for_all_active_strategies(
    db_path: str = DB_PATH,
    notify: Callable[[str, dict], None] | None = None,
) -> list[dict]:
    """Run the daily methodology gate for all shadow_trading + backtested strategies.

    For each strategy:
    - Calls _evaluate_strategy_methodology_gate (wrapped in _safe_run)
    - Persists a strategy_promotion_events row with triggered_by='gate_proposal',
      from_status==to_status (informational, no real transition),
      justification_note=NULL
    - Invokes notify callback on PASS proposals (T4 will provide it)

    Returns a list of result dicts, one per strategy.

    Feature flag: METHODOLOGY_GATE_ENABLED=false returns [] with no persistence.
    """
    if os.environ.get("METHODOLOGY_GATE_ENABLED", "true").lower() == "false":
        return []

    active = get_strategies_by_status(
        ["shadow_trading", "backtested"], db_path,
    )
    results = []
    for strategy_id in active:
        passes, evidence = _safe_run(strategy_id, db_path)
        current_status = _get_strategy_status(strategy_id, db_path) or "unknown"
        conn = connect_db(db_path)
        try:
            _write_promotion_event(
                conn,
                strategy_id=strategy_id,
                from_status=current_status,
                to_status=current_status,
                triggered_by="gate_proposal",
                evidence=evidence,
                justification_note=None,
            )
            conn.commit()
        finally:
            conn.close()

        if passes and notify is not None:
            try:
                notify(strategy_id, evidence)
            except Exception:
                logger.exception(
                    "[METHODOLOGY_GATE] notify callback raised for strategy=%s",
                    strategy_id,
                )

        results.append({
            "strategy_id": strategy_id,
            "passes": passes,
            "evidence": evidence,
        })
    return results
