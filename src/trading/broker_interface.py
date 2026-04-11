"""Abstract broker interface for multi-broker support.

Called by: shadow_trading.executor (via broker_factory)
Calls: none (implementations call broker APIs)
Owns tables: none
Config keys: live_trading.broker
Tests: tests/test_broker_interface.py

WHY an abstract base class (Strategy Pattern): The executor talks to a
BrokerAdapter interface, not a specific broker. Swapping brokers is a config
change, not a code change. This matters because:
  1. We test on IB paper (port 4002) before going live (port 4001) — same code
  2. If IB Gateway crashes, we fall back to Alpaca live with one config edit
  3. Future brokers (Tradier, Schwab) are one new file, not 15 edits
  4. The executor's 1,500+ lines of trade logic don't know which broker is active

WHY normalized dataclasses: Alpaca returns alpaca-py objects with Alpaca field
names. IB returns ib_async objects with completely different field names. The
normalized types mean the executor never deals with broker-specific types.

These 10 methods cover 100% of live trading interactions — audited from every
import of alpaca_adapter in executor.py, governor.py, and shadow_service.py.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


@dataclass
class BrokerOrder:
    """Normalized order representation across brokers."""
    order_id: str
    ticker: str
    side: str           # "buy" or "sell"
    quantity: int
    order_type: str     # "market", "limit", "bracket"
    status: str         # "pending", "filled", "cancelled", "rejected"
    filled_avg_price: Optional[float] = None
    filled_qty: Optional[int] = None
    stop_price: Optional[float] = None
    take_profit_price: Optional[float] = None
    child_order_ids: Optional[list[str]] = None  # IB bracket: [take_profit_id, stop_loss_id]
    broker: str = ""    # "alpaca" or "ib"
    perm_id: str = ""   # IB permId for cross-session order tracking


@dataclass
class BrokerAccount:
    """Normalized account info across brokers."""
    equity: float
    cash: float
    buying_power: float
    portfolio_value: float
    broker: str = ""


@dataclass
class BrokerPosition:
    """Normalized position representation."""
    ticker: str
    quantity: int
    avg_cost: float
    current_price: float
    unrealized_pnl: float
    market_value: float
    broker: str = ""


class BrokerAdapter(ABC):
    """Abstract broker adapter. Alpaca and IB both implement this.

    Each method maps to a specific operation the executor already performs.
    Implementations handle broker-specific quirks (Alpaca notional ordering,
    IB OCA bracket groups, etc.) and return normalized dataclasses.
    """

    @abstractmethod
    def get_account(self) -> BrokerAccount:
        """Get account info: equity, cash, buying power."""
        ...

    @abstractmethod
    def place_bracket_order(
        self,
        ticker: str,
        quantity: int,
        take_profit_price: float,
        stop_loss_price: float,
        limit_price: Optional[float] = None,
    ) -> BrokerOrder:
        """Place a bracket order (entry + stop + target)."""
        ...

    @abstractmethod
    def place_market_order(
        self,
        ticker: str,
        quantity: int,
        side: str = "buy",
    ) -> BrokerOrder:
        """Place a simple market order."""
        ...

    @abstractmethod
    def place_exit(self, ticker: str, quantity: int = 0) -> BrokerOrder:
        """Exit a position (market sell). quantity=0 means close all."""
        ...

    @abstractmethod
    def cancel_order(self, order_id: str) -> bool:
        """Cancel a pending order. Returns True if cancelled."""
        ...

    @abstractmethod
    def get_order_status(self, order_id: str) -> BrokerOrder:
        """Get current status of an order."""
        ...

    @abstractmethod
    def get_position(self, ticker: str) -> Optional[BrokerPosition]:
        """Get position for a specific ticker, or None."""
        ...

    @abstractmethod
    def get_all_positions(self) -> list[BrokerPosition]:
        """Get all open positions."""
        ...

    @abstractmethod
    def get_current_price(self, ticker: str) -> Optional[float]:
        """Get current market price for a ticker."""
        ...

    @abstractmethod
    def is_connected(self) -> bool:
        """Check if the broker connection is alive."""
        ...
