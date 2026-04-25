"""Tests for instrumentation_filter module (T1.08).

Covers:
  - is_fully_instrumented predicate (NULL, empty-string, None, type checks)
  - filter_fully_instrumented order preservation + empty input
  - assess_statistical_power Bailey-LdP MinTRL boundary behaviour
  - integration: synthetic trade list -> filter+power chain
"""

from __future__ import annotations

import math

import pytest

from src.analytics.instrumentation_filter import (
    PowerAssessment,
    assess_statistical_power,
    filter_fully_instrumented,
    is_fully_instrumented,
)

UNDERPOWERED_PHRASE = (
    "Stage-1 sample is underpowered; reported Sharpe is not "
    "statistically reliable. Consider deferring promotion until "
    "N >= MinTRL."
)


# ---- is_fully_instrumented -------------------------------------------------


def _full_row():
    return {
        "pnl_pct": 1.5,
        "actual_entry_time": "2026-04-20T14:30:00Z",
        "actual_exit_time": "2026-04-22T15:55:00Z",
        "excess_return": 0.4,
    }


def test_is_fully_instrumented_all_present():
    assert is_fully_instrumented(_full_row()) is True


def test_is_fully_instrumented_zero_pnl_is_valid():
    """0.0 is a real value, NOT missing."""
    row = _full_row()
    row["pnl_pct"] = 0.0
    row["excess_return"] = 0.0
    assert is_fully_instrumented(row) is True


@pytest.mark.parametrize(
    "missing_col",
    ["pnl_pct", "actual_entry_time", "actual_exit_time", "excess_return"],
)
def test_is_fully_instrumented_none_fails(missing_col):
    row = _full_row()
    row[missing_col] = None
    assert is_fully_instrumented(row) is False


@pytest.mark.parametrize(
    "missing_col",
    ["pnl_pct", "actual_entry_time", "actual_exit_time", "excess_return"],
)
def test_is_fully_instrumented_empty_string_fails(missing_col):
    """SQLite doesn't enforce typing — '' counts as missing."""
    row = _full_row()
    row[missing_col] = ""
    assert is_fully_instrumented(row) is False


@pytest.mark.parametrize(
    "missing_col",
    ["pnl_pct", "actual_entry_time", "actual_exit_time", "excess_return"],
)
def test_is_fully_instrumented_absent_key_fails(missing_col):
    row = _full_row()
    del row[missing_col]
    assert is_fully_instrumented(row) is False


def test_is_fully_instrumented_non_string_time_fails():
    """Time fields must be strings; ints/floats count as missing."""
    row = _full_row()
    row["actual_entry_time"] = 1234567890
    assert is_fully_instrumented(row) is False


def test_is_fully_instrumented_whitespace_only_string_fails():
    """A bare whitespace string is effectively empty."""
    row = _full_row()
    row["actual_entry_time"] = "   "
    assert is_fully_instrumented(row) is False


# ---- filter_fully_instrumented ---------------------------------------------


def test_filter_preserves_order_and_drops_partials():
    rows = [
        {**_full_row(), "trade_id": "A"},
        {**_full_row(), "trade_id": "B", "pnl_pct": None},
        {**_full_row(), "trade_id": "C"},
        {**_full_row(), "trade_id": "D", "actual_exit_time": ""},
        {**_full_row(), "trade_id": "E"},
    ]
    out = filter_fully_instrumented(rows)
    assert [r["trade_id"] for r in out] == ["A", "C", "E"]


def test_filter_empty_input_returns_empty_list():
    assert filter_fully_instrumented([]) == []


def test_filter_returns_list_not_generator():
    """Caller may iterate twice; the result must be materialized."""
    out = filter_fully_instrumented(iter([_full_row()]))
    assert isinstance(out, list)
    assert len(out) == 1
    assert len(out) == 1  # iterate twice; still 1


# ---- assess_statistical_power ----------------------------------------------


def test_assess_returns_dataclass_shape():
    res = assess_statistical_power(n=100)
    assert isinstance(res, PowerAssessment)
    assert res.n == 100
    assert isinstance(res.mintrl_required, float)
    assert res.status in {"powered", "underpowered", "marginal"}
    assert isinstance(res.message, str) and res.message != ""


def test_assess_mintrl_value_target_zero_alpha_05():
    """Bailey-LdP closed-form, target=0, alpha=0.05, Gaussian fallback:
    MinTRL = 1 + z_(alpha/2)^2 ≈ 1 + 1.959964^2 ≈ 4.84 per audit §F-1.
    """
    res = assess_statistical_power(n=10, target_sharpe=0.0, alpha=0.05)
    # 1 + 1.959963984540054**2 == 4.841458820694112
    assert res.mintrl_required == pytest.approx(4.841458820694112, rel=1e-6)


