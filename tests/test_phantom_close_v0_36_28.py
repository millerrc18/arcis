"""Regression-locks for v0.36.28 — phantom-close bug in bracket-exit detection.

Background
==========

Pre-v0.36.28, three code paths in `src/shadow_trading/executor.py` interpreted
the bracket-PARENT order's `status='filled'` as an exit signal. For Alpaca OCO
bracket orders the "parent" IS the BUY entry order — `parent_status='filled'`
is the NORMAL state of every open bracket position, not an exit signal.

Each affected path eventually wrote the BUY's `filled_avg_price` as the
shadow_trade's `actual_exit_price` via the shared helper
`_close_from_broker_fill`:

1. `_retry_exit` pre-check (line 1430-1434): `pending_order_id = exit_order_id
   or alpaca_order_id`. When `exit_order_id` is None, fell back to the BUY
   parent — checked its `status`, then called `_close_from_broker_fill`.

2. Pre-exit cancel-race path (line 2007-2009): same fallback chain via
   `_pending_oid`.

3. Bracket-exit detection block (line 1865-1869): explicitly checked
   `parent_status in FILLED_ORDER_STATUSES` and set `bracket_exit=True` with
   `current_price = parent.filled_avg_price` — which gated out the timeout-
   exit SELL submission, leaving the position open on Alpaca while marking
   shadow_trade closed with phantom pnl.

Smoking gun (AMD trade_id `dcd090be`, found 2026-05-19): shadow_trades shows
`actual_entry_price=$439.80`, `actual_exit_price=$440.72` — exactly the 5-08
Alpaca BUY-fill price. No SELL of AMD between 5-08 entry and 5-18 14:03
stop-fill in Alpaca's order history. Confirmed via Alpaca REST API.

Affected scope: 7 confirmed phantom rows since 2026-04-13 (commit baa8466d).
Each one led to a duplicate orphan-backfilled trade with NULL recommendation_id
that the auditor then mis-attributed.

The fix
=======

**Architectural (defense-in-depth):** add a `side == "sell"` guard inside
`_close_from_broker_fill` at executor.py:1361. This helper writes the filled
order's `filled_avg_price` as the EXIT price — it must NEVER be called with
a BUY order. The guard refuses to close-from-fill when the order is a BUY
and emits a critical log entry so any caller that mis-routes is visible.
Covers all three call sites in one line.

**Direct removal:** delete the parent-status branch at executor.py:1865-1869.
The legs check immediately below at 1870-1883 already handles real bracket
exits (stop or target leg actually firing). Removing the parent-status branch
means `bracket_exit` only becomes True when a SELL leg fills.

This file pins both contracts.
"""
from __future__ import annotations

from unittest.mock import patch, MagicMock

import pytest


# ── _close_from_broker_fill side guard ───────────────────────────────────


def test_close_from_broker_fill_refuses_buy_orders():
    """A BUY order's filled price must NEVER be written as a shadow_trade
    exit price. The helper refuses and emits no close.
    """
    from src.shadow_trading.executor import _close_from_broker_fill

    trade = {
        "trade_id": "test-trade-123",
        "ticker": "AMD",
        "actual_entry_price": 439.80,
        "planned_shares": 2,
        "exit_reason": "timeout",
    }
    buy_fill = {
        "order_id": "buy-order-abc",
        "status": "filled",
        "side": "buy",          # ← the guard's target
        "filled_avg_price": 440.72,
        "filled_at": "2026-05-08T16:10:19Z",
    }

    with patch("src.shadow_trading.executor.close_shadow_trade") as mock_close:
        _close_from_broker_fill(trade, buy_fill, db_path=":memory:")

    assert mock_close.call_count == 0, (
        "_close_from_broker_fill must refuse to close from a BUY order — that "
        "BUY's filled_avg_price is the ENTRY price, not an exit. Writing it "
        "as exit_price creates the phantom-close pattern fixed in v0.36.28."
    )


def test_close_from_broker_fill_processes_sell_orders():
    """A SELL order's filled price correctly drives the exit close."""
    from src.shadow_trading.executor import _close_from_broker_fill

    trade = {
        "trade_id": "test-trade-456",
        "ticker": "AMD",
        "actual_entry_price": 439.80,
        "planned_shares": 2,
        "exit_reason": "stop_loss",
    }
    sell_fill = {
        "order_id": "sell-order-xyz",
        "status": "filled",
        "side": "sell",
        "filled_avg_price": 418.50,
        "filled_at": "2026-05-18T14:03:51Z",
    }

    with patch("src.shadow_trading.executor.close_shadow_trade") as mock_close:
        _close_from_broker_fill(trade, sell_fill, db_path=":memory:")

    assert mock_close.call_count == 1, (
        "_close_from_broker_fill must process SELL orders as normal."
    )
    kwargs = mock_close.call_args.kwargs
    assert kwargs.get("exit_price") == 418.50
    # P&L: (418.50 - 439.80) * 2 = -42.60
    assert kwargs.get("pnl_dollars") == pytest.approx(-42.60, abs=0.01)


