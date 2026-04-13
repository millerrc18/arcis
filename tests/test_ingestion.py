"""Tests for market data ingestion.

CLAUDE.md: no external-API calls during pytest. yfinance is mocked so these
tests run offline and deterministically. The expectation we're testing is that
our code correctly extracts OHLCV columns and keys-by-ticker from whatever
yfinance returns — we don't need the real network to verify that wrapper logic.
"""

from unittest.mock import patch

import pandas as pd

from src.data_ingestion.market_data import fetch_ohlcv, fetch_spy_benchmark

EXPECTED_COLUMNS = ["Open", "High", "Low", "Close", "Volume"]


def _fake_ohlcv_df(rows: int = 5) -> pd.DataFrame:
    """Deterministic OHLCV stub matching yfinance's single-ticker shape."""
    idx = pd.date_range("2026-01-01", periods=rows, freq="D")
    return pd.DataFrame(
        {
            "Open":   [100.0 + i for i in range(rows)],
            "High":   [101.0 + i for i in range(rows)],
            "Low":    [ 99.0 + i for i in range(rows)],
            "Close":  [100.5 + i for i in range(rows)],
            "Volume": [1_000_000 + i for i in range(rows)],
        },
        index=idx,
    )


def test_fetch_ohlcv_returns_dict():
    # Multi-ticker branch of fetch_ohlcv uses group_by="ticker" layout.
    frames = {t: _fake_ohlcv_df() for t in ("AAPL", "MSFT")}
    multi = pd.concat(frames, axis=1)  # MultiIndex (ticker, col)
    with patch("src.data_ingestion.market_data.yf.download", return_value=multi):
        result = fetch_ohlcv(["AAPL", "MSFT"], period="5d")
    assert isinstance(result, dict)


def test_ohlcv_has_expected_columns():
    with patch("src.data_ingestion.market_data.yf.download", return_value=_fake_ohlcv_df()):
        result = fetch_ohlcv(["AAPL"], period="5d")
    assert "AAPL" in result
    df = result["AAPL"]
    assert isinstance(df, pd.DataFrame)
    for col in EXPECTED_COLUMNS:
        assert col in df.columns, f"Missing column: {col}"


def test_fetch_spy_benchmark():
    with patch("src.data_ingestion.market_data.yf.download", return_value=_fake_ohlcv_df()):
        df = fetch_spy_benchmark(period="5d")
    assert isinstance(df, pd.DataFrame)
    assert not df.empty
    for col in EXPECTED_COLUMNS:
        assert col in df.columns, f"Missing column: {col}"


def test_empty_tickers_returns_empty():
    # No yfinance mock needed — fetch_ohlcv returns {} before calling yf.download.
    result = fetch_ohlcv([], period="5d")
    assert result == {}
