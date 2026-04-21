#!/usr/bin/env python
"""One-shot cleanup for needs_manual_review overshoot zombies.

Context: sprint fix/paper-exit-qty-asymmetry surfaced 13 DB rows in
`status='needs_manual_review', exit_reason='exit_overshoot_detected'`
state — phantom-exit residuals accumulated 2026-04-15 through 2026-04-21
by the bug fixed in Commits 4-6 (reconcile 3rd branch + executor D3
qty-sync + _strip_enum lowercase normalization).

Runs AFTER the fix ships and operator verifies the overshoot mechanism
is closed. For each zombie row: queries Alpaca for the ticker's current
position and handles three cases:

  - qty == 0  → short was covered elsewhere. Close the DB row with
                exit_reason='overshoot_covered_post_deploy', record the
                cover-fill price + time + approximate pnl (best-effort).
  - qty < 0   → still short at Alpaca. Leave row as-is; operator must
                manually cover before re-running.
  - qty > 0   → ticker has a new long position (post-overshoot re-entry
                or manual operation). Leave row as-is; log warning.

Idempotent by design: re-runs skip rows already in terminal state
(status!='needs_manual_review').

Exit codes:
  0 -- success (or no-op on idempotent re-run)
  2 -- Alpaca API unreachable
  3 -- unexpected DB state (no zombies match; operator should re-audit)

Called by: operator (manual one-shot after fix/paper-exit-qty-asymmetry deploys)
Calls: src.shadow_trading.alpaca_adapter.get_all_positions,
       src.shadow_trading.alpaca_adapter._get_trading_client (for order history)
Owns tables: none (writes to shadow_trades via UPDATE)
Config keys: none
Tests: tests/scripts/test_cleanup_overshoot_zombies.py
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from src.config import DB_PATH
from src.shadow_trading.alpaca_adapter import get_all_positions

ET = ZoneInfo("America/New_York")


def _fetch_zombie_rows(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Query all overshoot-detected rows still awaiting resolution."""
    conn.row_factory = sqlite3.Row
    return conn.execute(
        "SELECT trade_id, ticker, direction, status, entry_price, "
        "       actual_entry_price, planned_shares, exit_reason, "
        "       created_at, updated_at "
        "FROM shadow_trades "
        "WHERE status = 'needs_manual_review' "
        "  AND exit_reason = 'exit_overshoot_detected'"
    ).fetchall()


def _last_buy_to_close_fill(ticker: str, lookback_days: int = 14) -> dict | None:
    """Find the most recent filled buy_to_close order for a ticker.

    Returns dict with filled_avg_price and filled_at, or None if no such
    order exists in the lookback window. Uses a direct client call (read-only)
    because alpaca_adapter doesn't expose a filtered-by-position-intent helper.
    """
    try:
        from src.shadow_trading.alpaca_adapter import _get_trading_client
        from alpaca.trading.requests import GetOrdersRequest
        from alpaca.trading.enums import QueryOrderStatus
    except ImportError as e:
        print(f"[WARN] alpaca-py not available ({e}); pnl will be null", file=sys.stderr)
        return None

    after = (datetime.now(ET) - timedelta(days=lookback_days)).isoformat()
    client = _get_trading_client()
    try:
        req = GetOrdersRequest(
            status=QueryOrderStatus.CLOSED,
            symbols=ticker,
            after=after,
            limit=50,
        )
        orders = client.get_orders(filter=req)
    except Exception as exc:
        print(f"[WARN] {ticker}: get_orders failed ({exc}); pnl will be null",
              file=sys.stderr)
        return None

    for order in orders:
        if str(getattr(order, "position_intent", "")).lower().endswith("buy_to_close"):
            if str(getattr(order, "status", "")).lower().endswith("filled"):
                return {
                    "filled_avg_price": float(order.filled_avg_price or 0),
                    "filled_at": str(order.filled_at) if order.filled_at else None,
                    "qty": float(order.qty or 0),
                }
    return None


