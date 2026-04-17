"""Handler registry mixin for WatchLoop (Phase A of asyncio refactor).

Provides event-subscription + async dispatch primitives so WatchLoop can
grow handler wiring (`on_tick`, `on_fill`, `on_minute_bar`) without
bloating `src/scheduler/watch.py` further. Phase B will move existing
time-window blocks into `_maybe_*` handlers registered on `on_tick`;
Phase 6 streaming work will attach handlers for Alpaca TradingStream /
StockDataStream events.

Called by: scheduler.watch (WatchLoop inherits the mixin)
Calls: none
Owns tables: none
Config keys: none
Tests: tests/test_watch_handler_registry.py
"""

import asyncio
import logging
import signal
import threading
from collections.abc import Callable

logger = logging.getLogger(__name__)


class HandlerRegistryMixin:
    """Mixin providing a `{event: [handler, ...]}` registry + async dispatch.

    Host class contract:
        - `self._handlers: dict[str, list[Callable]]` must be initialized in
          `__init__` before `on()` or `_dispatch()` are called.
        - `self._run_sync_body()` must be defined for `run_async()` to call.
    """

    def run(self):
        """Sync entrypoint — drives the asyncio loop (Phase A of asyncio refactor)."""
        if threading.current_thread() is threading.main_thread():
            signal.signal(
                signal.SIGTERM,
                lambda signum, frame: setattr(self, "_shutdown_requested", True),
            )
        asyncio.run(self.run_async())

    async def run_async(self):
        """Async entrypoint. Runs the sync body in a worker thread for now."""
        await asyncio.to_thread(self._run_sync_body)

    def on(self, event: str):
        """Register a handler for an event type (decorator or direct call).

        Sync and coroutine handlers both work. Sync handlers are wrapped in
        `asyncio.to_thread` at dispatch time so they never block the loop.
        """
        def decorator(func: Callable) -> Callable:
            self._handlers.setdefault(event, []).append(func)
            return func
        return decorator

    async def _dispatch(self, event: str, *args, **kwargs) -> None:
        """Run every registered handler for `event` in registration order.

        Handler exceptions are logged and swallowed so one broken handler
        cannot kill siblings or the event loop — mirrors the `_safe_run`
        contract used by the pre-refactor synchronous dispatch.
        """
        for handler in self._handlers.get(event, []):
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(*args, **kwargs)
                else:
                    await asyncio.to_thread(handler, *args, **kwargs)
            except Exception as exc:
                logger.error(
                    "[WATCH] Handler %s for event %s failed: %s",
                    getattr(handler, "__name__", repr(handler)), event, exc,
                )

    def _dispatch_sync(self, event: str, *args, **kwargs) -> None:
        """Sync-context dispatch for callers already in a worker thread.

        Phase B uses this inside `_run_sync_body` so the sync tick loop can
        fire registered handlers without needing to hop back to the event
        loop via `asyncio.run_coroutine_threadsafe`. Sync handlers run
        directly; coroutine handlers get a short-lived asyncio.run wrap.
        Exceptions are still logged + swallowed per the `_dispatch` contract.
        """
        for handler in self._handlers.get(event, []):
            try:
                if asyncio.iscoroutinefunction(handler):
                    asyncio.run(handler(*args, **kwargs))
                else:
                    handler(*args, **kwargs)
            except Exception as exc:
                logger.error(
                    "[WATCH] Handler %s for event %s failed: %s",
                    getattr(handler, "__name__", repr(handler)), event, exc,
                )
