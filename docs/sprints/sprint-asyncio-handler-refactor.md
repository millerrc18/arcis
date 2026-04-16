# Sprint: asyncio handler refactor — watch loop restructure for intraday optionality

**Authority:** intraday feasibility report (`docs/research/deep-research/intraday-desk-feasibility-report.md`) Phase 1 decision #1
**Effort:** 2-3 days CC time (non-trivial refactor)
**Branch:** `refactor/asyncio-handler-watch-loop` (follow-up sprint; spec on `docs/asyncio-refactor-spec`)
**Tag on merge:** minor bump (behavior unchanged but architecture shifts) — e.g. v0.23.0 or later
**Priority:** MEDIUM (preserves intraday optionality; not time-critical until Phase 6)

---

## Goal

Replace the current synchronous 60-second `time.sleep`-based poll loop in `src/scheduler/watch.py` with an asyncio event loop that dispatches to registered handler functions (`on_daily_bar`, `on_fill`, `on_signal`, `on_schedule_tick`). Preserve all existing behavior byte-for-byte. Enable Phase 6 intraday desk to plug minute-bar and fill-stream handlers into the same loop without a second rewrite.

**This is a pure structural refactor.** No new features, no new scans, no new scheduled tasks. The goal is that the post-refactor WatchLoop behaves identically to the pre-refactor one, with the only observable difference being the ability to add handler registrations for future streaming work.

---

## Current architecture (audited 2026-04-16)

File: `src/scheduler/watch.py` — **2,023 lines** (well over the 400-line suggested cap; pre-existing debt).

Key observations:

- `WatchLoop.run()` is a single top-level `while True:` loop at line 1036.
- `time.sleep(60)` at line 1747 — the core 60-second tick.
- No `asyncio`, no `async def`, no `await` anywhere in this file or in any other scheduler file. The only asyncio in the entire `src/` tree is in `src/api/websocket.py:56,62,64` for the FastAPI WebSocket broadcaster (compatible but separate).
- Task dispatch happens via helper methods on the WatchLoop class: `_run_scan`, `_run_mr_scan`, `_run_morning_watchlist`, `_run_eod_recap`, `_run_daily_audit`, `_run_training_collection`, `_run_bracket_health_check`, `_run_postclose_reconciliation`. Each is called conditionally from inside `run()` based on the current ET time.
- All synchronous. Most sleeping/blocking happens inside those helper methods (yfinance calls, LLM inference, DB writes).
- `_safe_run(name, func)` at line 1769 is the exception boundary — it wraps a callable and adds per-task exponential backoff. That's the natural extension point for a handler registry.

**Pre-existing debt** (NOT addressed by this sprint):

- The 2,023 line size. Splitting is a separate sprint.
- Some cyclomatic complexity inside `run()` — 30+ time-window checks.
- `_safe_run` is a class method, not a decorator. Handlers would benefit from decorator-style registration.

This sprint is **additive + structural**. It does not reduce file size and does not refactor the time-window logic.

---

## Target architecture

Event-loop-based with a handler registry. Pseudocode:

```python
# src/scheduler/watch.py (post-refactor, still the same file)

import asyncio

class WatchLoop:
    def __init__(self, ...):
        ...
        self._handlers: dict[str, list[Callable]] = defaultdict(list)
        # Populated below via @self.on("event_name") decorators or direct register()

    def on(self, event: str):
        """Decorator / function to register a handler for an event type."""
        def decorator(func):
            self._handlers[event].append(func)
            return func
        return decorator

    async def _dispatch(self, event: str, *args, **kwargs):
        """Call every registered handler for `event`, in registration order."""
        for handler in self._handlers.get(event, []):
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(*args, **kwargs)
                else:
                    # Wrap sync handlers in asyncio.to_thread to avoid blocking the event loop.
                    await asyncio.to_thread(handler, *args, **kwargs)
            except Exception as e:
                logger.error("[WATCH] Handler %s for %s failed: %s", handler.__name__, event, e)
                # Per-task backoff still applies — delegate to _safe_run wrapper pattern.

    async def run_async(self):
        """Main event loop. Replaces the synchronous run()."""
        self._acquire_lock()
        self._print_banner()
        self._ensure_all_tables()
        self._register_default_handlers()   # Wires existing _run_scan etc. to tick events

        while not self._shutdown_requested:
            now = datetime.now(ET)
            await self._dispatch("on_tick", now)     # Every 60s
            # Today's events fire inside handlers that check time windows themselves,
            # mirroring the current if/elif chain. This keeps behavior byte-identical.
            await asyncio.sleep(60)

    def run(self):
        """Synchronous entrypoint preserved for NSSM / main.py backward compat."""
        asyncio.run(self.run_async())
```

Existing helper methods stay as-is and are registered at startup:

```python
def _register_default_handlers(self):
    self.on("on_tick")(self._maybe_run_morning_watchlist)
    self.on("on_tick")(self._maybe_run_scan)
    self.on("on_tick")(self._maybe_run_mr_scan)
    self.on("on_tick")(self._maybe_run_eod_recap)
    self.on("on_tick")(self._maybe_run_daily_audit)
    # ... etc. — one `_maybe_*` per existing time-window block.
```

Each `_maybe_*` internally does:

```python
def _maybe_run_scan(self, now):
    if self._should_scan(now):
        self._safe_run("scan", self._run_scan)
```

Which is a direct extract of the body of the current `run()` for that time window.

**Phase 6 extension point (future sprint):**

```python
# In a Phase 6 intraday file — outside this refactor's scope:
@watch_loop.on("on_minute_bar")
async def record_bar(bar):
    await store_bar(bar)

@watch_loop.on("on_fill")
async def handle_fill(fill):
    await update_trade_status(fill)
```

And the bar/fill events get fed in from `StockDataStream.subscribe_bars` + `TradingStream.subscribe_trade_updates` subscribers running as separate asyncio tasks.

---

## Migration path

### Phase A — Introduce handler registry (no behavior change)

1. Add `self._handlers`, `on()` decorator, and `_dispatch()` to `WatchLoop`.
2. Add `run_async()` as a parallel entrypoint alongside existing `run()`.
3. In `run_async()`, immediately delegate back to the old `run()` loop body — literally wrap it unchanged inside an `async def`. Use `asyncio.to_thread(self._run_one_tick)` if needed.
4. Existing entry via `main.py` still calls `WatchLoop.run()`, which now delegates to `asyncio.run(self.run_async())`.
5. **Observable behavior: identical.** The event loop is there but no handlers are registered yet; the old code runs inside one synchronous tick function.

### Phase B — Extract each time-window block into a `_maybe_*` handler

6. For each `if/elif` block inside the current `run()`, extract to a `_maybe_<name>` method that takes `now` and calls `_safe_run` if the time window matches.
7. Register each `_maybe_*` to `"on_tick"` in `_register_default_handlers`.
8. Replace the inline chain in the async tick function with `await self._dispatch("on_tick", now)`.

### Phase C — Lock in via tests

9. Add integration test that constructs a WatchLoop with a mocked clock, advances it through a 24-hour cycle, and asserts every existing task fires at the right time-window.
10. Add unit test for the handler registry: `on()` appends, `_dispatch()` runs in order, exceptions in one handler don't stop others.

### What is intentionally NOT done in this sprint

- Do NOT convert existing `_run_*` methods to `async def`. They continue to be sync; `_dispatch` wraps them via `asyncio.to_thread`.
- Do NOT add any streaming subscriptions. That's Phase 6.
- Do NOT split watch.py into multiple files. Pre-existing debt.

---

## Risk assessment