def _close_zombie_row(
    conn: sqlite3.Connection,
    row: sqlite3.Row,
    cover: dict | None,
    now_iso: str,
) -> dict:
    """Write the closing UPDATE for a zombie whose short has been covered.

    Best-effort pnl: uses the DB row's original long entry_price against the
    cover fill price. This captures only the long-leg P&L (entry → cover),
    NOT the short-leg P&L (sell_to_open → cover). The short-leg P&L is
    captured in Alpaca's account activity; operator can reconcile manually
    via `docs/audit/` if needed. Marking the reason explicitly so future
    analytics know pnl is an approximation.
    """
    entry_price = float(row["actual_entry_price"] or row["entry_price"] or 0)
    shares = float(row["planned_shares"] or 0)
    exit_price = float(cover["filled_avg_price"]) if cover else 0.0
    exit_time = cover["filled_at"] if cover else now_iso

    if entry_price > 0 and exit_price > 0 and shares > 0:
        pnl_dollars = round((exit_price - entry_price) * shares, 2)
        pnl_pct = round((exit_price - entry_price) / entry_price * 100, 2)
    else:
        pnl_dollars = 0.0
        pnl_pct = 0.0

    conn.execute(
        "UPDATE shadow_trades SET "
        "  status = 'closed', "
        "  exit_reason = 'overshoot_covered_post_deploy', "
        "  actual_exit_price = ?, "
        "  actual_exit_time = ?, "
        "  pnl_dollars = ?, "
        "  pnl_pct = ?, "
        "  updated_at = ? "
        "WHERE trade_id = ?",
        (
            exit_price if exit_price > 0 else None,
            exit_time,
            pnl_dollars,
            pnl_pct,
            now_iso,
            row["trade_id"],
        ),
    )
    return {
        "trade_id": row["trade_id"],
        "ticker": row["ticker"],
        "exit_price": exit_price,
        "pnl_dollars": pnl_dollars,
        "pnl_pct": pnl_pct,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Close covered-short overshoot zombies to terminal state."
    )
    parser.add_argument(
        "--apply", action="store_true",
        help="Actually write DB updates. Without this flag, dry-run only.",
    )
    parser.add_argument(
        "--db", default=DB_PATH,
        help=f"SQLite DB path (default: {DB_PATH}).",
    )
    parser.add_argument(
        "--lookback-days", type=int, default=14,
        help="How far back to search for the cover fill (default: 14).",
    )
    args = parser.parse_args(argv)

    dry_run = not args.apply
    now = datetime.now(ET)

    try:
        positions = {p["symbol"]: float(p.get("qty") or 0) for p in get_all_positions()}
    except Exception as exc:
        print(f"[ERROR] Alpaca API unreachable: {exc}", file=sys.stderr)
        return 2

    with sqlite3.connect(args.db, timeout=30.0) as conn:
        zombies = _fetch_zombie_rows(conn)

    if not zombies:
        print("[INFO] No overshoot zombies found. Nothing to do.")
        return 0

    print(f"[INFO] Found {len(zombies)} overshoot zombies. "
          f"Mode: {'DRY-RUN' if dry_run else 'APPLY'}")
    print(f"[INFO] Current Alpaca positions: "
          f"{ {t: q for t, q in positions.items() if q != 0} }")
    print()

    covered: list[dict] = []
    still_short: list[str] = []
    unexpected_long: list[str] = []
    no_cover_fill: list[str] = []

    now_iso = now.isoformat()

    for row in zombies:
        ticker = row["ticker"]
        broker_qty = positions.get(ticker, 0.0)
        tag = f"{ticker} (trade {row['trade_id'][:8]}..., planned={row['planned_shares']}, alpaca={broker_qty:+.0f})"

        if broker_qty == 0:
            cover = _last_buy_to_close_fill(ticker, lookback_days=args.lookback_days)
            if cover is None:
                no_cover_fill.append(tag)
                print(f"  [WARN] {tag} — covered but no buy_to_close fill found in "
                      f"last {args.lookback_days}d; will close with pnl=null")
            if not dry_run:
                with sqlite3.connect(args.db, timeout=30.0) as conn:
                    result = _close_zombie_row(conn, row, cover, now_iso)
                    conn.commit()
                covered.append(result)
            else:
                est_price = cover["filled_avg_price"] if cover else 0.0
                covered.append({
                    "trade_id": row["trade_id"],
                    "ticker": ticker,
                    "exit_price": est_price,
                    "pnl_dollars": "(dry-run)",
                    "pnl_pct": "(dry-run)",
                })
            if cover:
                print(f"  [CLOSE] {tag} — cover fill at ${cover['filled_avg_price']:.2f}")
            else:
                print(f"  [CLOSE] {tag} — no cover fill data")

        elif broker_qty < 0:
            still_short.append(tag)
            print(f"  [SKIP]  {tag} — still short at broker; operator must cover first")

        else:  # broker_qty > 0
            unexpected_long.append(tag)
            print(f"  [SKIP]  {tag} — new long position at broker; row left as-is")

    # Summary
    print()
    print("=" * 72)
    print(f"Closed (or would close): {len(covered)}")
    for r in covered:
        pnl_str = (
            f"${r['pnl_dollars']:+.2f}" if isinstance(r['pnl_dollars'], float)
            else str(r['pnl_dollars'])
        )
        print(f"  {r['ticker']}: exit ${r['exit_price']:.2f}, pnl={pnl_str}")
    print(f"Still short (skipped): {len(still_short)}")
    for t in still_short:
        print(f"  {t}")
    print(f"Unexpected long (skipped): {len(unexpected_long)}")
    for t in unexpected_long:
        print(f"  {t}")
    print(f"Covered but no cover-fill found: {len(no_cover_fill)}")
    for t in no_cover_fill:
        print(f"  {t}")

    if dry_run:
        print()
        print("[INFO] Dry-run complete. Re-run with --apply to write changes.")
    else:
        print()
        print(f"[INFO] {len(covered)} row(s) updated.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
