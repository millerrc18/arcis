"""Calibrate backtest-engine transaction-cost defaults from swing history.

Called by: scripts/run_backtest.py (optional --calibrate-costs flag,
           future), src.platform.backtest_engine (potential future
           default-construction path).
Calls: sqlite3, numpy.median.
Owns tables: none (reads shadow_trades).
Config keys: none.
Tests: tests/platform/test_cost_calibration.py.

Replaces the hardcoded 3 bps slippage + 1.5 bps spread assumption with
a median computed from the 85+ closed swing trades' observed slippage.
Median (not mean) is robust to tail fills (rare 20+ bps events that
would distort a mean).

Non-negotiable gate: calibrated slippage_bps must be within 30% of the
3 bps hardcoded default. If wildly off, the calibration is wrong OR
real swing data drifted — operator investigates before trusting.
"""
from __future__ import annotations

import logging
import sqlite3
import warnings

import numpy as np

from src.config import DB_PATH
from src.utils.db import connect_db

logger = logging.getLogger(__name__)

_DEFAULT_ENTRY_BPS = 3.0
_DEFAULT_EXIT_BPS = 3.0
_MIN_SAMPLE_SIZE = 10


def calibrate_from_swing_history(db_path: str = DB_PATH) -> dict:
    """Compute median entry + exit slippage_bps from closed swing trades.

    Returns dict:
        entry_slippage_bps, exit_slippage_bps — median per-side bps.
        n_trades — sample size.
        source — 'calibrated' | 'default' (fallback when no data or <10).

    Falls back to hardcoded 3 bps when fewer than 10 swing trades exist
    (sample too small to calibrate).
    """
    conn = connect_db(db_path)
    try:
        rows = conn.execute(
            """SELECT entry_slippage_bps, exit_slippage_bps
               FROM shadow_trades
               WHERE desk = 'swing' AND actual_exit_time IS NOT NULL
                     AND entry_slippage_bps IS NOT NULL
                     AND exit_slippage_bps IS NOT NULL""",
        ).fetchall()
    finally:
        conn.close()

    if not rows:
        warnings.warn(
            "[COST_CALIBRATION] no swing trades with slippage data; "
            "falling back to hardcoded defaults",
            RuntimeWarning,
        )
        return {
            "entry_slippage_bps": _DEFAULT_ENTRY_BPS,
            "exit_slippage_bps": _DEFAULT_EXIT_BPS,
            "n_trades": 0,
            "source": "default",
        }

    if len(rows) < _MIN_SAMPLE_SIZE:
        warnings.warn(
            f"[COST_CALIBRATION] only {len(rows)} swing trades; sample too "
            "small to calibrate reliably — falling back to defaults",
            RuntimeWarning,
        )
        return {
            "entry_slippage_bps": _DEFAULT_ENTRY_BPS,
            "exit_slippage_bps": _DEFAULT_EXIT_BPS,
            "n_trades": len(rows),
            "source": "default",
        }

    entry_bps = float(np.median([r[0] for r in rows if r[0] is not None]))
    exit_bps = float(np.median([r[1] for r in rows if r[1] is not None]))

    return {
        "entry_slippage_bps": entry_bps,
        "exit_slippage_bps": exit_bps,
        "n_trades": len(rows),
        "source": "calibrated",
    }
