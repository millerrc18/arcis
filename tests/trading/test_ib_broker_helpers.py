"""Smoke tests for ib_broker_helpers (PR #736 split surface).

When ib_broker.py was split per #736, the cancel-bracket-children helpers
extracted into ib_broker_helpers.py. The end-to-end behavior is covered
by test_ib_cancel_before_close.py; this file covers import-shape +
unit-level helper invariants.
"""

from __future__ import annotations

from unittest.mock import MagicMock


def test_ib_broker_helpers_module_imports():
    """Public surface of ib_broker_helpers must import cleanly."""
    from src.trading import ib_broker_helpers
    assert hasattr(ib_broker_helpers, "cancel_bracket_children_for_ticker")
    assert hasattr(ib_broker_helpers, "verify_bracket_integrity")
    assert hasattr(ib_broker_helpers, "handle_ib_error")


def test_verify_bracket_integrity_with_no_open_trades():
    """Empty IB trades list → empty issues list."""
    from src.trading.ib_broker_helpers import verify_bracket_integrity
    ib = MagicMock()
    ib.openTrades.return_value = []
    issues = verify_bracket_integrity(ib)
    assert issues == []


def test_find_active_sell_children_filters_by_ticker():
    """_find_active_sell_children returns trades only for the named ticker."""
    from src.trading.ib_broker_helpers import _find_active_sell_children

    aapl_trade = MagicMock()
    aapl_trade.contract.symbol = "AAPL"
    aapl_trade.order.action = "SELL"
    aapl_trade.orderStatus.status = "Submitted"

    msft_trade = MagicMock()
    msft_trade.contract.symbol = "MSFT"
    msft_trade.order.action = "SELL"
    msft_trade.orderStatus.status = "Submitted"

    ib = MagicMock()
    ib.openTrades.return_value = [aapl_trade, msft_trade]

    matched = _find_active_sell_children(ib, "AAPL")
    assert len(matched) == 1
    assert matched[0].contract.symbol == "AAPL"


def test_cancel_bracket_children_for_ticker_with_no_active_returns_empty():
    """No active SELL children → returns empty list, no cancel calls."""
    from src.trading.ib_broker_helpers import cancel_bracket_children_for_ticker
    ib = MagicMock()
    ib.openTrades.return_value = []
    result = cancel_bracket_children_for_ticker(ib, "AAPL", ack_timeout=1.0)
    assert result == []
    ib.cancelOrder.assert_not_called()
