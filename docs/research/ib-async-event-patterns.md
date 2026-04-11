# Event-driven order fills in ib_async for polling-based trading systems

**ib_async's event system will update Trade objects automatically—but only while the asyncio event loop is spinning.** For a synchronous application polling every 15–30 minutes with `time.sleep()` between cycles, messages accumulate in the TCP buffer unprocessed, and trade state goes stale. The safest production pattern for long polling intervals is to **connect fresh each cycle**, reconstruct bracket order state from the server, and disconnect when done. If you prefer a persistent connection, replace every `time.sleep()` with `ib.sleep()` to keep the event loop alive between polls. Below is a complete technical breakdown of the event system internals, bracket order mechanics, known pitfalls, and production-ready code patterns.

---

## How the three order-fill events differ and which fires first

ib_async provides events at two levels: **IB-global events** (on the `IB` instance) and **Trade-level events** (on each `Trade` object returned by `placeOrder()`). The three key fill-related events have distinct semantics:

| Event | Level | Signature | When it fires |
|-------|-------|-----------|---------------|
| `ib.orderStatusEvent` | Global | `callback(trade: Trade)` | Every status change for any order |
| `trade.statusEvent` | Per-trade | `callback(trade: Trade)` | Every status change for that specific order |
| `trade.filledEvent` | Per-trade | `callback(trade: Trade)` | **Once**, only when status transitions to `Filled` |
| `trade.fillEvent` | Per-trade | `callback(trade: Trade, fill: Fill)` | Each partial or full execution |

The internal `wrapper.py` processes the TWS `orderStatus` callback and fires events in this sequence: **`trade.statusEvent` → `ib.orderStatusEvent` → `trade.filledEvent`** (if status became `Filled`). Separately, execution reports arrive via the `execDetails` callback, which fires `trade.fillEvent` and `ib.execDetailsEvent` with the `Fill` object containing price, quantity, and execution ID. Commission data follows via `commissionReport`, firing `trade.commissionReportEvent`.

The critical distinction: **`fillEvent` fires on every partial fill** with execution details, while **`filledEvent` fires exactly once** when the order reaches terminal `Filled` status. For a market order that fills instantly in one shot, both fire; for a limit order that fills in three tranches, `fillEvent` fires three times but `filledEvent` fires only once at the end.

```python
# Monitoring both partial and complete fills
def on_each_fill(trade, fill):
    print(f"Partial: {fill.execution.shares} @ {fill.execution.price}")

def on_fully_filled(trade):
    print(f"Complete: avg {trade.orderStatus.avgFillPrice}")

trade = ib.placeOrder(contract, order)
trade.fillEvent += on_each_fill      # every execution
trade.filledEvent += on_fully_filled  # once, when done
```

## The Event class internals and the += operator

ib_async delegates its event system to the `aeventkit` library (a fork of the original `eventkit`). The `Event` class stores listeners in a `_slots` list as `[obj, weakref, func]` tuples. The `+=` operator is aliased to `connect()`, and calling the event object directly triggers `emit()`:

```python
# Internally:
__iadd__ = connect      # event += handler
__isub__ = disconnect   # event -= handler
__call__ = emit         # event(args) fires all handlers
```

**Weak references are the default.** When you write `trade.filledEvent += self.on_filled`, eventkit stores a weak reference to `self`. If `self` gets garbage collected, the handler silently disappears. This is the root cause of GitHub issue erdewit/ib_insync#72, where handlers on bound methods vanished. The fix: keep a strong reference to any object whose methods serve as event handlers, or pass `keep_ref=True` to `connect()` explicitly.

