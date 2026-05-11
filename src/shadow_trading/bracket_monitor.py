"""Bracket order health monitoring — verifies stop/target legs are active.

Called by: scheduler.watch
Calls: notifications.telegram, shadow_trading.alpaca_adapter
Owns tables: bracket_health
Config keys: none
Tests: tests/test_bracket_monitor.py

Why bracket health monitoring?
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Alpaca bracket orders consist of 3 legs: the entry order, a stop-loss
leg, and a take-profit leg.  If any leg silently fails (e.g. Alpaca
rejects the stop due to price rules), the position is unprotected — it
can gap down without a stop-loss.

This monitor runs on three schedules:
  - "intraday": during market hours, checks all open bracket orders
  - "premarket": before market open, sends a summary Telegram alert
  - "postclose": after market close, logs unprotected overnight positions

A broken bracket (missing or cancelled stop/target leg) triggers an
immediate Telegram alert so the operator can manually intervene.  This
is a safety-critical module: an unprotected position during a gap-down
event can lose far more than the intended stop distance.

Partial fill detection (#104): if a bracket leg is only partially
filled, the position may not be fully hedged.  The monitor alerts on
this condition because partial fills are silent in the Alpaca dashboard.
"""

import logging
import sqlite3
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

from src.config import DB_PATH
from src.utils.db import connect_db, engine_aware_upsert

logger = logging.getLogger(__name__)

ET = ZoneInfo("America/New_York")
DEFAULT_DB_PATH = DB_PATH
# A bracket leg is considered "active" (protecting the position) if its
# status is "new" (queued but not yet triggered) or "held" (held at the
# exchange awaiting fill).  Any other status (filled, cancelled, expired,
# rejected) means the leg is no longer protecting the position.
# Fix: added "accepted" — Alpaca uses this for queued bracket legs in addition
# to "new" and "held". Without it, legs in "accepted" state show as broken.
ACTIVE_LEG_STATUSES = {"new", "held", "accepted"}

# Table creation handled by src/schema/registry.py


def ensure_bracket_health_table(db_path: str = DEFAULT_DB_PATH) -> None:
    """No-op: table creation handled by src/schema/registry.py at startup."""
    pass


def _is_oco_topology(order_status: dict) -> bool:
    """Return True if the order status dict represents an OCO order.

    OCO topology: the parent IS the take-profit LIMIT order (parent has
    limit_price set and order_class='oco'), and legs contains only the STOP.

    Detection priority:
    1. Explicit order_class field ('oco').
    2. Structural fallback: parent has limit_price set, no LIMIT child in legs.
       Handles production payloads where _serialize_order has not yet been
       updated to forward order_class from the Alpaca SDK object.
    """
    raw_class = str(order_status.get("order_class") or "").lower()
    order_class = raw_class.split(".")[-1] if "." in raw_class else raw_class
    if order_class == "oco":
        return True
    if order_class in ("bracket", "simple"):
        return False
    # Structural fallback: parent has a limit_price and no LIMIT-type leg.
    parent_has_limit = order_status.get("limit_price") is not None
    if not parent_has_limit:
        return False
    for leg in order_status.get("legs", []) or []:
        leg_type = str(leg.get("type") or leg.get("order_type") or "").lower()
        leg_type = leg_type.split(".")[-1] if "." in leg_type else leg_type
        if "limit" in leg_type or leg.get("limit_price") is not None:
            return False
    return True


