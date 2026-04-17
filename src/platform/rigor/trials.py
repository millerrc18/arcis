"""Trials registry — counts N_eff for Deflated Sharpe + variance estimator.

Called by: src.platform.promotion (reads N_eff and V per-gate),
           scripts.run_backtest (records each trial on completion — Sprint 3+).
Calls: sqlite3, uuid, datetime, numpy (for variance estimator).
Owns tables: trials_registry.
Config keys: none.
Tests: tests/platform/rigor/test_trials.py.

Per Bailey-Lopez de Prado False Strategy theorem: every parameter
combination tested counts as one trial. If you run 30 strategies with
10 parameter grid points each, N_eff = 300 not 30. This module is the
source-of-truth for N_eff across ALL Sprint-3+ DSR calls.
"""

from __future__ import annotations

import sqlite3
import uuid
import warnings
from datetime import datetime, timezone
from typing import Any

import numpy as np

from src.config import DB_PATH

# Documented fallback when variance estimator has insufficient sample.
# Per Bailey-Lopez de Prado 2014, typical V for a diversified strategy
# pool lands in [0.01, 0.05] (annualized). Fallback at 0.02 — mid-range.
# v0.25 work: replace with family-specific empirical variance.
_VARIANCE_FALLBACK = 0.02 / 250  # per-observation, not annualized


def get_current_n_eff(db_path: str = DB_PATH) -> int:
    """Return the global count of trials recorded in trials_registry.
    This is the N used in DSR's E[max SR] formula — every backtest
    counts, including parameter sweeps."""
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "SELECT COUNT(*) FROM trials_registry"
        ).fetchone()
    finally:
        conn.close()
    return int(row[0])


def record_trial(
    strategy_id: str,
    spec_hash: str,
    sr_raw: float | None = None,
    sr_ann: float | None = None,
    n_trades: int | None = None,
    skew: float | None = None,
    kurt: float | None = None,
    passed_dsr_gate: bool = False,
    params_searched_json: str | None = None,
    n_params_searched: int = 1,
    db_path: str = DB_PATH,
) -> str:
    """Record one trial to trials_registry. Returns trial_id (uuid)."""
    trial_id = str(uuid.uuid4())
    created_at = datetime.now(timezone.utc).isoformat()
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """INSERT INTO trials_registry
               (trial_id, strategy_id, spec_hash, params_searched_json,
                n_params_searched, sr_raw, sr_ann, n_trades, skew, kurt,
                passed_dsr_gate, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (trial_id, strategy_id, spec_hash, params_searched_json,
             int(n_params_searched), sr_raw, sr_ann, n_trades, skew, kurt,
             1 if passed_dsr_gate else 0, created_at),
        )
        conn.commit()
    finally:
        conn.close()
    return trial_id


def get_variance_for_strategy_family(
    family: str | None = None, db_path: str = DB_PATH,
) -> float:
    """Return V[SR] estimate used as the variance parameter in DSR's
    E[max SR] formula.

    Full v0.25 work: compute per-observation variance of per-trial
    Sharpe ratios grouped by strategy family. For now: if >= 20 trials
    exist globally, use their empirical variance; otherwise fall back
    to 0.02/250 (documented constant).
    """
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            "SELECT sr_raw FROM trials_registry WHERE sr_raw IS NOT NULL"
        ).fetchall()
    finally:
        conn.close()
    sr_values = [r[0] for r in rows if r[0] is not None]
    if len(sr_values) >= 20:
        v = float(np.var(sr_values, ddof=1))
        # Guard: never return 0 (would zero out E[max SR])
        if v > 0:
            return v
    # Documented fallback — v0.25 work will tighten this
    warnings.warn(
        f"[TRIALS] Fewer than 20 recorded trials (have {len(sr_values)}); "
        f"using _VARIANCE_FALLBACK={_VARIANCE_FALLBACK}. v0.25 work: "
        "replace with empirical family variance.",
        RuntimeWarning,
    )
    return _VARIANCE_FALLBACK
