"""Tests for bracket health monitoring."""

import sqlite3
from unittest.mock import patch

from src.schema.sqlite import generate_create_sql
from src.schema.registry import TABLES
from src.shadow_trading.bracket_monitor import (
    _classify_legs,
    check_bracket_health,
    ensure_bracket_health_table,
)
from tests.conftest import init_test_db


def _make_db(db_path: str) -> None:
    init_test_db(db_path, ["shadow_trades", "bracket_health"])


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
    """Table creation is handled by the schema registry; verify the registry has it."""
    db_path = str(tmp_path / "bracket.db")

    # ensure_bracket_health_table is now a no-op; table is created via registry
    with sqlite3.connect(db_path) as conn:
        conn.executescript(generate_create_sql(TABLES["bracket_health"]))

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


# --- OCO topology tests ---


def test_oco_with_held_stop_classified_healthy(tmp_path):
    """OCO parent=LIMIT(NEW), legs=[STOP(HELD)] must be classified as intact.

    Production shape: Alpaca OCO order where the parent IS the take-profit
    limit order and the single leg is the stop-loss.  bracket_monitor was
    false-alerting 'alerted_target_leg' for all 4 live paper positions
    (BK, C, COP, TGT) since 2026-05-05T13:10 ET.
    """
    db_path = str(tmp_path / "bracket.db")
    _make_db(db_path)
    _insert_trade(db_path)

    # OCO topology: parent is the LIMIT take-profit; single leg is the STOP.
    order_status = {
        "order_class": "oco",
        "type": "limit",
        "status": "new",
        "limit_price": 200.0,
        "stop_price": None,
        "legs": [
            {"type": "stop", "status": "held", "stop_price": 175.0, "limit_price": None},
        ],
    }

    with patch("src.shadow_trading.alpaca_adapter.get_order_status", return_value=order_status), patch(
        "src.shadow_trading.bracket_monitor._alert"
    ) as mock_alert:
        result = check_bracket_health(db_path=db_path)

    assert result["checked"] == 1
    assert result["protected"] == 1
    assert result["broken"] == []
    mock_alert.assert_not_called()

    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT bracket_intact, stop_leg_status, target_leg_status FROM bracket_health"
        ).fetchone()
    assert row[0] == 1, "bracket_intact must be 1"
    assert row[1] == "held", f"stop_leg_status must be 'held', got {row[1]!r}"
    assert row[2] == "new", f"target_leg_status (from parent) must be 'new', got {row[2]!r}"


def test_oco_with_canceled_stop_classified_broken(tmp_path):
    """OCO with STOP(CANCELED) must classify as broken and fire an alert."""
    db_path = str(tmp_path / "bracket.db")
    _make_db(db_path)
    _insert_trade(db_path)

    order_status = {
        "order_class": "oco",
        "type": "limit",
        "status": "new",
        "limit_price": 200.0,
        "stop_price": None,
        "legs": [
            {"type": "stop", "status": "canceled", "stop_price": 175.0, "limit_price": None},
        ],
    }

    with patch("src.shadow_trading.alpaca_adapter.get_order_status", return_value=order_status), patch(
        "src.shadow_trading.bracket_monitor._alert"
    ) as mock_alert:
        result = check_bracket_health(db_path=db_path)

    assert result["checked"] == 1
    assert result["protected"] == 0
    assert result["broken"][0]["ticker"] == "AAPL"
    mock_alert.assert_called()
    assert any("stop" in str(call) for call in mock_alert.call_args_list), (
        "Expected an alert mentioning the stop leg"
    )

    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT bracket_intact, stop_leg_status, target_leg_status FROM bracket_health"
        ).fetchone()
    assert row[0] == 0, "bracket_intact must be 0 when stop is canceled"


def test_bracket_with_both_legs_active_classified_healthy(tmp_path):
    """Regression-lock: BRACKET topology with STOP(NEW) + LIMIT(NEW) must still be intact.

    This test locks the existing BRACKET path so refactoring for OCO support
    cannot silently break the original classification logic.
    """
    db_path = str(tmp_path / "bracket.db")
    _make_db(db_path)
    _insert_trade(db_path)

    order_status = {
        "order_class": "bracket",
        "type": "market",
        "status": "filled",
        "limit_price": None,
        "stop_price": None,
        "legs": [
            {"type": "stop", "status": "new", "stop_price": 175.0, "limit_price": None},
            {"type": "limit", "status": "new", "limit_price": 200.0, "stop_price": None},
        ],
    }

    with patch("src.shadow_trading.alpaca_adapter.get_order_status", return_value=order_status), patch(
        "src.shadow_trading.bracket_monitor._alert"
    ) as mock_alert:
        result = check_bracket_health(db_path=db_path)

    assert result["checked"] == 1
    assert result["protected"] == 1
    assert result["broken"] == []
    mock_alert.assert_not_called()

    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT bracket_intact, stop_leg_status, target_leg_status FROM bracket_health"
        ).fetchone()
    assert row == (1, "new", "new")


def test_classifier_returns_unified_shape_for_both_classes(tmp_path):
    """The bracket_health DB record has identical columns for BRACKET and OCO inputs.

    Verifies that downstream consumers of bracket_health never need to branch
    on order_class — the recorded columns (stop_leg_status, target_leg_status,
    bracket_intact) are always populated for both topologies.
    """
    db_path = str(tmp_path / "bracket.db")
    _make_db(db_path)
    _insert_trade(db_path, trade_id="bracket-trade", ticker="MSFT", order_id="order-b")
    _insert_trade(db_path, trade_id="oco-trade", ticker="AAPL", order_id="order-o")

    bracket_order = {
        "order_class": "bracket",
        "type": "market",
        "status": "filled",
        "limit_price": None,
        "stop_price": None,
        "legs": [
            {"type": "stop", "status": "new", "stop_price": 175.0, "limit_price": None},
            {"type": "limit", "status": "new", "limit_price": 200.0, "stop_price": None},
        ],
    }
    oco_order = {
        "order_class": "oco",
        "type": "limit",
        "status": "new",
        "limit_price": 200.0,
        "stop_price": None,
        "legs": [
            {"type": "stop", "status": "held", "stop_price": 175.0, "limit_price": None},
        ],
    }

    def _get_order_status_side_effect(order_id):
        return bracket_order if order_id == "order-b" else oco_order

    with patch(
        "src.shadow_trading.alpaca_adapter.get_order_status",
        side_effect=_get_order_status_side_effect,
    ), patch("src.shadow_trading.bracket_monitor._alert"):
        check_bracket_health(db_path=db_path)

    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            "SELECT trade_id, stop_leg_status, target_leg_status, bracket_intact "
            "FROM bracket_health ORDER BY trade_id"
        ).fetchall()

    assert len(rows) == 2
    by_trade = {r[0]: r for r in rows}

    bracket_row = by_trade["bracket-trade"]
    oco_row = by_trade["oco-trade"]

    # Both must have all three columns populated (not NULL).
    for trade_id, row in by_trade.items():
        assert row[1] is not None, f"{trade_id}: stop_leg_status is NULL"
        assert row[2] is not None, f"{trade_id}: target_leg_status is NULL"
        assert row[3] is not None, f"{trade_id}: bracket_intact is NULL"

    # Both must be intact.
    assert bracket_row[3] == 1, "BRACKET topology must be intact"
    assert oco_row[3] == 1, "OCO topology must be intact"
