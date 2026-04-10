"""Build fund-manager-style email digests for Arcis.

Called by: scheduler.watch
Calls: none
Owns tables: none
Config keys: none
Tests: tests/test_digest_builder.py

Four digests per day, each with a specific purpose:
1. Pre-market (7:30 AM): Portfolio status, overnight events, today's plan
2. Midday (12:00 PM): Morning activity, P&L update, any risk alerts
3. EOD (4:15 PM): Full day recap, all trades, daily P&L, next actions
4. Evening (8:00 PM): Model metrics, training data, flywheel velocity
"""

import logging
import sqlite3
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from src.config import DB_PATH

logger = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")


def _safe_fetchall(conn, sql, params=()):
    """Execute query, return list. Returns [] if table missing."""
    try:
        return conn.execute(sql, params).fetchall()
    except sqlite3.OperationalError as e:
        if "no such table" in str(e):
            return []
        raise


def _safe_fetchone(conn, sql, params=()):
    """Execute query, return one row. Returns None if table/column missing."""
    try:
        return conn.execute(sql, params).fetchone()
    except sqlite3.OperationalError as e:
        if "no such table" in str(e) or "no such column" in str(e):
            return None
        raise


def _coerce_float(value, default: float = 0.0) -> float:
    """Best-effort float coercion for mixed-type SQLite values."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def build_premarket_digest(db_path: str = DB_PATH) -> tuple[str, str]:
    """Pre-market brief: portfolio status, overnight events, today's plan."""
    now = datetime.now(ET)

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row

        open_trades = _safe_fetchall(
            conn,
            "SELECT ticker, entry_price, planned_shares, source, created_at "
            "FROM shadow_trades WHERE status = 'open' AND COALESCE(quarantined, 0) = 0"
            " ORDER BY source, ticker",
        )
        paper_trades = [t for t in open_trades if t["source"] == "paper"]
        live_trades = [t for t in open_trades if t["source"] == "live"]

        yesterday = (now - timedelta(days=1)).strftime("%Y-%m-%d")
        closed_yesterday = _safe_fetchall(
            conn,
            "SELECT ticker, pnl_dollars, pnl_pct, exit_reason "
            "FROM shadow_trades WHERE status = 'closed' AND date(actual_exit_time) = ?"
            " AND COALESCE(quarantined, 0) = 0",
            (yesterday,),
        )

        overnight_activity = _safe_fetchall(
            conn,
            "SELECT event_type, detail FROM activity_log "
            "WHERE created_at > ? ORDER BY created_at DESC LIMIT 10",
            ((now - timedelta(hours=12)).isoformat(),),
        )

        council = _safe_fetchone(
            conn,
            "SELECT consensus, confidence_weighted_score, is_contested "
            "FROM council_sessions ORDER BY created_at DESC LIMIT 1",
        )

    subject = f"Arcis Pre-Market — {now.strftime('%b %d')} | {len(paper_trades)} paper, {len(live_trades)} live"

    lines = [
        "ARCIS — PRE-MARKET BRIEF",
        now.strftime("%A, %B %d, %Y"),
        "",
        "━━━ PORTFOLIO STATUS ━━━",
        f"Paper positions: {len(paper_trades)} open",
        f"Live positions:  {len(live_trades)} open",
    ]

    if closed_yesterday:
        total_pnl = sum(float(t["pnl_dollars"] or 0) for t in closed_yesterday)
        wins = sum(1 for t in closed_yesterday if _coerce_float(t["pnl_dollars"]) > 0)
        lines.extend([
            "",
            f"Yesterday: {len(closed_yesterday)} trades closed, "
            f"{wins}W/{len(closed_yesterday) - wins}L, P&L: ${total_pnl:+.2f}",
        ])

    if council:
        consensus = council["consensus"] or "unknown"
        confidence = _coerce_float(council["confidence_weighted_score"], 0.0)
        contested = " (contested)" if council["is_contested"] else ""
        lines.extend(["", "━━━ COUNCIL ━━━", f"Latest assessment: {consensus}{contested}"])
        if confidence > 0:
            lines.append(f"Confidence: {confidence:.0%}")

    lines.extend([
        "", "━━━ TODAY'S PLAN ━━━",
        "Market scans: every 30 min (9:30 AM – 4:00 PM ET)",
        "EOD recap at 4:15 PM", "", "— Arcis",
    ])

    return subject, "\n".join(lines)


