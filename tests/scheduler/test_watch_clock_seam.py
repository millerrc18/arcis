"""Proof tests for the WatchLoop clock/sleep injection seam (lifecycle-sim T3).

The simulator needs to drive WatchLoop's brain-clock and pace its main loop
without real wall-clock time. These tests pin the contract:

  - Default construction (no kwargs) preserves prod behavior exactly:
    _clock returns a tz-aware ET datetime ~= datetime.now(ET), and
    _sleep IS time.sleep (the real one).
  - Injected clock/sleep are used verbatim: _clock() returns the injected
    fixed datetime, and _sleep routes to the injected fake (no real sleep).
"""
import time
from datetime import datetime

import pytest

from src.scheduler.watch import ET, WatchLoop


def _minimal_loop(**kwargs) -> WatchLoop:
    # __init__ only reads config dict keys; no DB / heavy deps are touched.
    return WatchLoop(config={}, **kwargs)


def test_default_clock_is_now_et_equivalent():
    loop = _minimal_loop()
    before = datetime.now(ET)
    got = loop._clock()
    after = datetime.now(ET)
    # tz-aware, in ET, and bracketed by two real now(ET) reads.
    assert got.tzinfo is not None
    assert got.tzinfo == ET
    assert before <= got <= after


def test_default_sleep_is_real_time_sleep():
    loop = _minimal_loop()
    assert loop._sleep is time.sleep


def test_injected_clock_returns_fixed_datetime():
    fixed = datetime(2026, 5, 22, 9, 30, 0, tzinfo=ET)
    loop = _minimal_loop(clock=lambda: fixed)
    assert loop._clock() is fixed
    assert loop._clock() == fixed


def test_injected_sleep_is_called_not_real_sleep():
    calls = []
    loop = _minimal_loop(sleep=lambda secs: calls.append(secs))
    # Injected fake must be the bound seam, not real time.sleep.
    assert loop._sleep is not time.sleep
    loop._sleep(60)
    assert calls == [60]