| Risk | Probability | Mitigation |
|---|---|---|
| Subtle timing drift (handler registry introduces µs-level delays) | Low | The bottleneck is 60s sleep, not dispatch overhead. |
| Exception in one `_maybe_*` stops later handlers | Medium | `_dispatch` wraps each call in try/except. Log + continue. Matches current `_safe_run` semantics. |
| NSSM service fails to start after the async wrap | Low | `run()` is preserved as the entry function; `asyncio.run` is standard on Python 3.11+. Ubuntu-targeted `systemd` in Phase 2 hardware plan also compatible. |
| Dashboard/FastAPI integration (already async) confused by a second event loop | Medium | FastAPI runs in its own uvicorn worker process; WatchLoop is a separate process. No shared event loop. Verified by current `src/api/websocket.py` usage pattern — FastAPI's loop is accessed via `asyncio.get_running_loop()` inside the request handler, never from WatchLoop. |
| Hidden `threading.Lock` or `time.sleep` calls in helper methods that deadlock under `asyncio.to_thread` | Medium | Extensive pre-refactor tests + `test_watch_bootstrap.py` + `test_watch_resilience.py` should catch regressions. If found, wrap the specific helper in a named executor thread pool with size=1 to serialize. |

**Biggest operational risk:** the existing tests are synchronous and rely on the synchronous `run()` path. They may need `asyncio.run` wrappers or pytest-asyncio fixtures. Estimated test-update effort: half a day.

---

## Compatibility matrix

### Already async — no change needed

- `src/api/websocket.py` — FastAPI WebSocket broadcaster. Separate process, separate loop.
- `src/api/*` — FastAPI uvicorn worker. Process-level separation.

### Currently synchronous, will remain synchronous (wrapped in `asyncio.to_thread`)

- All `_run_*` helpers in WatchLoop.
- `src/services/scan_service.py::run_scan`
- `src/services/mr_scan_service.py::run_mr_scan`
- `src/shadow_trading/executor.py::open_shadow_trade` and all exit paths
- `src/shadow_trading/reconcile.py::reconcile_paper_trades`
- yfinance calls everywhere
- SQLite writes

### Windows NSSM service compatibility

NSSM spawns `python -m src.main startup` which calls `WatchLoop(config).run()`. Post-refactor, `run()` calls `asyncio.run(self.run_async())`. NSSM doesn't care — it just sees one process. Verified by the existing `src/api/websocket.py` using `asyncio.run()` pattern already.

---

## Pre-Flight Checks

```bash
# 1. Line count of watch.py (establish baseline, target does not exceed).
wc -l src/scheduler/watch.py
# Expected: ~2,023.

# 2. Verify no new asyncio dependencies beyond stdlib.
grep -rn "import asyncio" src/scheduler/ 2>/dev/null | head
# Expected: empty (intentional — we add it in this sprint).

# 3. Verify _safe_run is the only exception wrapper in the dispatch path.
grep -n "_safe_run\|def _run_" src/scheduler/watch.py | head

# 4. Python version check.
python --version
# Expected: 3.11+ (required for asyncio.to_thread and asyncio.TaskGroup).

# 5. Test baseline.
pytest tests/test_watch_bootstrap.py tests/test_watch_resilience.py tests/test_watch_import.py -v
# All must pass pre-refactor.
```

---

## Task List

### Task 1 — Add handler registry + `run_async` wrapper (Phase A)

Additive. Old `run()` still works; `run_async()` just wraps it. Smallest possible diff to introduce the event-loop infrastructure.

### Task 2 — Extract time-window blocks into `_maybe_*` handlers (Phase B)

30+ small extractions. Each is a text-move + wrap-in-`if`. Test after each 5-10 extractions.

### Task 3 — Wire handlers via `_register_default_handlers` (Phase B continued)

Replace the inline if/elif chain in `run()` with a `_dispatch("on_tick")` call. This is the flip point — before it, behavior is identical; after, it's async-dispatched.

