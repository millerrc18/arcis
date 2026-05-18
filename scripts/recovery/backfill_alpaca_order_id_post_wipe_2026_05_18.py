"""One-shot DB backfill for 'matched but DB-blind' open positions.

Context (P0-1 from docs/audits/2026-W21-execution-cleanup/inventory.md):

After the 2026-05-17 PG wipe and SQLite -> PG restore cycle, six shadow_trades
in status='open' had no alpaca_order_id in DB but were actively protected by
an OCO bracket at Alpaca. The watch loop's reconcile-orphan-backfill logic
doesn't handle this case because it only backfills when there's a position
at broker AND NO matching open shadow_trade. Here, the shadow_trade exists
(matched by ticker); only the OID linkage is missing.

This script:
  1. Scans shadow_trades for status='open' AND empty alpaca_order_id
  2. For each ticker, queries Alpaca for active OCO orders
  3. Matches by ticker
  4. Backfills shadow_trades.alpaca_order_id

Safety:
  - Dry-run by default (--commit to actually write)
  - Per-ticker isolation: one ticker's failure doesn't halt the batch
  - Idempotent: re-running on already-backfilled rows is a no-op
  - Pre-flight: rejects if multiple OCO orders match a ticker
    (ambiguity requires operator review)

Usage:
    python scripts/recovery/backfill_alpaca_order_id_post_wipe_2026_05_18.py            # dry-run
    python scripts/recovery/backfill_alpaca_order_id_post_wipe_2026_05_18.py --commit   # apply
"""
from __future__ import annotations

import argparse
import logging
import sys
import os

# Ensure repo root on path so `from src...` works when invoked directly
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from src.config import DB_PATH
from src.shadow_trading.alpaca_adapter import _get_trading_client, _strip_enum
from src.utils.db import connect_db


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("backfill-oid-2026-05-18")


# Broker-side states that mean the order/leg is alive and protecting the
# position. Mirrors `bracket_attach.py:ACTIVE_BROKER_STATUSES`.
ACTIVE_BROKER_STATUSES = frozenset({"new", "held", "accepted", "pending_new"})


def _is_active_protection(order) -> bool:
    """Return True if an Alpaca order is an active OCO providing protection."""
    parent_status = _strip_enum(getattr(order, "status", None))
    if parent_status in ACTIVE_BROKER_STATUSES:
        return True
    for leg in (getattr(order, "legs", None) or []):
        leg_status = _strip_enum(getattr(leg, "status", None))
        if leg_status in ACTIVE_BROKER_STATUSES:
            return True
    return False


def find_blind_open_trades(conn) -> list[dict]:
    """Return list of open shadow_trades missing alpaca_order_id."""
    rows = conn.execute("""
        SELECT trade_id, ticker, planned_shares, stop_price, target_1
        FROM shadow_trades
        WHERE status='open'
          AND COALESCE(quarantined, 0) = 0
          AND (alpaca_order_id IS NULL OR alpaca_order_id = '')
        ORDER BY ticker
    """).fetchall()
    return [dict(r) for r in rows]


def find_active_bracket_for_ticker(client, ticker: str) -> tuple[str | None, str | None]:
    """Query Alpaca for the single active OCO bracket order for `ticker`.

    Returns (order_id, reason_if_none).
      - (oid, None) when exactly one active bracket is found
      - (None, "no_active_bracket") when no protective orders exist
      - (None, "ambiguous: N orders") when multiple match (needs operator review)
    """
    try:
        from alpaca.trading.requests import GetOrdersRequest
        from alpaca.trading.enums import QueryOrderStatus
        orders = client.get_orders(GetOrdersRequest(
            status=QueryOrderStatus.OPEN, symbols=[ticker],
        ))
    except Exception as exc:
        return None, f"alpaca_get_orders_failed: {exc}"

    active = [o for o in orders if _is_active_protection(o)]
    if not active:
        return None, "no_active_bracket"
    if len(active) > 1:
        return None, f"ambiguous: {len(active)} active orders"
    return str(active[0].id), None


