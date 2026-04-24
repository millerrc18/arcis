"""Tests for MarketPulse sector analytics module."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Ensure lib is importable
# ---------------------------------------------------------------------------
_MP_ROOT = Path(__file__).resolve().parent.parent
if str(_MP_ROOT) not in sys.path:
    sys.path.insert(0, str(_MP_ROOT))

from tests.fixtures.make_bars import make_bars_df  # noqa: E402
from lib.analytics.sectors import (  # noqa: E402
    sector_rotation,
    sector_heatmap,
    relative_strength,
)

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

TICKERS = ["AAPL", "MSFT", "GOOG", "AMZN"]
SECTOR_MAP = {
    "AAPL": "Technology",
    "MSFT": "Technology",
    "GOOG": "Communication Services",
    "AMZN": "Consumer Discretionary",
}
DAYS = 10


@pytest.fixture
def bars_df():
    """Synthetic 10-day bar DataFrame for 4 tickers."""
    return make_bars_df(tickers=TICKERS, days=DAYS, bars_per_day=20, seed=42)


# ---------------------------------------------------------------------------
# sector_rotation
# ---------------------------------------------------------------------------


class TestSectorRotation:
    """Tests for the ``sector_rotation`` function."""

    def test_sector_rotation_ranking(self, bars_df):
        """Sectors must be sorted by avg_return descending."""
        result = sector_rotation(bars_df, SECTOR_MAP)

        returns = [s.avg_return for s in result.sectors]
        assert returns == sorted(returns, reverse=True), (
            f"Sectors not sorted descending by avg_return: {returns}"
        )

    def test_sector_rotation_ticker_count(self, bars_df):
        """Technology should have 2 tickers, others 1 each."""
        result = sector_rotation(bars_df, SECTOR_MAP)

        counts = {s.sector: s.ticker_count for s in result.sectors}
        assert counts["Technology"] == 2
        assert counts["Communication Services"] == 1
        assert counts["Consumer Discretionary"] == 1

    def test_sector_rotation_period_string(self, bars_df):
        """Period string should contain ' to ' with date-like substrings."""
        result = sector_rotation(bars_df, SECTOR_MAP)

        assert " to " in result.period
        parts = result.period.split(" to ")
        assert len(parts) == 2
        # Both parts should look like YYYY-MM-DD
        for part in parts:
            assert len(part) == 10
            assert part[4] == "-"
            assert part[7] == "-"


# ---------------------------------------------------------------------------
# sector_heatmap
# ---------------------------------------------------------------------------


class TestSectorHeatmap:
    """Tests for the ``sector_heatmap`` function."""

    def test_sector_heatmap_grid(self, bars_df):
        """Cell count should equal num_sectors * num_dates."""
        result = sector_heatmap(bars_df, SECTOR_MAP)

        expected_cells = len(result.sectors) * len(result.dates)
        assert len(result.cells) == expected_cells

    def test_sector_heatmap_dates(self, bars_df):
        """All trading dates should be present."""
        result = sector_heatmap(bars_df, SECTOR_MAP)

        # We requested 10 trading days
        assert len(result.dates) == DAYS

    def test_sector_heatmap_sectors(self, bars_df):
        """All 3 unique sectors should appear."""
        result = sector_heatmap(bars_df, SECTOR_MAP)

        assert set(result.sectors) == {
            "Technology",
            "Communication Services",
            "Consumer Discretionary",
        }


# ---------------------------------------------------------------------------
# relative_strength
# ---------------------------------------------------------------------------


class TestRelativeStrength:
    """Tests for the ``relative_strength`` function."""

    def test_relative_strength_ratio(self, bars_df):
        """RS ratios should exist and span above/below 1.0 (approximately)."""
        result = relative_strength(bars_df, SECTOR_MAP)

        ratios = [t.rs_ratio for t in result.tickers]
        assert len(ratios) == 4

        # At least one ticker should outperform (>1) and one underperform (<1)
        assert any(r > 1.0 for r in ratios), f"No ratio > 1.0: {ratios}"
        assert any(r < 1.0 for r in ratios), f"No ratio < 1.0: {ratios}"

    def test_relative_strength_default_benchmark(self, bars_df):
        """Without benchmark_tickers, benchmark should be 'equal-weight'."""
        result = relative_strength(bars_df, SECTOR_MAP)

        assert result.benchmark == "equal-weight"

    def test_relative_strength_custom_benchmark(self, bars_df):
        """Passing benchmark_tickers should set the benchmark label."""
        result = relative_strength(bars_df, SECTOR_MAP, benchmark_tickers=["AAPL"])

        assert result.benchmark == "AAPL"
        # Benchmark return should match AAPL's own return
        aapl_entry = next(t for t in result.tickers if t.ticker == "AAPL")
        assert aapl_entry.rs_ratio == pytest.approx(1.0, abs=1e-10), (
            "AAPL's RS ratio against itself should be ~1.0"
        )


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Edge-case tests for sector analytics."""

    def test_unmapped_tickers_excluded(self, bars_df):
        """Tickers not in sector_map should be excluded from results."""
        # Add a ticker not in sector_map
        import pandas as pd
        extra = make_bars_df(tickers=["XYZ"], days=DAYS, bars_per_day=20, seed=99)
        combined = pd.concat([bars_df, extra], ignore_index=True)

        # sector_rotation
        rot = sector_rotation(combined, SECTOR_MAP)
        all_tickers_in_rot = set()
        for s in rot.sectors:
            assert s.sector in SECTOR_MAP.values()
        total_ticker_count = sum(s.ticker_count for s in rot.sectors)
        assert total_ticker_count == 4, (
            f"Expected 4 mapped tickers, got {total_ticker_count}"
        )

        # sector_heatmap -- only mapped sectors appear
        hm = sector_heatmap(combined, SECTOR_MAP)
        for cell in hm.cells:
            assert cell.sector in SECTOR_MAP.values()

        # relative_strength -- only mapped tickers
        rs = relative_strength(combined, SECTOR_MAP)
        rs_tickers = {t.ticker for t in rs.tickers}
        assert "XYZ" not in rs_tickers
        assert rs_tickers == set(TICKERS)


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------


class TestSerialization:
    """Verify to_dict() works on sector result types."""

    def test_rotation_to_dict(self, bars_df):
        result = sector_rotation(bars_df, SECTOR_MAP)
        d = result.to_dict()

        assert isinstance(d, dict)
        assert "sectors" in d
        assert "period" in d
        assert isinstance(d["sectors"], list)
        assert len(d["sectors"]) == 3
        for sector in d["sectors"]:
            assert "sector" in sector
            assert "avg_return" in sector
            assert "total_volume" in sector
            assert "ticker_count" in sector

    def test_heatmap_to_dict(self, bars_df):
        result = sector_heatmap(bars_df, SECTOR_MAP)
        d = result.to_dict()

        assert isinstance(d, dict)
        assert "cells" in d
        assert "sectors" in d
        assert "dates" in d

    def test_relative_strength_to_dict(self, bars_df):
        result = relative_strength(bars_df, SECTOR_MAP)
        d = result.to_dict()

        assert isinstance(d, dict)
        assert "tickers" in d
        assert "benchmark" in d
        for t in d["tickers"]:
            assert "ticker" in t
            assert "rs_ratio" in t
            assert "ticker_return" in t
            assert "benchmark_return" in t
