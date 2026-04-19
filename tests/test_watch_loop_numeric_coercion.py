"""Regression tests for TypeError leaks in watch-loop numeric paths.

Two watch-loop tasks were throwing `TypeError: '<' not supported between
instances of 'str' and 'int'` every cycle:

  * morning watchlist → rank_universe → _score_ticker @ ranker.py:195
  * post-close stats pulse → compute_window_stats @ journal/stats.py:71

Root cause in both: SQLite REAL columns can return as TEXT after a DB
recovery (#195), and the code compared the raw value against a numeric
literal. Defensive `float()` coercion fixes both.
"""
from __future__ import annotations

import sqlite3
import sys
import types
from pathlib import Path
from unittest.mock import patch


# ── Ranker: _score_ticker tolerates string numeric features ──────────

def test_score_ticker_survives_string_iv_rank():
    """iv_rank='22' (string, not int) must not raise TypeError."""
    from src.ranking.ranker import _score_ticker

    features = {
        "trend_state": "uptrend",
        "relative_strength_state": "neutral",
        "pullback_depth_pct": -5.0,
        "iv_rank": "22",  # ← the bug: string leaked from SQLite
        "put_call_vol_ratio": "0.9",
    }
    score = _score_ticker(features)  # must not raise
    assert isinstance(score, (int, float))
    assert 0 <= score <= 100


def test_score_ticker_survives_string_pullback_and_volume():
    """All numeric comparisons must coerce — not just iv_rank."""
    from src.ranking.ranker import _score_ticker

    features = {
        "trend_state": "strong_uptrend",
        "relative_strength_state": "strong_outperformer",
        "_sector_rs_score": "18.5",
        "pullback_depth_pct": "-4.5",
        "dist_to_sma20_pct": "-2.0",
        "volume_ratio_20d": "0.7",
        "iv_rank": "80",
        "put_call_vol_ratio": "1.5",
    }
    score = _score_ticker(features)
    assert isinstance(score, (int, float))


def test_score_ticker_gibberish_value_defaults_gracefully():
    """Non-numeric strings must not raise; they default to 0.0 / None."""
    from src.ranking.ranker import _score_ticker

    features = {
        "trend_state": "neutral",
        "relative_strength_state": "neutral",
        "pullback_depth_pct": "n/a",
        "iv_rank": "N/A",
    }
    score = _score_ticker(features)
    assert isinstance(score, (int, float))


# ── Stats pulse: compute_window_stats tolerates string numerics ─────

def _make_shadow_trades_db(tmp_path: Path, rows: list[tuple]) -> str:
    """Build a minimal shadow_trades-schema DB with the given rows."""
    db = tmp_path / "stats_test.db"
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE shadow_trades (
            trade_id TEXT PRIMARY KEY,
            status TEXT,
            quarantined INTEGER DEFAULT 0,
            actual_exit_time TEXT,
            pnl_pct NUMERIC,
            pnl_dollars NUMERIC,
            excess_return NUMERIC
        );
        """
    )
    for i, (pnl_pct, pnl_d, excess) in enumerate(rows):
        conn.execute(
            "INSERT INTO shadow_trades "
            "(trade_id, status, quarantined, actual_exit_time, "
            " pnl_pct, pnl_dollars, excess_return) "
            "VALUES (?, 'closed', 0, '2026-04-19T10:00:00', ?, ?, ?)",
            (f"t{i}", pnl_pct, pnl_d, excess),
        )
    conn.commit()
    conn.close()
    return str(db)


def test_compute_window_stats_survives_string_pnl_pct(tmp_path):
    """pnl_pct='1.5' (string) must not raise on the `p > 0` comparison."""
    from src.journal import stats

    # Mix of string + float + None (matches what #195 recovery produces)
    db = _make_shadow_trades_db(tmp_path, [
        ("1.5", 100.0, 0.01),   # winner, as str
        ("-0.8", -50.0, -0.005),  # loser, as str
        (2.0, 150.0, None),      # winner, float
        (None, None, None),      # all-None row (filtered)
    ])
    result = stats.compute_window_stats(db)
    assert result["count"] == 4  # total rows (including all-None)
    assert result["wins"] == 2   # 1.5 and 2.0 coerce correctly
    assert result["losses"] == 1
    assert result["best_pct"] == 2.0
    assert result["worst_pct"] == -0.8


def test_compute_window_stats_drops_unparseable_values(tmp_path):
    """Gibberish in pnl_pct drops the row rather than raising."""
    from src.journal import stats

    db = _make_shadow_trades_db(tmp_path, [
        ("1.0", 50.0, 0.01),
        ("garbage", 0.0, 0.0),  # unparseable — dropped
        ("2.5", 75.0, 0.02),
    ])
    result = stats.compute_window_stats(db)
    # garbage row drops out of pnl_pcts → 2 wins on parseable rows
    assert result["wins"] == 2
    assert result["best_pct"] == 2.5
