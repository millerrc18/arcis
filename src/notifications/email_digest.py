"""Email-tier aggregator (#115 T5 — DD-15/17/27/28/29/30/32/33/34).

Aggregates email-bound events into three tiers: preopen (07:30 ET weekday),
postclose (17:00 ET weekday), weekly (Sun 18:00 ET).

Called by: src.evaluation.auditor, src.scheduler.{overnight,reports,watch},
           src.services.{scan_service,recap_service,watchlist_service}, src.cli
Calls:     src.notifications.digest_queue.DigestQueue, src.email.notifier.send_email
Owns tables: none (re-uses notifications_digest_queue via DigestQueue)
Config keys: email.tier_times.*, email.tiers.*.{enabled,send_when_empty},
             email.dual_write_hold_over.{mode,shadow_output_dir}, email.holidays.skip_*
Tests:     tests/notifications/test_email_digest_module.py

Architecture (DD-29): flat module — EVENT_TO_TIER routing dict + 5 public
functions + private helpers. Module-load fail-fast (DD-30 + DA-MIN-19) uses
ImportError (not assert) so caller try/except catches drift correctly.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from src.config import load_config
from src.email.notifier import send_email
from src.notifications.digest_queue import DigestQueue, FlushResult
from src.notifications.telegram import EMAIL_TIER_EVENT_TYPES

logger = logging.getLogger(__name__)

TierName = Literal["preopen", "postclose", "weekly"]


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

    Reads email.dual_write_hold_over.mode from config:
      shadow (default)  → _write_shadow_file ONLY; no SMTP
      off               → _dispatch_tier (real send_email)
      time_aligned      → _dispatch_tier (real send_email)
    """
    cfg = load_config()
    email_cfg = (cfg or {}).get("email", {})
    holdover = email_cfg.get("dual_write_hold_over", {}) or {}
    mode = holdover.get("mode", "shadow")
    shadow_dir = holdover.get("shadow_output_dir", "tmp/digest-shadow")

    # Aggregate-then-dispatch (DD-27): batch-fetch tier rows ourselves rather
    # than per-row dispatch via DigestQueue.flush.
    rows = _fetch_pending_tier_rows(tier, conn=conn) if conn is not None else []

    subject, plain, html, overflow_ids = render_digest(
        tier, rows=rows, db_path=db_path, now_et=now_et
    )

    included_ids = [r["id"] for r in rows if r["id"] not in overflow_ids]

    if mode == "shadow":
        _write_shadow_file(tier, subject, plain, html, output_dir=shadow_dir)
        # Shadow mode does NOT advance rows to 'sent' — old paths keep
        # serving the inbox-volume-unchanged invariant.
        return FlushResult(successes=len(included_ids), failures=0, abandoned=0)

    # mode in ('off', 'time_aligned') → real email
    _dispatch_tier(
        tier, subject, plain, html, included_ids, overflow_ids,
        db_path=db_path, conn=conn,
    )
    return FlushResult(successes=len(included_ids), failures=0, abandoned=0)


def render_digest(
    tier: TierName,
    rows: list[dict],
    *,
    db_path: str | None = None,
    now_et=None,
    top_k: int = 10,
) -> tuple[str, str, str, list[int]]:
    """Render (subject, plain_body, html_body, overflow_row_ids) for a tier.

    STUB (T5 — Tasks 6/7 fill in real per-tier rendering). Returns a valid
    4-tuple so downstream callers + tests have a stable contract.

    overflow_row_ids: row IDs that did NOT fit in top-K (DA-CRIT-2 fix).
    Caller MUST NOT mark these as flush_status='sent' — they are either
    attached as overflow file OR left as flush_status='pending'.
    """
    subject = f"Arcis {tier.capitalize()} Digest [stub]"
    plain = "[stub digest body — T6/T7 will render real content]"
    html = "<p>[stub digest body — T6/T7 will render real content]</p>"
    overflow_ids: list[int] = []
    return subject, plain, html, overflow_ids


def preview_tier(tier: TierName, *, db_path: str | None = None) -> str:
    """Return the plain-text body that would be sent. Used by CLI digest-preview."""
    subject, plain, html, overflow_ids = render_digest(tier, rows=[], db_path=db_path)
    return plain


def handover_check(
    *,
    window_days: int = 7,
    db_path: str | None = None,
) -> dict:
    """DA-MAJ-7 hold-over exit-criteria check.

    SKELETON (T5 — Task 17 will fill in real tripwire logic).
    """
    return {"status": "PASS", "tripwires": {}}


# ── Private helpers ───────────────────────────────────────────────────────

def _collect_preopen_critical_replays(conn) -> list[dict]:
    """DD-17 revised: query queue rows tagged with the hybrid-CRITICAL marker
    for digest replay. Queue rows are CANONICAL (DD-34)."""
    if conn is None:
        return []
    rows = conn.execute(
        "SELECT id, event_type, severity, payload_json, source_tag, flush_status "
        "FROM notifications_digest_queue "
        "WHERE source_tag = 'email:preopen:critical-overflow' "
        "  AND flush_status IN ('pending', 'in_progress') "
        "ORDER BY created_at ASC"
    ).fetchall()
    out = []
    for r in rows:
        try:
            payload = json.loads(r["payload_json"])
        except Exception:
            payload = {}
        # Tolerate missing fields (DA-MIN-17 — defensive defaults).
        out.append({
            "id": r["id"],
            "event_type": r["event_type"],
            "severity": r["severity"],
            "source_tag": r["source_tag"],
            "category": payload.get("category", "unknown"),
            "description": payload.get("description", ""),
            "recommendation": payload.get("recommendation", ""),
            "fired_immediately_at": payload.get("fired_immediately_at", ""),
            "subject": payload.get("subject", ""),
            "body": payload.get("body", ""),
        })
    return out


def _collect_preopen_data(db_path, now_et) -> dict:
    """STUB — Task 6 fills in (queue rows + critical-replay aggregation)."""
    return {}


def _collect_postclose_data(db_path, now_et) -> dict:
    """STUB — Task 6 fills in."""
    return {}


def _collect_weekly_data(db_path, now_et) -> dict:
    """STUB — Task 7 fills in (weekly tables: data_asset, scan_metrics, training)."""
    return {}


def _render_preopen_html(data, replays) -> tuple[str, str]:
    """STUB — Task 6 fills in. Returns (subject, html_body)."""
    return ("[Stub Pre-Open]", "<p>[Stub Pre-Open]</p>")


def _render_postclose_html(data) -> tuple[str, str]:
    """STUB — Task 6 fills in. Returns (subject, html_body)."""
    return ("[Stub Post-Close]", "<p>[Stub Post-Close]</p>")


def _render_weekly_html(data) -> tuple[str, str]:
    """STUB — Task 7 fills in. Returns (subject, html_body)."""
    return ("[Stub Weekly]", "<p>[Stub Weekly]</p>")


def _render_plain_from_html(html: str) -> str:
    """Best-effort HTML→plain (strip tags). Minimal implementation."""
    return re.sub(r"<[^>]+>", "", html or "")


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
