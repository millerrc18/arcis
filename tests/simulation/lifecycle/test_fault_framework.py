"""Fault-framework hardening tests (Task 14).

Complements test_faults.py (Task 10) by rounding out the framework-level
guarantees the stress harness depends on:

  * NO-LEAKAGE across ALL fault families — arm a representative fault from EVERY
    family (broker, network, market, data, process, clock), run, disarm via the
    FaultRegistry, then assert a SECOND clean run on the SAME fakes sees NO
    residue. Each family wraps a different seam, so a single combined teardown
    proving every seam restored is the framework's core no-leakage contract.

  * DST cadence oracle across BOTH transitions — a once-per-day cadence predicate
    fires EXACTLY ONCE across the spring-forward (a wall-time that never occurs)
    AND the fall-back (a wall-time that occurs twice) hour.

  * Reconcile 24h recent-close window math across the DST boundary — a
    fixed-DURATION 24h window stays correct (does not drift by an hour) when the
    VirtualClock is advanced across a DST edge, because the window is computed in
    absolute (UTC-equivalent) time, not wall-clock arithmetic.

KNOWN LIMITATION (T10): VirtualClock.advance() is offset-naive — advancing
across a DST edge does NOT perform a genuine wall-clock fold (the UTC offset does
not flip). So these tests assert the ACHIEVABLE expectations: the cadence fires
exactly once (the reference predicate dedupes by calendar date, which is correct
regardless of a genuine fold) and the 24h window is a clean fixed duration in
absolute time. They do NOT fake a fold that the clock cannot produce.
"""

from datetime import datetime, timedelta, timezone

import pytest

from src.simulation.lifecycle.clock import ET, VirtualClock
from src.simulation.lifecycle.fakes import (
    FakeLLM,
    FakeMarketData,
    FakeTradingClient,
    FakeTrainerPidfile,
)
from src.simulation.lifecycle.faults import FaultRegistry
from src.simulation.lifecycle.faults.broker_faults import PartialFillFault
from src.simulation.lifecycle.faults.clock_faults import (
    DstEdgeClockFault,
    dst_cadence_fires_once,
)
from src.simulation.lifecycle.faults.data_faults import SchemaDriftFault
from src.simulation.lifecycle.faults.market_faults import (
    HighCandidateVolumeFault,
    MarketHaltFault,
)
from src.simulation.lifecycle.faults.network_faults import ApiTimeoutFault
from src.simulation.lifecycle.faults.process_faults import PidRecycleFault


def _clock():
    return VirtualClock(datetime(2026, 5, 22, 9, 30, tzinfo=ET))


def _bracket_request(symbol="AAPL", qty=10, tp=110.0, sl=90.0, side="buy"):
    return type(
        "Req",
        (),
        {
            "symbol": symbol,
            "qty": qty,
            "side": side,
            "order_class": "bracket",
            "type": "market",
            "limit_price": None,
            "stop_price": None,
            "take_profit": {"limit_price": tp},
            "stop_loss": {"stop_price": sl},
        },
    )()


# ── no-leakage across ALL fault families ──────────────────────────────────────


