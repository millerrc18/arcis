"""Tests for LLM output validation — 6 hard bounds on trade parameters."""

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from src.llm.validator import validate_llm_output


def _make_packet(entry=100.0, stop=95.0, target=110.0, ticker="AAPL",
                 shares=10, allocation=3000.0, conviction=7):
    """Create a mock packet object matching the attribute names in validator.py."""
    ps = SimpleNamespace(
        entry_price=entry,
        stop_level=stop,
        target_1=target,
        shares=shares,
        allocation_dollars=allocation,
    )
    return SimpleNamespace(
        ticker=ticker,
        entry_price=entry,
        stop_invalidation=stop,
        stop_price=stop,
        position_sizing=ps,
        llm_conviction=conviction,
    )


def _make_features(current_price=100.0):
    return {"current_price": current_price}


def _make_config(starting_capital=100000):
    return {"risk": {"starting_capital": starting_capital}}


class TestValidPacket:
    """A well-formed packet should pass all 6 checks."""

    def test_valid_packet_passes(self):
        packet = _make_packet()
        is_valid, reason = validate_llm_output(packet, _make_features(), _make_config())
        assert is_valid is True
        assert reason == "passed"

    def test_valid_packet_close_to_current(self):
        """Entry within 10% of current price should pass."""
        packet = _make_packet(entry=108.0)
        is_valid, _ = validate_llm_output(packet, _make_features(100.0), _make_config())
        assert is_valid is True


class TestTickerValidation:
    """Check 1: Ticker must be in universe (soft — silent pass if universe unavailable)."""

    @patch("src.universe.sp100.get_sp100_universe", return_value=["AAPL", "MSFT", "GOOGL"])
    def test_valid_ticker_passes(self, mock_universe):
        packet = _make_packet(ticker="AAPL")
        is_valid, _ = validate_llm_output(packet, _make_features(), _make_config())
        assert is_valid is True

    @patch("src.universe.sp100.get_sp100_universe", return_value=["AAPL", "MSFT", "GOOGL"])
    def test_hallucinated_ticker_rejected(self, mock_universe):
        packet = _make_packet(ticker="FAKE")
        is_valid, reason = validate_llm_output(packet, _make_features(), _make_config())
        assert is_valid is False
        assert "ticker" in reason.lower() or "universe" in reason.lower()

    @patch("src.universe.sp100.get_sp100_universe", side_effect=Exception("unavailable"))
    def test_universe_unavailable_passes_silently(self, mock_universe):
        """If universe check fails, should pass silently."""
        packet = _make_packet(ticker="ANYTHING")
        is_valid, _ = validate_llm_output(packet, _make_features(), _make_config())
        assert is_valid is True


class TestEntryPriceDeviation:
    """Check 2: |entry - current| / current <= 10%."""

    def test_entry_too_far_from_current(self):
        """Entry 20% above current should fail."""
        packet = _make_packet(entry=120.0)
        is_valid, reason = validate_llm_output(packet, _make_features(100.0), _make_config())
        assert is_valid is False
        assert "entry" in reason.lower() or "price" in reason.lower() or "deviat" in reason.lower()

    def test_entry_within_tolerance(self):
        """Entry 5% above current should pass."""
        packet = _make_packet(entry=105.0)
        is_valid, _ = validate_llm_output(packet, _make_features(100.0), _make_config())
        assert is_valid is True

    def test_zero_current_price_skips_check(self):
        """If current_price is 0, check should be skipped."""
        packet = _make_packet(entry=100.0)
        is_valid, _ = validate_llm_output(packet, _make_features(0.0), _make_config())
        assert is_valid is True


class TestStopBelowEntry:
    """Check 3: Stop must be below entry (for longs)."""

    def test_stop_above_entry_rejected(self):
        """Stop at 105 with entry at 100 should fail."""
        packet = _make_packet(entry=100.0, stop=105.0)
        is_valid, reason = validate_llm_output(packet, _make_features(), _make_config())
        assert is_valid is False
        assert "stop" in reason.lower()


class TestStopDistanceBounds:
    """Check 4: 0.5% <= (entry - stop) / entry <= 15%."""

    def test_stop_too_tight(self):
        """Stop 0.1% below entry should fail."""
        packet = _make_packet(entry=100.0, stop=99.9)
        is_valid, reason = validate_llm_output(packet, _make_features(), _make_config())
        assert is_valid is False
        assert "stop" in reason.lower() or "distance" in reason.lower()

    def test_stop_too_wide(self):
        """Stop 20% below entry should fail."""
        packet = _make_packet(entry=100.0, stop=80.0)
        is_valid, reason = validate_llm_output(packet, _make_features(), _make_config())
        assert is_valid is False

    def test_stop_within_bounds(self):
        """Stop 5% below entry should pass."""
        packet = _make_packet(entry=100.0, stop=95.0)
        is_valid, _ = validate_llm_output(packet, _make_features(), _make_config())
        assert is_valid is True


class TestPositionSizeCap:
    """Check 5: allocation_dollars / starting_capital <= 5%."""

    def test_oversized_position_rejected(self):
        """$10K position on $100K account (10%) should fail."""
        packet = _make_packet(allocation=10000.0)
        is_valid, reason = validate_llm_output(packet, _make_features(), _make_config(100000))
        assert is_valid is False
        assert "position" in reason.lower() or "size" in reason.lower() or "alloc" in reason.lower()

    def test_normal_position_passes(self):
        """$3K position on $100K account (3%) should pass."""
        packet = _make_packet(allocation=3000.0)
        is_valid, _ = validate_llm_output(packet, _make_features(), _make_config(100000))
        assert is_valid is True


class TestConvictionRange:
    """Check 6: 1 <= conviction <= 10."""

    def test_conviction_zero_rejected(self):
        packet = _make_packet(conviction=0)
        is_valid, reason = validate_llm_output(packet, _make_features(), _make_config())
        assert is_valid is False
        assert "conviction" in reason.lower()

    def test_conviction_11_rejected(self):
        packet = _make_packet(conviction=11)
        is_valid, reason = validate_llm_output(packet, _make_features(), _make_config())
        assert is_valid is False

    def test_conviction_in_range(self):
        packet = _make_packet(conviction=5)
        is_valid, _ = validate_llm_output(packet, _make_features(), _make_config())
        assert is_valid is True
