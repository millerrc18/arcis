"""Phase 3-revised T5 — bracket_monitor._record_check cross-engine verification."""

import sqlite3
from unittest.mock import patch, call

import pytest

from src.shadow_trading.bracket_monitor import _record_check
from tests.conftest import init_test_db


def _make_db(db_path: str) -> None:
    init_test_db(db_path, ["bracket_health"])


def test_record_check_calls_engine_aware_upsert(tmp_path):
    """_record_check must call engine_aware_upsert (not raw conn.execute INSERT)."""
    db_path = str(tmp_path / "bracket.db")
    _make_db(db_path)

    with patch("src.shadow_trading.bracket_monitor.engine_aware_upsert") as mock_upsert:
        _record_check(
            trade_id="trade-1",
            ticker="AAPL",
            stop_status="new",
            target_status="new",
            bracket_intact=True,
            action_taken=None,
            db_path=db_path,
        )

    assert mock_upsert.called, "engine_aware_upsert must be called by _record_check"
    args, kwargs = mock_upsert.call_args
    table_name = args[1] if len(args) > 1 else kwargs.get("table_name")
    row_dict = args[2] if len(args) > 2 else kwargs.get("row_dict")
    action = kwargs.get("action") or (args[3] if len(args) > 3 else None)

    assert table_name == "bracket_health"
    assert action == "ignore"
    assert row_dict["trade_id"] == "trade-1"
    assert row_dict["ticker"] == "AAPL"
    assert row_dict["bracket_intact"] == 1  # int cast for PG INTEGER column


def test_record_check_inserts_rows_sqlite(tmp_path):
    """_record_check writes 3 rows; COUNT(*)==3 and SUM(bracket_intact)==2 on SQLite."""
    db_path = str(tmp_path / "bracket.db")
    _make_db(db_path)

    rows_to_insert = [
        ("trade-1", "AAPL", "new", "new", True, "alerted"),
        ("trade-2", "MSFT", "held", "held", True, None),
        ("trade-3", "GOOG", "canceled", "new", False, "alerted_stop_leg"),
    ]
    for trade_id, ticker, stop_status, target_status, intact, action_taken in rows_to_insert:
        _record_check(
            trade_id=trade_id,
            ticker=ticker,
            stop_status=stop_status,
            target_status=target_status,
            bracket_intact=intact,
            action_taken=action_taken,
            db_path=db_path,
        )

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        count = conn.execute("SELECT COUNT(*) FROM bracket_health").fetchone()[0]
        total_intact = conn.execute("SELECT SUM(bracket_intact) FROM bracket_health").fetchone()[0]
        rows = conn.execute(
            "SELECT check_id, trade_id, ticker, stop_leg_status, target_leg_status, "
            "bracket_intact, action_taken, checked_at FROM bracket_health ORDER BY trade_id"
        ).fetchall()

    assert count == 3
    assert total_intact == 2

    # Verify all 8 columns round-trip correctly
    row_map = {r["trade_id"]: r for r in rows}

    assert row_map["trade-1"]["ticker"] == "AAPL"
    assert row_map["trade-1"]["stop_leg_status"] == "new"
    assert row_map["trade-1"]["target_leg_status"] == "new"
    assert row_map["trade-1"]["bracket_intact"] == 1
    assert row_map["trade-1"]["action_taken"] == "alerted"
    assert row_map["trade-1"]["checked_at"] is not None
    assert row_map["trade-1"]["check_id"] is not None

    assert row_map["trade-2"]["ticker"] == "MSFT"
    assert row_map["trade-2"]["stop_leg_status"] == "held"
    assert row_map["trade-2"]["target_leg_status"] == "held"
    assert row_map["trade-2"]["bracket_intact"] == 1
    assert row_map["trade-2"]["action_taken"] is None

    assert row_map["trade-3"]["ticker"] == "GOOG"
    assert row_map["trade-3"]["stop_leg_status"] == "canceled"
    assert row_map["trade-3"]["target_leg_status"] == "new"
    assert row_map["trade-3"]["bracket_intact"] == 0
    assert row_map["trade-3"]["action_taken"] == "alerted_stop_leg"


def test_record_check_bracket_intact_int_cast_sqlite(tmp_path):
    """bracket_intact is stored as 1/0 INTEGER (not True/False) on SQLite."""
    db_path = str(tmp_path / "bracket.db")
    _make_db(db_path)

    _record_check(
        trade_id="trade-true",
        ticker="AAPL",
        stop_status="new",
        target_status="new",
        bracket_intact=True,
        action_taken=None,
        db_path=db_path,
    )
    _record_check(
        trade_id="trade-false",
        ticker="AAPL",
        stop_status="canceled",
        target_status="new",
        bracket_intact=False,
        action_taken=None,
        db_path=db_path,
    )

    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            "SELECT trade_id, bracket_intact FROM bracket_health ORDER BY trade_id"
        ).fetchall()

    row_map = {r[0]: r[1] for r in rows}
    assert row_map["trade-true"] == 1
    assert row_map["trade-false"] == 0
