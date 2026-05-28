"""Telegram notification client for Arcis.

Called by: cli.commands, data_collection.research_synthesizer, scheduler.watch, services.scan_service, shadow_trading.bracket_monitor, shadow_trading.executor, training.canary, training.ingestion_gate
Calls: config, council.engine, logging.activity, notifications.telegram_delivery, training.versioning
Owns tables: none
Config keys: bot_token, chat_id, enabled, telegram
Tests: tests/test_action_reminders.py, tests/test_expanded_notifications.py, tests/test_live_trading.py, tests/test_system_validator.py

Sends real-time alerts for trade opens/closes, scan results,
system events, and overnight pipeline status.

Setup:
1. Message @BotFather on Telegram, send /newbot, follow prompts
2. Copy the bot token
3. Message your new bot (send /start)
4. Get your chat_id: visit https://api.telegram.org/bot<TOKEN>/getUpdates
5. Add to config/settings.local.yaml:
   telegram:
     enabled: true
     bot_token: "your-bot-token"
     chat_id: "your-chat-id"

Function groups (32+ functions organized by category):

  Core transport (defined here):
    send_telegram, is_telegram_enabled, _get_telegram_config, _send_single,
    _redact_token, _html_escape

  Central dispatcher (defined here):
    safe_send, _do_dispatch, _do_dispatch_escalated, _EVENT_MAP, _load_notifications_config

  Pre-formatted alerts (moved to telegram_delivery.py, re-exported here):
    The notify_* builders + their payload dataclasses live in
    src/notifications/telegram_delivery.py (T11). They are re-imported so that
    imports and test patches at src.notifications.telegram.<name> still resolve.

  Trade lifecycle (gated by trade_id/ticker):
    notify_trade_opened, notify_trade_closed

  Scan & pipeline notifications:
    notify_scan_complete, notify_scan_result, notify_first_scan_summary,
    notify_watchlist, notify_premarket_complete, notify_premarket_brief

  System & risk alerts:
    notify_risk_alert, notify_system_event, notify_startup_complete,
    notify_validation_summary, notify_collection_failure,
    notify_exposure_alert, notify_regime_alert

  Overnight & scheduling:
    notify_overnight_complete, notify_overnight_training_complete,
    notify_gpu_health, notify_scoring_summary, notify_schedule_health

  Periodic reports:
    notify_daily_summary, notify_eod_report, notify_data_asset_report,
    notify_weekly_digest, notify_retrain_report, notify_research_papers,
    notify_research_digest

  Milestones & alerts:
    notify_milestone, notify_streak_alert, notify_earnings_warning,
    notify_position_earnings_warning, notify_model_event

  Action reminders:
    notify_action_required

  Command handler (moved to telegram_commands.py):
    poll_commands, handle_command, check_action_reminders, _cmd_*

Rate limiting: No explicit rate limiter; Telegram's Bot API allows ~30 msg/sec.
The overnight pipeline naturally spaces messages out. If batch notifications
become an issue, a queue with per-second throttling should be added.

All messages use parse_mode="HTML" by default because Markdown requires
escaping special chars that appear frequently in financial data (., -, +).
"""

import logging
import os
import socket
from datetime import datetime
from types import MappingProxyType
from zoneinfo import ZoneInfo

import requests
import requests.exceptions
import urllib3.exceptions

from src.config import DB_PATH
from src.notifications._config import _get_telegram_config

logger = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")

TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"


# #424 — Sanitize the bot token from any string that contains the
# standard Telegram URL pattern. Telegram bot tokens have the shape
# `<digits>:<base64-ish>` and appear in URLs as `/bot<TOKEN>/<method>`.
# requests.post exceptions on connection errors include the URL in the
# message, so any logger.warning("...%s", e) call leaks the token to
# wherever logs ship (Loki, files, dashboard streams).
#
# Restored 2026-04-24 after silent revert by #668 (4-minute merge-race
# with #663). See hotfix commit message + post-mortem issue for detail.
import re as _re_424
_TELEGRAM_TOKEN_RE = _re_424.compile(r"/bot([0-9]+:[A-Za-z0-9_\-]+)")


