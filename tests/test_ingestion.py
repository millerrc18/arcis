"""Tests for market data ingestion.

These tests hit the network via yfinance and require internet access.
They use short periods to keep execution fast.
"""

import pandas as pd

from src.data_ingestion.market_data import fetch_ohlcv, fetch_spy_benchmark

EXPECTED_COLUMNS = ["Open", "High", "Low", "Close", "Volume"]


def test_fetch_ohlcv_returns_dict():
    result = fetch_ohlcv(["AAPL", "MSFT"], period="5d")
    assert isinstance(result, dict)


def test_ohlcv_has_expected_columns():
    result = fetch_ohlcv(["AAPL"], period="5d")
    assert "AAPL" in result
    df = result["AAPL"]
    assert isinstance(df, pd.DataFrame)
    for col in EXPECTED_COLUMNS:
        assert col in df.columns, f"Missing column: {col}"


def test_fetch_spy_benchmark():
    df = fetch_spy_benchmark(period="5d")
    assert isinstance(df, pd.DataFrame)
    assert not df.empty
    for col in EXPECTED_COLUMNS:
        assert col in df.columns, f"Missing column: {col}"


def test_empty_tickers_returns_empty():
    result = fetch_ohlcv([], period="5d")
    assert result == {}
