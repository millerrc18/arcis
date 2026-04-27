"""Per-method runner helpers for the promotion gate.

Called by: src.methods.promotion_gate
Calls:
  src.methods.cpcv.cpcv, src.methods.cpcv.EmbargoZeroError,
  src.methods.block_bootstrap.block_bootstrap_ci,
  src.methods.mc_permutation.mc_permutation_pvalue,
  src.methods.psr.psr, src.methods.psr.dsr,
  src.methods.white_rc.white_rc,
  src.methods._rf_vector.compute_per_period_rf_vector (when dates supplied)
Owns tables: none
Config keys: none
Tests: tests/methods/test_promotion_gate_methodology.py

Split from promotion_gate.py during Sprint-0.B/B1 (#730) to satisfy the
400-line repo-structure guardrail. promotion_gate.py imports all symbols
defined here; existing callers and tests are unaffected.
"""
from __future__ import annotations

import datetime as _dt
import logging
from typing import Sequence

import numpy as np

from src.methods.cpcv import EmbargoZeroError, cpcv
from src.methods.block_bootstrap import block_bootstrap_ci
from src.methods.mc_permutation import mc_permutation_pvalue
from src.methods.psr import psr, dsr
from src.methods.white_rc import white_rc

logger = logging.getLogger(__name__)
_gate_logger = logging.getLogger("src.methods.promotion_gate")

_MIN_CPCV_K = 2
_DEFAULT_CPCV_K = 5
_DEFAULT_CPCV_EMBARGO = 10


def _cpcv_auto_fail(n: int, k: int, embargo: int, extra: dict | None = None) -> dict:
    """Build the leakage-safe CPCV auto-fail vote dict (operator Q6=A)."""
    details: dict = {
        "reason": "insufficient_data_for_leakage_safe_cpcv",
        "n_obs": int(n), "k": int(k), "embargo": int(embargo),
    }
    if extra:
        details.update(extra)
    else:
        details["min_required"] = int(_MIN_CPCV_K * 2)
    return {"name": "cpcv", "passed": False, "value": None, "threshold": 0.0, "details": details}


def _run_cpcv(returns: np.ndarray, alpha: float) -> dict:
    """Run CPCV and return a vote dict (mean OOS Sharpe > 0 → pass).

    Auto-FAILs with structured reason when the series is too short for a
    leakage-safe (k>=2, embargo>=1) config (operator Q6=A).
    """
    arr = returns
    n = len(arr)
    k = _DEFAULT_CPCV_K
    embargo = _DEFAULT_CPCV_EMBARGO
    _MIN_LEAK_SAFE_EMBARGO = 1
    while k > _MIN_CPCV_K and n < k * (embargo + 1):
        if embargo > _MIN_LEAK_SAFE_EMBARGO:
            embargo -= 1
        if n < k * (embargo + 1):
            k -= 1

    if n < k * (embargo + 1) or embargo < _MIN_LEAK_SAFE_EMBARGO:
        _gate_logger.warning(
            "[PROMOTION_GATE_CPCV_EMBARGO_ZERO] insufficient data for "
            "leakage-safe CPCV: n_obs=%d, k=%d, embargo=%d, min_required=%d",
            n, k, embargo, _MIN_CPCV_K * (_MIN_LEAK_SAFE_EMBARGO + 1),
        )
        return _cpcv_auto_fail(n, k, embargo)

    try:
        result = cpcv(arr, k=k, embargo=embargo, rf_period=0.0)
    except EmbargoZeroError as exc:
        _gate_logger.warning(
            "[PROMOTION_GATE_CPCV_EMBARGO_ZERO] per-fold embargo wiped "
            "train_idx: %s", exc,
        )
        return _cpcv_auto_fail(n, k, embargo, extra={"error": str(exc)})
    sharpes = [s if s is not None else 0.0 for s in result["fold_sharpes"]]
    mean_sharpe = float(np.mean(sharpes)) if sharpes else 0.0
    passed = mean_sharpe > 0.0
    return {"name": "cpcv", "passed": passed, "value": mean_sharpe, "threshold": 0.0}


def _run_bootstrap(returns: np.ndarray, alpha: float) -> dict:
    """Run block bootstrap CI and return a vote dict.

    Passes when the lower bound of the 95% CI is > 0. Resolves
    block_bootstrap_ci via src.methods.promotion_gate so tests that patch
    src.methods.promotion_gate.block_bootstrap_ci take effect.
    """
    from src.methods import promotion_gate as _pg
    lo, hi = _pg.block_bootstrap_ci(returns, rf_period=0.0, n_resamples=10000, seed=42)
    passed = lo > 0.0
    return {
        "name": "block_bootstrap",
        "passed": passed,
        "value": lo,
        "threshold": 0.0,
    }


