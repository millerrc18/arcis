"""Promotion gate orchestrator — runs 5 methodology methods and votes.

Authority: Arcis audit spec §F-12.

Pure-function module — no I/O, no DB on the legacy code path. The Sprint-0
Wave-3b RF-WIRING extension takes an optional `dates` argument and, when
provided, fetches per-period rf via FRED (effectful — see
src.methods._rf_vector); on failure it falls back to placeholder per-index.

Called by: external research scripts (via import).
Calls:
  src.methods.cpcv.cpcv,
  src.methods.block_bootstrap.block_bootstrap_ci,
  src.methods.mc_permutation.mc_permutation_pvalue,
  src.methods.psr.psr, src.methods.psr.dsr, src.methods.psr.mintrl,
  src.methods.white_rc.white_rc,
  src.methods._rf_vector.compute_per_period_rf_vector (Sprint-0 Wave-3b
    RF-WIRING — only when `dates` is supplied to `promotion_gate`).
Owns tables: none.
Config keys: none (FRED_API_KEY env honored transitively via the rf adapter
  when `dates` is supplied).
Tests: tests/methods/test_promotion_gate.py.

Decision logic:
  - MinTRL guard (checked first): if N < mintrl → {"decision": "defer",
    "reason": "insufficient_track_record", ...}
  - Inverse hard-block: MC permutation p-value > (1 − alpha) AND
    mean(returns) < 0. This signals the strategy's edge is negative under
    the null — i.e., the permuted labels OUTPERFORM the real labels. This is
    a structural red flag that five-method voting cannot override → "reject".
  - Vote count: ≥4 of 5 methods pass at α=0.05 → "promote", else "reject".

Input assumptions:
  - returns: 1-D sequence of per-period (e.g. per-trade) returns, NOT
    annualized. Length must be >= 5 (minimum for PSR/DSR/MinTRL).
  - n_trials: cumulative number of strategies tried in the research process.
    Pass 1 for single-strategy case (no multi-test penalty).
  - dates (optional): Sprint-0 Wave-3b RF-WIRING. When supplied (one
    `datetime.date` per period, len == len(returns)), each method runs
    against the rf-excess series (returns - per-trade FRED rf). When
    omitted, the legacy rf=0.0 behaviour is preserved for backward compat.
  - For CPCV, the series must be long enough for the default k=5 folds +
    embargo=10; the runner shortens k automatically when the series is short.
  - For White's Reality Check, a 2-column matrix is constructed by pairing
    the strategy returns with a zero-returns baseline, as the method requires
    at least N=2 strategies.
  - For MC permutation, directions are inferred from the sign of returns
    (+1 for positive, -1 for non-positive) since raw direction labels are
    not available at this interface level.
"""
from __future__ import annotations

import datetime as _dt
import logging
from typing import Sequence

import numpy as np

from src.methods.cpcv import cpcv
from src.methods.block_bootstrap import block_bootstrap_ci
from src.methods.mc_permutation import mc_permutation_pvalue
from src.methods.psr import psr, dsr, mintrl
from src.methods.white_rc import white_rc

logger = logging.getLogger(__name__)

_ALPHA = 0.05
_MIN_VOTES_TO_PROMOTE = 4
_MIN_CPCV_K = 2
_DEFAULT_CPCV_K = 5
_DEFAULT_CPCV_EMBARGO = 10


def _run_cpcv(returns: np.ndarray, alpha: float) -> dict:
    """Run CPCV and return a vote dict.

    Passes when the mean OOS fold Sharpe > 0. A fold Sharpe of None (from
    empty folds) is treated as 0.0.
    """
    arr = returns
    n = len(arr)
    # Choose k and embargo to fit the series length
    k = _DEFAULT_CPCV_K
    embargo = _DEFAULT_CPCV_EMBARGO
    while k > _MIN_CPCV_K and n < k * (embargo + 1):
        embargo = max(0, embargo - 1)
        if n < k * (embargo + 1):
            k -= 1
    result = cpcv(arr, k=k, embargo=embargo, rf_period=0.0)
    sharpes = [s if s is not None else 0.0 for s in result["fold_sharpes"]]
    mean_sharpe = float(np.mean(sharpes)) if sharpes else 0.0
    passed = mean_sharpe > 0.0
    return {
        "name": "cpcv",
        "passed": passed,
        "value": mean_sharpe,
        "threshold": 0.0,
    }


