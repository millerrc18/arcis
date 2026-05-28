"""Email-digest rendering helpers (#115 — Phase 5 PR-C T16 split of email_digest.py).

Pure rendering / HTML / formatting surface for the email-tier aggregator:
the per-tier render orchestrator (render_digest), the top-K-by-severity
truncation, the per-section HTML builders for preopen / postclose / weekly,
the weekly-tier data collectors, and the plain-text projection.

Called by: src.notifications.email_digest (flush_tier / preview_tier)
Calls:     src.scheduler.holidays (none directly), stdlib html/json/re/datetime
Owns tables: none (reads activity_log, shadow_trades, training_examples,
             canary_evaluations, api_costs, notifications_sent,
             notifications_digest_queue via the caller-supplied conn)
Config keys: none (top_k passed in by flush_tier from email.digest_truncation)
Tests:     tests/notifications/test_email_digest_render_daily.py,
           tests/notifications/test_email_digest_render_weekly.py

Architecture (DD-29): extracted verbatim from email_digest.py; render_digest +
preview_tier are re-exported by the orchestrator so the public API and all
`from src.notifications.email_digest import render_digest` call sites are
byte-for-byte unchanged.
"""

from __future__ import annotations

import html as html_lib
import json
import re
from datetime import datetime, timedelta, timezone
from typing import Literal
from zoneinfo import ZoneInfo

TierName = Literal["preopen", "postclose", "weekly"]

# Severity rank for top-K truncation (DD-05 revised). Higher = more critical.
_SEVERITY_RANK = {
    "critical": 5,
    "alert": 4,
    "warning": 3,
    "normal": 2,
    "low": 1,
}

_ET = ZoneInfo("America/New_York")


def render_digest(
    tier: TierName,
    rows: list[dict],
    *,
    db_path: str | None = None,
    now_et=None,
    top_k: int = 10,
    conn=None,
) -> tuple[str, str, str, list[int]]:
    """Render (subject, plain_body, html_body, overflow_row_ids) for a tier.

    overflow_row_ids: row IDs that did NOT fit in top-K (DA-CRIT-2 fix).
    Caller MUST NOT mark these as flush_status='sent' — they are either
    attached as overflow file OR left as flush_status='pending'.

    Top-K (DD-05 revised, DD-19): rank rows by severity (critical > alert >
    warning > normal > low), keep top-`top_k`, return the rest as overflow.

    `conn` is the sqlite connection used for critical-replay lookup (DD-34).
    """
    included, overflow_ids = _truncate_top_k(rows, top_k=top_k)
    if tier == "preopen":
        replays = _collect_preopen_critical_replays(conn) if conn is not None else []
        subject, html = _render_preopen_html(
            included, replays, now_et=now_et,
        )
    elif tier == "postclose":
        subject, html = _render_postclose_html(
            included, db_path=db_path, conn=conn, now_et=now_et,
        )
    elif tier == "weekly":
        data = _collect_weekly_data(db_path, now_et, conn=conn)
        subject, html = _render_weekly_html(
            data, included, now_et=now_et,
        )
    else:  # pragma: no cover — TierName Literal prevents this in practice
        raise ValueError(f"unknown tier: {tier!r}")

    plain = _render_plain_from_html(html)
    return subject, plain, html, overflow_ids


def _truncate_top_k(
    rows: list[dict], *, top_k: int,
) -> tuple[list[dict], list[int]]:
    """Stable top-K-by-severity truncation. Returns (included, overflow_ids).

    Ranking: critical > alert > warning > normal > low. Within a rank the
    original ordering is preserved (stable sort by negative-rank, original
    index). Overflow IDs are the row IDs that did NOT make the top-K.
    """
    if not rows or len(rows) <= top_k:
        return list(rows), []
    indexed = list(enumerate(rows))
    indexed.sort(
        key=lambda pair: (
            -_SEVERITY_RANK.get(str(pair[1].get("severity", "")).lower(), 0),
            pair[0],
        )
    )
    kept_pairs = indexed[:top_k]
    dropped_pairs = indexed[top_k:]
    # Preserve original order in the rendered output (stability).
    kept_pairs.sort(key=lambda p: p[0])
    dropped_pairs.sort(key=lambda p: p[0])
    included = [p[1] for p in kept_pairs]
    overflow_ids = [p[1]["id"] for p in dropped_pairs]
    return included, overflow_ids


def preview_tier(tier: TierName, *, db_path: str | None = None) -> str:
    """Return the plain-text body that would be sent. Used by CLI digest-preview."""
    subject, plain, html, overflow_ids = render_digest(tier, rows=[], db_path=db_path)
    return plain


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