def _run_mc_perm(
    returns: np.ndarray,
    alpha: float,
    directions: Sequence[int] | None = None,
) -> dict:
    """Run MC permutation test and return a vote dict.

    Sprint-0 Wave-5b PROMOTION-GATE-METHODOLOGY (operator Q6=A): abstains
    when no real directions are supplied.
    """
    if directions is None:
        return {
            "name": "mc_perm",
            "passed": None,
            "value": None,
            "threshold": alpha,
            "details": {
                "reason": "mc_permutation_requires_real_directions",
            },
        }
    dirs = list(directions)
    if len(dirs) != len(returns):
        raise ValueError(
            f"len(directions)={len(dirs)} must equal len(returns)={len(returns)}"
        )
    p_value = mc_permutation_pvalue(
        returns.tolist(), dirs, n_permutations=500, seed=42
    )
    passed = p_value < alpha
    return {
        "name": "mc_perm",
        "passed": passed,
        "value": p_value,
        "threshold": alpha,
    }


def _run_psr(returns: np.ndarray, n_trials: int, alpha: float) -> dict:
    """Run PSR/DSR and return a vote dict.

    Uses DSR when n_trials > 1; PSR when n_trials == 1.
    Passes when the probability exceeds 0.5.
    """
    if n_trials > 1:
        prob = dsr(returns, n_trials=n_trials)
    else:
        prob = psr(returns)
    passed = prob > 0.5
    return {
        "name": "psr_dsr",
        "passed": passed,
        "value": prob,
        "threshold": 0.5,
    }


def _run_white_rc(
    returns: np.ndarray,
    alpha: float,
    n_trials: int = 1,
    candidate_pool: np.ndarray | None = None,
) -> dict:
    """Run White's Reality Check and return a vote dict.

    Sprint-0 Wave-5b PROMOTION-GATE-METHODOLOGY (operator Q6=A): abstains
    when n_trials==1 and no candidate_pool is supplied.
    """
    if candidate_pool is None and n_trials <= 1:
        return {
            "name": "white_rc",
            "passed": None,
            "value": None,
            "threshold": alpha,
            "details": {
                "reason": "white_rc_requires_candidate_pool",
                "n_trials": int(n_trials),
            },
        }
    if candidate_pool is None:
        matrix = np.column_stack([returns, np.zeros_like(returns)])
    else:
        pool = np.asarray(candidate_pool, dtype=float)
        if pool.ndim == 1:
            pool = pool[:, None]
        if pool.shape[0] != len(returns):
            raise ValueError(
                f"candidate_pool rows={pool.shape[0]} must equal "
                f"len(returns)={len(returns)}"
            )
        matrix = np.column_stack([returns, pool])
    p_value = white_rc(matrix, n_resamples=10000, seed=42)
    passed = p_value < alpha
    return {
        "name": "white_rc",
        "passed": passed,
        "value": p_value,
        "threshold": alpha,
    }


def _detect_inverse_hard_block(
    mc_perm_vote: dict, returns: np.ndarray, alpha: float,
) -> bool:
    """Detect an inverse hard-block from the MC permutation vote.

    Returns True when mc perm p-value >= (1 − alpha) AND mean(returns) < 0.
    Returns False when MC permutation abstained (value=None).
    """
    p_value = mc_perm_vote.get("value")
    if p_value is None:
        return False
    return bool(p_value >= (1.0 - alpha) and float(np.mean(returns)) < 0.0)


def _adjust_returns_via_fred(
    arr: np.ndarray,
    dates: Sequence[_dt.date],
) -> tuple[np.ndarray, str]:
    """Sprint-0 Wave-3b RF-WIRING: pre-subtract per-trade rf from arr.

    Returns (excess_arr, rf_source) where rf_source is "fred_dtb3" if at
    least one entry came from FRED, else "placeholder".
    """
    from src.methods._rf_vector import compute_per_period_rf_vector

    if len(dates) != len(arr):
        raise ValueError(
            f"len(dates)={len(dates)} must equal len(returns)={len(arr)}"
        )
    rf_vec, used_fred = compute_per_period_rf_vector(list(dates))
    rf_arr = np.asarray(rf_vec, dtype=float)
    rf_source = "fred_dtb3" if used_fred else "placeholder"
    _gate_logger.info(
        "[PROMOTION_GATE_RF] rf_source=%s, n_periods=%d, mean_rf=%.6e",
        rf_source, len(rf_arr), float(rf_arr.mean()) if len(rf_arr) else 0.0,
    )
    return arr - rf_arr, rf_source
