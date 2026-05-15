"""Backfill OCO bracket protection on open positions the broker shows unprotected.

Context: 2026-05-15 health-check revealed 17 of 19 open shadow_trades had
no active broker-side stop/target legs. Two failure modes converged on
the same gap:

  1. **Bracket canceled** — the 2026-05-12 reconciler mis-fire (triggered
     by an upstream PG schema error: ``relation "model_versions" does
     not exist``) caused the reconciler to cancel the TP/SL legs of
     seven tickers, mistakenly thinking they were "dangling orders for a
     missing trade record." The trade records actually existed.
  2. **No bracket ever attached** — when the reconciler backfills an
     orphan position (broker has shares, system doesn't), it creates a
     shadow_trade record but does NOT submit a new bracket order. The
     system tracks the position but has no broker-side enforcement.

This module fills the systemic gap: it scans open shadow_trades and
attaches an OCO (sell-limit at ``target_1`` + sell-stop at ``stop_price``)
for each position the broker shows unprotected.

Called by:
  - ``src.shadow_trading.reconcile`` — call with ``ticker_filter=[ticker]``
    after a backfill_orphan completes for that ticker
  - ``src.shadow_trading.bracket_monitor`` — periodic repair after broken-
    bracket detection (TODO follow-up)
  - Standalone CLI: ``python -m src.shadow_trading.bracket_attach [--dry-run]``

Returns: ``{"scanned": int, "submitted": [...], "skipped": [...], "failed": [...]}``

Tests: tests/shadow_trading/test_bracket_attach.py
"""
from __future__ import annotations

import logging
import sys
from typing import Optional

from src.config import DB_PATH
from src.shadow_trading.alpaca_adapter import (
    _get_trading_client, _strip_enum,
)
from src.utils.db import connect_db

logger = logging.getLogger(__name__)

# Broker-side states that mean the order/leg is alive and protecting the
# position. Mirrors `bracket_monitor.ACTIVE_LEG_STATUSES` plus
# `pending_new` (the routing-stage transient that OCOs return on submit).
ACTIVE_BROKER_STATUSES = frozenset({"new", "held", "accepted", "pending_new"})


def _is_protected(order) -> bool:
    """Return True if a broker order represents active bracket protection.

    For an OCO order: parent is the sell-limit, legs[0] is the sell-stop.
    Either being active means the position is protected.

    For an original BRACKET order: parent is the entry (FILLED after fill),
    legs are TP + SL. Once parent is FILLED, only the legs matter.

    Either way: at least one of parent or any leg in ACTIVE_BROKER_STATUSES
    means there is an outstanding exit order at the broker.
    """
    parent_status = _strip_enum(getattr(order, "status", None))
    if parent_status in ACTIVE_BROKER_STATUSES:
        return True
    for leg in (getattr(order, "legs", None) or []):
        leg_status = _strip_enum(getattr(leg, "status", None))
        if leg_status in ACTIVE_BROKER_STATUSES:
            return True
    return False


def _build_oco_request(ticker: str, qty: int, stop_price: float, target_1: float):
    """Construct an Alpaca OCO sell request.

    Alpaca's OCO model: a sell-limit (take_profit) paired with a sell-stop
    (stop_loss). Either leg's fill auto-cancels the other.

    Dict form (not TakeProfitRequest/StopLossRequest classes) for the
    take_profit / stop_loss fields — Pydantic coerces, and the dict form
    avoids extra alpaca-py imports the conftest mocks don't ship.
    """
    from alpaca.trading.requests import LimitOrderRequest
    from alpaca.trading.enums import OrderSide, TimeInForce, OrderClass
    return LimitOrderRequest(
        symbol=ticker,
        qty=qty,
        side=OrderSide.SELL,
        time_in_force=TimeInForce.GTC,
        limit_price=round(target_1, 2),
        order_class=OrderClass.OCO,
        take_profit={"limit_price": round(target_1, 2)},
        stop_loss={"stop_price": round(stop_price, 2)},
    )


