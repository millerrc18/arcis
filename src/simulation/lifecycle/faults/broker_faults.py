"""Broker fault injectors (Task 10).

Each fault reproduces a broker-side fault class that caused a real Arcis
data-integrity bug, by configuring the FakeTradingClient's injectable
``fill_policy`` seam (from T5) or by wrapping its public methods on the
INSTANCE. The FakeTradingClient itself is NEVER edited (it is read-only here):
faults swap ``client._fill_policy`` or shadow a bound method and restore the
original on disarm.

Faults provided:
  * PartialFillFault — entry fills less than requested (filled_qty < qty).
  * BrokerQtyZeroExitFault — an exit leg fills qty=0, so the position never
    actually closes (the "close didn't reduce" data bug).
  * OcoLegRaceFault — both OCO legs fill on the SAME tick (the sibling-cancel
    lost the race), via an explicit ``race()`` helper.
  * DuplicateFillFault — the same fill event is delivered N times.
  * TransientEmptyBrokerFault — get_all_positions() returns [] for the first
    N calls (a transient-empty broker response) then recovers.
  * StickyPositionFault — a closed position lingers in the position book.
  * CloseDidNotClearFault — an exit leg fill leaves the leg un-filled / open.
  * PhantomCloseFault — a leg is marked filled with NO position change (the
    DB says closed but the broker still holds shares).

Called by: the ScenarioRunner (Task 11) — NOT wired here.
Calls: src.simulation.lifecycle.fakes.FakeTradingClient (seams only).
Owns tables: none. Config keys: none.
Tests: tests/simulation/lifecycle/test_faults.py
"""

from __future__ import annotations

from typing import Optional

from src.simulation.lifecycle.faults import FaultInjector


class _ClientFault(FaultInjector):
    """Base for faults that swap a seam / method on a FakeTradingClient."""

    def __init__(self, client) -> None:
        super().__init__()
        self._client = client


class PartialFillFault(_ClientFault):
    """Entry fills only a fraction of the requested qty."""

    def __init__(self, client, *, fill_fraction: float = 0.5) -> None:
        super().__init__(client)
        self._fraction = fill_fraction
        self._original = None

    def _install(self) -> None:
        self._original = self._client._fill_policy
        fraction = self._fraction

        def _policy(requested_qty: float, fill_qty: Optional[float]) -> float:
            if fill_qty is not None:
                return fill_qty
            return requested_qty * fraction

        self._client._fill_policy = _policy

    def _restore(self) -> None:
        self._client._fill_policy = self._original


class BrokerQtyZeroExitFault(_ClientFault):
    """An exit-leg fill reports qty=0, so the position is never reduced."""

    def __init__(self, client) -> None:
        super().__init__(client)
        self._original = None

    def _install(self) -> None:
        self._original = self._client.fill_leg

        def _fill_leg(leg_id, *, fill_price, fill_qty=None):
            return self._original(leg_id, fill_price=fill_price, fill_qty=0.0)

        self._client.fill_leg = _fill_leg

    def _restore(self) -> None:
        self._client.fill_leg = self._original


class OcoLegRaceFault(_ClientFault):
    """Both OCO legs fill on the same tick (sibling-cancel lost the race)."""

    def race(self, leg_a_id, leg_b_id, *, fill_price: float) -> dict:
        """Fill BOTH legs before either cancels its sibling."""
        leg_a = self._client.get_order_by_id(leg_a_id)
        leg_b = self._client.get_order_by_id(leg_b_id)
        for leg in (leg_a, leg_b):
            self._client._apply_fill(leg, leg.qty, fill_price)
            leg.status = "filled"
        return {leg_a_id: leg_a, leg_b_id: leg_b}


class DuplicateFillFault(_ClientFault):
    """The same entry fill is delivered N times."""

    def __init__(self, client, *, times: int = 2) -> None:
        super().__init__(client)
        self._times = times

    def fill_entry_duplicated(self, order_id, *, fill_price: float) -> list:
        events = []
        for _ in range(self._times):
            events.append(self._client.fill_entry(order_id, fill_price=fill_price))
        return events


class TransientEmptyBrokerFault(_ClientFault):
    """get_all_positions() returns [] for the first N calls, then recovers."""

    def __init__(self, client, *, empty_calls: int = 1) -> None:
        super().__init__(client)
        self._remaining = empty_calls
        self._original = None

    def _install(self) -> None:
        self._original = self._client.get_all_positions

        def _get_all_positions(*args, **kwargs):
            if self._remaining > 0:
                self._remaining -= 1
                return []
            return self._original(*args, **kwargs)

        self._client.get_all_positions = _get_all_positions

    def _restore(self) -> None:
        self._client.get_all_positions = self._original


class StickyPositionFault(_ClientFault):
    """A closed position lingers in the book (reduce-to-zero never deletes)."""

    def __init__(self, client) -> None:
        super().__init__(client)
        self._original = None

    def _install(self) -> None:
        self._original = self._client._reduce_position

        def _reduce_position(symbol, qty):
            existing = self._client._positions.get(symbol)
            if existing is None:
                return
            existing.qty -= qty
            if existing.qty < 0:
                existing.qty = 0.0

        self._client._reduce_position = _reduce_position

    def _restore(self) -> None:
        self._client._reduce_position = self._original


class CloseDidNotClearFault(_ClientFault):
    """An exit-leg fill leaves the leg un-filled / still open."""

    def __init__(self, client) -> None:
        super().__init__(client)
        self._original = None

    def _install(self) -> None:
        self._original = self._client.fill_leg

        def _fill_leg(leg_id, *, fill_price, fill_qty=None):
            leg = self._original(leg_id, fill_price=fill_price, fill_qty=fill_qty)
            leg.status = "new"
            return leg

        self._client.fill_leg = _fill_leg

    def _restore(self) -> None:
        self._client.fill_leg = self._original


class PhantomCloseFault(_ClientFault):
    """Mark a leg filled with NO position change (DB-closed, broker-open)."""

    def phantom_close(self, leg_id, *, fill_price: float = 0.0):
        """Stamp the leg 'filled' but leave the position book untouched."""
        leg = self._client.get_order_by_id(leg_id)
        self._client._apply_fill(leg, leg.qty, fill_price)
        leg.status = "filled"
        return leg
