"""Tests for the composable fault-injection framework (Task 10).

Faults patch the FAKES + harness ONLY (never prod code). Each fault is a
``FaultInjector`` with an arm()/disarm() lifecycle; a ``FaultRegistry`` arms a
set of them and guarantees clean teardown so NO fault leaks between runs.

These tests assert:
  * compose two faults + arm/disarm cleanly, and a SECOND clean run sees no
    residual fault (no leakage);
  * each broker fault produces the expected fake behavior (partial fill,
    qty=0 exit, OCO-leg race, duplicate fills, transient-empty, sticky
    position, close-didn't-clear, phantom close);
  * the process-restart fault reconstructs the loop IN-PROCESS (no real
    subprocess), and PID recycling drives the controllable pidfile;
  * the DST clock fault produces the defined cadence expectation (a cadence
    predicate fires EXACTLY ONCE across the spring-forward / fall-back hour).
"""

from datetime import datetime

import pytest

from src.simulation.lifecycle.clock import ET, VirtualClock
from src.simulation.lifecycle.fakes import (
    FakeLLM,
    FakeMarketData,
    FakeTradingClient,
    FakeTrainerPidfile,
)
from src.simulation.lifecycle.faults import FaultInjector, FaultRegistry
from src.simulation.lifecycle.faults.broker_faults import (
    BrokerQtyZeroExitFault,
    CloseDidNotClearFault,
    DuplicateFillFault,
    OcoLegRaceFault,
    PartialFillFault,
    PhantomCloseFault,
    StickyPositionFault,
    TransientEmptyBrokerFault,
)
from src.simulation.lifecycle.faults.clock_faults import (
    DstEdgeClockFault,
    dst_cadence_fires_once,
)
from src.simulation.lifecycle.faults.data_faults import (
    CorpusStarvationFault,
    SchemaDriftFault,
)
from src.simulation.lifecycle.faults.market_faults import (
    HighCandidateVolumeFault,
    MarketGapFault,
    MarketHaltFault,
    RegimeShiftFault,
)
from src.simulation.lifecycle.faults.network_faults import (
    ApiTimeoutFault,
    Api500Fault,
    MidSubmitFailureFault,
)
from src.simulation.lifecycle.faults.process_faults import (
    PidRecycleFault,
    TrainingRestartFault,
    WatchLoopRestartFault,
)


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


# ── base lifecycle + registry / no-leakage ────────────────────────────────


def test_partial_fill_arm_disarm_restores_default():
    client = FakeTradingClient(clock=_clock())
    fault = PartialFillFault(client, fill_fraction=0.3)
    fault.arm()
    o = client.submit_order(_bracket_request(qty=10))
    client.fill_entry(o.id, fill_price=100.0)
    assert float(o.filled_qty) < 10
    assert o.status == "partially_filled"
    fault.disarm()
    o2 = client.submit_order(_bracket_request(symbol="MSFT", qty=10))
    client.fill_entry(o2.id, fill_price=100.0)
    assert float(o2.filled_qty) == 10
    assert o2.status == "filled"


def test_double_arm_is_rejected():
    client = FakeTradingClient(clock=_clock())
    fault = PartialFillFault(client, fill_fraction=0.5)
    fault.arm()
    with pytest.raises(RuntimeError):
        fault.arm()
    fault.disarm()


def test_registry_composes_two_faults_then_teardown_no_leakage():
    client = FakeTradingClient(clock=_clock())
    market = FakeMarketData(seed=1)
    reg = FaultRegistry(
        [PartialFillFault(client, fill_fraction=0.5), MarketGapFault(market, gap_pct=-0.2)]
    )
    with reg.armed():
        o = client.submit_order(_bracket_request(qty=10))
        client.fill_entry(o.id, fill_price=100.0)
        assert float(o.filled_qty) == 5
        frame = market.fetch_cached_ohlcv("AAPL", "2026-01-02", "2026-01-09")
        assert (frame["Close"] < frame["Open"]).any()

    # Second CLEAN run on the SAME fakes — no residual fault.
    o2 = client.submit_order(_bracket_request(symbol="MSFT", qty=10))
    client.fill_entry(o2.id, fill_price=100.0)
    assert float(o2.filled_qty) == 10
    clean = FakeMarketData(seed=1)
    base = clean.fetch_cached_ohlcv("AAPL", "2026-01-02", "2026-01-09")
    after = market.fetch_cached_ohlcv("AAPL", "2026-01-02", "2026-01-09")
    assert list(after["Close"]) == list(base["Close"])


