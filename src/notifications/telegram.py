"""Telegram notification client for Arcis.

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
"""

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

import requests

from src.config import load_config

logger = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")

TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"


def _get_telegram_config() -> dict:
    """Load Telegram config from settings."""
    config = load_config()
    tg = config.get("telegram", {})
    return {
        "enabled": tg.get("enabled", False),
        "bot_token": tg.get("bot_token", ""),
        "chat_id": str(tg.get("chat_id", "")),
    }


def is_telegram_enabled() -> bool:
    """Check if Telegram notifications are configured and enabled."""
    cfg = _get_telegram_config()
    return cfg["enabled"] and bool(cfg["bot_token"]) and bool(cfg["chat_id"])


def send_telegram(message: str, parse_mode: str = "HTML") -> bool:
    """Send a message via Telegram Bot API.

    Args:
        message: Text to send (supports HTML formatting)
        parse_mode: "HTML" or "Markdown"

    Returns True on success, False on failure.
    """
    cfg = _get_telegram_config()
    if not cfg["enabled"] or not cfg["bot_token"] or not cfg["chat_id"]:
        return False

    try:
        url = TELEGRAM_API.format(token=cfg["bot_token"])
        resp = requests.post(
            url,
            json={
                "chat_id": cfg["chat_id"],
                "text": message,
                "parse_mode": parse_mode,
                "disable_web_page_preview": True,
            },
            timeout=10,
        )
        if resp.status_code == 200:
            return True
        else:
            logger.warning("[TELEGRAM] Send failed: %s %s", resp.status_code, resp.text[:200])
            return False
    except Exception as e:
        logger.warning("[TELEGRAM] Send error: %s", e)
        return False


# ── Pre-formatted alert functions ─────────────────────────────────────────


def notify_trade_opened(ticker: str, entry_price: float, stop: float,
                        target: float, score: int, shares: int,
                        setup_type: str | None = None,
                        setup_confidence: float | None = None,
                        source: str = "paper") -> bool:
    """Alert: new trade opened.

    Args:
        source: "paper" or "live" — controls header emoji and label.
    """
    pnl_risk = (entry_price - stop) * shares

    # Build header with source distinction
    if source == "live":
        header = f"🟢💰 <b>LIVE TRADE OPENED: {ticker}"
    else:
        header = f"🟢 <b>TRADE OPENED: {ticker}"

    if setup_type and setup_confidence is not None:
        header += f" ({setup_type} ↑{setup_confidence:.2f})"
    elif setup_type:
        header += f" ({setup_type})"
    header += "</b>"

    msg = (
        f"{header}\n"
        f"Entry: ${entry_price:.2f} | Stop: ${stop:.2f} | Target: ${target:.2f}\n"
        f"Shares: {shares} | Risk: ${pnl_risk:.2f}\n"
        f"Score: {score}/100"
    )
    return send_telegram(msg)


def notify_trade_closed(ticker: str, pnl_dollars: float, pnl_pct: float,
                        exit_reason: str, days_held: int,
                        source: str = "paper") -> bool:
    """Alert: trade closed."""
    emoji = "🟢" if pnl_dollars >= 0 else "🔴"
    label = "LIVE TRADE CLOSED" if source == "live" else "TRADE CLOSED"
    msg = (
        f"{emoji} <b>{label}: {ticker}</b>\n"
        f"P&L: ${pnl_dollars:+.2f} ({pnl_pct:+.1f}%)\n"
        f"Reason: {exit_reason} | Held: {days_held} days"
    )
    return send_telegram(msg)


def notify_scan_complete(packets_count: int, trades_opened: int,
                         trades_closed: int) -> bool:
    """Alert: scan cycle complete (only if something happened)."""
    if packets_count == 0 and trades_opened == 0 and trades_closed == 0:
        return True  # Skip silent scans
    msg = (
        f"📊 <b>SCAN COMPLETE</b>\n"
        f"Packets: {packets_count} | Opened: {trades_opened} | Closed: {trades_closed}"
    )
    return send_telegram(msg)


def notify_risk_alert(alert_type: str, detail: str) -> bool:
    """Alert: risk governor event."""
    msg = f"⚠️ <b>RISK ALERT: {alert_type}</b>\n{detail}"
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
        if isinstance(val, str) and "error" in val.lower():
            lines.append(f"  ❌ {key}: {val[:60]}")
        else:
            lines.append(f"  ✅ {key}")
    return send_telegram("\n".join(lines))


