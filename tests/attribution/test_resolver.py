"""Tests for attribution resolver OHLCV data-shape handling (SD#41 D2 fix).

Covers the MultiIndex-column defect that made simulate_mechanical_outcome
return 'loss' at stop_price on day 1 for every resolved trade
(audit: docs/research/attribution-resolver-audit.md).
"""

import sqlite3
from unittest.mock import patch

import pandas as pd
import pytest

from src.attribution.logger import (
    resolve_pending_outcomes,
    simulate_mechanical_outcome,
)


def _flat_columns_frame():
    """Pre-yfinance-multiindex shape: flat string columns."""
    return pd.DataFrame(
        {
            "Open":   [100, 101, 102, 103, 104],
            "High":   [102, 103, 105, 104, 105],
            "Low":    [99, 100, 101, 102, 103],
            "Close":  [101, 102, 104, 103, 104.5],
            "Volume": [1000] * 5,
        },
        index=pd.date_range("2026-01-01", periods=5),
    )


def _multiindex_frame(ticker: str = "AAPL"):
    """Current yfinance shape for single-ticker downloads."""
    df = _flat_columns_frame()
    df.columns = pd.MultiIndex.from_product([df.columns, [ticker]])
    return df


# ── Simulator is pure-logic: flat columns yield the right outcome ─────


def test_simulator_handles_flat_column_ohlcv():
    """Simulator produces the right outcome given correctly-shaped bars."""
    ohlcv = _flat_columns_frame().reset_index().to_dict("records")
    # Entry 100, stop 95, target 105 — target hit on day 3 (High=105)
    outcome, exit_price, days = simulate_mechanical_outcome(
        entry_price=100, stop_price=95, target_price=105,
        timeout_days=7, ohlcv=ohlcv,
    )
    assert outcome == "win"
    assert exit_price == 105
    assert days == 3


def test_simulator_returns_timeout_when_neither_breached():
    """No stop and no target hit -> timeout at last close."""
    ohlcv = _flat_columns_frame().reset_index().to_dict("records")
    outcome, exit_price, days = simulate_mechanical_outcome(
        entry_price=100, stop_price=80, target_price=120,
        timeout_days=7, ohlcv=ohlcv,
    )
    assert outcome == "timeout"
    assert exit_price == pytest.approx(104.5)
    assert days == 5


def test_simulator_returns_loss_when_stop_hit_first():
    """Low <= stop should trip the stop-first branch."""
    ohlcv = _flat_columns_frame().reset_index().to_dict("records")
    outcome, exit_price, days = simulate_mechanical_outcome(
        entry_price=100, stop_price=99.5, target_price=110,
        timeout_days=7, ohlcv=ohlcv,
    )
    assert outcome == "loss"
    assert exit_price == 99.5
    assert days == 1


# ── The D2-specific bug prevention ────────────────────────────────────


def _seed_pending(db_path: str, attribution_id: str = "test-1", ticker: str = "AAPL"):
    conn = sqlite3.connect(db_path)
    conn.executescript("""
        CREATE TABLE attribution_trades (
          attribution_id TEXT PRIMARY KEY, ticker TEXT, scan_timestamp TEXT,
          ranker_only_entry REAL, ranker_only_stop REAL, ranker_only_target REAL,
          ranker_only_outcome TEXT, ranker_only_pnl_pct REAL
        );
    """)
    conn.execute(
        "INSERT INTO attribution_trades VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (attribution_id, ticker, "2026-01-01T10:00:00-05:00",
         100.0, 95.0, 105.0, "pending", None),
    )
    conn.commit()
    conn.close()


def test_resolve_pending_flattens_multiindex_before_simulating(tmp_path):
    """Regression: yfinance MultiIndex columns must not slip through unflattened.

    Before the D2 fix, bar.get("Low") returned the default 0 because the
    DataFrame had tuple-keyed columns. Every trade exited at stop on day 1.
    The _flat_columns_frame has High=105 on day 3, so a correctly-flattened
    MultiIndex frame should produce ('win', 105, 3).
    """
    db = str(tmp_path / "resolver.db")
    _seed_pending(db)

    with patch("yfinance.download", return_value=_multiindex_frame("AAPL")):
        n = resolve_pending_outcomes(db_path=db)

    assert n == 1
    conn = sqlite3.connect(db)
    row = conn.execute(
        "SELECT ranker_only_outcome, ranker_only_pnl_pct FROM attribution_trades"
    ).fetchone()
    conn.close()
    # ('loss', -5.0) is the bug signature — must not appear here.
    assert row[0] == "win", (
        f"Got {row}; if it's ('loss', -5.0) the MultiIndex flatten regressed."
    )
    assert row[1] == pytest.approx(5.0)


def test_resolve_pending_handles_empty_yfinance_response(tmp_path):
    """Empty DataFrame -> row stays 'pending', no crash, no partial update."""
    db = str(tmp_path / "resolver.db")
    _seed_pending(db, attribution_id="empty-1", ticker="DELISTED")

    with patch("yfinance.download", return_value=pd.DataFrame()):
        n = resolve_pending_outcomes(db_path=db)

    assert n == 0
    conn = sqlite3.connect(db)
    row = conn.execute(
        "SELECT ranker_only_outcome, ranker_only_pnl_pct FROM attribution_trades"
    ).fetchone()
    conn.close()
    assert row[0] == "pending", (
        "Empty yfinance response must leave the row as 'pending' for retry."
    )
    assert row[1] is None


def test_resolve_pending_flat_frame_also_works(tmp_path):
    """Backwards compat: if upstream ever returns flat columns, we must still resolve."""
    db = str(tmp_path / "resolver.db")
    _seed_pending(db, attribution_id="flat-1")

    with patch("yfinance.download", return_value=_flat_columns_frame()):
        n = resolve_pending_outcomes(db_path=db)

    assert n == 1
    conn = sqlite3.connect(db)
    row = conn.execute(
        "SELECT ranker_only_outcome FROM attribution_trades"
    ).fetchone()
    conn.close()
    assert row[0] == "win"
