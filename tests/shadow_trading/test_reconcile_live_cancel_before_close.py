"""Regression-locks: live stale-close MUST cancel broker orders before
closing the local record.

Sprint 0 Wave 1c — RECONCILE-NAMEERR (LIVE CAPITAL SAFETY).

Pre-fix bug
-----------
``reconcile_live_trades`` had a dead list-comprehension referencing
``stale_entry`` — a variable that does NOT exist in the live loop scope
(the live loop variable is ``ticker``; ``stale_entry`` is the *paper*
loop variable). The reference raised ``NameError`` which the surrounding
``except Exception`` swallowed silently.

Net effect: the cancel-before-close broker call NEVER executed on live
stale closes. Each stale close marked the local record ``closed`` while
GTC bracket orders remained live on the broker side. On the next entry
attempt for the same ticker, those leaked orders could double-fire.

Test strategy
-------------
Seed a real SQLite shadow_trades row with status='open',
alpaca_order_id='ALP_ENTRY', exit_order_id='ALP_EXIT'. Mock the live
broker to return ZERO positions (so the trade is detected as stale)
and capture every ``cancel_order(...)`` call. Assert:

1. ``cancel_order`` is called for BOTH ``ALP_ENTRY`` and ``ALP_EXIT``.
2. Both calls happen BEFORE the trade row is updated to status='closed'.
3. Pre-fix this test would see ZERO ``cancel_order`` calls because the
   NameError silently aborted the cancel block.
"""
from __future__ import annotations

import sqlite3
from unittest.mock import MagicMock, patch

import pytest

from src.journal.store import insert_shadow_trade
from src.schema.sqlite import create_all_tables


@pytest.fixture
def tmp_live_db(tmp_path):
    """Seed a tmp SQLite with one stale live shadow_trade row.

    The row has explicit alpaca_order_id + exit_order_id so the cancel
    block has something to cancel. created_at is set in the past to
    make the trade obviously stale (no 1-hour guard on live, but
    explicit-old is still cleanest).
    """
    db = str(tmp_path / "test_live_reconcile.db")
    create_all_tables(db)
    insert_shadow_trade(
        {
            "trade_id": "TRADE_LIVE_STALE_1",
            "ticker": "AAPL",
            "direction": "long",
            "status": "open",
            "source": "live",
            "desk": "swing",
            "entry_price": 200.0,
            "actual_entry_price": 200.0,
            "stop_price": 190.0,
            "target_1": 210.0,
            "target_2": 220.0,
            "planned_shares": 10.0,
            "planned_allocation": 2000.0,
            "alpaca_order_id": "ALP_ENTRY",
            "exit_order_id": "ALP_EXIT",
            "ib_child_order_ids": None,
            "created_at": "2026-04-01T09:30:00",
            "updated_at": "2026-04-01T09:30:00",
        },
        db,
    )
    return db


