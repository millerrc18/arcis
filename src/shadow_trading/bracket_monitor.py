"""Bracket order health monitoring — verifies stop/target legs are active.

Called by: scheduler.watch
Calls: notifications.telegram, shadow_trading.alpaca_adapter
Owns tables: bracket_health
Config keys: none
Tests: tests/test_bracket_monitor.py
"""

import logging
import sqlite3
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

from src.config import DB_PATH
from src.utils.db import connect_db

logger = logging.getLogger(__name__)

ET = ZoneInfo("America/New_York")
DEFAULT_DB_PATH = DB_PATH
ACTIVE_LEG_STATUSES = {"new", "held"}

# Table creation handled by src/schema/registry.py


def ensure_bracket_health_table(db_path: str = DEFAULT_DB_PATH) -> None:
    """No-op: table creation handled by src/schema/registry.py at startup."""
    pass


def _classify_legs(order_status: dict) -> tuple[str | None, str | None]:
    """Extract the stop and target leg statuses from an Alpaca bracket payload."""
    stop_status = None
    target_status = None

    for leg in order_status.get("legs", []) or []:
        leg_status = str(leg.get("status") or "").lower() or None
        leg_type = str(leg.get("type") or leg.get("order_type") or "").lower()
        has_stop = leg.get("stop_price") is not None or "stop" in leg_type
        has_limit = leg.get("limit_price") is not None or "limit" in leg_type

        if has_stop and stop_status is None:
            stop_status = leg_status
        elif has_limit and target_status is None:
            target_status = leg_status

    return stop_status, target_status


def _check_partial_fills(order_status: dict, expected_qty: float) -> list[str]:
    """Detect partial fills on bracket legs (#104).

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
    """Persist one health-check record."""
    ensure_bracket_health_table(db_path)
    with connect_db(db_path) as conn:
        conn.execute(
            "INSERT INTO bracket_health "
            "(check_id, trade_id, ticker, stop_leg_status, target_leg_status, "
            " bracket_intact, action_taken, checked_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                str(uuid.uuid4()),
                trade_id,
                ticker,
                stop_status,
                target_status,
                1 if bracket_intact else 0,
                action_taken,
                datetime.now(ET).isoformat(),
            ),
        )
        conn.commit()


def _alert(message: str) -> None:
    """Best-effort Telegram alert for bracket health failures."""
    try:
        from src.notifications.telegram import send_telegram
        send_telegram(message)
    except Exception as exc:
        logger.warning("[BRACKET] Telegram alert failed: %s", exc)


def check_bracket_health(
    db_path: str = DEFAULT_DB_PATH,
    context: str = "intraday",
) -> dict:
    """Verify that every open bracket trade still has active stop and target legs."""
    from src.shadow_trading.alpaca_adapter import get_order_status

    ensure_bracket_health_table(db_path)

    with connect_db(db_path) as conn:
        try:
            trades = conn.execute(
                "SELECT trade_id, ticker, alpaca_order_id, planned_shares "
                "FROM shadow_trades "
                "WHERE status = 'open' AND alpaca_order_id IS NOT NULL "
                "AND COALESCE(order_type, '') = 'bracket'"
            ).fetchall()
        except Exception:
            trades = conn.execute(
                "SELECT trade_id, ticker, alpaca_order_id "
                "FROM shadow_trades "
                "WHERE status = 'open' AND alpaca_order_id IS NOT NULL "
                "AND COALESCE(order_type, '') = 'bracket'"
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

        intact = (
            stop_status in ACTIVE_LEG_STATUSES
            and target_status in ACTIVE_LEG_STATUSES
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

        if intact:
            protected += 1
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
            bracket_intact=intact,
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
