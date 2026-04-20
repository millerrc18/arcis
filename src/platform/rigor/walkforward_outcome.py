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


def _count_states(window_states: dict[int, str]) -> dict[str, int]:
    """Count occurrences of each per-window state. Single pass over states."""
    counts = {
        WINDOW_PASS: 0, WINDOW_FAIL: 0, WINDOW_INCONCLUSIVE_POWER: 0,
        WINDOW_INCONCLUSIVE_DATA: 0, WINDOW_INCONCLUSIVE_DURATION: 0,
    }
    for s in window_states.values():
        if s in counts:
            counts[s] += 1
    return counts


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
    """Deterministic reducer. Priority: duration > data > power > pass-count >
    drawdown > regime > pooled-sharpe > overall PASS. The duration check (R6
    extension v0.25.4 #538) takes precedence over data/power so operators
    can distinguish "window too short" from "strategy didn't signal."
    """
    c = _count_states(window_states)

    def _wrap(state: str, reason: str) -> OutcomeResult:
        return OutcomeResult(
            outcome_state=state, reason=reason,
            n_windows_pass=c[WINDOW_PASS], n_windows_fail=c[WINDOW_FAIL],
            n_windows_inconclusive_power=c[WINDOW_INCONCLUSIVE_POWER],
            n_windows_inconclusive_data=c[WINDOW_INCONCLUSIVE_DATA],
            n_windows_inconclusive_duration=c[WINDOW_INCONCLUSIVE_DURATION],
        )

    if c[WINDOW_INCONCLUSIVE_DURATION] >= inconclusive_window_threshold:
        return _wrap(STATE_INCONCLUSIVE, "duration_inconclusive")
    if c[WINDOW_INCONCLUSIVE_DATA] >= inconclusive_window_threshold:
        return _wrap(STATE_INCONCLUSIVE, "coverage_inconclusive")
    if c[WINDOW_INCONCLUSIVE_POWER] >= inconclusive_window_threshold:
        return _wrap(STATE_INCONCLUSIVE, "power_inconclusive")
    if c[WINDOW_PASS] < windows_passing_criterion_2:
        return _wrap(STATE_FAIL, "criterion_2_windows")
    if any(mdd > max_drawdown_cap_pct for mdd in max_drawdowns):
        return _wrap(STATE_FAIL, "criterion_4_drawdown")
    if distinct_vix_tiers < min_vix_tiers:
        return _wrap(STATE_FAIL, "criterion_5_regime_coverage")
    if pooled_sharpe < pooled_sharpe_min:
        return _wrap(STATE_FAIL, "criterion_3_pooled_sharpe")
    return _wrap(STATE_PASS, "walkforward_pass")
