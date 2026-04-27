"""Promotion gate orchestrator — runs 5 methodology methods and votes.

Authority: Arcis audit spec §F-12.

Pure-function module — no I/O, no DB on the legacy code path. The Sprint-0
Wave-3b RF-WIRING extension takes an optional `dates` argument and, when
provided, fetches per-period rf via FRED (effectful — see
src.methods._rf_vector); on failure it falls back to placeholder per-index.

Called by: external research scripts (via import).
Calls:
  src.methods.promotion_gate_helpers (per-method runners + helpers),
  src.methods.psr.mintrl.
Owns tables: none.
Config keys: none (FRED_API_KEY env honored transitively via the rf adapter
  when `dates` is supplied).
Tests: tests/methods/test_promotion_gate.py,
       tests/methods/test_promotion_gate_methodology.py.

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
    `details["reason"]="white_rc_requires_candidate_pool"`.
  - For MC permutation, Sprint-0 Wave-5b PROMOTION-GATE-METHODOLOGY
    (operator Q6=A): directions are no longer inferred from the sign of
    returns. When `directions` is not supplied, the vote abstains
    (`passed=None`) with
    `details["reason"]="mc_permutation_requires_real_directions"`.

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

from src.methods.block_bootstrap import block_bootstrap_ci  # re-exported for patch compat
from src.methods.psr import mintrl
from src.methods.promotion_gate_helpers import (
    _adjust_returns_via_fred,
    _detect_inverse_hard_block,
    _run_bootstrap,
    _run_cpcv,
    _run_mc_perm,
    _run_psr,
    _run_white_rc,
)

logger = logging.getLogger(__name__)

_ALPHA = 0.05
_MIN_VOTES_TO_PROMOTE = 4


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
    `passed=False` (clear fail), or `passed=None` (abstain). Per Q6=A
    operator-chose-strict: the 4-of-5 threshold stays rigid. Abstentions
    count as "not passing" — only explicit `passed=True` votes contribute.
    """
    votes_bool = {v["name"]: v["passed"] for v in all_votes}
    details: dict = {}
    for v in all_votes:
        entry = {"value": v["value"], "threshold": v["threshold"]}
        if "details" in v:
            entry["details"] = v["details"]
        details[v["name"]] = entry
    details["inverse_hard_block"] = _detect_inverse_hard_block(mc_perm_vote, arr, alpha)
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


def promotion_gate(
    returns: list | np.ndarray,
    n_trials: int,
    alpha: float = _ALPHA,
    dates: Sequence[_dt.date] | None = None,
    directions: Sequence[int] | None = None,
    candidate_pool: np.ndarray | None = None,
) -> dict:
    """Run 5 methodology votes and return a promote/defer/reject decision.

    See module docstring for full semantics. Per-method runners live in
    promotion_gate_helpers (Sprint-0.B/B1 #730 split).

    Returns dict with keys: decision, votes, n_obs, mintrl, details, reason?.
    Decision priority: (1) N < mintrl → defer; (2) inverse hard-block → reject;
    (3) ≥4-of-5 pass → promote, else reject. Abstentions count as not-pass
    (operator Q6=A strict).
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
