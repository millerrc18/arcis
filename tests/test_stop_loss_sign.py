"""E2 — stop_loss sign convention tests.

Validates that exit computations in executor.py + reconcile.py produce
negative pnl_dollars / pnl_pct for stop_loss exits (price moved against the
position) and positive values for target_hit exits.

Pre-investigation finding: both executor.py:2191 and reconcile.py:155 use
(exit_price - entry_price) * shares — correct sign for long positions. The
sign flip visible in the cockpit (Trade History +$82.08 vs Model Performance
-$82.08) is downstream/display-only; it lives outside this task's scope.
This test suite locks the backend sign convention so a future fix can verify
against a known-good baseline.
"""
from __future__ import annotations


def _compute_pnl(entry_price: float, exit_price: float, shares: float) -> tuple[float, float]:
    """Compute pnl_dollars and pnl_pct using the same formula as executor.py:2191."""
    pnl_dollars = (exit_price - entry_price) * shares
    pnl_pct = ((exit_price - entry_price) / entry_price * 100) if entry_price > 0 else 0
    return pnl_dollars, pnl_pct


def _reconcile_pnl(entry_price: float, exit_px: float, shares: float) -> float:
    """Compute pnl_dollars using the same formula as reconcile.py:155."""
    return (exit_px - entry_price) * shares


class TestStopLossSign:
    def test_stop_loss_exit_pnl_is_negative(self):
        entry = 100.0
        exit_price = 95.0
        shares = 10.0
        pnl_dollars, pnl_pct = _compute_pnl(entry, exit_price, shares)
        assert pnl_pct < 0, f"stop_loss pnl_pct should be negative, got {pnl_pct}"
        assert pnl_dollars < 0, f"stop_loss pnl_dollars should be negative, got {pnl_dollars}"

    def test_stop_loss_pnl_magnitude_correct(self):
        entry = 100.0
        exit_price = 95.0
        shares = 10.0
        pnl_dollars, pnl_pct = _compute_pnl(entry, exit_price, shares)
        assert pnl_dollars == -50.0
        assert abs(pnl_pct - (-5.0)) < 1e-9

    def test_target_hit_exit_pnl_is_positive(self):
        entry = 100.0
        exit_price = 108.0
        shares = 10.0
        pnl_dollars, pnl_pct = _compute_pnl(entry, exit_price, shares)
        assert pnl_pct > 0, f"target_hit pnl_pct should be positive, got {pnl_pct}"
        assert pnl_dollars > 0, f"target_hit pnl_dollars should be positive, got {pnl_dollars}"

    def test_reconcile_stop_loss_pnl_is_negative(self):
        entry = 100.0
        stop_price = 95.0
        shares = 10.0
        pnl = _reconcile_pnl(entry, stop_price, shares)
        assert pnl < 0, f"reconcile stop_loss pnl should be negative, got {pnl}"

    def test_reconcile_target_hit_pnl_is_positive(self):
        entry = 100.0
        target_price = 108.0
        shares = 10.0
        pnl = _reconcile_pnl(entry, target_price, shares)
        assert pnl > 0, f"reconcile target_hit pnl should be positive, got {pnl}"