def _classify_legs(order_status: dict) -> tuple[str | None, str | None]:
    """Extract the stop and target leg statuses from an Alpaca order payload.

    Supports two Alpaca order topologies:

    BRACKET: parent is the filled entry order; legs=[STOP, LIMIT].
    Both the stop-loss and take-profit are in parent.legs.

    OCO: parent IS the take-profit LIMIT order (order_class='oco' or
    structural: parent has limit_price, legs has only STOP).  The
    take-profit status is read from the parent; the stop status from
    the single leg.

    Returns (stop_status, target_status) as lowercase strings or None.
    """
    if _is_oco_topology(order_status):
        # OCO: parent status = take-profit status; single leg = stop.
        raw_parent = str(order_status.get("status") or "").lower()
        target_status = raw_parent.split(".")[-1] if "." in raw_parent else raw_parent
        target_status = target_status or None

        stop_status = None
        for leg in order_status.get("legs", []) or []:
            leg_type = str(leg.get("type") or leg.get("order_type") or "").lower()
            leg_type = leg_type.split(".")[-1] if "." in leg_type else leg_type
            has_stop = leg.get("stop_price") is not None or "stop" in leg_type
            if has_stop and stop_status is None:
                raw_status = str(leg.get("status") or "").lower()
                stop_status = raw_status.split(".")[-1] if "." in raw_status else raw_status
                stop_status = stop_status or None
        return stop_status, target_status

    # BRACKET (and unrecognized) topology: find STOP + LIMIT in legs.
    stop_status = None
    target_status = None

    for leg in order_status.get("legs", []) or []:
        # Fix for #248 follow-up: defensively strip Alpaca enum prefix from leg
        # status. _serialize_order should handle this, but belt-and-suspenders
        # since 0/N protected persisted for 5+ days in production logs.
        raw_status = str(leg.get("status") or "").lower()
        leg_status = raw_status.split(".")[-1] if "." in raw_status else raw_status
        leg_status = leg_status or None
        leg_type = str(leg.get("type") or leg.get("order_type") or "").lower()
        leg_type = leg_type.split(".")[-1] if "." in leg_type else leg_type
        has_stop = leg.get("stop_price") is not None or "stop" in leg_type
        has_limit = leg.get("limit_price") is not None or "limit" in leg_type

        if has_stop and stop_status is None:
            stop_status = leg_status
        elif has_limit and target_status is None:
            target_status = leg_status

    return stop_status, target_status


def _check_partial_fills(order_status: dict, expected_qty: float) -> list[str]:
    """Detect partial fills on bracket legs (#104).

    A partial fill means only some shares are protected by the bracket
    leg.  For example, if you bought 100 shares but only 60 have a
    stop-loss, 40 shares are naked.  This is particularly dangerous
    for overnight holds where gap risk is highest.

    Returns list of warning messages for any partially filled legs.
    """
    warnings = []
    for leg in order_status.get("legs", []) or []:
        leg_status = str(leg.get("status") or "").lower()
        if leg_status != "partially_filled":
            continue
        filled_qty = float(leg.get("filled_qty") or 0)
        leg_type = str(leg.get("type") or leg.get("order_type") or "").lower()
        leg_label = "stop" if "stop" in leg_type else "target"
        if filled_qty < expected_qty:
            warnings.append(
                f"{leg_label} leg partially filled: {filled_qty}/{expected_qty} shares"
            )
    return warnings


def _record_check(
    trade_id: str,
    ticker: str,
    stop_status: str | None,
    target_status: str | None,
    bracket_intact: bool,
    action_taken: str | None,
    db_path: str,
) -> None:
    """Persist one health-check record.

    Every check (pass or fail) is written to bracket_health for audit
    trail.  This enables post-hoc analysis: "How often are brackets
    breaking?  Is it correlated with specific order types or times?"
    """
    ensure_bracket_health_table(db_path)
    with connect_db(db_path) as conn:
        engine_aware_upsert(conn, 'bracket_health', {
            'check_id': str(uuid.uuid4()),
            'trade_id': trade_id,
            'ticker': ticker,
            'stop_leg_status': stop_status,
            'target_leg_status': target_status,
            'bracket_intact': 1 if bracket_intact else 0,
            'action_taken': action_taken,
            'checked_at': datetime.now(ET).isoformat(),
        }, action='ignore')


def _alert(message: str) -> None:
    """Best-effort Telegram alert for bracket health failures.

    Best-effort: if Telegram is down, the alert is logged but the
    monitor continues.  A failed alert must never prevent the health
    check from completing and recording its findings.
    """
    try:
        from src.notifications.telegram import send_telegram
        send_telegram(message)
    except Exception as exc:
        logger.warning("[BRACKET] Telegram alert failed: %s", exc)


