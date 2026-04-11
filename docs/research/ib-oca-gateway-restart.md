# IB bracket orders survive Gateway restarts — but edge cases demand vigilance

**GTC bracket orders placed through IB Gateway persist through daily restarts because they are stored on IB's servers, not locally.** Once transmitted, the parent order, child orders (take-profit and stop-loss), and their OCA group linkage all live server-side and continue operating independently of the Gateway process. However, there is a critical distinction between the Gateway application restart (a local process restart) and the IB server reset (a nightly backend maintenance window at **23:45–00:45 ET**), and each introduces different risks. The most dangerous edge case involves **simulated order types** — including many stop orders — which are managed by IB's servers rather than routed natively to exchanges, creating a vulnerability window during the server reset.

## Where GTC orders actually live after transmission

The single most important architectural fact: **transmitted GTC orders are stored on IB's servers, not in the Gateway's local state.** IB's official order submission documentation states that "untransmitted orders will only be available within that TWS session and will be cleared on restart," but once an order is transmitted (Transmit=true), it is sent to and managed by IB's servers. This is confirmed by GTC orders persisting for months — they auto-cancel only at the end of the calendar quarter following their creation.

The OCA group metadata is **also server-side**. The `ocaGroup` string identifier and `ocaType` are properties of each transmitted order object. Since transmitted orders live on IB's servers, OCA grouping persists there too. IB's IBKR Guides confirm that OCA is managed as a native server-side construct: "once an order in the group fills, all other linked orders are canceled." The bracket's parent-child relationship (via `ParentId`) is likewise maintained server-side — children are held in a "PreSubmitted" state until the parent fills.

However, IB distinguishes between **native** and **simulated** order types, and this distinction is critical:

- **Native orders** (standard limit orders, some stop types on supporting exchanges) are routed directly to the exchange and operate completely independently of both the Gateway and IB's application servers
- **Simulated orders** (stop-market on many exchanges, trailing stops, certain conditional orders) are held and managed by IB's application servers — they show status "PreSubmitted" and rely on IB's systems to trigger them

IB's System Status page explicitly states: "Existing orders (native types) will operate normally although execution reports and **simulated orders will be delayed** until the reset is complete."

## Two distinct restart events create different risk profiles

Algo traders frequently conflate two separate events, but they carry very different risks.

**The Gateway application restart** (default 11:45 PM in the system timezone, configurable via Configure → Lock and Exit → Auto restart) is purely a local process restart. The Gateway disconnects from IB servers, restarts itself, and reconnects — typically taking **10–30 seconds**. During this window, your API client receives error code **1100** ("Connectivity between IB and TWS has been lost"). All transmitted orders remain active on IB's servers throughout. Available since version 974+, the auto-restart feature allows the Gateway to run Monday through Saturday without re-authentication; only Sunday at 1:00 AM ET requires manual 2FA.

**The IB server reset** (approximately **23:45–00:45 ET** for North America, daily) is a backend maintenance window affecting all clients globally. During this period, IB's official position is that native orders "will operate normally" while simulated orders "will be delayed." The practical implication: if your bracket's stop-loss is a simulated stop order (common on many exchanges), it may not trigger during this ~60-minute window if the market moves against you. IB explicitly recommends: "It is not recommended to operate during the scheduled reset times."

These two events typically overlap by design — the default Gateway restart time of 11:45 PM ET falls within the server reset window. This is intentional to minimize disruption.

## Child orders reappear automatically in ib_async after reconnect

The ib_async library (and its predecessor ib_insync) **automatically calls `reqOpenOrders()` during every connection**, including reconnections after Gateway restart. The `connectAsync()` method's initialization sequence explicitly includes:

```python
if not readonly:
    reqs['open orders'] = self.reqOpenOrdersAsync()
```

This means that after Gateway reconnects, all surviving GTC orders — including bracket children with their `parentId` and `ocaGroup` attributes intact — automatically repopulate `ib.openTrades()` and `ib.openOrders()`. No explicit call to `reqOpenOrders()` is necessary. The `connectedEvent` fires after this sync completes, making it the correct hook for post-reconnection verification logic.

Three prerequisites are critical for this to work correctly. First, the **"Download open orders on connection" setting must be checked** in Gateway's API configuration. Second, you **must reconnect with the same `clientId`** — orders placed by clientId 4 are invisible to clientId 5 (only clientId 0 has cross-client visibility, but cannot modify other clients' orders). Third, the library documentation warns that `reqOpenOrders()` can occasionally give stale information, recommending `openTrades()` as the more reliable method for ongoing state queries.

Several GitHub issues document reconnection edge cases. Issue **#502** (erdewit/ib_insync) revealed that failed order modifications cause false cancellation reports in the local state — the library sees "Cancelled" and removes the order from `openTrades()`, but the original order remains active on IB's servers until a full reconnect re-syncs state. Issue **#308** documented duplicate order ID conflicts after reconnection, and issue **#376** found that rapid disconnect/reconnect cycles cause clientId conflicts because the prior session hasn't fully torn down.

## OCA groups can break, but not typically from restarts alone

No community source has documented a confirmed case of OCA groups breaking **specifically** because of the 23:45 ET server reset. However, several failure modes are well-documented and relevant to production systems.

