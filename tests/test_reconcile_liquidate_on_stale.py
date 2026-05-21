"""v0.36.45 — liquidate-on-stale: the reconciled_stale close path must SELL a
position the broker still holds before flipping the DB row to closed, otherwise
the shares persist and re-orphan next cycle (the orphan-cycle amplifier).

Critical safety invariant under test: ``should_close`` is True ONLY when the
broker held nothing (qty<=0) OR the liquidating sell is confirmed cleared.
A submitted-but-unconfirmed sell must NOT close the DB row (leave it open for
the next cycle) — closing a row whose shares are still held is exactly the bug.
"""

import sqlite3
from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

from src.journal.store import initialize_database, insert_shadow_trade
from src.shadow_trading.reconcile import (
    _broker_qty,
    _liquidate_if_held,
    reconcile_paper_trades,
)


@pytest.fixture
def db_path(tmp_path):
    path = str(tmp_path / "test.sqlite3")
    initialize_database(path)
    return path


def _pos(ticker, qty, price=100.0):
    return {"symbol": ticker, "qty": qty, "current_price": price,
            "avg_entry_price": price, "market_value": qty * price}


# ── _broker_qty ──────────────────────────────────────────────────────────────

def test_broker_qty_found():
    assert _broker_qty("BAC", [_pos("BAC", 66.0)]) == 66.0


def test_broker_qty_absent_is_zero():
    assert _broker_qty("BAC", [_pos("AAPL", 5.0)]) == 0.0
    assert _broker_qty("BAC", []) == 0.0
    assert _broker_qty("BAC", None) == 0.0


def test_broker_qty_unparseable_is_zero():
    assert _broker_qty("BAC", [{"symbol": "BAC", "qty": None}]) == 0.0


# ── qty<=0 → DB-only close (unchanged behavior) ───────────────────────────────

def test_no_position_returns_db_only_close():
    with patch("src.shadow_trading.alpaca_adapter_paper.place_paper_exit") as sell:
        res = _liquidate_if_held(
            "BAC", desk="swing", source="paper",
            alpaca_positions=[_pos("AAPL", 5.0)], now=None, _attempts=1, _sleep=0,
        )
    assert res.should_close is True
    assert res.exit_price is None
    assert res.action == "no_position"
    sell.assert_not_called()  # never sell when nothing is held


# ── qty>0 + sell confirmed cleared → sell broker qty, close with fill ──────────

def test_held_position_sells_broker_qty_and_confirms():
    sold_order = {"order_id": "o1", "filled_avg_price": 50.98}
    # get_all_positions: post-cancel re-read sees the position still held, then
    # the confirmation poll sees it cleared.
    with patch("src.shadow_trading.alpaca_adapter_paper.place_paper_exit",
               return_value=sold_order) as sell, \
         patch("src.shadow_trading.alpaca_adapter.cancel_orders_for_ticker", return_value=1), \
         patch("src.shadow_trading.alpaca_adapter.get_all_positions",
               side_effect=[[_pos("BAC", 66.0)], []]):
        res = _liquidate_if_held(
            "BAC", desk="swing", source="paper",
            alpaca_positions=[_pos("BAC", 66.0)], now=None, _attempts=2, _sleep=0,
        )
    assert res.should_close is True
    assert res.exit_price == 50.98
    assert res.action == "sold"
    sell.assert_called_once()
    # broker qty (66), not DB planned_shares
    args, kwargs = sell.call_args
    assert args[0] == "BAC" and args[1] == 66


def test_broker_qty_differs_uses_broker_qty_not_planned():
    """AVGO trap: DB planned 6 but broker holds 4 — must sell the fresh broker qty (4)."""
    with patch("src.shadow_trading.alpaca_adapter_paper.place_paper_exit",
               return_value={"order_id": "o", "filled_avg_price": 413.0}) as sell, \
         patch("src.shadow_trading.alpaca_adapter.cancel_orders_for_ticker", return_value=0), \
         patch("src.shadow_trading.alpaca_adapter.get_all_positions",
               side_effect=[[_pos("AVGO", 4.0)], []]):
        _liquidate_if_held(
            "AVGO", desk="swing", source="paper",
            alpaca_positions=[_pos("AVGO", 4.0)], now=None, _attempts=1, _sleep=0,
        )
    assert sell.call_args[0][1] == 4


def test_position_cleared_during_cancel_does_not_sell():
    """If the OCO leg fills during the cancel/settle, the post-cancel re-read sees
    qty<=0 → resolved as 'cleared' with NO sell submitted (no over-sell / no short)."""
    with patch("src.shadow_trading.alpaca_adapter_paper.place_paper_exit") as sell, \
         patch("src.shadow_trading.alpaca_adapter.cancel_orders_for_ticker", return_value=1), \
         patch("src.shadow_trading.alpaca_adapter.get_all_positions", return_value=[]):
        res = _liquidate_if_held(
            "BAC", desk="swing", source="paper",
            alpaca_positions=[_pos("BAC", 66.0)], now=None, _attempts=1, _sleep=0,
        )
    assert res.should_close is True
    assert res.action == "cleared"
    sell.assert_not_called()


def test_post_cancel_reread_failure_blocks_sell():
    """If the post-cancel qty re-read fails, do NOT sell a stale qty — leave for next cycle."""
    with patch("src.shadow_trading.alpaca_adapter_paper.place_paper_exit") as sell, \
         patch("src.shadow_trading.alpaca_adapter.cancel_orders_for_ticker", return_value=0), \
         patch("src.shadow_trading.alpaca_adapter.get_all_positions",
               side_effect=RuntimeError("alpaca timeout")):
        res = _liquidate_if_held(
            "BAC", desk="swing", source="paper",
            alpaca_positions=[_pos("BAC", 66.0)], now=None, _attempts=1, _sleep=0,
        )
    assert res.should_close is False
    assert res.action == "sell_unconfirmed"
    sell.assert_not_called()