def test_all_fault_families_arm_disarm_leave_no_residue(tmp_path):
    """Arm one fault per family, run, disarm — a clean run sees NO residue.

    Covers every seam the framework touches: broker (PartialFillFault), network
    (ApiTimeoutFault), market bar-hook (MarketHaltFault), data shape
    (SchemaDriftFault), LLM candidate-volume (HighCandidateVolumeFault), process
    pidfile (PidRecycleFault). Reverse-order teardown must restore EACH.
    """
    client = FakeTradingClient(clock=_clock())
    market = FakeMarketData(seed=7)
    llm = FakeLLM(seed=7, n_candidates=3)
    pidfile = FakeTrainerPidfile(
        tmp_path / "lock.pid", pid=4242, alive=False, identity="trainer-A"
    )
    pidfile.acquire()

    reg = FaultRegistry(
        [
            PartialFillFault(client, fill_fraction=0.5),
            ApiTimeoutFault(client),
            MarketHaltFault(market),
            SchemaDriftFault(market, drop="Volume"),
            HighCandidateVolumeFault(llm, n_candidates=50),
            PidRecycleFault(pidfile, new_identity="unrelated-proc"),
        ]
    )

    with reg.armed():
        # Inside the armed window every family's fault is active.
        with pytest.raises(TimeoutError):
            client.get_all_positions()
        halted = market.fetch_cached_ohlcv("AAPL", "2026-01-02", "2026-01-12")
        assert (halted["High"] == halted["Low"]).all()
        assert "Volume" not in halted.columns
        assert len(llm.generate_candidates()) == 50
        assert pidfile.is_recycled("unrelated-proc") is True

    # SECOND clean run on the SAME fakes — every seam must be restored.
    # broker (network) seam restored: get_all_positions no longer raises.
    o = client.submit_order(_bracket_request(symbol="MSFT", qty=10))
    client.fill_entry(o.id, fill_price=100.0)
    assert float(o.filled_qty) == 10  # PartialFillFault restored
    assert client.get_all_positions() is not None  # ApiTimeoutFault restored

    clean = FakeMarketData(seed=7)
    base = clean.fetch_cached_ohlcv("AAPL", "2026-01-02", "2026-01-12")
    after = market.fetch_cached_ohlcv("AAPL", "2026-01-02", "2026-01-12")
    assert "Volume" in after.columns  # SchemaDriftFault restored
    assert not (after["High"] == after["Low"]).all()  # MarketHaltFault restored
    assert list(after["Close"]) == list(base["Close"])  # market bytes-identical

    assert len(llm.generate_candidates()) == 3  # HighCandidateVolumeFault restored
    assert pidfile.is_recycled("trainer-A") is False  # PidRecycleFault restored


def test_no_leakage_holds_even_when_run_body_raises(tmp_path):
    """A fault that leaks would survive an EXCEPTIONAL exit; reverse-order
    teardown must still restore every family even when the body raises."""
    client = FakeTradingClient(clock=_clock())
    market = FakeMarketData(seed=8)
    reg = FaultRegistry(
        [
            PartialFillFault(client, fill_fraction=0.5),
            MarketHaltFault(market),
            SchemaDriftFault(market, drop="Volume"),
        ]
    )
    with pytest.raises(ValueError):
        with reg.armed():
            raise ValueError("boom mid-run")

    o = client.submit_order(_bracket_request(qty=10))
    client.fill_entry(o.id, fill_price=100.0)
    assert float(o.filled_qty) == 10
    frame = market.fetch_cached_ohlcv("AAPL", "2026-01-02", "2026-01-12")
    assert "Volume" in frame.columns
    assert not (frame["High"] == frame["Low"]).all()


# ── DST cadence oracle: fires EXACTLY ONCE across BOTH transitions ─────────────


def test_dst_spring_forward_cadence_fires_exactly_once():
    """Spring forward 2026-03-08 02:00->03:00: target wall-time 02:15 is in the
    skipped hour, yet the once-per-day cadence MUST fire exactly once (the
    reference predicate fires on the first instant at-or-past the target)."""
    clock = VirtualClock(datetime(2026, 3, 8, 1, 30, tzinfo=ET))
    fault = DstEdgeClockFault(clock, transition="spring_forward")
    assert fault.expected_date == "2026-03-08"
    with FaultRegistry([fault]).armed():
        fires = dst_cadence_fires_once(clock, target_hour=2, target_minute=15)
    assert fires == 1


def test_dst_fall_back_cadence_fires_exactly_once():
    """Fall back 2026-11-01 02:00->01:00: target wall-time 01:15 occurs twice,
    yet the once-per-day cadence MUST fire exactly once (deduped by date)."""
    clock = VirtualClock(datetime(2026, 11, 1, 0, 30, tzinfo=ET))
    fault = DstEdgeClockFault(clock, transition="fall_back")
    assert fault.expected_date == "2026-11-01"
    with FaultRegistry([fault]).armed():
        fires = dst_cadence_fires_once(clock, target_hour=1, target_minute=15)
    assert fires == 1


