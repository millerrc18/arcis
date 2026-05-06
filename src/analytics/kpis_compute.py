"""KPI compute for daily gate proposals.

Called by: src/api/dashboard_routes.py (T7 wires the read route).
Calls: src.utils.db.connect_db
Owns tables: none (read-only)
Config keys: none
Tests: tests/test_kpis_compute_gate.py

Sprint 2 T6 — surfaces counts of methodology-gate proposals by decision
(promote / reject / defer) over 1d / 7d / 30d rolling windows.

Reads from strategy_promotion_events filtered by triggered_by='gate_proposal'.
'operator_confirm' rows are real promotion transitions and are intentionally
excluded — they are NOT gate-proposal observations.

Decision extraction:
  gate_result_json is a free-form TEXT column. The decision lives at
  gate_result_json['methodology_gate']['decision'].
  Rows where JSON is malformed, NULL, or missing the 'methodology_gate' key
  are counted under an 'unknown' bucket rather than being silently dropped.
  This choice makes data-quality problems visible in the dashboard without
  crashing the KPI pipeline.

Time windows are anchored to UTC now:
  1d  = last 24 h
  7d  = last 7 × 24 h
  30d = last 30 × 24 h
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone

from src.config import DB_PATH
from src.utils.db import connect_db

_WINDOWS = {"1d": 1, "7d": 7, "30d": 30}
_DECISIONS = ("promote", "reject", "defer", "unknown")


def _zero_counts() -> dict:
    return {d: 0 for d in _DECISIONS}


def get_gate_proposal_counts(db_path: str = DB_PATH) -> dict:
    """Return counts of gate proposals by decision over 1d / 7d / 30d windows.

    Returns a dict of the form::

        {
          "1d":  {"promote": int, "reject": int, "defer": int, "unknown": int},
          "7d":  {"promote": int, "reject": int, "defer": int, "unknown": int},
          "30d": {"promote": int, "reject": int, "defer": int, "unknown": int},
        }

    Rows with malformed / NULL gate_result_json or a missing 'methodology_gate'
    key are counted under 'unknown' rather than raising.
    """
    now = datetime.now(timezone.utc)
    cutoffs = {
        window: (now - timedelta(days=days)).isoformat()
        for window, days in _WINDOWS.items()
    }

    result = {window: _zero_counts() for window in _WINDOWS}

    conn = connect_db(db_path)
    try:
        rows = conn.execute(
            """SELECT gate_result_json, timestamp
               FROM strategy_promotion_events
               WHERE triggered_by = 'gate_proposal'
                 AND timestamp >= ?""",
            (cutoffs["30d"],),
        ).fetchall()
    finally:
        conn.close()

    for row in rows:
        ts_str = row["timestamp"]
        gate_json = row["gate_result_json"]

        decision = _extract_decision(gate_json)

        for window, cutoff in cutoffs.items():
            if ts_str >= cutoff:
                result[window][decision] += 1

    return result


def _extract_decision(gate_json: str | None) -> str:
    """Extract the methodology_gate decision from gate_result_json.

    Returns one of 'promote', 'reject', 'defer', or 'unknown'.
    'unknown' is returned when the JSON is NULL, malformed, or missing the
    'methodology_gate.decision' path.
    """
    if gate_json is None:
        return "unknown"
    try:
        parsed = json.loads(gate_json)
    except (json.JSONDecodeError, ValueError):
        return "unknown"
    try:
        decision = parsed["methodology_gate"]["decision"]
    except (KeyError, TypeError):
        return "unknown"
    if decision in ("promote", "reject", "defer"):
        return decision
    return "unknown"