def _redact_token(text) -> str:
    """Replace any embedded Telegram bot token with [REDACTED].

    Accepts a string OR an Exception instance. Returns a string safe
    to log. Use in EVERY except-block log call inside this module."""
    s = str(text) if not isinstance(text, str) else text
    return _TELEGRAM_TOKEN_RE.sub("/bot[REDACTED]", s)


def _html_escape(text) -> str:
    """HTML-escape user-controlled string fields. None-safe, str-coercing."""
    if text is None:
        return ""
    s = text if isinstance(text, str) else str(text)
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# Module-level dispatch map — single source of truth for known event types (T12 D3).
# _KNOWN_EVENT_TYPES is derived from this dict so the two representations
# can never diverge. safe_send uses _EVENT_MAP directly.
# Populated after notify_* functions are defined (see bottom of function-def block).
_EVENT_MAP: dict = {}  # filled in at module load after function definitions

# Derived from _EVENT_MAP after it is populated.  Do NOT edit this line —
# it is assigned once the dict is populated below.
_KNOWN_EVENT_TYPES: frozenset = frozenset()  # overwritten after _EVENT_MAP is built


def is_telegram_enabled() -> bool:
    """Check if Telegram notifications are configured and enabled."""
    cfg = _get_telegram_config()
    return cfg["enabled"] and bool(cfg["bot_token"]) and bool(cfg["chat_id"])


_TELEGRAM_CHUNK_SIZE = 4000


def _send_single(cfg: dict, text: str, parse_mode: str) -> bool:
    """Send one message chunk. Returns True on success, False on failure."""
    try:
        url = TELEGRAM_API.format(token=cfg["bot_token"])
        resp = requests.post(
            url,
            json={
                "chat_id": cfg["chat_id"],
                "text": text,
                "parse_mode": parse_mode,
                "disable_web_page_preview": True,
            },
            timeout=10,
        )
        if resp.status_code == 200:
            return True
        logger.warning(
            "[TELEGRAM] Send failed: %s %s",
            resp.status_code, _redact_token(resp.text[:200]),
        )
        return False
    except Exception as e:
        logger.warning("[TELEGRAM] Send error: %s", _redact_token(e))
        return False


def send_telegram(message: str, parse_mode: str = "HTML") -> bool:
    """Send a message via Telegram Bot API.

    Messages longer than 4000 characters are split into chunks with
    [chunk N/M] markers appended to each part.

    Args:
        message: Text to send (supports HTML formatting)
        parse_mode: "HTML" or "Markdown"

    Returns True on success, False on failure.
    """
    cfg = _get_telegram_config()
    if not cfg["enabled"] or not cfg["bot_token"] or not cfg["chat_id"]:
        return False

    if len(message) <= _TELEGRAM_CHUNK_SIZE:
        return _send_single(cfg, message, parse_mode)

    chunks = [
        message[i: i + _TELEGRAM_CHUNK_SIZE]
        for i in range(0, len(message), _TELEGRAM_CHUNK_SIZE)
    ]
    total = len(chunks)

    # Try HTML chunked first; if any chunk returns 400 (tag-tearing), retry all as plaintext.
    html_failed = False
    for idx, chunk in enumerate(chunks, start=1):
        tagged = f"{chunk}\n[chunk {idx}/{total}]"
        if not _send_single(cfg, tagged, parse_mode):
            html_failed = True
            break

    if not html_failed:
        return True

    # Plaintext fallback — strips any HTML tags that may have been torn by chunking.
    ok = True
    for idx, chunk in enumerate(chunks, start=1):
        tagged = f"{chunk}\n[chunk {idx}/{total}]"
        if not _send_single(cfg, tagged, None):
            ok = False
    return ok


