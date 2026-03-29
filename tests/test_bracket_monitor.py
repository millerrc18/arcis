"""Tests for bracket health monitoring."""

import sqlite3
from unittest.mock import patch

from src.shadow_trading.bracket_monitor import (
    BRACKET_HEALTH_SCHEMA,
    _classify_legs,
    check_bracket_health,
    ensure_bracket_health_table,
)


SHADOW_TRADES_SCHEMA = """
CREATE TABLE shadow_trades (
    trade_id TEXT PRIMARY KEY,
    ticker TEXT NOT NULL,
    status TEXT DEFAULT 'open',
    alpaca_order_id TEXT,
    order_type TEXT,
    created_at TEXT,
    updated_at TEXT
)
"""


def _make_db(db_path: str) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.executescript(SHADOW_TRADES_SCHEMA)
        conn.executescript(BRACKET_HEALTH_SCHEMA)
        conn.commit()


def _insert_trade(
    db_path: str,
    trade_id: str = "trade-1",
    ticker: str = "AAPL",
    order_id: str = "order-1",
    order_type: str = "bracket",
) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO shadow_trades "
            "(trade_id, ticker, status, alpaca_order_id, order_type, created_at, updated_at) "
            "VALUES (?, ?, 'open', ?, ?, '2026-03-29T09:30:00', '2026-03-29T09:30:00')",
            (trade_id, ticker, order_id, order_type),
        )
        conn.commit()


def test_ensure_bracket_health_table_creates_table(tmp_path):
    db_path = str(tmp_path / "bracket.db")

    ensure_bracket_health_table(db_path)

    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'bracket_health'"
        ).fetchone()
    assert row is not None


def test_classify_legs_reads_stop_and_target_status():
    stop_status, target_status = _classify_legs(
        {
            "legs": [
                {"type": "stop", "status": "new", "stop_price": 180.0},
                {"type": "limit", "status": "held", "limit_price": 200.0},
            ]
        }
    )

    assert stop_status == "new"
    assert target_status == "held"


def test_check_bracket_health_records_intact_bracket(tmp_path):
    db_path = str(tmp_path / "bracket.db")
    _make_db(db_path)
    _insert_trade(db_path)

    order_status = {
        "legs": [
            {"type": "stop", "status": "new", "stop_price": 180.0},
            {"type": "limit", "status": "held", "limit_price": 200.0},
        ]
    }

    with patch("src.shadow_trading.alpaca_adapter.get_order_status", return_value=order_status):
        result = check_bracket_health(db_path=db_path)

    assert result["checked"] == 1
    assert result["protected"] == 1
    assert result["broken"] == []

    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT bracket_intact, stop_leg_status, target_leg_status FROM bracket_health"
        ).fetchone()
    assert row == (1, "new", "held")


def test_check_bracket_health_alerts_on_broken_stop(tmp_path):
    db_path = str(tmp_path / "bracket.db")
    _make_db(db_path)
    _insert_trade(db_path)

    order_status = {
        "legs": [
            {"type": "stop", "status": "canceled", "stop_price": 180.0},
            {"type": "limit", "status": "new", "limit_price": 200.0},
        ]
    }

    with patch("src.shadow_trading.alpaca_adapter.get_order_status", return_value=order_status), patch(
        "src.shadow_trading.bracket_monitor._alert"
    ) as mock_alert:
        result = check_bracket_health(db_path=db_path)

    assert result["checked"] == 1
    assert result["protected"] == 0
    assert result["broken"][0]["ticker"] == "AAPL"
    mock_alert.assert_called_once()
    assert "stop leg canceled" in mock_alert.call_args.args[0]


def test_premarket_check_sends_summary_alert(tmp_path):
    db_path = str(tmp_path / "bracket.db")
    _make_db(db_path)
    _insert_trade(db_path)

    order_status = {
        "legs": [
            {"type": "stop", "status": "new", "stop_price": 180.0},
            {"type": "limit", "status": "new", "limit_price": 200.0},
        ]
    }

    with patch("src.shadow_trading.alpaca_adapter.get_order_status", return_value=order_status), patch(
        "src.shadow_trading.bracket_monitor._alert"
    ) as mock_alert:
        result = check_bracket_health(db_path=db_path, context="premarket")

    assert result["checked"] == 1
    assert result["protected"] == 1
    assert mock_alert.call_args_list[-1].args[0] == "✅ Pre-market bracket check: 1/1 positions protected"
