"""Email-tier aggregator (#115 T5 — DD-15/17/27/28/29/30/32/33/34).

Aggregates email-bound events into three tiers: preopen (07:30 ET weekday),
postclose (17:00 ET weekday), weekly (Sun 18:00 ET).

Called by: src.evaluation.auditor, src.scheduler.{overnight,reports,watch},
           src.services.{scan_service,recap_service,watchlist_service}, src.cli
Calls:     src.notifications.digest_queue.DigestQueue, src.email.notifier.send_email,
           src.notifications.email_digest_render, src.notifications.email_digest_handover
Owns tables: none (re-uses notifications_digest_queue via DigestQueue)
Config keys: email.tier_times.*, email.tiers.*.{enabled,send_when_empty},
             email.dual_write_hold_over.{mode,shadow_output_dir}, email.holidays.skip_*
Tests:     tests/notifications/test_email_digest_module.py

Architecture (DD-29 + Phase 5 PR-C T16): orchestrator module — EVENT_TO_TIER
routing dict + the queue-facing public functions (enqueue_for_email_digest,
flush_tier) + the dispatch/flush private helpers. Rendering moved to
email_digest_render.py and hold-over exit-criteria to email_digest_handover.py;
render_digest / preview_tier / handover_check are re-exported here so the
public API and all `from src.notifications.email_digest import ...` call sites
are byte-for-byte unchanged. Module-load fail-fast (DD-30 + DA-MIN-19) uses
ImportError (not assert) so caller try/except catches drift correctly.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

from src.config import load_config
from src.email.notifier import send_email
from src.notifications.digest_queue import DigestQueue, FlushResult
from src.notifications.telegram import EMAIL_TIER_EVENT_TYPES

# Re-exported public API (Phase 5 PR-C T16 split — preserve import paths).
from src.notifications.email_digest_render import (  # noqa: F401
    render_digest,
    preview_tier,
    _collect_preopen_critical_replays,
)
from src.notifications.email_digest_handover import (  # noqa: F401
    handover_check,
    _open_handover_conn,
)

logger = logging.getLogger(__name__)

TierName = Literal["preopen", "postclose", "weekly"]

_ET = ZoneInfo("America/New_York")


# Routing matrix (DD-29 — load-bearing). Section 5 of design spec.
# audit_critical is hybrid (DD-01): ALSO fires immediately.
EVENT_TO_TIER: dict[str, TierName] = {
    "audit_critical":            "preopen",
    "audit_alert":               "postclose",
    "audit_red_assessment":      "postclose",
    "morning_watchlist":         "preopen",
    "action_packet":             "postclose",
    "eod_recap_email":           "postclose",
    "premarket_content":         "preopen",
    "midday_content":            "postclose",
    "eod_content":               "postclose",
    "evening_content":           "postclose",
    "weekly_digest_content":     "weekly",
    "saturday_training_report":  "weekly",
    "saturday_cto_report":       "weekly",
    "research_synthesis_email":  "weekly",
}

# Carve-outs: bypass queue (DD-14) or hybrid (DD-01).
CARVE_OUT_TYPES: frozenset[str] = frozenset({
    "audit_critical",            # hybrid: immediate + queued
    "escalated_telegram_fail",   # immediate-only
})

# Module-load fail-fast (DD-30 revised + DA-MIN-19): drift surfaces as
# ImportError, not AssertionError, so caller try/except catches it. True
# render-time AssertionError still surfaces loudly (not silenced).
_drift = set(EVENT_TO_TIER.keys()) - set(EMAIL_TIER_EVENT_TYPES)
if _drift:
    raise ImportError(
        f"email_digest module-load drift: EVENT_TO_TIER contains event_types "
        f"not in telegram.EMAIL_TIER_EVENT_TYPES: {_drift!r}"
    )
del _drift


def _default_notifications_config():
    """Build the minimal NotificationsConfig used by DigestQueue."""
    from src.notifications.policy import NotificationsConfig
    return NotificationsConfig(
        default_routing={"telegram": True, "email": False},
        digest_low=True,
        quiet_hours_start="22:00",
        quiet_hours_end="06:00",
        quiet_digest=True,
        mute_event_types=[],
        routing_overrides={},
        cadence_minutes_per_event_type={},
        retry_attempts=3,
        retry_backoff_seconds=[1, 5, 15],
    )


# ── Public functions ──────────────────────────────────────────────────────

def enqueue_for_email_digest(
    event_type: str,
    *,
    severity: str,
    payload: dict,
    source_tag: str | None = None,
    conn=None,
    now_et=None,
    config=None,
) -> int | None:
    """Enqueue an email-bound event to the appropriate tier (DD-28).

    Raises KeyError if event_type is not in EVENT_TO_TIER (no silent default
    tier — every emit MUST declare its tier).

    source_tag defaults to f'email:{tier}'. Callers MAY supply a sub-tag
    (e.g. 'email:preopen:critical-overflow' for the hybrid CRITICAL marker —
    DD-17 revised + DD-34).
    """
    tier = EVENT_TO_TIER[event_type]  # raises KeyError per DD-28
    if source_tag is None:
        source_tag = f"email:{tier}"
    if config is None:
        config = _default_notifications_config()
    queue = DigestQueue(conn, config=config)
    return queue.enqueue(
        event_type=event_type,
        severity=severity,
        payload=payload,
        source_tag=source_tag,
    )


def flush_tier(
    tier: TierName,
    *,
    db_path: str | None = None,
    now_et=None,
    conn=None,
) -> FlushResult:
    """Drain queue rows for `tier`, render, and dispatch — OR shadow-write only.

    Modes: shadow → _write_shadow_file only; off/time_aligned → real send_email.
    Empty-suppression (DD-33): if rows + replays = 0 and send_when_empty=False,
    write a dedup-suppressed marker row and return without sending.
    """
    cfg = load_config() or {}
    email_cfg = cfg.get("email", {})
    holdover = email_cfg.get("dual_write_hold_over", {}) or {}
    mode = holdover.get("mode", "shadow")
    shadow_dir = holdover.get("shadow_output_dir", "tmp/digest-shadow")
    top_k = int((email_cfg.get("digest_truncation", {}) or {}).get("top_k_per_section", 10))

    if _should_skip_on_holiday(tier, email_cfg):
        logger.info("[digest] tier=%s suppressed: market holiday", tier)
        return FlushResult(successes=0, failures=0, abandoned=0)

    rows = _fetch_pending_tier_rows(tier, conn=conn) if conn is not None else []
    replays = (
        _collect_preopen_critical_replays(conn)
        if (tier == "preopen" and conn is not None) else []
    )

    if tier in ("preopen", "postclose") and _check_empty_suppression(
        tier, len(rows), len(replays), cfg,
    ):
        logger.info("[digest] tier=%s suppressed: empty", tier)
        _write_suppressed_dedup(tier, conn=conn)
        return FlushResult(successes=0, failures=0, abandoned=0)

    subject, plain, html, overflow_ids = render_digest(
        tier, rows=rows, db_path=db_path, now_et=now_et, top_k=top_k, conn=conn,
    )
    included_ids = [r["id"] for r in rows if r["id"] not in overflow_ids]

    if mode == "shadow":
        _write_shadow_file(tier, subject, plain, html, output_dir=shadow_dir)
        return FlushResult(successes=len(included_ids), failures=0, abandoned=0)

    _dispatch_tier(
        tier, subject, plain, html, included_ids, overflow_ids,
        db_path=db_path, conn=conn,
    )
    return FlushResult(successes=len(included_ids), failures=0, abandoned=0)


# ── Private helpers ───────────────────────────────────────────────────────

def _should_skip_on_holiday(tier: TierName, email_cfg: dict) -> bool:
    """DD-23: True iff preopen/postclose should suppress on a full NYSE closure.

    Weekly is calendar-based, never suppressed. ImportError on the holidays
    module is swallowed (best-effort) so missing market-calendar data does
    not crash the digest.
    """
    if tier not in ("preopen", "postclose"):
        return False
    holidays_cfg = (email_cfg or {}).get("holidays", {}) or {}
    if not holidays_cfg.get(f"skip_{tier}_on_market_holidays", True):
        return False
    try:
        from src.scheduler.holidays import is_market_holiday
        return bool(is_market_holiday())
    except ImportError:
        return False


def _fetch_pending_tier_rows(tier: TierName, *, conn=None) -> list[dict]:
    """Read pending rows for a tier directly from the queue table.

    Aggregate-then-dispatch (DD-27): flush_tier reads rows itself to render
    a single digest body. The colon-delimited match (DD-35 / DA-MAJ-9) means
    'email:preopen' captures BOTH 'email:preopen' AND 'email:preopen:*' rows.
    """
    if conn is None:
        return []
    tag = f"email:{tier}"
    rows = conn.execute(
        "SELECT id, event_type, severity, payload_json, source_tag, flush_attempts "
        "FROM notifications_digest_queue "
        "WHERE flush_status='pending' "
        "  AND (source_tag = ? OR source_tag LIKE ? || ':%') "
        "ORDER BY created_at ASC",
        (tag, tag),
    ).fetchall()
    out = []
    for r in rows:
        try:
            payload = json.loads(r["payload_json"])
        except Exception:
            payload = {}
        out.append({
            "id": r["id"],
            "event_type": r["event_type"],
            "severity": r["severity"],
            "source_tag": r["source_tag"],
            "flush_attempts": r["flush_attempts"],
            "payload": payload,
        })
    return out


def _dispatch_tier(
    tier: TierName,
    subject: str,
    plain: str,
    html: str,
    included_ids: list[int],
    overflow_ids: list[int],
    *,
    db_path: str | None = None,
    conn=None,
) -> bool:
    """Send the rendered digest via send_email and mark included rows sent.

    DA-CRIT-2: overflow_ids are NOT marked sent here — they remain pending
    OR are written to an overflow attachment (per overflow_strategy config).
    Task 6 implements attachment payload-building; T5's stub sends with none.
    """
    attachments: list[tuple[str, bytes]] | None = None
    ok = send_email(subject, plain, html_body=html, attachments=attachments)
    if ok and conn is not None and included_ids:
        now = datetime.now(timezone.utc).isoformat()
        placeholders = ",".join("?" for _ in included_ids)
        conn.execute(
            f"UPDATE notifications_digest_queue "
            f"SET flush_status='sent', flushed_at=? "
            f"WHERE id IN ({placeholders})",
            (now, *included_ids),
        )
        conn.commit()
    return bool(ok)


def _write_shadow_file(
    tier: TierName,
    subject: str,
    plain: str,
    html: str,
    output_dir: str,
) -> tuple[Path, Path]:
    """Write the rendered digest to <output_dir>/<tier>-<YYYY-MM-DD>.{html,txt}.

    Creates output_dir if missing. Uses encoding='utf-8' (operator memory:
    Python's open() defaults to cp1252 on Windows and corrupts non-ASCII).
    """
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    date_str = datetime.now().strftime("%Y-%m-%d")
    html_file = out_path / f"{tier}-{date_str}.html"
    txt_file = out_path / f"{tier}-{date_str}.txt"
    html_payload = f"<!-- Subject: {subject} -->\n{html}"
    txt_payload = f"Subject: {subject}\n\n{plain}"
    with open(html_file, "w", encoding="utf-8") as f:
        f.write(html_payload)
    with open(txt_file, "w", encoding="utf-8") as f:
        f.write(txt_payload)
    return html_file, txt_file


def _check_empty_suppression(
    tier: TierName,
    included_count: int,
    replay_count: int,
    config: dict,
) -> bool:
    """DD-33: True if empty-tier suppression should fire (don't send email).

    Suppress when: zero events queued AND zero critical replays AND
    config.email.tiers.<tier>.send_when_empty == False.
    """
    if included_count > 0 or replay_count > 0:
        return False
    email_cfg = (config or {}).get("email", {})
    tier_cfg = (email_cfg.get("tiers", {}) or {}).get(tier, {}) or {}
    return tier_cfg.get("send_when_empty", False) is False


def _write_suppressed_dedup(tier: TierName, *, conn) -> None:
    """DD-33: write a notifications_dedup row marking this tier as suppressed.

    Uses event_type='digest_suppressed_empty' with dedup_key=
    'email:<tier>:YYYY-MM-DD:suppressed-empty'. UNIQUE(event_type, dedup_key)
    means re-attempts within the same day are no-ops (idempotent).
    """
    if conn is None:
        return
    date_str = datetime.now(_ET).strftime("%Y-%m-%d")
    dedup_key = f"email:{tier}:{date_str}:suppressed-empty"
    now = datetime.now(timezone.utc).isoformat()
    try:
        conn.execute(
            "INSERT OR IGNORE INTO notifications_dedup "
            "(event_type, dedup_key, sent_at) VALUES (?, ?, ?)",
            ("digest_suppressed_empty", dedup_key, now),
        )
        conn.commit()
    except Exception as e:  # table missing → best-effort, log + swallow
        logger.warning(
            "[digest] tier=%s could not write suppressed-dedup row: %s",
            tier, e,
        )