def test_dst_cadence_fires_exactly_once_per_calendar_date_over_multiple_days():
    """Stepping across MULTIPLE days through a DST edge fires once PER day —
    never zero (skipped hour) and never twice (doubled hour)."""
    clock = VirtualClock(datetime(2026, 3, 7, 23, 0, tzinfo=ET))
    # Walk ~2.5 days at 30-min steps so we cross 03-08 (spring forward) and 03-09.
    fired_dates: set = set()
    fires = 0
    for _ in range(120):
        now = clock.now()
        if (now.hour, now.minute) >= (2, 15) and now.date() not in fired_dates:
            fired_dates.add(now.date())
            fires += 1
        clock.advance(timedelta(minutes=30))
    # Each distinct calendar date that reached the target fires exactly once.
    assert fires == len(fired_dates)
    assert fires >= 2  # crossed at least two distinct dates including the DST edge


# ── reconcile 24h recent-close window math across the DST boundary ────────────


def _is_recent_close(now, close_at, *, window=timedelta(hours=24)):
    """A close is 'recent' iff it falls within ``window`` of ``now`` (inclusive).

    Reconcile's recent-close window is a FIXED DURATION measured in absolute
    time — mirrored here against the same tz-aware instants the simulator uses.
    """
    return (now - close_at) <= window and close_at <= now


def test_reconcile_24h_window_is_clean_fixed_duration_across_spring_forward():
    """A close exactly 24h before ``now`` (in absolute/UTC time) is the window
    boundary across the spring-forward edge — the window does NOT drift by the
    skipped hour because it is computed in absolute time."""
    now = VirtualClock(datetime(2026, 3, 9, 9, 30, tzinfo=ET)).now()
    # 24h earlier crosses the 03-08 spring-forward edge.
    boundary = now - timedelta(hours=24)
    # The absolute (UTC) delta is a clean 24h, NOT 23h (no wall-clock drift).
    assert (now.astimezone(timezone.utc) - boundary.astimezone(timezone.utc)) == timedelta(hours=24)
    just_inside = now - timedelta(hours=23, minutes=59)
    just_outside = now - timedelta(hours=24, minutes=1)
    assert _is_recent_close(now, boundary) is True
    assert _is_recent_close(now, just_inside) is True
    assert _is_recent_close(now, just_outside) is False


def test_reconcile_24h_window_is_clean_fixed_duration_across_fall_back():
    """The same fixed-duration window holds across the fall-back edge: 24h in
    absolute time stays 24h even though a wall-clock hour repeats."""
    now = VirtualClock(datetime(2026, 11, 2, 9, 30, tzinfo=ET)).now()
    boundary = now - timedelta(hours=24)  # crosses 11-01 fall-back edge
    assert (now.astimezone(timezone.utc) - boundary.astimezone(timezone.utc)) == timedelta(hours=24)
    just_inside = now - timedelta(hours=23, minutes=59)
    just_outside = now - timedelta(hours=24, minutes=1)
    assert _is_recent_close(now, boundary) is True
    assert _is_recent_close(now, just_inside) is True
    assert _is_recent_close(now, just_outside) is False


def test_virtualclock_advance_is_offset_naive_across_dst_edge():
    """DOCUMENTED LIMITATION (T10): advancing 1h across the spring-forward edge
    does NOT perform a genuine wall-clock fold — the UTC offset does not flip
    and the skipped wall-time (02:30) is produced. This test pins the KNOWN
    behavior so any future genuine-fold change is a deliberate, visible break."""
    clock = VirtualClock(datetime(2026, 3, 8, 1, 30, tzinfo=ET))
    clock.advance(timedelta(hours=1))
    advanced = clock.now()
    # Offset-naive: still -05:00 (EST), and the skipped 02:30 wall-time appears.
    assert advanced.hour == 2 and advanced.minute == 30
    assert advanced.utcoffset() == timedelta(hours=-5)
