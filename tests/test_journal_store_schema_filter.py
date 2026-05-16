"""Tests for _filter_to_schema — the SQL column-name injection guard (#415).

Verifies that the journal-layer helper drops dict keys not declared in the
schema registry, closing the f-string interpolation vector in log_recommendation,
insert_shadow_trade, update_shadow_trade, and update_recommendation.
"""
from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

from src.journal.store import (
    close_shadow_trade,
    _filter_to_schema,
    initialize_database,
    insert_shadow_trade,
    update_shadow_trade,
)


@pytest.fixture
def tmp_db(tmp_path):
    db = tmp_path / "journal.sqlite3"
    initialize_database(str(db))
    return str(db)


def _valid_trade() -> dict:
    et = ZoneInfo("America/New_York")
    return {
        "trade_id": str(uuid.uuid4()),
        "ticker": "AAPL",
        "direction": "long",
        "planned_shares": 10,
        "entry_price": 150.0,
        "stop_price": 140.0,
        "target_1": 160.0,
        "target_2": 170.0,
        "status": "open",
        "source": "paper",
        "created_at": datetime.now(et).isoformat(),
        "updated_at": datetime.now(et).isoformat(),
    }


class TestFilterHelper:
    def test_preserves_known_keys(self):
        data = {"ticker": "AAPL", "direction": "long", "entry_price": 100.0}
        filtered = _filter_to_schema("shadow_trades", data)
        assert filtered == data

    def test_drops_sql_injection_key(self):
        data = {"ticker": "AAPL", "note = 'x' --": "gotcha"}
        filtered = _filter_to_schema("shadow_trades", data)
        assert "note = 'x' --" not in filtered
        assert filtered["ticker"] == "AAPL"

    def test_drops_unknown_column(self):
        data = {"ticker": "AAPL", "totally_new_field_not_in_schema": 42}
        filtered = _filter_to_schema("shadow_trades", data)
        assert "totally_new_field_not_in_schema" not in filtered
        assert filtered["ticker"] == "AAPL"

    def test_drops_non_identifier_syntax(self):
        data = {"ticker": "AAPL", "bad-name": 1, "1leading_digit": 2, "; DROP TABLE x;": 3}
        filtered = _filter_to_schema("shadow_trades", data)
        for bad in ("bad-name", "1leading_digit", "; DROP TABLE x;"):
            assert bad not in filtered
        assert filtered["ticker"] == "AAPL"

    def test_unknown_table_passes_through(self):
        data = {"anything": "goes"}
        filtered = _filter_to_schema("not_a_real_table_xyz", data)
        assert filtered == data

    def test_empty_input_empty_output(self):
        assert _filter_to_schema("shadow_trades", {}) == {}

    def test_logs_dropped_keys(self, caplog):
        data = {"ticker": "AAPL", "evil": 1}
        with caplog.at_level("WARNING"):
            _filter_to_schema("shadow_trades", data)
        assert any("dropped non-schema keys" in r.message for r in caplog.records)
        assert any("evil" in r.message for r in caplog.records)


class TestWritePathsIntegration:
    def test_insert_shadow_trade_drops_injection_key(self, tmp_db, caplog):
        trade = _valid_trade()
        trade_id = trade["trade_id"]
        trade["note = 'pwned' --"] = "ignored"
        trade["some_random_field"] = "also ignored"

        with caplog.at_level("WARNING"):
            returned_id = insert_shadow_trade(trade, db_path=tmp_db)

        assert returned_id == trade_id
        with sqlite3.connect(tmp_db) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM shadow_trades WHERE trade_id=?", (trade_id,)
            ).fetchone()
        assert row is not None
        assert row["ticker"] == "AAPL"
        assert any("dropped non-schema keys" in r.message for r in caplog.records)

    def test_update_shadow_trade_drops_injection_keys(self, tmp_db):
        trade = _valid_trade()
        trade_id = insert_shadow_trade(trade, db_path=tmp_db)

        update_shadow_trade(
            trade_id,
            {
                "entry_price": 155.0,
                "evil = 'hax' --": 999,
                "unknown_col_xyz": "bad",
            },
            db_path=tmp_db,
        )

        with sqlite3.connect(tmp_db) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM shadow_trades WHERE trade_id=?", (trade_id,)
            ).fetchone()
        assert row["entry_price"] == 155.0

    def test_update_shadow_trade_all_keys_invalid_is_noop(self, tmp_db):
        trade = _valid_trade()
        trade_id = insert_shadow_trade(trade, db_path=tmp_db)
        update_shadow_trade(
            trade_id,
            {"bogus_col": 1, "another-bad-one": 2},
            db_path=tmp_db,
        )
        with sqlite3.connect(tmp_db) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT entry_price FROM shadow_trades WHERE trade_id=?", (trade_id,)
            ).fetchone()
        assert row["entry_price"] == 150.0

    def test_update_shadow_trade_preserves_valid_update(self, tmp_db):
        trade = _valid_trade()
        trade_id = insert_shadow_trade(trade, db_path=tmp_db)
        update_shadow_trade(
            trade_id,
            {"entry_price": 160.0, "target_1": 175.0},
            db_path=tmp_db,
        )
        with sqlite3.connect(tmp_db) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT entry_price, target_1 FROM shadow_trades WHERE trade_id=?",
                (trade_id,),
            ).fetchone()
        assert row["entry_price"] == 160.0
        assert row["target_1"] == 175.0

    def test_close_shadow_trade_coerces_invalid_exit_reason(self, tmp_db):
        trade = _valid_trade()
        trade_id = insert_shadow_trade(trade, db_path=tmp_db)

        with patch("src.journal.store._build_spy_excess_fields", return_value={}), \
             patch("src.journal.store._broadcast_and_log_close"):
            close_shadow_trade(
                trade_id=trade_id,
                exit_price=155.0,
                exit_time=datetime.now(ZoneInfo("America/New_York")).isoformat(),
                exit_reason=None,
                pnl_dollars=50.0,
                pnl_pct=3.3,
                db_path=tmp_db,
            )

        with sqlite3.connect(tmp_db) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT status, exit_reason FROM shadow_trades WHERE trade_id=?",
                (trade_id,),
            ).fetchone()
        assert row["status"] == "closed"
        assert row["exit_reason"] == "unknown"