def notify_system_event(event: str, detail: str = "") -> bool:
    """Alert: general system event."""
    msg = f"🔧 <b>{event}</b>"
    if detail:
        msg += f"\n{detail}"
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
    msg = f"🧠 <b>MODEL: {event}</b>\nModel: {model_name}"
    if detail:
        msg += f"\n{detail}"
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
            msg += f"\n  {emoji} {task}"
            if not status.get("success", False) and status.get("error"):
                msg += f": {str(status['error'])[:40]}"
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

    msg = (
        f"🌅 <b>PRE-MARKET BRIEF</b> ({now})\n\n"
        f"VIX: {vix:.2f} ({vix_change:+.1f}) | Regime: {regime}\n"
        f"S&amp;P Futures: {spy_futures_pct:+.1f}% | 10Y: {ten_year:.2f}%\n"
        f"Earnings today: {earnings_str}\n"
        f"{events_str}\n\n"
        f"Council consensus: {council_consensus.upper()} ({council_confidence}%)\n"
        f"Open positions: {open_paper} paper, {open_live} live"
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


def notify_eod_report(paper_open: int, paper_open_pnl: float,
                      paper_closed_today: int, paper_closed_pnl: float,
                      live_open: int, live_open_pnl: float,
                      live_closed_today: int, live_closed_pnl: float,
                      win_rate: float, wins: int, losses: int,
                      best_ticker: str, best_pct: float,
                      worst_ticker: str, worst_pct: float,
                      regime: str, vix: float, vix_change: float) -> bool:
    """Alert: 4:00 PM end-of-day P&L report with paper/live split."""
    now = datetime.now(ET).strftime("%H:%M ET")

    msg = (
        f"📈 <b>END OF DAY</b> ({now})\n\n"
        f"Paper: {paper_open} open (${paper_open_pnl:+.2f}) | "
        f"{paper_closed_today} closed today (${paper_closed_pnl:+.2f})\n"
        f"Live:  {live_open} open (${live_open_pnl:+.2f}) | "
        f"{live_closed_today} closed today (${live_closed_pnl:+.2f})\n"
        f"Win rate (all time): {win_rate:.0%} ({wins}W / {losses}L)\n\n"
        f"Best: {best_ticker} {best_pct:+.1f}% | Worst: {worst_ticker} {worst_pct:+.1f}%\n"
        f"Regime: {regime} | VIX: {vix:.1f} ({vix_change:+.1f})"
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
        f"Regime shifted: {regime_old} → {regime_new}\n"
        f"Qualification threshold: {qual_old} → {qual_new}\n"
        f"Position sizing: {sizing_old}% → {sizing_new}%\n\n"
        f"Action: {'Tighter' if vix_now > vix_prev else 'Looser'} filters active. "
        f"{'Fewer' if vix_now > vix_prev else 'More'} trades expected."
    )
    return send_telegram(msg)


def notify_milestone(milestone: str, detail: str) -> bool:
    """Alert: trade milestone reached (1st trade, 10th close, etc.)."""
    msg = f"🏆 <b>MILESTONE: {milestone}</b>\n\n{detail}"
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


def notify_weekly_digest(
    period_start: str, period_end: str,
    # Trades
    opened_paper: int, opened_live: int,
    closed_paper: int, closed_live: int,
    win_rate: float, expectancy: float,
    best_ticker: str, best_pct: float,
    worst_ticker: str, worst_pct: float,
    pnl_paper: float, pnl_live: float,
    # Data asset
    training_start: int, training_end: int,
    signal_start: int, signal_end: int,
    scoring_backlog: int, quality_avg: float,
    # Model
    canary_status: str, llm_success_rate: float,
    # Market
    regime: str, vix: float, vix_range_low: float, vix_range_high: float,
    spy_weekly_pct: float,
    # Council
    council_sessions: int, council_consensus: str, council_avg_confidence: int,
    # Next week
    earnings_next_week: list[str], events_next_week: list[str],
) -> bool:
    """Alert: Sunday 8 PM weekly digest — full system summary."""
    earnings_str = ", ".join(earnings_next_week[:5]) if earnings_next_week else "None"
    events_str = ", ".join(events_next_week[:3]) if events_next_week else "None"

    msg = (
        f"📋 <b>WEEKLY DIGEST</b> ({period_start}–{period_end})\n\n"
        f"<b>TRADES:</b>\n"
        f"  Opened: {opened_paper} paper, {opened_live} live\n"
        f"  Closed: {closed_paper} paper, {closed_live} live\n"
        f"  Win rate: {win_rate:.0%} | Expectancy: ${expectancy:+.2f}\n"
        f"  Best: {best_ticker} {best_pct:+.1f}% | Worst: {worst_ticker} {worst_pct:+.1f}%\n"
        f"  P&amp;L: Paper ${pnl_paper:+.2f} | Live ${pnl_live:+.2f}\n\n"
        f"<b>DATA ASSET:</b>\n"
        f"  Training examples: {training_start} → {training_end} (+{training_end - training_start})\n"
        f"  Signal zoo: {signal_start} → {signal_end} (+{signal_end - signal_start})\n"
        f"  Scoring backlog: {scoring_backlog}\n"
        f"  Quality avg: {quality_avg:.1f}/5.0\n\n"
        f"<b>MODEL:</b>\n"
        f"  Canary: {canary_status}\n"
        f"  LLM success rate: {llm_success_rate:.0%}\n\n"
        f"<b>MARKET:</b>\n"
        f"  Regime: {regime}\n"
        f"  VIX: {vix:.1f} (range: {vix_range_low:.1f}–{vix_range_high:.1f})\n"
        f"  SPY: {spy_weekly_pct:+.1f}% this week\n\n"
        f"<b>COUNCIL:</b>\n"
        f"  Sessions: {council_sessions}\n"
        f"  Consensus: {council_consensus} (avg {council_avg_confidence}% confidence)\n\n"
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
        f"Model: {model_name}\n"
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
    msg = (
        f"📄 {total_new} new research papers\n"
        f"Top: {top_paper[:60]} (relevance: {top_score:.1f})"
    )
    return send_telegram(msg)


def notify_research_digest(papers_count: int, actionable_count: int,
                           digest_summary: str) -> bool:
    """Send weekly research intelligence digest."""
    msg = (
        f"📚 <b>WEEKLY RESEARCH DIGEST</b>\n\n"
        f"Papers reviewed: {papers_count}\n"
        f"Actionable findings: {actionable_count}\n\n"
        f"{digest_summary[:800]}"
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
        f"Last error: {last_error[:80]}\n"
        f"Last success: {last_success_ago}\n\n"
        f"Other collectors: {others_str}"
    )
    return send_telegram(msg)


def notify_exposure_alert(sector: str, count: int, tickers: list[str],
                          exposure_pct: float, limit_pct: float) -> bool:
    """Alert: sector concentration exceeds limit."""
    ticker_str = ", ".join(tickers[:5])
    msg = (
        f"⚠️ <b>EXPOSURE ALERT</b>\n\n"
        f"{count} positions in {sector} ({ticker_str})\n"
        f"Sector exposure: {exposure_pct:.0f}% of portfolio\n"
        f"Limit: {limit_pct:.0f}%\n\n"
        f"Consider: Skip next {sector} setup until exposure normalizes."
    )
    return send_telegram(msg)


def notify_position_earnings_warning(ticker: str, days_until: int,
                                     earnings_date: str, earnings_time: str,
                                     current_pnl: float, current_pnl_pct: float,
                                     expected_move_pct: float | None = None) -> bool:
    """Alert: open position has earnings within 3 trading days."""
    time_label = "BMO" if earnings_time and "before" in earnings_time.lower() else (
        "AMC" if earnings_time and "after" in earnings_time.lower() else earnings_time or "TBD"
    )
    msg = (
        f"📅 <b>EARNINGS WARNING: You hold {ticker}</b>\n\n"
        f"Earnings in {days_until} days ({earnings_date} {time_label})\n"
        f"Current P&amp;L: ${current_pnl:+.2f} ({current_pnl_pct:+.1f}%)\n"
    )
    if expected_move_pct is not None:
        msg += f"Expected move: ±{expected_move_pct:.1f}% (from options IV)\n"
    msg += "\nConsider: Close before earnings or accept binary risk."
    return send_telegram(msg)


# ── Telegram Command Handler ──────────────────────────────────────────────

TELEGRAM_UPDATES_API = "https://api.telegram.org/bot{token}/getUpdates"


def poll_commands(last_update_id: int = 0) -> tuple[list[dict], int]:
    """Poll for incoming Telegram commands.

    Returns (commands, new_last_update_id).
    Each command is {"command": "/status", "args": "", "chat_id": "123"}.
    """
    cfg = _get_telegram_config()
    if not cfg["enabled"] or not cfg["bot_token"]:
        return [], last_update_id

    try:
        url = TELEGRAM_UPDATES_API.format(token=cfg["bot_token"])
        resp = requests.get(
            url,
            params={"offset": last_update_id + 1, "timeout": 1},
            timeout=5,
        )
        if resp.status_code != 200:
            return [], last_update_id

        data = resp.json()
        if not data.get("ok") or not data.get("result"):
            return [], last_update_id

        commands = []
        new_id = last_update_id
        for update in data["result"]:
            new_id = max(new_id, update["update_id"])
            msg = update.get("message", {})
            text = msg.get("text", "")
            chat_id = str(msg.get("chat", {}).get("id", ""))

            # Only process commands from our authorized chat
            if chat_id != cfg["chat_id"]:
                continue

            if text.startswith("/"):
                parts = text.split(maxsplit=1)
                cmd = parts[0].lower().split("@")[0]  # Strip @botname
                args = parts[1] if len(parts) > 1 else ""
                commands.append({"command": cmd, "args": args, "chat_id": chat_id})

        return commands, new_id

    except Exception as e:
        logger.debug("[TELEGRAM] Poll error: %s", e)
        return [], last_update_id


# ── Action Reminder Notifications ─────────────────────────────────────

def notify_action_required(action: str, detail: str, urgency: str = "normal") -> bool:
    """Send a Telegram notification when a manual action is needed.

    urgency: 'low', 'normal', 'high', 'critical'
    """
    icons = {"low": "📋", "normal": "🔔", "high": "⚠️", "critical": "🚨"}
    icon = icons.get(urgency, "🔔")
    msg = f"{icon} <b>ACTION REQUIRED</b>\n\n<b>{action}</b>\n{detail}"
    return send_telegram(msg)


def check_action_reminders(db_path: str = "ai_research_desk.sqlite3") -> list[str]:
    """Check all conditions that require manual action. Returns list of actions sent.

    Called daily at 8 PM from the watch loop. Checks:
    1. Phase gate milestone reached (50/100/200 closed trades)
    2. Sunday review ritual reminder (Sundays at 5 PM)
    3. API key rotation (every 90 days)
    4. Unscored training examples accumulating
    5. Reconcile needed (Alpaca vs DB divergence)
    6. Saturday retrain didn't fire
    """
    import sqlite3
    sent = []
    now = datetime.now(ET)

    try:
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row

            # 1. Phase gate milestones
            closed = conn.execute(
                "SELECT COUNT(*) as c FROM shadow_trades WHERE status = 'closed'"
            ).fetchone()
            closed_count = closed["c"] if closed else 0

            for milestone in [50, 100, 200, 500]:
                if closed_count >= milestone:
                    # Check if we already notified for this milestone
                    already = conn.execute(
                        "SELECT COUNT(*) as c FROM activity_log "
                        "WHERE event_type = 'gate_milestone' AND detail LIKE ?",
                        (f"%{milestone}%",),
                    ).fetchone()
                    if not (already and already["c"] > 0):
                        notify_action_required(
                            f"Phase gate: {milestone} closed trades reached!",
                            f"You have {closed_count} closed trades.\n"
                            f"Run: <code>python -m src.main evaluate-gate</code>\n"
                            f"Then review results with Claude.",
                            urgency="high",
                        )
                        try:
                            conn.execute(
                                "INSERT INTO activity_log (event_type, detail, created_at) "
                                "VALUES (?, ?, ?)",
                                ("gate_milestone", f"Notified {milestone} trades", now.isoformat()),
                            )
                            conn.commit()
                        except Exception as e:
                            logger.warning("[TELEGRAM] gate_milestone activity_log insert failed: %s", e)
                        sent.append(f"gate_{milestone}")
                    break  # Only notify for highest milestone

            # 2. Sunday review ritual (5 PM Sundays)
            if now.weekday() == 6 and now.hour == 17:
                notify_action_required(
                    "Weekly review ritual",
                    "Export 20 recent training examples + arcis.log + dashboard screenshots.\n"
                    "Review with Claude for format drift, look-ahead bias, regime gaps.\n"
                    "Prepare Monday action items.",
                    urgency="normal",
                )
                sent.append("sunday_review")

            # 3. API key rotation (check every 90 days)
            last_rotation = conn.execute(
                "SELECT detail FROM activity_log "
                "WHERE event_type = 'api_key_rotation' ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
            if not last_rotation:
                # Never rotated — remind after system has been running 90 days
                oldest_trade = conn.execute(
                    "SELECT MIN(created_at) as first FROM shadow_trades"
                ).fetchone()
                if oldest_trade and oldest_trade["first"]:
                    from datetime import datetime as dt
                    try:
                        first = dt.fromisoformat(oldest_trade["first"].replace("Z", "+00:00"))
                        if (now - first.replace(tzinfo=ET if first.tzinfo is None else first.tzinfo)).days >= 90:
                            notify_action_required(
                                "Rotate API keys (90-day reminder)",
                                "Rotate: Alpaca, Anthropic, Finnhub, Polygon (if active).\n"
                                "Update config/settings.local.yaml and Render env vars.\n"
                                "Log: <code>python -m src.main log-activity api_key_rotation 'Rotated all keys'</code>",
                                urgency="normal",
                            )
                            sent.append("api_rotation")
                    except Exception as e:
                        logger.warning("[TELEGRAM] api_rotation date check failed: %s", e)

            # 4. Unscored training examples
            unscored = conn.execute(
                "SELECT COUNT(*) as c FROM training_examples "
                "WHERE quality_score_auto IS NULL OR quality_score_auto = 0"
            ).fetchone()
            unscored_count = unscored["c"] if unscored else 0
            if unscored_count > 100:
                notify_action_required(
                    f"Score training data ({unscored_count} unscored)",
                    f"{unscored_count} training examples need quality scoring.\n"
                    f"Run: <code>python -m src.main score-training-data</code>\n"
                    f"Cost: ~${unscored_count * 0.008:.2f} (Claude API)",
                    urgency="low",
                )
                sent.append("score_training")

            # 5. Saturday retrain check (Sundays — did Saturday retrain happen?)
            if now.weekday() == 6 and now.hour >= 10:
                active = conn.execute(
                    "SELECT version_name, created_at FROM model_versions "
                    "WHERE status = 'active' ORDER BY created_at DESC LIMIT 1"
                ).fetchone()
                if active:
                    try:
                        from datetime import datetime as dt
                        created = dt.fromisoformat(active["created_at"].replace("Z", "+00:00"))
                        days_since = (now - created.replace(tzinfo=ET if created.tzinfo is None else created.tzinfo)).days
                        if days_since > 14:
                            notify_action_required(
                                f"Model retrain overdue ({days_since} days)",
                                f"Last retrain: {active['created_at'][:10]} ({active['version_name']})\n"
                                f"Run: <code>python -m src.main train --force</code>\n"
                                f"Or check Saturday overnight schedule logs.",
                                urgency="high",
                            )
                            sent.append("retrain_overdue")
                    except Exception as e:
                        logger.warning("[TELEGRAM] retrain_overdue date check failed: %s", e)

    except Exception as e:
        logger.debug("[TELEGRAM] Action reminder check failed: %s", e)

    return sent


def handle_command(command: str, args: str) -> str:
    """Process a Telegram command and return the response text.

    Available commands:
    /status — System status summary
    /trades — Open trades list
    /pnl — Current P&L
    /scan — Last scan results
    /earnings — Upcoming earnings
    /schedule — Compute schedule status
    /scoring — Scoring backlog
    /council — Run AI council session
    /help — List commands
    """
    try:
        if command == "/help" or command == "/start":
            return (
                "🤖 <b>ARCIS COMMANDS</b>\n\n"
                "/status — System status\n"
                "/trades — Open trades\n"
                "/pnl — Current P&L\n"
                "/scan — Last scan result\n"
                "/earnings — Upcoming earnings\n"
                "/schedule — Compute schedule\n"
                "/scoring — Scoring backlog\n"
                "/council — Run AI council session\n"
                "/health — GPU & system health\n"
                "/log — Recent activity log\n"
                "/pull — Git pull latest code\n"
                "/logs — Last 20 lines of arcis.log\n"
                "/gpu — GPU details (nvidia-smi)\n"
                "/disk — Disk usage\n"
                "/uptime — Watch loop uptime\n"
                "/help — This message"
            )

        elif command == "/status":
            return _cmd_status()
        elif command == "/trades":
            return _cmd_trades()
        elif command == "/pnl":
            return _cmd_pnl()
        elif command == "/scan":
            return _cmd_last_scan()
        elif command == "/earnings":
            return _cmd_earnings()
        elif command == "/schedule":
            return _cmd_schedule()
        elif command == "/scoring":
            return _cmd_scoring()
        elif command == "/council":
            return _cmd_council(args)
        elif command == "/health":
            return _cmd_health()
        elif command == "/log":
            return _cmd_log()
        elif command == "/pull":
            return _cmd_pull()
        elif command == "/logs":
            return _cmd_logs()
        elif command == "/gpu":
            return _cmd_gpu()
        elif command == "/disk":
            return _cmd_disk()
        elif command == "/uptime":
            return _cmd_uptime()
        else:
            return f"Unknown command: {command}\nSend /help for available commands."

    except Exception as e:
        return f"❌ Error: {str(e)[:200]}"


def _cmd_status() -> str:
    """System status summary."""
    now = datetime.now(ET)

    # Check Ollama directly instead of importing is_llm_available
    try:
        resp = requests.get("http://localhost:11434/api/tags", timeout=3)
        llm_ok = resp.status_code == 200
    except Exception as e:
        logger.warning("[TELEGRAM] _cmd_status Ollama check failed: %s", e)
        llm_ok = False

    try:
        from src.training.versioning import get_active_model_name, get_training_example_counts
        model = get_active_model_name()
        counts = get_training_example_counts()
        total = counts['total']
    except Exception as e:
        logger.warning("[TELEGRAM] _cmd_status model info failed: %s", e)
        model = "unknown"
        total = "?"

    market_open = 9 <= now.hour < 16 and now.weekday() < 5

    return (
        f"🔧 <b>SYSTEM STATUS</b> ({now.strftime('%H:%M ET')})\n"
        f"LLM: {'✅' if llm_ok else '❌'} {model}\n"
        f"Training examples: {total}\n"
        f"Market: {'Open' if market_open else 'Closed'}"
    )


def _cmd_trades() -> str:
    """List open trades with paper/live split."""
    import sqlite3
    try:
        with sqlite3.connect("ai_research_desk.sqlite3") as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """SELECT ticker, entry_price, pnl_pct, pnl_dollars, created_at,
                       COALESCE(source, 'paper') as source
                FROM shadow_trades WHERE status = 'open'
                ORDER BY source DESC, created_at DESC"""
            ).fetchall()

        if not rows:
            return "📭 No open trades."

        paper_trades = [r for r in rows if r["source"] == "paper"]
        live_trades = [r for r in rows if r["source"] == "live"]

        lines = [f"📊 <b>OPEN TRADES</b> ({len(rows)})"]

        if live_trades:
            lines.append(f"\n💰 <b>LIVE</b> ({len(live_trades)}):")
            for r in live_trades:
                emoji = "🟢" if (r["pnl_pct"] or 0) >= 0 else "🔴"
                pnl = r["pnl_pct"] or 0
                try:
                    from datetime import datetime
                    opened = datetime.fromisoformat(r["created_at"][:19])
                    days = (datetime.now() - opened).days
                except Exception as e:
                    logger.warning("[TELEGRAM] _cmd_trades live days_held calc failed: %s", e)
                    days = "?"
                lines.append(
                    f"  {emoji} {r['ticker']}: ${r['entry_price']:.2f} "
                    f"({pnl:+.1f}%) Day {days}"
                )

        if paper_trades:
            lines.append(f"\n📝 <b>PAPER</b> ({len(paper_trades)}):")
            for r in paper_trades:
                emoji = "🟢" if (r["pnl_pct"] or 0) >= 0 else "🔴"
                pnl = r["pnl_pct"] or 0
                try:
                    from datetime import datetime
                    opened = datetime.fromisoformat(r["created_at"][:19])
                    days = (datetime.now() - opened).days
                except Exception as e:
                    logger.warning("[TELEGRAM] _cmd_trades paper days_held calc failed: %s", e)
                    days = "?"
                lines.append(
                    f"  {emoji} {r['ticker']}: ${r['entry_price']:.2f} "
                    f"({pnl:+.1f}%) Day {days}"
                )

        return "\n".join(lines)
    except Exception as e:
        return f"📭 No open trades or error: {e}"


def _cmd_pnl() -> str:
    """Current P&L summary with paper/live split."""
    import sqlite3
    try:
        with sqlite3.connect("ai_research_desk.sqlite3") as conn:
            conn.row_factory = sqlite3.Row

            # Overall stats
            open_row = conn.execute(
                """SELECT COUNT(*) as cnt, COALESCE(SUM(pnl_dollars), 0) as total_pnl
                FROM shadow_trades WHERE status = 'open'"""
            ).fetchone()

            closed_row = conn.execute(
                """SELECT COUNT(*) as cnt, COALESCE(SUM(pnl_dollars), 0) as total_pnl,
                   COALESCE(AVG(CASE WHEN pnl_dollars > 0 THEN 1.0 ELSE 0.0 END), 0) as win_rate
                FROM shadow_trades WHERE status = 'closed'"""
            ).fetchone()

            # Live-specific stats
            live_open = conn.execute(
                """SELECT COUNT(*) as cnt, COALESCE(SUM(pnl_dollars), 0) as total_pnl
                FROM shadow_trades WHERE status = 'open' AND source = 'live'"""
            ).fetchone()

            live_closed = conn.execute(
                """SELECT COUNT(*) as cnt, COALESCE(SUM(pnl_dollars), 0) as total_pnl,
                   COALESCE(AVG(CASE WHEN pnl_dollars > 0 THEN 1.0 ELSE 0.0 END), 0) as win_rate
                FROM shadow_trades WHERE status = 'closed' AND source = 'live'"""
            ).fetchone()

        open_pnl = open_row["total_pnl"]
        closed_pnl = closed_row["total_pnl"]
        total = open_pnl + closed_pnl
        emoji = "🟢" if total >= 0 else "🔴"

        lines = [
            f"{emoji} <b>P&L SUMMARY</b>",
            f"Open: {open_row['cnt']} trades, ${open_pnl:+.2f}",
            f"Closed: {closed_row['cnt']} trades, ${closed_pnl:+.2f}",
            f"Win rate: {closed_row['win_rate']:.0%}",
            f"Total: ${total:+.2f}",
        ]

        # Show live breakdown if any live trades exist
        live_total_cnt = live_open["cnt"] + live_closed["cnt"]
        if live_total_cnt > 0:
            live_pnl = live_open["total_pnl"] + live_closed["total_pnl"]
            live_emoji = "🟢" if live_pnl >= 0 else "🔴"
            lines.append(f"\n💰 <b>LIVE</b>: {live_emoji} ${live_pnl:+.2f}")
            lines.append(f"  Open: {live_open['cnt']} | Closed: {live_closed['cnt']}")
            if live_closed["cnt"] > 0:
                lines.append(f"  Win rate: {live_closed['win_rate']:.0%}")

            # Paper = total minus live
            paper_pnl = total - live_pnl
            paper_emoji = "🟢" if paper_pnl >= 0 else "🔴"
            paper_open = open_row["cnt"] - live_open["cnt"]
            paper_closed = closed_row["cnt"] - live_closed["cnt"]
            lines.append(f"\n📝 <b>PAPER</b>: {paper_emoji} ${paper_pnl:+.2f}")
            lines.append(f"  Open: {paper_open} | Closed: {paper_closed}")

        return "\n".join(lines)
    except Exception as e:
        logger.warning("[TELEGRAM] _cmd_pnl failed: %s", e)
        return "No P&L data available yet."


def _cmd_last_scan() -> str:
    """Last scan result."""
    import sqlite3
    try:
        with sqlite3.connect("ai_research_desk.sqlite3") as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """SELECT ticker, priority_score, created_at
                FROM recommendations ORDER BY created_at DESC LIMIT 5"""
            ).fetchall()

        if not rows:
            return "📭 No scans yet."

        lines = ["📊 <b>RECENT RECOMMENDATIONS</b>"]
        for r in rows:
            score = r["priority_score"] or 0
            lines.append(f"  • {r['ticker']} (score: {score:.0f}) — {r['created_at'][:16]}")
        return "\n".join(lines)
    except Exception as e:
        logger.warning("[TELEGRAM] _cmd_last_scan failed: %s", e)
        return "📭 No scan data available yet."


def _cmd_earnings() -> str:
    """Upcoming earnings."""
    try:
        from scripts.fetch_earnings_calendar import get_all_upcoming_earnings
        upcoming = get_all_upcoming_earnings(days=14)
        if not upcoming:
            return "📅 No earnings in the next 14 days."

        lines = [f"📅 <b>EARNINGS (next 14 days)</b> — {len(upcoming)} stocks"]
        for item in upcoming[:15]:
            lines.append(
                f"  • {item['ticker']} — {item['earnings_date']} "
                f"({item['days_away']}d) {item.get('earnings_time') or ''}"
            )
        if len(upcoming) > 15:
            lines.append(f"  ...and {len(upcoming) - 15} more")
        return "\n".join(lines)
    except Exception as e:
        return f"📅 Earnings data unavailable: {e}"


def _cmd_schedule() -> str:
    """Compute schedule status."""
    now = datetime.now(ET)
    hour = now.hour

    if 9 <= hour < 16 and now.weekday() < 5:
        phase = "🟢 MARKET HOURS — Scanning + between-scan scoring"
    elif 5 <= hour < 9:
        phase = "🌅 PRE-MARKET — Features, training gen, news scoring"
    elif 16 <= hour < 19:
        phase = "📝 POST-MARKET — Scoring, DPO generation"
    elif 19 <= hour or hour < 5:
        phase = "🌙 OVERNIGHT — Training pipeline active"
    else:
        phase = "⏸️ TRANSITION"

    return (
        f"⏰ <b>COMPUTE SCHEDULE</b> ({now.strftime('%H:%M ET')})\n"
        f"Phase: {phase}\n"
        f"Day: {'Weekday' if now.weekday() < 5 else 'Weekend'}\n"
        f"Target utilization: 73%"
    )


def _cmd_scoring() -> str:
    """Scoring backlog status."""
    import sqlite3
    try:
        with sqlite3.connect("ai_research_desk.sqlite3") as conn:
            total = conn.execute(
                "SELECT COUNT(*) FROM training_examples"
            ).fetchone()[0]
            scored = conn.execute(
                "SELECT COUNT(*) FROM training_examples WHERE quality_score IS NOT NULL"
            ).fetchone()[0]
            unscored = total - scored

        return (
            f"📝 <b>SCORING STATUS</b>\n"
            f"Total examples: {total}\n"
            f"Scored: {scored}\n"
            f"Backlog: {unscored}"
        )
    except Exception as e:
        logger.warning("[TELEGRAM] _cmd_scoring failed: %s", e)
        return "📝 No scoring data available."


def _cmd_council(question: str = "") -> str:
    """Run an AI council session and format the result.

    If a question is provided (e.g., /council Should we buy the 3090?),
    runs a strategic session. Otherwise runs a daily tactical session.
    """
    try:
        from src.council.engine import CouncilEngine
        engine = CouncilEngine()

        if question.strip():
            result = engine.run_session(
                session_type="strategic",
                trigger_reason=question.strip(),
                custom_question=question.strip(),
            )
        else:
            result = engine.run_session(
                session_type="daily",
                trigger_reason="Telegram /council command",
            )
    except Exception as e:
        return f"❌ Council session failed: {str(e)[:200]}"

    now = datetime.now(ET).strftime("%H:%M ET")
    direction = result.get("consensus", "unknown").upper()
    consensus_type = result.get("consensus_type", "?")
    confidence = result.get("confidence_avg", 0)

    lines = [f"🏛️ <b>AI COUNCIL SESSION</b> ({now})"]
    if question.strip():
        lines.append(f"📋 <i>{question.strip()[:100]}</i>")
    lines.append(f"Direction: <b>{direction}</b> ({consensus_type}, {confidence:.0%} avg confidence)")

    if result.get("is_contested"):
        lines.append("⚠️ <i>No consensus — required Round 2</i>")

    lines.append("")

    # V2 agent emoji and label mappings
    agent_emojis = {
        "tactical_operator": "⚡",
        "strategic_architect": "🏗️",
        "red_team": "🔴",
        "innovation_engine": "💡",
        "macro_navigator": "🌍",
    }
    agent_labels = {
        "tactical_operator": "Tactical",
        "strategic_architect": "Strategic",
        "red_team": "Red Team",
        "innovation_engine": "Innovation",
        "macro_navigator": "Macro",
    }

    # Use agent_assessments from v2 result
    assessments = result.get("agent_assessments", [])
    for assessment in assessments:
        agent = assessment.get("agent", "unknown")
        emoji = agent_emojis.get(agent, "⚪")
        label = agent_labels.get(agent, agent.replace("_", " ").title())
        direction_a = assessment.get("direction", "neutral")
        conf_a = assessment.get("confidence", 0)
        reasoning = assessment.get("key_reasoning", "")[:80]
        dir_emoji = {"bullish": "🟢", "neutral": "⚪", "bearish": "🔴"}.get(direction_a, "⚪")
        lines.append(f"{emoji} {label}: {dir_emoji} {direction_a} ({conf_a:.0%})")
        if reasoning:
            lines.append(f"   <i>{reasoning}...</i>")

    # Parameter adjustments
    params = result.get("parameter_adjustments", {})
    if params:
        lines.append("")
        for p, detail in params.items():
            if isinstance(detail, dict):
                prev = detail.get("previous", "?")
                applied = detail.get("applied", "?")
                if prev != applied:
                    lines.append(f"📊 {p}: {prev} → {applied}")

    if result.get("total_cost"):
        lines.append(f"\n💰 ${result['total_cost']:.4f} | Rounds: {result.get('rounds_completed', 0)}")

    return "\n".join(lines)


def _cmd_health() -> str:
    """GPU and system health."""
    import subprocess
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=temperature.gpu,utilization.gpu,memory.used,memory.total",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10
        )
        parts = result.stdout.strip().split(", ")
        temp, util, mem_used, mem_total = parts[0], parts[1], parts[2], parts[3]
        return (
            f"🖥️ <b>SYSTEM HEALTH</b>\n"
            f"GPU Temp: {temp}°C\n"
            f"GPU Util: {util}%\n"
            f"VRAM: {mem_used}/{mem_total} MB"
        )
    except Exception as e:
        logger.warning("[TELEGRAM] _cmd_health nvidia-smi failed: %s", e)
        return "🖥️ GPU health data unavailable (nvidia-smi not found)"


