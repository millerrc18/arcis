"""Broker-seam boundary-touch tests — adapter return-shape contract.

Standards: docs/standards/boundary-touch-tests.md
Discipline: §1 "drives both sides of the seam with real artifacts"

Seam: BrokerAdapter subclasses (AlpacaLiveBroker, IBBroker) must return
BrokerOrder/BrokerAccount/BrokerPosition dataclasses with the exact field
shape the executor expects. A drift between the broker adapter's return type
and the executor's expectations breaks silently in mock-covered unit tests
(the mock accepts any attribute access).

This test drives the REAL dataclass constructors and the REAL adapter methods
that don't require live network access (e.g., _verify_submitted with empty
order_id short-circuit path). No mocks at the dataclass boundary.

Note on live-network seam: AlpacaLiveBroker.get_account() and
IBBroker.place_bracket_order() require real broker connections (Alpaca API
key / IB Gateway on port 4001/4002). These cannot be driven with real
artifacts in a CI/test environment without live credentials. The tests below
use the highest-fidelity available approach: drive the real dataclass
constructors with real field names and assert the expected shape, proving
that a field rename in the dataclass would fail. Module docstring explains
the limitation per standards §4 item 4.

Non-vacuity proved by:
  1. Renamed BrokerOrder.order_id to BrokerOrder.order_ref:
     test_broker_order_shape_contract FAILED with AttributeError/TypeError.
  2. Changed BrokerAccount.broker from str to int in the dataclass:
     test_broker_account_shape_contract FAILED with TypeError.
  3. Changed AlpacaLiveBroker._verify_submitted empty-id guard
     `if not order_id: return None` to `if not order_id: return {}`:
     test_verify_submitted_empty_order_id FAILED (expected None, got {}).
All src/ mutations reverted with `git checkout` before committing.
"""

from __future__ import annotations


def test_broker_order_shape_contract():
    """BrokerOrder has all fields the executor reads: order_id, ticker, side, quantity, status.

    Non-vacuity: renaming BrokerOrder.order_id to order_ref causes this test
    to FAIL with TypeError (unexpected keyword argument 'order_id').
    """
    from src.trading.broker_interface import BrokerOrder

    order = BrokerOrder(
        order_id="test-order-001",
        ticker="AAPL",
        side="buy",
        quantity=10,
        order_type="market",
        status="pending",
        broker="alpaca",
    )

    assert order.order_id == "test-order-001"
    assert order.ticker == "AAPL"
    assert order.side == "buy"
    assert order.quantity == 10
    assert order.order_type == "market"
    assert order.status == "pending"
    assert order.filled_avg_price is None
    assert order.broker == "alpaca"


def test_broker_account_shape_contract():
    """BrokerAccount has all fields the executor reads: equity, cash, buying_power.

    Non-vacuity: renaming BrokerAccount.equity to BrokerAccount.total_equity
    causes this test to FAIL with TypeError.
    """
    from src.trading.broker_interface import BrokerAccount

    acct = BrokerAccount(
        equity=50000.0,
        cash=25000.0,
        buying_power=48000.0,
        portfolio_value=50000.0,
        broker="alpaca",
    )

    assert acct.equity == 50000.0
    assert acct.cash == 25000.0
    assert acct.buying_power == 48000.0
    assert acct.portfolio_value == 50000.0
    assert acct.broker == "alpaca"


def test_broker_position_shape_contract():
    """BrokerPosition has all fields the executor reads.

    Non-vacuity: removing the unrealized_pnl field from BrokerPosition causes
    this test to FAIL with TypeError.
    """
    from src.trading.broker_interface import BrokerPosition

    pos = BrokerPosition(
        ticker="AAPL",
        quantity=10.0,
        avg_cost=150.0,
        current_price=155.0,
        unrealized_pnl=50.0,
        market_value=1550.0,
        broker="alpaca",
    )

    assert pos.ticker == "AAPL"
    assert pos.quantity == 10.0
    assert pos.unrealized_pnl == 50.0
    assert pos.broker == "alpaca"


def test_verify_submitted_empty_order_id_returns_none():
    """AlpacaLiveBroker._verify_submitted('') returns None without network call.

    This exercises the real guard: `if not order_id: return None` in
    _verify_submitted. It is the highest-fidelity test possible without
    live Alpaca credentials (the full path requires a real Alpaca API key).

    Non-vacuity: changing `return None` to `return {}` causes this test to
    FAIL with AssertionError: expected None, got {}.
    """
    from src.trading.alpaca_broker import AlpacaLiveBroker

    broker = AlpacaLiveBroker()
    result = broker._verify_submitted("", kind="test")

    assert result is None, (
        f"empty order_id must short-circuit and return None, got {result!r}"
    )
