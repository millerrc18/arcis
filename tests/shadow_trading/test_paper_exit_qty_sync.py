"""D3 tests — paper exit qty sync against broker state.

Context: `docs/sprints/fix_paper_exit_qty_asymmetry_evaluation.md` §D3.

Before this sprint, `src/shadow_trading/executor.py:1461` dispatched
_submit_exit_order(trade, shares=planned_shares) without verifying the
broker still had that many shares. Two failure modes:

  - planned > alpaca_qty > 0:  Alpaca rejects "insufficient qty" (CVS loop).
  - planned > 0, alpaca_qty == 0: Alpaca accepts as sell_to_open — phantom
    short position (C 2026-04-21, 13 zombies 4/15–4/20).

Option 3.1 (approved): use `min(planned, alpaca_qty)` from the
`_alpaca_tickers` cache already fetched at executor.py:1174. When
alpaca_qty <= 0, skip the submit entirely and mark the trade for
reconcile to handle (no sell dispatched).
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.journal.store import initialize_database, insert_shadow_trade


@pytest.fixture
def tmp_db(tmp_path):
    db = str(tmp_path / "paper_exit_qty.db")
    initialize_database(db)
    return db


def _seed_open_bracket(
    db_path: str,
    *,
    ticker: str,
    trade_id: str,
    planned_shares: float,
    stop_price: float = 74.51,
    target_1: float = 81.12,
    created_at: str = "2026-04-13T09:44:20-04:00",
    timeout_days: int = 8,
) -> None:
    # Sprint 0 / Wave 2b — pin per-trade timeout_days to match this suite's
    # intent (timeout fires at day 8). Otherwise insert_shadow_trade defaults
    # the field to 15, which (post Bug-3 fix) wins over the config global
    # passed in load_config and the timeout exit no longer fires at day 13.
    insert_shadow_trade(
        {
            "trade_id": trade_id,
            "ticker": ticker,
            "direction": "long",
            "status": "open",
            "source": "paper",
            "desk": "swing",
            "order_type": "bracket",
            "planned_shares": planned_shares,
            "entry_price": 78.29,
            "actual_entry_price": 78.29,
            "stop_price": stop_price,
            "target_1": target_1,
            "target_2": 0.0,
            "strategy_type": "pullback",
            "alpaca_order_id": "f0a58eae-eed9-429a-a219-ba890e6a1370",
            "created_at": created_at,
            "updated_at": created_at,
            "timeout_days": timeout_days,
        },
        db_path,
    )


def _row_status(db_path: str, trade_id: str) -> dict | None:
    import sqlite3

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT status, exit_reason, exit_order_id FROM shadow_trades WHERE trade_id = ?",
            (trade_id,),
        ).fetchone()
    return dict(row) if row else None


def _run_exit_check(
    db_path: str,
    *,
    alpaca_positions: list[dict],
    current_price: float,
    order_status: dict | None = None,
) -> tuple[MagicMock, MagicMock]:
    """Drive check_and_manage_open_trades with mocked broker state and capture submit calls."""
    from src.shadow_trading import executor as exec_mod

    mock_submit = MagicMock(
        return_value={
            "order_id": "mock-exit-order-id",
            "status": "OrderStatus.FILLED",
            "filled_avg_price": current_price,
            "filled_qty": 1,
        }
    )
    mock_order_status = MagicMock(
        return_value=order_status
        or {
            "status": "FILLED",
            "filled_avg_price": 78.29,
            "legs": [],
        }
    )

    with patch.object(
        exec_mod, "_get_current_price_safe", return_value=current_price
    ), patch(
        "src.shadow_trading.alpaca_adapter.get_all_positions",
        return_value=alpaca_positions,
    ), patch(
        "src.shadow_trading.alpaca_adapter.place_paper_exit",
        mock_submit,
    ), patch(
        "src.shadow_trading.alpaca_adapter.get_order_status",
        mock_order_status,
    ), patch(
        "src.shadow_trading.alpaca_adapter.cancel_paper_order",
        return_value={"cancelled": True},
    ), patch.object(
        exec_mod, "load_config",
        return_value={
            "shadow_trading": {"timeout_days": 8, "max_positions": 10},
            "strategies": {"mean_reversion": {}},
            "trading": {"ib_enabled": False},
        },
    ):
        exec_mod.check_and_manage_open_trades(
            db_path=db_path, source_filter="paper",
        )
    return mock_submit, mock_order_status


def test_paper_exit_uses_broker_state_when_db_stale(tmp_db):
    """D3 core: planned=130, broker=4 → submit qty=4 (not 130).

    CVS-style residual. Before D3, executor submitted 130 → Alpaca
    rejected "insufficient qty available: 4". With D3, the min-sync clips
    to the broker's 4 and the sell succeeds.
    """
    _seed_open_bracket(
        tmp_db, ticker="CVS", trade_id="cvs-sync-1", planned_shares=130.0,
    )

    mock_submit, _ = _run_exit_check(
        tmp_db,
        # Timeout triggers: day 8 == timeout_days. current_price shouldn't
        # matter for timeout path.
        alpaca_positions=[{"symbol": "CVS", "qty": "4", "avg_entry_price": "78.70"}],
        current_price=77.48,
    )

    # Exit must have fired once with qty=4, not 130.
    assert mock_submit.called, "Exit submit was never called — expected timeout-driven exit to fire"
    submitted_qtys = [call.args[1] for call in mock_submit.call_args_list]
    assert 4 in submitted_qtys, (
        f"Expected submit with qty=4 (synced to broker), got qtys={submitted_qtys}. "
        "Without D3, submit would use planned_shares=130 and Alpaca rejects."
    )
    assert 130 not in submitted_qtys, (
        "Executor must NOT submit with stale planned_shares when broker has fewer."
    )


def test_paper_exit_zero_qty_no_submit(tmp_db):
    """D3 phantom-exit prevention: planned=65, broker=0 → no submit at all.

    The C 2026-04-21 09:43 scenario: target leg filled server-side, closing
    the position at Alpaca. DB row not yet updated. Executor sees trade as
    status='open'; fallback target_1_hit triggers. Without D3, a sell of
    65 shares fires against qty=0 → Alpaca opens sell_to_open → -65 short.
    With D3, broker_qty <= 0 aborts the submit.
    """
    _seed_open_bracket(
        tmp_db, ticker="C", trade_id="c-phantom-1",
        planned_shares=65.0, stop_price=120.76, target_1=133.96,
        created_at="2026-04-14T11:17:03-04:00",
    )

    mock_submit, _ = _run_exit_check(
        tmp_db,
        # Broker has no position; market price above target_1 would trigger
        # fallback exit pre-D3.
        alpaca_positions=[],
        current_price=134.71,
    )

    # Critical: no submit at all.
    assert not mock_submit.called, (
        "D3 violation: executor submitted a sell against a zero-qty broker position. "
        f"Submit call_args_list: {mock_submit.call_args_list}. "
        "This is the phantom-exit mechanism that created C's -65 short on 2026-04-21."
    )


def test_paper_exit_race_with_reconcile(tmp_db):
    """D3 race-safety: mid-cycle reconcile doesn't produce wrong qty.

    Simulated sequence: the executor has fetched broker positions at the
    top of check_and_manage_open_trades (line ~1174). Between that fetch
    and the actual _submit_exit_order call, suppose reconcile ran and
    updated the DB. The executor must use its *already-fetched* broker
    snapshot (the D3 cache), not re-read state. This keeps the exit
    consistent with what it observed.
    """
    _seed_open_bracket(
        tmp_db, ticker="CVS", trade_id="cvs-race-1", planned_shares=100.0,
    )

    mock_submit, _ = _run_exit_check(
        tmp_db,
        # Cache-time snapshot: broker had 50 CVS.
        alpaca_positions=[{"symbol": "CVS", "qty": "50", "avg_entry_price": "78.00"}],
        current_price=77.48,
    )

    # Exit must reflect the cache-time snapshot (50), not planned (100).
    # And must not produce a divergent or zero qty.
    submitted_qtys = [call.args[1] for call in mock_submit.call_args_list]
    if mock_submit.called:
        assert all(q == 50 for q in submitted_qtys), (
            f"Race-safety: all submitted qtys must equal cached broker qty=50, "
            f"got {submitted_qtys}."
        )
