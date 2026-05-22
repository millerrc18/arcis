"""Stateful FakeTradingClient at the alpaca-py SDK boundary (Task 5).

This fake stands in for the object that
``src.shadow_trading.alpaca_adapter._get_trading_client`` returns — the
alpaca-py ``TradingClient``. Faking HERE (not at the BrokerAdapter ABC)
routes BOTH the paper dict path AND the live dataclass path through the REAL
``_serialize_order``, so order objects must expose the same attribute surface
the SDK does: ``.id``, ``.symbol``, ``.qty``, ``.side``, ``.type``/
``.order_type``, ``.status``, ``.filled_qty``, ``.filled_avg_price``,
``.legs`` (each leg an order object with ``.id``), etc.

State held:
  - an order book (id -> FakeOrder), including the OCO take-profit + stop-loss
    legs of every bracket;
  - a position book (symbol -> FakePosition with qty / avg_price).

OCO semantics: when one exit leg fills, its sibling auto-cancels and the
position closes (qty -> 0). Partial fills update filled_qty and the position
book. A qty=0 exit closes the position.

Determinism (spec §7.2): a monotonic integer counter drives every order id
and client_order_id, so two identical runs produce identical id sequences.
Fill timestamps are read from an injected VirtualClock.

Fault hooks (Task 10) are intentionally NOT implemented here, but a clean
seam is left: ``fill_policy`` is an injectable callable that decides the
fill quantity for an entry, so a later task can wrap it to simulate
rejections / partials / drops without touching this class.

Called by: the ScenarioRunner (later task) — NOT wired here.
Calls: src.simulation.lifecycle.clock (VirtualClock).
Owns tables: none. Config keys: none.
Tests: tests/simulation/lifecycle/test_fake_trading_client.py
"""

from __future__ import annotations

from typing import Callable, Optional

from src.simulation.lifecycle.clock import VirtualClock


class FakeOrder:
    """Duck-typed alpaca-py order object consumed by real _serialize_order."""

    def __init__(
        self,
        *,
        order_id: str,
        client_order_id: str,
        symbol: str,
        qty: float,
        side: str,
        order_type: str,
        status: str = "new",
        limit_price: Optional[float] = None,
        stop_price: Optional[float] = None,
        created_at: Optional[str] = None,
    ) -> None:
        self.id = order_id
        self.client_order_id = client_order_id
        self.symbol = symbol
        self.qty = qty
        self.side = side
        self.type = order_type
        self.order_type = order_type
        self.status = status
        self.filled_qty = "0"
        self.filled_avg_price: Optional[float] = None
        self.filled_at: Optional[str] = None
        self.created_at = created_at
        self.limit_price = limit_price
        self.stop_price = stop_price
        self.legs: list[FakeOrder] = []


class FakePosition:
    """Duck-typed alpaca-py position object (qty / avg_entry_price)."""

    def __init__(self, *, symbol: str, qty: float, avg_entry_price: float) -> None:
        self.symbol = symbol
        self.qty = qty
        self.avg_entry_price = avg_entry_price
        self.current_price = avg_entry_price
        self.market_value = qty * avg_entry_price
        self.unrealized_pl = 0.0
        self.unrealized_plpc = 0.0


def _default_fill_policy(requested_qty: float, fill_qty: Optional[float]) -> float:
    """Fill the requested qty unless the caller specifies a partial amount."""
    return requested_qty if fill_qty is None else fill_qty


