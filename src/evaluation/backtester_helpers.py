"""Helpers for the walk-forward backtesting framework.

Called by: evaluation.backtester
Calls: none
Owns tables: none
Config keys: none
Tests: tests/test_backtester.py
"""


def compute_max_drawdown_duration(equity_curve: list[dict]) -> int:
    """Return the longest drawdown duration in the equity curve (in steps).

    Args:
        equity_curve: List of dicts with an ``equity`` key (ascending time order).

    Returns:
        Integer count of steps spent below a prior equity peak.
    """
    max_dd_duration_days = 0
    current_dd_start = 0
    peak_eq = equity_curve[0]["equity"] if equity_curve else 0
    for i, point in enumerate(equity_curve):
        eq = point["equity"]
        if eq >= peak_eq:
            peak_eq = eq
            current_dd_start = i
        else:
            dd_dur = i - current_dd_start
            if dd_dur > max_dd_duration_days:
                max_dd_duration_days = dd_dur
    return max_dd_duration_days