def check_qty_match(client, ticker: str, planned_shares: float) -> tuple[bool, str | None]:
    """Verify broker's open position qty matches our planned_shares.

    Returns (match_ok, reason_if_mismatch). Tolerance ±1 share for fractional
    drift in Alpaca's qty reporting.
    """
    try:
        pos = client.get_open_position(ticker)
        broker_qty = float(pos.qty)
    except Exception as exc:
        return False, f"no_broker_position: {exc}"

    if abs(broker_qty - float(planned_shares)) > 1:
        return False, f"qty_mismatch: broker={broker_qty} planned={planned_shares}"
    return True, None


def run(db_path: str, commit: bool) -> dict:
    """Execute the backfill. Returns a result dict for the report."""
    client = _get_trading_client(desk="swing")
    conn = connect_db(db_path)

    candidates = find_blind_open_trades(conn)
    logger.info("Found %d open trade(s) missing alpaca_order_id", len(candidates))

    backfilled: list[tuple[str, str]] = []
    skipped: list[tuple[str, str]] = []
    failed: list[tuple[str, str]] = []

    for c in candidates:
        ticker = c["ticker"]
        trade_id = c["trade_id"]
        planned_shares = c["planned_shares"]

        # Pre-flight: broker qty must match planned. Skip qty-mismatch cases
        # (Cat C from inventory) — they need P1-level partial-exit reconciliation,
        # not silent OID backfill that papers over the discrepancy.
        qty_ok, qty_reason = check_qty_match(client, ticker, planned_shares)
        if not qty_ok:
            skipped.append((ticker, qty_reason or "qty check failed"))
            logger.info("  %s — SKIP: %s", ticker, qty_reason)
            continue

        oid, reason = find_active_bracket_for_ticker(client, ticker)
        if oid is None:
            skipped.append((ticker, reason or "unknown"))
            logger.info("  %s — SKIP: %s", ticker, reason)
            continue

        if not commit:
            backfilled.append((ticker, f"WOULD_SET oid={oid}"))
            logger.info("  %s — DRY-RUN: would UPDATE alpaca_order_id=%s", ticker, oid)
            continue

        try:
            conn.execute(
                "UPDATE shadow_trades SET alpaca_order_id=? WHERE trade_id=?",
                (oid, trade_id),
            )
            conn.commit()
            backfilled.append((ticker, oid))
            logger.info("  %s — COMMITTED: alpaca_order_id=%s", ticker, oid)
        except Exception as exc:
            failed.append((ticker, str(exc)))
            logger.warning("  %s — UPDATE failed: %s", ticker, exc)

    conn.close()
    return {
        "scanned": len(candidates),
        "backfilled": backfilled,
        "skipped": skipped,
        "failed": failed,
        "commit": commit,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--commit",
        action="store_true",
        help="Apply changes. Default: dry-run only.",
    )
    parser.add_argument(
        "--db-path",
        default=DB_PATH,
        help="DB path (default: src.config.DB_PATH; cutover routes to PG).",
    )
    args = parser.parse_args()

    print("=" * 70)
    print("BACKFILL alpaca_order_id for DB-blind open positions")
    print("Mode:", "COMMIT" if args.commit else "DRY-RUN")
    print("=" * 70)

    result = run(args.db_path, args.commit)

    print()
    print("Scanned:    %d" % result["scanned"])
    print("Backfilled: %d" % len(result["backfilled"]))
    for ticker, oid_or_msg in result["backfilled"]:
        print(f"  {ticker}: {oid_or_msg}")
    print("Skipped:    %d" % len(result["skipped"]))
    for ticker, reason in result["skipped"]:
        print(f"  {ticker}: {reason}")
    print("Failed:     %d" % len(result["failed"]))
    for ticker, err in result["failed"]:
        print(f"  {ticker}: {err}")
    print()
    print("To apply: re-run with --commit")
    return 0 if not result["failed"] else 2


if __name__ == "__main__":
    sys.exit(main())