### Task 4 — Tests

- Unit tests for `on()` / `_dispatch()`.
- Integration test with mocked clock advancing through 24h, asserting every existing task fires at the right ET time.
- Update existing `test_watch_*` to use `asyncio.run` or pytest-asyncio where needed.

### Task 5 — Documentation

- `docs/research/async-watch-loop-handler-pattern.md` (new, ~1 page) — the handler pattern as documented API for future developers.
- CHANGELOG entry under "Changed — architecture" category.
- MASTER.md Section 11: flip `asyncio handler refactor` row from `SPEC WRITTEN` to `IMPLEMENTED`.

---

## Success Criteria

1. `watch.py` compiles and imports cleanly.
2. `pytest tests/test_watch_*` passes with no regressions (net 0 pass change; +10 new tests for the registry).
3. Full pytest suite passes.
4. `python -m src.main startup` starts the watch loop and the first scan fires at the expected ET time (manual smoke test).
5. `_register_default_handlers` wires every existing task (audit: count `if/elif` blocks in pre-refactor `run()` and verify post-refactor handler count matches).
6. NSSM service restart produces the same log lines (`[WATCH] Banner`, `[WATCH] IB integration dormant per SD#41`, etc.) post-refactor.
7. No new dependencies added to `requirements.txt`. asyncio is stdlib.
8. Pre-existing behavior byte-identical (verified by a 24h mock-clock integration test).

---

## Out-of-Scope

- Splitting `watch.py` into multiple files (separate sprint; pre-existing 2,023-line debt).
- Adding minute-bar or fill streaming subscriptions (Phase 6).
- Converting existing `_run_*` methods to `async def` (they stay sync, wrapped via `asyncio.to_thread`).
- Migrating FastAPI handlers to share the WatchLoop event loop (they're in a different process anyway).
- Any performance optimization — dispatch overhead at a 60s tick is immaterial.
- Adding a test runner with pytest-asyncio as a new dependency if existing tests can be adapted with plain `asyncio.run` wrappers.

---

## Pseudocode appendix — full post-refactor `run_async()` skeleton

```python
async def run_async(self):
    """Main asyncio event loop. Replaces the synchronous run().

    Hooks (registered via _register_default_handlers):
      on_tick — fires every 60s. All current time-window blocks use this.
      on_daily_bar — fires once per trading day after market close. (Phase 6.)
      on_minute_bar — fires every minute during market hours. (Phase 6.)
      on_fill — fires on every Alpaca fill event. (Phase 6.)
      on_signal — fires when a scan produces a packet-worthy signal. (Phase 6.)
    """
    self._acquire_lock()
    root = logging.getLogger()
    if not any(isinstance(h, DBLogHandler) for h in root.handlers):
        root.addHandler(DBLogHandler())
    self._print_banner()
    self._ensure_all_tables()
    self._configure_database()
    self._check_row_counts()
    # ... remaining startup (capital check, config overrides, etc.) stays unchanged

    self._register_default_handlers()

    while not self._shutdown_requested:
        try:
            now = datetime.now(ET)
            self._reset_daily_state_if_midnight(now)
            await self._dispatch("on_tick", now)
        except Exception as exc:
            logger.error("[WATCH] Tick failed: %s", exc, exc_info=True)
        await asyncio.sleep(60)

    self._release_lock()


def run(self):
    """Synchronous entrypoint. Preserved for NSSM / main.py compatibility."""
    asyncio.run(self.run_async())
```

---

## Commit Messages (for the follow-up execution sprint)

```
feat(scheduler): add handler registry + run_async wrapper (Phase A)
refactor(scheduler): extract time-window blocks into _maybe_* handlers (10 tasks)
refactor(scheduler): replace run() if/elif chain with on_tick dispatch
test(scheduler): handler-registry unit + mock-clock integration tests
docs: async watch loop handler pattern + MASTER.md status
```