def _cmd_log() -> str:
    """Recent activity log entries."""
    try:
        from src.logging.activity import get_recent_activity

        entries = get_recent_activity(limit=10)
        if not entries:
            return "📋 No activity log entries yet."

        lines = ["📋 <b>RECENT ACTIVITY</b>"]
        for e in entries:
            # Extract time from ISO timestamp
            ts = e.get("timestamp", "")
            try:
                time_str = ts[11:16]  # HH:MM from ISO format
            except Exception as e:
                logger.warning("[TELEGRAM] _cmd_log timestamp parse failed: %s", e)
                time_str = "??:??"
            cat = e.get("category", "?")
            event = e.get("event", "")
            lines.append(f"{time_str} [{cat}] {event}")
        return "\n".join(lines)
    except Exception as e:
        return f"📋 Activity log unavailable: {e}"


def _cmd_pull() -> str:
    """Git pull latest code."""
    import subprocess
    try:
        result = subprocess.run(
            ["git", "pull"], capture_output=True, text=True, timeout=30
        )
        output = result.stdout.strip() or result.stderr.strip()
        return f"📥 <b>GIT PULL</b>\n<pre>{output[:500]}</pre>"
    except Exception as e:
        return f"❌ Git pull failed: {e}"


def _cmd_logs() -> str:
    """Last 20 lines of arcis.log."""
    import os
    log_path = os.path.join("logs", "arcis.log")
    try:
        with open(log_path, "r") as f:
            lines = f.readlines()
        last_20 = lines[-20:] if len(lines) >= 20 else lines
        text = "".join(last_20).strip()
        return f"📜 <b>LAST 20 LOG LINES</b>\n<pre>{text[:3500]}</pre>"
    except FileNotFoundError:
        return "📜 Log file not found"
    except Exception as e:
        return f"📜 Log read failed: {e}"


