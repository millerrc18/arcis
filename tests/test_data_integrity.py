"""Tests for src/data_integrity.py."""

import math

import pytest

from src.data_integrity import validate_features, validate_trade_entry, validate_universe


# ---------------------------------------------------------------------------
# validate_features
# ---------------------------------------------------------------------------

class TestValidateFeatures:
    def test_valid_features_pass(self):
        features = {"current_price": 150.0, "atr_14": 3.5, "volume_ratio_20d": 1.2}
        assert validate_features("AAPL", features) is True

    def test_nan_value_rejected(self):
        features = {"current_price": 150.0, "atr_14": float("nan")}
        assert validate_features("AAPL", features) is False

    def test_inf_value_rejected(self):
        features = {"current_price": 150.0, "atr_14": float("inf")}
        assert validate_features("AAPL", features) is False

    def test_negative_inf_rejected(self):
        features = {"current_price": 150.0, "atr_14": float("-inf")}
        assert validate_features("AAPL", features) is False

    def test_zero_price_rejected(self):
        features = {"current_price": 0}
        assert validate_features("AAPL", features) is False

    def test_negative_price_rejected(self):
        features = {"current_price": -10.0}
        assert validate_features("AAPL", features) is False

    def test_missing_price_rejected(self):
        features = {"atr_14": 3.5}  # no current_price -> defaults to 0
        assert validate_features("AAPL", features) is False

    def test_string_price_rejected(self):
        features = {"current_price": "not_a_number"}
        assert validate_features("AAPL", features) is False

    def test_integer_price_accepted(self):
        features = {"current_price": 100}
        assert validate_features("AAPL", features) is True

    def test_nan_in_current_price_rejected(self):
        features = {"current_price": float("nan")}
        assert validate_features("AAPL", features) is False

    def test_empty_features_rejected(self):
        # No current_price key, defaults to 0
        assert validate_features("AAPL", {}) is False

    def test_non_float_values_pass(self):
        # String and None values are not float, so NaN/Inf check skips them
        features = {"current_price": 50.0, "trend_state": "bullish", "extra": None}
        assert validate_features("AAPL", features) is True


# ---------------------------------------------------------------------------
# validate_trade_entry
# ---------------------------------------------------------------------------

class TestValidateTradeEntry:
    def test_valid_trade_passes(self):
        assert validate_trade_entry("AAPL", 150.0, 145.0, [155.0, 160.0]) is True

    def test_zero_entry_rejected(self):
        assert validate_trade_entry("AAPL", 0, 145.0, [155.0]) is False

    def test_negative_entry_rejected(self):
        assert validate_trade_entry("AAPL", -10.0, 145.0, [155.0]) is False

    def test_zero_stop_rejected(self):
        assert validate_trade_entry("AAPL", 150.0, 0, [155.0]) is False

    def test_negative_stop_rejected(self):
        assert validate_trade_entry("AAPL", 150.0, -5.0, [155.0]) is False

    def test_no_targets_rejected(self):
        assert validate_trade_entry("AAPL", 150.0, 145.0, None) is False

    def test_empty_targets_rejected(self):
        assert validate_trade_entry("AAPL", 150.0, 145.0, []) is False

    def test_stop_above_entry_rejected(self):
        assert validate_trade_entry("AAPL", 150.0, 155.0, [160.0]) is False

    def test_stop_equal_entry_rejected(self):
        assert validate_trade_entry("AAPL", 150.0, 150.0, [160.0]) is False

    def test_single_target_valid(self):
        assert validate_trade_entry("AAPL", 100.0, 95.0, [110.0]) is True

    def test_none_entry_rejected(self):
        assert validate_trade_entry("AAPL", None, 95.0, [110.0]) is False

    def test_none_stop_rejected(self):
        assert validate_trade_entry("AAPL", 100.0, None, [110.0]) is False


# ---------------------------------------------------------------------------
# validate_universe
# ---------------------------------------------------------------------------

class TestValidateUniverse:
    def test_valid_tickers(self):
        result = validate_universe(["AAPL", "MSFT", "GOOG"])
        assert result == ["AAPL", "MSFT", "GOOG"]

    def test_empty_list_returns_empty(self):
        assert validate_universe([]) == []

    def test_numeric_ticker_rejected(self):
        result = validate_universe(["AAPL", "123", "MSFT"])
        assert result == ["AAPL", "MSFT"]

    def test_too_long_ticker_rejected(self):
        result = validate_universe(["AAPL", "TOOLONG", "FB"])
        # "TOOLONG" is 7 chars, limit is 6
        assert "TOOLONG" not in result
        assert "AAPL" in result
        assert "FB" in result

    def test_empty_string_rejected(self):
        result = validate_universe(["", "AAPL"])
        assert result == ["AAPL"]

    def test_non_string_rejected(self):
        result = validate_universe([123, None, "MSFT"])
        assert result == ["MSFT"]

    def test_ticker_with_numbers_rejected(self):
        # isalpha() rejects digits
        result = validate_universe(["BRK1", "AAPL"])
        assert result == ["AAPL"]

    def test_special_chars_rejected(self):
        result = validate_universe(["AA-PL", "MS.FT", "GOOG"])
        assert result == ["GOOG"]

    def test_single_char_ticker_valid(self):
        result = validate_universe(["A", "F"])
        assert result == ["A", "F"]

    def test_six_char_ticker_valid(self):
        result = validate_universe(["ABCDEF"])
        assert result == ["ABCDEF"]

    def test_all_invalid_returns_empty(self):
        result = validate_universe(["", "123", None])
        assert result == []
