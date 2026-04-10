# Trade Reconciliation Rectification Plan

> **Goal:** Clean up all position/order mismatches between Alpaca and the DB,
> restore buying power, and ensure the system can trade normally.
>
> **DO NOT touch:** CAT, CVX, WMT — these are the 3 legitimately tracked open trades.

---

## Current State

| Category | Tickers | Count | Issue |
|----------|---------|-------|-------|
| DB-tracked open (KEEP) | CAT, CVX, WMT | 3 | Legitimate. CAT/CVX have pending limit sells (their bracket targets). Leave alone. |
| Orphans (no DB record) | USB, CVS, MO, GOOGL, TXN, SBUX, TGT, CSCO, PFE | 9 | Alpaca holds positions + limit sell orders. DB has no open record. |
| Ghosts (DB=rejected, Alpaca=open) | GS, XOM, COP, FDX, NEE, LIN | 6 | DB marked as `order_rejected_buying_power` but Alpaca actually filled them. Have limit sell orders. |
| Rejected trades in DB | ~42 trades | 42 | `status='failed'` with `order_type='rejected_buying_power'`. Terminal but not marked closed. |
| Phantom shorts (closing) | C, ETN | 2 | Close orders submitted after-hours, will fill at next market open. |

**Total cleanup:** 15 positions to close + 42 DB records to fix + verify C/ETN filled.

---

## Phase 1: Cancel pending orders on orphan + ghost positions

The 15 orphan/ghost positions each have a pending limit sell order that locks
their shares via `held_for_orders`. These must be cancelled before we can close
the positions.

**Get the order IDs for the 15 tickers, then cancel them:**

```python
from src.shadow_trading.alpaca_adapter import _get_trading_client

client = _get_trading_client()

# These are the 15 orphan + ghost tickers to clean up
cleanup_tickers = [
    # 9 orphans (no DB record)
    'USB', 'CVS', 'MO', 'GOOGL', 'TXN', 'SBUX', 'TGT', 'CSCO', 'PFE',
    # 6 ghosts (DB=rejected but Alpaca has position)
    'GS', 'XOM', 'COP', 'FDX', 'NEE', 'LIN',
]

# DO NOT cancel orders for these — they are legitimate
keep_tickers = {'CAT', 'CVX', 'WMT'}

# Get all open orders
from alpaca.trading.requests import GetOrdersRequest
from alpaca.trading.enums import QueryOrderStatus
orders = client.get_orders(filter=GetOrdersRequest(status=QueryOrderStatus.OPEN))

cancelled = 0
for order in orders:
    if order.symbol in cleanup_tickers and order.symbol not in keep_tickers:
        try:
            client.cancel_order_by_id(order.id)
            print(f"Cancelled order for {order.symbol}: {order.side} {order.qty} @ {order.limit_price} (id={order.id})")
            cancelled += 1
        except Exception as e:
            print(f"Failed to cancel {order.symbol} order {order.id}: {e}")

print(f"\nCancelled {cancelled} orders")
```

**Wait 2 seconds after cancelling for Alpaca to release the held_for_orders lock.**

```python
import time
time.sleep(2)
```

---

## Phase 2: Close the 15 orphan + ghost positions

Now that the orders are cancelled and shares are unlocked, close the positions:

```python
from src.shadow_trading.alpaca_adapter import _get_trading_client

client = _get_trading_client()

cleanup_tickers = [
    'USB', 'CVS', 'MO', 'GOOGL', 'TXN', 'SBUX', 'TGT', 'CSCO', 'PFE',
    'GS', 'XOM', 'COP', 'FDX', 'NEE', 'LIN',
]

closed = 0
for ticker in cleanup_tickers:
    try:
        client.close_position(ticker)
        print(f"{ticker}: close order submitted")
        closed += 1
    except Exception as e:
        print(f"{ticker}: {e}")

print(f"\nSubmitted {closed} close orders")
```

**Note:** If market is closed, these queue as market-on-open orders for next session.

---

## Phase 3: Mark rejected/failed DB trades as closed

42 trades have `status='failed'` with `order_type='rejected_buying_power'`.
These are terminal — mark them closed so they don't clutter active queries.

Also mark the 6 ghost tickers' DB records as closed (they were "rejected" in
the DB but actually filled on Alpaca — we're closing the Alpaca side in Phase 2,
so the DB side should also be terminal).

```python
import sqlite3

conn = sqlite3.connect('ai_research_desk.sqlite3')

# Mark all failed/rejected trades as closed
updated = conn.execute("""
    UPDATE shadow_trades
    SET status = 'closed',
        exit_reason = CASE
            WHEN order_type = 'rejected_buying_power' THEN 'rejected_buying_power'
            WHEN order_type = 'failed' THEN 'entry_failed'
            ELSE 'cleanup_' || COALESCE(order_type, 'unknown')
        END
    WHERE status = 'failed'
""").rowcount
conn.commit()
print(f"Marked {updated} failed trades as closed")

# Also mark any exit_failed trades as closed
updated2 = conn.execute("""
    UPDATE shadow_trades
    SET status = 'closed'
    WHERE status = 'exit_failed'
""").rowcount
conn.commit()
print(f"Marked {updated2} exit_failed trades as closed")

conn.close()
```

---

## Phase 4: Verify C and ETN shorts are closed

C (-420 shares) and ETN (-228 shares) had close orders submitted after-hours.
Verify they filled:

```python
from src.shadow_trading.alpaca_adapter import get_all_positions

positions = get_all_positions()
for p in positions:
    if p['symbol'] in ('C', 'ETN'):
        print(f"WARNING: {p['symbol']} still open — qty={p['qty']}")

if not any(p['symbol'] in ('C', 'ETN') for p in positions):
    print("C and ETN: confirmed closed")
```

If they're still showing, their close orders haven't filled yet (market was closed).
They will fill at next market open.

---

## Phase 5: Final reconciliation and verification

```python
# Run reconciliation
from src.shadow_trading.reconcile import reconcile_paper_trades
result = reconcile_paper_trades(dry_run=False)
print(result)

# Check buying power
from src.shadow_trading.alpaca_adapter import get_account_info
acct = get_account_info()
print(f"\nEquity:       ${acct['equity']:,.2f}")
print(f"Buying power: ${acct['buying_power']:,.2f}")
print(f"Positions:    {len(get_all_positions())}")

# Verify DB state
import sqlite3
conn = sqlite3.connect('ai_research_desk.sqlite3')
conn.row_factory = sqlite3.Row
open_trades = conn.execute(
    "SELECT ticker, status FROM shadow_trades WHERE status NOT IN ('closed')"
).fetchall()
print(f"\nNon-closed trades in DB: {len(open_trades)}")
for t in open_trades:
    print(f"  {t['ticker']}: {t['status']}")
conn.close()
```

**Expected end state:**
- Alpaca: 3 positions (CAT, CVX, WMT) + pending C/ETN closes
- DB: 3 open trades (CAT, CVX, WMT), everything else closed
- Buying power: ~$90K+ (freed from 15 closed positions)
- Reconciliation: matched=3, orphaned=0, stale=0

---

## Phase 6: Pull latest code

The executor has been patched so future rejected trades go straight to
`status='closed'` instead of `status='failed'`. Pull to prevent recurrence:

```bash
git pull origin main
```
