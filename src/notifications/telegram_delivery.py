"""Telegram pre-formatted alert layer for Arcis (delivery slice of telegram.py).

Called by: notifications.telegram (re-exported), scheduler.watch, scheduler.overnight, scheduler.reports, services.scan_service, shadow_trading.bracket_monitor, shadow_trading.executor, training.canary, training.ingestion_gate
Calls: data_ingestion.finnhub, notifications.telegram
Owns tables: none
Config keys: telegram
Tests: tests/notifications/test_html_escape_siblings.py, tests/notifications/test_platform_events.py, tests/test_expanded_notifications.py, tests/notifications/test_safe_send.py

Holds the `notify_*` alert-message builders and their typed payload
dataclasses, extracted from `src/notifications/telegram.py` (Phase 5 PR-C
T11, §3 + DD-08c) to bring telegram.py back under the structure-debt cap.

The transport core (send_telegram, _send_single, requests, _redact_token,
_html_escape, _get_telegram_config) and the policy dispatcher (safe_send,
_EVENT_MAP, _do_dispatch) stay in telegram.py. Every function here calls
those upward via the late-bound module reference `_tg.<name>(...)` (NOT a
`from ... import`) so that the conftest session null-router patch on
`telegram._send_single` and the suite-wide `telegram.send_telegram` /
`telegram._html_escape` test patches bind regardless of which module the
caller lives in. See T10 late-binding pattern + tests/conftest.py:709.

Each notify_* function is re-exported from telegram.py, so existing
imports (`from src.notifications.telegram import notify_trade_opened`) and
patch targets (`patch("src.notifications.telegram.notify_trade_opened")`)
continue to resolve unchanged.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

import src.notifications.telegram as _tg
from src.data_ingestion.finnhub import normalize_earnings_time

ET = ZoneInfo("America/New_York")


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
    return _tg.send_telegram("\n".join(lines))


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
        f"{emoji} <b>{label}: {_tg._html_escape(ticker)}</b>",
        f"P&L: ${pnl_dollars:+.2f} ({pnl_pct:+.1f}%)",
        f"Reason: {_tg._html_escape(exit_reason)} | Held: {days_held}d",
    ]
    lines.extend(_format_closed_extras(
        payload.excess_return, payload.spy_return_over_hold, payload.mfe_pct, payload.mae_pct,
        payload.drawdown_from_mfe, payload.sector, payload.regime_at_entry, payload.regime_at_exit,
        payload.entry_slippage_bps, payload.exit_slippage_bps,
    ))
    return _tg.send_telegram("\n".join(lines))


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
    return _tg.send_telegram(msg)


def notify_risk_alert(alert_type: str, detail: str) -> bool:
    """Alert: risk governor event."""
    msg = f"⚠️ <b>RISK ALERT: {_tg._html_escape(alert_type)}</b>\n{_tg._html_escape(detail)}"
    return _tg.send_telegram(msg)


def notify_earnings_warning(tickers: list[str]) -> bool:
    """Alert: stocks reporting earnings soon."""
    if not tickers:
        return True
    ticker_list = "\n".join(f"  • {t}" for t in tickers)
    msg = f"📅 <b>EARNINGS THIS WEEK</b>\n{ticker_list}"
    return _tg.send_telegram(msg)


def notify_overnight_complete(results: dict) -> bool:
    """Alert: overnight data collection summary."""
    now = datetime.now(ET).strftime("%H:%M ET")
    lines = [f"🌙 <b>OVERNIGHT DATA COLLECTION</b> ({now})"]
    for key, val in results.items():
        if isinstance(val, dict):
            if not val.get("success", True):
                err = _tg._html_escape(str(val.get("error", ""))[:60])
                lines.append(f"  ❌ {_tg._html_escape(key)}: {err}" if err else f"  ❌ {_tg._html_escape(key)}")
            else:
                lines.append(f"  ✅ {_tg._html_escape(key)}")
        elif isinstance(val, str) and "error" in val.lower():
            lines.append(f"  ❌ {_tg._html_escape(key)}: {_tg._html_escape(val[:60])}")
        else:
            lines.append(f"  ✅ {_tg._html_escape(key)}")
    return _tg.send_telegram("\n".join(lines))


def notify_system_event(event: str, detail: str = "") -> bool:
    """Alert: general system event."""
    msg = f"🔧 <b>{_tg._html_escape(event)}</b>"
    if detail:
        msg += f"\n{_tg._html_escape(detail)}"
    return _tg.send_telegram(msg)


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
        emoji = "❌"
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
            msg += f"❌ {d}\n"

    if warning_details:
        msg += "\n"
        for d in warning_details[:5]:
            msg += f"⚠️ {d}\n"

    if launching:
        overnight_str = "overnight" if overnight else "daytime"
        msg += f"\nWatch loop launching ({overnight_str} + {email_mode})"
    elif criticals > 0:
        msg += "\nUse --force to override."

    return _tg.send_telegram(msg)


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
    return _tg.send_telegram(msg)


def notify_model_event(event: str, model_name: str, detail: str = "") -> bool:
    """Alert: model training/promotion/rollback event."""
    msg = f"🧠 <b>MODEL: {_tg._html_escape(event)}</b>\nModel: {_tg._html_escape(model_name)}"
    if detail:
        msg += f"\n{_tg._html_escape(detail)}"
    return _tg.send_telegram(msg)


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
    return _tg.send_telegram(msg)


def notify_scan_result(scan_number: int, total_scanned: int,
                       packet_worthy: int, watchlist: int) -> bool:
    """Alert: scan cycle result (fires every scan, not just when trades open)."""
    now = datetime.now(ET).strftime("%H:%M ET")
    msg = (
        f"📊 <b>SCAN #{scan_number}</b> ({now})\n"
        f"Scanned: {total_scanned} | Packet-worthy: {packet_worthy} | Watchlist: {watchlist}"
    )
    return _tg.send_telegram(msg)


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
    return _tg.send_telegram(msg)


def notify_gpu_health(direction: str, success: bool, detail: str = "") -> bool:
    """Alert: GPU health lifecycle event under the dual-GPU static partition.

    Static partition (#94): training pins GPU0 (RTX 3090); Ollama remains
    resident on GPU1 (RTX 3060) throughout. There is NO load/unload around
    training — pre-#94 VRAM-handoff language was retired with the partition.
    """
    emoji = "✅" if success else "❌"
    if direction == "training":
        msg = f"{emoji} <b>GPU HEALTH → TRAINING</b>\nTraining lifecycle on GPU0 (Ollama remains on GPU1)"
    else:
        msg = f"{emoji} <b>GPU HEALTH → INFERENCE</b>\nOllama health on GPU1 (training partition idle)"
    if detail:
        msg += f"\n{detail}"
    return _tg.send_telegram(msg)


def notify_overnight_training_complete(tasks_completed: int, tasks_total: int,
                                       details: dict | None = None) -> bool:
    """Alert: overnight training pipeline complete."""
    now = datetime.now(ET).strftime("%H:%M ET")
    msg = f"🌙 <b>OVERNIGHT TRAINING</b> ({now})\nTasks: {tasks_completed}/{tasks_total}"
    if details:
        for task, status in details.items():
            emoji = "✅" if status.get("success", False) else "❌"
            msg += f"\n  {emoji} {_tg._html_escape(task)}"
            if not status.get("success", False) and status.get("error"):
                msg += f": {_tg._html_escape(str(status['error'])[:40])}"
    return _tg.send_telegram(msg)


def notify_scoring_summary(scored_today: int, backlog: int) -> bool:
    """Alert: daily scoring summary (end of market hours)."""
    msg = (
        f"📝 <b>SCORING SUMMARY</b>\n"
        f"Scored today: {scored_today}\n"
        f"Backlog remaining: {backlog}"
    )
    return _tg.send_telegram(msg)


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
    return _tg.send_telegram(msg)


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
        f"{_tg._html_escape('S&P')} Futures: {spy_futures_pct:+.2f}% | 10Y: {ten_year:.2f}%\n"
        f"Earnings today: {earnings_str}\n"
        f"{events_str}\n\n"
        f"Council consensus: {council_consensus.upper()} ({council_confidence}%)\n"
        f"Open positions: {open_paper} paper, {open_live} live"
    )
    return _tg.send_telegram(msg)


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
    return _tg.send_telegram(msg)


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
    return _tg.send_telegram(msg)


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
    return _tg.send_telegram(msg)


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
    return _tg.send_telegram(msg)


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
        f"Regime shifted: {_tg._html_escape(regime_old)} → {_tg._html_escape(regime_new)}\n"
        f"Qualification threshold: {qual_old} → {qual_new}\n"
        f"Position sizing: {sizing_old}% → {sizing_new}%\n\n"
        f"Action: {'Tighter' if vix_now > vix_prev else 'Looser'} filters active. "
        f"{'Fewer' if vix_now > vix_prev else 'More'} trades expected."
    )
    return _tg.send_telegram(msg)


def notify_milestone(milestone: str, detail: str) -> bool:
    """Alert: trade milestone reached (1st trade, 10th close, etc.)."""
    msg = f"🏆 <b>MILESTONE: {_tg._html_escape(milestone)}</b>\n\n{_tg._html_escape(detail)}"
    return _tg.send_telegram(msg)


def notify_streak_alert(streak_length: int, recent_trades: list[tuple[str, float]],
                        max_drawdown_pct: float,
                        risk_governor_status: str,
                        historical_max_streak: int) -> bool:
    """Alert: 3+ consecutive losses."""
    recent_str = ", ".join(f"{_tg._html_escape(t)} {p:+.1f}%" for t, p in recent_trades[:5])
    msg = (
        f"🔶 <b>STREAK ALERT: {streak_length} consecutive losses</b>\n\n"
        f"Recent: {recent_str}\n"
        f"Max drawdown: {max_drawdown_pct:+.1f}% | Risk governor: {_tg._html_escape(risk_governor_status)}\n"
        f"Historical streak max: {historical_max_streak}\n\n"
        f"No action required — within normal parameters."
    )
    return _tg.send_telegram(msg)


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
        f"  {_tg._html_escape('P&L')}: Paper ${payload.pnl_paper:+.2f} | Live ${payload.pnl_live:+.2f}\n\n"
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
    return _tg.send_telegram(msg)


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
        f"Model: {_tg._html_escape(model_name)}\n"
        f"Training examples: {training_examples} (was {prev_examples})\n"
        f"New examples this week: {new_this_week} ({new_paper} paper, {new_live} live)\n\n"
        f"Canary evaluation: {canary_status}\n"
        f"  Perplexity: {perplexity:.2f} (was {prev_perplexity:.2f}, {ppl_delta:+.1f}%)\n"
        f"  Distinct-2: {distinct2:.2f} (was {prev_distinct2:.2f}, {d2_delta:+.1f}%)\n"
        f"  Verdict: {'Within normal range' if canary_status == 'STABLE' else '⚠️ Review recommended'}\n\n"
        f"Champion-challenger: {champion_challenger}"
    )
    return _tg.send_telegram(msg)


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
        f"Top: {_tg._html_escape(top_paper[:60])} (relevance: {score_value:.1f})"
    )
    return _tg.send_telegram(msg)


_RESEARCH_DIGEST_SUMMARY_LIMIT = 800


def notify_research_digest(papers_count: int, actionable_count: int,
                           digest_summary: str) -> bool:
    """Send weekly research intelligence digest."""
    if len(digest_summary) > _RESEARCH_DIGEST_SUMMARY_LIMIT:
        summary_body = _tg._html_escape(digest_summary[:_RESEARCH_DIGEST_SUMMARY_LIMIT]) + "\n[truncated; see email digest]"
    else:
        summary_body = _tg._html_escape(digest_summary)
    msg = (
        f"📚 <b>WEEKLY RESEARCH DIGEST</b>\n\n"
        f"Papers reviewed: {papers_count}\n"
        f"Actionable findings: {actionable_count}\n\n"
        f"{summary_body}"
    )
    return _tg.send_telegram(msg)


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
        f"Last error: {_tg._html_escape(last_error[:80])}\n"
        f"Last success: {last_success_ago}\n\n"
        f"Other collectors: {others_str}"
    )
    return _tg.send_telegram(msg)


def notify_exposure_alert(sector: str, count: int, tickers: list[str],
                          exposure_pct: float, limit_pct: float) -> bool:
    """Alert: sector concentration exceeds limit."""
    ticker_str = ", ".join(_tg._html_escape(t) for t in tickers[:5])
    msg = (
        f"⚠️ <b>EXPOSURE ALERT</b>\n\n"
        f"{count} positions in {_tg._html_escape(sector)} ({ticker_str})\n"
        f"Sector exposure: {exposure_pct:.0f}% of portfolio\n"
        f"Limit: {limit_pct:.0f}%\n\n"
        f"Consider: Skip next {_tg._html_escape(sector)} setup until exposure normalizes."
    )
    return _tg.send_telegram(msg)


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
    return _tg.send_telegram(msg)


# ── Action Reminder Notifications ─────────────────────────────────────

def notify_action_required(action: str, detail: str, urgency: str = "normal") -> bool:
    """Send a Telegram notification when a manual action is needed.

    urgency: 'low', 'normal', 'high', 'critical'
    """
    icons = {"low": "📋", "normal": "🔔", "high": "⚠️", "critical": "🚨"}
    if urgency not in icons:
        raise ValueError(f"Unknown urgency '{urgency}'; must be one of {list(icons)}")
    icon = icons[urgency]
    msg = f"{icon} <b>ACTION REQUIRED</b>\n\n<b>{_tg._html_escape(action)}</b>\n{_tg._html_escape(detail)}"
    return _tg.send_telegram(msg)


def notify_validation_summary(result: dict, force_send: bool = False) -> bool:
    """Send system validation summary via Telegram.

    Silent if all checks pass — only sends when there are warnings or failures.
    This prevents noise during normal operation while ensuring problems
    surface immediately. Failed checks show full detail; warnings show
    only category counts to keep the message concise.

    force_send=True bypasses the silent-on-pass branch and sends regardless
    (spec C12 — startup confirmation path).
    """
    if not _tg.is_telegram_enabled():
        return False

    passed = result.get("checks_passed", 0)
    failed = result.get("checks_failed", 0)
    warnings = result.get("checks_warning", 0)
    overall = result.get("overall_status", "unknown")
    total = result.get("checks_total", 0)

    # Silent on all-pass unless force_send is requested
    if failed == 0 and warnings == 0 and not force_send:
        return True

    icon = {"healthy": "✅", "degraded": "⚠️", "critical": "🚨"}.get(overall, "❓")

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
                    lines.append(f"  ❌ {cat}/{c['name']}: {c['detail'][:80]}")
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
        return _tg.send_telegram("\n".join(lines))
    except Exception as e:
        _tg.logger.warning(
            "[TELEGRAM] notify_validation_summary send failed: %s",
            _tg._redact_token(e),
        )
        return False


def notify_1min_bar_collection(bars_collected: int, tickers: int,
                                empty_ticker_days: int, dates: int = 1) -> bool:
    """Alert: nightly 1-minute bar collection completed.

    Called from `scheduler.overnight.run_1min_bar_collection` after the
    yfinance batch finishes. Silent on bars_collected == 0 to avoid
    weekend spam (yfinance returns empty for non-trading days).
    """
    if not _tg.is_telegram_enabled() or bars_collected == 0:
        return False
    empty_pct = (empty_ticker_days / (tickers * dates) * 100) if tickers and dates else 0
    mb = bars_collected * 60 / (1024 * 1024)
    msg = (
        "📈 <b>1-min bars collected</b>\n"
        f"{bars_collected:,} bars across {tickers} tickers / {dates}d\n"
        f"Empty: {empty_ticker_days}/{tickers * dates} ({empty_pct:.0f}%) "
        f"| ~{mb:.1f} MB"
    )
    return _tg.send_telegram(msg)


def notify_attribution_resolve_complete(resolved: int, pending_remaining: int) -> bool:
    """Alert: nightly attribution resolver finished.

    Called from the watch loop after `resolve_pending_outcomes`. Silent on
    resolved==0 AND pending_remaining==0 (nothing to report).
    """
    if not _tg.is_telegram_enabled():
        return False
    if resolved == 0 and pending_remaining == 0:
        return True
    icon = "✅" if resolved > 0 else "⏳"
    msg = (
        f"{icon} <b>Attribution resolver</b>\n"
        f"Resolved: {resolved} | Still pending: {pending_remaining}"
    )
    return _tg.send_telegram(msg)


def notify_stress_test_complete(scenarios_run: int, passed: int, failed: int,
                                 notes: str = "") -> bool:
    """Alert: stress-test re-run completed (triggered by model version change).

    Called from the 7 PM overnight handler when the active model rolls
    over. Always sends — stress test failures are actionable.
    """
    if not _tg.is_telegram_enabled():
        return False
    icon = "✅" if failed == 0 else "🚨"
    msg = (
        f"{icon} <b>STRESS TEST</b>\n"
        f"{scenarios_run} scenarios | {passed} passed | {failed} failed"
    )
    if notes:
        msg += f"\n{notes}"
    return _tg.send_telegram(msg)


def notify_trading_stats_update(stats: dict, label: str = "") -> bool:
    """Periodic stats pulse: trade count + win rate + PnL + excess vs SPY
    across today / 7d / 30d / all-time windows.

    `stats` is the dict returned by `src.journal.stats.compute_all_window_stats`.
    `label` is an optional header suffix (e.g. "PRE-MARKET", "MIDDAY", "POST-CLOSE").

    Silent on an empty database — if all four windows show count == 0 we
    skip the send so fresh deployments don't spam the channel.
    """
    if not _tg.is_telegram_enabled():
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
    return _tg.send_telegram("\n".join(lines))


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
    ticker = _tg._html_escape(payload.get("ticker", "UNKNOWN"))
    expected = _tg._html_escape(payload.get("expected_state", "?"))
    actual = _tg._html_escape(payload.get("actual_state", "?"))
    age = payload.get("divergence_age_minutes", 0)
    sev_label = _tg._html_escape(severity.upper())
    msg = (
        f"⚠ [{sev_label}] Drift detected — {ticker}: "
        f"expected {expected} (broker), actual {actual} (db), "
        f"age {age:.0f} min"
    )
    return _tg.send_telegram(msg)


def notify_alert_silence(last_seen: str, minutes_silent: int) -> bool:
    """Telegram alert when no notifications have flowed during market hours (T14 D5 / #94).

    Fires when check_alert_silence detects silence > threshold_minutes.

    Args:
        last_seen: ISO timestamp of last signal (or 'never').
        minutes_silent: How many minutes have elapsed without a notification signal.
    """
    last_seen_safe = _tg._html_escape(str(last_seen))
    msg = (
        f"⚠ [HIGH] Alert silence: no notifications in {minutes_silent} min "
        f"(last seen: {last_seen_safe})"
    )
    return _tg.send_telegram(msg)


# ── Email-tier event_type stubs (Sprint #115 T4 — DD-24 + DD-26) ──────────
# Email-tier events are dispatched through src.notifications.email_digest.
# They are registered in telegram._EVENT_MAP_MUTABLE ONLY so DigestQueue.enqueue
# (which validates event_type membership against _KNOWN_EVENT_TYPES) accepts
# them. Invoking any of these stubs through the Telegram path is a routing
# bug — the stub raises NotImplementedError to surface it loudly.


def _email_tier_stub_error(event_name: str) -> NotImplementedError:
    """Build the canonical NotImplementedError for an email-tier stub."""
    return NotImplementedError(
        f"Event {event_name} is email-tier-only; dispatch via "
        f"src.notifications.email_digest.flush_tier() instead."
    )


def notify_audit_critical_email_only(*args, **kwargs):
    """Email-tier stub — raises if reached via Telegram path. See DD-24."""
    raise _email_tier_stub_error("audit_critical")


def notify_audit_alert_email_only(*args, **kwargs):
    """Email-tier stub — raises if reached via Telegram path. See DD-24."""
    raise _email_tier_stub_error("audit_alert")


def notify_audit_red_assessment_email_only(*args, **kwargs):
    """Email-tier stub — raises if reached via Telegram path. See DD-24."""
    raise _email_tier_stub_error("audit_red_assessment")


def notify_morning_watchlist_email_only(*args, **kwargs):
    """Email-tier stub — raises if reached via Telegram path. See DD-24."""
    raise _email_tier_stub_error("morning_watchlist")


def notify_action_packet_email_only(*args, **kwargs):
    """Email-tier stub — raises if reached via Telegram path. See DD-24."""
    raise _email_tier_stub_error("action_packet")


def notify_eod_recap_email_email_only(*args, **kwargs):
    """Email-tier stub — raises if reached via Telegram path. See DD-24."""
    raise _email_tier_stub_error("eod_recap_email")


def notify_premarket_content_email_only(*args, **kwargs):
    """Email-tier stub — raises if reached via Telegram path. See DD-24."""
    raise _email_tier_stub_error("premarket_content")


def notify_midday_content_email_only(*args, **kwargs):
    """Email-tier stub — raises if reached via Telegram path. See DD-24."""
    raise _email_tier_stub_error("midday_content")


def notify_eod_content_email_only(*args, **kwargs):
    """Email-tier stub — raises if reached via Telegram path. See DD-24."""
    raise _email_tier_stub_error("eod_content")


def notify_evening_content_email_only(*args, **kwargs):
    """Email-tier stub — raises if reached via Telegram path. See DD-24."""
    raise _email_tier_stub_error("evening_content")


def notify_weekly_digest_content_email_only(*args, **kwargs):
    """Email-tier stub — raises if reached via Telegram path. See DD-24."""
    raise _email_tier_stub_error("weekly_digest_content")


def notify_saturday_training_report_email_only(*args, **kwargs):
    """Email-tier stub — raises if reached via Telegram path. See DD-24."""
    raise _email_tier_stub_error("saturday_training_report")


def notify_saturday_cto_report_email_only(*args, **kwargs):
    """Email-tier stub — raises if reached via Telegram path. See DD-24."""
    raise _email_tier_stub_error("saturday_cto_report")


def notify_research_synthesis_email_email_only(*args, **kwargs):
    """Email-tier stub — raises if reached via Telegram path. See DD-24."""
    raise _email_tier_stub_error("research_synthesis_email")
