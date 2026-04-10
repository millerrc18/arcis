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


def test_backfill_sets_protective_stop_and_targets():
    """Fix #354: backfilled orphans must have non-zero stop_price and target_1."""
    from src.shadow_trading.reconcile import _backfill_trade_data
    from datetime import datetime
    from zoneinfo import ZoneInfo
    now = datetime.now(ZoneInfo("America/New_York"))
    trade = _backfill_trade_data("AAPL", 150.0, 100, 15000.0, "paper", now)
    assert trade is not None
    assert trade["stop_price"] > 0
    assert trade["target_1"] > 0
    assert trade["target_2"] > 0
    assert trade["stop_price"] < trade["entry_price"]
    assert trade["target_1"] > trade["entry_price"]
    assert trade["target_2"] > trade["target_1"]


def test_backfill_handles_zero_entry_price():
    """Fix #354: backfill must not crash on zero entry price."""
    from src.shadow_trading.reconcile import _backfill_trade_data
    from datetime import datetime
    from zoneinfo import ZoneInfo
    now = datetime.now(ZoneInfo("America/New_York"))
    trade = _backfill_trade_data("BANKRUPT", 0.0, 100, 0.0, "paper", now)
    if trade is not None:
        assert isinstance(trade["stop_price"], (int, float))
        assert isinstance(trade["target_1"], (int, float))
