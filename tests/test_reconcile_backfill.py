"""Tests for reconcile backfill share validation."""

from datetime import datetime
from zoneinfo import ZoneInfo

from src.shadow_trading.reconcile import _backfill_trade_data

ET = ZoneInfo("America/New_York")


class TestBackfillSharesValidation:
    def test_positive_shares_returns_trade(self):
        now = datetime.now(ET)
        result = _backfill_trade_data("AAPL", 150.0, 10, 1500.0, "paper", now)
        assert result is not None
        assert result["planned_shares"] == 10
        assert result["ticker"] == "AAPL"

    def test_negative_shares_returns_none(self):
        now = datetime.now(ET)
        result = _backfill_trade_data("PFE", 25.0, -14, -350.0, "live", now)
        assert result is None

    def test_zero_shares_returns_none(self):
        now = datetime.now(ET)
        result = _backfill_trade_data("MSFT", 400.0, 0, 0.0, "paper", now)
        assert result is None
