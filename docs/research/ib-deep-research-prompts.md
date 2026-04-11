# IB Deep Research Prompts — 4 Questions Blocking Sprint IB-4

**Context for all 4 prompts:** I'm building an autonomous AI equity trading system (Arcis / Halcyon Lab) that currently uses Alpaca for paper and live trading. I'm integrating Interactive Brokers as a second broker using the `ib_async` Python library (community fork of `ib_insync`). The system trades S&P 100 large-cap equities with a pullback-in-uptrend strategy, 2-15 day holding periods, bracket orders (entry + stop-loss + take-profit), and runs 24/7 on Windows 11 with an RTX 3060. I need production-grade answers — not getting-started tutorials.

---

## Prompt 1: OCA Group Behavior Across Gateway Restarts

**Paste this into Claude Deep Research:**

```
I'm using Interactive Brokers with ib_async (Python) for bracket orders on US equities. My bracket orders use IB's bracketOrder() function which creates an OCA (One Cancels All) group: a parent market/limit buy + a take-profit limit sell + a stop-loss stop sell. All orders are GTC (Good Till Cancel).

IB Gateway performs a daily restart at approximately 11:45 PM ET. My system runs 24/7 on Windows 11.

I need definitive answers to these questions:

1. When IB Gateway restarts at 11:45 PM ET, what happens to:
   a. Filled parent orders (entry already executed, children active)
   b. The OCA group linking the children (stop + target)
   c. Unfilled parent orders (entry not yet executed)

2. After Gateway reconnects (~2-5 minutes later), do the child orders (stop-loss and take-profit) automatically reappear in the ib_async client's openTrades()? Or do they need to be explicitly re-requested?

3. Has anyone documented cases where the OCA group breaks during a Gateway restart — i.e., the stop-loss is cancelled but the take-profit remains active (or vice versa), leaving the position with only partial protection?

4. What is the recommended practice for verifying bracket integrity after a Gateway reconnect? Should I:
   a. Call ib.trades() and verify both children are still active?
   b. Call ib.openOrders() and match by OCA group ID?
   c. Resubmit the entire bracket if children are missing?

5. Are GTC orders stored on IB's servers (surviving Gateway restarts) or in the Gateway's local state (lost on restart)?

Please include: IB official documentation references, ib_async/ib_insync GitHub issues or discussions, community forum posts (Elite Trader, Reddit r/algotrading, ib_insync GitHub), and any academic or practitioner publications on IB order management. I need to know if this is a real production risk or a theoretical concern.
```

---

## Prompt 2: IB Paper Trading Fill Simulation Accuracy

**Paste this into Claude Deep Research:**

```
I'm comparing Interactive Brokers paper trading fills against Alpaca paper trading fills for the same equity trades (S&P 100 large-caps, bracket orders, 2-15 day holds). I need to understand how realistic IB's paper trading simulation is.

Specific questions:

1. How does IB paper trading simulate market order fills?
   a. Does it use the last traded price, midpoint of bid/ask, or a model with simulated spread?
   b. Does it model slippage based on order size relative to volume?
   c. Does it simulate partial fills, or does every market order fill instantly and completely?

2. How does IB paper trading simulate limit order fills?
   a. Does it require the price to trade through the limit (realistic) or just touch it?
   b. Does it model queue priority (time priority at a price level)?

3. How does IB paper trading simulate stop-loss triggers?
   a. Does the stop trigger on the last traded price, or the bid/ask?
   b. After triggering, is the resulting market order filled at the trigger price or at a simulated slippage price?

4. How does IB paper trading handle bracket orders specifically?
   a. When the stop or target triggers, does the OCA cancellation of the other leg happen instantly or with a simulated delay?

5. How does Alpaca paper trading compare on each of these dimensions? I'm looking for a direct comparison to understand whether IB paper vs Alpaca paper fills will diverge significantly for the same trade.

6. Are there any known biases in IB paper trading that would make backtested results look better or worse than live trading? (e.g., does paper trading ignore market impact, give unrealistically fast fills, etc.)

Please include: IB official documentation on paper trading simulation, community benchmarks comparing paper vs live fills, any academic analysis of simulated trading environments, and practitioner experience from algorithmic traders who transitioned from IB paper to live.
```

---

## Prompt 3: ib_async Event-Driven Fill Detection Patterns

**Paste this into Claude Deep Research:**

