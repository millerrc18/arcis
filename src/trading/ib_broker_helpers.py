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
_ib_logger = logging.getLogger("src.trading.ib_broker")

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
        _ib_logger.error("[IB] %s error for %s (code %d): %s",
                         classification, ticker, code, msg)
    else:
        _ib_logger.warning("[IB] %s for %s (code %d): %s",
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


def _find_active_sell_children(ib, ticker: str) -> list:
    """Return open SELL trades for ``ticker`` that could race an exit order."""
    return [
        trade for trade in ib.openTrades()
        if (trade.contract.symbol == ticker
            and trade.order.action == "SELL"
            and trade.orderStatus.status in (
                "PreSubmitted", "Submitted", "PendingSubmit",
            ))
    ]


def _await_cancel_acks(ib, cancelled_ids: list[str], ticker: str,
                       ack_timeout: float) -> None:
    """Poll IB until all ``cancelled_ids`` reach a terminal state or timeout.

    Raises ConnectionError if any order is still open after ``ack_timeout``.
    Terminal states: cancelled, apicancelled, inactive, filled.
    """
    terminal = {"cancelled", "apicancelled", "inactive", "filled"}
    elapsed = 0.0
    step = 0.5
    pending = set(cancelled_ids)
    while elapsed < ack_timeout and pending:
        ib.sleep(step)
        elapsed += step
        still_open = set()
        for trade in ib.openTrades():
            tid = str(trade.order.orderId)
            if tid in pending:
                if str(trade.orderStatus.status).lower() not in terminal:
                    still_open.add(tid)
        pending = still_open
    if pending:
        raise ConnectionError(
            f"IB cancel-before-close timeout for {ticker}: "
            f"orders still open after {ack_timeout}s: {sorted(pending)}"
        )


def cancel_bracket_children_for_ticker(
    ib,
    ticker: str,
    *,
    ack_timeout: float = 5.0,
) -> list[str]:
    """Cancel active bracket-child sell orders for ``ticker`` and wait for acks.

    Sprint 0 Wave 5c IB-CANCEL-BEFORE-CLOSE. Finds active SELL children,
    requests cancels, then waits for broker acknowledgement via
    _await_cancel_acks. Raises ConnectionError on ack timeout.
    Returns list of cancelled order_ids.
    """
    to_cancel = _find_active_sell_children(ib, ticker)
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

    _await_cancel_acks(ib, cancelled_ids, ticker, ack_timeout)
    logger.info(
        "[IB] CANCEL-BEFORE-CLOSE: %d bracket child cancel(s) "
        "acknowledged for %s before exit submit",
        len(cancelled_ids), ticker,
    )
    return cancelled_ids
