"""Tests for the three-state outcome reducer."""
from __future__ import annotations

import pytest

from src.platform.rigor.walkforward_outcome import (
    STATE_FAIL,
    STATE_INCONCLUSIVE,
    STATE_PASS,
    WINDOW_FAIL,
    WINDOW_INCONCLUSIVE_DATA,
    WINDOW_INCONCLUSIVE_POWER,
    WINDOW_PASS,
    reduce_outcome,
)


KW = dict(
    pooled_sharpe_min=0.5,
    max_drawdown_cap_pct=0.20,
    min_vix_tiers=2,
    windows_passing_criterion_2=4,
    inconclusive_window_threshold=2,
)


def test_all_pass_gives_state_pass():
    states = {i: WINDOW_PASS for i in range(5)}
    out = reduce_outcome(
        window_states=states, max_drawdowns=[0.05] * 5,
        pooled_sharpe=0.6, distinct_vix_tiers=3, **KW,
    )
    assert out.outcome_state == STATE_PASS
    assert out.reason == "walkforward_pass"
    assert out.n_windows_pass == 5


def test_two_inconclusive_data_gives_inconclusive_coverage():
    states = {
        0: WINDOW_PASS, 1: WINDOW_PASS, 2: WINDOW_PASS,
        3: WINDOW_INCONCLUSIVE_DATA, 4: WINDOW_INCONCLUSIVE_DATA,
    }
    out = reduce_outcome(
        window_states=states, max_drawdowns=[0.05] * 5,
        pooled_sharpe=0.6, distinct_vix_tiers=3, **KW,
    )
    assert out.outcome_state == STATE_INCONCLUSIVE
    assert out.reason == "coverage_inconclusive"
    assert out.n_windows_inconclusive_data == 2


def test_two_inconclusive_power_gives_inconclusive_power():
    states = {
        0: WINDOW_PASS, 1: WINDOW_PASS,
        2: WINDOW_INCONCLUSIVE_POWER, 3: WINDOW_INCONCLUSIVE_POWER,
        4: WINDOW_PASS,
    }
    out = reduce_outcome(
        window_states=states, max_drawdowns=[0.05] * 5,
        pooled_sharpe=0.6, distinct_vix_tiers=3, **KW,
    )
    assert out.outcome_state == STATE_INCONCLUSIVE
    assert out.reason == "power_inconclusive"
    assert out.n_windows_inconclusive_power == 2


def test_inconclusive_data_takes_precedence_over_power():
    """Both flags present at threshold: coverage wins per spec priority."""
    states = {
        0: WINDOW_INCONCLUSIVE_DATA, 1: WINDOW_INCONCLUSIVE_DATA,
        2: WINDOW_INCONCLUSIVE_POWER, 3: WINDOW_INCONCLUSIVE_POWER,
        4: WINDOW_PASS,
    }
    out = reduce_outcome(
        window_states=states, max_drawdowns=[0.05] * 5,
        pooled_sharpe=0.6, distinct_vix_tiers=3, **KW,
    )
    assert out.outcome_state == STATE_INCONCLUSIVE
    assert out.reason == "coverage_inconclusive"


def test_fewer_than_4_pass_is_fail():
    states = {
        0: WINDOW_PASS, 1: WINDOW_PASS, 2: WINDOW_PASS,
        3: WINDOW_FAIL, 4: WINDOW_FAIL,
    }
    out = reduce_outcome(
        window_states=states, max_drawdowns=[0.05] * 5,
        pooled_sharpe=0.6, distinct_vix_tiers=3, **KW,
    )
    assert out.outcome_state == STATE_FAIL
    assert out.reason == "criterion_2_windows"


def test_drawdown_cap_exceeded_is_fail():
    states = {i: WINDOW_PASS for i in range(5)}
    out = reduce_outcome(
        window_states=states,
        max_drawdowns=[0.05, 0.05, 0.25, 0.05, 0.05],  # one > 20%
        pooled_sharpe=0.6, distinct_vix_tiers=3, **KW,
    )
    assert out.outcome_state == STATE_FAIL
    assert out.reason == "criterion_4_drawdown"


def test_regime_coverage_insufficient_is_fail():
    states = {i: WINDOW_PASS for i in range(5)}
    out = reduce_outcome(
        window_states=states, max_drawdowns=[0.05] * 5,
        pooled_sharpe=0.6, distinct_vix_tiers=1, **KW,  # only 1 tier
    )
    assert out.outcome_state == STATE_FAIL
    assert out.reason == "criterion_5_regime_coverage"


def test_pooled_sharpe_below_threshold_is_fail():
    states = {i: WINDOW_PASS for i in range(5)}
    out = reduce_outcome(
        window_states=states, max_drawdowns=[0.05] * 5,
        pooled_sharpe=0.3, distinct_vix_tiers=3, **KW,
    )
    assert out.outcome_state == STATE_FAIL
    assert out.reason == "criterion_3_pooled_sharpe"


def test_drawdown_takes_precedence_over_regime_and_sharpe():
    """R6 priority: criterion 4 DD > criterion 5 regime > criterion 3 sharpe."""
    states = {i: WINDOW_PASS for i in range(5)}
    out = reduce_outcome(
        window_states=states,
        max_drawdowns=[0.25] * 5,  # all exceed
        pooled_sharpe=0.1, distinct_vix_tiers=0, **KW,
    )
    assert out.outcome_state == STATE_FAIL
    assert out.reason == "criterion_4_drawdown"


def test_four_pass_one_fail_satisfies_criterion_2():
    states = {
        0: WINDOW_PASS, 1: WINDOW_PASS, 2: WINDOW_PASS, 3: WINDOW_PASS,
        4: WINDOW_FAIL,
    }
    out = reduce_outcome(
        window_states=states, max_drawdowns=[0.05] * 5,
        pooled_sharpe=0.6, distinct_vix_tiers=3, **KW,
    )
    assert out.outcome_state == STATE_PASS
    assert out.n_windows_pass == 4
    assert out.n_windows_fail == 1