def test_registry_disarms_in_reverse_even_on_error():
    client = FakeTradingClient(clock=_clock())
    reg = FaultRegistry([PartialFillFault(client, fill_fraction=0.5)])
    with pytest.raises(ValueError):
        with reg.armed():
            raise ValueError("boom")
    o = client.submit_order(_bracket_request(qty=10))
    client.fill_entry(o.id, fill_price=100.0)
    assert float(o.filled_qty) == 10


# ── broker faults ──────────────────────────────────────────────────────────


def test_broker_qty_zero_exit():
    client = FakeTradingClient(clock=_clock())
    with FaultRegistry([BrokerQtyZeroExitFault(client)]).armed():
        o = client.submit_order(_bracket_request(qty=10))
        client.fill_entry(o.id, fill_price=100.0)
        leg = o.legs[0]
        client.fill_leg(leg.id, fill_price=110.0)
        assert client.get_open_position("AAPL") is not None
        assert float(client.get_open_position("AAPL").qty) == 10


def test_oco_leg_race_both_legs_fill():
    client = FakeTradingClient(clock=_clock())
    o = client.submit_order(_bracket_request(qty=10))
    client.fill_entry(o.id, fill_price=100.0)
    fault = OcoLegRaceFault(client)
    with FaultRegistry([fault]).armed():
        tp, sl = o.legs
        results = fault.race(tp.id, sl.id, fill_price=110.0)
        assert results[tp.id].status == "filled"
        assert results[sl.id].status == "filled"


def test_duplicate_fills():
    client = FakeTradingClient(clock=_clock())
    fault = DuplicateFillFault(client, times=2)
    with FaultRegistry([fault]).armed():
        o = client.submit_order(_bracket_request(qty=10))
        events = fault.fill_entry_duplicated(o.id, fill_price=100.0)
        assert len(events) == 2


def test_transient_empty_broker_response():
    client = FakeTradingClient(clock=_clock())
    o = client.submit_order(_bracket_request(qty=10))
    client.fill_entry(o.id, fill_price=100.0)
    fault = TransientEmptyBrokerFault(client, empty_calls=1)
    with FaultRegistry([fault]).armed():
        assert client.get_all_positions() == []
        assert len(client.get_all_positions()) == 1


def test_sticky_position_survives_close():
    client = FakeTradingClient(clock=_clock())
    with FaultRegistry([StickyPositionFault(client)]).armed():
        o = client.submit_order(_bracket_request(qty=10))
        client.fill_entry(o.id, fill_price=100.0)
        client.fill_leg(o.legs[0].id, fill_price=110.0)
        assert client.get_open_position("AAPL") is not None


def test_close_did_not_clear_leaves_order_open():
    client = FakeTradingClient(clock=_clock())
    o = client.submit_order(_bracket_request(qty=10))
    client.fill_entry(o.id, fill_price=100.0)
    with FaultRegistry([CloseDidNotClearFault(client)]).armed():
        leg = o.legs[0]
        client.fill_leg(leg.id, fill_price=110.0)
        assert leg.status != "filled"


def test_phantom_close_marks_filled_without_position_change():
    client = FakeTradingClient(clock=_clock())
    o = client.submit_order(_bracket_request(qty=10))
    client.fill_entry(o.id, fill_price=100.0)
    fault = PhantomCloseFault(client)
    with FaultRegistry([fault]).armed():
        leg = o.legs[0]
        fault.phantom_close(leg.id)
        assert leg.status == "filled"
        assert client.get_open_position("AAPL") is not None


# ── process faults ──────────────────────────────────────────────────────────


def test_watch_loop_restart_in_process_no_subprocess():
    rebuilt = {"count": 0}

    def reconstruct():
        rebuilt["count"] += 1
        return object()

    fault = WatchLoopRestartFault(reconstruct=reconstruct)
    with FaultRegistry([fault]).armed():
        loop = fault.restart_mid_cycle()
        assert loop is not None
    assert rebuilt["count"] == 1
    assert fault.spawned_subprocess is False


def test_training_restart_in_process():
    rebuilt = {"count": 0}
    fault = TrainingRestartFault(reconstruct=lambda: rebuilt.__setitem__("count", rebuilt["count"] + 1))
    with FaultRegistry([fault]).armed():
        fault.restart_mid_cycle()
    assert rebuilt["count"] == 1
    assert fault.spawned_subprocess is False


