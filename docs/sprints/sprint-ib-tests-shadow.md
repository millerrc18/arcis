# IB Test Coverage + Shadow Mode: Master Implementation Document

**Version:** 1.0 (triple Ralph-looped: spec, implementation plan, sprint prompt)
**Author:** Claude (Opus 4.6)
**Date:** April 11, 2026
**Closes:** GitHub Issue #368
**Priority:** HIGH — blocks IB paper validation, prerequisite for IB live trading gate (SD #25)

---

# PART 1: DESIGN SPEC

## 1.1 Problem Statement

The IB broker adapter (`src/trading/ib_broker.py`, 271 lines) implements all 10 `BrokerAdapter` methods but has **zero test coverage** on its core trading methods. The existing tests (in `tests/test_broker_interface.py`) only verify dataclass construction, interface compliance (method existence), factory routing, contract creation, and Alpaca delegation. None of the IB methods that handle money — `place_bracket_order`, `place_exit`, `get_account`, `cancel_order`, etc. — are tested.

Simultaneously, Strategy Decision #25 gates IB live trading on a 30-day Gateway stability test. We can't start that clock without a shadow mode that validates IB behavior alongside Alpaca without execution risk.

## 1.2 What Needs Testing

IBBroker uses 15 methods on the `ib_async.IB` client, 3 imported classes (`IB`, `Stock`, `MarketOrder`), and accesses attributes across 6 different ib_async object types. Every one of these interactions must be mocked and tested.

### IB Client Methods Used (15)

| Method | Used In | What It Does |
|--------|---------|-------------|
| `connect()` | `_ensure_connected` | Establishes TCP to Gateway |
| `isConnected()` | `_ensure_connected`, `is_connected` | Connection health check |
| `disconnect()` | `disconnect` | Graceful teardown |
| `sleep()` | 5 methods | Keeps IB event loop alive (NOT `time.sleep`) |
| `accountSummary()` | `get_account` | Returns list of AccountValue |
| `reqAccountSummary()` | `get_account` | Requests fresh account data |
| `qualifyContracts()` | `place_bracket_order`, `place_market_order`, `get_current_price` | Validates contract with IB |
| `bracketOrder()` | `place_bracket_order` | Creates 3 linked orders (parent + 2 children) |
| `placeOrder()` | `place_bracket_order`, `place_market_order` | Submits order to IB |
| `openTrades()` | `cancel_order` | Returns list of open Trade objects |
| `trades()` | `get_order_status` | Returns all Trade objects (open + closed) |
| `cancelOrder()` | `cancel_order` | Cancels a specific order |
| `positions()` | `get_position`, `get_all_positions` | Returns list of Position objects |
| `reqMktData()` | `get_current_price` | Requests market data snapshot |
| `cancelMktData()` | `get_current_price` | Cancels market data subscription |

### ib_async Object Types to Mock (6)

| Type | Key Attributes | Used In |
|------|---------------|---------|
| `AccountValue` | `.tag`, `.value` | `get_account` |
| `Trade` | `.order.orderId`, `.orderStatus.status`, `.orderStatus.avgFillPrice`, `.orderStatus.filled`, `.contract.symbol`, `.order.action`, `.order.totalQuantity`, `.order.orderType` | `place_bracket_order`, `place_market_order`, `get_order_status`, `cancel_order` |
| `Position` | `.contract.symbol`, `.position`, `.avgCost`, `.unrealizedPNL` | `get_position`, `get_all_positions` |
| `Order` | `.orderId`, `.orderType`, `.tif`, `.lmtPrice`, `.action`, `.totalQuantity` | `place_bracket_order` (mutated for MKT) |
| `Stock` | `.symbol`, `.exchange`, `.currency` | `_make_contract` |
| `Ticker` | `.marketPrice()` | `get_current_price` |

## 1.3 Mock Design

The tests must NOT import `ib_async` at all — the library requires an active IB Gateway connection even for import-time setup. All mocking must happen at the module level using `unittest.mock`.

**Mock factory pattern:** Create helper functions that produce mock ib_async objects with the correct attribute structure:

```python
def _mock_trade(order_id=1, ticker="AAPL", status="Filled", avg_price=150.0, filled=10, action="BUY", order_type="MKT", quantity=10):
    """Create a mock Trade object matching ib_async's structure."""
    trade = MagicMock()
    trade.order.orderId = order_id
    trade.order.action = action
    trade.order.orderType = order_type
    trade.order.totalQuantity = quantity
    trade.orderStatus.status = status
    trade.orderStatus.avgFillPrice = avg_price
    trade.orderStatus.filled = filled
    trade.contract.symbol = ticker
    return trade
```

## 1.4 Test Matrix

### Happy Path Tests (10 — one per BrokerAdapter method)

| Test | Method | Verifies |
|------|--------|----------|
| `test_get_account_returns_broker_account` | `get_account` | Parses AccountValue list into BrokerAccount with correct field mapping |
| `test_place_bracket_order_creates_three_orders` | `place_bracket_order` | bracketOrder called, all 3 orders placed, GTC set on all, parent returned as BrokerOrder |
| `test_place_bracket_order_market_when_no_limit` | `place_bracket_order` | When limit_price=None, parent order type changes to MKT |
| `test_place_market_order_buy` | `place_market_order` | MarketOrder created with BUY action, GTC, placed |
| `test_place_market_order_sell` | `place_market_order` | MarketOrder with SELL action |
| `test_place_exit_closes_full_position` | `place_exit` | quantity=0 looks up position, sells all shares |
| `test_cancel_order_finds_and_cancels` | `cancel_order` | Finds matching order in openTrades, cancels it, returns True |
| `test_cancel_order_not_found` | `cancel_order` | No matching order, returns False |
| `test_get_order_status_returns_broker_order` | `get_order_status` | Finds order in trades(), returns correct BrokerOrder |
| `test_get_position_returns_position` | `get_position` | Finds AAPL in positions(), returns BrokerPosition |
| `test_get_position_not_found` | `get_position` | Ticker not in positions(), returns None |
| `test_get_all_positions` | `get_all_positions` | Returns list of BrokerPosition from positions() |
| `test_get_current_price_snapshot` | `get_current_price` | reqMktData snapshot, marketPrice() called, data cancelled |

### Error Handling Tests (8)

| Test | Verifies |
|------|----------|
| `test_ensure_connected_raises_on_failure` | Connection error propagates (not swallowed) |
| `test_ensure_connected_reconnects_after_disconnect` | If isConnected() returns False, reconnects |
| `test_place_bracket_order_connection_lost` | Connection loss during order raises, not silent failure |
| `test_place_exit_no_position_raises` | place_exit with quantity=0 and no position raises ValueError |
| `test_get_order_status_not_found_raises` | Unknown order_id raises ValueError |
| `test_get_current_price_timeout` | reqMktData fails, returns None (not crash) |
| `test_get_account_empty_summary` | accountSummary() returns empty list, falls back to reqAccountSummary |
| `test_get_current_price_zero_price` | marketPrice() returns 0, returns None |

### Edge Case Tests (5)

| Test | Verifies |
|------|----------|
| `test_bracket_order_gtc_on_all_three` | All 3 bracket orders have tif="GTC" |
| `test_position_quantity_is_int` | pos.position (float in IB) cast to int |
| `test_account_values_cast_to_float` | AccountValue.value (string in IB) cast to float |
| `test_order_status_filled_zero` | filled=0 doesn't crash BrokerOrder construction |
| `test_disconnect_when_already_disconnected` | disconnect() is safe to call when not connected |

## 1.5 Shadow Mode Design

### Architecture

Shadow mode runs IB order construction and validation alongside Alpaca execution without submitting orders to IB.

```
Executor: open_shadow_trade() or open_live_trade()
    │
    ├── Alpaca: place order (REAL — paper or live)
    │
    └── IB Shadow: _log_ib_shadow() (LOG ONLY — no submission)
            │
            ├── Connect to IB Gateway (validates connectivity)
            ├── Qualify contract (validates IB knows the ticker)
            ├── Check account (validates buying power)
            ├── Construct bracket order (validates order parameters)
            ├── Log everything to ib_shadow_log table
            └── DO NOT call placeOrder()
```

### Config

```yaml
live_trading:
  ib:
    shadow_mode: true    # Log what IB would do without executing
    host: "127.0.0.1"
    port: 4002           # Paper port
    client_id: 1
```

### Schema: `ib_shadow_log` table

```python
TableDef(
    name="ib_shadow_log",
    description="Shadow log of what IB would have traded alongside Alpaca actuals",
    columns=[
        ColumnDef("shadow_id", "TEXT", nullable=False),
        ColumnDef("created_at", "TEXT", nullable=False),
        ColumnDef("trade_id", "TEXT"),           # Links to shadow_trades
        ColumnDef("ticker", "TEXT", nullable=False),
        ColumnDef("action", "TEXT"),              # BUY/SELL
        ColumnDef("quantity", "INTEGER"),
        ColumnDef("entry_price", "REAL"),         # Alpaca actual fill
        ColumnDef("stop_price", "REAL"),
        ColumnDef("target_price", "REAL"),
        ColumnDef("ib_connected", "INTEGER"),     # 1/0 — was Gateway reachable?
        ColumnDef("ib_contract_valid", "INTEGER"), # 1/0 — did qualifyContracts succeed?
        ColumnDef("ib_buying_power", "REAL"),      # IB account buying power at time
        ColumnDef("ib_would_accept", "INTEGER"),   # 1/0 — would IB have enough BP?
        ColumnDef("ib_order_params", "TEXT"),      # JSON of the bracket order params
        ColumnDef("ib_error", "TEXT"),             # Error message if any step failed
        ColumnDef("alpaca_order_id", "TEXT"),      # Alpaca order ID for comparison
        ColumnDef("alpaca_fill_price", "REAL"),    # Alpaca actual fill price
    ],
    primary_key="shadow_id",
)
```

### Shadow Logger Class

New file: `src/trading/ib_shadow.py` (~120 lines)

```python
class IBShadowLogger:
    """Logs what IB would have done for each Alpaca trade.

    Called by the executor AFTER Alpaca trade completes. Never blocks
    the main trading flow — all exceptions are caught and logged.
    """

    def __init__(self, config: dict):
        self._config = config
        self._broker = None  # Lazy IBBroker instance

    def log_shadow_trade(
        self, trade_id: str, ticker: str, quantity: int,
        entry_price: float, stop_price: float, target_price: float,
        alpaca_order_id: str, alpaca_fill_price: float,
        db_path: str = DB_PATH,
    ) -> None:
        """Log what IB would have done for this trade."""
```

### Executor Integration

In `open_shadow_trade()` and `open_live_trade()`, AFTER the Alpaca order succeeds, add:

```python
# IB Shadow logging (non-blocking)
try:
    if config.get("live_trading", {}).get("ib", {}).get("shadow_mode"):
        from src.trading.ib_shadow import IBShadowLogger
        shadow = IBShadowLogger(config)
        shadow.log_shadow_trade(
            trade_id=trade_id, ticker=ticker, quantity=shares,
            entry_price=entry_price, stop_price=stop_price,
            target_price=target_1, alpaca_order_id=alpaca_order_id,
            alpaca_fill_price=actual_fill_price,
        )
except Exception as e:
    logger.warning("[SHADOW-IB] Shadow logging failed (non-fatal): %s", e)
```

**Critical:** The shadow logging is wrapped in try/except at the executor level. If IB Gateway is down, the shadow log records `ib_connected=0` but Alpaca trading continues unaffected.

### What Shadow Mode Does NOT Do

- Does NOT submit orders to IB
- Does NOT block Alpaca execution in any path
- Does NOT modify the risk governor or any trade parameters
- Does NOT affect the training pipeline or any analytics
- Does NOT require IB Gateway to be running (gracefully handles disconnection)

## 1.6 Risks

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Mock structure doesn't match real ib_async | Medium | Medium | Document every mock attribute against ib_async source. Run integration test with real Gateway separately. |
| Shadow logger crashes executor | Low | Critical | All shadow calls wrapped in try/except at executor level. Shadow failures are warnings, never errors. |
| IB Gateway consumes a connection slot | Low | Low | Shadow mode uses one client_id. IB allows 8 concurrent. |
| Shadow data diverges from what live IB would do | Medium | Low | Shadow validates contract + BP but can't verify fill quality. Acknowledged limitation — fill comparison requires live execution. |
| Tests pass but real IB behavior differs | Medium | Medium | Tests validate our code's logic, not IB's behavior. Integration testing with real Gateway is a separate manual step. |

## 1.7 Success Criteria

1. ≥23 new tests for IBBroker (10 happy path + 8 error + 5 edge case)
2. All tests pass without ib_async installed (pure mock tests)
3. Shadow mode logs to `ib_shadow_log` for every Alpaca trade when enabled
4. Shadow mode never blocks or crashes Alpaca execution
5. `ib_shadow_log` schema registered and migrated via `validate-schema --fix`
6. Existing tests unchanged and still passing
7. No file exceeds 400 lines

---

# PART 2: IMPLEMENTATION PLAN

## 2.1 File Map

| File | Action | Lines (before → after) |
|------|--------|----------------------|
| `tests/test_ib_broker.py` | CREATE | 0 → ~350 |
| `src/trading/ib_shadow.py` | CREATE | 0 → ~140 |
| `src/schema/registry.py` | MODIFY | Add `ib_shadow_log` table (~15 lines) |
| `src/shadow_trading/executor.py` | MODIFY | Add shadow hook (~10 lines in 2 locations) |
| `tests/test_ib_shadow.py` | CREATE | 0 → ~120 |
| `CHANGELOG.md` | MODIFY | Add entry |
| `MASTER.md` | MODIFY | Update sprint queue |

**Files NOT modified:** `src/trading/ib_broker.py`, `src/trading/broker_factory.py`, `src/trading/broker_interface.py`, `src/trading/alpaca_broker.py`. The existing IB implementation is correct — we're adding tests and shadow mode, not changing production code.

## 2.2 Mock Structure Reference

CC must use these exact mock structures. Getting them wrong means tests pass but don't validate real behavior.

```python
# === AccountValue mock ===
# IB returns a list of these from accountSummary()
def _mock_account_value(tag, value):
    av = MagicMock()
    av.tag = tag
    av.value = str(value)  # IB returns STRING values
    return av

# Typical account summary:
mock_summary = [
    _mock_account_value("NetLiquidation", "100000.00"),
    _mock_account_value("TotalCashValue", "85000.00"),
    _mock_account_value("BuyingPower", "200000.00"),
    _mock_account_value("GrossPositionValue", "15000.00"),
]

# === Trade mock ===
# IB returns these from placeOrder(), trades(), openTrades()
def _mock_trade(order_id=1, ticker="AAPL", status="Filled",
                avg_price=150.0, filled=10, action="BUY",
                order_type="MKT", quantity=10):
    trade = MagicMock()
    trade.order.orderId = order_id
    trade.order.action = action
    trade.order.orderType = order_type
    trade.order.totalQuantity = quantity
    trade.orderStatus.status = status
    trade.orderStatus.avgFillPrice = avg_price
    trade.orderStatus.filled = filled
    trade.contract.symbol = ticker
    return trade

# === Position mock ===
# IB returns these from positions()
def _mock_position(ticker="AAPL", quantity=100, avg_cost=150.0, pnl=500.0):
    pos = MagicMock()
    pos.contract.symbol = ticker
    pos.position = float(quantity)  # IB returns FLOAT, not int
    pos.avgCost = avg_cost
    pos.unrealizedPNL = pnl
    return pos

# === Bracket order mock ===
# IB's bracketOrder() returns a list of 3 Order objects
def _mock_bracket_orders():
    parent = MagicMock()
    parent.orderType = "LMT"
    parent.tif = "DAY"  # IBBroker should change to GTC
    parent.lmtPrice = 150.0

    take_profit = MagicMock()
    take_profit.tif = "DAY"

    stop_loss = MagicMock()
    stop_loss.tif = "DAY"

    return [parent, take_profit, stop_loss]

# === Ticker (market data) mock ===
def _mock_ticker(price=155.0):
    ticker = MagicMock()
    ticker.marketPrice.return_value = price
    return ticker

# === Stock contract mock ===
def _mock_contract(symbol="AAPL"):
    contract = MagicMock()
    contract.symbol = symbol
    contract.exchange = "SMART"
    contract.currency = "USD"
    return contract
```

## 2.3 Test Organization

`tests/test_ib_broker.py` — organized by method, each class tests one BrokerAdapter method:

```
TestIBGetAccount (3 tests)
  - test_get_account_parses_summary
  - test_get_account_empty_falls_back_to_req
  - test_get_account_values_cast_from_string

TestIBPlaceBracketOrder (4 tests)
  - test_bracket_creates_three_orders
  - test_bracket_market_when_no_limit
  - test_bracket_all_gtc
  - test_bracket_connection_lost_raises

TestIBPlaceMarketOrder (2 tests)
  - test_market_buy
  - test_market_sell

TestIBPlaceExit (2 tests)
  - test_exit_closes_full_position
  - test_exit_no_position_raises

TestIBCancelOrder (2 tests)
  - test_cancel_finds_and_cancels
  - test_cancel_not_found_returns_false

TestIBGetOrderStatus (2 tests)
  - test_status_found
  - test_status_not_found_raises

TestIBGetPosition (3 tests)
  - test_position_found
  - test_position_not_found
  - test_position_quantity_cast_to_int

TestIBGetAllPositions (1 test)
  - test_returns_list

TestIBGetCurrentPrice (3 tests)
  - test_price_snapshot
  - test_price_timeout_returns_none
  - test_price_zero_returns_none

TestIBConnection (2 tests)
  - test_reconnects_when_disconnected
  - test_disconnect_safe_when_not_connected
```

**Total: 24 tests**

## 2.4 Shadow Mode Testing

`tests/test_ib_shadow.py`:

```
TestIBShadowLogger (6 tests)
  - test_logs_shadow_trade_when_connected
  - test_logs_with_ib_disconnected
  - test_contract_invalid_logged
  - test_insufficient_buying_power_logged
  - test_never_calls_place_order
  - test_exception_does_not_propagate
```

## 2.5 Executor Integration Testing

Add to existing `tests/test_live_trading.py` or `tests/test_bracket_safety.py`:

```
TestIBShadowIntegration (2 tests)
  - test_shadow_hook_called_when_enabled
  - test_shadow_hook_skipped_when_disabled
```

---

# PART 3: SPRINT PROMPT

> **Branch:** `feat/ib-tests-shadow`
> **Priority:** HIGH — blocks IB paper validation
> **Estimated CC time:** 6–8 hours
> **Closes:** GitHub Issue #368
>
> **Pre-flight:**
> ```bash
> git checkout main && git pull origin main
> git checkout -b feat/ib-tests-shadow
> python -m pytest tests/ -x -q --ignore=tests/test_ingestion.py
> wc -l src/trading/ib_broker.py  # should be 271
> ```
>
> **CRITICAL RULE:** Do NOT modify `src/trading/ib_broker.py`. The existing
> implementation is correct. This sprint adds tests and shadow mode alongside
> the existing code. If a test reveals a bug in ib_broker.py, document it in
> a comment but do NOT fix it in this sprint — file a separate issue.

---

## Task 1: Create IB mock helpers

**File:** Create `tests/conftest_ib.py` (~80 lines)

Create reusable mock factories for all 6 ib_async object types. These are imported by test files — they are NOT fixtures, they are plain functions.

```python
"""Mock factories for ib_async objects used in IBBroker tests.

These create MagicMock objects with the exact attribute structure that
ib_async returns from its API calls. Getting these wrong means tests
pass but don't validate real IB behavior.

Reference: ib_async source (Trade, OrderStatus, Position, AccountValue, Stock)
Cross-checked against src/trading/ib_broker.py attribute access patterns.
"""
from unittest.mock import MagicMock


def mock_account_value(tag: str, value: str) -> MagicMock:
    """Mock ib_async AccountValue. IB returns STRING values for everything."""
    av = MagicMock()
    av.tag = tag
    av.value = str(value)
    return av


def mock_trade(
    order_id: int = 1, ticker: str = "AAPL", status: str = "Filled",
    avg_price: float = 150.0, filled: int = 10, action: str = "BUY",
    order_type: str = "MKT", quantity: int = 10,
) -> MagicMock:
    """Mock ib_async Trade. Used by placeOrder, trades, openTrades."""
    trade = MagicMock()
    trade.order.orderId = order_id
    trade.order.action = action
    trade.order.orderType = order_type
    trade.order.totalQuantity = quantity
    trade.orderStatus.status = status
    trade.orderStatus.avgFillPrice = avg_price
    trade.orderStatus.filled = filled
    trade.contract.symbol = ticker
    return trade


def mock_position(
    ticker: str = "AAPL", quantity: float = 100.0,
    avg_cost: float = 150.0, pnl: float = 500.0,
) -> MagicMock:
    """Mock ib_async Position. Note: position is FLOAT in IB, cast to int in our code."""
    pos = MagicMock()
    pos.contract.symbol = ticker
    pos.position = quantity  # Float in IB
    pos.avgCost = avg_cost
    pos.unrealizedPNL = pnl
    return pos


def mock_bracket_orders() -> list[MagicMock]:
    """Mock ib_async bracketOrder() return: [parent, take_profit, stop_loss]."""
    orders = []
    for i in range(3):
        order = MagicMock()
        order.orderType = "LMT" if i == 0 else ("LMT" if i == 1 else "STP")
        order.tif = "DAY"  # IBBroker should override to GTC
        order.lmtPrice = 150.0
        orders.append(order)
    return orders


def mock_ticker_data(price: float = 155.0) -> MagicMock:
    """Mock ib_async Ticker from reqMktData snapshot."""
    ticker = MagicMock()
    ticker.marketPrice.return_value = price
    return ticker


def mock_account_summary() -> list[MagicMock]:
    """Standard mock account summary with all fields IBBroker reads."""
    return [
        mock_account_value("NetLiquidation", "100000.00"),
        mock_account_value("TotalCashValue", "85000.00"),
        mock_account_value("BuyingPower", "200000.00"),
        mock_account_value("GrossPositionValue", "15000.00"),
    ]
```

**Commit:** `test(ib): mock factories for all 6 ib_async object types`

---

## Task 2: Write IBBroker unit tests

**File:** Create `tests/test_ib_broker.py` (~350 lines)

**IMPORTANT:** Every test must patch `ib_async` imports inside `src/trading/ib_broker`. The IBBroker constructor does NOT import ib_async — the imports are deferred to method calls (`_ensure_connected`, `_make_contract`, `place_market_order`). Mock them at the point of import:

```python
@patch("src.trading.ib_broker.IBBroker._ensure_connected")
def test_example(self, mock_connect):
    broker = IBBroker(port=4002)
    broker._ib = MagicMock()  # Inject mock IB client
    # ... test the method
```

### Test Classes (implement ALL of these):

**TestIBGetAccount** — 3 tests:

```python
def test_get_account_parses_summary(self):
    """accountSummary() values correctly mapped to BrokerAccount fields."""
    # broker._ib.accountSummary.return_value = mock_account_summary()
    # Verify: equity=100000, cash=85000, buying_power=200000, broker="ib"

def test_get_account_empty_falls_back(self):
    """Empty accountSummary() triggers reqAccountSummary + sleep + retry."""
    # First call returns []. After reqAccountSummary + sleep, returns data.
    # Verify reqAccountSummary was called, sleep(2) was called.

def test_get_account_values_cast_from_string(self):
    """IB returns values as strings. Verify float() conversion."""
    # Use mock_account_value("NetLiquidation", "99999.99")
    # Verify acct.equity == 99999.99 (not string)
```

**TestIBPlaceBracketOrder** — 4 tests:

```python
def test_bracket_creates_three_orders(self):
    """bracketOrder() produces 3 orders, all submitted via placeOrder()."""
    # broker._ib.bracketOrder.return_value = mock_bracket_orders()
    # broker._ib.placeOrder.return_value = mock_trade(...)
    # Verify placeOrder called 3 times
    # Verify returned BrokerOrder has order_type="bracket"

def test_bracket_market_when_no_limit(self):
    """No limit_price → parent order type changed to MKT, lmtPrice=0."""
    # Call with limit_price=None
    # Verify bracket[0].orderType was set to "MKT"
    # Verify bracket[0].lmtPrice was set to 0

def test_bracket_all_gtc(self):
    """All 3 bracket orders must have tif='GTC'."""
    # Verify bracket[0].tif, bracket[1].tif, bracket[2].tif all set to "GTC"

def test_bracket_connection_lost_raises(self):
    """Connection failure during bracket order propagates exception."""
    # broker._ib.placeOrder.side_effect = ConnectionError("Lost connection")
    # Verify exception propagates (not swallowed)
```

**TestIBPlaceMarketOrder** — 2 tests:

```python
def test_market_buy(self):
    """Market buy creates MarketOrder with BUY action."""
    # Patch "src.trading.ib_broker.MarketOrder" import
    # Verify action="BUY", tif="GTC"
    # Verify returned BrokerOrder has side="buy"

def test_market_sell(self):
    """Market sell creates MarketOrder with SELL action."""
    # Verify action="SELL", returned order has side="sell"
```

**TestIBPlaceExit** — 2 tests:

```python
def test_exit_closes_full_position(self):
    """quantity=0 looks up position, sells all shares."""
    # broker._ib.positions.return_value = [mock_position("AAPL", 50)]
    # Call place_exit("AAPL", 0)
    # Verify place_market_order called with quantity=50, side="sell"

def test_exit_no_position_raises(self):
    """quantity=0 with no position raises ValueError."""
    # broker._ib.positions.return_value = []
    # Verify ValueError raised with "No position in AAPL"
```

**TestIBCancelOrder** — 2 tests:

```python
def test_cancel_finds_and_cancels(self):
    """Matching order in openTrades() gets cancelled, returns True."""
    # broker._ib.openTrades.return_value = [mock_trade(order_id=42)]
    # Verify cancelOrder called with the matching order
    # Verify returns True

def test_cancel_not_found_returns_false(self):
    """No matching order returns False without error."""
    # broker._ib.openTrades.return_value = [mock_trade(order_id=99)]
    # Call cancel_order("42")
    # Verify returns False, cancelOrder NOT called
```

**TestIBGetOrderStatus** — 2 tests:

```python
def test_status_found(self):
    """Matching order in trades() returns BrokerOrder with correct fields."""
    # broker._ib.trades.return_value = [mock_trade(order_id=42, status="Filled")]
    # Verify all BrokerOrder fields mapped correctly

def test_status_not_found_raises(self):
    """Unknown order_id raises ValueError."""
    # broker._ib.trades.return_value = []
    # Verify ValueError("Order 42 not found")
```

**TestIBGetPosition** — 3 tests:

```python
def test_position_found(self):
    """Ticker found in positions() returns BrokerPosition."""
    # Verify BrokerPosition fields correct, broker="ib"

def test_position_not_found(self):
    """Ticker not in positions() returns None."""

def test_position_quantity_cast_to_int(self):
    """IB returns position as float (100.0). Verify int conversion."""
    # mock_position(quantity=100.0)
    # Verify pos.quantity == 100 (int, not float)
```

**TestIBGetAllPositions** — 1 test:

```python
def test_returns_list(self):
    """Multiple positions returned as list of BrokerPosition."""
    # 3 positions: AAPL, MSFT, GOOG
    # Verify len == 3, all have broker="ib"
```

**TestIBGetCurrentPrice** — 3 tests:

```python
def test_price_snapshot(self):
    """Snapshot mode: reqMktData → sleep(3) → marketPrice() → cancelMktData."""
    # Verify call sequence: qualifyContracts, reqMktData(snapshot=True),
    # sleep(3), marketPrice(), cancelMktData
    # Verify returns the price as float

def test_price_timeout_returns_none(self):
    """reqMktData raises exception → returns None (not crash)."""
    # broker._ib.reqMktData.side_effect = TimeoutError
    # Verify returns None

def test_price_zero_returns_none(self):
    """marketPrice() returns 0 → returns None (invalid price)."""
    # mock_ticker_data(price=0.0)
    # Verify returns None
```

**TestIBConnection** — 2 tests:

```python
def test_reconnects_when_disconnected(self):
    """isConnected()=False triggers new connect()."""
    # broker._ib = MagicMock()
    # broker._ib.isConnected.return_value = False
    # Call _ensure_connected
    # Verify new IB() created and connect() called

def test_disconnect_safe_when_not_connected(self):
    """disconnect() when _ib is None doesn't crash."""
    # Already tested in existing tests — verify it's still there
```

**Run:**
```bash
python -m pytest tests/test_ib_broker.py -v
```

**Commit:** `test(ib): 24 unit tests for IBBroker — all 10 BrokerAdapter methods + errors + edges`

---

## Task 3: Add ib_shadow_log schema

**File:** `src/schema/registry.py`

Add after the existing `shadow_trades` table definition:

```python
_register(TableDef(
    name="ib_shadow_log",
    description="Shadow log of what IB would have traded alongside Alpaca actuals",
    columns=[
        ColumnDef("shadow_id", "TEXT", nullable=False),
        ColumnDef("created_at", "TEXT", nullable=False),
        ColumnDef("trade_id", "TEXT"),
        ColumnDef("ticker", "TEXT", nullable=False),
        ColumnDef("action", "TEXT"),
        ColumnDef("quantity", "INTEGER"),
        ColumnDef("entry_price", "REAL"),
        ColumnDef("stop_price", "REAL"),
        ColumnDef("target_price", "REAL"),
        ColumnDef("ib_connected", "INTEGER", default="0"),
        ColumnDef("ib_contract_valid", "INTEGER", default="0"),
        ColumnDef("ib_buying_power", "REAL"),
        ColumnDef("ib_would_accept", "INTEGER", default="0"),
        ColumnDef("ib_order_params", "TEXT"),
        ColumnDef("ib_error", "TEXT"),
        ColumnDef("alpaca_order_id", "TEXT"),
        ColumnDef("alpaca_fill_price", "REAL"),
    ],
    primary_key="shadow_id",
    indexes=[
        IndexDef("idx_ib_shadow_created_at", ["created_at"]),
        IndexDef("idx_ib_shadow_trade_id", ["trade_id"]),
    ],
))
```

**Commit:** `schema: add ib_shadow_log table for IB shadow mode comparison data`

---

## Task 4: Create IB shadow logger

**File:** Create `src/trading/ib_shadow.py` (~140 lines)

```python
"""IB Shadow Logger — logs what IB would have done for each Alpaca trade.

Called by: shadow_trading.executor (post-trade hook)
Calls: trading.ib_broker, schema.registry
Owns tables: ib_shadow_log
Config keys: live_trading.ib.shadow_mode
Tests: tests/test_ib_shadow.py

Shadow mode connects to IB Gateway and validates each trade's parameters
(contract, buying power, order structure) without submitting orders.
If Gateway is down, logs ib_connected=0 and continues.

CRITICAL: This module must NEVER:
  - Call placeOrder() on the IB client
  - Block Alpaca execution in any code path
  - Raise exceptions that propagate to the executor
"""

import json
import logging
import sqlite3
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

from src.config import DB_PATH

logger = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")


class IBShadowLogger:
    """Non-blocking shadow logger for IB trade comparison."""

    def __init__(self, config: dict):
        self._config = config
        self._broker = None

    def _get_broker(self):
        """Lazy init IB broker for shadow validation."""
        if self._broker is None:
            try:
                from src.trading.ib_broker import IBBroker
                ib_cfg = self._config.get("live_trading", {}).get("ib", {})
                self._broker = IBBroker(
                    host=ib_cfg.get("host", "127.0.0.1"),
                    port=ib_cfg.get("port", 4002),
                    client_id=ib_cfg.get("client_id", 1) + 10,  # Offset to avoid conflicts
                    timeout=ib_cfg.get("timeout", 5),
                )
            except Exception as e:
                logger.debug("[IB-SHADOW] Failed to create IBBroker: %s", e)
        return self._broker

    def log_shadow_trade(
        self,
        trade_id: str,
        ticker: str,
        quantity: int,
        entry_price: float,
        stop_price: float,
        target_price: float,
        alpaca_order_id: str = "",
        alpaca_fill_price: float = 0.0,
        db_path: str = DB_PATH,
    ) -> None:
        """Log what IB would have done for this trade.

        Steps:
        1. Connect to IB Gateway (or log failure)
        2. Validate contract (qualifyContracts)
        3. Check buying power
        4. Construct bracket order params (without submitting)
        5. Store everything in ib_shadow_log
        """
        shadow_id = str(uuid.uuid4())
        created_at = datetime.now(ET).isoformat()
        ib_connected = 0
        ib_contract_valid = 0
        ib_buying_power = None
        ib_would_accept = 0
        ib_order_params = None
        ib_error = None

        try:
            broker = self._get_broker()
            if broker is None:
                ib_error = "IBBroker creation failed"
            else:
                # Step 1: Check connection
                try:
                    broker._ensure_connected()
                    ib_connected = 1
                except Exception as e:
                    ib_error = f"Connection failed: {e}"

                if ib_connected:
                    # Step 2: Validate contract
                    try:
                        contract = broker._make_contract(ticker)
                        broker._ib.qualifyContracts(contract)
                        ib_contract_valid = 1
                    except Exception as e:
                        ib_error = f"Contract invalid: {e}"

                    # Step 3: Check buying power
                    try:
                        acct = broker.get_account()
                        ib_buying_power = acct.buying_power
                        required = entry_price * quantity
                        ib_would_accept = 1 if ib_buying_power >= required else 0
                    except Exception as e:
                        ib_error = (ib_error or "") + f" | Account check failed: {e}"

                    # Step 4: Construct order params (DO NOT SUBMIT)
                    ib_order_params = json.dumps({
                        "action": "BUY",
                        "quantity": quantity,
                        "take_profit": round(target_price, 2),
                        "stop_loss": round(stop_price, 2),
                        "order_type": "MKT",
                        "tif": "GTC",
                    })

        except Exception as e:
            ib_error = f"Shadow logging error: {e}"
            logger.warning("[IB-SHADOW] Unexpected error: %s", e)

        # Step 5: Store to database (always, even on failure)
        try:
            with sqlite3.connect(db_path) as conn:
                conn.execute(
                    """INSERT INTO ib_shadow_log
                       (shadow_id, created_at, trade_id, ticker, action, quantity,
                        entry_price, stop_price, target_price, ib_connected,
                        ib_contract_valid, ib_buying_power, ib_would_accept,
                        ib_order_params, ib_error, alpaca_order_id, alpaca_fill_price)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (shadow_id, created_at, trade_id, ticker, "BUY", quantity,
                     entry_price, stop_price, target_price, ib_connected,
                     ib_contract_valid, ib_buying_power, ib_would_accept,
                     ib_order_params, ib_error, alpaca_order_id, alpaca_fill_price),
                )
                conn.commit()
            logger.info("[IB-SHADOW] Logged shadow trade for %s: connected=%d, valid=%d, accept=%d",
                        ticker, ib_connected, ib_contract_valid, ib_would_accept)
        except Exception as e:
            logger.warning("[IB-SHADOW] Failed to write shadow log: %s", e)
```

**Commit:** `feat(ib_shadow): shadow logger — validates IB trades without executing`

---

## Task 5: Write shadow mode tests

**File:** Create `tests/test_ib_shadow.py` (~120 lines)

```python
"""Tests for IB Shadow Logger.

All tests use mocks — no IB Gateway required.
Verifies: logging, error handling, non-blocking behavior, never places orders.
"""
```

**6 tests:**

```python
def test_logs_shadow_trade_when_connected(self, tmp_db):
    """Full happy path: connected, contract valid, BP sufficient → logged."""
    # Mock IBBroker: connected, qualifyContracts succeeds, get_account returns BP
    # Verify: row in ib_shadow_log with ib_connected=1, ib_contract_valid=1, ib_would_accept=1

def test_logs_with_ib_disconnected(self, tmp_db):
    """Gateway down → ib_connected=0, still logs to DB."""
    # Mock _ensure_connected to raise ConnectionError
    # Verify: row logged with ib_connected=0, ib_error contains "Connection failed"

def test_contract_invalid_logged(self, tmp_db):
    """Unknown ticker → ib_contract_valid=0, still logs."""
    # Mock qualifyContracts to raise
    # Verify: ib_contract_valid=0

def test_insufficient_buying_power_logged(self, tmp_db):
    """Low BP → ib_would_accept=0."""
    # Mock get_account returning BP=$100, trade requires $15,000
    # Verify: ib_would_accept=0

def test_never_calls_place_order(self, tmp_db):
    """Shadow mode must NEVER call placeOrder."""
    # Run log_shadow_trade
    # Verify: broker._ib.placeOrder.assert_not_called()

def test_exception_does_not_propagate(self, tmp_db):
    """Any exception in shadow logging must not propagate."""
    # Mock everything to raise
    # Verify: no exception raised, warning logged
```

Each test should create a temporary SQLite DB with the `ib_shadow_log` table schema.

**Commit:** `test(ib_shadow): 6 tests — logging, error handling, never-execute guarantee`

---

## Task 6: Add executor shadow hook

**File:** `src/shadow_trading/executor.py`

Add the shadow hook in TWO locations:

**Location 1:** In `open_shadow_trade()`, after the Alpaca paper order succeeds (~line 400, after the trade is inserted into DB):

```python
# IB Shadow logging — non-blocking comparison data
try:
    ib_shadow_cfg = config.get("live_trading", {}).get("ib", {})
    if ib_shadow_cfg.get("shadow_mode"):
        from src.trading.ib_shadow import IBShadowLogger
        _ib_shadow = IBShadowLogger(config)
        _ib_shadow.log_shadow_trade(
            trade_id=trade_id, ticker=ticker, quantity=shares,
            entry_price=float(entry_price), stop_price=float(stop_price),
            target_price=float(target_1),
            alpaca_order_id=str(alpaca_oid or ""),
            alpaca_fill_price=float(actual_entry or entry_price),
        )
except Exception as e:
    logger.warning("[SHADOW-IB] Shadow logging failed (non-fatal): %s", e)
```

**Location 2:** In `open_live_trade()`, after the live Alpaca order succeeds (~line 1550, similar location):

Same code block as above.

**Do NOT add shadow hooks to exit paths** — shadow mode only compares entry behavior. Exit comparison requires live IB execution.

**Commit:** `feat(executor): IB shadow hook — log comparison data after Alpaca trades`

---

## Task 7: Add executor shadow integration tests

**File:** Add to `tests/test_live_trading.py` (2 new tests):

```python
class TestIBShadowIntegration:
    @patch("src.trading.ib_shadow.IBShadowLogger")
    def test_shadow_hook_called_when_enabled(self, MockShadow, ...):
        """When ib.shadow_mode=true, shadow logger is invoked after paper trade."""
        # Configure live_config with ib.shadow_mode: true
        # Execute open_shadow_trade
        # Verify MockShadow().log_shadow_trade.assert_called_once()

    def test_shadow_hook_skipped_when_disabled(self, ...):
        """When ib.shadow_mode not set, no shadow logging."""
        # Configure without shadow_mode
        # Verify IBShadowLogger never imported/called
```

**Commit:** `test(executor): IB shadow integration — hook called when enabled, skipped when not`

---

## Task 8: Documentation

**Files:**
- `CHANGELOG.md` — Add entry
- `MASTER.md` — Update IB status, note shadow mode ready
- Close GitHub Issue #368

**Commit:** `docs: IB test coverage + shadow mode — closes #368`

---

## Verification Checklist

```bash
# All existing tests still pass
python -m pytest tests/ -x -q --ignore=tests/test_ingestion.py

# New IB tests pass (ALL of them)
python -m pytest tests/test_ib_broker.py tests/test_ib_shadow.py -v

# Total new tests: ~32 (24 IB broker + 6 shadow + 2 integration)
python -m pytest tests/test_ib_broker.py tests/test_ib_shadow.py -v --tb=short | tail -5

# File sizes
wc -l src/trading/ib_shadow.py       # should be ~140
wc -l tests/test_ib_broker.py        # should be ~350
wc -l tests/test_ib_shadow.py        # should be ~120
wc -l tests/conftest_ib.py           # should be ~80

# ib_broker.py is UNCHANGED
git diff src/trading/ib_broker.py     # should be empty

# No placeOrder in shadow code
grep -rn "placeOrder" src/trading/ib_shadow.py  # should return nothing

# Frontend builds (schema change may affect API)
cd frontend && npm run build && cd ..
```

**Push:**
```bash
git push origin feat/ib-tests-shadow
```

---

## Ralph Loop Findings

### Spec (3 passes):

**Pass 1:** The mock structure for `bracketOrder()` was initially wrong — IB returns 3 Order objects, not Trade objects. Fixed: mocks return Order mocks that get passed to `placeOrder()` which returns Trade mocks. Two different object types in the same flow.

**Pass 2:** Shadow mode client_id must differ from the main IB client_id to avoid connection conflicts. IB Gateway rejects two connections with the same client_id. Fixed: shadow uses `client_id + 10` offset.

**Pass 3:** The `get_current_price` test needed to verify the SEQUENCE of calls (qualifyContracts → reqMktData(snapshot=True) → sleep(3) → marketPrice → cancelMktData). Order matters because calling marketPrice before sleep returns stale data.

### Implementation Plan (3 passes):

**Pass 1:** Tests must NOT import ib_async at all — even `import ib_async` can fail if the library isn't installed. All tests use `unittest.mock` exclusively. The `@pytest.mark.skipif(not _HAS_IB_ASYNC)` pattern in the existing tests is wrong for unit tests — unit tests should always run. Only integration tests should skip.

**Pass 2:** The executor hook locations needed precise specification. `open_shadow_trade` handles paper trades, `open_live_trade` handles live trades. Both need the hook because shadow mode compares IB against BOTH paper and live Alpaca paths.

**Pass 3:** The `ib_shadow_log` table should NOT be synced to Postgres — it's local diagnostic data, not analytics. Omit `sync_to_postgres=True`.

### Sprint Prompt (3 passes):

**Pass 1:** Added explicit rule: "Do NOT modify ib_broker.py." CC has a pattern of "fixing" things it finds during testing. IB broker changes need separate review — they could break production.

**Pass 2:** The shadow hook must use `float()` casts on all parameters from the executor — the type coercion fix (#383) showed that shadow_trades columns can still contain strings in existing rows.

**Pass 3:** Added "never calls placeOrder" as an explicit test (`test_never_calls_place_order`) — this is the single most important safety property of shadow mode and must have a dedicated test, not just implicit verification.