def test_assess_underpowered_below_mintrl():
    res = assess_statistical_power(n=3, target_sharpe=0.0, alpha=0.05)
    assert res.status == "underpowered"
    assert UNDERPOWERED_PHRASE in res.message


def test_assess_marginal_at_or_above_mintrl_below_2x():
    """MinTRL ≈ 4.84; n=5 ≥ MinTRL but < 2*MinTRL ≈ 9.68 -> marginal."""
    res = assess_statistical_power(n=5, target_sharpe=0.0, alpha=0.05)
    assert res.status == "marginal"
    assert UNDERPOWERED_PHRASE not in res.message


def test_assess_marginal_at_exactly_mintrl_boundary():
    """N == ceil(MinTRL) == 5 -> marginal (the lower boundary)."""
    res = assess_statistical_power(n=5, target_sharpe=0.0, alpha=0.05)
    # n=5 is the smallest int >= 4.84; this should be 'marginal' not 'underpowered'.
    assert res.n >= res.mintrl_required
    assert res.status == "marginal"


def test_assess_powered_at_2x_mintrl():
    """N ≥ 2*MinTRL ≈ 9.68 -> powered."""
    res = assess_statistical_power(n=10, target_sharpe=0.0, alpha=0.05)
    assert res.status == "powered"
    assert UNDERPOWERED_PHRASE not in res.message


def test_assess_powered_message_does_not_contain_warning():
    res = assess_statistical_power(n=200, target_sharpe=0.0, alpha=0.05)
    assert res.status == "powered"
    assert UNDERPOWERED_PHRASE not in res.message


def test_assess_alpha_changes_mintrl():
    """Tighter alpha -> larger z -> larger MinTRL."""
    loose = assess_statistical_power(n=10, alpha=0.10)
    tight = assess_statistical_power(n=10, alpha=0.01)
    assert tight.mintrl_required > loose.mintrl_required


def test_assess_alpha_001_value():
    """alpha=0.01 (two-sided) -> z_(alpha/2) = Phi^-1(0.995) ≈ 2.5758;
    MinTRL ≈ 1 + 2.5758^2 ≈ 7.6349.
    """
    res = assess_statistical_power(n=10, target_sharpe=0.0, alpha=0.01)
    # Phi^-1(0.995) ≈ 2.5758293035489004
    expected = 1.0 + 2.5758293035489004 ** 2
    assert res.mintrl_required == pytest.approx(expected, rel=1e-6)


def test_assess_non_zero_target_raises_or_marks_unsupported():
    """Scope fence: non-zero target_sharpe is T2.04 territory; not implemented here."""
    with pytest.raises((NotImplementedError, ValueError)):
        assess_statistical_power(n=10, target_sharpe=0.5)


# ---- integration -----------------------------------------------------------


def test_integration_filter_then_power_5_of_8():
    """Synthetic 8-row trade list: 5 fully-instrumented, 3 missing-various-cols.
    After filter -> N=5; with target=0 alpha=0.05 -> 'marginal'."""
    rows = [
        {**_full_row(), "trade_id": "T1"},                              # full
        {**_full_row(), "trade_id": "T2", "pnl_pct": None},             # missing pnl
        {**_full_row(), "trade_id": "T3"},                              # full
        {**_full_row(), "trade_id": "T4", "actual_entry_time": ""},     # missing entry
        {**_full_row(), "trade_id": "T5"},                              # full
        {**_full_row(), "trade_id": "T6", "excess_return": None},       # missing excess
        {**_full_row(), "trade_id": "T7"},                              # full
        {**_full_row(), "trade_id": "T8"},                              # full
    ]
    instrumented = filter_fully_instrumented(rows)
    assert len(instrumented) == 5
    assert [r["trade_id"] for r in instrumented] == ["T1", "T3", "T5", "T7", "T8"]
    res = assess_statistical_power(n=len(instrumented))
    assert res.n == 5
    assert res.status == "marginal"


def test_integration_filter_then_power_underpowered():
    """3 fully-instrumented + 5 partials -> N=3 -> 'underpowered'."""
    rows = [
        {**_full_row(), "trade_id": "P1"},                              # full
        {**_full_row(), "trade_id": "P2", "pnl_pct": None},
        {**_full_row(), "trade_id": "P3", "actual_entry_time": ""},
        {**_full_row(), "trade_id": "P4"},                              # full
        {**_full_row(), "trade_id": "P5", "excess_return": ""},
        {**_full_row(), "trade_id": "P6", "actual_exit_time": None},
        {**_full_row(), "trade_id": "P7"},                              # full
        {**_full_row(), "trade_id": "P8", "pnl_pct": ""},
    ]
    instrumented = filter_fully_instrumented(rows)
    assert len(instrumented) == 3
    res = assess_statistical_power(n=len(instrumented))
    assert res.status == "underpowered"
    assert UNDERPOWERED_PHRASE in res.message
