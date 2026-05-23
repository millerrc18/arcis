"""Tests for the authoritative CapitalLedger (Task 8).

The ledger is the INDEPENDENT source of truth the oracle (Task 9) compares
against the platform's own DB-derived capital/P&L numbers. It tracks starting
capital, realized P&L from closed fills, and unrealized P&L from open positions
marked at the current fake price.

These tests assert:
  (a) a sequence of entry+exit fills reconciles to the correct realized P&L
      and equity;
  (b) drawdown computes against peak equity correctly;
  (c) detect_phantom_pnl flags an unattributed P&L delta and passes a
      reconciled one.
"""

from src.simulation.lifecycle.oracle import CapitalLedger, SwallowedErrorObserver


def test_oracle_package_still_exports_observer():
    """Task 81's export must survive alongside the new CapitalLedger export."""
    assert SwallowedErrorObserver is not None
    assert CapitalLedger is not None


def test_long_round_trip_realizes_pnl_and_equity():
    """Buy 10 @ 100, sell 10 @ 110 => +100 realized; equity = start + 100."""
    ledger = CapitalLedger(starting_capital=10_000.0)

    ledger.apply_fill(symbol="AAPL", side="buy", qty=10, price=100.0)
    # Position open: no realized P&L yet.
    assert ledger.realized_pnl() == 0.0

    ledger.apply_fill(symbol="AAPL", side="sell", qty=10, price=110.0)
    assert ledger.realized_pnl() == 100.0
    # Flat now => no unrealized regardless of marks.
    assert ledger.unrealized_pnl({"AAPL": 999.0}) == 0.0
    assert ledger.total_equity({"AAPL": 999.0}) == 10_100.0


def test_open_position_marks_unrealized_and_equity():
    """Open long marked above entry contributes positive unrealized P&L."""
    ledger = CapitalLedger(starting_capital=5_000.0)
    ledger.apply_fill(symbol="MSFT", side="buy", qty=5, price=200.0)

    # Marked at 210 => (210-200)*5 = +50 unrealized.
    assert ledger.unrealized_pnl({"MSFT": 210.0}) == 50.0
    assert ledger.realized_pnl() == 0.0
    assert ledger.total_equity({"MSFT": 210.0}) == 5_050.0


def test_short_round_trip_realizes_pnl():
    """Sell 4 @ 50, buy 4 @ 40 => +40 realized on the short."""
    ledger = CapitalLedger(starting_capital=1_000.0)
    ledger.apply_fill(symbol="TSLA", side="sell", qty=4, price=50.0)
    assert ledger.unrealized_pnl({"TSLA": 45.0}) == 20.0  # short up 5/sh on 4 sh

    ledger.apply_fill(symbol="TSLA", side="buy", qty=4, price=40.0)
    assert ledger.realized_pnl() == 40.0
    assert ledger.total_equity({"TSLA": 999.0}) == 1_040.0


def test_drawdown_against_peak_equity():
    """Peak equity tracks the high-water mark; drawdown is peak-relative."""
    ledger = CapitalLedger(starting_capital=10_000.0)

    # Win to lift equity to 11,000 (peak).
    ledger.apply_fill(symbol="AAPL", side="buy", qty=10, price=100.0)
    ledger.apply_fill(symbol="AAPL", side="sell", qty=10, price=200.0)
    assert ledger.total_equity({}) == 11_000.0
    assert ledger.peak_equity() == 11_000.0
    assert ledger.drawdown({}) == 0.0  # at the peak

    # Losing round-trip realizes -100 => cumulative realized 900, equity 10,900.
    ledger.apply_fill(symbol="AAPL", side="buy", qty=10, price=100.0)
    ledger.apply_fill(symbol="AAPL", side="sell", qty=10, price=90.0)
    assert ledger.total_equity({}) == 10_900.0
    assert ledger.peak_equity() == 11_000.0  # peak is sticky
    assert ledger.drawdown({}) == (11_000.0 - 10_900.0) / 11_000.0


def test_drawdown_includes_open_marks():
    """An open mark below entry creates drawdown without a closed fill."""
    ledger = CapitalLedger(starting_capital=10_000.0)
    ledger.apply_fill(symbol="AAPL", side="buy", qty=10, price=100.0)
    # Peak observed at entry mark (equity == 10,000), then mark drops to 90.
    assert ledger.peak_equity({"AAPL": 100.0}) == 10_000.0
    dd = ledger.drawdown({"AAPL": 90.0})
    assert dd == (10_000.0 - 9_900.0) / 10_000.0


def test_detect_phantom_pnl_flags_unattributed_delta():
    """A db-reported P&L that does not match attributed fills is phantom."""
    ledger = CapitalLedger(starting_capital=10_000.0)
    ledger.apply_fill(symbol="AAPL", side="buy", qty=10, price=100.0)
    ledger.apply_fill(symbol="AAPL", side="sell", qty=10, price=110.0)
    # Ledger attributes +100 realized; DB claims +500 from nowhere.
    assert ledger.detect_phantom_pnl(500.0) is True


def test_detect_phantom_pnl_passes_reconciled_delta():
    """A db-reported P&L that matches attributed realized P&L is NOT phantom."""
    ledger = CapitalLedger(starting_capital=10_000.0)
    ledger.apply_fill(symbol="AAPL", side="buy", qty=10, price=100.0)
    ledger.apply_fill(symbol="AAPL", side="sell", qty=10, price=110.0)
    assert ledger.detect_phantom_pnl(100.0) is False


def test_detect_phantom_pnl_tolerates_float_noise():
    """Tiny floating-point differences within tolerance are NOT phantom."""
    ledger = CapitalLedger(starting_capital=10_000.0)
    ledger.apply_fill(symbol="AAPL", side="buy", qty=3, price=33.33)
    ledger.apply_fill(symbol="AAPL", side="sell", qty=3, price=44.44)
    realized = ledger.realized_pnl()
    assert ledger.detect_phantom_pnl(realized + 1e-9) is False