def _collect_preopen_data(db_path, now_et, *, conn=None) -> dict:
    """Collect overnight activity for the pre-open section.

    Section 5.1: Section 3 'Overnight activity summary' — activity_log
    events in past 12h. Tolerates missing table (returns []).
    """
    out: dict = {"overnight": []}
    if conn is None:
        return out
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=12)).isoformat()
    try:
        rows = conn.execute(
            "SELECT event_type, detail, created_at FROM activity_log "
            "WHERE created_at > ? ORDER BY created_at DESC LIMIT 10",
            (cutoff,),
        ).fetchall()
    except Exception:
        rows = []
    out["overnight"] = [
        {
            "event_type": (r["event_type"] if "event_type" in r.keys() else r[0]),
            "detail": (r["detail"] if "detail" in r.keys() else r[1]),
        }
        for r in rows
    ]
    return out


def _collect_postclose_data(db_path, now_et, *, conn=None) -> dict:
    """Collect EOD results + open positions for the post-close sections.

    Section 5.1: Section 1 'EOD results' (P&L + closed today),
    Section 4 'Open positions' (exit_time IS NULL, limit 10).
    Tolerates missing shadow_trades table.
    """
    out: dict = {"closed": [], "open": [], "closed_pnl": 0.0}
    if conn is None:
        return out
    today = (now_et or datetime.now(_ET)).strftime("%Y-%m-%d")
    try:
        closed = conn.execute(
            "SELECT ticker, pnl_dollars, pnl_pct, exit_reason "
            "FROM shadow_trades WHERE status='closed' "
            "  AND date(actual_exit_time)=? "
            "  AND COALESCE(quarantined,0)=0",
            (today,),
        ).fetchall()
    except Exception:
        closed = []
    try:
        open_rows = conn.execute(
            "SELECT ticker, entry_price, planned_shares "
            "FROM shadow_trades WHERE status='open' "
            "  AND COALESCE(quarantined,0)=0 "
            "ORDER BY ticker LIMIT 10"
        ).fetchall()
    except Exception:
        open_rows = []
    out["closed"] = [
        {
            "ticker": r["ticker"],
            "pnl_dollars": r["pnl_dollars"],
            "pnl_pct": r["pnl_pct"],
            "exit_reason": r["exit_reason"],
        }
        for r in closed
    ]
    out["open"] = [
        {
            "ticker": r["ticker"],
            "entry_price": r["entry_price"],
            "planned_shares": r["planned_shares"],
        }
        for r in open_rows
    ]
    try:
        out["closed_pnl"] = sum(float(r["pnl_dollars"] or 0) for r in closed)
    except Exception:
        out["closed_pnl"] = 0.0
    return out


def _collect_weekly_data(db_path, now_et, *, conn=None) -> dict:
    """Collect rolling-7-day data for the weekly digest.

    Section 5.1: 5 sections — performance (shadow_trades closed past 7d),
    training (training_examples + canary_evaluations), CTO (api_costs),
    research (queue rows — gathered at render time), audit week-in-review
    (notifications_sent past 7d). Tolerates missing tables (defaults to
    zero / empty so the weekly digest never crashes on a fresh DB).
    """
    out: dict = {
        "trades": [], "trades_pnl": 0.0, "wins": 0, "losses": 0,
        "trade_count": 0, "win_rate": 0.0,
        "training_count": 0, "training_quality_avg": 0.0, "canary_status": "N/A",
        "api_cost_total": 0.0,
        "audit_critical_count": 0, "audit_alert_count": 0,
        "audit_by_category": {},
    }
    if conn is None:
        return out
    cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    out.update(_collect_weekly_performance(conn, cutoff))
    out.update(_collect_weekly_training(conn, cutoff))
    out.update(_collect_weekly_cto(conn, cutoff))
    out.update(_collect_weekly_audit(conn, cutoff))
    return out


