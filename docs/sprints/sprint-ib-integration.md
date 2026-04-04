# Sprint: Interactive Brokers Integration — Live Trading Migration

> **Priority:** HIGH — IB live track record is a v1.0.0 path item and fund formation prerequisite
> **Estimated time:** 8-12 hours CC time
> **Prerequisites:** IB account approved (paper + live), IB Gateway installed on Windows
> **Tag as part of the next minor release after bug bash.**

---

## Context

Arcis currently uses Alpaca for both paper and live trading via `src/shadow_trading/alpaca_adapter.py`. The fund formation research ("From Solo AI Trader to Fund Manager") explicitly states:

> "Open an Interactive Brokers account alongside Alpaca for track record infrastructure.
> IBKR's PortfolioAnalyst provides GIPS-verified returns and institutional-grade
> performance reporting — capabilities Alpaca lacks."

**Target architecture:**
- **Paper trading:** Alpaca (unchanged — 100K paper account, bootcamp, Strategy #1 + #2)
- **Live trading:** Interactive Brokers (replaces Alpaca live — real money, GIPS track record)
- **Alpaca live ($100 account):** Keep as fallback, but IB becomes primary

The Alpaca paper account continues accumulating trades toward the Phase 1 gate. IB live runs the same signals with real capital for institutional-credible track record.

---

## Pre-Flight

1. Read `MASTER.md` — current state and architecture
2. Read `src/shadow_trading/alpaca_adapter.py` — the interface to replicate
3. Read `src/shadow_trading/executor.py` — the live trade execution path (lines 870-1070)
4. Run `python -m pytest tests/ -x -q` — record baseline pass count

---

## Task 1: Install IB Gateway and ib_async

**IB Gateway** is the headless version of TWS — no GUI, lower memory, designed for always-on automated systems. Ryan needs to install this on his Windows machine.

**Manual step (Ryan does this, not CC):**
1. Download IB Gateway from https://www.interactivebrokers.com/en/trading/ibgateway-stable.php
2. Install and log in with IB credentials
3. Configure: API Settings → Enable ActiveX and Socket Clients → Check
4. Port: 4002 for paper, 4001 for live (IB Gateway defaults)
5. Check "Download open orders on connection"
6. Leave IB Gateway running in the background

**CC installs the Python library:**
```bash
pip install ib_async --break-system-packages
```

`ib_async` is the actively maintained successor to `ib_insync` (original creator Ewald de Wit passed away in 2024; community forked and renamed). It provides sync/async wrappers around the TWS API.

---

## Task 2: Create the Broker Interface

**File:** `src/trading/__init__.py` (new directory)
**File:** `src/trading/broker_interface.py` (new file)

Create an abstract broker interface that both Alpaca and IB implement:

```python
"""Abstract broker interface for multi-broker support.

Called by: shadow_trading.executor
Calls: none (implementations call broker APIs)
Owns tables: none
Config keys: live_trading.broker
Tests: tests/test_broker_interface.py
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
    broker: str = ""    # "alpaca" or "ib"


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
    """Abstract broker adapter. Alpaca and IB both implement this."""

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
```

---

## Task 3: Wrap Existing Alpaca Adapter

**File:** `src/trading/alpaca_broker.py` (new file)

Wrap the existing `alpaca_adapter.py` functions into the `BrokerAdapter` interface. This is a thin wrapper — don't rewrite alpaca_adapter.py, just delegate to it:

```python
"""Alpaca broker adapter — wraps existing alpaca_adapter.py.

Called by: trading.broker_factory
Calls: shadow_trading.alpaca_adapter
"""

from src.trading.broker_interface import (
    BrokerAdapter, BrokerAccount, BrokerOrder, BrokerPosition
)

class AlpacaLiveBroker(BrokerAdapter):
    """Wraps Alpaca live trading functions."""

    def get_account(self) -> BrokerAccount:
        from src.shadow_trading.alpaca_adapter import get_live_account_info
        acct = get_live_account_info()
        return BrokerAccount(
            equity=float(acct.get("equity", 0)),
            cash=float(acct.get("cash", 0)),
            buying_power=float(acct.get("buying_power", 0)),
            portfolio_value=float(acct.get("portfolio_value", 0)),
            broker="alpaca",
        )

    # ... delegate each method to the corresponding alpaca_adapter function
    # This is mechanical — each method calls the existing function and
    # returns a normalized BrokerOrder/BrokerPosition/BrokerAccount
```

**Important:** This does NOT change how paper trading works. Paper trading continues calling `alpaca_adapter.py` directly. Only live trading goes through the broker interface.

---

## Task 4: Create the IB Adapter

**File:** `src/trading/ib_broker.py` (new file)

This is the core new code. Implement `BrokerAdapter` using `ib_async`:

```python
"""Interactive Brokers adapter via ib_async.

Called by: trading.broker_factory
Calls: ib_async (TWS API)
Owns tables: none
Config keys: live_trading.ib.*
Tests: tests/test_ib_broker.py

Requires IB Gateway or TWS running on localhost.
Default ports: 4001 (live), 4002 (paper).
"""

import logging
from typing import Optional

from src.trading.broker_interface import (
    BrokerAdapter, BrokerAccount, BrokerOrder, BrokerPosition
)

logger = logging.getLogger(__name__)


class IBBroker(BrokerAdapter):
    """Interactive Brokers adapter using ib_async."""

    def __init__(self, host: str = "127.0.0.1", port: int = 4001,
                 client_id: int = 1, timeout: int = 10):
        self._host = host
        self._port = port
        self._client_id = client_id
        self._timeout = timeout
        self._ib = None  # Lazy connection

    def _ensure_connected(self):
        """Lazy connect to IB Gateway. Reconnects if disconnected."""
        if self._ib is not None and self._ib.isConnected():
            return
        try:
            from ib_async import IB
            self._ib = IB()
            self._ib.connect(
                self._host, self._port, clientId=self._client_id,
                timeout=self._timeout,
            )
            logger.info("[IB] Connected to gateway at %s:%d", self._host, self._port)
        except Exception as e:
            logger.error("[IB] Connection failed: %s", e)
            self._ib = None
            raise

    def _make_contract(self, ticker: str):
        """Create an IB Stock contract for a US equity."""
        from ib_async import Stock
        return Stock(ticker, "SMART", "USD")

    def is_connected(self) -> bool:
        return self._ib is not None and self._ib.isConnected()

    def get_account(self) -> BrokerAccount:
        self._ensure_connected()
        # IB provides account values as a list of AccountValue objects
        account_values = self._ib.accountSummary()
        # Parse into a dict for easier access
        vals = {}
        for av in account_values:
            vals[av.tag] = av.value
        return BrokerAccount(
            equity=float(vals.get("NetLiquidation", 0)),
            cash=float(vals.get("TotalCashValue", 0)),
            buying_power=float(vals.get("BuyingPower", 0)),
            portfolio_value=float(vals.get("GrossPositionValue", 0)),
            broker="ib",
        )

    def place_bracket_order(
        self,
        ticker: str,
        quantity: int,
        take_profit_price: float,
        stop_loss_price: float,
        limit_price: Optional[float] = None,
    ) -> BrokerOrder:
        """Place IB bracket order (parent + 2 child orders in OCA group)."""
        self._ensure_connected()
        from ib_async import Order as IBOrder
        contract = self._make_contract(ticker)

        # IB bracket = 3 linked orders: parent entry + take profit + stop loss
        bracket = self._ib.bracketOrder(
            action="BUY",
            quantity=quantity,
            limitPrice=limit_price or 0,  # 0 = market
            takeProfitPrice=take_profit_price,
            stopLossPrice=stop_loss_price,
        )

        # If no limit price, convert parent to market order
        if not limit_price:
            bracket[0].orderType = "MKT"
            bracket[0].lmtPrice = 0

        # Set all orders to GTC
        for order in bracket:
            order.tif = "GTC"

        # Place the bracket (parent + children)
        trades = []
        for order in bracket:
            trade = self._ib.placeOrder(contract, order)
            trades.append(trade)

        parent_trade = trades[0]
        # Wait briefly for fill
        self._ib.sleep(2)

        return BrokerOrder(
            order_id=str(parent_trade.order.orderId),
            ticker=ticker,
            side="buy",
            quantity=quantity,
            order_type="bracket",
            status=parent_trade.orderStatus.status.lower(),
            filled_avg_price=parent_trade.orderStatus.avgFillPrice or None,
            filled_qty=int(parent_trade.orderStatus.filled) if parent_trade.orderStatus.filled else 0,
            stop_price=stop_loss_price,
            take_profit_price=take_profit_price,
            broker="ib",
        )

    def place_market_order(self, ticker: str, quantity: int,
                           side: str = "buy") -> BrokerOrder:
        self._ensure_connected()
        from ib_async import MarketOrder
        contract = self._make_contract(ticker)
        action = "BUY" if side == "buy" else "SELL"
        order = MarketOrder(action, quantity)
        order.tif = "GTC"
        trade = self._ib.placeOrder(contract, order)
        self._ib.sleep(2)

        return BrokerOrder(
            order_id=str(trade.order.orderId),
            ticker=ticker,
            side=side,
            quantity=quantity,
            order_type="market",
            status=trade.orderStatus.status.lower(),
            filled_avg_price=trade.orderStatus.avgFillPrice or None,
            filled_qty=int(trade.orderStatus.filled) if trade.orderStatus.filled else 0,
            broker="ib",
        )

    def place_exit(self, ticker: str, quantity: int = 0) -> BrokerOrder:
        """Close position. quantity=0 closes all shares."""
        self._ensure_connected()
        if quantity == 0:
            pos = self.get_position(ticker)
            if not pos:
                raise ValueError(f"No position in {ticker}")
            quantity = pos.quantity
        return self.place_market_order(ticker, quantity, side="sell")

    def cancel_order(self, order_id: str) -> bool:
        self._ensure_connected()
        for trade in self._ib.openTrades():
            if str(trade.order.orderId) == order_id:
                self._ib.cancelOrder(trade.order)
                self._ib.sleep(1)
                return True
        return False

    def get_order_status(self, order_id: str) -> BrokerOrder:
        self._ensure_connected()
        for trade in self._ib.trades():
            if str(trade.order.orderId) == order_id:
                return BrokerOrder(
                    order_id=order_id,
                    ticker=trade.contract.symbol,
                    side=trade.order.action.lower(),
                    quantity=int(trade.order.totalQuantity),
                    order_type=trade.order.orderType.lower(),
                    status=trade.orderStatus.status.lower(),
                    filled_avg_price=trade.orderStatus.avgFillPrice or None,
                    filled_qty=int(trade.orderStatus.filled) if trade.orderStatus.filled else 0,
                    broker="ib",
                )
        raise ValueError(f"Order {order_id} not found")

    def get_position(self, ticker: str) -> Optional[BrokerPosition]:
        self._ensure_connected()
        for pos in self._ib.positions():
            if pos.contract.symbol == ticker:
                return BrokerPosition(
                    ticker=ticker,
                    quantity=int(pos.position),
                    avg_cost=float(pos.avgCost),
                    current_price=0.0,  # Need separate market data request
                    unrealized_pnl=float(pos.unrealizedPNL) if hasattr(pos, 'unrealizedPNL') else 0.0,
                    market_value=float(pos.position * pos.avgCost),
                    broker="ib",
                )
        return None

    def get_all_positions(self) -> list[BrokerPosition]:
        self._ensure_connected()
        return [
            BrokerPosition(
                ticker=pos.contract.symbol,
                quantity=int(pos.position),
                avg_cost=float(pos.avgCost),
                current_price=0.0,
                unrealized_pnl=0.0,
                market_value=float(pos.position * pos.avgCost),
                broker="ib",
            )
            for pos in self._ib.positions()
        ]

    def get_current_price(self, ticker: str) -> Optional[float]:
        """Get current price via IB market data snapshot."""
        self._ensure_connected()
        try:
            contract = self._make_contract(ticker)
            self._ib.qualifyContracts(contract)
            ticker_data = self._ib.reqMktData(contract, snapshot=True)
            self._ib.sleep(3)  # Wait for snapshot
            price = ticker_data.marketPrice()
            self._ib.cancelMktData(contract)
            return float(price) if price and price > 0 else None
        except Exception as e:
            logger.debug("[IB] Price fetch failed for %s: %s", ticker, e)
            return None

    def disconnect(self):
        """Gracefully disconnect from IB Gateway."""
        if self._ib and self._ib.isConnected():
            self._ib.disconnect()
            logger.info("[IB] Disconnected from gateway")
```

**Critical notes for CC:**
- `ib_async` requires an event loop. The `IB()` object manages its own asyncio loop internally when used in sync mode.
- `self._ib.sleep(N)` is NOT `time.sleep()` — it keeps the IB event loop running while waiting, which is required for fills to arrive.
- IB bracket orders use `bracketOrder()` which returns a list of 3 `Order` objects (parent, take-profit, stop-loss). All three must be placed.
- IB uses `GTC` (Good Till Cancel) differently than Alpaca — verify behavior.
- IB has pacing violations: max ~50 messages/second. Don't spam requests.
- `accountSummary()` may need `self._ib.reqAccountSummary()` first depending on IB Gateway version. Check `ib_async` docs.

---

## Task 5: Broker Factory

**File:** `src/trading/broker_factory.py` (new file)

Simple factory that returns the right broker based on config:

```python
"""Broker factory — returns the configured live trading broker.

Called by: shadow_trading.executor
Config keys: live_trading.broker
"""

import logging
from src.trading.broker_interface import BrokerAdapter

logger = logging.getLogger(__name__)

# Singleton instances (one connection per broker)
_brokers: dict[str, BrokerAdapter] = {}


def get_live_broker(config: dict) -> BrokerAdapter:
    """Get the configured live trading broker adapter.

    Config:
        live_trading.broker: "alpaca" (default) or "ib"
        live_trading.ib.host: "127.0.0.1" (default)
        live_trading.ib.port: 4001 (live) or 4002 (paper)
        live_trading.ib.client_id: 1 (default)
    """
    live_cfg = config.get("live_trading", {})
    broker_name = live_cfg.get("broker", "alpaca")

    if broker_name in _brokers:
        broker = _brokers[broker_name]
        if broker.is_connected():
            return broker
        logger.warning("[BROKER] %s connection lost, reconnecting...", broker_name)

    if broker_name == "ib":
        from src.trading.ib_broker import IBBroker
        ib_cfg = live_cfg.get("ib", {})
        broker = IBBroker(
            host=ib_cfg.get("host", "127.0.0.1"),
            port=ib_cfg.get("port", 4001),
            client_id=ib_cfg.get("client_id", 1),
            timeout=ib_cfg.get("timeout", 10),
        )
        _brokers["ib"] = broker
        return broker

    # Default: Alpaca
    from src.trading.alpaca_broker import AlpacaLiveBroker
    broker = AlpacaLiveBroker()
    _brokers["alpaca"] = broker
    return broker
```

---

## Task 6: Wire Into Executor

**File:** `src/shadow_trading/executor.py`

The live trade execution path (function starting around line 870) currently imports directly from `alpaca_adapter`. Change it to use the broker factory:

**Replace the live entry block** (around lines 1060-1075) from:
```python
from src.shadow_trading.alpaca_adapter import place_live_entry
order = place_live_entry(ticker, planned_shares, notional=planned_allocation)
```

To:
```python
from src.trading.broker_factory import get_live_broker
broker = get_live_broker(config)
order = broker.place_bracket_order(
    ticker=ticker,
    quantity=planned_shares,
    take_profit_price=target_price,
    stop_loss_price=stop_price,
)
trade_data["alpaca_order_id"] = order.order_id  # Works for both brokers
trade_data["order_type"] = order.order_type
trade_data["actual_entry_price"] = order.filled_avg_price or entry_price
trade_data["broker"] = order.broker
```

**Also update the live exit path** (around line 59):
```python
# FROM:
from src.shadow_trading.alpaca_adapter import place_live_exit
return place_live_exit(trade["ticker"], 0)

# TO:
from src.trading.broker_factory import get_live_broker
from src.config import load_config
broker = get_live_broker(load_config())
result = broker.place_exit(trade["ticker"], 0)
return {"order_id": result.order_id, "status": result.status}
```

**Also update the live account info call** (around line 913):
```python
# FROM:
from src.shadow_trading.alpaca_adapter import get_live_account_info
live_acct = get_live_account_info()

# TO:
from src.trading.broker_factory import get_live_broker
broker = get_live_broker(config)
acct = broker.get_account()
live_acct = {
    "equity": acct.equity,
    "cash": acct.cash,
    "buying_power": acct.buying_power,
    "portfolio_value": acct.portfolio_value,
}
```

**Do NOT change the paper trading paths.** Paper trading continues using `alpaca_adapter.py` directly. Only live trading goes through the broker factory.

---

## Task 7: Add IB Config to YAML

**File:** `config/settings.example.yaml`

Add IB configuration under live_trading:

```yaml
live_trading:
  enabled: true
  broker: "ib"                             # "alpaca" or "ib"
  starting_capital: 100
  max_open_positions: 5
  risk:
    planned_risk_pct_max: 0.02
    stop_atr_multiplier: 2.0
    target_atr_multiplier: 2.0
    timeout_days: 7
  # Interactive Brokers settings (only used when broker: "ib")
  ib:
    host: "127.0.0.1"
    port: 4001                             # 4001=live, 4002=paper
    client_id: 1
    timeout: 10
    # IB Gateway must be running on this machine
  # Alpaca settings (only used when broker: "alpaca")
  api_key: "your-live-alpaca-api-key"
  secret_key: "your-live-alpaca-secret-key"
```

---

## Task 8: IB Connection Health Check

**File:** `src/trading/ib_broker.py` — add to IBBroker class
**File:** `src/scheduler/watch.py` — add to startup and heartbeat

Add IB connection status to the watch loop startup banner and heartbeat:

```python
# In _get_live_stats() or a new helper:
try:
    from src.trading.broker_factory import get_live_broker
    broker = get_live_broker(self.config)
    stats["ib_connected"] = broker.is_connected()
    stats["live_broker"] = self.config.get("live_trading", {}).get("broker", "alpaca")
except Exception:
    stats["ib_connected"] = False
    stats["live_broker"] = "unknown"
```

Add to banner output:
```
 Live broker: IB (connected) | Equity: $X,XXX
```

**Also add a Telegram alert** if IB disconnects during market hours:
```python
# In the main loop, check every 5 minutes during market hours:
if live_broker == "ib" and not broker.is_connected():
    logger.error("[IB] Gateway disconnected during market hours!")
    # Attempt reconnect
    try:
        broker._ensure_connected()
        send_telegram("✅ IB Gateway reconnected")
    except Exception:
        send_telegram("🚨 IB Gateway disconnected — live trades disabled until reconnect")
```

---

## Task 9: Add broker Column to shadow_trades

**File:** `src/schema/registry.py`

Add a `broker` column to track which broker executed each trade:

```python
ColumnDef("broker", "TEXT", default="alpaca", description="Broker that executed the trade (alpaca or ib)"),
```

This goes in the shadow_trades table definition, after the existing `source` column. Existing trades will default to "alpaca".

---

## Task 10: Dashboard IB Status

**File:** `frontend/src/pages/Dashboard.jsx`

Add IB connection status to the system section of the dashboard. The API already exposes system status — extend it:

**File:** `src/api/routes/system.py` — add an endpoint or extend `/status`:

```python
# Add to the status response:
try:
    from src.trading.broker_factory import get_live_broker
    from src.config import load_config
    broker = get_live_broker(load_config())
    status["ib_connected"] = broker.is_connected()
    status["live_broker"] = load_config().get("live_trading", {}).get("broker", "alpaca")
except Exception:
    status["ib_connected"] = False
    status["live_broker"] = "alpaca"
```

On the dashboard, show a small status indicator next to the halt button:
```
🟢 IB Connected | HALT TRADING
```
or
```
🔴 IB Disconnected | HALT TRADING
```

---

## Task 11: Tests

**File:** `tests/test_broker_interface.py` (new)
**File:** `tests/test_ib_broker.py` (new)

Write tests that DON'T require a live IB Gateway connection:

```python
# test_broker_interface.py:
# - Test BrokerOrder, BrokerAccount, BrokerPosition dataclasses
# - Test that AlpacaLiveBroker implements all abstract methods
# - Test that IBBroker implements all abstract methods
# - Test broker_factory returns correct type based on config

# test_ib_broker.py:
# - Test IBBroker._make_contract returns correct Stock contract
# - Test is_connected returns False when not connected
# - Test _ensure_connected raises when gateway not available
# - Mock-based tests for order placement flow
```

**Do NOT write tests that connect to a real IB Gateway.** All IB API calls should be mocked. The real integration testing happens manually when Ryan runs it.

---

## Task 12: Reconciliation Awareness

**File:** `src/shadow_trading/reconcile.py`

The reconciler currently only knows about Alpaca positions. Update it to also check IB positions when the broker is "ib":

```python
# When checking if a trade is still open on the broker:
if trade.get("broker") == "ib":
    from src.trading.broker_factory import get_live_broker
    broker = get_live_broker(config)
    pos = broker.get_position(trade["ticker"])
    # ... check if position still exists
else:
    # Existing Alpaca reconciliation logic
    from src.shadow_trading.alpaca_adapter import get_all_positions
    ...
```

---

## Task 13: Documentation

Update these files:

**`MASTER.md`:**
- Section 1 (Tech Stack): Add "Trading: Alpaca paper + IB live (bracket orders, GTC)"
- Section 3 (Architecture): Add IB Gateway to infrastructure layer
- Section 11 (Sprint Queue): Mark IB integration as DONE

**`config/settings.example.yaml`:**
- Already updated in Task 7

**`CLAUDE.md`:**
- Add `src/trading/` to the module registry
- Note: IB Gateway must be running for live trades

**`frontend/README.md` or `docs/deployment.md`:**
- Add IB Gateway setup instructions

---

## Task 14: Commit + Release

```bash
git add -A
git commit -m "feat: Interactive Brokers integration — broker abstraction + IB adapter

New module: src/trading/ (broker_interface, ib_broker, alpaca_broker, broker_factory)

Architecture:
- Abstract BrokerAdapter interface with normalized Order/Account/Position types
- IBBroker using ib_async (maintained fork of ib_insync)
- AlpacaLiveBroker wrapping existing alpaca_adapter.py
- Broker factory dispatches based on live_trading.broker config
- Paper trading unchanged (still Alpaca direct)
- Live trading routed through broker factory → IB or Alpaca

Features:
- IB bracket orders (OCA group: parent + take-profit + stop-loss)
- Lazy connection with auto-reconnect
- IB connection health check in watch loop banner + heartbeat
- Telegram alert on IB disconnect during market hours
- broker column on shadow_trades for provenance tracking
- Dashboard IB connection status indicator

Config: live_trading.broker = 'ib' | 'alpaca' (default)
IB settings: host, port (4001=live, 4002=paper), client_id, timeout

Tests: mock-based (no live IB Gateway required)"
```

---

## Acceptance Criteria

### Core
- [ ] `src/trading/broker_interface.py` defines BrokerAdapter ABC with 10 methods
- [ ] `src/trading/ib_broker.py` implements full BrokerAdapter for IB
- [ ] `src/trading/alpaca_broker.py` wraps existing Alpaca live functions
- [ ] `src/trading/broker_factory.py` returns correct broker based on config
- [ ] `live_trading.broker: "ib"` in config routes live trades through IBBroker
- [ ] `live_trading.broker: "alpaca"` (or missing) routes through AlpacaLiveBroker
- [ ] Paper trading completely unchanged — still calls alpaca_adapter.py directly

### Executor Integration
- [ ] Live entry uses `broker.place_bracket_order()` instead of `place_live_entry()`
- [ ] Live exit uses `broker.place_exit()` instead of `place_live_exit()`
- [ ] Live account info uses `broker.get_account()` instead of `get_live_account_info()`
- [ ] `trade_data["broker"]` set to "ib" or "alpaca" on every live trade

### IB-Specific
- [ ] Bracket orders use IB's native `bracketOrder()` (3 linked orders)
- [ ] All orders set to GTC time-in-force
- [ ] Lazy connection — only connects when first live trade fires
- [ ] Auto-reconnect if gateway connection drops
- [ ] Pacing-aware — no request spam

### Monitoring
- [ ] Watch loop banner shows live broker name and connection status
- [ ] Heartbeat shows IB connection status
- [ ] Telegram alert on IB disconnect during market hours
- [ ] Dashboard shows IB connection indicator

### Schema
- [ ] `broker` column added to shadow_trades (default "alpaca")
- [ ] Existing trades unaffected (default to "alpaca")

### Zero Regressions
- [ ] All Python tests pass (pass count ≥ baseline)
- [ ] `npm run build` succeeds
- [ ] Paper trading works identically (verify with `python -m src.main watch`)
- [ ] Config without `live_trading.broker` defaults to Alpaca (backward compatible)

### Deferred (not in this sprint)
- [ ] IB market data replacing yfinance for real-time prices
- [ ] IB PortfolioAnalyst integration for GIPS reporting
- [ ] IB Flex queries for automated tax/performance reports
- [ ] IB paper trading as alternative to Alpaca paper
- [ ] Position transfer (migrate existing Alpaca live positions to IB)
