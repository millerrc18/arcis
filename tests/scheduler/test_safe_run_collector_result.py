"""Tests for the T19 flip: WatchLoop._safe_run returns a CollectorResult.

Phase 5 PR-D / #72 / T19 (DD-15 r3 + DA1). Pre-flip _safe_run returned a
bare bool; post-flip it returns a CollectorResult so gating done-flag
callers branch on `.is_healthy` (CLAUDE.md §207) instead of object
truthiness. capability_health routing was dropped (kin #23 — the module is
the pull-based `table_freshness_health`, it has no `set_status` API).

The load-bearing test here is the non-vacuity guard: a gating caller must
NOT set its done-flag when _safe_run returns a `failed` CollectorResult.
Because a CollectorResult is object-truthy for EVERY status (result.py
deliberately omits __bool__), a caller that wrote `if self._safe_run(...):`
would set the flag even on failure — exactly the #623-class silent-failure
regression the `.is_healthy` flip exists to prevent.
"""

from collections import deque

from src.data_collection.result import CollectorResult
from src.scheduler.watch import WatchLoop


def _make_bare_watch_loop() -> WatchLoop:
    """A WatchLoop with only the state _safe_run touches (no heavy __init__)."""
    wl = WatchLoop.__new__(WatchLoop)
    wl._backoff = {}
    wl._consecutive_errors = 0
    wl._error_timestamps = deque(maxlen=20)
    wl._hourly_alert_sent = False
    return wl


def test_safe_run_returns_ok_collector_result_on_success():
    """A func that completes without raising yields a healthy 'ok' result."""
    wl = _make_bare_watch_loop()
    result = wl._safe_run("clean task", lambda: None)
    assert isinstance(result, CollectorResult)
    assert result.status == "ok"
    assert result.is_healthy is True


def test_safe_run_returns_failed_collector_result_on_exception():
    """A func that raises yields a 'failed' result carrying the error text."""
    wl = _make_bare_watch_loop()

    def boom():
        raise RuntimeError("collector boom")

    result = wl._safe_run("boom task", boom)
    assert isinstance(result, CollectorResult)
    assert result.status == "failed"
    assert result.is_healthy is False
    assert any("collector boom" in e for e in result.errors)
    # The failure must still be recorded for per-task backoff (#147/#231).
    assert "boom task" in wl._backoff


def test_safe_run_passes_through_func_collector_result():
    """If func itself returns a CollectorResult, _safe_run returns it verbatim
    (no synthesis) so a collector's real status/count/errors survive."""
    wl = _make_bare_watch_loop()
    real = CollectorResult.partial("edgar", 3, errors=["one item failed"])
    result = wl._safe_run("edgar", lambda: real)
    assert result is real
    assert result.status == "partial"
    assert result.is_healthy is True


def test_failed_result_is_object_truthy_so_is_healthy_is_required():
    """DD-15 r3 / result.py:27 — a 'failed' result is object-truthy. This is
    why gating callers must use .is_healthy, not `if result:`. Locks in the
    no-__bool__ contract that makes the non-vacuity guard below meaningful."""
    wl = _make_bare_watch_loop()

    def boom():
        raise RuntimeError("kaboom")

    result = wl._safe_run("t", boom)
    assert bool(result) is True          # object-truthy despite failure
    assert result.is_healthy is False    # health is via .is_healthy only


def test_gating_caller_sets_done_flag_on_healthy_result():
    """Happy path: a gating caller sets its done-flag when _safe_run succeeds."""
    wl = _make_bare_watch_loop()
    done = False
    if wl._safe_run("ok task", lambda: None).is_healthy:
        done = True
    assert done is True


def test_gating_caller_does_not_set_done_flag_on_failed_result():
    """NON-VACUITY GUARD (the whole point of the flip): a gating caller must
    NOT set its done-flag when _safe_run returns a failed result, so the next
    watch tick retries instead of locking out until midnight.

    Revert the `.is_healthy` on the production caller and this test fails: a
    bare `if self._safe_run(...):` is always truthy, so `done` would flip True
    on a failed task — the silent-failure regression the flip prevents.
    """
    wl = _make_bare_watch_loop()
    done = False

    def boom():
        raise RuntimeError("task failed")

    if wl._safe_run("failing task", boom).is_healthy:
        done = True

    assert done is False, (
        "Regression: done-flag set despite _safe_run returning a failed "
        "CollectorResult. A CollectorResult is always object-truthy — gating "
        "callers MUST branch on .is_healthy (CLAUDE.md §207), never `if result:`."
    )
    assert "failing task" in wl._backoff
