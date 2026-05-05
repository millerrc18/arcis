"""Live-fill cost calibration from shadow_trades closed positions.

Called by: future cost-aware backtests (T2.08), operator CLI
Calls: src.utils.db.connect_db
Owns tables: none (read-only from shadow_trades)
Config keys: none
Tests: tests/cost_model/test_calibration.py

Reads closed shadow_trades and computes realized slippage and commission
metrics, writing results to a JSON file for use by cost-aware backtests.
"""

import json
import sqlite3
import statistics
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.config import DB_PATH
from src.utils.db import connect_db
from src.shadow_trading.exit_reason import outcome_stats_filter_sql

_DEFAULT_OUTPUT_PATH = str(Path(DB_PATH).parent / "cost_calibration.json")


def _compute_percentile(sorted_values: list[float], pct: float) -> float:
    n = len(sorted_values)
    if n == 0:
        return 0.0
    idx = (pct / 100.0) * (n - 1)
    lo = int(idx)
    hi = min(lo + 1, n - 1)
    return sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * (idx - lo)


def _aggregate_rows(rows: list) -> tuple[list[float], list[float], list[float], dict[str, int]]:
    entry_slips: list[float] = []
    exit_slips: list[float] = []
    round_trips: list[float] = []
    count_by_ticker: dict[str, int] = {}
    for row in rows:
        e = (row["fill_entry_price"] - row["signal_entry_price"]) / row["signal_entry_price"] * 10_000
        x = (row["signal_exit_price"] - row["fill_exit_price"]) / row["signal_exit_price"] * 10_000
        entry_slips.append(e)
        exit_slips.append(x)
        round_trips.append(e + x)
        t = row["ticker"]
        count_by_ticker[t] = count_by_ticker.get(t, 0) + 1
    return entry_slips, exit_slips, round_trips, count_by_ticker


def _build_result(
    entry_slips: list[float],
    exit_slips: list[float],
    round_trips: list[float],
    count_by_ticker: dict[str, int],
) -> dict[str, Any]:
    ts = datetime.now(timezone.utc).isoformat()
    if not entry_slips:
        return {
            "total_count": 0,
            "median_entry_slippage_bps": None,
            "p95_entry_slippage_bps": None,
            "median_exit_slippage_bps": None,
            "median_round_trip_cost_bps": None,
            "count_by_ticker": {},
            "last_calibrated_at": ts,
        }
    return {
        "total_count": len(entry_slips),
        "median_entry_slippage_bps": statistics.median(entry_slips),
        "p95_entry_slippage_bps": _compute_percentile(sorted(entry_slips), 95),
        "median_exit_slippage_bps": statistics.median(exit_slips),
        "median_round_trip_cost_bps": statistics.median(round_trips),
        "count_by_ticker": count_by_ticker,
        "last_calibrated_at": ts,
    }


def calibrate(
    conn: sqlite3.Connection | None = None,
    output_path: str = _DEFAULT_OUTPUT_PATH,
) -> dict[str, Any]:
    """Read closed shadow_trades and compute cost calibration metrics.

    Parameters
    ----------
    conn:
        SQLite connection to use. If None, opens the default DB via connect_db().
    output_path:
        Path to write the calibration JSON. Parent directories are created if needed.

    Returns
    -------
    dict with keys: median_entry_slippage_bps, p95_entry_slippage_bps,
    median_exit_slippage_bps, median_round_trip_cost_bps,
    total_count, count_by_ticker, last_calibrated_at.
    """
    _conn = conn if conn is not None else connect_db()
    rows = _conn.execute(
        "SELECT ticker,"
        "       signal_entry_price, fill_entry_price,"
        "       signal_exit_price,  fill_exit_price"
        " FROM shadow_trades"
        " WHERE status = 'closed'"
        "   AND fill_entry_price IS NOT NULL"
        "   AND fill_exit_price  IS NOT NULL"
        "   AND signal_entry_price IS NOT NULL"
        "   AND signal_exit_price  IS NOT NULL"
        "   AND signal_entry_price > 0"
        f"  AND signal_exit_price  > 0 {outcome_stats_filter_sql()}"
    ).fetchall()
    entry_slips, exit_slips, round_trips, count_by_ticker = _aggregate_rows(rows)
    result = _build_result(entry_slips, exit_slips, round_trips, count_by_ticker)
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def get_calibrated_cost_model(
    calibration_path: str = _DEFAULT_OUTPUT_PATH,
) -> dict[str, Any] | None:
    """Read the calibration JSON written by calibrate().

    Returns None if the file does not exist.
    """
    path = Path(calibration_path)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))
