"""D2 tests — reconcile 3rd branch for partial-fill qty mismatch.

Context: `docs/sprints/fix_paper_exit_qty_asymmetry_evaluation.md` §D2.

Before this sprint, `src/shadow_trading/reconcile.py:655` had only two
branches for stuck exit_failed/exit_pending trades:
  - alpaca_qty <= 0  → needs_manual_review / exit_overshoot_detected
  - alpaca_qty > 0   → revert to 'open'  (re-triggered CVS retry loop)

Missing the 0 < alpaca_qty < planned_shares case. CVS trade 00330e8d on
2026-04-21 was planned=130 but Alpaca had 4 after a partial-fill exit.
Reconcile reverted to open; executor re-issued sell 130; Alpaca rejected
"insufficient qty available"; loop ran 17+ times before manual quarantine.

Option 2c (approved at gated checkpoint): mark status='needs_manual_review'
with exit_reason='qty_mismatch_partial_fill'. Operator resolves the
residual out-of-band.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from src.journal.store import initialize_database, insert_shadow_trade


def _seed_stuck_trade(
    db_path: str,
    *,
    ticker: str,
    trade_id: str,
    planned_shares: float,
    status: str = "exit_failed",
    exit_reason: str = "timeout",
) -> None:
    insert_shadow_trade(
        {
            "trade_id": trade_id,
            "ticker": ticker,
            "direction": "long",
            "status": status,
            "source": "paper",
            "desk": "swing",
            "order_type": "bracket",
            "planned_shares": planned_shares,
            "entry_price": 78.29,
            "actual_entry_price": 78.29,
            "stop_price": 74.51,
            "target_1": 81.12,
            "target_2": 0.0,
            "exit_reason": exit_reason,
            "created_at": "2026-04-13T09:44:20-04:00",
            "updated_at": "2026-04-21T09:48:41-04:00",
            "alpaca_order_id": "f0a58eae-eed9-429a-a219-ba890e6a1370",
        },
        db_path,
    )


@pytest.fixture
def tmp_db(tmp_path):
    db = str(tmp_path / "reconcile_partial.db")
    initialize_database(db)
    return db


def _call_reconcile(db_path: str, alpaca_positions: list[dict]):
    """Drive reconcile_paper_trades with mocked broker state."""
    from src.shadow_trading.reconcile import reconcile_paper_trades

    with patch(
        "src.shadow_trading.reconcile.get_all_positions",
        return_value=alpaca_positions,
    ), patch(
        "src.shadow_trading.reconcile.cancel_orders_for_ticker",
        return_value=0,
    ), patch(
        # Orphan-backfill side effect — unrelated to this test; no-op it.
        "src.journal.store.insert_shadow_trade",
        side_effect=lambda trade, db=None: trade.get("trade_id", "orphan-ignored"),
    ):
        return reconcile_paper_trades(
            desk="swing", dry_run=False, db_path=db_path,
        )


def _read_row(db_path: str, trade_id: str) -> dict | None:
    import sqlite3

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT status, exit_reason, planned_shares FROM shadow_trades WHERE trade_id = ?",
            (trade_id,),
        ).fetchone()
    return dict(row) if row else None


def test_reconcile_handles_0_lt_alpaca_qty_lt_planned(tmp_db):
    """D2 core: planned=130, broker=4 → needs_manual_review + qty_mismatch_partial_fill.

    This is the CVS `00330e8d` scenario from 2026-04-21 that ran 17+ loop
    iterations before the operator quarantined the row. Without the 3rd
    branch, reconcile reverts to 'open' (broker qty=4 > 0), and the next
    executor cycle re-dispatches a sell of the full planned qty (130) —
    Alpaca rejects, reconcile reverts again, ad infinitum.
    """
    _seed_stuck_trade(
        tmp_db,
        ticker="CVS",
        trade_id="cvs-partial-1",
        planned_shares=130.0,
    )

    _call_reconcile(
        tmp_db,
        alpaca_positions=[
            {"symbol": "CVS", "qty": "4", "avg_entry_price": "78.70"},
        ],
    )

    row = _read_row(tmp_db, "cvs-partial-1")
    assert row is not None
    assert row["status"] == "needs_manual_review", (
        f"Expected row to be flagged for manual review, got status={row['status']!r}. "
        "Without the D2 3rd branch, reverts to 'open' and re-triggers the exit loop."
    )
    assert row["exit_reason"] == "qty_mismatch_partial_fill", (
        f"Expected exit_reason='qty_mismatch_partial_fill', got {row['exit_reason']!r}. "
        "A distinct reason lets cleanup tooling separate these from overshoot zombies."
    )


def test_overshoot_guard_still_fires_at_negative_qty(tmp_db):
    """D2 regression: existing overshoot guard must not change behavior.

    2026-04-21 09:43 ET C trade — broker went to -65 after the phantom
    sell flipped long→short. Reconcile MUST still flag this as
    exit_overshoot_detected (not the new qty_mismatch reason).
    """
    _seed_stuck_trade(
        tmp_db,
        ticker="C",
        trade_id="c-overshoot-1",
        planned_shares=65.0,
    )

    _call_reconcile(
        tmp_db,
        alpaca_positions=[
            {"symbol": "C", "qty": "-65", "avg_entry_price": "134.71"},
        ],
    )

    row = _read_row(tmp_db, "c-overshoot-1")
    assert row is not None
    assert row["status"] == "needs_manual_review"
    assert row["exit_reason"] == "exit_overshoot_detected", (
        f"Overshoot guard must still fire unchanged, got {row['exit_reason']!r}."
    )


def test_happy_path_exit_unchanged(tmp_db):
    """D2 byte-identity: planned=50, broker=50 → revert to 'open' (no regression).

    Normal case: an exit_failed trade where Alpaca still has the full
    position (e.g. transient network error during exit submission). The
    existing behavior MUST be preserved — revert to status='open' so the
    next cycle can retry cleanly.
    """
    _seed_stuck_trade(
        tmp_db,
        ticker="AAPL",
        trade_id="aapl-happy-1",
        planned_shares=50.0,
    )

    _call_reconcile(
        tmp_db,
        alpaca_positions=[
            {"symbol": "AAPL", "qty": "50", "avg_entry_price": "180.0"},
        ],
    )

    row = _read_row(tmp_db, "aapl-happy-1")
    assert row is not None
    assert row["status"] == "open", (
        f"Happy path must revert to 'open', got {row['status']!r}. "
        "Regression: this was the pre-fix behavior for qty-matched broker state."
    )
    assert row["exit_reason"] is None or row["exit_reason"] == "", (
        f"exit_reason must be cleared on revert-to-open, got {row['exit_reason']!r}."
    )
