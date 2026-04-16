"""Tests for broker abstraction layer — interface, factory, adapters.

All tests use mocks — no live IB Gateway or Alpaca connection required.
Tests verify:
- Dataclass construction (BrokerOrder, BrokerAccount, BrokerPosition)
- Interface compliance (both adapters implement all 10 abstract methods)
- Factory routing (config "ib" -> IBBroker, "alpaca" -> AlpacaLiveBroker)
- IBBroker contract construction
- AlpacaLiveBroker delegation pattern
"""

import pytest
from unittest.mock import patch, MagicMock

from src.trading.broker_interface import (
    BrokerAdapter, BrokerOrder, BrokerAccount, BrokerPosition,
)


# ── Dataclass Tests ────────────────────────────────────────────────


class TestBrokerDataclasses:
    def test_broker_order_construction(self):
        order = BrokerOrder(
            order_id="123", ticker="AAPL", side="buy", quantity=10,
            order_type="bracket", status="filled", filled_avg_price=150.0,
            broker="ib",
        )
        assert order.order_id == "123"
        assert order.ticker == "AAPL"
        assert order.broker == "ib"
        assert order.filled_avg_price == 150.0

    def test_broker_account_construction(self):
        acct = BrokerAccount(
            equity=10000.0, cash=5000.0, buying_power=15000.0,
            portfolio_value=10000.0, broker="alpaca",
        )
        assert acct.equity == 10000.0
        assert acct.broker == "alpaca"

    def test_broker_position_construction(self):
        pos = BrokerPosition(
            ticker="MSFT", quantity=50, avg_cost=300.0,
            current_price=310.0, unrealized_pnl=500.0,
            market_value=15500.0, broker="ib",
        )
        assert pos.ticker == "MSFT"
        assert pos.quantity == 50
        assert pos.broker == "ib"

    def test_broker_order_defaults(self):
        order = BrokerOrder(
            order_id="1", ticker="X", side="buy", quantity=1,
            order_type="market", status="pending",
        )
        assert order.filled_avg_price is None
        assert order.filled_qty is None
        assert order.stop_price is None
        assert order.broker == ""


# ── Interface Compliance ───────────────────────────────────────────


class TestInterfaceCompliance:
    """Verify both adapters implement all abstract methods."""

    def test_alpaca_broker_implements_interface(self):
        from src.trading.alpaca_broker import AlpacaLiveBroker
        assert issubclass(AlpacaLiveBroker, BrokerAdapter)
        # Verify all 10 abstract methods are implemented
        broker = AlpacaLiveBroker()
        for method_name in [
            "get_account", "place_bracket_order", "place_market_order",
            "place_exit", "cancel_order", "get_order_status",
            "get_position", "get_all_positions", "get_current_price",
            "is_connected",
        ]:
            assert hasattr(broker, method_name), f"Missing method: {method_name}"
            assert callable(getattr(broker, method_name))

    def test_ib_broker_implements_interface(self):
        from src.trading.ib_broker import IBBroker
        assert issubclass(IBBroker, BrokerAdapter)
        broker = IBBroker(port=4002)
        for method_name in [
            "get_account", "place_bracket_order", "place_market_order",
            "place_exit", "cancel_order", "get_order_status",
            "get_position", "get_all_positions", "get_current_price",
            "is_connected",
        ]:
            assert hasattr(broker, method_name), f"Missing method: {method_name}"

    def test_alpaca_broker_is_always_connected(self):
        """Alpaca uses REST — no persistent connection to check."""
        from src.trading.alpaca_broker import AlpacaLiveBroker
        assert AlpacaLiveBroker().is_connected() is True

    def test_ib_broker_disconnected_by_default(self):
        """IBBroker uses lazy connect — not connected until first use."""
        from src.trading.ib_broker import IBBroker
        broker = IBBroker(port=4002)
        assert broker.is_connected() is False


# ── Factory Tests ──────────────────────────────────────────────────