def check_bracket_health(
    db_path: str = DEFAULT_DB_PATH,
    context: str = "intraday",
) -> dict:
    """Verify that every open bracket trade still has active stop and target legs.

    Iterates all open trades with an alpaca_order_id and order_type='bracket',
    fetches their current status from Alpaca, and classifies each bracket
    as intact (both legs active) or broken (any leg missing/cancelled).

    Context-dependent behavior:
      - "intraday": alerts immediately on broken brackets
      - "premarket": sends a summary "X/Y positions protected" message
      - "postclose": logs unprotected overnight positions (higher risk)
    """
    from src.shadow_trading.alpaca_adapter import get_order_status

    ensure_bracket_health_table(db_path)

    # STATUS-NARROW: bracket health is meaningful only for trades whose
    # broker-side legs SHOULD still be active. Broadening to ACTIVE_STATUSES
    # would generate false alarms on `exit_pending` (bracket cancel
    # initiated) and `submission_uncertain` (entry submission limbo), so
    # this query intentionally stays on `status='open'`. Sprint 0 / Wave 1b
    # STATUS-CONST: kept narrow per orphan-check parity (see reconcile.py
    # for the same rationale on the live/paper stale checks).
    with connect_db(db_path) as conn:
        try:
            trades = conn.execute(
                "SELECT trade_id, ticker, alpaca_order_id, planned_shares "
                "FROM shadow_trades "
                "WHERE status = 'open' AND alpaca_order_id IS NOT NULL "
                "AND COALESCE(order_type, '') = 'bracket'"
                " AND COALESCE(quarantined, 0) = 0"
            ).fetchall()
        except Exception:
            # STATUS-NARROW: same rationale as the primary query above —
            # only `status='open'` trades have legs the broker should still
            # be holding. This fallback exists for older schemas missing
            # `planned_shares`; the status filter must stay equally narrow.
            trades = conn.execute(
                "SELECT trade_id, ticker, alpaca_order_id "
                "FROM shadow_trades "
                "WHERE status = 'open' AND alpaca_order_id IS NOT NULL "
                "AND COALESCE(order_type, '') = 'bracket'"
                " AND COALESCE(quarantined, 0) = 0"
            ).fetchall()

    checked = 0
    protected = 0
    broken = []

    for trade in trades:
        checked += 1
        stop_status = None
        target_status = None
        action_taken = None

        try:
            order_status = get_order_status(trade["alpaca_order_id"])
            stop_status, target_status = _classify_legs(order_status)
        except Exception as exc:
            action_taken = f"status_lookup_failed:{exc}"
            logger.warning(
                "[BRACKET] Status lookup failed for %s (%s): %s",
                trade["ticker"],
                trade["trade_id"],
                exc,
            )

        # A bracket is intact only if BOTH legs are active.  A missing
        # target leg is less dangerous (you just miss profit-taking) but
        # a missing stop leg is critical (unlimited downside exposure).
        # Both are alerted because an incomplete bracket indicates
        # something went wrong with order submission.
        intact = (
            stop_status in ACTIVE_LEG_STATUSES
            and target_status in ACTIVE_LEG_STATUSES
        )

        # Healthy completion: take-profit filled, stop sibling auto-canceled by broker.
        # This is correct OCO behavior — the position exited cleanly via the target.
        # Must NOT fire an alert. Applies to both BRACKET and OCO topologies.
        healthy_completion = (
            target_status == "filled"
            and stop_status in ("canceled", "rejected")
        )

        # Check for partial fills on bracket legs (#104)
        try:
            expected_qty = float(trade["planned_shares"] or 0)
        except (KeyError, IndexError):
            expected_qty = 0
        if expected_qty > 0:
            try:
                partial_warnings = _check_partial_fills(order_status, expected_qty)
                for pw in partial_warnings:
                    _alert(
                        f"PARTIAL FILL: {trade['ticker']} {pw} — "
                        f"position may not be fully protected"
                    )
                    if action_taken is None:
                        action_taken = "alerted_partial_fill"
            except Exception as exc:
                logger.warning("[BRACKET] Partial fill check failed for %s: %s",
                               trade["ticker"], exc)

        if intact or healthy_completion:
            protected += 1
            if healthy_completion and action_taken is None:
                action_taken = "healthy_completion"
        else:
            broken.append(
                {
                    "ticker": trade["ticker"],
                    "trade_id": trade["trade_id"],
                    "stop_leg_status": stop_status,
                    "target_leg_status": target_status,
                }
            )
            if stop_status not in ACTIVE_LEG_STATUSES:
                _alert(
                    f"🔴 BRACKET ALERT: {trade['ticker']} stop leg "
                    f"{stop_status or 'missing'} — position may be unprotected"
                )
                action_taken = "alerted_stop_leg"
            elif target_status not in ACTIVE_LEG_STATUSES:
                _alert(
                    f"🔴 BRACKET ALERT: {trade['ticker']} target leg "
                    f"{target_status or 'missing'} — bracket is incomplete"
                )
                action_taken = "alerted_target_leg"

            if context == "postclose":
                action_taken = "logged_unprotected_overnight"

        _record_check(
            trade_id=trade["trade_id"],
            ticker=trade["ticker"],
            stop_status=stop_status,
            target_status=target_status,
            bracket_intact=intact or healthy_completion,
            action_taken=action_taken,
            db_path=db_path,
        )

    if context == "premarket":
        _alert(f"✅ Pre-market bracket check: {protected}/{checked} positions protected")

    return {
        "checked": checked,
        "protected": protected,
        "broken": broken,
        "context": context,
    }
