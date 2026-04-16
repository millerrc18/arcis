"""Tests for SPY benchmark utility (SD#41 REVISED / Sprint D1)."""

from unittest.mock import patch

import pandas as pd
import pytest

from src.analytics.spy_benchmark import (
    _load_sector_lookup,
    excess_return,
    get_sector,
    spy_return_over_range,
)


def test_excess_return_positive_when_beating_spy():
    """pnl_pct=5.0 (percent), spy=0.02 (fraction) -> excess = 5 - 2 = 3.0."""
    assert excess_return(5.0, 0.02) == pytest.approx(3.0)


def test_excess_return_negative_when_losing_to_spy():
    """pnl_pct=1.0, spy=+3% -> excess = 1 - 3 = -2.0."""
    assert excess_return(1.0, 0.03) == pytest.approx(-2.0)


def test_excess_return_none_when_spy_unavailable():
    """Missing SPY data must propagate as None, not as zero."""
    assert excess_return(1.0, None) is None


def test_excess_return_none_when_pnl_none():
    """Missing pnl_pct must propagate as None."""
    assert excess_return(None, 0.02) is None


def test_spy_return_handles_empty_yfinance_response():
    """Empty DataFrame from yfinance -> None (not crash, not zero)."""
    with patch("yfinance.download") as mock_dl:
        mock_dl.return_value = pd.DataFrame()
        assert (
            spy_return_over_range(
                "2026-01-01T10:00:00", "2026-01-05T10:00:00"
            )
            is None
        )


def test_spy_return_handles_exception_gracefully():
    """Any yfinance exception -> None; never propagates to the exit path."""
    with patch("yfinance.download", side_effect=Exception("net")):
        assert (
            spy_return_over_range(
                "2026-01-01T10:00:00", "2026-01-05T10:00:00"
            )
            is None
        )


def test_get_sector_returns_none_for_unknown_ticker():
    """Unknown ticker returns None; must not raise KeyError."""
    _load_sector_lookup.cache_clear()
    assert get_sector("FAKEZZ") is None