# ── Delivery layer (notify_* + payload dataclasses) ───────────────────────
# Phase 5 PR-C T11 (§3 + DD-08c): the pre-formatted alert builders and their
# typed payload dataclasses live in src/notifications/telegram_delivery.py to
# keep this module under the structure-debt cap. They are re-imported here so
# that existing imports and test patches at src.notifications.telegram.<name>
# continue to resolve, and so _EVENT_MAP_MUTABLE below can reference them.
# The delivery module calls back into this module's transport (send_telegram,
# _send_single, _html_escape) via a late-bound module reference, so the
# conftest null-router patch on telegram._send_single still neutralizes every
# send path regardless of which module the notify_* caller lives in.
from src.notifications.telegram_delivery import (  # noqa: E402
    TradeOpenedPayload,
    TradeClosedPayload,
    EodReportPayload,
    WeeklyDigestPayload,
    notify_trade_opened,
    notify_trade_closed,
    notify_scan_complete,
    notify_risk_alert,
    notify_earnings_warning,
    notify_overnight_complete,
    notify_system_event,
    notify_startup_complete,
    notify_daily_summary,
    notify_model_event,
    notify_watchlist,
    notify_scan_result,
    notify_premarket_complete,
    notify_gpu_health,
    notify_overnight_training_complete,
    notify_scoring_summary,
    notify_schedule_health,
    notify_premarket_brief,
    notify_trainer_holdout_empty,
    notify_first_scan_summary,
    notify_eod_report,
    notify_data_asset_report,
    notify_regime_alert,
    notify_milestone,
    notify_streak_alert,
    notify_weekly_digest,
    notify_retrain_report,
    notify_research_papers,
    notify_research_digest,
    notify_collection_failure,
    notify_exposure_alert,
    notify_position_earnings_warning,
    notify_action_required,
    notify_validation_summary,
    notify_1min_bar_collection,
    notify_attribution_resolve_complete,
    notify_stress_test_complete,
    notify_trading_stats_update,
    notify_manual_intervention_drift,
    notify_alert_silence,
    notify_audit_critical_email_only,
    notify_audit_alert_email_only,
    notify_audit_red_assessment_email_only,
    notify_morning_watchlist_email_only,
    notify_action_packet_email_only,
    notify_eod_recap_email_email_only,
    notify_premarket_content_email_only,
    notify_midday_content_email_only,
    notify_eod_content_email_only,
    notify_evening_content_email_only,
    notify_weekly_digest_content_email_only,
    notify_saturday_training_report_email_only,
    notify_saturday_cto_report_email_only,
    notify_research_synthesis_email_email_only,
)


def _write_notification_sent(
    event_type: str,
    channel: str,
    status: str,
    error_msg: str | None = None,
    recipient: str | None = None,
    conn=None,
) -> None:
    """Persist a dispatch outcome row to notifications_sent.

    Silently logs on any DB error — persistence must never crash the notification path.
    ``conn`` is accepted for testing (in-memory SQLite); production uses src.config.DB_PATH.
    """
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    _own_conn = conn is None
    try:
        if conn is None:
            from src.utils.db import connect_db
            from src.config import DB_PATH
            conn = connect_db(DB_PATH)
        conn.execute(
            "INSERT INTO notifications_sent"
            " (event_type, channel, recipient, sent_at, status, retry_count, error_msg)"
            " VALUES (?, ?, ?, ?, ?, 0, ?)",
            (event_type, channel, recipient, now, status, error_msg),
        )
        conn.commit()
    except Exception:
        logger.debug("[NOTIFICATIONS] _write_notification_sent failed silently", exc_info=True)
    finally:
        if _own_conn and conn is not None:
            try:
                conn.close()
            except Exception:
                pass


def _record_send_failure(event_type: str, error_msg: str) -> None:
    """Persist a failed dispatch to notifications_sent (T15 implementation)."""
    error_msg = _redact_token(error_msg)
    _write_notification_sent(event_type=event_type, channel="telegram", status="failed", error_msg=error_msg)
    logger.debug(
        "[NOTIFICATIONS] dispatch_failed event=%s err=%s",
        event_type, error_msg,
    )


