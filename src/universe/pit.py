"""Point-in-time universe and dividend-haircut utilities.

get_sp100_at(as_of_date, membership_table)
    Returns the SP100 constituent list as it was on `as_of_date`, consulting
    a historical membership table keyed by ISO-date strings.

    The production membership table is wired in a future task (T2.09+). For
    now the caller must supply the table explicitly (or rely on tests that
    inject a fixture table). This avoids survivorship bias: callers receive
    only the tickers that were actually in the index on the requested date.

apply_dividend_haircut(returns, dividend_yield_pct, period_days)
    Subtracts the period-prorated dividend yield from a return figure.
    All numeric arguments use decimal fractions (1% = 0.01). period_days
    is a non-negative integer.

    Formula: adjusted = returns - dividend_yield_pct * (period_days / 365)
"""

from typing import Optional


def get_sp100_at(
    as_of_date: str,
    membership_table: Optional[dict] = None,
) -> list:
    """Return the SP100 universe as it was on as_of_date.

    Args:
        as_of_date: ISO-format date string, e.g. "2024-01-01".
        membership_table: Dict mapping ISO-date strings to lists of tickers.
            Uses the most-recent snapshot whose key is <= as_of_date.
            Pass an empty dict to get an empty result (no snapshot available).

    Returns:
        Alphabetically sorted list of ticker strings for that date.
        Returns [] if no snapshot exists on or before as_of_date.
    """
    if membership_table is None:
        membership_table = {}

    if not membership_table:
        return []

    eligible = [k for k in membership_table if k <= as_of_date]
    if not eligible:
        return []

    snapshot_key = max(eligible)
    return sorted(membership_table[snapshot_key])


def apply_dividend_haircut(
    returns: float,
    dividend_yield_pct: float,
    period_days: int,
) -> float:
    """Subtract the period-prorated dividend yield from a return.

    Converts price-only returns to a dividend-adjusted approximation suitable
    for excess-Sharpe calculations without requiring a full dividend timeseries.

    Args:
        returns: Holding-period return as a decimal fraction (0.01 = 1%).
        dividend_yield_pct: Annual dividend yield as a decimal fraction
            (0.02 = 2%). Must be >= 0.
        period_days: Number of calendar days in the holding period (integer).
            Use 0 to apply no haircut.

    Returns:
        Adjusted return: returns - dividend_yield_pct * (period_days / 365).
    """
    return returns - dividend_yield_pct * (period_days / 365)
