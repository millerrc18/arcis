"""Platform-event Telegram notifications.

Called by: src.platform.backtest_engine, src.platform.promotion.
Calls: src.notifications.telegram.send_telegram.
Owns tables: none.
Config keys: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID (transitively via
             telegram module).
Tests: tests/notifications/test_platform_events.py.

All messages prefixed '[RESEARCH]' — operator filter rule on Telegram
client distinguishes from swing trade notifications.

Deduplication via content hash for notify_shadow_gate_ready: once a
gate has been signaled ready for a strategy, don't re-notify within 24h.
"""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

_PREFIX = "[RESEARCH]"
_DEDUP_WINDOW_HOURS = 24
_DEDUP_CACHE: dict[str, datetime] = {}


def _dedup_key(category: str, content: str) -> str:
    return hashlib.sha256(f"{category}::{content}".encode()).hexdigest()


def _already_notified_recently(key: str) -> bool:
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=_DEDUP_WINDOW_HOURS)
    last = _DEDUP_CACHE.get(key)
    if last and last > cutoff:
        return True
    _DEDUP_CACHE[key] = now
    # Opportunistic GC of expired entries
    expired = [k for k, v in _DEDUP_CACHE.items() if v < cutoff]
    for k in expired:
        del _DEDUP_CACHE[k]
    return False


def _send(message: str) -> None:
    """Send via the existing telegram module. Failures are logged,
    not raised — notifications must never crash business logic."""
    try:
        from src.notifications.telegram import send_telegram
        send_telegram(message)
    except Exception:
        logger.exception("[PLATFORM_EVENTS] telegram send failed")


def notify_backtest_complete(
    strategy_id: str, result_id: str, passed_gate_a: bool,
) -> None:
    """Fired from backtest_engine.run_backtest on completion."""
    key = _dedup_key("backtest_complete", f"{strategy_id}::{result_id}")
    if _already_notified_recently(key):
        return
    gate = "[OK] passed auto gate" if passed_gate_a else "[WAIT] awaiting manual"
    _send(
        f"{_PREFIX} Backtest complete: {strategy_id} "
        f"(result_id={result_id[:8]}) {gate}"
    )


def notify_shadow_gate_ready(strategy_id: str, evidence: dict) -> None:
    """Fired when a shadow_trading gate check first passes for a
    strategy. Dedup per-strategy within 24h."""
    key = _dedup_key("shadow_gate_ready", strategy_id)
    if _already_notified_recently(key):
        return
    dsr = evidence.get("dsr")
    pbo = evidence.get("pbo")
    oos = evidence.get("oos_efficiency")
    parts = [f"{_PREFIX} Gate ready for shadow_trading: {strategy_id}"]
    if dsr is not None:
        parts.append(f"DSR={dsr:.3f}")
    if pbo is not None:
        parts.append(f"PBO={pbo:.3f}")
    if oos is not None:
        parts.append(f"OOS_eff={oos:.3f}")
    parts.append("awaiting manual approval.")
    _send(" ".join(parts))


def notify_strategy_promoted(
    strategy_id: str, from_status: str | None, to_status: str,
) -> None:
    """Fired from promotion.promote after successful state transition."""
    _send(
        f"{_PREFIX} Promoted: {strategy_id} {from_status or 'None'} \u2192 {to_status}"
    )


def notify_strategy_demoted(strategy_id: str, reason: str) -> None:
    """Fired from promotion.demote."""
    _send(
        f"{_PREFIX} Demoted: {strategy_id} \u2192 deprecated. Reason: {reason}"
    )