def _check_nested_bypass_severity(notif_section: dict, path: str = "notifications") -> None:
    """Recursive walk; raise NotificationsConfigError if 'bypass_severity' key found anywhere."""
    from src.notifications.errors import NotificationsConfigError
    if not isinstance(notif_section, dict):
        return
    if "bypass_severity" in notif_section:
        raise NotificationsConfigError(
            f"Decision 20 lockdown: 'bypass_severity' key found at {path}.bypass_severity. "
            f"This knob does not exist in the v2 policy — rule #1 (severity in {{high, critical}}) "
            f"IS the bypass. Remove the key entirely."
        )
    for key, value in notif_section.items():
        if isinstance(value, dict):
            _check_nested_bypass_severity(value, f"{path}.{key}")


_ALLOWED_ROUTING_OVERRIDE_KEYS = frozenset({"telegram", "email", "escalation_after_attempts"})

# Import should_dispatch at module level so tests can patch it via
# `patch("src.notifications.telegram.should_dispatch", ...)`.
from src.notifications.policy import should_dispatch  # noqa: E402


def _load_notifications_config(yaml_path: str):
    """Load and validate the notifications: section from a YAML settings file.

    Returns a NotificationsConfig dataclass on success.
    Raises NotificationsConfigError with a specific message on any violation.
    """
    import yaml as _yaml
    from src.notifications.errors import NotificationsConfigError
    from src.notifications.policy import NotificationsConfig

    with open(yaml_path, encoding="utf-8") as fh:
        raw = _yaml.safe_load(fh)

    notif = (raw or {}).get("notifications", {}) or {}

    if "bypass_severity" in notif:
        raise NotificationsConfigError(
            "bypass_severity key is forbidden (Decision 20). "
            "Severity high/critical always sends; this knob was explicitly removed."
        )

    _check_nested_bypass_severity(notif)

    for evt, override in (notif.get("routing_overrides") or {}).items():
        if not isinstance(override, dict):
            raise NotificationsConfigError(
                f"routing_overrides[{evt!r}] must be a dict, got {type(override).__name__}"
            )
        unknown_keys = set(override.keys()) - _ALLOWED_ROUTING_OVERRIDE_KEYS
        if unknown_keys:
            raise NotificationsConfigError(
                f"routing_overrides[{evt!r}] has unknown key(s): {sorted(unknown_keys)!r}. "
                f"Allowed: {sorted(_ALLOWED_ROUTING_OVERRIDE_KEYS)!r}. "
                f"Typo? Missing channel? Add to allowlist if intentional."
            )

    for tstr, label in [
        (notif.get("quiet_hours_start", "22:00"), "quiet_hours_start"),
        (notif.get("quiet_hours_end", "06:00"), "quiet_hours_end"),
    ]:
        try:
            parts = str(tstr).split(":")
            if len(parts) != 2:
                raise ValueError
            h, m = int(parts[0]), int(parts[1])
            if not (0 <= h <= 23 and 0 <= m <= 59):
                raise ValueError
        except (ValueError, AttributeError):
            raise NotificationsConfigError(
                f"quiet_hours: {label}={tstr!r} is not a valid HH:MM string."
            )

    for evt, minutes in (notif.get("cadence_minutes_per_event_type") or {}).items():
        if evt not in _KNOWN_EVENT_TYPES:
            raise NotificationsConfigError(
                f"cadence_minutes_per_event_type: unknown event_type {evt!r}. "
                "Must be registered in src.notifications.telegram._EVENT_MAP."
            )
        if not (1 <= int(minutes) <= 1440):
            raise NotificationsConfigError(
                f"cadence_minutes_per_event_type[{evt!r}]={minutes}: "
                "must be in range [1, 1440]."
            )

    for evt in (notif.get("routing_overrides") or {}):
        if evt not in _KNOWN_EVENT_TYPES:
            raise NotificationsConfigError(
                f"routing_overrides: unknown event_type {evt!r}. "
                "Must be registered in src.notifications.telegram _EVENT_MAP."
            )

    retry = notif.get("retry") or {}
    attempts = int(retry.get("attempts", 3))
    if not (1 <= attempts <= 10):
        raise NotificationsConfigError(
            f"retry.attempts={attempts}: must be in range [1, 10]."
        )
    backoff = list(retry.get("backoff_seconds", []))
    if len(backoff) != attempts:
        raise NotificationsConfigError(
            f"retry.backoff_seconds has {len(backoff)} entries but "
            f"retry.attempts={attempts}; lengths must match."
        )

    digest_flush_minutes = int(notif.get("digest_flush_minutes", 60))
    if not (5 <= digest_flush_minutes <= 1440):
        raise NotificationsConfigError(
            f"digest_flush_minutes={digest_flush_minutes}: must be in range [5, 1440]."
        )

    return NotificationsConfig(
        default_routing=notif.get("default_routing") or {"telegram": True, "email": False},
        digest_low=bool(notif.get("digest_low", True)),
        quiet_hours_start=str(notif.get("quiet_hours_start", "22:00")),
        quiet_hours_end=str(notif.get("quiet_hours_end", "06:00")),
        quiet_digest=bool(notif.get("quiet_digest", True)),
        mute_event_types=list(notif.get("mute_event_types") or []),
        routing_overrides=dict(notif.get("routing_overrides") or {}),
        cadence_minutes_per_event_type=dict(notif.get("cadence_minutes_per_event_type") or {}),
        retry_attempts=attempts,
        retry_backoff_seconds=backoff,
        digest_flush_minutes=digest_flush_minutes,
    )


