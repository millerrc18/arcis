"""Tests for gate-proposal KPI counts in src/analytics/kpis_compute.py.

Sprint 2 T6 — counts of methodology-gate proposals by decision
(promote / reject / defer) over 1d / 7d / 30d windows.

All tests are hermetic: SQLite :memory: seeded inline, no .env dependency,
no network calls.
"""

import json
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from tests.conftest import init_test_db

from src.analytics.kpis_compute import get_gate_proposal_counts


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _gate_result_json(decision: str) -> str:
    return json.dumps({"methodology_gate": {"decision": decision}})


def _seed_event(conn, triggered_by: str, decision: str, hours_ago: float) -> None:
    ts = _iso(_now_utc() - timedelta(hours=hours_ago))
    conn.execute(
        """INSERT INTO strategy_promotion_events
           (strategy_id, from_status, to_status, triggered_by, gate_result_json, timestamp)
           VALUES (?, ?, ?, ?, ?, ?)""",
        ("strategy-test", "backtested", "backtested", triggered_by,
         _gate_result_json(decision), ts),
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_gate_proposal_counts_by_decision_1d(tmp_path):
    """5 gate_proposal rows within 24h: {promote:2, reject:1, defer:2}."""
    db = str(tmp_path / "test.db")
    init_test_db(db, tables=["strategy_promotion_events"])
    conn = sqlite3.connect(db)
    try:
        # 5 rows well within 1d window
        _seed_event(conn, "gate_proposal", "promote", 1)
        _seed_event(conn, "gate_proposal", "promote", 2)
        _seed_event(conn, "gate_proposal", "reject",  3)
        _seed_event(conn, "gate_proposal", "defer",   4)
        _seed_event(conn, "gate_proposal", "defer",   5)
        conn.commit()
    finally:
        conn.close()

    result = get_gate_proposal_counts(db_path=db)

    assert result["1d"]["promote"] == 2
    assert result["1d"]["reject"] == 1
    assert result["1d"]["defer"] == 2


def test_gate_proposal_counts_by_decision_7d(tmp_path):
    """Rows at 1d/3d/7d/8d ago: 7d window includes first three, excludes 8d-old."""
    db = str(tmp_path / "test.db")
    init_test_db(db, tables=["strategy_promotion_events"])
    conn = sqlite3.connect(db)
    try:
        _seed_event(conn, "gate_proposal", "promote", 24)      # 1d ago — inside 7d
        _seed_event(conn, "gate_proposal", "reject",  72)      # 3d ago — inside 7d
        _seed_event(conn, "gate_proposal", "defer",   7 * 24 - 1)  # ~7d ago — inside 7d
        _seed_event(conn, "gate_proposal", "promote", 8 * 24)  # 8d ago — outside 7d
        conn.commit()
    finally:
        conn.close()

    result = get_gate_proposal_counts(db_path=db)

    # 7d window: promote=1, reject=1, defer=1 (8d-old excluded)
    assert result["7d"]["promote"] == 1
    assert result["7d"]["reject"] == 1
    assert result["7d"]["defer"] == 1


def test_gate_proposal_counts_by_decision_30d(tmp_path):
    """Rows at 1d/15d/29d/31d ago: 30d window excludes 31d-old row."""
    db = str(tmp_path / "test.db")
    init_test_db(db, tables=["strategy_promotion_events"])
    conn = sqlite3.connect(db)
    try:
        _seed_event(conn, "gate_proposal", "promote", 24)        # 1d — inside 30d
        _seed_event(conn, "gate_proposal", "defer",   15 * 24)   # 15d — inside 30d
        _seed_event(conn, "gate_proposal", "reject",  29 * 24)   # 29d — inside 30d
        _seed_event(conn, "gate_proposal", "promote", 31 * 24)   # 31d — outside 30d
        conn.commit()
    finally:
        conn.close()

    result = get_gate_proposal_counts(db_path=db)

    # 30d window: promote=1, defer=1, reject=1 (31d-old excluded)
    assert result["30d"]["promote"] == 1
    assert result["30d"]["reject"] == 1
    assert result["30d"]["defer"] == 1


def test_operator_confirm_rows_excluded_from_proposal_counts(tmp_path):
    """operator_confirm rows must NOT appear in gate-proposal counts."""
    db = str(tmp_path / "test.db")
    init_test_db(db, tables=["strategy_promotion_events"])
    conn = sqlite3.connect(db)
    try:
        # 2 gate_proposal rows
        _seed_event(conn, "gate_proposal", "promote", 1)
        _seed_event(conn, "gate_proposal", "reject",  2)
        # 3 operator_confirm rows — must be excluded
        _seed_event(conn, "operator_confirm", "promote", 1)
        _seed_event(conn, "operator_confirm", "defer",   2)
        _seed_event(conn, "operator_confirm", "reject",  3)
        conn.commit()
    finally:
        conn.close()

    result = get_gate_proposal_counts(db_path=db)

    # Only the gate_proposal rows should count
    assert result["1d"]["promote"] == 1
    assert result["1d"]["reject"] == 1
    assert result["1d"]["defer"] == 0
    # Total across all decisions must equal 2 (not 5)
    total_1d = sum(result["1d"].values())
    assert total_1d == 2


def test_empty_table_returns_zero_counts(tmp_path):
    """Empty strategy_promotion_events → all zero counts across all windows."""
    db = str(tmp_path / "test.db")
    init_test_db(db, tables=["strategy_promotion_events"])

    result = get_gate_proposal_counts(db_path=db)

    for window in ("1d", "7d", "30d"):
        assert result[window]["promote"] == 0
        assert result[window]["reject"] == 0
        assert result[window]["defer"] == 0


def test_malformed_gate_result_json_handled_gracefully(tmp_path):
    """Malformed gate_result_json must not raise; row is counted as 'unknown'."""
    db = str(tmp_path / "test.db")
    init_test_db(db, tables=["strategy_promotion_events"])
    conn = sqlite3.connect(db)
    try:
        ts = _iso(_now_utc() - timedelta(hours=1))
        # Row with invalid JSON
        conn.execute(
            """INSERT INTO strategy_promotion_events
               (strategy_id, from_status, to_status, triggered_by, gate_result_json, timestamp)
               VALUES (?, ?, ?, ?, ?, ?)""",
            ("strategy-test", "backtested", "backtested", "gate_proposal",
             "not json", ts),
        )
        # Row with valid JSON but missing methodology_gate key
        conn.execute(
            """INSERT INTO strategy_promotion_events
               (strategy_id, from_status, to_status, triggered_by, gate_result_json, timestamp)
               VALUES (?, ?, ?, ?, ?, ?)""",
            ("strategy-test", "backtested", "backtested", "gate_proposal",
             json.dumps({"other_key": "value"}), ts),
        )
        # Row with NULL gate_result_json
        conn.execute(
            """INSERT INTO strategy_promotion_events
               (strategy_id, from_status, to_status, triggered_by, gate_result_json, timestamp)
               VALUES (?, ?, ?, ?, ?, ?)""",
            ("strategy-test", "backtested", "backtested", "gate_proposal",
             None, ts),
        )
        conn.commit()
    finally:
        conn.close()

    # Must not raise
    result = get_gate_proposal_counts(db_path=db)

    # All windows must be present with canonical keys
    for window in ("1d", "7d", "30d"):
        assert "promote" in result[window]
        assert "reject" in result[window]
        assert "defer" in result[window]
        assert "unknown" in result[window]
    # The 3 malformed rows land in 'unknown'
    assert result["1d"]["unknown"] == 3