def build_midday_digest(db_path: str = DB_PATH) -> tuple[str, str]:
    """Midday update: morning trades, P&L, risk alerts."""
    now = datetime.now(ET)
    today = now.strftime("%Y-%m-%d")

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row

        opened_today = _safe_fetchall(
            conn,
            "SELECT ticker, entry_price, planned_shares, source "
            "FROM shadow_trades WHERE date(created_at) = ? AND status IN ('open', 'closed')"
            " AND COALESCE(quarantined, 0) = 0",
            (today,),
        )
        closed_today = _safe_fetchall(
            conn,
            "SELECT ticker, pnl_dollars, pnl_pct, exit_reason "
            "FROM shadow_trades WHERE status = 'closed' AND date(actual_exit_time) = ?"
            " AND COALESCE(quarantined, 0) = 0",
            (today,),
        )
        risk_alerts = _safe_fetchall(
            conn,
            "SELECT detail, created_at FROM activity_log "
            "WHERE event_type = 'risk_alert' AND date(created_at) = ?",
            (today,),
        )
        scans = _safe_fetchall(
            conn,
            "SELECT scan_number, packet_worthy, paper_traded, llm_success, llm_total "
            "FROM scan_metrics WHERE date(created_at) = ? ORDER BY scan_number",
            (today,),
        )

    total_packets = sum(int(s["packet_worthy"] or 0) for s in scans)
    total_traded = sum(int(s["paper_traded"] or 0) for s in scans)
    llm_success = sum(int(s["llm_success"] or 0) for s in scans)
    llm_total = sum(int(s["llm_total"] or 0) for s in scans)
    llm_rate = f"{llm_success}/{llm_total} ({llm_success / llm_total * 100:.0f}%)" if llm_total > 0 else "n/a"
    closed_pnl = sum(float(t["pnl_dollars"] or 0) for t in closed_today)

    subject = f"Arcis Midday — {len(opened_today)} opened, {len(closed_today)} closed, P&L: ${closed_pnl:+.2f}"

    lines = [
        "ARCIS — MIDDAY UPDATE",
        f"{now.strftime('%A, %B %d')} — 12:00 PM ET",
        "", "━━━ MORNING ACTIVITY ━━━",
        f"Scans completed:  {len(scans)}",
        f"Setups scored:    {total_packets}",
        f"Trades opened:    {len(opened_today)} ({total_traded} attempted)",
        f"Trades closed:    {len(closed_today)}",
        f"LLM success rate: {llm_rate}",
    ]

    if closed_today:
        lines.extend(["", "━━━ CLOSED TRADES ━━━"])
        for t in closed_today:
            pnl = _coerce_float(t["pnl_dollars"])
            pct = _coerce_float(t["pnl_pct"])
            icon = "+" if pnl > 0 else "-"
            lines.append(f"  {icon} {t['ticker']:6s}  ${pnl:+8.2f}  ({pct:+.1f}%)  [{t['exit_reason']}]")
        lines.append(f"  Net: ${closed_pnl:+.2f}")

    if risk_alerts:
        lines.extend(["", "━━━ RISK ALERTS ━━━"])
        for alert in risk_alerts:
            lines.append(f"  ! {alert['detail']}")

    lines.extend(["", "— Arcis"])
    return subject, "\n".join(lines)


def build_eod_digest(db_path: str = DB_PATH) -> tuple[str, str]:
    """EOD recap: full day summary, all trades, P&L, position snapshot."""
    now = datetime.now(ET)
    today = now.strftime("%Y-%m-%d")

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row

        opened = _safe_fetchall(conn, "SELECT ticker, entry_price, planned_shares, source FROM shadow_trades WHERE date(created_at) = ? AND COALESCE(quarantined, 0) = 0", (today,))
        closed = _safe_fetchall(conn, "SELECT ticker, pnl_dollars, pnl_pct, exit_reason, source FROM shadow_trades WHERE status = 'closed' AND date(actual_exit_time) = ? AND COALESCE(quarantined, 0) = 0", (today,))
        open_positions = _safe_fetchall(conn, "SELECT ticker, entry_price, planned_shares, source, created_at FROM shadow_trades WHERE status = 'open' AND COALESCE(quarantined, 0) = 0 ORDER BY source, ticker")
        all_closed = _safe_fetchall(conn, "SELECT pnl_dollars, pnl_pct FROM shadow_trades WHERE status = 'closed' AND COALESCE(quarantined, 0) = 0")
        scans = _safe_fetchone(conn, "SELECT COUNT(*) as cnt FROM scan_metrics WHERE date(created_at) = ?", (today,))

    closed_pnl = sum(float(t["pnl_dollars"] or 0) for t in closed)
    total_trades = len(all_closed)
    total_pnl = sum(float(t["pnl_dollars"] or 0) for t in all_closed)
    win_rate = sum(1 for t in all_closed if _coerce_float(t["pnl_dollars"]) > 0) / total_trades if total_trades else 0

    subject = f"Arcis EOD — {now.strftime('%b %d')} | {len(closed)} closed, P&L: ${closed_pnl:+.2f} | Total: ${total_pnl:+.2f}"

    lines = [
        "ARCIS — END OF DAY RECAP",
        now.strftime("%A, %B %d, %Y"),
        "", "━━━ TODAY'S RESULTS ━━━",
        f"Trades opened:  {len(opened)}", f"Trades closed:  {len(closed)}",
        f"Day P&L:        ${closed_pnl:+.2f}",
        f"Scans run:      {scans['cnt'] if scans else 0}",
    ]

    if closed:
        lines.append("")
        for t in closed:
            pnl = _coerce_float(t["pnl_dollars"])
            pct = _coerce_float(t["pnl_pct"])
            icon = "+" if pnl > 0 else "-"
            lines.append(f"  {icon} {t['ticker']:6s}  ${pnl:+8.2f}  ({pct:+.1f}%)  [{t['exit_reason']}]")

    lines.extend([
        "", f"━━━ CUMULATIVE ({total_trades} trades) ━━━",
        f"Total P&L:    ${total_pnl:+.2f}", f"Win rate:     {win_rate:.0%}",
        f"Gate target:  {total_trades}/50 trades ({total_trades / 50 * 100:.0f}%)",
    ])

    paper = [t for t in open_positions if t["source"] == "paper"]
    live = [t for t in open_positions if t["source"] == "live"]
    lines.extend(["", "━━━ OPEN POSITIONS ━━━", f"Paper: {len(paper)} | Live: {len(live)}"])
    if paper:
        for t in paper[:10]:
            lines.append(f"  {t['ticker']:6s}  ${float(t['entry_price'] or 0):.2f}  x{t['planned_shares']}")
        if len(paper) > 10:
            lines.append(f"  ...and {len(paper) - 10} more")

    lines.extend(["", "— Arcis"])
    return subject, "\n".join(lines)