def _cmd_gpu() -> str:
    """GPU details via nvidia-smi."""
    import subprocess
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,temperature.gpu,utilization.gpu,memory.used,memory.total,power.draw",
             "--format=csv,noheader"],
            capture_output=True, text=True, timeout=10
        )
        return f"🖥️ <b>GPU</b>\n<pre>{result.stdout.strip()[:1000]}</pre>"
    except Exception as e:
        logger.warning("[TELEGRAM] _cmd_gpu nvidia-smi failed: %s", e)
        return "🖥️ nvidia-smi not available"


def _cmd_disk() -> str:
    """Disk usage for key directories."""
    import os
    import shutil

    dirs = {
        "DB": "ai_research_desk.sqlite3",
        "Logs": "logs",
        "Models": "models",
    }
    lines = ["💾 <b>DISK USAGE</b>"]

    total, used, free = shutil.disk_usage(".")
    lines.append(f"Disk: {used // (1024**3)}GB / {total // (1024**3)}GB ({free // (1024**3)}GB free)")

    for label, path in dirs.items():
        if os.path.isfile(path):
            size = os.path.getsize(path) / (1024 * 1024)
            lines.append(f"  {label}: {size:.1f} MB")
        elif os.path.isdir(path):
            total_size = sum(
                os.path.getsize(os.path.join(dp, f))
                for dp, _, fns in os.walk(path) for f in fns
            ) / (1024 * 1024)
            lines.append(f"  {label}: {total_size:.1f} MB")
        else:
            lines.append(f"  {label}: not found")

    return "\n".join(lines)