# ── Email-tier event_type stubs (Sprint #115 T4 — DD-24 + DD-26) ──────────
# Email-tier events are dispatched through src.notifications.email_digest.
# They are registered in _EVENT_MAP_MUTABLE below ONLY so DigestQueue.enqueue
# (which validates event_type membership against _KNOWN_EVENT_TYPES) accepts
# them. Invoking any of these stubs through the Telegram path is a routing
# bug — the stub raises NotImplementedError to surface it loudly.
#
# Tuple of (event_type, stub_function_name) pairs. The frozenset
# EMAIL_TIER_EVENT_TYPES is published below as the public allowlist.

EMAIL_TIER_EVENT_TYPES: frozenset[str] = frozenset({
    "audit_critical",
    "audit_alert",
    "audit_red_assessment",
    "morning_watchlist",
    "action_packet",
    "eod_recap_email",
    "premarket_content",
    "midday_content",
    "eod_content",
    "evening_content",
    "weekly_digest_content",
    "saturday_training_report",
    "saturday_cto_report",
    "research_synthesis_email",
})


# _email_tier_stub_error + the 14 notify_*_email_only stubs are defined in
# src/notifications/telegram_delivery.py and re-imported above (T11). The
# EMAIL_TIER_EVENT_TYPES allowlist stays here as the public contract.


# ── Module-level event map (T12 D3 consolidation) ─────────────────────────
# Single source of truth. _KNOWN_EVENT_TYPES is derived here so the two
# representations can never diverge. Place after all notify_* functions.