def _collect_weekly_performance(conn, cutoff: str) -> dict:
    """Section 1 data: closed shadow_trades in past 7 days."""
    try:
        trade_rows = conn.execute(
            "SELECT ticker, pnl_dollars, pnl_pct, exit_reason FROM shadow_trades "
            "WHERE status='closed' AND actual_exit_time > ? "
            "  AND COALESCE(quarantined, 0)=0 "
            "ORDER BY actual_exit_time DESC",
            (cutoff,),
        ).fetchall()
    except Exception:
        trade_rows = []
    trades = [
        {
            "ticker": r["ticker"], "pnl_dollars": r["pnl_dollars"],
            "pnl_pct": r["pnl_pct"], "exit_reason": r["exit_reason"],
        }
        for r in trade_rows
    ]
    pnls = [_coerce_float_local(r["pnl_dollars"], 0.0) for r in trade_rows]
    wins = sum(1 for p in pnls if p > 0)
    count = len(pnls)
    return {
        "trades": trades,
        "trades_pnl": sum(pnls),
        "wins": wins,
        "losses": sum(1 for p in pnls if p <= 0),
        "trade_count": count,
        "win_rate": (wins / count) if count else 0.0,
    }


def _collect_weekly_training(conn, cutoff: str) -> dict:
    """Section 2 data: training_examples + canary_evaluations past 7 days."""
    out = {"training_count": 0, "training_quality_avg": 0.0, "canary_status": "N/A"}
    try:
        training_row = conn.execute(
            "SELECT COUNT(*) AS c, AVG(quality_score_auto) AS q "
            "FROM training_examples WHERE created_at > ?",
            (cutoff,),
        ).fetchone()
        out["training_count"] = int(training_row["c"] or 0)
        out["training_quality_avg"] = float(training_row["q"] or 0.0)
    except Exception:
        pass
    try:
        canary_row = conn.execute(
            "SELECT status FROM canary_evaluations "
            "WHERE created_at > ? ORDER BY created_at DESC LIMIT 1",
            (cutoff,),
        ).fetchone()
        if canary_row:
            out["canary_status"] = str(canary_row["status"] or "N/A")
    except Exception:
        pass
    return out


def _collect_weekly_cto(conn, cutoff: str) -> dict:
    """Section 3 data: api_costs total in past 7 days."""
    try:
        cost_row = conn.execute(
            "SELECT COALESCE(SUM(cost_dollars), 0) AS total FROM api_costs "
            "WHERE created_at > ?",
            (cutoff,),
        ).fetchone()
        return {"api_cost_total": float(cost_row["total"] or 0.0)}
    except Exception:
        return {"api_cost_total": 0.0}


def _collect_weekly_audit(conn, cutoff: str) -> dict:
    """Section 5 data: CRITICAL+ALERT counts by category from notifications_sent."""
    try:
        audit_rows = conn.execute(
            "SELECT event_type, severity, COUNT(*) AS c FROM notifications_sent "
            "WHERE sent_at > ? AND severity IN ('critical', 'alert') "
            "GROUP BY event_type, severity",
            (cutoff,),
        ).fetchall()
    except Exception:
        audit_rows = []
    by_category: dict[str, int] = {}
    critical = 0
    alert = 0
    for r in audit_rows:
        sev = str(r["severity"] or "").lower()
        cat = str(r["event_type"] or "unknown")
        cnt = int(r["c"] or 0)
        by_category[cat] = by_category.get(cat, 0) + cnt
        if sev == "critical":
            critical += cnt
        elif sev == "alert":
            alert += cnt
    return {
        "audit_critical_count": critical,
        "audit_alert_count": alert,
        "audit_by_category": by_category,
    }


def _render_preopen_html(
    included: list[dict],
    replays: list[dict],
    *,
    now_et=None,
) -> tuple[str, str]:
    """Render pre-open subject + HTML body (Section 5.1, DA-MAJ-12 terminology).

    Sections: (1) Critical audit alerts (DD-17/DD-34 replays), (2) Morning
    watchlist (queued payload), (3) Overnight activity summary.
    """
    now = now_et or datetime.now(_ET)
    date_str = now.strftime("%b %d")
    watchlist_rows = [r for r in included if r["event_type"] == "morning_watchlist"]
    other_rows = [r for r in included if r["event_type"] != "morning_watchlist"]

    parts: list[str] = [
        "<html><body style='font-family:Arial,sans-serif'>",
        f"<h1>Arcis Pre-Open Brief — {html_lib.escape(date_str)}</h1>",
    ]
    parts.extend(_render_preopen_replays_section(replays))
    parts.extend(_render_preopen_watchlist_section(watchlist_rows))
    parts.extend(_render_preopen_overnight_section(other_rows))
    parts.append("</body></html>")

    html = "\n".join(parts)
    subject = (
        f"Arcis Pre-Open — {date_str} | "
        f"{len(replays)} alerts, {len(watchlist_rows)} watchlist"
    )
    return subject, html


