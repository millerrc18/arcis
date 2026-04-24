"""Tests for MarketPulse correlation analytics module."""

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
from lib.analytics.correlation import (  # noqa: E402
    pairwise_correlation,
    sector_correlation,
    rolling_correlation,
)


# ---------------------------------------------------------------------------
# pairwise_correlation
# ---------------------------------------------------------------------------


class TestPairwiseCorrelation:
    """Tests for the ``pairwise_correlation`` function."""

    def test_pairwise_self_correlation(self):
        """Diagonal of correlation matrix should be 1.0 (within tolerance)."""
        df = make_bars_df(tickers=["AAPL", "MSFT", "GOOG"], days=30, bars_per_day=20, seed=42)
        result = pairwise_correlation(df)

        for i in range(len(result.tickers)):
            assert result.matrix[i][i] == pytest.approx(1.0, abs=1e-10)

    def test_pairwise_symmetry(self):
        """corr(A,B) == corr(B,A) -- matrix must be symmetric."""
        df = make_bars_df(tickers=["AAPL", "MSFT", "GOOG"], days=30, bars_per_day=20, seed=42)
        result = pairwise_correlation(df)

        n = len(result.tickers)
        for i in range(n):
            for j in range(n):
                assert result.matrix[i][j] == pytest.approx(
                    result.matrix[j][i], abs=1e-10
                ), f"matrix[{i}][{j}] != matrix[{j}][{i}]"

    def test_pairwise_range(self):
        """All correlations must be in [-1, 1]."""
        df = make_bars_df(tickers=["AAPL", "MSFT", "GOOG"], days=30, bars_per_day=20, seed=42)
        result = pairwise_correlation(df)

        for pair in result.pairs:
            assert -1.0 <= pair.correlation <= 1.0, (
                f"Correlation between {pair.ticker_a} and {pair.ticker_b} "
                f"out of range: {pair.correlation}"
            )

        # Also check matrix values
        for row in result.matrix:
            for val in row:
                assert -1.0 <= val <= 1.0

    def test_pairwise_tickers_filter(self):
        """Passing tickers= filters to only those tickers."""
        df = make_bars_df(tickers=["AAPL", "MSFT", "GOOG"], days=30, bars_per_day=20, seed=42)
        result = pairwise_correlation(df, tickers=["AAPL", "MSFT"])

        assert set(result.tickers) == {"AAPL", "MSFT"}
        assert len(result.matrix) == 2
        assert len(result.matrix[0]) == 2
        # Should have exactly 1 pair (AAPL-MSFT)
        assert len(result.pairs) == 1


# ---------------------------------------------------------------------------
# sector_correlation
# ---------------------------------------------------------------------------


class TestSectorCorrelation:
    """Tests for the ``sector_correlation`` function."""

    def test_sector_correlation_basic(self):
        """Two sectors should produce valid correlation result."""
        df = make_bars_df(tickers=["AAPL", "MSFT", "GOOG"], days=30, bars_per_day=20, seed=42)
        sector_map = {"AAPL": "Tech", "MSFT": "Tech", "GOOG": "Comm"}

        result = sector_correlation(df, sector_map)

        assert set(result.sectors) == {"Comm", "Tech"}
        assert len(result.pairs) == 1  # one pair: Comm-Tech
        assert -1.0 <= result.pairs[0].correlation <= 1.0

    def test_sector_correlation_matrix_size(self):
        """Matrix should be 2x2 for 2 sectors."""
        df = make_bars_df(tickers=["AAPL", "MSFT", "GOOG"], days=30, bars_per_day=20, seed=42)
        sector_map = {"AAPL": "Tech", "MSFT": "Tech", "GOOG": "Comm"}

        result = sector_correlation(df, sector_map)

        assert len(result.matrix) == 2
        assert len(result.matrix[0]) == 2
        assert len(result.matrix[1]) == 2

        # Diagonal should be 1.0
        for i in range(2):
            assert result.matrix[i][i] == pytest.approx(1.0, abs=1e-10)


# ---------------------------------------------------------------------------
# rolling_correlation
# ---------------------------------------------------------------------------


class TestRollingCorrelation:
    """Tests for the ``rolling_correlation`` function."""

    def test_rolling_correlation_length(self):
        """Points count should be approximately n_days - window."""
        days = 30
        window = 21
        df = make_bars_df(tickers=["AAPL", "MSFT"], days=days, bars_per_day=20, seed=42)
        result = rolling_correlation(df, "AAPL", "MSFT", window=window)

        assert result.ticker_a == "AAPL"
        assert result.ticker_b == "MSFT"
        assert result.window == window

        # After pct_change we lose 1 day, then rolling(window) needs
        # window-1 more days.  So expected ~ days - 1 - (window - 1) = days - window
        expected_approx = days - window
        assert len(result.points) == pytest.approx(expected_approx, abs=2)

    def test_rolling_correlation_range(self):
        """All rolling correlation values must be in [-1, 1]."""
        df = make_bars_df(tickers=["AAPL", "MSFT"], days=30, bars_per_day=20, seed=42)
        result = rolling_correlation(df, "AAPL", "MSFT", window=10)

        assert len(result.points) > 0
        for pt in result.points:
            assert -1.0 <= pt.correlation <= 1.0, (
                f"Rolling correlation out of range at {pt.timestamp}: {pt.correlation}"
            )


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------


class TestSerialization:
    """Verify to_dict() works on correlation result types."""

    def test_to_dict_matrix(self):
        """Matrix serializes correctly via to_dict()."""
        df = make_bars_df(tickers=["AAPL", "MSFT", "GOOG"], days=30, bars_per_day=20, seed=42)
        result = pairwise_correlation(df)
        d = result.to_dict()

        assert isinstance(d, dict)
        assert "matrix" in d
        assert "pairs" in d
        assert "tickers" in d

        # Matrix should be list of lists of floats
        assert isinstance(d["matrix"], list)
        assert len(d["matrix"]) == 3
        for row in d["matrix"]:
            assert isinstance(row, list)
            assert len(row) == 3
            for val in row:
                assert isinstance(val, float)

        # Pairs should serialize
        assert isinstance(d["pairs"], list)
        assert len(d["pairs"]) == 3  # 3 choose 2
        for pair in d["pairs"]:
            assert "ticker_a" in pair
            assert "ticker_b" in pair
            assert "correlation" in pair
