# Async Watch-Loop Handler Pattern

**Status:** Phase A landed (v0.23.1, `refactor/asyncio-handler-watch-loop`).
Phases B and C are queued as separate follow-up sprints (see end of this doc).
**Authority:** `docs/sprints/sprint-asyncio-handler-refactor.md`.
**Consumed by:** Phase 6 intraday desk (streaming handlers).

---

## What Phase A shipped

`src/scheduler/watch.py::WatchLoop` now inherits `HandlerRegistryMixin` from
`src/scheduler/handler_registry.py`. Concretely:

1. **`run()`** became a thin synchronous wrapper that drives an asyncio
   loop via `asyncio.run(self.run_async())`. Signature unchanged — every
   existing caller (`src/cli/commands.py`, NSSM, `src/main.py`) works
   without modification.
2. **`run_async()`** is the async entrypoint. Today it just delegates to
   the old synchronous body via `asyncio.to_thread(self._run_sync_body)`
   so the event loop stays free while the 60-second poll runs in a
   worker thread.
3. **`_run_sync_body()`** is the renamed body of the pre-refactor
   `run()` — 740 lines of `while True:` + time-window `if/elif` blocks,
   unchanged. Phase B will carve this up into handlers.
4. **`on(event)`** registers a handler under an event name.
5. **`_dispatch(event, *args, **kwargs)`** is the async dispatch.
   Handler exceptions are logged + swallowed so one broken handler can't
   kill siblings or the loop.

### Zero behavior change

No handlers are registered by default, so `_dispatch` is a no-op today.
The 13 existing `test_watch_*` tests pass byte-for-byte. NSSM service
behavior, daily cadence, overnight collectors, and the 4-tier scan
schedule all run exactly as they did pre-refactor.

---

## Handler pattern — how to use it

### Register a handler

```python
from src.scheduler.watch import WatchLoop

watch = WatchLoop(config=...)

# Decorator form — cleanest for module-level handlers
@watch.on("on_tick")
def log_tick(now):
    logger.debug("Tick at %s", now)

# Direct-call form — useful when the handler is a bound method
watch.on("on_fill")(watch._handle_alpaca_fill)

# Async handlers work too — awaited directly, no thread hop
@watch.on("on_minute_bar")
async def record_bar(bar):
    await store_bar_async(bar)
```

### Fire the event

```python
# Inside the async watch loop (future Phase B)
async def run_async(self):
    while not self._shutdown_requested:
        now = datetime.now(ET)
        await self._dispatch("on_tick", now)
        await asyncio.sleep(60)
```

`_dispatch` walks the registered handlers in registration order and:
- `await`s coroutine handlers directly.
- Wraps sync handlers in `asyncio.to_thread` so blocking I/O (SQLite
  writes, yfinance calls, requests) doesn't freeze the event loop.
- Catches and logs any exception, then continues to the next handler —
  mirrors the `_safe_run` contract.

### Canonical event names (convention)

| Event | Fires | Payload | Current registrant |
|---|---|---|---|
| `on_tick` | Every 60s | `now: datetime` (ET) | (Phase B) |
| `on_fill` | Alpaca order fill/partial/cancel | `data: TradeUpdate` | (Phase 6) |
| `on_minute_bar` | Live 1-min OHLCV | `bar: Bar` | (Phase 6) |
| `on_daily_bar` | Post-close | `bar: DailyBar` | (Phase 6, optional) |
| `on_signal` | Scan produces a packet | `packet: dict` | (Phase 6, optional) |

Keep events narrow and past-tense. Prefer `on_fill` over `on_trade_event`.

---

## What's NOT in Phase A

Out of scope for this sprint — queued as separate branches:

### Phase B — extract time-window blocks (`refactor/asyncio-phase-b-handler-extraction`)

The 30+ `if hour == X` blocks inside `_run_sync_body()` become `_maybe_*`
methods registered on `on_tick`. Each extraction is a text-move + wrap
in `if self._should_X(now): self._safe_run("X", self._run_X)`.

After extraction:

```python
async def run_async(self):
    self._acquire_lock()
    self._print_banner()
    self._ensure_all_tables()
    self._configure_database()
    self._register_default_handlers()
    while not self._shutdown_requested:
        now = datetime.now(ET)
        self._reset_daily_state_if_midnight(now)
        await self._dispatch("on_tick", now)
        await asyncio.sleep(60)
```

Risk: subtle timing drift across 30 blocks. Mitigation: the mocked-clock
integration test in Phase C.

### Phase C — tests (`refactor/asyncio-phase-c-mock-clock-integration`)

Mock-clock integration test that advances a WatchLoop through a 24-hour
cycle and asserts every existing task fires at the right ET time.
Requires pytest-asyncio or plain `asyncio.run` wrappers around the
existing synchronous test helpers.

### Phase 6 streaming (separate sprint — not part of this refactor)

Once Phase B + C land, Phase 6 attaches `TradingStream` /
`StockDataStream` subscribers as `asyncio.create_task(stream.run())`
inside `run_async`. Handlers dispatch via `on_minute_bar` / `on_fill`.
See `docs/research/alpaca-py-intraday-streaming-gap.md`.

---

## Contract for future work

- **Do NOT add `asyncio` imports to `watch.py` directly.** Use the mixin.
  Keeps `watch.py` line count near the 2,039 baseline (pre-existing debt).
- **Sync handlers are the default.** Convert to `async def` only when
  the handler genuinely awaits on I/O (e.g., a streaming reconnect
  path). Most existing `_run_*` methods are sync and must stay sync.
- **Registration order matters.** Handlers run sequentially in
  registration order. For independence, register via
  `asyncio.gather`-style dispatch in a future Phase D if parallel
  handler execution is ever needed.
- **One handler per concern.** Don't let a single handler grow past
  the 60-line cap. If it does, extract a helper and register the
  helper.
