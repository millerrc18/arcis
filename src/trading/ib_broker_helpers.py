"""IB broker helpers — connection/integrity utilities and cancel-before-close.

Called by: trading.ib_broker
Calls: ib_async (TWS API)
Owns tables: none
Config keys: none
Tests: tests/test_ib_broker.py

Extracted from ib_broker.py during Sprint 0.B Wave B2.4 (issue #736)
to keep ib_broker.py under the 400-line file-size guardrail.
"""

import logging

logger = logging.getLogger(__name__)

_IB_ERROR_CODES = {
    110: "price_out_of_range",
    135: "unknown_order_id",
    200: "unknown_contract",
    201: "order_rejected",
    202: "order_cancelled",
    10147: "order_not_active",
}


def handle_ib_error(code: int, msg: str, ticker: str = "") -> None:
    """Log and classify IB error codes."""
    classification = _IB_ERROR_CODES.get(code, "unknown")
    if code in (200, 201):
        logger.error("[IB] %s error for %s (code %d): %s",
                    classification, ticker, code, msg)
    else:
        logger.warning("[IB] %s for %s (code %d): %s",
                      classification, ticker, code, msg)


def verify_bracket_integrity(ib) -> list[str]:
    """After reconnect, verify all positions have active stop orders.

    Returns list of tickers with missing protection.
    """
    unprotected = []
    positions = ib.positions()
    open_trades = ib.openTrades()
    protected_tickers = set()
    for trade in open_trades:
        if (trade.order.orderType in ("STP", "STP LMT") and
                trade.order.action == "SELL" and
                trade.orderStatus.status in ("PreSubmitted", "Submitted")):
            protected_tickers.add(trade.contract.symbol)
    for pos in positions:
        if pos.position > 0 and pos.contract.symbol not in protected_tickers:
            unprotected.append(pos.contract.symbol)
            logger.warning("[IB] UNPROTECTED POSITION: %s (%d shares, no active stop)",
                          pos.contract.symbol, int(pos.position))
    return unprotected


def cancel_bracket_children_for_ticker(
    ib,
    ticker: str,
    *,
    ack_timeout: float = 5.0,
) -> list[str]:
    """Cancel any active bracket-child sell orders for ``ticker`` and
    WAIT for the broker to acknowledge each cancel.

    Sprint 0 Wave 5c IB-CANCEL-BEFORE-CLOSE (CLAUDE.md "Cancel before
    close"). When IBBroker.place_bracket_order submits an OCA group
    of [parent BUY, take-profit SELL, stop-loss SELL], the two child
    SELL orders sit on the broker waiting for the parent to fill.
    After the parent fills, the children become active protective
    exits. If we then submit a market SELL via place_exit without
    cancelling those children first, three SELL orders race:

    - the new market exit
    - the stop-loss (STP/STP LMT)
    - the take-profit (LMT)

    Best case: one fills, ocaType=3 cancels the others. Worst case:
    two fill (the OCA group is broker-side, not atomic) and we
    oversell — which on a long position means going short.

    The Alpaca side mirrors this with cancel_orders_for_ticker on
    the reconcile path (src/shadow_trading/reconcile.py:591,645).
    IB lacked the equivalent until Wave 5c.

    Args:
        ib: Connected IB instance (ib_async.IB).
        ticker: Ticker symbol to cancel sell children for.
        ack_timeout: Seconds to wait for cancel acknowledgements.

    Returns the list of order_ids that were cancelled. Raises
    ConnectionError on cancel-ack timeout — the caller MUST NOT
    proceed to submit the exit if this raises.
    """
    to_cancel = []
    for trade in ib.openTrades():
        if (trade.contract.symbol == ticker
                and trade.order.action == "SELL"
                and trade.orderStatus.status in (
                    "PreSubmitted", "Submitted", "PendingSubmit",
                )):
            to_cancel.append(trade)
    if not to_cancel:
        return []

    cancelled_ids = []
    for trade in to_cancel:
        try:
            ib.cancelOrder(trade.order)
            cancelled_ids.append(str(trade.order.orderId))
            logger.info(
                "[IB] CANCEL-BEFORE-CLOSE: requesting cancel of "
                "%s order %s for %s (status=%s)",
                trade.order.orderType, trade.order.orderId, ticker,
                trade.orderStatus.status,
            )
        except Exception as exc:
            logger.warning(
                "[IB] CANCEL-BEFORE-CLOSE: cancelOrder raised for "
                "%s order %s: %s",
                ticker, trade.order.orderId, exc,
            )

    terminal = {"cancelled", "apicancelled", "inactive", "filled"}
    deadline = ack_timeout
    elapsed = 0.0
    step = 0.5
    cancelled_set = set(cancelled_ids)
    while elapsed < deadline and cancelled_set:
        ib.sleep(step)
        elapsed += step
        still_open = set()
        for trade in ib.openTrades():
            tid = str(trade.order.orderId)
            if tid in cancelled_set:
                status = str(trade.orderStatus.status).lower()
                if status not in terminal:
                    still_open.add(tid)
        cancelled_set = still_open

    if cancelled_set:
        raise ConnectionError(
            f"IB cancel-before-close timeout for {ticker}: "
            f"orders still open after {deadline}s: "
            f"{sorted(cancelled_set)}"
        )

    logger.info(
        "[IB] CANCEL-BEFORE-CLOSE: %d bracket child cancel(s) "
        "acknowledged for %s before exit submit",
        len(cancelled_ids), ticker,
    )
    return cancelled_ids