def _run_bootstrap(returns: np.ndarray, alpha: float) -> dict:
    """Run block bootstrap CI and return a vote dict.

    Passes when the lower bound of the 95% CI is > 0.
    """
    lo, hi = block_bootstrap_ci(returns, rf_period=0.0, n_resamples=1000, seed=42)
    passed = lo > 0.0
    return {
        "name": "block_bootstrap",
        "passed": passed,
        "value": lo,
        "threshold": 0.0,
    }


def _run_mc_perm(returns: np.ndarray, alpha: float) -> dict:
    """Run MC permutation test and return a vote dict.

    Directions are inferred from the sign of returns (+1 for r > 0, else -1).
    Passes when p-value < alpha (evidence against the null of no edge).
    """
    directions = [1 if r > 0 else -1 for r in returns.tolist()]
    p_value = mc_permutation_pvalue(
        returns.tolist(), directions, n_permutations=500, seed=42
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

    Uses DSR when n_trials > 1 (multi-testing adjustment); PSR when n_trials == 1.
    Passes when the probability exceeds 0.5.
    """
    if n_trials > 1:
        prob = dsr(returns, n_trials=n_trials)
        name = "psr_dsr"
    else:
        prob = psr(returns)
        name = "psr_dsr"
    passed = prob > 0.5
    return {
        "name": name,
        "passed": passed,
        "value": prob,
        "threshold": 0.5,
    }


def _run_white_rc(returns: np.ndarray, alpha: float) -> dict:
    """Run White's Reality Check and return a vote dict.

    White RC requires a (T, N) matrix with N >= 2. We construct a 2-column
    matrix: column 0 = strategy returns, column 1 = zeros (null baseline).
    Passes when the RC p-value < alpha.
    """
    matrix = np.column_stack([returns, np.zeros_like(returns)])
    p_value = white_rc(matrix, n_resamples=1000, seed=42)
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

    An inverse hard-block occurs when:
      - MC permutation p-value >= (1 − alpha): the permuted (randomized)
        labels score HIGHER than the real labels in >= alpha fraction of
        the permutations, indicating the real edge is negative.
      - AND mean(returns) < 0: confirms the edge is in the wrong direction.

    When both conditions hold, the strategy is actively harmful — five-method
    voting cannot override this structural red flag.
    """
    p_value = mc_perm_vote["value"]
    return bool(p_value >= (1.0 - alpha) and float(np.mean(returns)) < 0.0)


def _decide(
    all_votes: list[dict],
    mc_perm_vote: dict,
    arr: np.ndarray,
    n_obs: int,
    mintrl_val: int,
    alpha: float,
) -> dict:
    """Aggregate votes into a final decision dict.

    Priority order:
      1. N < mintrl → defer
      2. Inverse hard-block detected → reject
      3. >= _MIN_VOTES_TO_PROMOTE votes pass → promote, else reject
    """
    votes_bool = {v["name"]: v["passed"] for v in all_votes}
    details = {v["name"]: {"value": v["value"], "threshold": v["threshold"]} for v in all_votes}
    details["inverse_hard_block"] = _detect_inverse_hard_block(mc_perm_vote, arr, alpha)

    base = {"votes": votes_bool, "n_obs": n_obs, "mintrl": mintrl_val, "details": details}

    if n_obs < mintrl_val:
        return {**base, "decision": "defer", "reason": "insufficient_track_record"}

    if details["inverse_hard_block"]:
        return {**base, "decision": "reject"}

    n_pass = sum(1 for v in all_votes if v["passed"])
    decision = "promote" if n_pass >= _MIN_VOTES_TO_PROMOTE else "reject"
    return {**base, "decision": decision}


def _adjust_returns_via_fred(
    arr: np.ndarray,
    dates: Sequence[_dt.date],
) -> tuple[np.ndarray, str]:
    """Sprint-0 Wave-3b RF-WIRING: pre-subtract per-trade rf from `arr`.

    Returns (excess_arr, rf_source) where rf_source is "fred_dtb3" if at
    least one entry came from FRED, else "placeholder". Logs an info-level
    line tagged `[PROMOTION_GATE_RF]` so operators can confirm wiring is
    live in a given run.

    Centralised here so all five method runners (cpcv, bootstrap, mc_perm,
    psr/dsr, white_rc) consume an rf-adjusted input series — the runners
    themselves continue to call rf_period=0.0 since the adjustment is now
    baked into `arr`. This mirrors the kpis.py pattern where
    `_compute_per_trade_rf` returns a vector and the callers subtract it
    inline before invoking canonical_sharpe.
    """
    from src.methods._rf_vector import compute_per_period_rf_vector

    if len(dates) != len(arr):
        raise ValueError(
            f"len(dates)={len(dates)} must equal len(returns)={len(arr)}"
        )
    rf_vec, used_fred = compute_per_period_rf_vector(list(dates))
    rf_arr = np.asarray(rf_vec, dtype=float)
    rf_source = "fred_dtb3" if used_fred else "placeholder"
    logger.info(
        "[PROMOTION_GATE_RF] rf_source=%s, n_periods=%d, mean_rf=%.6e",
        rf_source, len(rf_arr), float(rf_arr.mean()) if len(rf_arr) else 0.0,
    )
    return arr - rf_arr, rf_source


def promotion_gate(
    returns: list | np.ndarray,
    n_trials: int,
    alpha: float = _ALPHA,
    dates: Sequence[_dt.date] | None = None,
) -> dict:
    """Evaluate a strategy via 5 methodology methods and return a promote/defer/reject decision.

    Runs CPCV, block-bootstrap CI, MC permutation, PSR/DSR, and White's
    Reality Check. Aggregates votes and applies MinTRL and inverse-hard-block
    guards before deciding.

    Args:
        returns:  1-D array-like of per-period returns (e.g. per-trade PnL).
                  Must have length >= 5.
        n_trials: Number of strategies tried in the research process
                  (used for DSR multi-testing correction). Pass 1 for a
                  single-strategy case.
        alpha:    Significance level. Default 0.05 (canonical; do not change).
        dates:    Sprint-0 Wave-3b RF-WIRING. Optional list of per-period
                  dates (one `datetime.date` per element of `returns`). When
                  supplied, the gate fetches per-trade rf from FRED DTB3
                  via src.methods._rf_vector.compute_per_period_rf_vector
                  and runs every method against the rf-excess series. When
                  omitted (legacy callers), all methods see raw `returns`
                  with rf_period=0.0 — preserving the prior behaviour.

    Returns:
        dict with keys:
          "decision":  "promote" | "defer" | "reject"
          "votes":     {method_name: pass_bool, ...}
          "n_obs":     int — length of returns series
          "mintrl":    int — minimum track record length at alpha
          "details":   dict — per-method value/threshold + metadata. Includes
                       "rf_source": "fred_dtb3" | "placeholder" | "unwired"
                       so callers can verify whether the FRED rf wiring
                       actually fired.
          "reason":    str (present on "defer" only)

    Decision rules (in priority order):
      1. If N < mintrl → "defer" (reason="insufficient_track_record")
      2. If inverse hard-block detected → "reject" (MC perm p >= 1−alpha AND mean < 0)
      3. If ≥4 of 5 method votes pass → "promote", else "reject"
    """
    arr = np.asarray(returns, dtype=float)
    if dates is not None:
        arr_for_methods, rf_source = _adjust_returns_via_fred(arr, dates)
    else:
        arr_for_methods = arr
        rf_source = "unwired"

    vote_mc_perm = _run_mc_perm(arr_for_methods, alpha)
    all_votes = [
        _run_cpcv(arr_for_methods, alpha),
        _run_bootstrap(arr_for_methods, alpha),
        vote_mc_perm,
        _run_psr(arr_for_methods, n_trials, alpha),
        _run_white_rc(arr_for_methods, alpha),
    ]
    decision = _decide(
        all_votes, vote_mc_perm, arr_for_methods,
        len(arr_for_methods), mintrl(arr_for_methods, alpha=alpha), alpha,
    )
    decision["details"]["rf_source"] = rf_source
    return decision
