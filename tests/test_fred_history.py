"""Tests for FRED historical data fetch and point-in-time lookup."""

import pandas as pd
import pytest

from src.training.historical_data import get_fred_value_as_of


# ── Fixtures ──────────────────────────────────────────────────────────


def _make_fred_data() -> dict[str, pd.Series]:
    """Create synthetic FRED data for testing."""
    # Monthly-ish data: Jan, Feb, Mar 2024
    vix_dates = pd.to_datetime(["2024-01-02", "2024-01-15", "2024-02-01", "2024-02-15", "2024-03-01"])
    vix_values = [13.5, 14.2, 16.8, 18.1, 15.3]

    spread_dates = pd.to_datetime(["2024-01-05", "2024-02-05", "2024-03-05"])
    spread_values = [-0.45, -0.32, 0.10]

    return {
        "VIXCLS": pd.Series(vix_values, index=vix_dates, name="VIXCLS"),
        "T10Y2Y": pd.Series(spread_values, index=spread_dates, name="T10Y2Y"),
    }


# ── Point-in-time lookup tests ───────────────────────────────────────


class TestFredPointInTime:
    """Verify point-in-time lookups prevent lookahead bias."""

    def test_fred_lookup_returns_point_in_time(self):
        """Feb 15 lookup returns Feb value, not March."""
        fred_data = _make_fred_data()

        # Look up VIX as of Feb 15 — should get the Feb 15 value (18.1)
        value = get_fred_value_as_of(fred_data, "VIXCLS", "2024-02-15")
        assert value == 18.1

        # Look up VIX as of Feb 10 — should get Feb 1 value (16.8), not Feb 15
        value = get_fred_value_as_of(fred_data, "VIXCLS", "2024-02-10")
        assert value == 16.8

        # Look up spread as of Feb 20 — should get Feb value (-0.32), not March
        value = get_fred_value_as_of(fred_data, "T10Y2Y", "2024-02-20")
        assert value == -0.32

    def test_fred_missing_returns_none(self):
        """Lookup for a date before series start returns None."""
        fred_data = _make_fred_data()

        # Before any data exists
        value = get_fred_value_as_of(fred_data, "VIXCLS", "2023-12-01")
        assert value is None

    def test_fred_missing_series_returns_none(self):
        """Lookup for a series not in fred_data returns None."""
        fred_data = _make_fred_data()

        value = get_fred_value_as_of(fred_data, "UNRATE", "2024-02-15")
        assert value is None

    def test_fred_empty_data_returns_none(self):
        """Lookup with empty fred_data returns None."""
        value = get_fred_value_as_of({}, "VIXCLS", "2024-02-15")
        assert value is None

    def test_fred_exact_date_match(self):
        """Lookup on exact observation date returns that value."""
        fred_data = _make_fred_data()

        value = get_fred_value_as_of(fred_data, "T10Y2Y", "2024-03-05")
        assert value == 0.10

    def test_fred_latest_value_returned(self):
        """Lookup well past all data returns the most recent value."""
        fred_data = _make_fred_data()

        value = get_fred_value_as_of(fred_data, "VIXCLS", "2024-12-31")
        assert value == 15.3  # The March value (last in series)
