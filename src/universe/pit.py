"""Point-in-time universe and dividend-haircut utilities.

get_sp100_at(as_of_date, membership_table)
    Returns the SP100 constituent list as it was on `as_of_date`, consulting
    a historical membership table keyed by ISO-date strings.

    Production membership table is loaded from data/reference/sp100_history.json
    (regenerated manually via scripts/build_sp100_history.py — Wikipedia-sourced
    + curated event list).

load_sp100_membership_table()
    Load the SP100 historical membership table from data/reference/sp100_history.json.
    Cached at module level via @lru_cache(maxsize=1).

get_data_range()
    Return (earliest_date, latest_date) covered by the loaded membership table as
    date objects.

UniverseDataMissing
    Raised when SP100 membership data is unavailable for a requested as_of date.

apply_dividend_haircut(returns, dividend_yield_pct, period_days)
    Subtracts the period-prorated dividend yield from a return figure.
    All numeric arguments use decimal fractions (1% = 0.01). period_days
    is a non-negative integer.

    Formula: adjusted = returns - dividend_yield_pct * (period_days / 365)

Called by: production PIT-aware backtest paths. 24 legacy callers still use src.universe.sp100.get_sp100_universe() (migration to this module is deferred to Sprint 1.A.1).
Calls: nothing external (pure-function utilities over a caller-supplied membership_table dict).
Owns tables: data/reference/sp100_history.json (regenerated via scripts/build_sp100_history.py).
Config keys: none.
Tests: tests/universe/test_pit.py.
"""

import json
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Optional


_SP100_HISTORY_PATH = Path(__file__).resolve().parents[2] / 'data' / 'reference' / 'sp100_history.json'


class UniverseDataMissing(Exception):
    """Raised when SP100 membership data is unavailable for a requested as_of date.

    Causes:
      - data/reference/sp100_history.json file is absent (run scripts/build_sp100_history.py)
      - as_of_date is before the earliest covered date in the loaded table
      - as_of_date is after the latest covered date (refresh data via scripts/build_sp100_history.py)
    """


@lru_cache(maxsize=1)
def load_sp100_membership_table() -> dict[str, list[str]]:
    """Load the SP100 historical membership table from data/reference/sp100_history.json.

    Cached at module level — first call reads + parses; subsequent calls return
    the cached dict. Use `load_sp100_membership_table.cache_clear()` in tests if
    you need to force a re-read after monkeypatching the data file.

    Returns:
        Dict mapping ISO-date strings (e.g. '2024-01-01') to sorted lists of
        ticker strings.

    Raises:
        UniverseDataMissing: if the JSON file is absent. The exception message
            instructs the operator to run scripts/build_sp100_history.py.
    """
    if not _SP100_HISTORY_PATH.exists():
        raise UniverseDataMissing(
            f"SP100 historical membership file not found at {_SP100_HISTORY_PATH}. "
            f"Run `python scripts/build_sp100_history.py` to generate it."
        )
    with _SP100_HISTORY_PATH.open('r', encoding='utf-8') as f:
        return json.load(f)


def get_data_range() -> tuple[date, date]:
    """Return (earliest_date, latest_date) covered by the loaded membership table.

    Returns date objects (not strings) so callers can compare against datetime.date.

    Raises:
        UniverseDataMissing: if the JSON file is absent (propagated from loader).
    """
    table = load_sp100_membership_table()
    keys = sorted(table.keys())
    earliest = date.fromisoformat(keys[0])
    latest = date.fromisoformat(keys[-1])
    return earliest, latest


def get_sp100_at(
    as_of_date: str,
    membership_table: Optional[dict] = None,
) -> list:
    """Return the SP100 universe as it was on as_of_date.

    Dual-mode:

    Production path (membership_table is None, the default):
        Loads the membership table from data/reference/sp100_history.json via
        load_sp100_membership_table().  Validates that as_of_date falls within
        the covered range; raises UniverseDataMissing for out-of-range dates or
        if the data file is absent.

    Test-fixture path (membership_table is an explicit dict, including {}):
        Uses the caller-supplied table exactly as provided.  The loader is never
        called.  UniverseDataMissing is never raised.
        Empty membership_table={} still returns [] (preserves existing test semantics).

    Args:
        as_of_date: ISO-format date string, e.g. "2024-01-01".
        membership_table: Explicit dict mapping ISO-date strings to lists of
            tickers (test-fixture path), or None to load from
            data/reference/sp100_history.json (production path).

    Returns:
        Alphabetically sorted list of ticker strings for that date.
        Returns [] if no snapshot exists on or before as_of_date.

    Raises:
        UniverseDataMissing: (production path only) if the data file is absent,
            or if as_of_date is before the earliest or after the latest covered date.
        ValueError: if as_of_date is not a valid ISO-format date string.
    """
    if membership_table is None:
        membership_table = load_sp100_membership_table()
        earliest, latest = get_data_range()
        as_of = date.fromisoformat(as_of_date)
        if as_of < earliest:
            raise UniverseDataMissing(
                f"as_of={as_of_date} is before earliest covered date {earliest.isoformat()}"
            )
        if as_of > latest:
            raise UniverseDataMissing(
                f"as_of={as_of_date} is after latest covered date {latest.isoformat()};"
                f" refresh data via scripts/build_sp100_history.py"
            )

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
