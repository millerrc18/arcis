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


class TestAlpacaLiveBracket651:
    """#651 — AlpacaLiveBroker.place_bracket_order must place a REAL bracket
    on the Alpaca live account (entry + take_profit + stop_loss as one
    atomic OCO order), not a market order with software-managed stops.

    Pre-#651 the wrapper called place_live_entry (a MarketOrderRequest with
    no broker-side stop or take-profit) and lied about it by recording
    order_type='bracket' in the DB. SBUX (2026-04-10) sat open 14 days with
    zero broker-side protection because of this — operator manually liquidated.
    """

    def test_place_bracket_order_routes_to_place_live_bracket(self):
        """Wrapper must call place_live_bracket (not place_live_entry)."""
        from unittest.mock import patch
        from src.trading.alpaca_broker import AlpacaLiveBroker

        fake_order = {
            "order_id": "alpaca-bracket-123",
            "status": "accepted",
            "filled_avg_price": None,
            "qty": 10,
            "legs": ["leg-tp", "leg-sl"],
        }
        # Sprint 0 Wave 5c LIVE-VERIFY: AlpacaLiveBroker now polls
        # verify_live_order_accepted post-submit. Patch it so the test
        # remains a unit test of the routing logic (place_live_bracket
        # vs place_live_entry) without requiring real Alpaca creds.
        verify_payload = {
            "verified": True, "status": "accepted", "attempts": 1,
            "order": {"order_id": "alpaca-bracket-123", "status": "accepted"},
        }
        with patch(
            "src.shadow_trading.alpaca_adapter.place_live_bracket",
            return_value=fake_order,
        ) as mock_bracket, patch(
            "src.shadow_trading.alpaca_adapter.place_live_entry"
        ) as mock_entry, patch(
            "src.shadow_trading.alpaca_adapter.verify_live_order_accepted",
            return_value=verify_payload,
        ):
            broker = AlpacaLiveBroker()
            result = broker.place_bracket_order(
                ticker="SBUX",
                quantity=10,
                take_profit_price=102.0,
                stop_loss_price=91.88,
                limit_price=96.95,
            )

        # Critical: the bracket function was called, the market entry was NOT
        mock_bracket.assert_called_once()
        mock_entry.assert_not_called()

        kwargs = mock_bracket.call_args.kwargs
        assert kwargs["ticker"] == "SBUX"
        assert kwargs["shares"] == 10
        assert kwargs["take_profit_price"] == 102.0
        assert kwargs["stop_loss_price"] == 91.88
        assert kwargs["limit_price"] == 96.95

        # Returned BrokerOrder reflects the bracket
        assert result.order_type == "bracket"
        assert result.stop_price == 91.88
        assert result.take_profit_price == 102.0
        assert result.child_order_ids == ["leg-tp", "leg-sl"]

    def test_place_live_bracket_submits_alpaca_bracket_request(self):
        """place_live_bracket must submit OrderClass.BRACKET with TP+SL fields."""
        from unittest.mock import MagicMock, patch
        from src.shadow_trading.alpaca_adapter import place_live_bracket

        fake_order = MagicMock()
        fake_order.id = "alpaca-bracket-456"
        fake_order.symbol = "SBUX"
        fake_order.qty = 10
        fake_order.side = "buy"
        fake_order.type = "market"
        fake_order.status = "accepted"
        fake_order.filled_avg_price = None
        fake_order.legs = []

        fake_client = MagicMock()
        fake_client.submit_order.return_value = fake_order

        with patch(
            "src.shadow_trading.alpaca_adapter_live._get_live_config",
            return_value={"enabled": True, "api_key": "k", "api_secret": "s"},
        ), patch(
            "src.shadow_trading.alpaca_adapter_live._get_live_trading_client",
            return_value=fake_client,
        ):
            place_live_bracket(
                ticker="SBUX",
                shares=10,
                take_profit_price=102.0,
                stop_loss_price=91.88,
            )

        # Inspect the request we sent to Alpaca. Conftest mocks aliases
        # MarketOrderRequest and LimitOrderRequest to the same class, so we
        # check by absence of limit_price (the distinguishing attribute) and
        # by the mock enum's `value` payload rather than identity equality.
        submitted = fake_client.submit_order.call_args.args[0]
        assert not hasattr(submitted, "limit_price"), "market path must not set limit_price"
        assert submitted.order_class.value == "bracket"
        assert submitted.time_in_force.value == "gtc"  # survive across sessions
        assert submitted.take_profit == {"limit_price": 102.0}
        assert submitted.stop_loss == {"stop_price": 91.88}

    def test_place_live_bracket_with_limit_uses_limit_request(self):
        """When limit_price is provided, use LimitOrderRequest for slippage protection."""
        from unittest.mock import MagicMock, patch
        from src.shadow_trading.alpaca_adapter import place_live_bracket

        fake_order = MagicMock()
        fake_order.id = "x"
        fake_order.symbol = "SBUX"
        fake_order.qty = 10
        fake_order.side = "buy"
        fake_order.type = "limit"
        fake_order.status = "accepted"
        fake_order.filled_avg_price = None
        fake_order.legs = []

        fake_client = MagicMock()
        fake_client.submit_order.return_value = fake_order

        with patch(
            "src.shadow_trading.alpaca_adapter_live._get_live_config",
            return_value={"enabled": True, "api_key": "k", "api_secret": "s"},
        ), patch(
            "src.shadow_trading.alpaca_adapter_live._get_live_trading_client",
            return_value=fake_client,
        ):
            place_live_bracket(
                ticker="SBUX",
                shares=10,
                take_profit_price=102.0,
                stop_loss_price=91.88,
                limit_price=96.95,
            )

        # Limit path must include limit_price (the distinguishing attribute
        # vs the market path) and still attach broker-side bracket children.
        submitted = fake_client.submit_order.call_args.args[0]
        assert hasattr(submitted, "limit_price"), "limit path must set limit_price"
        assert submitted.limit_price == 96.95
        assert submitted.order_class.value == "bracket"
        assert submitted.take_profit == {"limit_price": 102.0}
        assert submitted.stop_loss == {"stop_price": 91.88}

    def test_paper_and_live_bracket_use_same_alpaca_api(self):
        """Coupling test: paper and live bracket implementations must be
        structurally equivalent (same OrderClass, TimeInForce, request types).

        The pre-#651 comment "Alpaca live doesn't have a native bracket order
        API like paper" was factually wrong. This test makes that assumption
        explicit so future developers can't reintroduce the same belief.
        """
        import inspect
        from src.shadow_trading import alpaca_adapter

        paper_src = inspect.getsource(alpaca_adapter.place_bracket_order)
        # Live bracket request construction is in _build_live_bracket_request
        # (delegated out of place_live_bracket for single-responsibility).
        live_src = inspect.getsource(alpaca_adapter._build_live_bracket_request)

        # Both must use OrderClass.BRACKET — that's the safety contract
        assert "OrderClass.BRACKET" in paper_src
        assert "OrderClass.BRACKET" in live_src

        # Both must use GTC so brackets survive across sessions
        assert "TimeInForce.GTC" in paper_src
        assert "TimeInForce.GTC" in live_src

        # Both must support take_profit and stop_loss kwargs
        assert "take_profit=" in paper_src and "take_profit=" in live_src
        assert "stop_loss=" in paper_src and "stop_loss=" in live_src
