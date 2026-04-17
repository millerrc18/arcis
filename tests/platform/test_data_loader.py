"""Tests for src.platform.data_loader — thin adapter over simulation.cache."""
from unittest.mock import patch

import pandas as pd
import pytest

from src.platform.data_loader import (
    load_ohlcv_range,
    load_spy_return,
    load_universe_as_of,
)


def test_load_ohlcv_aapl_returns_dataframe():
    df = load_ohlcv_range("AAPL", "2023-06-01", "2023-06-30")
    # Either cached parquet or live yfinance returns a DataFrame
    if df is None:
        pytest.skip("no cached AAPL data in this environment")
    assert isinstance(df, pd.DataFrame)
    assert not df.empty
    assert set(["Open", "High", "Low", "Close"]).issubset(df.columns)


def test_load_ohlcv_missing_ticker_returns_none():
    df = load_ohlcv_range("ZZZZZZ_NOT_A_TICKER", "2023-06-01", "2023-06-05")
    assert df is None


def test_load_spy_return_matches_benchmark_module():
    with patch("src.platform.data_loader.spy_return_over_range") as m:
        m.return_value = 0.0123
        out = load_spy_return("2023-06-01", "2023-06-15")
    assert out == 0.0123
    m.assert_called_once_with("2023-06-01", "2023-06-15")


def test_load_universe_sp500_falls_back_to_sp100_with_warning(caplog):
    import logging
    with caplog.at_level(logging.WARNING, logger="src.platform.data_loader"):
        out = load_universe_as_of("sp500", "2023-06-01")
    assert isinstance(out, list)
    assert len(out) >= 100  # actual S&P 100 list has 102 entries (GOOG + GOOGL both included)
    assert any("sp500" in r.message and "falling back" in r.message
               for r in caplog.records)
