"""Walk-forward three-state outcome state machine (R6 reducer).

Called by: src.platform.rigor.walkforward_runner.
Calls: none.
Owns tables: none.
Config keys: none.
Tests: tests/platform/rigor/test_walkforward_outcome.py.

Single source of truth for how per-window states + pooled metrics +
regime coverage combine into the overall outcome. Split into its own
module so the reducer is unit-testable without the full runner
integration surface.

Outcome states are the exact three strings that persist to
walkforward_results.outcome_state. NEVER collapse to boolean.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence


STATE_PASS = "PASS"
STATE_FAIL = "FAIL"
STATE_INCONCLUSIVE = "INCONCLUSIVE"

# Window-level sub-states — only reported to the dashboard / persisted,
# not returned as overall outcome.
WINDOW_PASS = "PASS"
WINDOW_FAIL = "FAIL"
WINDOW_INCONCLUSIVE_POWER = "INCONCLUSIVE_POWER"
WINDOW_INCONCLUSIVE_DATA = "INCONCLUSIVE_DATA"
# v0.25.4 (#538): window span below min_window_duration_days threshold.
# Takes precedence over INCONCLUSIVE_DATA at both per-window assignment
# and run-level reduction so operators can distinguish "window too short"
# from "strategy didn't signal."
WINDOW_INCONCLUSIVE_DURATION = "INCONCLUSIVE_DURATION"


@dataclass
class OutcomeResult:
    outcome_state: str  # STATE_PASS | STATE_FAIL | STATE_INCONCLUSIVE
    reason: str         # structured reason code
    # Summary counts (used by dashboard + promotion gate)
    n_windows_pass: int
    n_windows_fail: int
    n_windows_inconclusive_power: int
    n_windows_inconclusive_data: int
    n_windows_inconclusive_duration: int = 0


def reduce_outcome(
    window_states: dict[int, str],
    max_drawdowns: Sequence[float],
    pooled_sharpe: float,
    distinct_vix_tiers: int,
    *,
    pooled_sharpe_min: float,
    max_drawdown_cap_pct: float,
    min_vix_tiers: int,
    windows_passing_criterion_2: int,
    inconclusive_window_threshold: int,
) -> OutcomeResult:
    """Deterministic reducer. Priority order:

      0. >= inconclusive_window_threshold windows INCONCLUSIVE_DURATION
         → overall INCONCLUSIVE(duration)  (v0.25.4 #538)
      1. >= inconclusive_window_threshold windows INCONCLUSIVE_DATA
         → overall INCONCLUSIVE(coverage)
      2. >= inconclusive_window_threshold windows INCONCLUSIVE_POWER
         → overall INCONCLUSIVE(power)
      3. fewer than windows_passing_criterion_2 windows PASS
         → overall FAIL(criterion_2_windows)
      4. any window drawdown > cap
         → overall FAIL(criterion_4_drawdown)
      5. distinct VIX tiers < min required
         → overall FAIL(criterion_5_regime_coverage)
      6. pooled Sharpe < min
         → overall FAIL(criterion_3_pooled_sharpe)
      7. otherwise PASS
    """
    n_pass = sum(1 for s in window_states.values() if s == WINDOW_PASS)
    n_fail = sum(1 for s in window_states.values() if s == WINDOW_FAIL)
    n_incpow = sum(
        1 for s in window_states.values() if s == WINDOW_INCONCLUSIVE_POWER
    )
    n_incdata = sum(
        1 for s in window_states.values() if s == WINDOW_INCONCLUSIVE_DATA
    )
    n_incdur = sum(
        1 for s in window_states.values() if s == WINDOW_INCONCLUSIVE_DURATION
    )

    def _wrap(state: str, reason: str) -> OutcomeResult:
        return OutcomeResult(
            outcome_state=state, reason=reason,
            n_windows_pass=n_pass, n_windows_fail=n_fail,
            n_windows_inconclusive_power=n_incpow,
            n_windows_inconclusive_data=n_incdata,
            n_windows_inconclusive_duration=n_incdur,
        )

    if n_incdur >= inconclusive_window_threshold:
        return _wrap(STATE_INCONCLUSIVE, "duration_inconclusive")
    if n_incdata >= inconclusive_window_threshold:
        return _wrap(STATE_INCONCLUSIVE, "coverage_inconclusive")
    if n_incpow >= inconclusive_window_threshold:
        return _wrap(STATE_INCONCLUSIVE, "power_inconclusive")
    if n_pass < windows_passing_criterion_2:
        return _wrap(STATE_FAIL, "criterion_2_windows")
    for mdd in max_drawdowns:
        if mdd > max_drawdown_cap_pct:
            return _wrap(STATE_FAIL, "criterion_4_drawdown")
    if distinct_vix_tiers < min_vix_tiers:
        return _wrap(STATE_FAIL, "criterion_5_regime_coverage")
    if pooled_sharpe < pooled_sharpe_min:
        return _wrap(STATE_FAIL, "criterion_3_pooled_sharpe")
    return _wrap(STATE_PASS, "walkforward_pass")