def test_close_from_broker_fill_refuses_missing_side():
    """Defensive: if the filled_order has no `side` field, refuse rather than
    guess. Better to leave the trade open than to write a phantom exit."""
    from src.shadow_trading.executor import _close_from_broker_fill

    trade = {
        "trade_id": "test-trade-789",
        "ticker": "AMD",
        "actual_entry_price": 100.0,
        "planned_shares": 1,
        "exit_reason": "timeout",
    }
    fill_no_side = {
        "order_id": "order-abc",
        "status": "filled",
        # side intentionally missing
        "filled_avg_price": 101.0,
        "filled_at": "2026-05-18T12:00:00Z",
    }

    with patch("src.shadow_trading.executor.close_shadow_trade") as mock_close:
        _close_from_broker_fill(trade, fill_no_side, db_path=":memory:")

    assert mock_close.call_count == 0, (
        "Missing `side` field is ambiguous — refuse rather than guess. "
        "Fail-safe behavior."
    )


def test_close_from_broker_fill_processes_uppercase_sell():
    """Alpaca SDK enums may stringify as 'SELL' or 'OrderSide.SELL' — accept
    case-insensitive 'sell' match."""
    from src.shadow_trading.executor import _close_from_broker_fill

    trade = {
        "trade_id": "test-trade-case",
        "ticker": "AMD",
        "actual_entry_price": 100.0,
        "planned_shares": 1,
        "exit_reason": "stop_loss",
    }
    for side_variant in ("SELL", "Sell", "sell"):
        sell_fill = {
            "order_id": f"order-{side_variant}",
            "status": "filled",
            "side": side_variant,
            "filled_avg_price": 95.0,
            "filled_at": "2026-05-18T12:00:00Z",
        }
        with patch("src.shadow_trading.executor.close_shadow_trade") as mock_close:
            _close_from_broker_fill(trade, sell_fill, db_path=":memory:")
        assert mock_close.call_count == 1, (
            f"Expected SELL variant {side_variant!r} to be processed, but it was refused."
        )


# ── Source-code regression-locks ────────────────────────────────────────


def _read_executor_source() -> str:
    """Read the executor.py source for static structural checks."""
    import os
    path = os.path.join(
        os.path.dirname(__file__), "..", "src", "shadow_trading", "executor.py",
    )
    with open(path, encoding="utf-8") as f:
        return f.read()


def test_parent_status_branch_removed_from_bracket_check():
    """The buggy parent-status-filled branch must not reappear in the
    bracket-exit detection block.

    Pre-v0.36.28 code (now removed):

        if parent_status in FILLED_ORDER_STATUSES:
            exit_price = order_status.get("filled_avg_price")
            if exit_price:
                current_price = exit_price
                bracket_exit = True

    For an Alpaca OCO bracket, the parent is the BUY entry order — its
    `filled` status is the NORMAL state of every open position, not an exit
    signal. Active code reintroducing this pattern would re-create the
    phantom-close bug.

    We allow the literal in comments / docstrings (for incident-history
    documentation) but flag it as active code.
    """
    source = _read_executor_source()

    # Walk line-by-line skipping comments and triple-quoted blocks
    in_triple_quote = False
    suspicious_lines: list[int] = []
    for i, line in enumerate(source.splitlines(), start=1):
        stripped = line.lstrip()
        triple_count = stripped.count('"""') + stripped.count("'''")
        if stripped.startswith("#"):
            if triple_count % 2 == 1:
                in_triple_quote = not in_triple_quote
            continue
        if in_triple_quote:
            if triple_count % 2 == 1:
                in_triple_quote = not in_triple_quote
            continue
        if triple_count % 2 == 1:
            in_triple_quote = not in_triple_quote
            continue
        # The diagnostic pattern: active code that sets bracket_exit=True
        # immediately after referencing parent_status in FILLED_ORDER_STATUSES.
        if "parent_status in FILLED_ORDER_STATUSES" in stripped:
            suspicious_lines.append(i)

    assert not suspicious_lines, (
        "The buggy parent-status branch must not reappear in active code. "
        f"Found at line(s) {suspicious_lines}. See v0.36.28 CHANGELOG entry."
    )


def test_close_from_broker_fill_has_side_guard():
    """The defense-in-depth guard inside `_close_from_broker_fill` must be
    present — it catches mis-routes from any caller (including the two
    sibling sites at executor.py:1430-1434 and 2007-2009).

    The guard is a `side` check that refuses BUY orders. Source-code lock
    so refactors don't accidentally remove it.
    """
    source = _read_executor_source()

    # Locate the function and grab its body up to the next top-level def
    fn_marker = "def _close_from_broker_fill("
    fn_start = source.find(fn_marker)
    assert fn_start != -1, "_close_from_broker_fill function missing"
    # Next top-level def or end of file
    next_def = source.find("\ndef ", fn_start + len(fn_marker))
    fn_body = source[fn_start:next_def if next_def != -1 else len(source)]

    # The guard pattern must appear inside the body
    assert "side" in fn_body and (
        "buy" in fn_body.lower()
    ), (
        "_close_from_broker_fill must contain a side-check that refuses BUY "
        "orders. The guard is the defense-in-depth fix from v0.36.28 — "
        "removing it re-opens the phantom-close attack surface for all 3 "
        "call sites that pass an order dict to this helper."
    )


def test_legs_check_path_preserved():
    """Removing the parent-status branch must NOT damage the legs check
    immediately below at lines 1870-1883 (now lower after the removal).
    The legs check is what correctly detects real bracket-leg fills.
    """
    source = _read_executor_source()
    # The legs iteration pattern should still be present
    assert 'legs = order_status.get("legs", [])' in source, (
        "The legs check must remain in executor.py — it's the correct way "
        "to detect bracket exit (when a stop or target SELL leg actually fills)."
    )
    # And the loop body should still test partially_filled + filled
    assert '"filled"' in source and '"partially_filled"' in source, (
        "Legs status check for filled/partially_filled must remain intact."
    )
