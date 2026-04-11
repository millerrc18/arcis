"""Tests for _coerce_to_schema write-boundary type coercion (#383)."""

import pytest

from src.journal.store import _coerce_to_schema


class TestCoerceToSchema:
    """Verify REAL/INTEGER columns are coerced from string to numeric."""

    def test_string_to_float_for_real_column(self):
        result = _coerce_to_schema("shadow_trades", {"pnl_dollars": "25.3"})
        assert result["pnl_dollars"] == 25.3
        assert isinstance(result["pnl_dollars"], float)

    def test_string_to_float_negative(self):
        result = _coerce_to_schema("shadow_trades", {"pnl_dollars": "-100.50"})
        assert result["pnl_dollars"] == -100.50

    def test_float_passthrough(self):
        result = _coerce_to_schema("shadow_trades", {"pnl_dollars": 42.0})
        assert result["pnl_dollars"] == 42.0
        assert isinstance(result["pnl_dollars"], float)

    def test_int_to_float_for_real_column(self):
        result = _coerce_to_schema("shadow_trades", {"entry_price": 150})
        assert result["entry_price"] == 150.0
        assert isinstance(result["entry_price"], float)

    def test_none_preserved(self):
        result = _coerce_to_schema("shadow_trades", {"pnl_dollars": None})
        assert result["pnl_dollars"] is None

    def test_text_column_not_coerced(self):
        result = _coerce_to_schema("shadow_trades", {"status": "open"})
        assert result["status"] == "open"
        assert isinstance(result["status"], str)

    def test_unknown_table_passthrough(self):
        data = {"foo": "bar", "num": "123"}
        result = _coerce_to_schema("nonexistent_table", data)
        assert result == data

    def test_unknown_column_passthrough(self):
        result = _coerce_to_schema("shadow_trades", {"unknown_col": "value"})
        assert result["unknown_col"] == "value"

    def test_invalid_value_not_coerced(self):
        result = _coerce_to_schema("shadow_trades", {"pnl_dollars": "not_a_number"})
        assert result["pnl_dollars"] == "not_a_number"

    def test_multiple_real_columns(self):
        data = {
            "entry_price": "150.25",
            "stop_price": "145.00",
            "pnl_dollars": "500.75",
            "status": "open",
            "ticker": "AAPL",
        }
        result = _coerce_to_schema("shadow_trades", data)
        assert isinstance(result["entry_price"], float)
        assert isinstance(result["stop_price"], float)
        assert isinstance(result["pnl_dollars"], float)
        assert isinstance(result["status"], str)
        assert isinstance(result["ticker"], str)

    def test_integer_column_coercion(self):
        result = _coerce_to_schema("shadow_trades", {"planned_shares": "100"})
        assert result["planned_shares"] == 100
        assert isinstance(result["planned_shares"], int)

    def test_integer_from_float_string(self):
        result = _coerce_to_schema("shadow_trades", {"planned_shares": "100.0"})
        assert result["planned_shares"] == 100
        assert isinstance(result["planned_shares"], int)

    def test_recommendations_table(self):
        result = _coerce_to_schema("recommendations", {
            "price_at_recommendation": "259.50",
            "ticker": "MSFT",
        })
        assert isinstance(result["price_at_recommendation"], float)
        assert result["price_at_recommendation"] == 259.50
        assert result["ticker"] == "MSFT"