```
I'm using ib_async (Python, community fork of ib_insync) for algorithmic trading. My current implementation uses synchronous polling with ib.sleep() to wait for order fills:

```python
trade = self._ib.placeOrder(contract, order)
self._ib.sleep(2)  # Wait 2 seconds for fill
status = trade.orderStatus.status  # Check if filled
```

This is brittle — fast fills might be missed if they happen before the sleep, and slow fills (pending orders) timeout after 2 seconds. I need to move to event-driven fill detection.

Questions:

1. What is the recommended pattern for detecting order fills using ib_async's event system?
   a. How do `ib.orderStatusEvent`, `trade.statusEvent`, and `trade.filledEvent` differ?
   b. Which event fires first when an order fills?
   c. Is there a race condition between placing the order and attaching the event handler?

2. My application is synchronous (not asyncio-based). It runs a watch loop that polls every 15-30 minutes. Between polls, the IB event loop is not spinning.
   a. Can I use ib_async events in a synchronous application?
   b. Do I need to run `ib.sleep()` or `ib.waitOnUpdate()` periodically to process queued events?
   c. Should I run the IB event loop on a separate thread? If so, what are the threading pitfalls with ib_async?

3. What's the recommended pattern for "fire and check later"?
   a. Place order, store trade object, continue with other work
   b. On next poll cycle (15-30 min later), check trade.orderStatus.status
   c. Does this work reliably, or can the trade object become stale?

4. For bracket orders specifically (3 linked orders):
   a. How do I detect when a child order (stop or target) fills?
   b. Does the parent trade object's events fire when a child fills?
   c. What's the recommended pattern for monitoring all 3 legs of a bracket?

5. What are the known pitfalls of ib_async event handling?
   a. Memory leaks from accumulating event handlers
   b. Events firing during disconnect/reconnect
   c. Events lost during Gateway restart

Please include: ib_async source code references, working code examples, GitHub issues about event handling bugs, and any patterns from production trading systems using ib_async. I'm particularly interested in patterns that work with a synchronous polling architecture rather than a pure asyncio application.
```

---

## Prompt 4: IB Gateway Stability on Windows 11

**Paste this into Claude Deep Research:**

```
I'm running Interactive Brokers Gateway (not TWS) on Windows 11 for 24/7 algorithmic trading. The system is a dedicated trading machine (Ryzen, RTX 3060, 24GB RAM) that also runs Python processes, Ollama (LLM inference), and a FastAPI server.

I need to understand IB Gateway's long-term stability characteristics on Windows 11 for planning a 30-day continuous operation validation gate.

Questions:

1. What is the typical uptime pattern for IB Gateway on Windows 11?
   a. How reliable is the daily restart at ~11:45 PM ET? Does it always come back?
   b. How long does the restart take (connection downtime)?
   c. Are there any days where the restart fails and requires manual intervention?

2. What are the most common failure modes for IB Gateway on Windows 11?
   a. Memory leaks over multi-week operation?
   b. Java process crashes (Gateway is a Java application)?
   c. Windows Update forcing restarts?
   d. Interaction with other processes (GPU drivers, Ollama, Python)?
   e. Network adapter sleep/power management issues?

3. How should I configure IB Gateway for maximum stability?
   a. Auto-restart settings (IBC — IB Controller)?
   b. Java heap size (-Xmx)?
   c. Windows power settings to prevent sleep/hibernate?
   d. Disabling Windows Update during market hours?
   e. Running as a Windows service vs. desktop application?

4. What happens during IB scheduled maintenance windows?
   a. How often does IB have full system outages?
   b. Are these announced in advance?
   c. What happens to GTC orders during maintenance?

5. For a 30-day stability gate, what's a realistic target?
   a. What uptime percentage should I expect? (95%? 99%? 99.9%?)
   b. How many manual interventions per month should I budget for?
   c. Are weekends different from weekdays? (Gateway behavior when markets are closed)

6. Is IBC (IB Controller) or similar auto-restart tool recommended for production?
   a. Does IBC reliably handle the daily 11:45 PM restart?
   b. Does IBC handle unexpected crashes and auto-restart?
   c. What are the alternatives to IBC?

Please include: community experience from Elite Trader forums, Reddit r/algotrading, ib_insync/ib_async GitHub issues, any systematic stability analysis, and practitioner blog posts about running IB Gateway in production. I'm specifically interested in Windows 11 experiences (not Linux/Docker deployments) from 2024-2026.
```

---

## How to Use These

1. Open 4 separate Claude Deep Research sessions (or run sequentially)
2. Paste each prompt verbatim
3. Save the results to `docs/research/`:
   - `ib-oca-gateway-restart.md`
   - `ib-paper-fill-simulation.md`
   - `ib-async-event-patterns.md`
   - `ib-gateway-windows-stability.md`
4. The answers directly inform Sprint IB-4 (Production Hardening) implementation details
5. Share the results in our next session — I'll incorporate the findings into the final IB-4 sprint prompt
