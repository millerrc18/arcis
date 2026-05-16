"""Tests for stress test win-rate computation methodology.

Root-cause analysis (P7): All 7 historical scenarios showed win_rate=0.0.
The win-counting logic inside run_scenario() was not extractable for unit
testing, making it impossible to verify independently of yfinance or the DB.

Fix: extract compute_win_rate() and compute_win_rate_from_trades() as
standalone helpers in src/simulation/engine.py, then test them directly.

Tests:
  (1) 50/50 mix of winning/losing trades → win_rate ≈ 0.50
  (2) All-winners → win_rate = 1.0
  (3) All-losers → win_rate = 0.0
  (4) Unit-test win-counting helper with small (entry, exit) tuples
  (5) Empty trade list → win_rate = 0.0 (no division by zero)
"""

import pytest
from pathlib import Path


# ---------------------------------------------------------------------------
# Import the helpers under test. These must exist in engine.py after the fix.
# ---------------------------------------------------------------------------
from src.simulation.engine import compute_win_rate, compute_win_rate_from_trades


# ---------------------------------------------------------------------------
# Test 1 — 50/50 synthetic scenario
# ---------------------------------------------------------------------------

def _make_trade(outcome: str, entry: float = 100.0) -> dict:
    """Build a minimal trade dict that compute_win_rate_from_trades accepts."""
    if outcome == "win":
        exit_price = entry * 1.03
    elif outcome == "loss":
        exit_price = entry * 0.95
    else:
        exit_price = entry * 1.005  # timeout — small positive
    pnl_pct = (exit_price - entry) / entry * 100
    return {
        "entry": entry,
        "exit": exit_price,
        "outcome": outcome,
        "pnl_pct": round(pnl_pct, 2),
    }


def test_fifty_fifty_win_rate():
    """50 wins + 50 losses → win_rate should be 0.50 ± 0.01."""
    trades = [_make_trade("win") for _ in range(50)] + [_make_trade("loss") for _ in range(50)]
    wr = compute_win_rate_from_trades(trades)
    assert abs(wr - 0.50) < 0.01, f"Expected 0.50, got {wr}"


# ---------------------------------------------------------------------------
# Test 2 — All-winners
# ---------------------------------------------------------------------------

def test_all_winners_win_rate():
    """100 winning trades → win_rate = 1.0."""
    trades = [_make_trade("win") for _ in range(100)]
    wr = compute_win_rate_from_trades(trades)
    assert wr == 1.0, f"Expected 1.0, got {wr}"


# ---------------------------------------------------------------------------
# Test 3 — All-losers
# ---------------------------------------------------------------------------

def test_all_losers_win_rate():
    """100 losing trades → win_rate = 0.0."""
    trades = [_make_trade("loss") for _ in range(100)]
    wr = compute_win_rate_from_trades(trades)
    assert wr == 0.0, f"Expected 0.0, got {wr}"


# ---------------------------------------------------------------------------
# Test 4 — Unit-test win-counting helper with (entry, exit) tuples
# ---------------------------------------------------------------------------

def test_compute_win_rate_tuples():
    """compute_win_rate() accepts a list of (entry, exit) tuples.

    A trade is a win iff exit_price > entry_price (pre-cost gross comparison).
    With 3 wins and 1 loss: expected win_rate = 0.75.
    """
    pairs = [
        (100.0, 103.0),  # win
        (100.0,  95.0),  # loss
        (200.0, 206.0),  # win
        (150.0, 154.5),  # win
    ]
    wr = compute_win_rate(pairs)
    assert abs(wr - 0.75) < 1e-9, f"Expected 0.75, got {wr}"


def test_compute_win_rate_all_wins():
    pairs = [(100.0, 105.0), (200.0, 210.0), (50.0, 55.0)]
    assert compute_win_rate(pairs) == 1.0


def test_compute_win_rate_all_losses():
    pairs = [(100.0, 95.0), (200.0, 190.0)]
    assert compute_win_rate(pairs) == 0.0


# ---------------------------------------------------------------------------
# Test 5 — Edge cases
# ---------------------------------------------------------------------------

def test_empty_trades_no_division_by_zero():
    """Empty trade list must return 0.0, not raise ZeroDivisionError."""
    assert compute_win_rate([]) == 0.0
    assert compute_win_rate_from_trades([]) == 0.0


def test_single_win():
    pairs = [(100.0, 101.0)]
    assert compute_win_rate(pairs) == 1.0


def test_single_loss():
    pairs = [(100.0, 99.0)]
    assert compute_win_rate(pairs) == 0.0


def test_timeout_not_counted_as_win():
    """Timeout trades (outcome='timeout') are NOT wins even if exit > entry."""
    trades = [
        {"entry": 100.0, "exit": 100.5, "outcome": "timeout", "pnl_pct": 0.5},
        {"entry": 100.0, "exit": 103.0, "outcome": "win",     "pnl_pct": 3.0},
        {"entry": 100.0, "exit":  95.0, "outcome": "loss",    "pnl_pct": -5.0},
    ]
    wr = compute_win_rate_from_trades(trades)
    # 1 win out of 3 trades
    assert abs(wr - 1 / 3) < 1e-9, f"Expected {1/3:.6f}, got {wr}"


def test_stress_result_id_is_deterministic_for_upsert():
    """Same scenario payload must produce the same stress_test_results key."""
    from scripts.stress_test import _stress_result_id

    result = {
        "scenario": "covid_crash",
        "start_date": "2020-02-20",
        "end_date": "2020-04-30",
        "model_version": "v0.36.10",
    }
    assert _stress_result_id(result) == _stress_result_id(dict(result))

    changed = dict(result)
    changed["model_version"] = "v0.36.11"
    assert _stress_result_id(result) != _stress_result_id(changed)


def test_stress_test_persistence_has_no_raw_insert_or_replace():
    """PG-routed stress persistence must use engine_aware_upsert."""
    source = Path("scripts/stress_test.py").read_text(encoding="utf-8")
    assert "INSERT OR REPLACE" not in source
    assert "engine_aware_upsert" in source


def test_stress_test_records_yfinance_gap_caveats():
    """Expected historical-data gaps should become structured caveats."""
    source = Path("scripts/stress_test.py").read_text(encoding="utf-8")
    assert "market_data_gaps" in source
    assert "yfinance_historical_gap" in source
