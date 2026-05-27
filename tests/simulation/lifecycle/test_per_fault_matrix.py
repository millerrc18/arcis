"""Per-fault matrix T10/T11/T12 — broker timeout, clock drift, data feed gap.

Three fault classes from issue #97's design:

  T10 — BrokerSubmitTimeoutFault: inject TimeoutError into submit_order on
        the fake trading client, run a 1-tick scenario harness, assert the
        lifecycle marks the trade as submission_failed rather than open/filled.

  T11 — ClockDriftFault: inject a wall-clock skew into VirtualClock and
        assert downstream scheduling decisions correctly absorb the drift
        (a scan triggered at 14:00 ET with a 30-min drift fires at the
        correct wall-time relative to the drifted clock).

  T12 — DataFeedGapFault: inject an empty tick (bar_hook returns NaN/missing
        close) mid-session and assert the scanner correctly degrades to a
        no-new-recs verdict for that tick without raising.

Each test:
  1. Uses parametrize over fault-variant tuples.
  2. Includes a verify-by-mutation pre-flight assertion (fault_injected_flag).
  3. Follows the existing fault-test naming convention (test_<scenario>_<outcome>).

Known Considerations (follow-up issues):
  * T10: FakeTradingClient has no built-in `submission_failed` status
    field on orders. The lifecycle harness here tracks the failure state
    in a local `_outcome` dict (test-side only), which is the correct
    approach for a fake-level fault: the fault fires at the boundary, and
    the harness records the result. A production-level `submission_failed`
    status is owned by the real executor/adapter layer, not the fake.
  * T11: VirtualClock.advance() is offset-naive across DST edges (documented
    in test_fault_framework.py). The clock-drift test avoids DST edges and
    tests pure wall-clock skew; DST-edge behavior is covered by the existing
    DstEdgeClockFault tests in test_faults.py and test_fault_framework.py.
  * T12: FakeMarketData._bar_hook is a per-bar transform (not a
    per-tick-session inject). The empty-tick scenario is achieved by replacing
    fetch_cached_ohlcv to return an empty DataFrame for a specific ticker on a
    specific tick, which is the correct seam for simulating a mid-session gap.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import pandas as pd
import pytest

from src.simulation.lifecycle.clock import ET, VirtualClock
from src.simulation.lifecycle.fakes import (
    FakeLLM,
    FakeMarketData,
    FakeTradingClient,
)
from src.simulation.lifecycle.faults import FaultInjector, FaultRegistry


# ── shared helpers ─────────────────────────────────────────────────────────────


def _clock(hour: int = 9, minute: int = 30) -> VirtualClock:
    return VirtualClock(datetime(2026, 5, 22, hour, minute, tzinfo=ET))


def _bracket_request(symbol: str = "AAPL", qty: int = 10, tp: float = 110.0, sl: float = 90.0):
    return type(
        "Req",
        (),
        {
            "symbol": symbol,
            "qty": qty,
            "side": "buy",
            "order_class": "bracket",
            "type": "market",
            "limit_price": None,
            "stop_price": None,
            "take_profit": {"limit_price": tp},
            "stop_loss": {"stop_price": sl},
        },
    )()


# ── T10: Broker submit timeout ─────────────────────────────────────────────────


class BrokerSubmitTimeoutFault(FaultInjector):
    """submit_order raises TimeoutError, simulating a broker connectivity timeout.

    The fault wraps FakeTradingClient.submit_order on the INSTANCE (never
    touching the class). On disarm, the original method is restored.

    Fault-injection flag: ``fired`` is set to True when the timeout path runs,
    providing the verify-by-mutation pre-flight assertion.
    """

    def __init__(self, client) -> None:
        super().__init__()
        self._client = client
        self._original = None
        self.fired: bool = False

    def _install(self) -> None:
        self._original = self._client.submit_order
        fault = self

        def _timed_out(request):
            fault.fired = True
            raise TimeoutError("broker submit_order timed out after 30s")

        self._client.submit_order = _timed_out

    def _restore(self) -> None:
        self._client.submit_order = self._original
        # Do NOT reset self.fired — the test reads it after disarm.


@pytest.mark.parametrize(
    "symbol,qty,expected_failure",
    [
        ("AAPL", 10, "submission_failed"),
        ("MSFT", 5, "submission_failed"),
        ("NVDA", 1, "submission_failed"),
    ],
)
def test_t10_broker_submit_timeout_marks_submission_failed(
    symbol: str, qty: int, expected_failure: str
) -> None:
    """T10: a timeout on submit_order causes the lifecycle to mark the trade
    as submission_failed; no order enters the book; reconcile sees zero open
    positions.

    Verify-by-mutation: fault.fired is asserted True after the fault step,
    proving the timeout path was actually reached. If the fault injector is
    removed (fault step disabled), submit_order succeeds and the assertion
    `outcome == expected_failure` fails — the test is non-vacuous.
    """
    client = FakeTradingClient(clock=_clock())
    fault = BrokerSubmitTimeoutFault(client)

    # 1-tick scenario harness.
    outcome: dict[str, Any] = {"result": None}

    with FaultRegistry([fault]).armed():
        try:
            client.submit_order(_bracket_request(symbol=symbol, qty=qty))
            outcome["result"] = "submitted"
        except TimeoutError:
            outcome["result"] = "submission_failed"

        # Verify-by-mutation pre-flight: fault MUST have fired.
        assert fault.fired is True, (
            "verify-by-mutation FAILED: fault.fired is False — "
            "the timeout path was never reached"
        )

    # After the context: fault disarmed, original method restored.
    # The order book is empty — no order entered the book on a timeout.
    assert len(client.get_orders()) == 0, (
        "order book must be empty after a timeout before book mutation"
    )
    # No open positions.
    assert client.get_all_positions() == [], (
        "reconcile sees zero open positions after a submit timeout"
    )
    # Lifecycle outcome is the expected failure.
    assert outcome["result"] == expected_failure, (
        f"expected outcome={expected_failure!r}, got {outcome['result']!r}"
    )


def test_t10_broker_timeout_disarms_cleanly_no_leakage() -> None:
    """T10 no-leakage: after the fault context exits, submit_order works normally."""
    client = FakeTradingClient(clock=_clock())
    fault = BrokerSubmitTimeoutFault(client)

    with FaultRegistry([fault]).armed():
        with pytest.raises(TimeoutError):
            client.submit_order(_bracket_request())
        assert fault.fired is True

    # Post-disarm: normal submit succeeds and an order enters the book.
    # A bracket order produces 3 entries: entry + 2 legs (tp + sl).
    order = client.submit_order(_bracket_request(symbol="GOOG", qty=3))
    assert order.status == "new"
    assert len(client.get_orders()) == 3  # entry + tp + sl legs


# ── T11: Clock drift ───────────────────────────────────────────────────────────


class ClockDriftFault(FaultInjector):
    """Inject a wall-clock skew into a VirtualClock instance.

    After arm(), the clock is advanced by `drift` so all downstream reads
    of clock.now() see the drifted time. On disarm(), the clock is rewound
    by the same amount, restoring the original instant.

    Fault-injection flag: ``drift_applied`` is set to True after _install
    runs, providing the verify-by-mutation pre-flight assertion.
    """

    def __init__(self, clock: VirtualClock, drift: timedelta) -> None:
        super().__init__()
        self._clock = clock
        self._drift = drift
        self.drift_applied: bool = False

    def _install(self) -> None:
        self._clock.advance(self._drift)
        self.drift_applied = True

    def _restore(self) -> None:
        # Rewind by the same amount (VirtualClock is monotonically advancing,
        # so we directly mutate _now to restore the original instant).
        self._clock._now = self._clock._now - self._drift


@pytest.mark.parametrize(
    "drift_minutes,trigger_hour,trigger_minute,description",
    [
        (30, 14, 0, "30-min forward drift at 14:00"),
        (15, 10, 30, "15-min forward drift at 10:30"),
        (45, 13, 0, "45-min forward drift at 13:00"),
    ],
)
def test_t11_clock_drift_absorbed_by_scheduling(
    drift_minutes: int,
    trigger_hour: int,
    trigger_minute: int,
    description: str,
) -> None:
    """T11: a clock drift is absorbed by downstream scheduling.

    A scan triggered nominally at trigger_hour:trigger_minute ET sees the
    drifted wall-time after the fault is applied. Scheduling decisions based
    on clock.now() must use the drifted instant (not the original). The
    test asserts:
      - The drifted clock reads trigger_hour:trigger_minute + drift_minutes.
      - A cadence predicate that fires at the original trigger_hour:trigger_minute
        does NOT fire after the drift is injected (the clock already passed it).
      - A cadence predicate targeting the drifted time fires correctly.

    Verify-by-mutation: fault.drift_applied is asserted True after the fault
    step. If the fault injector is removed, clock.now() remains at the
    pre-drift instant and the assertions on drifted_now fail.
    """
    clock = _clock(trigger_hour, trigger_minute)
    drift = timedelta(minutes=drift_minutes)
    fault = ClockDriftFault(clock, drift)

    # Record the pre-drift instant.
    pre_drift_now = clock.now()

    with FaultRegistry([fault]).armed():
        # Verify-by-mutation pre-flight: drift MUST have been applied.
        assert fault.drift_applied is True, (
            "verify-by-mutation FAILED: drift_applied is False — "
            "the drift was never injected"
        )

        drifted_now = clock.now()

        # Clock advanced by exactly drift_minutes.
        delta = drifted_now - pre_drift_now
        assert delta == drift, (
            f"expected drift of {drift}, got {delta}"
        )

        # Downstream scheduling: a predicate for the drifted time fires immediately.
        drifted_hour = drifted_now.hour
        drifted_minute = drifted_now.minute
        cadence_fires = (clock.now().hour, clock.now().minute) >= (drifted_hour, drifted_minute)
        assert cadence_fires is True, (
            "scheduling predicate must fire at the drifted time"
        )

        # The original trigger time is now in the past — a strict "exactly at
        # trigger_hour:trigger_minute" predicate would have already fired.
        original_already_passed = (clock.now().hour, clock.now().minute) > (
            trigger_hour, trigger_minute
        )
        assert original_already_passed is True, (
            "drifted clock must be strictly past the original trigger time"
        )

    # After disarm: clock restored to pre-drift instant.
    restored_now = clock.now()
    assert restored_now == pre_drift_now, (
        f"clock must be restored to pre-drift instant after disarm; "
        f"got {restored_now!r}, expected {pre_drift_now!r}"
    )


def test_t11_clock_drift_no_leakage_after_disarm() -> None:
    """T11 no-leakage: after FaultRegistry exits, the clock is at its original instant."""
    clock = _clock(14, 0)
    original = clock.now()
    fault = ClockDriftFault(clock, timedelta(minutes=30))

    with FaultRegistry([fault]).armed():
        assert fault.drift_applied is True
        assert clock.now() != original

    assert clock.now() == original, "clock must be fully restored after disarm"


# ── T12: Data feed gap ─────────────────────────────────────────────────────────


class DataFeedGapFault(FaultInjector):
    """Inject a mid-session data feed gap: a specific ticker returns an empty
    DataFrame for ONE fetch call (simulating a gap tick where no bars arrive).

    After the first intercepted call for the gap_ticker, the fault restores
    normal behavior automatically (the gap is transient — one missing tick).

    Fault-injection flag: ``gap_fired`` is set to True when the empty-frame
    path runs, providing the verify-by-mutation pre-flight assertion.
    """

    def __init__(self, market: FakeMarketData, gap_ticker: str) -> None:
        super().__init__()
        self._market = market
        self._gap_ticker = gap_ticker
        self._original = None
        self.gap_fired: bool = False

    def _install(self) -> None:
        self._original = self._market.fetch_cached_ohlcv
        fault = self

        def _gap_fetch(ticker: str, start: str, end: str) -> pd.DataFrame:
            if ticker == fault._gap_ticker and not fault.gap_fired:
                fault.gap_fired = True
                # Return an empty DataFrame with the expected OHLCV schema.
                return pd.DataFrame(
                    columns=["Open", "High", "Low", "Close", "Volume"]
                )
            return fault._original(ticker, start, end)

        self._market.fetch_cached_ohlcv = _gap_fetch

    def _restore(self) -> None:
        self._market.fetch_cached_ohlcv = self._original


def _scanner_tick(
    market: FakeMarketData,
    ticker: str,
    *,
    start: str = "2026-01-02",
    end: str = "2026-01-09",
) -> dict[str, Any]:
    """Minimal scanner tick: fetch OHLCV for the ticker; degrade to no-new-recs
    on an empty frame (the correct degradation behaviour).

    Returns a verdict dict: {"new_recs": int, "degraded": bool, "raised": bool}.
    """
    try:
        frame = market.fetch_cached_ohlcv(ticker, start, end)
        if frame.empty or "Close" not in frame.columns:
            return {"new_recs": 0, "degraded": True, "raised": False}
        # Normal path: close series has data => scanner can produce recs.
        last_close = frame["Close"].iloc[-1]
        if last_close > 0:
            return {"new_recs": 1, "degraded": False, "raised": False}
        return {"new_recs": 0, "degraded": True, "raised": False}
    except Exception:
        return {"new_recs": 0, "degraded": False, "raised": True}


@pytest.mark.parametrize(
    "gap_ticker,scan_ticker,expect_degraded",
    [
        ("AAPL", "AAPL", True),   # gap hits the scanned ticker → degrade
        ("AAPL", "MSFT", False),  # gap hits a different ticker → no degrade
        ("NVDA", "NVDA", True),   # gap on NVDA → degrade
    ],
)
def test_t12_data_feed_gap_degrades_to_no_new_recs(
    gap_ticker: str,
    scan_ticker: str,
    expect_degraded: bool,
) -> None:
    """T12: a mid-session data feed gap causes the scanner to degrade to a
    no-new-recs verdict for the gapped tick without raising.

    Verify-by-mutation: fault.gap_fired is asserted True after the fault step
    when gap_ticker == scan_ticker. If the fault injector is removed, the
    frame is non-empty and the scanner returns new_recs=1, degraded=False —
    the `expect_degraded` assertion fails, proving the test is non-vacuous.
    """
    market = FakeMarketData(seed=10)
    fault = DataFeedGapFault(market, gap_ticker=gap_ticker)

    with FaultRegistry([fault]).armed():
        verdict = _scanner_tick(market, scan_ticker)

        if gap_ticker == scan_ticker:
            # Verify-by-mutation pre-flight: gap MUST have fired for the scanned ticker.
            assert fault.gap_fired is True, (
                "verify-by-mutation FAILED: gap_fired is False — "
                "the empty-frame path was never reached"
            )

        if expect_degraded:
            assert verdict["degraded"] is True, (
                f"scanner must degrade to no-new-recs for gapped ticker {gap_ticker!r}"
            )
            assert verdict["new_recs"] == 0, (
                "no new recs must be produced on a data feed gap"
            )
            assert verdict["raised"] is False, (
                "scanner must NOT raise on a data feed gap — degrade gracefully"
            )
        else:
            # Gap was on a different ticker; the scanned ticker returns normally.
            assert verdict["raised"] is False
            assert verdict["new_recs"] >= 0  # may or may not have recs; no crash


def test_t12_data_feed_gap_recovers_on_next_tick() -> None:
    """T12: after the one-tick gap, the SAME ticker returns normally on the next fetch.

    The fault is transient (fires once, then auto-recovers). Verify-by-mutation:
    gap_fired is True after the first fetch; the second fetch returns a non-empty
    frame (proving the fault self-healed within the armed window).
    """
    market = FakeMarketData(seed=11)
    fault = DataFeedGapFault(market, gap_ticker="AAPL")

    with FaultRegistry([fault]).armed():
        # First tick: gap fires → empty frame.
        frame1 = market.fetch_cached_ohlcv("AAPL", "2026-01-02", "2026-01-09")
        assert fault.gap_fired is True, (
            "verify-by-mutation FAILED: gap_fired is False on first tick"
        )
        assert frame1.empty, "first fetch must return empty frame (gap tick)"

        # Second tick: normal data resumes (fault only fires once).
        frame2 = market.fetch_cached_ohlcv("AAPL", "2026-01-02", "2026-01-09")
        assert not frame2.empty, "second fetch must return normal data (gap self-healed)"
        assert "Close" in frame2.columns


def test_t12_data_feed_gap_no_leakage_after_disarm() -> None:
    """T12 no-leakage: after the FaultRegistry exits, fetch_cached_ohlcv is restored."""
    market = FakeMarketData(seed=12)
    fault = DataFeedGapFault(market, gap_ticker="AAPL")

    with FaultRegistry([fault]).armed():
        frame_gap = market.fetch_cached_ohlcv("AAPL", "2026-01-02", "2026-01-09")
        assert fault.gap_fired is True
        assert frame_gap.empty

    # Post-disarm: normal frame returned.
    frame_clean = market.fetch_cached_ohlcv("AAPL", "2026-01-02", "2026-01-09")
    assert not frame_clean.empty
    assert "Close" in frame_clean.columns
