"""Tests for the WatchLoop handler registry (Phase A of asyncio refactor).

Covers the three additions from `sprint-asyncio-handler-refactor.md` Task 1:
- `self._handlers` registry
- `on(event)` decorator/direct-call registration
- `_dispatch(event, *args, **kwargs)` async dispatch

Does NOT exercise the full watch loop — that's the integration target for
Phase C. This file locks in the registry contract so Phase B extractions
and Phase 6 streaming handlers can rely on it.
"""

from __future__ import annotations

import asyncio

import pytest

from src.scheduler.watch import WatchLoop


def _bare_loop() -> WatchLoop:
    """Construct a WatchLoop without running it — we only need the handler API."""
    return WatchLoop(config={})


def test_handlers_registry_starts_empty():
    """A fresh WatchLoop has no registered handlers for any event."""
    loop = _bare_loop()
    assert loop._handlers == {}


def test_on_decorator_registers_handler():
    """@loop.on('event') appends the wrapped function to that event's list."""
    loop = _bare_loop()

    @loop.on("on_tick")
    def handler(now):
        return "called"

    assert loop._handlers["on_tick"] == [handler]


def test_on_direct_call_registers_handler():
    """loop.on('event')(fn) is the non-decorator form — same result."""
    loop = _bare_loop()

    def handler(now):
        return "called"

    loop.on("on_tick")(handler)
    assert loop._handlers["on_tick"] == [handler]


def test_on_preserves_registration_order():
    """Handlers fire in the order they were registered."""
    loop = _bare_loop()
    a = lambda now: None
    b = lambda now: None
    c = lambda now: None
    loop.on("on_tick")(a)
    loop.on("on_tick")(b)
    loop.on("on_tick")(c)
    assert loop._handlers["on_tick"] == [a, b, c]


def test_dispatch_runs_sync_handlers():
    """Sync handlers get wrapped in asyncio.to_thread so they never block the event loop."""
    loop = _bare_loop()
    calls = []

    def handler(now):
        calls.append(now)

    loop.on("on_tick")(handler)
    asyncio.run(loop._dispatch("on_tick", "2026-04-16T10:00"))
    assert calls == ["2026-04-16T10:00"]


def test_dispatch_runs_async_handlers():
    """Coroutine handlers are awaited directly (no thread hop)."""
    loop = _bare_loop()
    calls = []

    async def handler(now):
        calls.append(now)

    loop.on("on_tick")(handler)
    asyncio.run(loop._dispatch("on_tick", "2026-04-16T10:01"))
    assert calls == ["2026-04-16T10:01"]


def test_dispatch_calls_every_registered_handler_in_order():
    """All handlers for an event fire, in registration order, for every dispatch."""
    loop = _bare_loop()
    order: list[str] = []

    loop.on("on_tick")(lambda now: order.append("a"))
    loop.on("on_tick")(lambda now: order.append("b"))
    loop.on("on_tick")(lambda now: order.append("c"))

    asyncio.run(loop._dispatch("on_tick", None))
    assert order == ["a", "b", "c"]


def test_dispatch_swallows_handler_exceptions(caplog):
    """One broken handler must not stop siblings or propagate to the caller.

    Mirrors the `_safe_run` contract used by the synchronous dispatch:
    errors are logged and the loop continues.
    """
    loop = _bare_loop()
    after = []

    def broken(now):
        raise RuntimeError("boom")

    def works(now):
        after.append("ran")

    loop.on("on_tick")(broken)
    loop.on("on_tick")(works)

    # Must not raise.
    asyncio.run(loop._dispatch("on_tick", None))
    assert after == ["ran"], "sibling handler must still fire"


def test_dispatch_unknown_event_is_noop():
    """Dispatching an event with zero registered handlers does nothing — no error."""
    loop = _bare_loop()
    # No handlers registered; must not raise.
    asyncio.run(loop._dispatch("on_fill", "some-fill-event"))


def test_dispatch_passes_through_args_and_kwargs():
    """Positional and keyword args reach the handler unchanged."""
    loop = _bare_loop()
    captured: dict = {}

    def handler(now, *, source):
        captured["now"] = now
        captured["source"] = source

    loop.on("on_tick")(handler)
    asyncio.run(loop._dispatch("on_tick", "T", source="test"))
    assert captured == {"now": "T", "source": "test"}


def test_run_async_delegates_to_sync_body(monkeypatch):
    """run_async() must wrap _run_sync_body in asyncio.to_thread.

    Checks the Phase A invariant: run() and run_async() are both valid
    entrypoints, and the existing synchronous body runs unchanged inside
    the thread pool so the event loop stays free for future streaming tasks.
    """
    loop = _bare_loop()
    called = {"count": 0}

    def fake_body():
        called["count"] += 1

    monkeypatch.setattr(loop, "_run_sync_body", fake_body)
    asyncio.run(loop.run_async())
    assert called["count"] == 1


def test_run_delegates_to_run_async(monkeypatch):
    """Synchronous `run()` must drive `run_async()` via asyncio.run."""
    loop = _bare_loop()
    called = {"async_ran": False}

    async def fake_run_async():
        called["async_ran"] = True

    monkeypatch.setattr(loop, "run_async", fake_run_async)
    loop.run()
    assert called["async_ran"] is True


# ── _dispatch_sync — Phase B sync-context helper ──────────────────────


def test_dispatch_sync_runs_sync_handlers_inline():
    """`_dispatch_sync` must run sync handlers on the calling thread (no thread hop)."""
    loop = _bare_loop()
    import threading
    seen_threads: list[int] = []

    def handler(now):
        seen_threads.append(threading.get_ident())

    loop.on("on_tick")(handler)
    loop._dispatch_sync("on_tick", "T")
    assert len(seen_threads) == 1
    assert seen_threads[0] == threading.get_ident()


def test_dispatch_sync_runs_async_handlers_via_asyncio_run():
    """Async handlers called from sync context get wrapped in a short-lived loop."""
    loop = _bare_loop()
    calls: list[str] = []

    async def handler(now):
        calls.append(now)

    loop.on("on_tick")(handler)
    loop._dispatch_sync("on_tick", "T")
    assert calls == ["T"]


def test_dispatch_sync_swallows_handler_exceptions():
    """Same exception contract as `_dispatch` — one broken handler can't kill siblings."""
    loop = _bare_loop()
    after: list[str] = []

    def broken(now):
        raise RuntimeError("boom")

    def works(now):
        after.append("ran")

    loop.on("on_tick")(broken)
    loop.on("on_tick")(works)
    loop._dispatch_sync("on_tick", None)  # must not raise
    assert after == ["ran"]


def test_dispatch_sync_preserves_registration_order():
    """Handlers fire in registration order across the sync dispatch."""
    loop = _bare_loop()
    order: list[str] = []
    loop.on("on_tick")(lambda now: order.append("a"))
    loop.on("on_tick")(lambda now: order.append("b"))
    loop.on("on_tick")(lambda now: order.append("c"))
    loop._dispatch_sync("on_tick", None)
    assert order == ["a", "b", "c"]
