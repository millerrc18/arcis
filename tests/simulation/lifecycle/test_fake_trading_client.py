"""Tests for FakeTradingClient (Task 5).

The fake stands in for the alpaca-py SDK trading client at the SDK boundary
(the object `src.shadow_trading.alpaca_adapter._get_trading_client` returns).
Faking HERE — not at the BrokerAdapter ABC — routes the real
`_serialize_order` over the fake's order objects, so these tests assert the
fake emits exactly the SDK shape that prod normalization consumes.

OCO semantics, partial fills, qty=0 exits, position-book accounting, and
deterministic monotonic client_order_id sequencing (spec §7.2) are exercised
directly against the fake.
"""

from datetime import datetime, timezone

import pytest

from src.shadow_trading.alpaca_adapter import _serialize_order
from src.simulation.lifecycle.clock import ET, VirtualClock
from src.simulation.lifecycle.fakes import FakeTradingClient


def _clock():
    return VirtualClock(datetime(2026, 5, 22, 9, 30, tzinfo=ET))


def _bracket_request(symbol="AAPL", qty=10, tp=110.0, sl=90.0, side="buy"):
    """A minimal duck-typed bracket request matching what the paper adapter
    builds (MarketOrderRequest with order_class=BRACKET + take_profit /
    stop_loss legs). Attribute names mirror alpaca-py request objects."""
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


# ── _serialize_order compatibility ───────────────────────────────────────


def test_bracket_submit_serializes_to_prod_shape():
    client = FakeTradingClient(clock=_clock())
    order = client.submit_order(_bracket_request(symbol="AAPL", qty=10))

    normalized = _serialize_order(order)

    assert normalized["order_id"] == str(order.id)
    assert normalized["symbol"] == "AAPL"
    assert normalized["qty"] == 10.0
    assert normalized["side"] == "buy"
    assert normalized["type"] == "market"
    assert normalized["status"] in {"new", "accepted", "pending_new"}
    assert len(normalized["legs"]) == 2
    leg_ids = {leg["order_id"] for leg in normalized["legs"]}
    assert all(leg_ids)  # every leg has a non-empty id
    # legs carry the OCO exit prices through real normalization
    tp_leg = [l for l in normalized["legs"] if l["limit_price"] is not None]
    sl_leg = [l for l in normalized["legs"] if l["stop_price"] is not None]
    assert tp_leg and tp_leg[0]["limit_price"] == 110.0
    assert sl_leg and sl_leg[0]["stop_price"] == 90.0


def test_order_legs_expose_sdk_attributes():
    client = FakeTradingClient(clock=_clock())
    order = client.submit_order(_bracket_request())
    assert len(order.legs) == 2
    for leg in order.legs:
        assert leg.id is not None
        assert leg.symbol == order.symbol
        # _strip_enum-friendly plain strings
        assert leg.side == "sell"


# ── OCO sibling auto-cancel ──────────────────────────────────────────────


def test_oco_sibling_autocancels_on_fill():
    client = FakeTradingClient(clock=_clock())
    order = client.submit_order(_bracket_request(symbol="MSFT", qty=5))
    client.fill_entry(order.id, fill_price=100.0)
    tp_leg, sl_leg = order.legs

    client.fill_leg(tp_leg.id, fill_price=110.0)

    refreshed_tp = client.get_order_by_id(tp_leg.id)
    refreshed_sl = client.get_order_by_id(sl_leg.id)
    assert refreshed_tp.status == "filled"
    assert refreshed_sl.status == "canceled"
    # position closes when an exit leg fills
    assert client.get_open_position("MSFT") is None


# ── partial fills + position book ────────────────────────────────────────


def test_partial_fill_reflected_in_filled_qty_and_position_book():
    client = FakeTradingClient(clock=_clock())
    order = client.submit_order(_bracket_request(symbol="NVDA", qty=10))

    client.fill_entry(order.id, fill_price=50.0, fill_qty=4)

    refreshed = client.get_order_by_id(order.id)
    assert refreshed.status == "partially_filled"
    assert float(refreshed.filled_qty) == 4.0
    pos = client.get_open_position("NVDA")
    assert pos is not None
    assert float(pos.qty) == 4.0
    assert float(pos.avg_entry_price) == 50.0


def test_position_book_qty_equality_after_full_fill():
    client = FakeTradingClient(clock=_clock())
    order = client.submit_order(_bracket_request(symbol="TSLA", qty=8))
    client.fill_entry(order.id, fill_price=200.0)
    pos = client.get_open_position("TSLA")
    assert float(pos.qty) == 8.0
    assert float(pos.avg_entry_price) == 200.0
    positions = client.get_all_positions()
    assert any(p.symbol == "TSLA" and float(p.qty) == 8.0 for p in positions)


def test_qty_zero_exit_closes_position():
    client = FakeTradingClient(clock=_clock())
    order = client.submit_order(_bracket_request(symbol="AMD", qty=6))
    client.fill_entry(order.id, fill_price=80.0)
    assert client.get_open_position("AMD") is not None

    sl_leg = order.legs[1]
    client.fill_leg(sl_leg.id, fill_price=70.0)  # stop fills, qty -> 0

    assert client.get_open_position("AMD") is None
    assert all(p.symbol != "AMD" for p in client.get_all_positions())


# ── cancel + lookups ─────────────────────────────────────────────────────


def test_cancel_order_by_id_marks_canceled():
    client = FakeTradingClient(clock=_clock())
    order = client.submit_order(_bracket_request(symbol="QQQ", qty=3))
    client.cancel_order_by_id(order.id)
    assert client.get_order_by_id(order.id).status == "canceled"


def test_get_orders_returns_submitted_orders():
    client = FakeTradingClient(clock=_clock())
    o1 = client.submit_order(_bracket_request(symbol="A", qty=1))
    o2 = client.submit_order(_bracket_request(symbol="B", qty=2))
    ids = {o.id for o in client.get_orders(None)}
    assert o1.id in ids and o2.id in ids


# ── determinism (spec §7.2) ──────────────────────────────────────────────


def test_deterministic_client_order_id_sequence_across_runs():
    def run():
        client = FakeTradingClient(clock=_clock())
        ids = []
        for sym in ("AAA", "BBB", "CCC"):
            order = client.submit_order(_bracket_request(symbol=sym, qty=1))
            ids.append(order.client_order_id)
        return ids

    run_a = run()
    run_b = run()
    assert run_a == run_b
    # monotonic integer sequence embedded in client_order_id
    assert run_a == sorted(run_a)
    assert len(set(run_a)) == 3
