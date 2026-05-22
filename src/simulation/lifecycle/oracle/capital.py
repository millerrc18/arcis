"""Authoritative capital ledger for the lifecycle oracle (Task 8).

Called by: simulation.lifecycle.oracle (Task 9 invariant 5 + 6 checks)
Calls: none (pure in-memory accounting)
Owns tables: none
Config keys: none
Tests: tests/simulation/lifecycle/test_capital.py

This ledger is the INDEPENDENT source of truth the oracle compares against the
platform's own DB-derived capital / P&L numbers. It is fed from the
FakeTradingClient's fills (entries open or grow a position, exits close or
reduce it) and computes:

  - realized P&L  : locked-in profit from closing fills, using average-cost
                    basis per symbol (long and short);
  - unrealized P&L: open positions marked at the current fake price;
  - total equity  : starting_capital + realized + unrealized;
  - peak equity   : the sticky high-water mark of total equity;
  - drawdown      : peak-relative loss fraction (the honest-metrics
                    denominator invariant 6 asserts against).

``detect_phantom_pnl`` is the capital-conservation signal invariant 5 asserts:
a DB-reported P&L that does not reconcile (within tolerance) to the realized
P&L this ledger attributed to actual fills is phantom — capital appearing or
vanishing with no attributed fill behind it.
"""

from __future__ import annotations

from dataclasses import dataclass

# Reconciliation tolerance for detect_phantom_pnl. A DB-reported P&L within this
# absolute band of the ledger's attributed realized P&L is treated as the same
# number (guards against float round-trip noise), anything beyond it is phantom.
_PHANTOM_TOLERANCE = 1e-6


@dataclass
class _Lot:
    """A symbol's net open position under average-cost basis.

    ``qty`` is signed: positive for a net long, negative for a net short.
    ``avg_price`` is the average entry price of the open quantity.
    """

    qty: float = 0.0
    avg_price: float = 0.0


class CapitalLedger:
    """Independent, fill-driven capital / P&L truth for the oracle."""

    def __init__(self, *, starting_capital: float) -> None:
        self._starting_capital = float(starting_capital)
        self._realized = 0.0
        self._lots: dict[str, _Lot] = {}
        self._peak_equity = float(starting_capital)

    # ── fill ingestion ────────────────────────────────────────────────────

    def apply_fill(self, *, symbol: str, side: str, qty: float, price: float) -> None:
        """Ingest one fill from the FakeTradingClient position book.

        A buy adds +qty, a sell adds -qty to the net signed lot. The portion of
        the fill that reduces an opposing position realizes P&L; the remainder
        opens or extends a position at average cost.
        """
        signed = float(qty) if side == "buy" else -float(qty)
        lot = self._lots.setdefault(symbol, _Lot())
        self._realized += self._fill_lot(lot, signed, float(price))
        if lot.qty == 0.0:
            self._lots.pop(symbol, None)
        self._observe_peak(self._equity_from_marks({}))

    @staticmethod
    def _fill_lot(lot: _Lot, signed_qty: float, price: float) -> float:
        """Apply a signed fill to a lot, returning realized P&L from it."""
        realized = 0.0
        # Closing portion: fill quantity that offsets the existing position.
        if lot.qty != 0.0 and (lot.qty > 0) != (signed_qty > 0):
            direction = 1.0 if lot.qty > 0 else -1.0
            closing = min(abs(signed_qty), abs(lot.qty))
            realized = (price - lot.avg_price) * closing * direction
            lot.qty -= direction * closing
            signed_qty += direction * closing  # consume the closing portion
        # Opening / extending portion: any fill quantity left re-bases avg cost.
        if signed_qty != 0.0:
            if lot.qty == 0.0:
                lot.avg_price = price
                lot.qty = signed_qty
            else:
                total = lot.qty + signed_qty
                lot.avg_price = (
                    (lot.avg_price * lot.qty) + (price * signed_qty)
                ) / total
                lot.qty = total
        return realized

    # ── P&L surface ───────────────────────────────────────────────────────

    def realized_pnl(self) -> float:
        """Locked-in P&L from all closing fills attributed so far."""
        return self._realized

    def unrealized_pnl(self, marks: dict[str, float]) -> float:
        """Mark-to-market P&L of open positions at the given fake prices.

        Symbols absent from ``marks`` contribute zero unrealized P&L (no mark
        available => no opinion), which keeps a flat book at exactly zero.
        """
        total = 0.0
        for symbol, lot in self._lots.items():
            mark = marks.get(symbol)
            if mark is None:
                continue
            total += (mark - lot.avg_price) * lot.qty
        return total

    def total_equity(self, marks: dict[str, float]) -> float:
        """starting_capital + realized + unrealized at the given marks."""
        return self._equity_from_marks(marks)

    def peak_equity(self, marks: dict[str, float] | None = None) -> float:
        """High-water mark of total equity (sticky across the run).

        Passing current ``marks`` folds the present mark-to-market equity into
        the high-water comparison before returning it.
        """
        if marks is not None:
            self._observe_peak(self._equity_from_marks(marks))
        return self._peak_equity

    def drawdown(self, marks: dict[str, float]) -> float:
        """Peak-relative loss fraction at the given marks (0.0 at the peak)."""
        equity = self._equity_from_marks(marks)
        self._observe_peak(equity)
        if self._peak_equity <= 0.0:
            return 0.0
        return (self._peak_equity - equity) / self._peak_equity

    # ── capital-conservation signal (invariant 5) ─────────────────────────

    def detect_phantom_pnl(self, db_reported_pnl: float) -> bool:
        """Flag a DB-reported P&L that does not reconcile to attributed fills.

        Returns True when ``db_reported_pnl`` differs from the ledger's
        attributed realized P&L by more than the reconciliation tolerance —
        capital that appeared or vanished with no fill behind it.
        """
        return abs(float(db_reported_pnl) - self._realized) > _PHANTOM_TOLERANCE

    # ── internals ─────────────────────────────────────────────────────────

    def _equity_from_marks(self, marks: dict[str, float]) -> float:
        return self._starting_capital + self._realized + self.unrealized_pnl(marks)

    def _observe_peak(self, equity: float) -> None:
        if equity > self._peak_equity:
            self._peak_equity = equity