class FakeTradingClient:
    """Stateful in-memory stand-in for alpaca-py's TradingClient."""

    def __init__(
        self,
        *,
        clock: VirtualClock,
        fill_policy: Callable[[float, Optional[float]], float] = _default_fill_policy,
    ) -> None:
        self._clock = clock
        self._fill_policy = fill_policy
        self._counter = 0
        self._orders: dict[str, FakeOrder] = {}
        self._positions: dict[str, FakePosition] = {}

    # ── id minting (deterministic, monotonic) ────────────────────────────

    def _next_id(self, prefix: str) -> tuple[str, str]:
        self._counter += 1
        seq = self._counter
        return f"sim-order-{seq:08d}", f"{prefix}-{seq:08d}"

    def _now_iso(self) -> str:
        return self._clock.now().isoformat()

    # ── order submission ─────────────────────────────────────────────────

    def submit_order(self, request) -> FakeOrder:
        """Submit a bracket/OCO order; return an SDK-shaped FakeOrder."""
        symbol = request.symbol
        qty = float(request.qty)
        side = _coerce(getattr(request, "side", "buy"))
        order_type = _coerce(getattr(request, "type", None)) or (
            "limit" if getattr(request, "limit_price", None) else "market"
        )
        order_id, client_order_id = self._next_id("entry")
        order = FakeOrder(
            order_id=order_id,
            client_order_id=client_order_id,
            symbol=symbol,
            qty=qty,
            side=side,
            order_type=order_type,
            status="new",
            limit_price=_to_price(getattr(request, "limit_price", None)),
            stop_price=_to_price(getattr(request, "stop_price", None)),
            created_at=self._now_iso(),
        )
        order.legs = self._build_legs(request, symbol, qty, side)
        self._orders[order.id] = order
        for leg in order.legs:
            self._orders[leg.id] = leg
        return order

    def _build_legs(self, request, symbol: str, qty: float, entry_side: str) -> list[FakeOrder]:
        """Build the OCO take-profit + stop-loss legs for a bracket request."""
        take_profit = getattr(request, "take_profit", None)
        stop_loss = getattr(request, "stop_loss", None)
        if not take_profit and not stop_loss:
            return []
        exit_side = "sell" if entry_side == "buy" else "buy"
        legs: list[FakeOrder] = []
        if take_profit:
            tp_id, tp_coid = self._next_id("tp")
            legs.append(FakeOrder(
                order_id=tp_id, client_order_id=tp_coid, symbol=symbol,
                qty=qty, side=exit_side, order_type="limit", status="held",
                limit_price=_to_price(take_profit.get("limit_price")),
                created_at=self._now_iso(),
            ))
        if stop_loss:
            sl_id, sl_coid = self._next_id("sl")
            legs.append(FakeOrder(
                order_id=sl_id, client_order_id=sl_coid, symbol=symbol,
                qty=qty, side=exit_side, order_type="stop", status="held",
                stop_price=_to_price(stop_loss.get("stop_price")),
                created_at=self._now_iso(),
            ))
        return legs

    # ── deterministic fills (driven by the simulator) ────────────────────

    def fill_entry(
        self, order_id: str, *, fill_price: float, fill_qty: Optional[float] = None
    ) -> FakeOrder:
        """Fill an entry order (fully or partially) and update the book."""
        order = self._orders[order_id]
        filled = self._fill_policy(order.qty, fill_qty)
        self._apply_fill(order, filled, fill_price)
        order.status = "filled" if filled >= order.qty else "partially_filled"
        self._open_or_add_position(order.symbol, filled, fill_price)
        return order

    def fill_leg(
        self, leg_id: str, *, fill_price: float, fill_qty: Optional[float] = None
    ) -> FakeOrder:
        """Fill an OCO exit leg; auto-cancel its sibling and close position."""
        leg = self._orders[leg_id]
        filled = leg.qty if fill_qty is None else fill_qty
        self._apply_fill(leg, filled, fill_price)
        leg.status = "filled"
        self._cancel_siblings(leg)
        self._reduce_position(leg.symbol, filled)
        return leg

    def _apply_fill(self, order: FakeOrder, filled: float, fill_price: float) -> None:
        order.filled_qty = str(filled)
        order.filled_avg_price = float(fill_price)
        order.filled_at = self._now_iso()

    def _cancel_siblings(self, filled_leg: FakeOrder) -> None:
        for order in self._orders.values():
            if (
                order.symbol == filled_leg.symbol
                and order.id != filled_leg.id
                and order.status == "held"
                and order.side == filled_leg.side
            ):
                order.status = "canceled"

    # ── position book ────────────────────────────────────────────────────

    def _open_or_add_position(self, symbol: str, qty: float, price: float) -> None:
        if qty <= 0:
            return
        existing = self._positions.get(symbol)
        if existing is None:
            self._positions[symbol] = FakePosition(
                symbol=symbol, qty=qty, avg_entry_price=price
            )
            return
        total = existing.qty + qty
        existing.avg_entry_price = (
            (existing.avg_entry_price * existing.qty) + (price * qty)
        ) / total
        existing.qty = total
        existing.market_value = existing.qty * existing.avg_entry_price

    def _reduce_position(self, symbol: str, qty: float) -> None:
        existing = self._positions.get(symbol)
        if existing is None:
            return
        existing.qty -= qty
        if existing.qty <= 0:
            del self._positions[symbol]
        else:
            existing.market_value = existing.qty * existing.avg_entry_price

    # ── SDK read surface ─────────────────────────────────────────────────

    def get_order_by_id(self, order_id) -> FakeOrder:
        return self._orders[str(order_id)]

    def get_orders(self, filter=None) -> list[FakeOrder]:
        return list(self._orders.values())

    def get_all_positions(self) -> list[FakePosition]:
        return list(self._positions.values())

    def get_open_position(self, symbol) -> Optional[FakePosition]:
        return self._positions.get(str(symbol))

    def cancel_order_by_id(self, order_id) -> None:
        order = self._orders.get(str(order_id))
        if order is not None:
            order.status = "canceled"


def _coerce(value) -> Optional[str]:
    """Return a plain lowercase string for an enum-ish or string value."""
    if value is None:
        return None
    inner = getattr(value, "value", None)
    if isinstance(inner, str):
        return inner
    text = str(value)
    return text.split(".")[-1].lower() if "." in text else text.lower()


def _to_price(value) -> Optional[float]:
    if value in (None, ""):
        return None
    return float(value)