_EVENT_MAP_MUTABLE: dict = {
    # Trade lifecycle
    "trade_opened": notify_trade_opened,
    "trade_closed": notify_trade_closed,
    # Scan & pipeline
    "scan_complete": notify_scan_complete,
    "scan_result": notify_scan_result,
    "first_scan_summary": notify_first_scan_summary,
    "watchlist": notify_watchlist,
    "premarket_complete": notify_premarket_complete,
    "premarket_brief": notify_premarket_brief,
    # System & risk alerts
    "risk_alert": notify_risk_alert,
    "system_event": notify_system_event,
    "startup_complete": notify_startup_complete,
    "validation_summary": notify_validation_summary,
    "collection_failure": notify_collection_failure,
    "exposure_alert": notify_exposure_alert,
    "regime_alert": notify_regime_alert,
    # Overnight & scheduling
    "overnight_complete": notify_overnight_complete,
    "overnight_training_complete": notify_overnight_training_complete,
    "gpu_health": notify_gpu_health,
    "scoring_summary": notify_scoring_summary,
    "schedule_health": notify_schedule_health,
    # Periodic reports
    "daily_summary": notify_daily_summary,
    "eod_report": notify_eod_report,
    "data_asset_report": notify_data_asset_report,
    "weekly_digest": notify_weekly_digest,
    "retrain_report": notify_retrain_report,
    "research_papers": notify_research_papers,
    "research_digest": notify_research_digest,
    # Milestones & alerts
    "milestone": notify_milestone,
    "streak_alert": notify_streak_alert,
    "earnings_warning": notify_earnings_warning,
    "position_earnings_warning": notify_position_earnings_warning,
    "model_event": notify_model_event,
    # Action reminders
    "action_required": notify_action_required,
    # Training & data
    "trainer_holdout_empty": notify_trainer_holdout_empty,
    "1min_bar_collection": notify_1min_bar_collection,
    "attribution_resolve_complete": notify_attribution_resolve_complete,
    "stress_test_complete": notify_stress_test_complete,
    "trading_stats_update": notify_trading_stats_update,
    # Monitoring (Wave C T4)
    "manual_intervention_drift": notify_manual_intervention_drift,
    # Monitoring (Wave D T14 D5)
    "alert_silence": notify_alert_silence,
    # ── Email-tier event_types (Sprint #115 T4 — DD-24 + DD-26) ───────────
    # These events are NEVER dispatched via Telegram. The stub mappings exist
    # only so DigestQueue.enqueue accepts them (the queue validates against
    # _KNOWN_EVENT_TYPES which is derived from _EVENT_MAP below). Actual
    # delivery flows through src.notifications.email_digest.flush_tier().
    # Each stub raises NotImplementedError if invoked through the Telegram
    # path so misrouted events fail loudly rather than silently no-op.
    "audit_critical": notify_audit_critical_email_only,
    "audit_alert": notify_audit_alert_email_only,
    "audit_red_assessment": notify_audit_red_assessment_email_only,
    "morning_watchlist": notify_morning_watchlist_email_only,
    "action_packet": notify_action_packet_email_only,
    "eod_recap_email": notify_eod_recap_email_email_only,
    "premarket_content": notify_premarket_content_email_only,
    "midday_content": notify_midday_content_email_only,
    "eod_content": notify_eod_content_email_only,
    "evening_content": notify_evening_content_email_only,
    "weekly_digest_content": notify_weekly_digest_content_email_only,
    "saturday_training_report": notify_saturday_training_report_email_only,
    "saturday_cto_report": notify_saturday_cto_report_email_only,
    "research_synthesis_email": notify_research_synthesis_email_email_only,
}
_EVENT_MAP = MappingProxyType(_EVENT_MAP_MUTABLE)

# Overwrite the placeholder frozenset now that _EVENT_MAP is populated.
_KNOWN_EVENT_TYPES = frozenset(_EVENT_MAP)

# CC3: payload-type events pass a single `payload` positional argument.
_PAYLOAD_EVENTS = frozenset({"trade_opened", "trade_closed", "eod_report", "weekly_digest"})

# Maps event_type -> dataclass class for round-trip reconstruction after json.loads.
_PAYLOAD_CLASS_MAP = {
    "trade_opened": TradeOpenedPayload,
    "trade_closed": TradeClosedPayload,
    "eod_report": EodReportPayload,
    "weekly_digest": WeeklyDigestPayload,
}


# ── Testability hooks (replaced in tests via patch) ───────────────────────