def _render_preopen_replays_section(replays: list[dict]) -> list[str]:
    """Pre-open Section 1: critical audit alerts fired since last digest."""
    if not replays:
        return [
            "<p style='color:#666'>Critical audit alerts fired since last digest: none.</p>"
        ]
    out: list[str] = [
        "<h2 style='color:#b00'>Critical audit alerts fired since last digest</h2>",
        "<ul>",
    ]
    for r in replays:
        cat = html_lib.escape(str(r.get("category", "unknown")))
        desc = html_lib.escape(str(r.get("description", "")))
        ts = html_lib.escape(str(r.get("fired_immediately_at", "")))
        out.append(
            f"<li><b>{cat}</b> — {desc}"
            + (f" <span style='color:#666'>({ts})</span>" if ts else "")
            + "</li>"
        )
    out.append("</ul>")
    return out


def _render_preopen_watchlist_section(watchlist_rows: list[dict]) -> list[str]:
    """Pre-open Section 2: morning watchlist."""
    if not watchlist_rows:
        return ["<h2>Morning watchlist</h2>", "<p>No morning watchlist queued.</p>"]
    out: list[str] = ["<h2>Morning watchlist</h2>", "<ul>"]
    for r in watchlist_rows:
        payload = r.get("payload", {}) or {}
        tickers = payload.get("tickers", [])
        note = payload.get("summary", "")
        ticker_str = (
            ", ".join(html_lib.escape(str(t)) for t in tickers)
            if tickers else "(no tickers)"
        )
        out.append(
            f"<li>{ticker_str}"
            + (f" — {html_lib.escape(str(note))}" if note else "")
            + "</li>"
        )
    out.append("</ul>")
    return out


def _render_preopen_overnight_section(other_rows: list[dict]) -> list[str]:
    """Pre-open Section 3: overnight activity summary."""
    if not other_rows:
        return ["<h2>Overnight activity summary</h2>", "<p>No overnight events queued.</p>"]
    out: list[str] = ["<h2>Overnight activity summary</h2>", "<ul>"]
    for r in other_rows:
        payload = r.get("payload", {}) or {}
        evt = html_lib.escape(str(r.get("event_type", "")))
        summary = html_lib.escape(
            str(payload.get("summary", "") or payload.get("detail", ""))
        )
        out.append(
            f"<li><b>{evt}</b>"
            + (f": {summary}" if summary else "")
            + "</li>"
        )
    out.append("</ul>")
    return out


def _render_postclose_html(
    included: list[dict],
    *,
    db_path: str | None = None,
    conn=None,
    now_et=None,
) -> tuple[str, str]:
    """Render post-close subject + HTML body (Section 5.1).

    Sections: (1) EOD results (P&L + closed from shadow_trades),
    (2) Action packets summarized, (3) Audit alerts, (4) Open positions.
    """
    now = now_et or datetime.now(_ET)
    date_str = now.strftime("%b %d")
    data = _collect_postclose_data(db_path, now_et, conn=conn)
    packets = [r for r in included if r["event_type"] == "action_packet"]
    audit_alerts = [
        r for r in included
        if r["event_type"] in ("audit_alert", "audit_red_assessment")
    ]
    closed = data.get("closed", [])
    open_positions = data.get("open", [])
    closed_pnl = float(data.get("closed_pnl") or 0.0)

    parts: list[str] = [
        "<html><body style='font-family:Arial,sans-serif'>",
        f"<h1>Arcis Post-Close Recap — {html_lib.escape(date_str)}</h1>",
    ]
    parts.extend(_render_postclose_eod_section(closed, closed_pnl))
    parts.extend(_render_postclose_packets_section(packets))
    parts.extend(_render_postclose_audit_section(audit_alerts))
    parts.extend(_render_postclose_positions_section(open_positions))
    parts.append("</body></html>")

    html = "\n".join(parts)
    subject = (
        f"Arcis Post-Close — {date_str} | "
        f"{len(closed)} closed, P&L: ${closed_pnl:+.2f}"
    )
    return subject, html


def _render_postclose_eod_section(
    closed: list[dict], closed_pnl: float,
) -> list[str]:
    """Post-close Section 1: EOD results — P&L + closed positions today."""
    out: list[str] = [
        "<h2>EOD results</h2>",
        f"<p>Trades closed: <b>{len(closed)}</b> &middot; "
        f"Day P&amp;L: <b>${closed_pnl:+.2f}</b></p>",
    ]
    if closed:
        out.append("<ul>")
        for t in closed:
            pnl = _coerce_float_local(t.get("pnl_dollars"), 0.0)
            pct = _coerce_float_local(t.get("pnl_pct"), 0.0)
            tk = html_lib.escape(str(t.get("ticker", "")))
            er = html_lib.escape(str(t.get("exit_reason", "")))
            out.append(f"<li>{tk}: ${pnl:+.2f} ({pct:+.1f}%) [{er}]</li>")
        out.append("</ul>")
    return out


