# alpaca-py Intraday Streaming Gap (Phase 6 Pre-Work)

**Authority:** `docs/sprints/sprint-alpaca-py-migration.md` Task 4
**Written:** 2026-04-16
**Consumed by:** Phase 6 intraday desk sprint (not yet scheduled)
**Current state:** zero streaming surface area in `src/`.

---

## Why this exists

Phase 6 introduces an intraday desk that reacts to real-time bars and fills.
The current system is a 60-second synchronous poll loop — fine for swing
trading, wrong shape for intraday. This doc pre-maps the alpaca-py streaming
classes needed so Phase 6 can wire handlers rather than architect from
scratch.

**This is pre-work, not a sprint plan.** No code changes result from this
document.

---

## Streaming classes required

alpaca-py exposes two streaming clients under the `0.43+` API:

### 1. `alpaca.trading.stream.TradingStream`

**Subscribes to:** order events (new, fill, partial_fill, canceled, expired,
rejected) for the account.

**Transport:** WebSocket, auto-reconnecting. Single long-lived connection
per account (one for paper, one for live — tied to the API key).

**Handler signature:**
```python
from alpaca.trading.stream import TradingStream

stream = TradingStream(api_key, secret_key, paper=True)

async def on_trade_update(data):
    # data.order.id, data.order.status, data.order.filled_qty, data.order.filled_avg_price
    # data.event: 'new' | 'fill' | 'partial_fill' | 'canceled' | 'expired' | 'rejected'
    ...

stream.subscribe_trade_updates(on_trade_update)
await stream.run()  # blocks until stream.stop()
```

**Attachment point (future):** inside `WatchLoop.run_async()` as a
`asyncio.create_task(stream.run())`, with the handler calling
`self._dispatch("on_fill", data)`. This requires the asyncio-handler
refactor sprint (`sprint-asyncio-handler-refactor.md`) to have shipped
first — attaching an async task to a synchronous watch loop is not clean.

### 2. `alpaca.data.live.stock.StockDataStream`

**Subscribes to:** minute bars, trades, quotes for a list of symbols.

**Transport:** WebSocket, same reconnection model.

**Handler signature:**
```python
from alpaca.data.live.stock import StockDataStream

stream = StockDataStream(api_key, secret_key)

async def on_minute_bar(bar):
    # bar.symbol, bar.timestamp, bar.open, bar.high, bar.low, bar.close, bar.volume
    ...

stream.subscribe_bars(on_minute_bar, "AAPL", "MSFT", ...)
await stream.run()
```

**Attachment point (future):** same pattern — `asyncio.create_task` inside
the async watch loop. Handler dispatches to `on_minute_bar` event, which
can be consumed by either:
- A live writer into the existing `minute_bars` table (replacing the
  nightly yfinance batch with streaming once Phase 6 is live).
- The intraday signal engine that generates entries.

---

## Subscription lifecycle

### Per-ticker subscribe / unsubscribe

`StockDataStream.subscribe_bars(handler, *symbols)` can be called multiple
times — symbols accumulate. `unsubscribe_bars(*symbols)` drops specific
ones. Typical Phase 6 pattern:

```python
# At premarket: subscribe to today's universe
stream.subscribe_bars(on_minute_bar, *todays_universe)

# At post-close: drop everything
stream.unsubscribe_bars(*todays_universe)
```

S&P 100 is 102 tickers. Well within Alpaca's per-stream symbol limit
(30 symbols per connection on the free tier; paid / Algo+ supports more).
If Arcis stays free-tier, Phase 6 needs to chunk the universe across
multiple `StockDataStream` connections or upgrade.

**Action item (Phase 6 blocker):** verify current Alpaca subscription
tier and plan limits.

### Reconnect behavior

Both `TradingStream` and `StockDataStream` auto-reconnect on WebSocket
drops with exponential backoff. Application code should be idempotent —
after reconnect, subscriptions are re-established automatically (the
client re-subscribes based on its internal state).

**Gotcha:** if the process is killed mid-session, in-flight messages may
be lost. For `TradingStream` this is important — a missed fill event
means the local shadow_trade stays "open" when the Alpaca side is
closed. Mitigation: on startup, reconcile via REST `GetOrdersRequest`
and only then start streaming.

---

## Integration points in the existing codebase

Post-refactor watch loop (after `sprint-asyncio-handler-refactor.md`):

```python
# Phase 6 bootstrap — NOT in this sprint
from alpaca.trading.stream import TradingStream
from alpaca.data.live.stock import StockDataStream

class WatchLoop:
    async def run_async(self):
        ...
        if self.config.get("intraday_desk", {}).get("enabled"):
            self._trading_stream = TradingStream(api_key, secret_key, paper=True)
            self._data_stream = StockDataStream(api_key, secret_key)
            self._trading_stream.subscribe_trade_updates(self._on_trade_update)
            self._data_stream.subscribe_bars(self._on_minute_bar, *self._universe())
            asyncio.create_task(self._trading_stream.run())
            asyncio.create_task(self._data_stream.run())

    async def _on_trade_update(self, data):
        await self._dispatch("on_fill", data)

    async def _on_minute_bar(self, bar):
        await self._dispatch("on_minute_bar", bar)
```

Then Phase 6 intraday signal files register handlers via `@watch_loop.on(...)`.

---

## Prerequisites for Phase 6 intraday desk

Before streaming can be wired:

1. **Asyncio handler refactor sprint** — `sprint-asyncio-handler-refactor.md`
   must land so `WatchLoop` has a `run_async()` entrypoint and a `_dispatch`
   registry.
2. **`minute_bars` table** — shipped v0.23.0 (`sprint-1min-bar-collection`).
   Streaming can backfill into the same table with `INSERT OR REPLACE`.
3. **Alpaca subscription tier check** — confirm symbol-per-connection
   limit vs. S&P 100 universe size.
4. **Order-idempotency hardening** — address Gap 2 in the current
   best-practices audit (`client_order_id` on every submit). Intraday
   order volume will amplify the network-retry risk.
5. **Connection supervisor** — a small module (`src/streaming/supervisor.py`,
   future) that monitors the WebSocket streams, re-starts them on hard
   disconnect, and reconciles against REST on startup.

Items 1-4 are tracked; item 5 is a Phase 6 implementation detail and will
be scoped in the Phase 6 sprint.

---

## Not in scope

- The actual intraday signal generation logic (separate model).
- VWAP reversion / microstructure features (separate sprint once minute
  bars accumulate to 1+ months of history).
- Multi-account streaming (paper + live simultaneously) — current
  architecture uses one account per process.
- Options-chain streaming (`OptionDataStream` exists but not needed for
  the intraday desk scope).