When `emit()` fires, it iterates `_slots` synchronously and calls each handler. If a handler is a coroutine function, it's scheduled via `asyncio.ensure_future()`. **Handler exceptions are caught and routed to the event's `error_event`**, not propagated to the caller—bugs in handlers can be silently swallowed (ib_async Discussion #26). Always wrap handler logic in try/except with explicit logging.

## There is no race condition between placeOrder() and handler attachment

A common concern is whether a fast market order can fill before you attach handlers to the returned `Trade`. The answer: **no race condition exists** because `placeOrder()` only sends the message over the TCP socket and returns immediately. The fill response from TWS can only be processed when the asyncio event loop next spins (during `ib.sleep()`, `ib.run()`, or `ib.waitOnUpdate()`). Since event handlers are attached synchronously before the loop resumes, they are guaranteed to be in place before any callbacks fire:

```python
trade = ib.placeOrder(contract, order)  # sends message, returns immediately
trade.filledEvent += on_filled          # safe—loop hasn't spun yet
ib.sleep(0)  # NOW the loop processes TWS response and handler fires
```

However, if you use **IB-level events** (`ib.orderStatusEvent`), attach them *before* calling `placeOrder()`, since the global event fires for all orders and you want it registered before any processing.

---

## Using ib_async events in synchronous polling applications

### ib.sleep() is the event loop pump

ib_async's "synchronous" API is a facade over asyncio. Every blocking method—`ib.sleep()`, `ib.connect()`, `ib.reqHistoricalData()`—internally calls `util.run()`, which executes `loop.run_until_complete()` on an asyncio coroutine. **`ib.sleep(secs)` is not just a delay; it runs the event loop for `secs` seconds**, processing all incoming TWS messages, firing callbacks, and updating Trade objects.

- **`ib.sleep(0)`** drains all currently queued messages and returns immediately. Use it to flush pending updates at the start of a poll cycle.
- **`ib.sleep(N)`** runs the event loop for N seconds, processing messages as they arrive.
- **`ib.waitOnUpdate(timeout)`** blocks until TWS sends any data update (or timeout expires). Returns `True` if an update arrived, `False` on timeout.

The difference: `sleep(5)` always waits 5 seconds; `waitOnUpdate(5)` returns as soon as the first update arrives, or after 5 seconds if nothing comes.

### What happens during 15–30 minute gaps with time.sleep()

If your application calls `time.sleep(900)` between poll cycles while the IB connection remains open, **the asyncio event loop stops entirely**. TCP data from TWS accumulates in the OS socket buffer. Messages are not lost at the network level—they're buffered—but they are not processed by ib_async's decoder, so:

- **Trade objects remain stale.** `trade.orderStatus.status` reflects whatever was last processed.
- **Events do not fire.** Handler callbacks sit idle.
- **When you finally call `ib.sleep(0)`**, all buffered messages get processed in a burst—events fire for fills that happened 20 minutes ago.
- **Risk of socket buffer overflow or TCP timeout.** While localhost connections rarely time out, the socket buffer has finite capacity. If TWS sends enough market data or account updates during 15 minutes, the buffer could fill, and TWS may drop the connection.

The official documentation warns: *"If user code spends much time in a calculation, or uses time.sleep() with a long delay, the framework will stop spinning, messages accumulate and things may go awry."*

### The startLoop() and patchAsyncio() functions

`util.patchAsyncio()` applies the `nest_asyncio` library to allow calling `loop.run_until_complete()` from within an already-running event loop—necessary for Jupyter notebooks and some GUI frameworks. `util.startLoop()` simply calls `patchAsyncio()`. In a standard Python script, neither is needed; just call `ib.run()` at the end or use `ib.sleep()` in a loop.

### Threading: technically possible, practically painful

ib_async is fundamentally single-threaded due to asyncio. Running it on a separate thread requires creating a new event loop for that thread (`asyncio.set_event_loop(asyncio.new_event_loop())`). GitHub issues #167 and #436 document `RuntimeError: There is no current event loop in thread` errors. The recommended architecture is to **run ib_async in the main thread** and offload heavy computation to worker threads, or use the connect/disconnect pattern per poll cycle.

---

## The "fire and check later" pattern for 15–30 minute polling

### Option 1: Connect/disconnect each cycle (recommended)

This is the safest pattern for long polling intervals. Bracket orders execute server-side at IB regardless of your API connection state. Each poll cycle reconnects and rebuilds state:

```python
import time
from ib_async import *

def poll_cycle():
    ib = IB()
    ib.connect('127.0.0.1', 7497, clientId=1)
    ib.sleep(2)  # let initial state sync complete
    
    # Reconstruct state from server
    open_trades = ib.openTrades()
    positions = ib.positions()
    executions = ib.executions()
    
    # Check bracket order status by matching parentId
    for trade in open_trades:
        parent_id = trade.order.parentId
        status = trade.orderStatus.status
        print(f"Order {trade.order.orderId} (parent={parent_id}): {status}")
    
    # Place new orders if needed
    # ...
    
    ib.disconnect()

while True:
    poll_cycle()
    time.sleep(900)  # safe—no IB connection during sleep
```

**Key advantage: no stale state, no idle connection, no event loop concerns.** Trade objects from previous sessions are gone, but `ib.openTrades()` and `ib.executions()` reconstruct everything from the server. Track orders by **`permId`** (permanent, survives sessions) rather than `orderId` (session-specific).

### Option 2: Persistent connection with ib.sleep()

```python
from ib_async import *

ib = IB()
ib.connect('127.0.0.1', 7497, clientId=1)

# Attach global handler once
ib.orderStatusEvent += lambda trade: print(f"{trade.contract.symbol}: {trade.orderStatus.status}")

while True:
    # Flush any queued messages first
    ib.sleep(0)
    
    # Check current state
    for trade in ib.openTrades():
        if trade.isDone():
            print(f"Order {trade.order.orderId} completed: {trade.orderStatus.status}")
    
    # Keep event loop alive during wait
    ib.sleep(900)  # processes messages continuously for 15 min
```

This keeps Trade objects live-updated but requires handling daily TWS restarts (23:45–00:45 ET) and connection drops.

### Does the TCP connection survive 15–30 minutes idle?

The TWS API has **no application-level heartbeat protocol**. On localhost, the TCP connection typically survives because the OS doesn't enforce short idle timeouts and TWS periodically sends background messages (market data farm status codes 2104/2106, account updates). However, if you have zero active subscriptions and use `time.sleep()`, there's a real risk of the connection going stale. `ib.setTimeout(60)` can detect this by firing `timeoutEvent` if no data arrives for 60 seconds—but it only monitors, it doesn't send keepalives.

---

## Bracket orders: placement, tracking, and child order behavior

### Creating and placing bracket orders

The `ib.bracketOrder()` helper creates three linked orders using IB's parent-child mechanism:

```python
bracket = ib.bracketOrder('BUY', 100, limitPrice=150.0, 
                          takeProfitPrice=160.0, stopLossPrice=145.0)

# bracket.parent:     LimitOrder BUY 100 @ 150, transmit=False
# bracket.takeProfit: LimitOrder SELL 100 @ 160, transmit=False, parentId=parent.orderId  
# bracket.stopLoss:   StopOrder  SELL 100 @ 145, transmit=True,  parentId=parent.orderId

# Must place all three — the last one (transmit=True) triggers atomic submission
parent_trade = ib.placeOrder(contract, bracket.parent)
tp_trade = ib.placeOrder(contract, bracket.takeProfit)
sl_trade = ib.placeOrder(contract, bracket.stopLoss)
```

The `transmit=False` / `transmit=True` pattern ensures IB receives all three orders before activating any of them. **Each order gets its own independent Trade object** with its own events.

### Child order lifecycle

The parent Trade object's events **do not fire when a child fills**. Each leg is fully independent in the event system. To monitor the complete bracket:

```python
parent_trade.filledEvent += lambda t: print("Entry filled!")
tp_trade.filledEvent += lambda t: print("Take profit hit!")
sl_trade.filledEvent += lambda t: print("Stop loss hit!")
```

**IB handles the OCA (One-Cancels-All) logic server-side.** When one child fills (e.g., stop loss), IB automatically cancels the other child (take profit). You'll see `cancelledEvent` fire on the cancelled child. The parent remains `Filled`.

To reconstruct bracket relationships in a polling architecture, filter `openTrades()` by `parentId`:

```python
for trade in ib.openTrades():
    if trade.order.parentId == parent_order_id:
        print(f"Child {trade.order.orderId}: {trade.orderStatus.status}")
```

### Caveat: no guarantee against double fills

IB's documentation warns there is **no absolute guarantee** that both OCA children won't fill in an extremely fast market. If the take-profit and stop-loss prices are close together, both could execute before the cancellation propagates on the exchange.

---

## Known pitfalls and production patterns

### Memory leaks from event handler accumulation

If you reattach handlers on every reconnect cycle—`ib.orderStatusEvent += handler`—handlers accumulate because `+=` appends to the internal `_slots` list. After 100 reconnects, you have 100 copies of the same handler firing on every status change. **Fix: attach handlers once outside the reconnect loop**, or call `event.clear()` before reattaching:

```python
# WRONG — handlers accumulate
async def on_reconnect():
    ib.orderStatusEvent += my_handler  # adds another copy each time

# RIGHT — attach once, outside reconnect loop
ib.orderStatusEvent += my_handler
async def on_reconnect():
    pass  # handler already attached
```

### Events during disconnect/reconnect cycles

When a connection drops, **Trade-level events (`statusEvent`, `fillEvent`) are NOT marked as done** (erdewit/ib_insync#413). Your code won't know the connection died unless you separately monitor `ib.disconnectedEvent`. After reconnect, all previous Trade objects are orphaned—`ib.trades()` returns empty. You must rebuild state via `ib.reqAllOpenOrders()`, `ib.executions()`, and `ib.positions()`.

```python
ib.disconnectedEvent += lambda: print("CONNECTION LOST — all Trade objects now stale")
ib.connectedEvent += lambda: print("Reconnected — rebuild state from server")
```

### The phantom order bug (fixed in ib_async 2.0.1)

A critical bug in earlier versions: when an order modification triggered a validation error from IB, the library incorrectly deleted the order from local state—even though it remained live on IB's servers (erdewit/ib_insync#502). The order became invisible to `openTrades()` and `openOrders()`. **ib_async 2.0.1 fixed this**, but the lesson stands: periodically call `ib.reqAllOpenOrders()` to verify local state matches the server.

### Orders stuck in PendingSubmit (ib_async#66)

Users report orders that stay `PendingSubmit` with `remaining=0.0` and never appear in TWS. Production systems must implement **timeout-based verification**: if a trade hasn't left `PendingSubmit` within a few seconds, cross-check with `ib.reqAllOpenOrders()`.

### Silent handler failures

Exceptions in event handlers are caught by eventkit and routed to the event's `error_event`, not raised to the caller. **Bugs in your handlers are invisible** unless you explicitly log them:

```python
def safe_handler(trade):
    try:
        # your logic here
        process_fill(trade)
    except Exception as e:
        logger.error(f"Handler error: {e}", exc_info=True)

trade.filledEvent += safe_handler
```

### Terminal statuses and trade.isDone()

`trade.isDone()` returns `True` when `orderStatus.status` is in `DoneStates`:

- **`Filled`** — fully executed
- **`Cancelled`** — cancelled by user or system
- **`ApiCancelled`** — cancelled via API
- **`Inactive`** — rejected by IB (e.g., margin violation, contract not found)

Note that ib_async added `Inactive` to `DoneStates`—the original ib_insync did not include it, which could cause code to wait forever on a rejected order.

### State recovery after disconnect

```python
# After reconnecting:
ib.connect('127.0.0.1', 7497, clientId=1)
ib.sleep(2)  # let sync complete

# Server-side state reconstruction
open_orders = ib.reqAllOpenOrders()   # all orders across all clientIds
open_trades = ib.openTrades()          # current session's tracked trades
executions = ib.executions()           # fills from this session
positions = ib.positions()             # current positions
completed = ib.reqCompletedOrders()    # historical completed orders
```

---

## ib_async vs ib_insync: what changed in the fork

ib_async was created in March 2024 after ib_insync's creator, **Ewald de Wit, passed away**. The repository was archived and the community forked it under the `ib-api-reloaded` organization.

| Attribute | ib_insync | ib_async |
|-----------|-----------|----------|
| Latest version | 0.9.86 (archived) | **2.1.0** (Dec 2025) |
| Status | Dead—read-only | Actively maintained |
| Python | 3.6+ | **≥ 3.10** |
| Event library | eventkit | **aeventkit** (functionally identical fork) |
| pip install | `ib-insync` | `ib_async` |
| Import | `from ib_insync import *` | `from ib_async import *` |

**The event system architecture is identical.** Same event names, same patterns, same `+=` subscription syntax. The underlying `aeventkit` is a functionally equivalent fork of `eventkit`, created because the original PyPI package was locked behind a closed account.

Key improvements in ib_async 2.x: fixed phantom order deletion on validation errors, expanded `DoneStates` to include `Inactive`, better event loop handling (fixes for stale/cached event loops), improved warning code classification, and modern Python 3.10+ type annotations. **Migration from ib_insync is straightforward**—change the import, update pip, and review the `qualifyContractsAsync()` return value change (now returns `None` for failed qualifications instead of silently dropping them).

**All new projects should use ib_async.** ib_insync will never receive updates for future IBKR protocol changes and will eventually break.

---

## Recommended architecture for your 15–30 minute polling system

Given your synchronous polling pattern with long intervals between cycles, the **connect/disconnect pattern** is the most robust approach:

```python
import time, logging
from ib_async import *

logger = logging.getLogger(__name__)

# Track orders by permId (survives sessions)
tracked_brackets = {}  # {parent_permId: {'symbol': ..., 'entry_time': ...}}

def poll_cycle():
    ib = IB()
    try:
        ib.connect('127.0.0.1', 7497, clientId=1)
        ib.sleep(2)  # let initial sync complete
        
        # 1. Check existing bracket orders
        for trade in ib.openTrades():
            perm = trade.order.permId
            parent = trade.order.parentId
            logger.info(f"Open: permId={perm} parentId={parent} "
                       f"status={trade.orderStatus.status} "
                       f"filled={trade.orderStatus.filled}")
        
        # 2. Check positions
        for pos in ib.positions():
            logger.info(f"Position: {pos.contract.symbol} "
                       f"qty={pos.position} avg={pos.avgCost}")
        
        # 3. Check recent executions
        for fill in ib.fills():
            logger.info(f"Fill: {fill.contract.symbol} "
                       f"{fill.execution.shares}@{fill.execution.price}")
        
        # 4. Place new bracket orders if conditions met
        # contract = Stock('AAPL', 'SMART', 'USD')
        # ib.qualifyContracts(contract)
        # bracket = ib.bracketOrder('BUY', 100, 150.0, 160.0, 145.0)
        # for o in bracket:
        #     t = ib.placeOrder(contract, o)
        # ib.sleep(1)  # confirm submission
        # tracked_brackets[bracket.parent.permId] = {...}
        
    except Exception as e:
        logger.error(f"Poll cycle error: {e}", exc_info=True)
    finally:
        if ib.isConnected():
            ib.disconnect()

while True:
    poll_cycle()
    time.sleep(900)  # safe—no active IB connection
```

This pattern eliminates all idle-connection risks, stale-state bugs, and event loop concerns. Bracket orders execute server-side at IB regardless of your connection status. Each cycle reconstructs the full picture from authoritative server state. The tradeoff—connection overhead of ~2 seconds per cycle—is negligible against a 15-minute interval.