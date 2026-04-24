"""Tests for marketpulse lib.indices -- IndexManager, Index, IndexInfo.

Covers:
- Loading built-in index JSON files (DOW30, SP100, SP500, NDX100, RUT2000)
- get_tickers() returns the correct ticker list
- list_indices() returns IndexInfo for all built-in indices
- create_custom_list() writes JSON and returns an Index
- is_index() returns True/False correctly
- get_index() raises IndexNotFoundError for unknown names
- get_index() finds custom lists after creation
- list_indices() includes both built-in and custom lists
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Make ``lib`` importable regardless of packaging setup.
# ---------------------------------------------------------------------------
_MP_ROOT = Path(__file__).resolve().parent.parent  # skills/marketpulse
if str(_MP_ROOT) not in sys.path:
    sys.path.insert(0, str(_MP_ROOT))

from lib.db import MarketPulseConfig, reset_config  # noqa: E402
from lib.indices import Index, IndexInfo, IndexManager, IndexNotFoundError  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _fresh_config(tmp_path: Path):
    """Reset the global config singleton before each test."""
    reset_config()
    os.environ["MARKETPULSE_DATA_DIR"] = str(tmp_path)
    os.environ.setdefault("POLYGON_API_KEY", "test-key-fixture")
    yield
    reset_config()
    os.environ.pop("MARKETPULSE_DATA_DIR", None)


@pytest.fixture
def test_config(tmp_path: Path) -> MarketPulseConfig:
    """Return a MarketPulseConfig pointed at the temp data directory."""
    cfg = MarketPulseConfig(
        data_dir=tmp_path,
        polygon_api_key="test-key-fixture",
    )
    cfg.ensure_dirs()
    return cfg


@pytest.fixture
def mgr(test_config: MarketPulseConfig) -> IndexManager:
    """Return an IndexManager backed by the temp config."""
    return IndexManager(config=test_config)


# ---------------------------------------------------------------------------
# get_index -- built-in indices
# ---------------------------------------------------------------------------

class TestGetIndex:
    """Tests for loading built-in index JSON files."""

    def test_load_dow30(self, mgr: IndexManager):
        idx = mgr.get_index("DOW30")
        assert isinstance(idx, Index)
        assert idx.short_name == "DOW30"
        assert idx.name == "Dow Jones Industrial Average"
        assert idx.source == "Wikipedia"
        assert len(idx.constituents) == 30

    def test_load_sp100(self, mgr: IndexManager):
        idx = mgr.get_index("SP100")
        assert idx.short_name == "SP100"
        assert len(idx.constituents) >= 100

    def test_load_sp500(self, mgr: IndexManager):
        idx = mgr.get_index("SP500")
        assert idx.short_name == "SP500"
        assert len(idx.constituents) >= 500

    def test_load_ndx100(self, mgr: IndexManager):
        idx = mgr.get_index("NDX100")
        assert idx.short_name == "NDX100"
        assert len(idx.constituents) >= 100

    def test_load_rut2000(self, mgr: IndexManager):
        """RUT2000 seed is a placeholder with 0 constituents (not freely available)."""
        idx = mgr.get_index("RUT2000")
        assert idx.short_name == "RUT2000"
        assert idx.source == "placeholder"
        assert isinstance(idx.constituents, list)

    def test_case_insensitive_lookup(self, mgr: IndexManager):
        """Index lookup should be case-insensitive."""
        idx_lower = mgr.get_index("dow30")
        idx_upper = mgr.get_index("DOW30")
        assert idx_lower.short_name == idx_upper.short_name
        assert len(idx_lower.constituents) == len(idx_upper.constituents)

    def test_index_has_correct_fields(self, mgr: IndexManager):
        idx = mgr.get_index("DOW30")
        assert idx.description != ""
        assert idx.last_updated != ""
        # Each constituent has required keys
        for c in idx.constituents:
            assert "ticker" in c
            assert "name" in c
            assert "sector" in c

    def test_raises_for_unknown_index(self, mgr: IndexManager):
        with pytest.raises(IndexNotFoundError, match="not found"):
            mgr.get_index("NONEXISTENT_INDEX")


# ---------------------------------------------------------------------------
# get_tickers
# ---------------------------------------------------------------------------

class TestGetTickers:
    """Tests for the get_tickers() shortcut."""

    def test_returns_ticker_list(self, mgr: IndexManager):
        tickers = mgr.get_tickers("DOW30")
        assert isinstance(tickers, list)
        assert len(tickers) == 30
        # All strings
        assert all(isinstance(t, str) for t in tickers)

    def test_known_tickers_present(self, mgr: IndexManager):
        tickers = mgr.get_tickers("DOW30")
        assert "AAPL" in tickers
        assert "MSFT" in tickers

    def test_tickers_match_constituents(self, mgr: IndexManager):
        idx = mgr.get_index("SP100")
        assert idx.tickers == mgr.get_tickers("SP100")


# ---------------------------------------------------------------------------
# list_indices
# ---------------------------------------------------------------------------

class TestListIndices:
    """Tests for listing all available indices."""

    def test_returns_index_info_objects(self, mgr: IndexManager):
        infos = mgr.list_indices()
        assert len(infos) >= 5  # dow30, nasdaq100, russell2000, sp100, sp500
        assert all(isinstance(i, IndexInfo) for i in infos)

    def test_all_seed_indices_present(self, mgr: IndexManager):
        infos = mgr.list_indices()
        names = {i.short_name for i in infos}
        assert "DOW30" in names
        assert "SP100" in names
        assert "SP500" in names
        assert "NDX100" in names
        assert "RUT2000" in names

    def test_index_info_has_ticker_count(self, mgr: IndexManager):
        infos = mgr.list_indices()
        dow = next(i for i in infos if i.short_name == "DOW30")
        assert dow.ticker_count == 30

    def test_index_info_fields(self, mgr: IndexManager):
        infos = mgr.list_indices()
        for info in infos:
            assert info.short_name != ""
            assert info.name != ""
            # RUT2000 is a placeholder with 0 constituents
            if info.short_name != "RUT2000":
                assert info.ticker_count > 0


# ---------------------------------------------------------------------------
# create_custom_list
# ---------------------------------------------------------------------------

class TestCreateCustomList:
    """Tests for creating custom ticker lists."""

    def test_creates_and_returns_index(self, mgr: IndexManager, test_config: MarketPulseConfig):
        idx = mgr.create_custom_list("my-watchlist", ["AAPL", "GOOG", "TSLA"])
        assert isinstance(idx, Index)
        assert idx.short_name == "my-watchlist"
        assert idx.source == "custom"
        assert len(idx.constituents) == 3

    def test_tickers_uppercased(self, mgr: IndexManager):
        idx = mgr.create_custom_list("lowercased", ["aapl", "msft"])
        assert idx.tickers == ["AAPL", "MSFT"]

    def test_json_file_created(self, mgr: IndexManager, test_config: MarketPulseConfig):
        mgr.create_custom_list("persisted", ["NVDA"])
        custom_dir = test_config.data_dir / "custom_lists"
        files = list(custom_dir.glob("*.json"))
        assert len(files) == 1
        assert "persisted" in files[0].name

    def test_custom_list_retrievable(self, mgr: IndexManager):
        mgr.create_custom_list("roundtrip", ["AMD", "INTC"])
        idx = mgr.get_index("roundtrip")
        assert idx.tickers == ["AMD", "INTC"]

    def test_case_insensitive_custom_list_lookup(self, mgr: IndexManager):
        """Creating with 'MyList' and retrieving with 'mylist' should work."""
        mgr.create_custom_list("MyList", ["AAPL", "GOOG"])
        idx = mgr.get_index("mylist")
        assert idx.tickers == ["AAPL", "GOOG"]

    def test_empty_name_raises(self, mgr: IndexManager):
        """An empty or whitespace-only name should raise ValueError."""
        with pytest.raises(ValueError, match="cannot be empty"):
            mgr.create_custom_list("", ["AAPL"])
        with pytest.raises(ValueError, match="cannot be empty"):
            mgr.create_custom_list("   ", ["AAPL"])


# ---------------------------------------------------------------------------
# is_index
# ---------------------------------------------------------------------------

class TestIsIndex:
    """Tests for the is_index() check."""

    def test_known_builtin_returns_true(self, mgr: IndexManager):
        assert mgr.is_index("DOW30") is True
        assert mgr.is_index("SP500") is True
        assert mgr.is_index("NDX100") is True

    def test_case_insensitive(self, mgr: IndexManager):
        assert mgr.is_index("dow30") is True
        assert mgr.is_index("sp100") is True

    def test_unknown_returns_false(self, mgr: IndexManager):
        assert mgr.is_index("FAKE_INDEX") is False
        assert mgr.is_index("nonexistent") is False

    def test_custom_list_returns_true(self, mgr: IndexManager):
        mgr.create_custom_list("my-list", ["AAPL"])
        assert mgr.is_index("my-list") is True


# ---------------------------------------------------------------------------
# Integration: custom lists + list_indices
# ---------------------------------------------------------------------------

class TestCustomListIntegration:
    """Custom lists should integrate with list_indices and get_index."""

    def test_list_indices_includes_custom(self, mgr: IndexManager):
        mgr.create_custom_list("favorites", ["AAPL", "MSFT"])
        infos = mgr.list_indices()
        names = {i.short_name for i in infos}
        assert "favorites" in names
        # Still has built-ins
        assert "DOW30" in names

    def test_custom_source_marked(self, mgr: IndexManager):
        mgr.create_custom_list("sector-bets", ["XLF", "XLK"])
        infos = mgr.list_indices()
        custom_info = next(i for i in infos if i.short_name == "sector-bets")
        assert custom_info.source == "custom"

    def test_get_index_finds_custom_after_creation(self, mgr: IndexManager):
        mgr.create_custom_list("late-add", ["RIVN", "LCID"])
        idx = mgr.get_index("late-add")
        assert idx.short_name == "late-add"
        assert idx.tickers == ["RIVN", "LCID"]

    def test_multiple_custom_lists(self, mgr: IndexManager):
        mgr.create_custom_list("list-a", ["AAPL"])
        mgr.create_custom_list("list-b", ["MSFT"])
        infos = mgr.list_indices()
        custom_names = {i.short_name for i in infos if i.source == "custom"}
        assert "list-a" in custom_names
        assert "list-b" in custom_names