def test_pid_recycle_fault(tmp_path):
    pidfile = FakeTrainerPidfile(tmp_path / "lock.pid", pid=4242, alive=True, identity="trainer-A")
    pidfile.acquire()
    fault = PidRecycleFault(pidfile, new_identity="unrelated-proc")
    with FaultRegistry([fault]).armed():
        assert pidfile.is_recycled("unrelated-proc") is True
    # disarm restores identity
    assert pidfile.is_recycled("trainer-A") is False


# ── market faults ──────────────────────────────────────────────────────────


def test_market_halt_freezes_price():
    market = FakeMarketData(seed=2)
    with FaultRegistry([MarketHaltFault(market)]).armed():
        frame = market.fetch_cached_ohlcv("AAPL", "2026-01-02", "2026-01-12")
        assert (frame["High"] == frame["Low"]).all()


def test_regime_shift_changes_drift():
    market = FakeMarketData(seed=2)
    with FaultRegistry([RegimeShiftFault(market, drift=-0.5)]).armed():
        frame = market.fetch_cached_ohlcv("AAPL", "2026-01-02", "2026-01-12")
        assert frame["Close"].iloc[-1] < frame["Open"].iloc[0]


def test_high_candidate_volume():
    llm = FakeLLM(seed=3, n_candidates=2)
    with FaultRegistry([HighCandidateVolumeFault(llm, n_candidates=50)]).armed():
        assert len(llm.generate_candidates()) == 50
    assert len(llm.generate_candidates()) == 2


# ── network faults ───────────────────────────────────────────────────────────


def test_api_500_fault_raises():
    client = FakeTradingClient(clock=_clock())
    fault = Api500Fault(client)
    with FaultRegistry([fault]).armed():
        with pytest.raises(Exception):
            client.submit_order(_bracket_request())
    client.submit_order(_bracket_request())


def test_api_timeout_fault_raises():
    client = FakeTradingClient(clock=_clock())
    with FaultRegistry([ApiTimeoutFault(client)]).armed():
        with pytest.raises(TimeoutError):
            client.get_all_positions()


def test_mid_submit_failure_after_book_mutation():
    client = FakeTradingClient(clock=_clock())
    fault = MidSubmitFailureFault(client)
    with FaultRegistry([fault]).armed():
        with pytest.raises(Exception):
            client.submit_order(_bracket_request())
        assert len(client.get_orders()) > 0


# ── data faults ──────────────────────────────────────────────────────────────


def test_corpus_starvation_empties_candidates():
    llm = FakeLLM(seed=4, n_candidates=10)
    with FaultRegistry([CorpusStarvationFault(llm)]).armed():
        assert llm.generate_candidates() == []
    assert len(llm.generate_candidates()) == 10


def test_schema_drift_renames_column():
    market = FakeMarketData(seed=5)
    with FaultRegistry([SchemaDriftFault(market, drop="Volume")]).armed():
        frame = market.fetch_cached_ohlcv("AAPL", "2026-01-02", "2026-01-09")
        assert "Volume" not in frame.columns
    frame2 = market.fetch_cached_ohlcv("AAPL", "2026-01-02", "2026-01-09")
    assert "Volume" in frame2.columns


# ── clock fault (DST oracle) ─────────────────────────────────────────────────


def test_dst_spring_forward_cadence_fires_once():
    # Spring forward 2026: 2026-03-08 02:00 ET -> 03:00 ET.
    clock = VirtualClock(datetime(2026, 3, 8, 1, 30, tzinfo=ET))
    fault = DstEdgeClockFault(clock, transition="spring_forward")
    with FaultRegistry([fault]).armed():
        fires = dst_cadence_fires_once(clock, target_hour=2, target_minute=15)
        assert fires == 1


def test_dst_fall_back_cadence_fires_once():
    # Fall back 2026: 2026-11-01 02:00 ET -> 01:00 ET (1am occurs twice).
    clock = VirtualClock(datetime(2026, 11, 1, 0, 30, tzinfo=ET))
    fault = DstEdgeClockFault(clock, transition="fall_back")
    with FaultRegistry([fault]).armed():
        fires = dst_cadence_fires_once(clock, target_hour=1, target_minute=15)
        assert fires == 1