def _render_postclose_packets_section(packets: list[dict]) -> list[str]:
    """Post-close Section 2: Action packets summarized."""
    if not packets:
        return ["<h2>Action packets summarized</h2>", "<p>No action packets today.</p>"]
    out: list[str] = ["<h2>Action packets summarized</h2>", "<ul>"]
    for r in packets:
        payload = r.get("payload", {}) or {}
        tk = html_lib.escape(str(payload.get("ticker", "")))
        summary = html_lib.escape(str(payload.get("summary", "")))
        out.append(
            f"<li><b>{tk}</b>"
            + (f": {summary}" if summary else "")
            + "</li>"
        )
    out.append("</ul>")
    return out


def _render_postclose_audit_section(audit_alerts: list[dict]) -> list[str]:
    """Post-close Section 3: ALERT-level audit findings (lower-severity)."""
    if not audit_alerts:
        return ["<h2>Audit alerts</h2>", "<p>No audit alerts.</p>"]
    out: list[str] = ["<h2>Audit alerts</h2>", "<ul>"]
    for r in audit_alerts:
        payload = r.get("payload", {}) or {}
        cat = html_lib.escape(
            str(payload.get("category", r.get("event_type", "alert")))
        )
        desc = html_lib.escape(str(payload.get("description", "")))
        out.append(
            f"<li><b>{cat}</b>"
            + (f" — {desc}" if desc else "")
            + "</li>"
        )
    out.append("</ul>")
    return out


def _render_postclose_positions_section(open_positions: list[dict]) -> list[str]:
    """Post-close Section 4: Open positions (limit 10)."""
    if not open_positions:
        return ["<h2>Open positions</h2>", "<p>No open positions.</p>"]
    out: list[str] = ["<h2>Open positions</h2>", "<ul>"]
    for p in open_positions:
        tk = html_lib.escape(str(p.get("ticker", "")))
        ep = _coerce_float_local(p.get("entry_price"), 0.0)
        sh = p.get("planned_shares", "")
        out.append(f"<li>{tk}: entry ${ep:.2f} x{sh}</li>")
    out.append("</ul>")
    return out