class TestBrokerFactory:
    def setup_method(self):
        """Clear factory cache between tests."""
        from src.trading import broker_factory
        broker_factory._brokers.clear()

    def test_factory_returns_alpaca_by_default(self):
        from src.trading.broker_factory import get_live_broker
        config = {"live_trading": {}}
        broker = get_live_broker(config)
        from src.trading.alpaca_broker import AlpacaLiveBroker
        assert isinstance(broker, AlpacaLiveBroker)

    def test_factory_returns_alpaca_when_configured(self):
        from src.trading.broker_factory import get_live_broker
        config = {"live_trading": {"broker": "alpaca"}}
        broker = get_live_broker(config)
        from src.trading.alpaca_broker import AlpacaLiveBroker
        assert isinstance(broker, AlpacaLiveBroker)

    def test_factory_returns_ib_when_configured(self):
        from src.trading.broker_factory import get_live_broker
        config = {
            "trading": {"ib_enabled": True},  # SD#41 — explicit opt-in past cold-storage gate
            "live_trading": {
                "broker": "ib",
                "ib": {"host": "127.0.0.1", "port": 4002, "client_id": 99},
            },
        }
        broker = get_live_broker(config)
        from src.trading.ib_broker import IBBroker
        assert isinstance(broker, IBBroker)
        assert broker._port == 4002
        assert broker._client_id == 99

    def test_factory_caches_broker_instances(self):
        from src.trading.broker_factory import get_live_broker
        config = {"live_trading": {"broker": "alpaca"}}
        broker1 = get_live_broker(config)
        broker2 = get_live_broker(config)
        assert broker1 is broker2

    def test_factory_ib_default_port_is_paper(self):
        """Default port should be 4002 (paper), not 4001 (live)."""
        from src.trading.broker_factory import get_live_broker
        config = {
            "trading": {"ib_enabled": True},  # SD#41 — explicit opt-in past cold-storage gate
            "live_trading": {"broker": "ib"},
        }
        broker = get_live_broker(config)
        from src.trading.ib_broker import IBBroker
        assert isinstance(broker, IBBroker)
        assert broker._port == 4002  # PAPER, not live

    def test_reset_brokers_clears_cache(self):
        from src.trading.broker_factory import get_live_broker, reset_brokers, _brokers
        config = {"live_trading": {"broker": "alpaca"}}
        get_live_broker(config)
        assert len(_brokers) == 1
        reset_brokers()
        assert len(_brokers) == 0


# ── IB Broker Unit Tests ──────────────────────────────────────────

try:
    import ib_async  # noqa: F401
    _HAS_IB_ASYNC = True
except ImportError:
    _HAS_IB_ASYNC = False


@pytest.mark.skipif(not _HAS_IB_ASYNC, reason="ib_async not installed")
class TestIBBrokerUnit:
    def test_make_contract(self):
        """_make_contract should create a Stock contract for US equity."""
        from src.trading.ib_broker import IBBroker
        broker = IBBroker(port=4002)
        contract = broker._make_contract("AAPL")
        assert contract.symbol == "AAPL"
        assert contract.exchange == "SMART"
        assert contract.currency == "USD"

    def test_ensure_connected_raises_without_gateway(self):
        """_ensure_connected should raise when no IB Gateway is running."""
        from src.trading.ib_broker import IBBroker
        broker = IBBroker(host="127.0.0.1", port=19999, timeout=1)
        with pytest.raises(Exception):
            broker._ensure_connected()

    def test_disconnect_when_not_connected(self):
        """disconnect() should be safe to call when not connected."""
        from src.trading.ib_broker import IBBroker
        broker = IBBroker(port=4002)
        broker.disconnect()  # Should not raise


# ── Alpaca Broker Delegation Tests ─────────────────────────────────


class TestAlpacaBrokerDelegation:
    @patch("src.shadow_trading.alpaca_adapter.get_live_account_info")
    def test_get_account_delegates(self, mock_acct):
        mock_acct.return_value = {
            "equity": 5000.0, "cash": 3000.0,
            "buying_power": 8000.0, "portfolio_value": 5000.0,
        }
        from src.trading.alpaca_broker import AlpacaLiveBroker
        broker = AlpacaLiveBroker()
        acct = broker.get_account()
        assert acct.equity == 5000.0
        assert acct.broker == "alpaca"
        mock_acct.assert_called_once()

    @patch("src.shadow_trading.alpaca_adapter.get_current_price")
    def test_get_current_price_delegates(self, mock_price):
        mock_price.return_value = 150.25
        from src.trading.alpaca_broker import AlpacaLiveBroker
        broker = AlpacaLiveBroker()
        price = broker.get_current_price("AAPL")
        assert price == 150.25
        mock_price.assert_called_once_with("AAPL")
