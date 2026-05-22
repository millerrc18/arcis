"""Network fault injectors (Task 10).

Reproduce the API-failure classes by wrapping the FakeTradingClient's public
methods on the INSTANCE so a call raises like a real SDK transport failure —
without editing the fake. ``MidSubmitFailureFault`` mutates the order book
BEFORE raising, reproducing the dangerous "broker accepted, client saw an
error" partial-state bug (the orphan-source failure mode).

Faults provided:
  * Api500Fault — submit_order raises a 5xx-style error.
  * ApiTimeoutFault — get_all_positions raises TimeoutError.
  * MidSubmitFailureFault — submit_order mutates the book, THEN raises.

Called by: the ScenarioRunner (Task 11) — NOT wired here.
Calls: src.simulation.lifecycle.fakes.FakeTradingClient (seams only).
Owns tables: none. Config keys: none.
Tests: tests/simulation/lifecycle/test_faults.py
"""

from __future__ import annotations

from src.simulation.lifecycle.faults import FaultInjector


class ApiError(Exception):
    """A generic SDK-transport-style error (5xx)."""


class _MethodRaiseFault(FaultInjector):
    """Wrap one client method so it raises the configured exception."""

    method_name = ""

    def __init__(self, client) -> None:
        super().__init__()
        self._client = client
        self._original = None

    def _install(self) -> None:
        self._original = getattr(self._client, self.method_name)
        setattr(self._client, self.method_name, self._raise)

    def _restore(self) -> None:
        setattr(self._client, self.method_name, self._original)

    def _raise(self, *args, **kwargs):  # pragma: no cover - overridden
        raise NotImplementedError


class Api500Fault(_MethodRaiseFault):
    """submit_order raises a 5xx-style API error."""

    method_name = "submit_order"

    def _raise(self, *args, **kwargs):
        raise ApiError("simulated HTTP 500 from broker API")


class ApiTimeoutFault(_MethodRaiseFault):
    """get_all_positions raises a TimeoutError."""

    method_name = "get_all_positions"

    def _raise(self, *args, **kwargs):
        raise TimeoutError("simulated broker API timeout")


class MidSubmitFailureFault(FaultInjector):
    """Order is booked at the broker, then the client call fails mid-submit."""

    def __init__(self, client) -> None:
        super().__init__()
        self._client = client
        self._original = None

    def _install(self) -> None:
        self._original = self._client.submit_order

        def _submit(request):
            order = self._original(request)
            raise ApiError(
                f"connection reset after broker booked order {order.id}"
            )

        self._client.submit_order = _submit

    def _restore(self) -> None:
        self._client.submit_order = self._original