def build_evening_digest(db_path: str = DB_PATH) -> tuple[str, str]:
    """Evening digest: model quality, training data, flywheel velocity."""
    now = datetime.now(ET)
    today = now.strftime("%Y-%m-%d")

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row

        total_examples = _safe_fetchone(conn, "SELECT COUNT(*) as c FROM training_examples")
        today_examples = _safe_fetchone(conn, "SELECT COUNT(*) as c FROM training_examples WHERE date(created_at) = ?", (today,))
        scored = _safe_fetchone(conn, "SELECT COUNT(*) as c FROM training_examples WHERE quality_score_auto IS NOT NULL")
        avg_quality = _safe_fetchone(conn, "SELECT AVG(quality_score_auto) as avg FROM training_examples WHERE quality_score_auto IS NOT NULL")
        closed_total = _safe_fetchone(conn, "SELECT COUNT(*) as c FROM shadow_trades WHERE status = 'closed' AND COALESCE(quarantined, 0) = 0")
        scan_today = _safe_fetchone(conn, "SELECT SUM(llm_success) as s, SUM(llm_total) as t FROM scan_metrics WHERE date(created_at) = ?", (today,))
        canary = _safe_fetchone(conn, "SELECT degradation_detected, avg_score, distinct_2, created_at FROM canary_evaluations ORDER BY created_at DESC LIMIT 1")
        costs_today = _safe_fetchone(conn, "SELECT SUM(cost_dollars) as total FROM api_costs WHERE date(created_at) = ?", (today,))

    total_ex = total_examples["c"] if total_examples else 0
    today_ex = today_examples["c"] if today_examples else 0
    scored_count = scored["c"] if scored else 0
    avg_q = float(avg_quality["avg"]) if avg_quality and avg_quality["avg"] else 0
    closed_count = closed_total["c"] if closed_total else 0

    llm_s = scan_today["s"] if scan_today and scan_today["s"] else 0
    llm_t = scan_today["t"] if scan_today and scan_today["t"] else 0
    llm_rate = f"{llm_s / llm_t * 100:.0f}%" if llm_t > 0 else "n/a"
    cost = float(costs_today["total"]) if costs_today and costs_today["total"] else 0

    subject = f"Arcis Evening — {total_ex} examples, {closed_count}/50 trades, LLM {llm_rate}"

    lines = [
        "ARCIS — EVENING DIGEST", now.strftime("%A, %B %d, %Y"),
        "", "━━━ DATA ASSET ━━━",
        f"Training examples:  {total_ex}/2,800 target ({total_ex / 2800 * 100:.1f}%)",
        f"Added today:        {today_ex}",
        f"Quality scored:     {scored_count}/{total_ex}",
    ]
    lines.append(f"Avg quality score:  {avg_q:.1f}/5" if avg_q > 0 else "Avg quality score:  Not scored yet")

    lines.extend([
        "", "━━━ FLYWHEEL ━━━",
        f"Closed trades:      {closed_count}/50 gate target ({closed_count / 50 * 100:.0f}%)",
        f"LLM success rate:   {llm_rate} (today)",
    ])

    if canary:
        verdict = "DEGRADED" if canary["degradation_detected"] else "HEALTHY"
        lines.extend(["", "━━━ MODEL QUALITY ━━━", f"Canary verdict:     {verdict}"])
        if canary["avg_score"]:
            lines.append(f"Avg score:          {float(canary['avg_score']):.2f}")
        if canary["distinct_2"]:
            lines.append(f"Distinct-2:         {float(canary['distinct_2']):.4f}")
        lines.append(f"Last evaluated:     {canary['created_at'][:10]}")
    else:
        lines.extend(["", "━━━ MODEL QUALITY ━━━", "Awaiting first Saturday retrain for canary evaluation."])

    lines.extend([
        "", "━━━ COSTS ━━━",
        f"API spend today:    ${cost:.2f}" if cost else "API spend today:    $0.00",
        "", "— Arcis",
    ])

    return subject, "\n".join(lines)
