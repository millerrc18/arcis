"""Telegram notification client for Arcis.

Called by: cli.commands, data_collection.research_synthesizer, scheduler.watch, services.scan_service, shadow_trading.bracket_monitor, shadow_trading.executor, training.canary, training.ingestion_gate
Calls: config, council.engine, logging.activity, training.versioning
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

  Core transport:
    send_telegram, is_telegram_enabled, _get_telegram_config

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
    notify_vram_handoff, notify_scoring_summary, notify_schedule_health

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
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType
from typing import Optional
from zoneinfo import ZoneInfo

import requests
import requests.exceptions
import urllib3.exceptions

from src.config import DB_PATH, load_config
from src.data_ingestion.finnhub import normalize_earnings_time
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


# ── Typed dataclass payloads (CC3) ────────────────────────────────────────


@dataclass
class TradeOpenedPayload:
    ticker: str
    entry_price: float
    stop: float
    target: float
    score: int
    shares: int
    setup_type: Optional[str] = None
    setup_confidence: Optional[float] = None
    source: str = "paper"
    sector: Optional[str] = None
    regime_at_entry: Optional[str] = None
    vix_at_entry: Optional[float] = None
    concurrent_positions: Optional[int] = None
    llm_conviction: Optional[int] = None


@dataclass
class TradeClosedPayload:
    ticker: str
    pnl_dollars: float
    pnl_pct: float
    exit_reason: str
    days_held: int
    source: str = "paper"
    sector: Optional[str] = None
    regime_at_entry: Optional[str] = None
    regime_at_exit: Optional[str] = None
    mfe_pct: Optional[float] = None
    mae_pct: Optional[float] = None
    excess_return: Optional[float] = None
    spy_return_over_hold: Optional[float] = None
    drawdown_from_mfe: Optional[float] = None
    entry_slippage_bps: Optional[float] = None
    exit_slippage_bps: Optional[float] = None


@dataclass
class EodReportPayload:
    paper_open: int
    paper_open_pnl: float
    paper_closed_today: int
    paper_closed_pnl: float
    live_open: int
    live_open_pnl: float
    live_closed_today: int
    live_closed_pnl: float
    win_rate: float
    wins: int
    losses: int
    best_ticker: str
    best_pct: float
    worst_ticker: str
    worst_pct: float
    regime: str
    vix: float
    vix_change: float
    risk_rejected: int = 0
    risk_qualified: int = 0


@dataclass
class WeeklyDigestPayload:
    period_start: str
    period_end: str
    opened_paper: int
    opened_live: int
    closed_paper: int
    closed_live: int
    win_rate: float
    expectancy: float
    best_ticker: str
    best_pct: float
    worst_ticker: str
    worst_pct: float
    pnl_paper: float
    pnl_live: float
    training_start: int
    training_end: int
    signal_start: int
    signal_end: int
    scoring_backlog: int
    quality_avg: float
    canary_status: str
    llm_success_rate: float
    regime: str
    vix: float
    vix_range_low: float
    vix_range_high: float
    spy_weekly_pct: float
    council_sessions: int
    council_consensus: str
    council_avg_confidence: int
    earnings_next_week: list
    events_next_week: list


# ── Pre-formatted alert functions ─────────────────────────────────────────


def notify_trade_opened(payload: TradeOpenedPayload) -> bool:
    """Alert: new trade opened.

    Args:
        payload: TradeOpenedPayload dataclass with all trade fields.
                 source controls header emoji/label ("paper" or "live").
    """
    ticker = payload.ticker
    entry_price = payload.entry_price
    stop = payload.stop
    target = payload.target
    score = payload.score
    shares = payload.shares
    setup_type = payload.setup_type
    setup_confidence = payload.setup_confidence
    source = payload.source
    sector = payload.sector
    regime_at_entry = payload.regime_at_entry
    vix_at_entry = payload.vix_at_entry
    concurrent_positions = payload.concurrent_positions
    llm_conviction = payload.llm_conviction

    pnl_risk = (entry_price - stop) * shares
    rr_ratio = ((target - entry_price) / (entry_price - stop)) if entry_price > stop else None

    header = "🟢💰 <b>LIVE TRADE OPENED: " if source == "live" else "🟢 <b>TRADE OPENED: "
    header += ticker
    if setup_type and setup_confidence is not None:
        header += f" ({setup_type} ↑{setup_confidence:.2f})"
    elif setup_type:
        header += f" ({setup_type})"
    header += "</b>"

    lines = [
        header,
        f"Entry: ${entry_price:.2f} | Stop: ${stop:.2f} | Target: ${target:.2f}",
        f"Shares: {shares} | Risk: ${pnl_risk:.2f}" + (
            f" | R:R {rr_ratio:.2f}" if rr_ratio is not None else ""
        ),
        f"Score: {score}/100" + (
            f" | Conviction: {llm_conviction}/10" if llm_conviction is not None else ""
        ),
    ]
    context_bits = []
    if sector:
        context_bits.append(f"🏭 {sector}")
    if regime_at_entry:
        context_bits.append(f"📊 {regime_at_entry}")
    if vix_at_entry is not None:
        context_bits.append(f"VIX {vix_at_entry:.1f}")
    if concurrent_positions is not None:
        context_bits.append(f"{concurrent_positions} open")
    if context_bits:
        lines.append(" | ".join(context_bits))
    return send_telegram("\n".join(lines))


def notify_trade_closed(payload: TradeClosedPayload) -> bool:
    """Alert: trade closed.

    Args:
        payload: TradeClosedPayload dataclass. Optional fields render only when
                 present — callers set what they have. See shadow_trades schema
                 (`src/schema/registry.py`) for field semantics.
    """
    ticker = payload.ticker
    pnl_dollars = payload.pnl_dollars
    pnl_pct = payload.pnl_pct
    exit_reason = payload.exit_reason
    days_held = payload.days_held
    source = payload.source

    emoji = "🟢" if pnl_dollars >= 0 else "🔴"
    label = "LIVE TRADE CLOSED" if source == "live" else "TRADE CLOSED"
    lines = [
        f"{emoji} <b>{label}: {_html_escape(ticker)}</b>",
        f"P&L: ${pnl_dollars:+.2f} ({pnl_pct:+.1f}%)",
        f"Reason: {_html_escape(exit_reason)} | Held: {days_held}d",
    ]
    lines.extend(_format_closed_extras(
        payload.excess_return, payload.spy_return_over_hold, payload.mfe_pct, payload.mae_pct,
        payload.drawdown_from_mfe, payload.sector, payload.regime_at_entry, payload.regime_at_exit,
        payload.entry_slippage_bps, payload.exit_slippage_bps,
    ))
    return send_telegram("\n".join(lines))


def _format_closed_extras(excess_return, spy_return_over_hold, mfe_pct, mae_pct,
                          drawdown_from_mfe, sector, regime_at_entry,
                          regime_at_exit, entry_slippage_bps,
                          exit_slippage_bps) -> list[str]:
    """Render the optional-field lines of `notify_trade_closed`.

    Split out to keep the caller under the 60-line cap and make it trivial
    to extend with new optional fields later without touching the caller.
    """
    lines: list[str] = []
    if excess_return is not None and spy_return_over_hold is not None:
        lines.append(
            f"🎯 Excess vs SPY: {excess_return:+.2f}% "
            f"(SPY over hold: {spy_return_over_hold * 100:+.2f}%)"
        )
    elif excess_return is not None:
        lines.append(f"🎯 Excess vs SPY: {excess_return:+.2f}%")
    mfe_mae = [x for x in (
        f"MFE {mfe_pct:+.1f}%" if mfe_pct is not None else None,
        f"MAE {mae_pct:+.1f}%" if mae_pct is not None else None,
        f"DD-from-peak {drawdown_from_mfe:+.1f}%" if drawdown_from_mfe is not None else None,
    ) if x]
    if mfe_mae:
        lines.append("📈 " + " | ".join(mfe_mae))
    ctx: list[str] = []
    if sector:
        ctx.append(f"🏭 {sector}")
    if regime_at_entry and regime_at_exit and regime_at_entry != regime_at_exit:
        ctx.append(f"{regime_at_entry} → {regime_at_exit}")
    elif regime_at_entry:
        ctx.append(regime_at_entry)
    if ctx:
        lines.append(" | ".join(ctx))
    slip = [x for x in (
        f"entry {entry_slippage_bps:+.1f}bps" if entry_slippage_bps is not None else None,
        f"exit {exit_slippage_bps:+.1f}bps" if exit_slippage_bps is not None else None,
    ) if x]
    if slip:
        lines.append("⚙️ Slippage: " + " | ".join(slip))
    return lines


def notify_scan_complete(packets_count: int, trades_opened: int,
                         trades_closed: int) -> bool:
    """Alert: scan cycle complete (only if something happened).

    Gated: skips sending if nothing happened to avoid spamming during
    market hours when scans run every 30 minutes.
    """
    if packets_count == 0 and trades_opened == 0 and trades_closed == 0:
        return True  # Skip silent scans
    msg = (
        f"📊 <b>SCAN COMPLETE</b>\n"
        f"Packets: {packets_count} | Opened: {trades_opened} | Closed: {trades_closed}"
    )
    return send_telegram(msg)


def notify_risk_alert(alert_type: str, detail: str) -> bool:
    """Alert: risk governor event."""
    msg = f"⚠️ <b>RISK ALERT: {_html_escape(alert_type)}</b>\n{_html_escape(detail)}"
    return send_telegram(msg)


def notify_earnings_warning(tickers: list[str]) -> bool:
    """Alert: stocks reporting earnings soon."""
    if not tickers:
        return True
    ticker_list = "\n".join(f"  • {t}" for t in tickers)
    msg = f"📅 <b>EARNINGS THIS WEEK</b>\n{ticker_list}"
    return send_telegram(msg)


def notify_overnight_complete(results: dict) -> bool:
    """Alert: overnight data collection summary."""
    now = datetime.now(ET).strftime("%H:%M ET")
    lines = [f"🌙 <b>OVERNIGHT DATA COLLECTION</b> ({now})"]
    for key, val in results.items():
        if isinstance(val, dict):
            if not val.get("success", True):
                err = _html_escape(str(val.get("error", ""))[:60])
                lines.append(f"  ❌ {_html_escape(key)}: {err}" if err else f"  ❌ {_html_escape(key)}")
            else:
                lines.append(f"  ✅ {_html_escape(key)}")
        elif isinstance(val, str) and "error" in val.lower():
            lines.append(f"  ❌ {_html_escape(key)}: {_html_escape(val[:60])}")
        else:
            lines.append(f"  ✅ {_html_escape(key)}")
    return send_telegram("\n".join(lines))


def notify_system_event(event: str, detail: str = "") -> bool:
    """Alert: general system event."""
    msg = f"🔧 <b>{_html_escape(event)}</b>"
    if detail:
        msg += f"\n{_html_escape(detail)}"
    return send_telegram(msg)


def notify_startup_complete(
    overall_status: str,
    passed: int,
    warnings: int,
    criticals: int,
    warning_details: list[str] | None = None,
    critical_details: list[str] | None = None,
    launching: bool = True,
    email_mode: str = "digest",
    overnight: bool = True,
) -> bool:
    """Alert: startup validation complete."""
    if criticals > 0:
        emoji = "\u274c"
        title = "ARCIS STARTUP BLOCKED"
    elif warnings > 0:
        emoji = "\U0001f680"
        title = "ARCIS STARTUP"
    else:
        emoji = "\U0001f680"
        title = "ARCIS STARTUP"

    msg = f"{emoji} <b>{title}</b>\n\n"
    msg += f"{passed} passed | {warnings} warnings | {criticals} critical\n"
    msg += f"Status: <b>{overall_status.upper()}</b>\n"

    if critical_details:
        msg += "\n"
        for d in critical_details[:5]:
            msg += f"\u274c {d}\n"

    if warning_details:
        msg += "\n"
        for d in warning_details[:5]:
            msg += f"\u26a0\ufe0f {d}\n"

    if launching:
        overnight_str = "overnight" if overnight else "daytime"
        msg += f"\nWatch loop launching ({overnight_str} + {email_mode})"
    elif criticals > 0:
        msg += "\nUse --force to override."

    return send_telegram(msg)


def notify_daily_summary(total_pnl: float, open_trades: int,
                         closed_today: int, win_rate: float | None = None) -> bool:
    """Alert: end-of-day summary."""
    emoji = "🟢" if total_pnl >= 0 else "🔴"
    msg = (
        f"{emoji} <b>DAILY SUMMARY</b>\n"
        f"P&L Today: ${total_pnl:+.2f}\n"
        f"Open Trades: {open_trades} | Closed Today: {closed_today}"
    )
    if win_rate is not None:
        msg += f"\nWin Rate: {win_rate:.0%}"
    return send_telegram(msg)


def notify_model_event(event: str, model_name: str, detail: str = "") -> bool:
    """Alert: model training/promotion/rollback event."""
    msg = f"🧠 <b>MODEL: {_html_escape(event)}</b>\nModel: {_html_escape(model_name)}"
    if detail:
        msg += f"\n{_html_escape(detail)}"
    return send_telegram(msg)


# ── Additional notification events ────────────────────────────────────────


def notify_watchlist(tickers: list[str], count: int,
                     watchlist_count: int = 0) -> bool:
    """Alert: morning watchlist with high-conviction (packet-worthy) names."""
    now = datetime.now(ET).strftime("%H:%M ET")
    msg = f"☀️ <b>MORNING WATCHLIST</b> ({now})\n"
    if tickers:
        msg += f"🎯 {count} packet-worthy (score 40+):\n"
        msg += "\n".join(f"  • {t}" for t in tickers[:10])
        if count > 10:
            msg += f"\n  ...and {count - 10} more"
        if watchlist_count:
            msg += f"\n📋 {watchlist_count} additional on watchlist (25-40)"
    else:
        msg += "No qualifying setups found."
    return send_telegram(msg)


def notify_scan_result(scan_number: int, total_scanned: int,
                       packet_worthy: int, watchlist: int) -> bool:
    """Alert: scan cycle result (fires every scan, not just when trades open)."""
    now = datetime.now(ET).strftime("%H:%M ET")
    msg = (
        f"📊 <b>SCAN #{scan_number}</b> ({now})\n"
        f"Scanned: {total_scanned} | Packet-worthy: {packet_worthy} | Watchlist: {watchlist}"
    )
    return send_telegram(msg)


def notify_premarket_complete(features_done: bool, training_gen: int,
                              news_scored: int, candidates: int) -> bool:
    """Alert: pre-market pipeline complete."""
    now = datetime.now(ET).strftime("%H:%M ET")
    msg = (
        f"🌅 <b>PRE-MARKET COMPLETE</b> ({now})\n"
        f"  {'✅' if features_done else '❌'} Rolling features\n"
        f"  ✅ Training examples generated: {training_gen}\n"
        f"  ✅ News items scored: {news_scored}\n"
        f"  ✅ Candidates pre-analyzed: {candidates}"
    )
    return send_telegram(msg)


def notify_vram_handoff(direction: str, success: bool, detail: str = "") -> bool:
    """Alert: VRAM transition between Ollama and PyTorch."""
    emoji = "✅" if success else "❌"
    if direction == "training":
        msg = f"{emoji} <b>VRAM → TRAINING</b>\nOllama unloaded, PyTorch subprocess launched"
    else:
        msg = f"{emoji} <b>VRAM → INFERENCE</b>\nTraining complete, Ollama loaded and warm"
    if detail:
        msg += f"\n{detail}"
    return send_telegram(msg)


def notify_overnight_training_complete(tasks_completed: int, tasks_total: int,
                                       details: dict | None = None) -> bool:
    """Alert: overnight training pipeline complete."""
    now = datetime.now(ET).strftime("%H:%M ET")
    msg = f"🌙 <b>OVERNIGHT TRAINING</b> ({now})\nTasks: {tasks_completed}/{tasks_total}"
    if details:
        for task, status in details.items():
            emoji = "✅" if status.get("success", False) else "❌"
            msg += f"\n  {emoji} {_html_escape(task)}"
            if not status.get("success", False) and status.get("error"):
                msg += f": {_html_escape(str(status['error'])[:40])}"
    return send_telegram(msg)


def notify_scoring_summary(scored_today: int, backlog: int) -> bool:
    """Alert: daily scoring summary (end of market hours)."""
    msg = (
        f"📝 <b>SCORING SUMMARY</b>\n"
        f"Scored today: {scored_today}\n"
        f"Backlog remaining: {backlog}"
    )
    return send_telegram(msg)


def notify_schedule_health(gpu_util: float, scan_delay_max: float,
                           handoff_ok: bool, temp_max: int) -> bool:
    """Alert: daily schedule health check."""
    msg = (
        f"📈 <b>SCHEDULE HEALTH</b>\n"
        f"GPU utilization: {gpu_util:.1f}%\n"
        f"Max scan delay: {scan_delay_max:.1f}s\n"
        f"VRAM handoffs: {'✅' if handoff_ok else '❌'}\n"
        f"GPU temp max: {temp_max}°C"
    )
    return send_telegram(msg)


# ── Expanded Notification Functions ───────────────────────────────────────


def notify_premarket_brief(vix: float, vix_change: float, regime: str,
                           spy_futures_pct: float, ten_year: float,
                           earnings_today: list[str],
                           fomc_days: int | None, nfp_days: int | None,
                           council_consensus: str, council_confidence: int,
                           open_paper: int, open_live: int) -> bool:
    """Alert: 6:00 AM pre-market brief with overnight context."""
    now = datetime.now(ET).strftime("%H:%M ET")

    earnings_str = ", ".join(earnings_today[:5]) if earnings_today else "None"

    event_parts = []
    if fomc_days is not None:
        event_parts.append(f"FOMC in {fomc_days} days")
    if nfp_days is not None:
        event_parts.append(f"NFP in {nfp_days} days")
    events_str = " | ".join(event_parts) if event_parts else "No major events this week"

    # #643 — both VIX-change and S&P futures pct rendered as `-0.0` on quiet
    # mornings (precision too low for fields whose typical magnitude is <0.5).
    # Operators read the leading minus + zero as broken data and panic-debug.
    # Bumped to 2 decimals so e.g. -0.04% renders as -0.04% instead of -0.0%.
    msg = (
        f"🌅 <b>PRE-MARKET BRIEF</b> ({now})\n\n"
        f"VIX: {vix:.2f} ({vix_change:+.2f}) | Regime: {regime}\n"
        f"{_html_escape('S&P')} Futures: {spy_futures_pct:+.2f}% | 10Y: {ten_year:.2f}%\n"
        f"Earnings today: {earnings_str}\n"
        f"{events_str}\n\n"
        f"Council consensus: {council_consensus.upper()} ({council_confidence}%)\n"
        f"Open positions: {open_paper} paper, {open_live} live"
    )
    return send_telegram(msg)


def notify_trainer_holdout_empty(
    train_count: int,
    most_recent_date: str,
    days_stale: int,
) -> bool:
    """#617 — alert: training holdout split was empty due to stalled corpus.

    Fires when export_training_data writes a non-empty training set but
    zero holdout examples. This happens when all examples are older than
    the 5-day temporal gap window, meaning model evaluation (canary, A/B)
    cannot run on out-of-sample data.
    """
    msg = (
        f"⚠️ <b>TRAINER HOLDOUT EMPTY</b>\n"
        f"Training examples: {train_count}\n"
        f"Holdout examples:  0\n"
        f"Corpus most recent: {most_recent_date} ({days_stale}d stale)\n"
        f"Model evaluation blocked. Run backfill or wait for collection to resume."
    )
    return send_telegram(msg)


def notify_first_scan_summary(total_scanned: int, packet_worthy: int,
                              watchlist: int, trades_opened_paper: int,
                              trades_opened_live: int,
                              top_setups: list[tuple[str, int]],
                              setup_type_counts: dict[str, int],
                              llm_success: int, llm_total: int,
                              llm_fallback: int) -> bool:
    """Alert: first scan of the day summary with richer detail."""
    now = datetime.now(ET).strftime("%H:%M ET")

    top_str = " ".join(f"{t}({s})" for t, s in top_setups[:3]) if top_setups else "None"
    setup_parts = [f"{count} {stype}" for stype, count in setup_type_counts.items()]
    setup_str = ", ".join(setup_parts) if setup_parts else "None"

    msg = (
        f"📊 <b>FIRST SCAN COMPLETE</b> ({now})\n\n"
        f"Scanned: {total_scanned} | Packet-worthy: {packet_worthy} | Watchlist: {watchlist}\n"
        f"Trades opened: {trades_opened_paper} paper, {trades_opened_live} live\n"
        f"Top setups: {top_str}\n"
        f"Setup types: {setup_str}\n\n"
        f"LLM success: {llm_success}/{llm_total}"
    )
    if llm_fallback > 0:
        msg += f" ({llm_fallback} template fallback)"
    return send_telegram(msg)


def notify_eod_report(payload: EodReportPayload) -> bool:
    """Alert: 4:00 PM end-of-day P&L report with paper/live split."""
    now = datetime.now(ET).strftime("%H:%M ET")

    msg = (
        f"📈 <b>END OF DAY</b> ({now})\n\n"
        f"Paper: {payload.paper_open} open (${payload.paper_open_pnl:+.2f}) | "
        f"{payload.paper_closed_today} closed today (${payload.paper_closed_pnl:+.2f})\n"
        f"Live:  {payload.live_open} open (${payload.live_open_pnl:+.2f}) | "
        f"{payload.live_closed_today} closed today (${payload.live_closed_pnl:+.2f})\n"
        f"Win rate (all time): {payload.win_rate:.0%} ({payload.wins}W / {payload.losses}L)\n\n"
        f"Best: {payload.best_ticker} {payload.best_pct:+.1f}% | "
        f"Worst: {payload.worst_ticker} {payload.worst_pct:+.1f}%\n"
        f"Regime: {payload.regime} | VIX: {payload.vix:.1f} ({payload.vix_change:+.1f})"
    )
    if payload.risk_qualified > 0:
        msg += (
            f"\nRisk governor: {payload.risk_qualified - payload.risk_rejected}"
            f"/{payload.risk_qualified} passed ({payload.risk_rejected} blocked)"
        )
    return send_telegram(msg)


def notify_data_asset_report(training_total: int, training_today: int,
                             training_target: int,
                             signal_zoo_total: int, signal_zoo_today: int,
                             scoring_backlog: int,
                             quality_avg: float,
                             flywheel_count: int) -> bool:
    """Alert: 4:30 PM data asset report with training example growth."""
    msg = (
        f"📦 <b>DATA ASSET REPORT</b>\n\n"
        f"Training examples: {training_total} (+{training_today} today) → target {training_target}\n"
        f"Signal zoo entries: {signal_zoo_total} (+{signal_zoo_today} today)\n"
        f"Scoring backlog: {scoring_backlog}\n"
        f"Quality avg: {quality_avg:.1f}/5.0\n\n"
    )
    if flywheel_count > 0:
        msg += f"Flywheel: ✅ {flywheel_count} new examples from closed trades"
    else:
        msg += "Flywheel: ⏸️ No new examples from closed trades today"
    return send_telegram(msg)


def notify_regime_alert(vix_now: float, vix_prev: float,
                        threshold_crossed: float,
                        regime_old: str, regime_new: str,
                        qual_old: int, qual_new: int,
                        sizing_old: int, sizing_new: int) -> bool:
    """Alert: VIX crossed a key threshold, regime may have shifted."""
    direction = "above" if vix_now > vix_prev else "below"
    msg = (
        f"⚡ <b>REGIME ALERT</b>\n\n"
        f"VIX crossed {threshold_crossed:.0f} (was {vix_prev:.1f}, now {vix_now:.1f})\n"
        f"Regime shifted: {_html_escape(regime_old)} → {_html_escape(regime_new)}\n"
        f"Qualification threshold: {qual_old} → {qual_new}\n"
        f"Position sizing: {sizing_old}% → {sizing_new}%\n\n"
        f"Action: {'Tighter' if vix_now > vix_prev else 'Looser'} filters active. "
        f"{'Fewer' if vix_now > vix_prev else 'More'} trades expected."
    )
    return send_telegram(msg)


def notify_milestone(milestone: str, detail: str) -> bool:
    """Alert: trade milestone reached (1st trade, 10th close, etc.)."""
    msg = f"🏆 <b>MILESTONE: {_html_escape(milestone)}</b>\n\n{_html_escape(detail)}"
    return send_telegram(msg)


def notify_streak_alert(streak_length: int, recent_trades: list[tuple[str, float]],
                        max_drawdown_pct: float,
                        risk_governor_status: str,
                        historical_max_streak: int) -> bool:
    """Alert: 3+ consecutive losses."""
    recent_str = ", ".join(f"{t} {p:+.1f}%" for t, p in recent_trades[:5])
    msg = (
        f"🔶 <b>STREAK ALERT: {streak_length} consecutive losses</b>\n\n"
        f"Recent: {recent_str}\n"
        f"Max drawdown: {max_drawdown_pct:+.1f}% | Risk governor: {risk_governor_status}\n"
        f"Historical streak max: {historical_max_streak}\n\n"
        f"No action required — within normal parameters."
    )
    return send_telegram(msg)


def notify_weekly_digest(payload: WeeklyDigestPayload) -> bool:
    """Alert: Sunday 8 PM weekly digest — full system summary."""
    earnings_str = ", ".join(payload.earnings_next_week[:5]) if payload.earnings_next_week else "None"
    events_str = ", ".join(payload.events_next_week[:3]) if payload.events_next_week else "None"

    msg = (
        f"📋 <b>WEEKLY DIGEST</b> ({payload.period_start}–{payload.period_end})\n\n"
        f"<b>TRADES:</b>\n"
        f"  Opened: {payload.opened_paper} paper, {payload.opened_live} live\n"
        f"  Closed: {payload.closed_paper} paper, {payload.closed_live} live\n"
        f"  Win rate: {payload.win_rate:.0%} | Expectancy: ${payload.expectancy:+.2f}\n"
        f"  Best: {payload.best_ticker} {payload.best_pct:+.1f}% | "
        f"Worst: {payload.worst_ticker} {payload.worst_pct:+.1f}%\n"
        f"  {_html_escape('P&L')}: Paper ${payload.pnl_paper:+.2f} | Live ${payload.pnl_live:+.2f}\n\n"
        f"<b>DATA ASSET:</b>\n"
        f"  Training examples: {payload.training_start} → {payload.training_end} "
        f"(+{payload.training_end - payload.training_start})\n"
        f"  Signal zoo: {payload.signal_start} → {payload.signal_end} "
        f"(+{payload.signal_end - payload.signal_start})\n"
        f"  Scoring backlog: {payload.scoring_backlog}\n"
        f"  Quality avg: {payload.quality_avg:.1f}/5.0\n\n"
        f"<b>MODEL:</b>\n"
        f"  Canary: {payload.canary_status}\n"
        f"  LLM success rate: {payload.llm_success_rate:.0%}\n\n"
        f"<b>MARKET:</b>\n"
        f"  Regime: {payload.regime}\n"
        f"  VIX: {payload.vix:.1f} (range: {payload.vix_range_low:.1f}–{payload.vix_range_high:.1f})\n"
        f"  SPY: {payload.spy_weekly_pct:+.1f}% this week\n\n"
        f"<b>COUNCIL:</b>\n"
        f"  Sessions: {payload.council_sessions}\n"
        f"  Consensus: {payload.council_consensus} (avg {payload.council_avg_confidence}% confidence)\n\n"
        f"<b>NEXT WEEK:</b>\n"
        f"  Earnings: {earnings_str}\n"
        f"  Events: {events_str}"
    )
    return send_telegram(msg)


def notify_retrain_report(model_name: str,
                          training_examples: int, prev_examples: int,
                          new_this_week: int, new_paper: int, new_live: int,
                          canary_status: str,
                          perplexity: float, prev_perplexity: float,
                          distinct2: float, prev_distinct2: float,
                          champion_challenger: str) -> bool:
    """Alert: Saturday retrain complete with canary evaluation."""
    ppl_delta = ((perplexity - prev_perplexity) / prev_perplexity * 100) if prev_perplexity else 0
    d2_delta = ((distinct2 - prev_distinct2) / prev_distinct2 * 100) if prev_distinct2 else 0

    msg = (
        f"🧠 <b>SATURDAY RETRAIN COMPLETE</b>\n\n"
        f"Model: {_html_escape(model_name)}\n"
        f"Training examples: {training_examples} (was {prev_examples})\n"
        f"New examples this week: {new_this_week} ({new_paper} paper, {new_live} live)\n\n"
        f"Canary evaluation: {canary_status}\n"
        f"  Perplexity: {perplexity:.2f} (was {prev_perplexity:.2f}, {ppl_delta:+.1f}%)\n"
        f"  Distinct-2: {distinct2:.2f} (was {prev_distinct2:.2f}, {d2_delta:+.1f}%)\n"
        f"  Verdict: {'Within normal range' if canary_status == 'STABLE' else '⚠️ Review recommended'}\n\n"
        f"Champion-challenger: {champion_challenger}"
    )
    return send_telegram(msg)


def notify_research_papers(total_new: int, top_paper: str, top_score: float) -> bool:
    """Notify about new research papers discovered."""
    if total_new == 0:
        return True
    try:
        score_value = float(top_score)
    except (TypeError, ValueError):
        score_value = 0.0
    msg = (
        f"📄 {total_new} new research papers\n"
        f"Top: {_html_escape(top_paper[:60])} (relevance: {score_value:.1f})"
    )
    return send_telegram(msg)


_RESEARCH_DIGEST_SUMMARY_LIMIT = 800


def notify_research_digest(papers_count: int, actionable_count: int,
                           digest_summary: str) -> bool:
    """Send weekly research intelligence digest."""
    if len(digest_summary) > _RESEARCH_DIGEST_SUMMARY_LIMIT:
        summary_body = _html_escape(digest_summary[:_RESEARCH_DIGEST_SUMMARY_LIMIT]) + "\n[truncated; see email digest]"
    else:
        summary_body = _html_escape(digest_summary)
    msg = (
        f"📚 <b>WEEKLY RESEARCH DIGEST</b>\n\n"
        f"Papers reviewed: {papers_count}\n"
        f"Actionable findings: {actionable_count}\n\n"
        f"{summary_body}"
    )
    return send_telegram(msg)


def notify_collection_failure(collector_name: str, consecutive_failures: int,
                              last_error: str, last_success_ago: str,
                              other_collectors: dict[str, bool]) -> bool:
    """Alert: data collector failed 3+ consecutive times."""
    others_str = " ".join(
        f"{'✅' if ok else '❌'} {name}"
        for name, ok in other_collectors.items()
    )
    msg = (
        f"🚨 <b>COLLECTION ALERT</b>\n\n"
        f"{collector_name} collector failed {consecutive_failures} consecutive times\n"
        f"Last error: {_html_escape(last_error[:80])}\n"
        f"Last success: {last_success_ago}\n\n"
        f"Other collectors: {others_str}"
    )
    return send_telegram(msg)


def notify_exposure_alert(sector: str, count: int, tickers: list[str],
                          exposure_pct: float, limit_pct: float) -> bool:
    """Alert: sector concentration exceeds limit."""
    ticker_str = ", ".join(_html_escape(t) for t in tickers[:5])
    msg = (
        f"⚠️ <b>EXPOSURE ALERT</b>\n\n"
        f"{count} positions in {_html_escape(sector)} ({ticker_str})\n"
        f"Sector exposure: {exposure_pct:.0f}% of portfolio\n"
        f"Limit: {limit_pct:.0f}%\n\n"
        f"Consider: Skip next {_html_escape(sector)} setup until exposure normalizes."
    )
    return send_telegram(msg)


def notify_position_earnings_warning(ticker: str, days_until: int,
                                     earnings_date: str, earnings_time: str,
                                     current_pnl: float, current_pnl_pct: float,
                                     expected_move_pct: float | None = None) -> bool:
    """Alert: open position has earnings within 3 trading days."""
    time_label = normalize_earnings_time(earnings_time)
    msg = (
        f"📅 <b>EARNINGS WARNING: You hold {ticker}</b>\n\n"
        f"Earnings in {days_until} days ({earnings_date} {time_label})\n"
        f"Current P&amp;L: ${current_pnl:+.2f} ({current_pnl_pct:+.1f}%)\n"
    )
    if expected_move_pct is not None:
        msg += f"Expected move: ±{expected_move_pct:.1f}% (from options IV)\n"
    msg += "\nConsider: Close before earnings or accept binary risk."
    return send_telegram(msg)


# ── Action Reminder Notifications ─────────────────────────────────────

def notify_action_required(action: str, detail: str, urgency: str = "normal") -> bool:
    """Send a Telegram notification when a manual action is needed.

    urgency: 'low', 'normal', 'high', 'critical'
    """
    icons = {"low": "📋", "normal": "🔔", "high": "⚠️", "critical": "🚨"}
    if urgency not in icons:
        raise ValueError(f"Unknown urgency '{urgency}'; must be one of {list(icons)}")
    icon = icons[urgency]
    msg = f"{icon} <b>ACTION REQUIRED</b>\n\n<b>{_html_escape(action)}</b>\n{_html_escape(detail)}"
    return send_telegram(msg)


def notify_validation_summary(result: dict, force_send: bool = False) -> bool:
    """Send system validation summary via Telegram.

    Silent if all checks pass — only sends when there are warnings or failures.
    This prevents noise during normal operation while ensuring problems
    surface immediately. Failed checks show full detail; warnings show
    only category counts to keep the message concise.

    force_send=True bypasses the silent-on-pass branch and sends regardless
    (spec C12 — startup confirmation path).
    """
    if not is_telegram_enabled():
        return False

    passed = result.get("checks_passed", 0)
    failed = result.get("checks_failed", 0)
    warnings = result.get("checks_warning", 0)
    overall = result.get("overall_status", "unknown")
    total = result.get("checks_total", 0)

    # Silent on all-pass unless force_send is requested
    if failed == 0 and warnings == 0 and not force_send:
        return True

    icon = {"healthy": "\u2705", "degraded": "\u26a0\ufe0f", "critical": "\ud83d\udea8"}.get(overall, "\u2753")

    lines = [
        f"{icon} <b>SYSTEM VALIDATION</b>",
        f"Status: <b>{overall.upper()}</b>",
        f"Passed: {passed} | Warnings: {warnings} | Failed: {failed} | Total: {total}",
        "",
    ]

    # Detail failed checks
    if failed > 0:
        lines.append("<b>Failures:</b>")
        for cat, checks in result.get("categories", {}).items():
            for c in checks:
                if c["status"] == "fail":
                    lines.append(f"  \u274c {cat}/{c['name']}: {c['detail'][:80]}")
        lines.append("")

    # Summary of warning categories
    if warnings > 0:
        warn_cats = {}
        for cat, checks in result.get("categories", {}).items():
            cnt = sum(1 for c in checks if c["status"] == "warn")
            if cnt:
                warn_cats[cat] = cnt
        if warn_cats:
            lines.append("<b>Warnings:</b> " + ", ".join(
                f"{cat}({n})" for cat, n in warn_cats.items()
            ))

    try:
        return send_telegram("\n".join(lines))
    except Exception as e:
        logger.warning(
            "[TELEGRAM] notify_validation_summary send failed: %s",
            _redact_token(e),
        )
        return False


def notify_1min_bar_collection(bars_collected: int, tickers: int,
                                empty_ticker_days: int, dates: int = 1) -> bool:
    """Alert: nightly 1-minute bar collection completed.

    Called from `scheduler.overnight.run_1min_bar_collection` after the
    yfinance batch finishes. Silent on bars_collected == 0 to avoid
    weekend spam (yfinance returns empty for non-trading days).
    """
    if not is_telegram_enabled() or bars_collected == 0:
        return False
    empty_pct = (empty_ticker_days / (tickers * dates) * 100) if tickers and dates else 0
    mb = bars_collected * 60 / (1024 * 1024)
    msg = (
        "📈 <b>1-min bars collected</b>\n"
        f"{bars_collected:,} bars across {tickers} tickers / {dates}d\n"
        f"Empty: {empty_ticker_days}/{tickers * dates} ({empty_pct:.0f}%) "
        f"| ~{mb:.1f} MB"
    )
    return send_telegram(msg)


def notify_attribution_resolve_complete(resolved: int, pending_remaining: int) -> bool:
    """Alert: nightly attribution resolver finished.

    Called from the watch loop after `resolve_pending_outcomes`. Silent on
    resolved==0 AND pending_remaining==0 (nothing to report).
    """
    if not is_telegram_enabled():
        return False
    if resolved == 0 and pending_remaining == 0:
        return True
    icon = "✅" if resolved > 0 else "⏳"
    msg = (
        f"{icon} <b>Attribution resolver</b>\n"
        f"Resolved: {resolved} | Still pending: {pending_remaining}"
    )
    return send_telegram(msg)


def notify_stress_test_complete(scenarios_run: int, passed: int, failed: int,
                                 notes: str = "") -> bool:
    """Alert: stress-test re-run completed (triggered by model version change).

    Called from the 7 PM overnight handler when the active model rolls
    over. Always sends — stress test failures are actionable.
    """
    if not is_telegram_enabled():
        return False
    icon = "✅" if failed == 0 else "🚨"
    msg = (
        f"{icon} <b>STRESS TEST</b>\n"
        f"{scenarios_run} scenarios | {passed} passed | {failed} failed"
    )
    if notes:
        msg += f"\n{notes}"
    return send_telegram(msg)


def notify_trading_stats_update(stats: dict, label: str = "") -> bool:
    """Periodic stats pulse: trade count + win rate + PnL + excess vs SPY
    across today / 7d / 30d / all-time windows.

    `stats` is the dict returned by `src.journal.stats.compute_all_window_stats`.
    `label` is an optional header suffix (e.g. "PRE-MARKET", "MIDDAY", "POST-CLOSE").

    Silent on an empty database — if all four windows show count == 0 we
    skip the send so fresh deployments don't spam the channel.
    """
    if not is_telegram_enabled():
        return False
    if all(w.get("count", 0) == 0 for w in stats.values()):
        return True  # silent — nothing to report yet

    header = "📊 <b>TRADING STATS"
    if label:
        header += f" — {label.upper()}"
    header += "</b>"
    lines = [header]

    order = [
        ("today", "Today"),
        ("7d", "7d"),
        ("30d", "30d"),
        ("all_time", "All-time"),
    ]
    for key, name in order:
        w = stats.get(key) or {}
        count = w.get("count", 0)
        if count == 0:
            lines.append(f"<b>{name}:</b> — (0 trades)")
            continue
        wr = w.get("win_rate")
        wr_str = f"{wr:.0%}" if wr is not None else "—"
        avg_pct = w.get("avg_pnl_pct")
        avg_str = f"{avg_pct:+.2f}%" if avg_pct is not None else "—"
        total = w.get("total_pnl_dollars") or 0.0
        excess = w.get("avg_excess_return")
        excess_str = f" | excess {excess:+.2f}%" if excess is not None else ""
        sharpe = w.get("excess_sharpe")
        sharpe_str = f" | ex-Sharpe {sharpe:.2f}" if sharpe is not None else ""
        lines.append(
            f"<b>{name}:</b> {count} trades | WR {wr_str} | "
            f"avg {avg_str} | PnL ${total:+.2f}{excess_str}{sharpe_str}"
        )
    lines.append(
        "\n<i>Excess = pnl_pct − SPY return over hold. "
        "ex-Sharpe shown once ≥10 closed trades in the window.</i>"
    )
    return send_telegram("\n".join(lines))


def notify_manual_intervention_drift(payload: dict, severity: str = "high") -> bool:
    """Telegram alert for manual-intervention drift (Wave C T4 / #45).

    Fires when the operator closes a paper position in the Alpaca dashboard
    but the local shadow_trade row still shows active.

    Args:
        payload: DriftFinding.as_dict() — must contain ticker, expected_state,
                 actual_state, divergence_age_minutes.
        severity: Alert severity, passed through from the watch-loop caller.
                  Do NOT hardcode 'high' here — severity is determined at the
                  call site (watch.py tick_drift_detector).
    """
    ticker = _html_escape(payload.get("ticker", "UNKNOWN"))
    expected = _html_escape(payload.get("expected_state", "?"))
    actual = _html_escape(payload.get("actual_state", "?"))
    age = payload.get("divergence_age_minutes", 0)
    sev_label = _html_escape(severity.upper())
    msg = (
        f"⚠ [{sev_label}] Drift detected — {ticker}: "
        f"expected {expected} (broker), actual {actual} (db), "
        f"age {age:.0f} min"
    )
    return send_telegram(msg)


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
    "vram_handoff": notify_vram_handoff,
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
    # Additional event types
    "alert_silence": notify_system_event,
}
_EVENT_MAP = MappingProxyType(_EVENT_MAP_MUTABLE)

# Overwrite the placeholder frozenset now that _EVENT_MAP is populated.
_KNOWN_EVENT_TYPES = frozenset(_EVENT_MAP)

# CC3: payload-type events pass a single `payload` positional argument.
_PAYLOAD_EVENTS = frozenset({"trade_opened", "trade_closed", "eod_report", "weekly_digest"})


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
            result = notify_fn(payload["payload"])
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
            if send_email(subject=subject, body=body):
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