def test_live_stale_close_cancels_broker_orders_before_close(tmp_live_db):
    """The dead-code NameError fix exercises the cancel-before-close path.

    Asserts the live broker's ``cancel_order`` is invoked for both the
    entry and exit order IDs, and that the trade row is still in the
    ``open`` (not closed) state at the moment of each cancel call.
    """
    from src.shadow_trading.reconcile import reconcile_live_trades

    # Capture: list of (cancel_id, trade_status_at_call_time)
    cancel_log: list[tuple[str, str]] = []

    def _cancel_spy(order_id):
        # Snapshot the trade row's status at the time cancel is called.
        # If the fix is working, status MUST still be 'open' here —
        # close happens AFTER the cancel block.
        with sqlite3.connect(tmp_live_db) as _conn:
            _conn.row_factory = sqlite3.Row
            row = _conn.execute(
                "SELECT status FROM shadow_trades WHERE trade_id = ?",
                ("TRADE_LIVE_STALE_1",),
            ).fetchone()
        cancel_log.append((str(order_id), row["status"] if row else "MISSING"))
        return {"id": str(order_id), "status": "cancelled"}

    mock_broker = MagicMock()
    mock_broker.get_all_positions.return_value = []  # → trade is stale
    mock_broker.cancel_order.side_effect = _cancel_spy

    with (
        patch("src.trading.broker_factory.get_live_broker", return_value=mock_broker),
        patch(
            "src.shadow_trading.reconcile.get_live_positions", return_value=[]
        ),
        # Avoid network in PnL estimation
        patch(
            "src.shadow_trading.reconcile._estimate_exit_pnl",
            return_value=(0.0, 0.0, 0.0),
        ),
    ):
        result = reconcile_live_trades(
            desk="swing", dry_run=False, db_path=tmp_live_db,
        )

    # 1. Stale was detected and processed
    assert "AAPL" in result["stale"], (
        "AAPL should be detected as stale (broker has no position)"
    )
    assert "AAPL" in result["marked_closed"], (
        "AAPL should be marked closed by reconcile"
    )

    # 2. cancel_order was called — pre-fix this would be 0 because the
    #    NameError was silently swallowed.
    cancelled_ids = [cid for cid, _status in cancel_log]
    assert mock_broker.cancel_order.call_count >= 2, (
        f"Expected cancel_order called at least twice (entry + exit IDs); "
        f"got {mock_broker.cancel_order.call_count}. "
        f"Pre-fix RECONCILE-NAMEERR bug would yield 0 calls."
    )
    assert "ALP_ENTRY" in cancelled_ids, (
        f"alpaca_order_id ALP_ENTRY missing from cancel_order calls: "
        f"{cancelled_ids}"
    )
    assert "ALP_EXIT" in cancelled_ids, (
        f"exit_order_id ALP_EXIT missing from cancel_order calls: "
        f"{cancelled_ids}"
    )

    # 3. CRITICAL ordering assertion: every cancel happened while the
    #    trade was still 'open' — i.e., BEFORE close_shadow_trade flipped
    #    it to 'closed'. Pre-fix (with the NameError swallowed), the
    #    cancel block was unreachable and close happened with leaked
    #    broker orders.
    for cid, status_at_call in cancel_log:
        assert status_at_call == "open", (
            f"cancel_order({cid}) was called when trade status was "
            f"{status_at_call!r} — must be 'open' (cancel BEFORE close). "
            "Pre-fix bug would skip cancels entirely; a regression that "
            "moves cancel AFTER close would also fail this assertion."
        )

    # 4. After reconcile, trade is closed in the DB (post-condition).
    with sqlite3.connect(tmp_live_db) as _conn:
        _conn.row_factory = sqlite3.Row
        final = _conn.execute(
            "SELECT status FROM shadow_trades WHERE trade_id = ?",
            ("TRADE_LIVE_STALE_1",),
        ).fetchone()
    assert final["status"] == "closed", (
        "trade should be marked closed after reconcile"
    )


def test_static_no_stale_entry_in_live_path_code():
    """Guardrail: ``stale_entry`` must NOT appear as code in ``reconcile_live_trades``.

    The variable name only exists as the loop variable in
    ``reconcile_paper_trades``. Any code-level use of it inside
    ``reconcile_live_trades`` is the dead-code NameError pattern.

    This static check prevents future refactors from re-introducing the
    same anti-pattern (e.g., copy-pasting paper logic into live without
    renaming the loop variable). It uses ``ast`` to walk only the
    ``reconcile_live_trades`` function body and check identifier
    references (``ast.Name`` nodes) — that way comments mentioning
    ``stale_entry`` for documentation purposes don't false-positive.
    """
    import ast
    import pathlib

    src = pathlib.Path("src/shadow_trading/reconcile.py").read_text(
        encoding="utf-8",
    )
    tree = ast.parse(src)
    live_func = next(
        (
            node for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef)
            and node.name == "reconcile_live_trades"
        ),
        None,
    )
    assert live_func is not None, "reconcile_live_trades not found in module"

    bad_refs = [
        n for n in ast.walk(live_func)
        if isinstance(n, ast.Name) and n.id == "stale_entry"
    ]
    assert not bad_refs, (
        f"Found {len(bad_refs)} `stale_entry` reference(s) in "
        "reconcile_live_trades — that variable only exists in "
        "reconcile_paper_trades. RECONCILE-NAMEERR (Sprint 0 Wave 1c) "
        "regression: dead-code list-comp silently raised NameError, "
        "disabling cancel-before-close on every live stale close. "
        "Use `ticker` / `trade_id` (the live loop vars)."
    )


def test_static_live_cancel_path_has_cancel_order_call():
    """Guardrail: the live stale-close block must contain a
    ``broker.cancel_order(...)`` call.

    Prevents a future refactor from accidentally dropping the cancel
    logic entirely while removing dead code.
    """
    import pathlib

    src = pathlib.Path("src/shadow_trading/reconcile.py").read_text(
        encoding="utf-8",
    )
    # Slice between the live stale-loop header and the close_shadow_trade
    # call inside that loop.
    live_loop = src.find("for ticker in stale:")
    assert live_loop > 0, "expected `for ticker in stale:` in live path"
    close_call = src.find("close_shadow_trade(", live_loop)
    assert close_call > live_loop, "expected close_shadow_trade after stale loop"
    pre_close = src[live_loop:close_call]
    assert "cancel_order" in pre_close, (
        "live stale-close path must call broker.cancel_order(...) BEFORE "
        "close_shadow_trade. Cancel-before-close is the LIVE CAPITAL "
        "SAFETY invariant — without it, GTC bracket orders leak after "
        "the local record closes."
    )
