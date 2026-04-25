"""Tests for point-in-time universe and dividend-haircut functions."""

import pytest
from src.universe.pit import get_sp100_at, apply_dividend_haircut


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

MEMBERSHIP_TABLE = {
    "2023-06-01": ["AAPL", "MSFT", "GOOG"],
    "2024-01-01": ["AAPL", "MSFT", "GOOG", "NVDA"],
    "2024-07-01": ["AAPL", "MSFT", "NVDA"],          # GOOG removed
    "2025-01-01": ["AAPL", "MSFT", "NVDA", "META"],  # META added
}


# ---------------------------------------------------------------------------
# get_sp100_at tests
# ---------------------------------------------------------------------------

def test_get_sp100_at_exact_date(membership_table=MEMBERSHIP_TABLE):
    """Exact snapshot date returns exactly that snapshot."""
    result = get_sp100_at("2024-01-01", membership_table=membership_table)
    assert result == ["AAPL", "GOOG", "MSFT", "NVDA"]


def test_get_sp100_at_between_snapshots(membership_table=MEMBERSHIP_TABLE):
    """Date between two snapshots returns the most recent prior snapshot."""
    # 2024-03-15 is after 2024-01-01 and before 2024-07-01
    result = get_sp100_at("2024-03-15", membership_table=membership_table)
    assert result == ["AAPL", "GOOG", "MSFT", "NVDA"]


def test_get_sp100_at_addition_appears_after_join_date(membership_table=MEMBERSHIP_TABLE):
    """Ticker added in a later snapshot is absent before and present after."""
    before = get_sp100_at("2024-06-30", membership_table=membership_table)
    after = get_sp100_at("2024-07-01", membership_table=membership_table)
    assert "GOOG" in before
    assert "GOOG" not in after


def test_get_sp100_at_removal_drops_from_universe(membership_table=MEMBERSHIP_TABLE):
    """Ticker removed in a snapshot is absent on that date."""
    result = get_sp100_at("2025-01-01", membership_table=membership_table)
    assert "META" in result
    assert "GOOG" not in result


def test_get_sp100_at_empty_table():
    """Empty membership table returns empty list."""
    result = get_sp100_at("2024-01-01", membership_table={})
    assert result == []


def test_get_sp100_at_date_before_all_snapshots(membership_table=MEMBERSHIP_TABLE):
    """Date before the earliest snapshot returns empty list."""
    result = get_sp100_at("2020-01-01", membership_table=membership_table)
    assert result == []


def test_get_sp100_at_returns_sorted_list(membership_table=MEMBERSHIP_TABLE):
    """Returned list is alphabetically sorted."""
    result = get_sp100_at("2025-01-01", membership_table=membership_table)
    assert result == sorted(result)


# ---------------------------------------------------------------------------
# apply_dividend_haircut tests
# ---------------------------------------------------------------------------

def test_apply_dividend_haircut_basic():
    """1% annual yield, 30-day period, 1% return -> ~0.9178% return."""
    # Inputs: all decimal fractions; period_days int
    # Expected: 0.01 - (0.01 * 30/365) = 0.01 - 0.000821... = 0.009178...
    result = apply_dividend_haircut(
        returns=0.01,
        dividend_yield_pct=0.01,
        period_days=30,
    )
    expected = 0.01 - (0.01 * 30 / 365)
    assert abs(result - expected) < 1e-10


def test_apply_dividend_haircut_zero_yield():
    """Zero dividend yield leaves return unchanged."""
    result = apply_dividend_haircut(
        returns=0.05,
        dividend_yield_pct=0.0,
        period_days=90,
    )
    assert result == pytest.approx(0.05)


def test_apply_dividend_haircut_full_year():
    """365-day period deducts the full annual yield."""
    result = apply_dividend_haircut(
        returns=0.10,
        dividend_yield_pct=0.02,
        period_days=365,
    )
    assert result == pytest.approx(0.10 - 0.02)


def test_apply_dividend_haircut_negative_return():
    """Haircut is applied even when return is negative."""
    result = apply_dividend_haircut(
        returns=-0.03,
        dividend_yield_pct=0.02,
        period_days=182,
    )
    expected = -0.03 - (0.02 * 182 / 365)
    assert result == pytest.approx(expected)


def test_apply_dividend_haircut_zero_period_days():
    """Zero-day period applies zero haircut."""
    result = apply_dividend_haircut(
        returns=0.05,
        dividend_yield_pct=0.03,
        period_days=0,
    )
    assert result == pytest.approx(0.05)