**The partial fill race condition** is the most dangerous. The twsapi Groups.io forum includes this critical warning: "OCAs are not magic, and there are rare situations where more than one order is filled... In a frantic market it could move one way (triggering one order) and then rapidly reverse, triggering the other before IB has had time to react and cancel it." Since stop orders are often simulated by IB rather than native to the exchange, the fill notification must reach IB's servers quickly enough to cancel the opposing leg — creating a theoretical race condition even during normal operation.

**System cancellations don't propagate through OCA groups.** IB's official documentation contains a critical caveat: "if one of the orders is rejected or canceled by the **system**, the remaining order(s) WILL NOT automatically be canceled." This means if IB's system rejects or cancels one leg of your bracket during a server reset (for any reason), the other leg will remain active, leaving your position with only partial protection. Only client-initiated cancellations and fills trigger OCA propagation.

A 2012 incident documented on the Limit Up Trading blog involved IB canceling a stop-loss and good-after-time order from a bracket while leaving the profit target intact, exposing the position completely. The root cause was partial fills on the parent order causing unexpected OCA behavior. IB acknowledged and fixed that specific bug, but it illustrates the category of risk.

**OCA string reuse** is another documented pitfall. NinjaTrader forum users discovered that reusing the same OCA identifier string across multiple bracket trades causes TWS to reject subsequent orders with "Cancelled by system: OCA group already filled." Each bracket must use a unique OCA identifier.

## Production verification workflow after every reconnect

Based on the IB API documentation and community best practices, the recommended post-reconnection verification follows a specific sequence. The `connectedEvent` in ib_async fires after the initial order sync completes, making it the right place to implement this logic.

**Step 1: Verify positions match expectations.** Call `ib.positions()` immediately after reconnection and compare actual positions against your system's expected state. Any discrepancy indicates fills occurred during the disconnection window that may not yet be reflected in your internal state.

**Step 2: Verify bracket integrity.** Iterate through `ib.openTrades()` and reconstruct bracket groups by matching `parentId` and `ocaGroup` values. For each position that should have protective orders, confirm both the take-profit and stop-loss children exist and are in "Submitted" or "PreSubmitted" status. Use `permId` (persistent, unique account-wide) for cross-session tracking rather than `orderId`, which is session-specific.

**Step 3: Check for fills during disconnection.** Call `ib.reqExecutions()` to retrieve any executions that occurred while disconnected. This catches the case where a bracket child filled during the Gateway restart but the fill report hasn't been processed by your system.

**Step 4: Resubmit missing protection.** If a child order is missing — one leg of the bracket was cancelled or rejected during the server reset — immediately submit a replacement order. Do not assume the OCA relationship will self-heal. The safest approach is to cancel any remaining orphaned child and resubmit a fresh bracket pair with a new OCA group identifier.

For the API calls themselves, `reqOpenOrders()` returns orders from your clientId and re-binds them for modification. `reqAllOpenOrders()` returns all API orders across all clients but is **read-only** — it cannot bind or modify orders. After calling `reqAllOpenOrders()`, any subsequent `placeOrder()` must use order IDs greater than all returned IDs.

## Architecture recommendations for 24/7 IB systems

The community consensus for production IB algo trading systems converges on several infrastructure patterns. **IBC** (github.com/IbcAlpha/IBC) is the dominant automation tool for managing Gateway login, 2FA, and restart cycles. Many production systems run IB Gateway inside **Docker containers** with IBC and docker-compose autoheal, achieving approximately one unplanned failure per month according to Elite Trader forum reports. The ib_async **Watchdog** class builds on IBC to add connection monitoring — it probes with historical data requests and auto-restarts Gateway via IBC when unresponsive.

Several configuration settings are non-negotiable for 24/7 bracket order systems:

- **Enable "Fill outside RTH"** (`outsideRth=True`) on all protective orders. Without this, GTC orders on IB will not execute outside regular trading hours, even for instruments that trade 24 hours. Multiple community reports document positions left unprotected overnight because this flag was missing.
- **Enable "Download open orders on connection"** in Gateway API settings. Without this, `reqOpenOrders()` returns nothing on reconnect.
- **Use GTC time-in-force on all bracket children.** A documented gotcha: mixing DAY and GTC within a bracket means one leg expires at session close while the other persists, leaving positions partially exposed.
- **Use OcaType 3** (with block/overfill protection) for bracket children. This routes only one OCA order at a time, preventing the dual-fill race condition in volatile markets.

For the restart timing itself, set the Gateway auto-restart during a period when your traded instruments are least active. The default 11:45 PM ET aligns with the IB server reset window, which is by design. Some futures traders prefer 17:01 ET (just after the CME daily close) to minimize exposure during the brief restart gap.

## Conclusion

The core architecture is sound: **transmitted GTC bracket orders and their OCA linkage are server-side constructs that survive Gateway restarts.** The ib_async library automatically re-syncs open orders on reconnection. The real risks lie at the edges — simulated stop orders delayed during the nightly server reset, the system-cancellation OCA propagation gap, and the rare but possible dual-fill race condition. A production system that verifies bracket integrity after every reconnection, uses `permId` for tracking, enables "Fill outside RTH," and runs independent position reconciliation can mitigate these risks effectively. The behavior is not fully documented by IB in any single authoritative source — the complete picture must be assembled from the API docs, system status page, community forums, and library source code. The one genuinely undocumented risk is the exact behavior of simulated stop orders during the 23:45–00:45 ET server reset window, where IB's language ("delayed") leaves ambiguity about whether a fast market move could breach your stop without execution during that period.