def notify_validation_summary(result: dict) -> bool:
    """Send system validation summary via Telegram.

    Silent if all checks pass. Warns on warnings, details on failures.
    """
    if not is_telegram_enabled():
        return False

    passed = result.get("checks_passed", 0)
    failed = result.get("checks_failed", 0)
    warnings = result.get("checks_warning", 0)
    overall = result.get("overall_status", "unknown")
    total = result.get("checks_total", 0)

    # Silent on all-pass
    if failed == 0 and warnings == 0:
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
        logger.warning("[TELEGRAM] notify_validation_summary send failed: %s", e)
        return False


def _cmd_uptime() -> str:
    """Watch loop uptime and next event."""
    now = datetime.now(ET)
    hour = now.hour

    # Determine next scheduled event
    if hour < 8:
        next_event = "Pre-market features at 8:00 ET"
    elif hour < 9:
        next_event = "Market open scan at 9:30 ET"
    elif 9 <= hour < 16:
        next_event = "Next scan in ~30 min"
    elif hour < 17:
        next_event = "Post-close capture at 17:30 ET"
    elif hour < 18:
        next_event = "Training collection at 18:00 ET"
    elif hour < 19:
        next_event = "Overnight training at 19:00 ET"
    else:
        next_event = "Data collection pipeline"

    return (
        f"⏱️ <b>UPTIME</b>\n"
        f"Time: {now.strftime('%Y-%m-%d %H:%M ET')}\n"
        f"Day: {now.strftime('%A')}\n"
        f"Next: {next_event}"
    )