def _coerce_float_local(value, default: float = 0.0) -> float:
    """Defensive float coercion (mirrors digest_builder pattern)."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _render_weekly_html(
    data: dict,
    included: list[dict],
    *,
    now_et=None,
) -> tuple[str, str]:
    """Render weekly subject + HTML body (Section 5.1, DD-12 subsumption).

    Five sections: (1) Weekly performance, (2) Training pipeline status,
    (3) CTO report highlights, (4) Research synthesis, (5) Audit
    week-in-review. Subject: 'Arcis Weekly — {Mon DD-Sun DD} | {N} trades,
    P&L: ${X} | Audit: {status}'.
    """
    now = now_et or datetime.now(_ET)
    period_end = now
    period_start = now - timedelta(days=6)
    period_str = (
        f"{period_start.strftime('%b %d')}-{period_end.strftime('%b %d')}"
    )

    trade_count = int(data.get("trade_count", 0) or 0)
    trades_pnl = float(data.get("trades_pnl", 0.0) or 0.0)
    audit_critical = int(data.get("audit_critical_count", 0) or 0)
    audit_alert = int(data.get("audit_alert_count", 0) or 0)
    audit_status = "clean"
    if audit_critical > 0:
        audit_status = f"{audit_critical} CRITICAL"
    elif audit_alert > 0:
        audit_status = f"{audit_alert} ALERT"

    research_rows = [
        r for r in included if r.get("event_type") == "research_synthesis_email"
    ]

    parts: list[str] = [
        "<html><body style='font-family:Arial,sans-serif'>",
        f"<h1>Arcis Weekly Report — {html_lib.escape(period_str)}</h1>",
    ]
    parts.extend(_render_weekly_performance_section(data))
    parts.extend(_render_weekly_training_section(data))
    parts.extend(_render_weekly_cto_section(data))
    parts.extend(_render_weekly_research_section(research_rows))
    parts.extend(_render_weekly_audit_section(data))
    parts.append("</body></html>")

    html = "\n".join(parts)
    subject = (
        f"Arcis Weekly — {period_str} | {trade_count} trades, "
        f"P&L: ${trades_pnl:+.2f} | Audit: {audit_status}"
    )
    return subject, html


def _render_weekly_performance_section(data: dict) -> list[str]:
    """Weekly Section 1: P&L + win rate + trade count + per-ticker lines."""
    trade_count = int(data.get("trade_count", 0) or 0)
    trades_pnl = float(data.get("trades_pnl", 0.0) or 0.0)
    wins = int(data.get("wins", 0) or 0)
    losses = int(data.get("losses", 0) or 0)
    win_rate_pct = float(data.get("win_rate", 0.0) or 0.0) * 100
    trades = data.get("trades", []) or []

    out: list[str] = [
        "<h2>Weekly performance</h2>",
        f"<p>Trades closed: <b>{trade_count}</b> &middot; "
        f"Win rate: <b>{win_rate_pct:.1f}%</b> ({wins}W / {losses}L) &middot; "
        f"P&amp;L: <b>${trades_pnl:+.2f}</b></p>",
    ]
    if trades:
        out.append("<ul>")
        for t in trades[:10]:
            tk = html_lib.escape(str(t.get("ticker", "")))
            pnl = _coerce_float_local(t.get("pnl_dollars"), 0.0)
            pct = _coerce_float_local(t.get("pnl_pct"), 0.0)
            er = html_lib.escape(str(t.get("exit_reason", "")))
            out.append(f"<li>{tk}: ${pnl:+.2f} ({pct:+.1f}%) [{er}]</li>")
        out.append("</ul>")
    else:
        out.append("<p>No trades closed this week.</p>")
    return out


def _render_weekly_training_section(data: dict) -> list[str]:
    """Weekly Section 2: training pipeline status (subsumes Saturday training)."""
    count = int(data.get("training_count", 0) or 0)
    quality = float(data.get("training_quality_avg", 0.0) or 0.0)
    canary = html_lib.escape(str(data.get("canary_status", "N/A") or "N/A"))
    return [
        "<h2>Training pipeline status</h2>",
        f"<p>New examples this week: <b>{count}</b> &middot; "
        f"Avg quality score: <b>{quality:.2f}</b> &middot; "
        f"Canary: <b>{canary}</b></p>",
    ]


def _render_weekly_cto_section(data: dict) -> list[str]:
    """Weekly Section 3: CTO report highlights (subsumes Saturday CTO)."""
    cost = float(data.get("api_cost_total", 0.0) or 0.0)
    return [
        "<h2>CTO report highlights</h2>",
        f"<p>API cost (rolling 7d): <b>${cost:.2f}</b></p>",
    ]


def _render_weekly_research_section(research_rows: list[dict]) -> list[str]:
    """Weekly Section 4: research synthesis (graceful empty-state)."""
    if not research_rows:
        return [
            "<h2>Research synthesis</h2>",
            "<p>No research synthesis queued this week.</p>",
        ]
    out: list[str] = ["<h2>Research synthesis</h2>", "<ul>"]
    for r in research_rows:
        payload = r.get("payload", {}) or {}
        title = html_lib.escape(str(payload.get("title", "(untitled)")))
        summary = html_lib.escape(str(payload.get("summary", "")))
        out.append(
            f"<li><b>{title}</b>"
            + (f" — {summary}" if summary else "")
            + "</li>"
        )
    out.append("</ul>")
    return out


def _render_weekly_audit_section(data: dict) -> list[str]:
    """Weekly Section 5: audit week-in-review — CRITICAL+ALERT counts by category."""
    critical = int(data.get("audit_critical_count", 0) or 0)
    alert = int(data.get("audit_alert_count", 0) or 0)
    by_cat = data.get("audit_by_category", {}) or {}
    out: list[str] = [
        "<h2>Audit week-in-review</h2>",
        f"<p>CRITICAL: <b>{critical}</b> &middot; ALERT: <b>{alert}</b></p>",
    ]
    if by_cat:
        out.append("<ul>")
        for cat, cnt in sorted(by_cat.items()):
            out.append(
                f"<li>{html_lib.escape(str(cat))}: {int(cnt)}</li>"
            )
        out.append("</ul>")
    else:
        out.append("<p>No CRITICAL or ALERT audit findings this week.</p>")
    return out


def _render_plain_from_html(html: str) -> str:
    """Best-effort HTML→plain (strip tags). Minimal implementation."""
    return re.sub(r"<[^>]+>", "", html or "")