# ── safety: sell submitted but position NOT cleared → block the close ─────────

def test_sell_unconfirmed_position_still_held_blocks_close():
    with patch("src.shadow_trading.alpaca_adapter_paper.place_paper_exit",
               return_value={"order_id": "o", "filled_avg_price": None}), \
         patch("src.shadow_trading.alpaca_adapter.cancel_orders_for_ticker", return_value=0), \
         patch("src.shadow_trading.alpaca_adapter.get_all_positions",
               return_value=[_pos("BAC", 66.0)]):  # still held on every re-poll
        res = _liquidate_if_held(
            "BAC", desk="swing", source="paper",
            alpaca_positions=[_pos("BAC", 66.0)], now=None, _attempts=2, _sleep=0,
        )
    assert res.should_close is False
    assert res.action == "sell_unconfirmed"


def test_sell_submit_exception_blocks_close():
    # post-cancel re-read sees the position still held, so we reach the sell, which raises.
    with patch("src.shadow_trading.alpaca_adapter_paper.place_paper_exit",
               side_effect=RuntimeError("alpaca 500")), \
         patch("src.shadow_trading.alpaca_adapter.cancel_orders_for_ticker", return_value=0), \
         patch("src.shadow_trading.alpaca_adapter.get_all_positions",
               return_value=[_pos("BAC", 66.0)]):
        res = _liquidate_if_held(
            "BAC", desk="swing", source="paper",
            alpaca_positions=[_pos("BAC", 66.0)], now=None, _attempts=1, _sleep=0,
        )
    assert res.should_close is False
    assert res.action == "sell_unconfirmed"


# ── live path uses close_position (place_live_exit), not paper sell ───────────

def test_live_uses_place_live_exit_not_paper():
    with patch("src.shadow_trading.alpaca_adapter_live.place_live_exit",
               return_value={"order_id": "L", "filled_avg_price": 124.26}) as live_sell, \
         patch("src.shadow_trading.alpaca_adapter_paper.place_paper_exit") as paper_sell, \
         patch("src.shadow_trading.alpaca_adapter.cancel_orders_for_ticker", return_value=0), \
         patch("src.shadow_trading.alpaca_adapter.get_live_positions",
               side_effect=[[_pos("DUK", 34.0)], []]):
        res = _liquidate_if_held(
            "DUK", desk="swing", source="live",
            alpaca_positions=[_pos("DUK", 34.0)], now=None, _attempts=1, _sleep=0,
        )
    assert res.should_close is True
    assert res.action == "sold"
    live_sell.assert_called_once()
    paper_sell.assert_not_called()


# ── integration: reconcile_paper_trades liquidates a close-didn't-clear position ─

def test_paper_reconcile_liquidates_close_didnt_clear(db_path):
    """A DB-closed position the broker still holds (close-didn't-clear) is SOLD by
    the reconciler — not re-backfilled (which would restart the orphan loop)."""
    now_str = datetime.now(ZoneInfo("America/New_York")).isoformat()
    insert_shadow_trade(
        {"ticker": "LIQT", "status": "open", "source": "paper", "direction": "long",
         "entry_price": 100.0, "planned_shares": 10, "created_at": now_str, "updated_at": now_str},
        db_path,
    )
    # Precondition: row was closed recently, but the broker still holds the shares.
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "UPDATE shadow_trades SET status='closed', actual_exit_time=? WHERE ticker='LIQT'",
            (now_str,),
        )

    held = [{"symbol": "LIQT", "qty": 10.0, "avg_entry_price": 100.0,
             "current_price": 99.0, "market_value": 990.0}]
    # reconcile.get_all_positions → main fetch/detection (LIQT held). The helper's
    # alpaca_adapter.get_all_positions: post-cancel re-read sees it held, confirm cleared.
    with patch("src.shadow_trading.reconcile.get_all_positions", return_value=held), \
         patch("src.shadow_trading.alpaca_adapter_paper.place_paper_exit",
               return_value={"order_id": "o", "filled_avg_price": 99.0}) as sell, \
         patch("src.shadow_trading.alpaca_adapter.cancel_orders_for_ticker", return_value=0), \
         patch("src.shadow_trading.alpaca_adapter.get_all_positions",
               side_effect=[list(held), []]):
        result = reconcile_paper_trades(db_path=db_path, dry_run=False)

    assert result["liquidated"] == ["LIQT"]
    assert result["backfilled"] == []          # NOT re-orphaned
    sell.assert_called_once()
    assert sell.call_args[0][1] == 10          # sold the broker qty


def test_paper_reconcile_dry_run_does_not_liquidate(db_path):
    """dry_run must never submit a real sell."""
    now_str = datetime.now(ZoneInfo("America/New_York")).isoformat()
    insert_shadow_trade(
        {"ticker": "LIQT", "status": "open", "source": "paper", "direction": "long",
         "entry_price": 100.0, "planned_shares": 10, "created_at": now_str, "updated_at": now_str},
        db_path,
    )
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "UPDATE shadow_trades SET status='closed', actual_exit_time=? WHERE ticker='LIQT'",
            (now_str,),
        )
    held = [{"symbol": "LIQT", "qty": 10.0, "avg_entry_price": 100.0,
             "current_price": 99.0, "market_value": 990.0}]
    with patch("src.shadow_trading.reconcile.get_all_positions", return_value=held), \
         patch("src.shadow_trading.alpaca_adapter_paper.place_paper_exit") as sell:
        result = reconcile_paper_trades(db_path=db_path, dry_run=True)

    sell.assert_not_called()
    assert result.get("liquidated", []) == []