def _load_config_for_safe_send():
    """Return the active NotificationsConfig. Replaced in tests via patch."""
    from src.config import load_config
    import os
    cfg_path = os.environ.get("ARCIS_SETTINGS_PATH", "config/settings.local.yaml")
    if not os.path.exists(cfg_path):
        cfg_path = "config/settings.yaml"
    if not os.path.exists(cfg_path):
        cfg_path = "config/settings.example.yaml"
    return _load_notifications_config(cfg_path)


def _now_et_for_safe_send():
    """Return current datetime in Eastern TZ. Replaced in tests via patch."""
    return datetime.now(ET)


def _get_digest_db_conn():
    """Return a DB connection for digest queue enqueue. Replaced in tests via patch."""
    from src.utils.db import connect_db
    from src.config import DB_PATH
    return connect_db(DB_PATH)


def _resolve_source_tag() -> str:
    """Return a caller source tag for digest queue rows."""
    return "safe_send"


# ── Dispatch helpers ──────────────────────────────────────────────────────

def _do_dispatch(event_type: str, payload: dict, severity: str, channels: list) -> bool:
    """Dispatch a single notification via the appropriate notify_* function.

    Called for SEND verdict (not escalate). payload is the kwargs dict from the
    original safe_send call. Does NOT re-gate through should_dispatch.
    Looks up _EVENT_MAP at call time so that test patches on notify_* take effect.
    """
    import sys
    _mod = sys.modules[__name__]
    # Re-resolve the function through the module to respect test patches.
    fn_name = _EVENT_MAP[event_type].__name__
    notify_fn = getattr(_mod, fn_name, _EVENT_MAP[event_type])
    try:
        if event_type in _PAYLOAD_EVENTS:
            payload_obj = payload["payload"]
            if isinstance(payload_obj, dict):
                payload_obj = _PAYLOAD_CLASS_MAP[event_type](**payload_obj)
            result = notify_fn(payload_obj)
        else:
            result = notify_fn(**payload)
        _write_notification_sent(event_type=event_type, channel="telegram", status="ok")
        return bool(result)
    except (
        urllib3.exceptions.HTTPError,
        requests.exceptions.RequestException,
        socket.timeout,
        OSError,
    ) as e:
        logger.warning(
            "[NOTIFICATIONS] %s dispatch failed (network): %s",
            event_type, _redact_token(e),
        )
        _record_send_failure(event_type, _redact_token(e))
        return False


def _do_dispatch_escalated(event_type: str, payload: dict, severity: str, channels: list) -> bool:
    """Dispatch an escalated notification (all configured channels, sequential).

    For the escalate verdict: attempt each channel in order; return True if any
    channel succeeds. Design choice: sequential (not parallel) because failure
    visibility is more important than throughput for escalated alerts.
    """
    success = False
    if "telegram" in channels:
        success = _do_dispatch(event_type, payload, severity, ["telegram"]) or success
    if "email" in channels:
        try:
            from src.email.notifier import send_email
            subject = f"[ESCALATED] {event_type}"
            redacted_repr = _redact_token(repr(payload))[:1024]
            body = (
                f"Escalated notification: {event_type}\n"
                f"Severity: {severity}\n"
                f"Payload (redacted, truncated to 1024 chars): {redacted_repr}\n"
                f"\nForensic detail: SELECT * FROM notifications_sent WHERE event_type = '{event_type}' "
                f"ORDER BY sent_at DESC LIMIT 1;"
            )
            # NOTE: This is a CARVE-OUT — Telegram-failure escalation must fire email IMMEDIATELY.
            # Do NOT route through src.notifications.email_digest.enqueue_for_email_digest() — see #115 DD-14.
            email_ok = send_email(subject=subject, body=body)
            # Audit-trail row with distinguishable event_type='escalated_telegram_fail' so the
            # escalation carve-out is queryable independently of send_email's internal 'email_send' row.
            _write_notification_sent(
                event_type="escalated_telegram_fail",
                channel="email",
                status="ok" if email_ok else "failed",
                error_msg=None if email_ok else f"send_email returned False for {event_type}",
            )
            if email_ok:
                success = True
        except (
            urllib3.exceptions.HTTPError,
            requests.exceptions.RequestException,
            socket.timeout,
            OSError,
        ) as e:
            logger.warning(
                "[NOTIFICATIONS] escalated email failed for %s: %s",
                event_type, _redact_token(str(e)),
            )
    if not channels:
        success = _do_dispatch(event_type, payload, severity, ["telegram"]) or success
    return success


