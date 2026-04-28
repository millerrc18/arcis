"""Tests for T5a: point-in-time universe migration in fetch_historical_universe.

Verifies that fetch_historical_universe calls pit.get_sp100_at with an ISO
string derived from start_date, instead of the legacy get_sp100_universe().
"""

import ast
import os
from datetime import date, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest


_HISTORICAL_DATA_PATH = os.path.normpath(os.path.join(
    os.path.dirname(__file__),
    "..", "..",
    "src", "training", "historical_data.py",
))


def _get_module_source():
    with open(_HISTORICAL_DATA_PATH, encoding="utf-8") as f:
        return f.read()


def test_get_sp100_universe_not_imported_at_module_level():
    """get_sp100_universe must not appear as a top-level import."""
    source = _get_module_source()
    tree = ast.parse(source)
    for node in tree.body:
        if isinstance(node, ast.ImportFrom):
            if node.module and "sp100" in node.module:
                names = [alias.name for alias in node.names]
                assert "get_sp100_universe" not in names, (
                    "get_sp100_universe must not be imported at module level "
                    "after T5a migration"
                )


def _make_mock_raw(mock_df):
    mock_raw = MagicMock()
    mock_raw.__getitem__ = lambda self, key: mock_df
    return mock_raw


def _make_mock_df():
    mock_df = MagicMock()
    mock_df.empty = False
    mock_df.dropna.return_value = mock_df
    mock_df.__len__ = lambda self: 300
    ts_min = MagicMock()
    ts_min.strftime = lambda fmt: "2021-01-01"
    ts_max = MagicMock()
    ts_max.strftime = lambda fmt: "2026-01-01"
    mock_df.index.min.return_value = ts_min
    mock_df.index.max.return_value = ts_max
    mock_df.__getitem__ = lambda self, key: mock_df
    return mock_df


def test_fetch_historical_universe_calls_get_sp100_at():
    """fetch_historical_universe must call pit.get_sp100_at (not get_sp100_universe)."""
    fake_tickers = ["AAPL", "MSFT"]
    mock_df = _make_mock_df()
    mock_raw = _make_mock_raw(mock_df)

    import src.training.historical_data as hd_mod

    with patch.object(hd_mod, "get_sp100_at") as mock_pit, \
         patch("src.training.historical_data.os.path.exists", return_value=False), \
         patch("src.training.historical_data.os.makedirs"), \
         patch("src.training.historical_data.open", MagicMock(), create=True), \
         patch("yfinance.download", return_value=mock_raw):

        mock_pit.return_value = fake_tickers

        hd_mod.fetch_historical_universe(lookback_years=5)

        assert mock_pit.called, "pit.get_sp100_at was not called"
        iso_arg = mock_pit.call_args[0][0]
        assert isinstance(iso_arg, str), (
            f"get_sp100_at must be called with an ISO string, got {type(iso_arg)}"
        )
        date.fromisoformat(iso_arg)


def test_start_date_computed_before_universe_call():
    """get_sp100_at ISO arg must be approximately start_date (5 years ago)."""
    fake_tickers = ["AAPL", "MSFT"]
    mock_df = _make_mock_df()
    mock_raw = _make_mock_raw(mock_df)

    import src.training.historical_data as hd_mod

    with patch.object(hd_mod, "get_sp100_at") as mock_pit, \
         patch("src.training.historical_data.os.path.exists", return_value=False), \
         patch("src.training.historical_data.os.makedirs"), \
         patch("src.training.historical_data.open", MagicMock(), create=True), \
         patch("yfinance.download", return_value=mock_raw):

        mock_pit.return_value = fake_tickers

        lookback_years = 5
        hd_mod.fetch_historical_universe(lookback_years=lookback_years)

        iso_arg = mock_pit.call_args[0][0]
        as_of = date.fromisoformat(iso_arg)
        expected = (datetime.now() - timedelta(days=lookback_years * 365)).date()
        delta_days = abs((as_of - expected).days)
        assert delta_days <= 10, (
            f"get_sp100_at called with {iso_arg}, expected ~{expected.isoformat()}; "
            f"delta={delta_days} days — start_date not computed before universe call"
        )