def attach_brackets_for_unprotected_positions(
    db_path: str = DB_PATH,
    desk: str = "swing",
    dry_run: bool = False,
    ticker_filter: Optional[list[str]] = None,
) -> dict:
    """Scan open positions and attach OCO brackets where the broker shows none.

    Args:
        db_path: SQLite or Postgres DB path; defaults to runtime DB.
        desk: Alpaca client desk routing; defaults to "swing".
        dry_run: When True, runs all pre-flight checks but does not submit
            orders or write to the DB. Returns the same shape dict.
        ticker_filter: When set, only consider trades whose ticker is in
            this list. Used by the reconciler to act on a single just-
            backfilled position.

    Returns:
        ``{"scanned": int, "submitted": [(ticker, order_id, qty), ...],
           "skipped": [(ticker, reason), ...],
           "failed": [(ticker, error), ...]}``

    Per-ticker isolation: a failure on one ticker does not halt the batch.
    Pre-flight checks (broker has matching long qty, stop < current < target,
    no other open orders, not already protected) skip rather than submit
    bad orders.
    """
    client = _get_trading_client(desk=desk)
    conn = connect_db(db_path)

    try:
        rows = conn.execute(
            """SELECT trade_id, ticker, planned_shares, stop_price, target_1,
                      alpaca_order_id, order_type
               FROM shadow_trades
               WHERE status='open'
                 AND COALESCE(quarantined,0)=0
                 AND stop_price IS NOT NULL
                 AND target_1 IS NOT NULL
                 AND planned_shares > 0
               ORDER BY ticker"""
        ).fetchall()
    finally:
        # We do per-action commits below; close at the very end.
        pass

    submitted: list[tuple[str, str, int]] = []
    skipped: list[tuple[str, str]] = []
    failed: list[tuple[str, str]] = []
    scanned = 0

    for r in rows:
        ticker = r["ticker"]
        if ticker_filter is not None and ticker not in ticker_filter:
            continue
        scanned += 1

        planned = float(r["planned_shares"])
        stop_price = float(r["stop_price"])
        target_1 = float(r["target_1"])

        # Already protected?
        existing_oid = r["alpaca_order_id"]
        if existing_oid:
            try:
                existing_order = client.get_order_by_id(existing_oid)
                if _is_protected(existing_order):
                    skipped.append((ticker, "already protected"))
                    continue
            except Exception as exc:
                # Stale or unknown order — fall through to attempt re-attach
                logger.debug("[BRACKET_ATTACH] %s: get_order_by_id failed (%s); proceeding to re-attach", ticker, exc)

        # Pre-flight 1: broker has a matching long position
        try:
            pos = client.get_open_position(ticker)
            broker_qty = float(pos.qty)
            current_price = float(pos.current_price)
        except Exception as exc:
            skipped.append((ticker, f"no broker position: {exc}"))
            continue

        if broker_qty <= 0:
            skipped.append((ticker, f"broker qty {broker_qty} not positive"))
            continue
        if abs(broker_qty - planned) > 1:
            skipped.append((ticker, f"qty mismatch: broker={broker_qty} planned={planned}"))
            continue

        # Pre-flight 2: bracket levels won't fire on submit
        if stop_price >= current_price:
            skipped.append((ticker, f"stop ${stop_price:.2f} >= current ${current_price:.2f}"))
            continue
        if target_1 <= current_price:
            skipped.append((ticker, f"target ${target_1:.2f} <= current ${current_price:.2f}"))
            continue

        # Pre-flight 3: no other open orders for this ticker (avoid duplicate brackets)
        try:
            from alpaca.trading.requests import GetOrdersRequest
            from alpaca.trading.enums import QueryOrderStatus
            open_orders = client.get_orders(GetOrdersRequest(
                status=QueryOrderStatus.OPEN, symbols=[ticker],
            ))
            if open_orders:
                skipped.append((ticker, f"already has {len(open_orders)} open order(s)"))
                continue
        except Exception as exc:
            skipped.append((ticker, f"open-orders check failed: {exc}"))
            continue

        qty = int(broker_qty)

        if dry_run:
            submitted.append((ticker, "DRY_RUN", qty))
            logger.info("[BRACKET_ATTACH] %s: DRY_RUN — would submit OCO (qty=%d, stop=%.2f, target=%.2f)",
                        ticker, qty, stop_price, target_1)
            continue

        # Submit + update DB
        try:
            order = client.submit_order(_build_oco_request(ticker, qty, stop_price, target_1))
            new_oid = str(order.id)
        except Exception as exc:
            failed.append((ticker, str(exc)))
            logger.warning("[BRACKET_ATTACH] %s: submit failed: %s", ticker, exc)
            continue

        try:
            conn.execute(
                "UPDATE shadow_trades SET alpaca_order_id=?, order_type='bracket' WHERE trade_id=?",
                (new_oid, r["trade_id"]),
            )
            conn.commit()
            submitted.append((ticker, new_oid, qty))
            logger.info("[BRACKET_ATTACH] %s: attached OCO oid=%s (qty=%d)", ticker, new_oid, qty)
        except Exception as exc:
            # OCO is at the broker; DB write failed. Position IS protected
            # but the shadow_trade record won't reflect the new oid. Log
            # loudly so the operator can manually update.
            failed.append((ticker, f"DB update failed (OCO submitted at broker, oid={new_oid}): {exc}"))
            logger.error(
                "[BRACKET_ATTACH] %s: OCO submitted (oid=%s) but DB update failed: %s",
                ticker, new_oid, exc,
            )

    conn.close()
    return {
        "scanned": scanned,
        "submitted": submitted,
        "skipped": skipped,
        "failed": failed,
    }


def _main(argv: list[str]) -> int:
    """CLI entry point. Run as: python -m src.shadow_trading.bracket_attach [--dry-run]."""
    dry_run = "--dry-run" in argv
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
    result = attach_brackets_for_unprotected_positions(dry_run=dry_run)
    print(f"Scanned: {result['scanned']}")
    print(f"Submitted: {len(result['submitted'])}")
    for t, oid, qty in result["submitted"]:
        print(f"  {t}: qty={qty} oid={oid}")
    print(f"Skipped: {len(result['skipped'])}")
    for t, reason in result["skipped"]:
        print(f"  {t}: {reason}")
    print(f"Failed: {len(result['failed'])}")
    for t, err in result["failed"]:
        print(f"  {t}: {err}")
    return 0 if not result["failed"] else 1


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