# ── Central dispatcher (T12 D3 verdict-dispatch rewrite) ─────────────────

def safe_send(event_type: str, *, force: bool = False, **kwargs) -> bool:
    """Central dispatcher for notify_* functions, now routed through the policy gate.

    Consults should_dispatch(event_type, severity, now_et, config) and branches
    on the PolicyDecision.verdict:
      - send     → _do_dispatch (normal path)
      - digest   → DigestQueue.enqueue (buffered path)
      - mute     → log + return False (silent drop)
      - escalate → _do_dispatch_escalated (all channels, sequential)

    force=True overrides the policy gate and always sends via telegram.

    Design principle: catch ONLY genuine network failures. Let ImportError /
    NameError / AttributeError propagate so import-time bugs surface at startup,
    not silently at runtime. (Sprint 4 T2 / overnight.py incident: both a
    NameError and an ImportError in the alarm path were swallowed for months.)

    Args:
        event_type: registered key in _EVENT_MAP. KeyError on unknown — intentional.
        force:      bypass policy gate, always send.
        **kwargs:   passed through to the resolved notify_* function, PLUS
                    optional `severity` key (default 'normal').

    Returns:
        True if dispatch succeeded or was queued; False if disabled, muted, or
        transient network failure.

    Raises:
        ImportError, NameError, AttributeError, KeyError — propagated.

    SECURITY: `event_type` MUST be a hardcoded string literal at the call site.
    Never wire it to user input or external request payloads.
    """
    if not is_telegram_enabled():
        return False

    _EVENT_MAP[event_type]  # KeyError if unknown — intentional, keep before policy gate

    severity = kwargs.pop("severity", "normal")

    from src.notifications.policy import PolicyDecision

    config = None
    if force:
        logger.info(
            "[NOTIFICATIONS] force_bypass: event_type=%s severity=%s",
            event_type, severity,
        )
        decision = PolicyDecision(
            verdict="send",
            reason="force_bypass",
            channels=["telegram"],
            matched_rule=0,
        )
    else:
        try:
            config = _load_config_for_safe_send()
        except Exception:
            config = None

        if config is not None:
            now_et = _now_et_for_safe_send()
            decision = should_dispatch(event_type, severity, now_et, config)
        else:
            decision = PolicyDecision(
                verdict="send",
                reason="no_config",
                channels=["telegram"],
                matched_rule=0,
            )

    if decision.verdict == "send":
        return _do_dispatch(event_type, kwargs, severity, decision.channels)
    elif decision.verdict == "digest":
        try:
            from src.notifications.digest_queue import DigestQueue
            with _get_digest_db_conn() as conn:
                q = DigestQueue(conn, config=config)
                q.enqueue(
                    event_type=event_type,
                    severity=severity,
                    payload=kwargs,
                    source_tag=_resolve_source_tag(),
                )
            return True
        except (
            urllib3.exceptions.HTTPError,
            requests.exceptions.RequestException,
            socket.timeout,
            OSError,
        ) as e:
            logger.warning("[NOTIFICATIONS] digest enqueue failed for %s: %s", event_type, e)
            return False
    elif decision.verdict == "mute":
        logger.info("[NOTIFICATIONS] %s muted (%s)", event_type, decision.reason)
        return False
    elif decision.verdict == "escalate":
        return _do_dispatch_escalated(event_type, kwargs, severity, decision.channels)
    else:
        return _do_dispatch(event_type, kwargs, severity, decision.channels)


# Backward compatibility — remove after all callers are updated
try:
    from src.notifications.telegram_commands import (
        poll_commands, handle_command, check_action_reminders
    )
except ImportError:
    pass
