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
    Sprint-0 Wave-5b PROMOTION-GATE-METHODOLOGY (operator Q6=A): the
    auto-shrink loop never decrements embargo to 0; if the series cannot
    support k>=2 with embargo>=1, CPCV vote auto-FAILs with
    `details["reason"]="insufficient_data_for_leakage_safe_cpcv"`.
  - For White's Reality Check, Sprint-0 Wave-5b PROMOTION-GATE-METHODOLOGY
    (operator Q6=A): when `n_trials==1` and no `candidate_pool` is
    supplied, the vote abstains (`passed=None`) with
    `details["reason"]="white_rc_requires_candidate_pool"`. The prior
    zero-baseline pairing semantically conflated the multi-strategy
    data-snooping correction with a single-strategy V_bar > 0 test.
  - For MC permutation, Sprint-0 Wave-5b PROMOTION-GATE-METHODOLOGY
    (operator Q6=A): directions are no longer inferred from the sign of
    returns. When `directions` is not supplied, the vote abstains
    (`passed=None`) with
    `details["reason"]="mc_permutation_requires_real_directions"`. The
    sign-inferred fallback made the test trivially significant for any
    non-zero-mean series.

Abstention semantics (Wave-5b): a vote with `passed=None` does NOT count
toward the 4-of-5 tally. Operator Q6=A chose strict — the threshold stays
rigid; abstentions force the strategy to clear the gate on the other
votes. The `details` dict gains `n_pass`, `n_fail`, `n_abstentions`
counters for introspection.
"""
from __future__ import annotations

import datetime as _dt
import logging
from typing import Sequence

import numpy as np

from src.methods.cpcv import EmbargoZeroError, cpcv
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

    Sprint-0 Wave-5b PROMOTION-GATE-METHODOLOGY (operator Q6=A): the
    auto-shrink loop below previously decremented embargo to 0, silently
    disabling leakage protection. Per Q6=A, when the series is too short
    to support a leakage-safe (k, embargo) configuration with embargo > 0,
    the CPCV vote auto-FAILs with `passed=False` and a structured
    `details["reason"]="insufficient_data_for_leakage_safe_cpcv"`. Vote
    count: CPCV is 1 of 5 votes; the gate threshold is 4-of-5, so an
    auto-FAIL means the strategy must pass the OTHER 4 votes to be
    promoted. (Operator chose strict — running CPCV with embargo=0 is
    disallowed because the test loses its leakage-protection meaning.)
    """
    arr = returns
    n = len(arr)
    # Choose k and embargo to fit the series length. We keep shrinking k
    # until the configuration fits OR k drops to _MIN_CPCV_K. Critically,
    # we never decrement embargo below 1 — embargo=0 silently disables
    # leakage protection (operator Q6=A).
    k = _DEFAULT_CPCV_K
    embargo = _DEFAULT_CPCV_EMBARGO
    _MIN_LEAK_SAFE_EMBARGO = 1
    while k > _MIN_CPCV_K and n < k * (embargo + 1):
        if embargo > _MIN_LEAK_SAFE_EMBARGO:
            embargo -= 1
        if n < k * (embargo + 1):
            k -= 1

    # Final feasibility check: if the series still cannot support k>=2 with
    # embargo>=1, return an auto-FAIL vote. This is the Q6=A guard rail.
    if n < k * (embargo + 1) or embargo < _MIN_LEAK_SAFE_EMBARGO:
        min_required = _MIN_CPCV_K * (_MIN_LEAK_SAFE_EMBARGO + 1)
        logger.warning(
            "[PROMOTION_GATE_CPCV_EMBARGO_ZERO] insufficient data for "
            "leakage-safe CPCV: n_obs=%d, k=%d, embargo=%d, min_required=%d",
            n, k, embargo, min_required,
        )
        return {
            "name": "cpcv",
            "passed": False,
            "value": None,
            "threshold": 0.0,
            "details": {
                "reason": "insufficient_data_for_leakage_safe_cpcv",
                "n_obs": int(n),
                "k": int(k),
                "embargo": int(embargo),
                "min_required": int(min_required),
            },
        }

    try:
        result = cpcv(arr, k=k, embargo=embargo, rf_period=0.0)
    except EmbargoZeroError as exc:
        # Defense-in-depth: _apply_embargo can also raise if a particular
        # fold's embargo wipes out its train_idx (e.g. extreme corner case
        # where the feasibility check above passes but the per-fold geometry
        # collapses). Surface this as the same auto-FAIL.
        logger.warning(
            "[PROMOTION_GATE_CPCV_EMBARGO_ZERO] per-fold embargo wiped "
            "train_idx: %s", exc,
        )
        return {
            "name": "cpcv",
            "passed": False,
            "value": None,
            "threshold": 0.0,
            "details": {
                "reason": "insufficient_data_for_leakage_safe_cpcv",
                "n_obs": int(n),
                "k": int(k),
                "embargo": int(embargo),
                "error": str(exc),
            },
        }
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

    Sprint-0 Wave-5b PROMOTION-GATE-METHODOLOGY (operator Q6=A): the prior
    `n_resamples=1000` was 1/10 of the documented production default
    (`docs/methodology-toolkit.md:56` and `block_bootstrap.py`'s
    `_DEFAULT_N_RESAMPLES=10000`). Pinned to 10000 here so the gate runs
    at the full statistical resolution. This will slow the gate end-to-end
    (~2-3s at T=200, scales linearly with T); tests that previously ran
    fast against this code path now sit closer to ~15s wall — well under
    the pytest --timeout=120 ceiling.
    """
    lo, hi = block_bootstrap_ci(returns, rf_period=0.0, n_resamples=10000, seed=42)
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

    Sprint-0 Wave-5b PROMOTION-GATE-METHODOLOGY (operator Q6=A): the prior
    implementation inferred `directions` from `1 if r > 0 else -1`. Per
    `mc_permutation.py:9-11` the null is "trade-direction labels carry no
    predictive information", so inferring labels from the sign of the
    realized return makes the test trivially significant for any non-zero-
    mean series — it is no longer a meaningful test.

    Per Q6=A: skip MC permutation when no real `directions` parameter is
    supplied. Abstain (`passed=None`) instead, with structured
    `details["reason"]="mc_permutation_requires_real_directions"`. The
    abstention is treated as "not pass" by the 4-of-5 vote tally — the
    strategy must clear the gate on the OTHER 4 votes.

    Args:
        returns:    1-D returns array.
        alpha:      Significance level.
        directions: Optional per-trade direction labels (+1/-1). When
                    supplied, the test runs as before. When None, the
                    vote abstains.
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


def _run_white_rc(
    returns: np.ndarray,
    alpha: float,
    n_trials: int = 1,
    candidate_pool: np.ndarray | None = None,
) -> dict:
    """Run White's Reality Check and return a vote dict.

    Sprint-0 Wave-5b PROMOTION-GATE-METHODOLOGY (operator Q6=A): the prior
    implementation paired the strategy returns against an artificial
    zero-returns baseline to satisfy White RC's N>=2 requirement. While
    mathematically defensible, this is semantically wrong for a
    single-strategy gate: the test conflates "p-value vs zero baseline"
    with "is V_bar > 0", losing the multi-strategy data-snooping correction
    that is the whole point of White RC.

    Per Q6=A: when `n_trials==1` AND no real `candidate_pool` is supplied,
    abstain (`passed=None`) with structured
    `details["reason"]="white_rc_requires_candidate_pool"`. The abstention
    is treated as "not pass" by the 4-of-5 vote tally — the strategy must
    clear the gate on the OTHER 4 votes (operator chose strict).

    When a real `candidate_pool` (T, N>=1) is supplied, columns are stacked
    with the strategy returns to form the (T, N+1) input matrix, and the
    test runs at full statistical meaning.

    Args:
        returns:        1-D strategy returns (length T).
        alpha:          Significance level.
        n_trials:       Number of strategies tried in research. Default 1
                        (single-strategy case → abstain when no pool).
        candidate_pool: Optional (T, N>=1) matrix of competing-strategy
                        returns. If supplied, the test runs against the
                        real pool. If None and n_trials==1, abstain.
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
        # n_trials > 1 but no explicit pool — fall back to the legacy
        # 2-column [returns, zeros] surface. This preserves backward compat
        # for callers that pass n_trials > 1 (signaling multi-strategy
        # research) but haven't yet plumbed the actual candidate-pool
        # matrix through. The semantically richer N>1 pool wiring is the
        # follow-up; here we at least don't silently abstain on what was
        # the prior contract.
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
    # Sprint-0 Wave-5b PROMOTION-GATE-METHODOLOGY sibling-search: same
    # n_resamples=1000 anti-pattern as the bootstrap runner. White RC's
    # documented default is also 10000 (`white_rc.py:25`,
    # `docs/methodology-toolkit.md:55`); pin to that here.
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

    An inverse hard-block occurs when:
      - MC permutation p-value >= (1 − alpha): the permuted (randomized)
        labels score HIGHER than the real labels in >= alpha fraction of
        the permutations, indicating the real edge is negative.
      - AND mean(returns) < 0: confirms the edge is in the wrong direction.

    When both conditions hold, the strategy is actively harmful — five-method
    voting cannot override this structural red flag.

    Sprint-0 Wave-5b PROMOTION-GATE-METHODOLOGY: when MC permutation
    abstains (`passed=None`, `value=None`), the inverse-hard-block detector
    cannot fire — the underlying test wasn't run. We return False so the
    gate falls through to ordinary vote counting (which will then likely
    fail anyway under strict 4-of-5 with an abstention). This is the
    intended semantics: an abstention is not evidence against the strategy,
    just absence of evidence for it.
    """
    p_value = mc_perm_vote.get("value")
    if p_value is None:
        return False
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

    Sprint-0 Wave-5b PROMOTION-GATE-METHODOLOGY (operator Q6=A):
    abstention semantics. A vote may now have `passed=True` (clear pass),
    `passed=False` (clear fail), or `passed=None` (abstain — the underlying
    method couldn't be cleanly evaluated, e.g. White RC without a candidate
    pool, or MC permutation without real direction labels).

    Per Q6=A operator-chose-strict: the 4-of-5 threshold stays rigid.
    Abstentions count as "not passing" — only explicit `passed=True` votes
    contribute to the tally. So 3 voted-pass + 2 abstain → 3 < 4 → reject.
    The strategy must clear the gate on the votes that DID run cleanly.

    Each vote's `details` entry preserves the per-method `details` dict
    (including any `reason` field) for downstream introspection. The
    top-level `details` dict also gains a `n_abstentions` counter so
    operators/dashboards can see at a glance whether the gate decision
    was driven by failed methods or skipped methods.
    """
    votes_bool = {v["name"]: v["passed"] for v in all_votes}
    # Per-method `details` rolled up: include the per-vote `details` payload
    # (reason, n_obs, etc.) when present, alongside value/threshold.
    details: dict = {}
    for v in all_votes:
        entry = {"value": v["value"], "threshold": v["threshold"]}
        if "details" in v:
            entry["details"] = v["details"]
        details[v["name"]] = entry
    details["inverse_hard_block"] = _detect_inverse_hard_block(mc_perm_vote, arr, alpha)
    # Count strict-pass / strict-fail / abstain across the 5 votes.
    n_pass = sum(1 for v in all_votes if v["passed"] is True)
    n_fail = sum(1 for v in all_votes if v["passed"] is False)
    n_abstain = sum(1 for v in all_votes if v["passed"] is None)
    details["n_pass"] = n_pass
    details["n_fail"] = n_fail
    details["n_abstentions"] = n_abstain

    base = {"votes": votes_bool, "n_obs": n_obs, "mintrl": mintrl_val, "details": details}

    if n_obs < mintrl_val:
        return {**base, "decision": "defer", "reason": "insufficient_track_record"}

    if details["inverse_hard_block"]:
        return {**base, "decision": "reject"}

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
    directions: Sequence[int] | None = None,
    candidate_pool: np.ndarray | None = None,
) -> dict:
    """Evaluate a strategy via 5 methodology methods and return a promote/defer/reject decision.

    Runs CPCV, block-bootstrap CI, MC permutation, PSR/DSR, and White's
    Reality Check. Aggregates votes and applies MinTRL and inverse-hard-block
    guards before deciding.

    Args:
        returns:        1-D array-like of per-period returns (e.g. per-trade PnL).
                        Must have length >= 5.
        n_trials:       Number of strategies tried in the research process
                        (used for DSR multi-testing correction). Pass 1 for a
                        single-strategy case.
        alpha:          Significance level. Default 0.05 (canonical; do not change).
        dates:          Sprint-0 Wave-3b RF-WIRING. Optional list of per-period
                        dates (one `datetime.date` per element of `returns`). When
                        supplied, the gate fetches per-trade rf from FRED DTB3
                        via src.methods._rf_vector.compute_per_period_rf_vector
                        and runs every method against the rf-excess series. When
                        omitted (legacy callers), all methods see raw `returns`
                        with rf_period=0.0 — preserving the prior behaviour.
        directions:     Sprint-0 Wave-5b PROMOTION-GATE-METHODOLOGY (operator
                        Q6=A). Optional per-trade direction labels (+1/-1)
                        for the MC permutation test. When None, MC perm
                        abstains (vote `passed=None`) per Q6=A — the prior
                        sign-of-return inference made the test trivially
                        significant.
        candidate_pool: Sprint-0 Wave-5b PROMOTION-GATE-METHODOLOGY (operator
                        Q6=A). Optional (T, N>=1) candidate-pool returns for
                        White's Reality Check. When None and n_trials==1,
                        White RC abstains (vote `passed=None`) per Q6=A —
                        the prior zero-baseline pairing semantically conflated
                        the multi-strategy data-snooping correction with a
                        single-strategy V_bar > 0 test.

    Returns:
        dict with keys:
          "decision":  "promote" | "defer" | "reject"
          "votes":     {method_name: pass_bool_or_None, ...}
          "n_obs":     int — length of returns series
          "mintrl":    int — minimum track record length at alpha
          "details":   dict — per-method value/threshold + metadata. Includes
                       "rf_source": "fred_dtb3" | "placeholder" | "unwired"
                       so callers can verify whether the FRED rf wiring
                       actually fired. Also includes `n_pass`, `n_fail`,
                       `n_abstentions` counters (Wave-5b).
          "reason":    str (present on "defer" only)

    Decision rules (in priority order):
      1. If N < mintrl → "defer" (reason="insufficient_track_record")
      2. If inverse hard-block detected → "reject" (MC perm p >= 1−alpha AND mean < 0)
      3. If ≥4 of 5 method votes pass → "promote", else "reject"

    Vote semantics (Wave-5b):
      - `passed=True`  — vote contributes 1 to the 4-of-5 tally.
      - `passed=False` — vote does NOT contribute.
      - `passed=None`  — vote abstained; does NOT contribute. Strict 4-of-5
                         stays rigid (operator Q6=A) so an abstention forces
                         the strategy to pass on the OTHER 4 votes.
    """
    arr = np.asarray(returns, dtype=float)
    if dates is not None:
        arr_for_methods, rf_source = _adjust_returns_via_fred(arr, dates)
    else:
        arr_for_methods = arr
        rf_source = "unwired"

    vote_mc_perm = _run_mc_perm(arr_for_methods, alpha, directions=directions)
    all_votes = [
        _run_cpcv(arr_for_methods, alpha),
        _run_bootstrap(arr_for_methods, alpha),
        vote_mc_perm,
        _run_psr(arr_for_methods, n_trials, alpha),
        _run_white_rc(
            arr_for_methods, alpha,
            n_trials=n_trials, candidate_pool=candidate_pool,
        ),
    ]
    decision = _decide(
        all_votes, vote_mc_perm, arr_for_methods,
        len(arr_for_methods), mintrl(arr_for_methods, alpha=alpha), alpha,
    )
    decision["details"]["rf_source"] = rf_source
    return decision
