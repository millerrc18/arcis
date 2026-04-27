"""Live-order verification helpers extracted from alpaca_adapter.py (Sprint-0.C/C.2).

Called by: src.shadow_trading.alpaca_adapter
Calls: src.shadow_trading.alpaca_adapter_live
Owns tables: none
Config keys: none
Tests: tests/shadow_trading/test_alpaca_adapter_split.py, tests/shadow_trading/test_alpaca_adapter.py
"""
import logging

logger = logging.getLogger(__name__)


_LIVE_VERIFY_ACCEPTED = {"accepted", "new", "pending_new", "filled",
                         "partially_filled", "done_for_day"}
_LIVE_VERIFY_REJECTED = {"rejected", "canceled", "expired", "suspended"}


class OrderNotAcceptedError(Exception):
    """Raised when an order submitted via Alpaca live did NOT reach an
    acceptable status (terminal-cancel, rejected, expired, suspended,
    or persistent unknown after polling).

    Sprint 0 Wave 5c LIVE-VERIFY: Network errors during submission do not
    mean Alpaca rejected the order. Equally, a fire-and-forget submit
    can race a broker-side rejection that the SDK never raised. Live
    capital paths MUST observe the broker's authoritative status.
    """

    def __init__(self, order_id: str, status: str, attempts: int = 1,
                 last_error: str | None = None):
        self.order_id = order_id
        self.status = status
        self.attempts = attempts
        self.last_error = last_error
        msg = (
            f"Order {order_id} not accepted: status={status!r} "
            f"after {attempts} verification attempt(s)"
        )
        if last_error:
            msg += f" (last_error={last_error})"
        super().__init__(msg)


def _poll_order_status(order_id: str) -> tuple[str, dict]:
    """Fetch live order status and build a normalized payload dict.

    Returns (status_str, payload_dict). Raises on client/network errors
    so the caller can count them as polling failures.
    """
    from src.shadow_trading.alpaca_adapter_live import _get_live_trading_client
    client = _get_live_trading_client()
    order = client.get_order_by_id(order_id)
    status = str(order.status).lower().replace("orderstatus.", "")
    payload = {
        "order_id": str(getattr(order, "id", order_id)),
        "symbol": str(getattr(order, "symbol", "")),
        "status": status,
        "qty": float(order.qty) if getattr(order, "qty", None) else 0.0,
        "filled_qty": (
            float(order.filled_qty)
            if getattr(order, "filled_qty", None) else 0.0
        ),
        "filled_avg_price": (
            float(order.filled_avg_price)
            if getattr(order, "filled_avg_price", None) else None
        ),
    }
    return status, payload


def _classify_order_status(status: str) -> str:
    """Map a raw Alpaca order status string to 'accepted', 'rejected', or 'pending'.

    Returns 'accepted' when status is in the accepted terminal set,
    'rejected' when status is in the rejected terminal set, or
    'pending' for any other/unknown status.
    """
    if status in _LIVE_VERIFY_ACCEPTED:
        return "accepted"
    if status in _LIVE_VERIFY_REJECTED:
        return "rejected"
    return "pending"


def _calculate_backoff(attempt: int, base_delay: float, max_delay: float) -> float:
    """Return the exponential backoff delay for the given attempt number (1-based).

    delay = min(base_delay * 2^(attempt-1), max_delay)
    """
    return min(base_delay * (2 ** (attempt - 1)), max_delay)


def _handle_poll_attempt(
    order_id: str, attempt: int, max_attempts: int,
) -> tuple[dict | None, str, str | None]:
    """Execute one poll attempt; return (result_or_None, last_status, last_error).

    Returns (result_dict, status, None) when the order reached an accepted state.
    Raises OrderNotAcceptedError when a terminal-reject is observed.
    Returns (None, status, None) when status is pending/unknown — caller retries.
    Returns (None, 'unknown', error_str) when the API call itself fails.
    """
    try:
        status, payload = _poll_order_status(order_id)
        classification = _classify_order_status(status)
        if classification == "accepted":
            return (
                {"verified": True, "status": status,
                 "attempts": attempt, "order": payload},
                status, None,
            )
        if classification == "rejected":
            logger.error(
                "[LIVE-VERIFY] Order %s in terminal-reject state %r after %d attempt(s)",
                order_id, status, attempt,
            )
            raise OrderNotAcceptedError(order_id=order_id, status=status, attempts=attempt)
        logger.warning(
            "[LIVE-VERIFY] Order %s status=%r on attempt %d/%d; retrying",
            order_id, status, attempt, max_attempts,
        )
        return None, status, None
    except OrderNotAcceptedError:
        raise
    except Exception as exc:
        logger.warning(
            "[LIVE-VERIFY] Could not verify order %s (attempt %d/%d): %s",
            order_id, attempt, max_attempts, exc,
        )
        return None, "unknown", str(exc)


def verify_live_order_accepted(
    order_id: str,
    *,
    max_attempts: int = 5,
    base_delay: float = 1.0,
    max_delay: float = 8.0,
    sleep_fn=None,
) -> dict:
    """Poll Alpaca live for terminal acceptance/rejection of a live order.

    Sprint 0 Wave 5c LIVE-VERIFY. Raises OrderNotAcceptedError on terminal-reject
    or exhausted attempts. Returns {"verified": True, "status", "attempts", "order"}.
    Sub-helpers: _poll_order_status, _classify_order_status, _calculate_backoff,
    _handle_poll_attempt.
    """
    import time as _time
    if sleep_fn is None:
        sleep_fn = _time.sleep

    last_status = "unknown"
    last_error: str | None = None

    for attempt in range(1, max_attempts + 1):
        result, last_status, err = _handle_poll_attempt(order_id, attempt, max_attempts)
        if result is not None:
            return result
        if err is not None:
            last_error = err
        if attempt < max_attempts:
            sleep_fn(_calculate_backoff(attempt, base_delay, max_delay))

    raise OrderNotAcceptedError(
        order_id=order_id,
        status=last_status,
        attempts=max_attempts,
        last_error=last_error,
    )
