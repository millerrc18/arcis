"""End-of-day recap email formatter.

Called by: scheduler.watch, services.recap_service
Calls: config, journal.store, shadow_trading.executor, universe.company_names
Owns tables: none
Config keys: shadow_trading
Tests: tests/test_packet_builders.py
"""

from src.config import DB_PATH
from src.universe.company_names import get_company_name


def build_eod_recap(packet_worthy: list[dict], watchlist: list[dict],
                    journal_entries: list[dict], date_str: str,
                    shadow_data: dict | None = None) -> str:
    """Build a formatted plain-text EOD recap email body.

    Args:
        packet_worthy: List of packet-worthy candidate dicts from get_top_candidates.
        watchlist: List of watchlist candidate dicts from get_top_candidates.
        journal_entries: List of recommendation dicts from get_todays_recommendations.
        date_str: Date string for the header (YYYY-MM-DD).
        shadow_data: Optional dict with shadow ledger info:
            open_trades, opened_today, closed_today, realized_pnl, unrealized_pnl,
            closed_details, open_details

    Returns:
        Formatted plain-text email body.
    """
    lines = []

    # Header
    lines.append(f"[TRADE DESK] EOD Recap - {date_str}")
    lines.append("")

    # Market context (from first available candidate with regime data)
    regime_source = None
    for candidates in [packet_worthy, watchlist]:
        for c in candidates:
            feat = c.get("features", {})
            if feat.get("regime_label"):
                regime_source = feat
                break
        if regime_source:
            break

    if regime_source:
        lines.append("MARKET CONTEXT:")
        lines.append(
            f"  Regime: {regime_source.get('regime_label', 'n/a').replace('_', ' ').title()} | "
            f"Volatility: {regime_source.get('volatility_regime', 'n/a').title()} "
            f"({regime_source.get('vix_proxy', 0):.1f}%)"
        )
        lines.append(
            f"  SPY: {regime_source.get('spy_20d_return', 0):+.1f}% (20d) | "
            f"{regime_source.get('spy_drawdown_from_high', 0):.1f}% from high | "
            f"RSI: {regime_source.get('spy_rsi_14', 'n/a')} | "
            f"Breadth: {regime_source.get('market_breadth_label', 'n/a').title()} "
            f"({regime_source.get('market_breadth_pct', 0):.0f}%)"
        )
        lines.append("")

    # Activity summary
    lines.append("ACTIVITY SUMMARY:")
    lines.append(f"  - Packets sent today: {len(journal_entries)}")
    lines.append(f"  - Watchlist names: {len(watchlist)}")
    lines.append(f"  - Total recommendations logged: {len(journal_entries)}")
    lines.append("")

    # Packets sent today
    lines.append("PACKETS SENT:")
    if journal_entries:
        for entry in journal_entries:
            ticker = entry.get("ticker", "???")
            name = entry.get("company_name") or get_company_name(ticker)
            entry_zone = entry.get("entry_zone", "n/a")
            stop = entry.get("stop_level", "n/a")
            t1 = entry.get("target_1", "")
            t2 = entry.get("target_2", "")
            targets = f"{t1} / {t2}".strip(" /") if t1 or t2 else "n/a"
            confidence = entry.get("confidence_score", "n/a")
            conf_str = f"{confidence:.0f}" if isinstance(confidence, (int, float)) else str(confidence)
            lines.append(
                f"  {ticker:6s}  {name:20s}  entry={entry_zone}  stop={stop}  "
                f"targets={targets}  confidence={conf_str}/10"
            )
    else:
        lines.append("  No packet-worthy setups today.")
    lines.append("")

    # Shadow ledger section
    if shadow_data:
        lines.append("SHADOW LEDGER UPDATE:")
        lines.append(f"  Open positions: {shadow_data.get('open_trades', 0)}")
        lines.append(f"  Trades opened today: {shadow_data.get('opened_today', 0)}")
        lines.append(f"  Trades closed today: {shadow_data.get('closed_today', 0)}")
        lines.append(f"  Today's realized P&L: ${shadow_data.get('realized_pnl', 0):+.2f}")
        lines.append(f"  Open unrealized P&L: ${shadow_data.get('unrealized_pnl', 0):+.2f}")

        closed_details = shadow_data.get("closed_details", [])
        if closed_details:
            lines.append("")
            lines.append("  Closed today:")
            for cd in closed_details:
                lines.append(
                    f"    {cd['ticker']:6s}  {cd['exit_reason']:15s}  "
                    f"P&L=${cd['pnl']:+.2f} ({cd['pnl_pct']:+.1f}%)  "
                    f"held {cd['days']} days"
                )

        open_details = shadow_data.get("open_details", [])
        if open_details:
            lines.append("")
            lines.append("  Open positions:")
            for od in open_details:
                lines.append(
                    f"    {od['ticker']:6s}  entry=${od['entry']:.2f}  "
                    f"current=${od['current']:.2f}  "
                    f"P&L=${od['pnl']:+.2f} ({od['pnl_pct']:+.1f}%)  "
                    f"day {od['days']}/{od['timeout']}"
                )
        lines.append("")

    # Watchlist status
    lines.append("WATCHLIST STATUS:")
    if watchlist:
        for c in watchlist:
            feat = c["features"]
            name = get_company_name(c["ticker"])
            lines.append(
                f"  {c['ticker']:6s}  {name:20s}  score={c['score']:.0f}  "
                f"trend={feat.get('trend_state', 'n/a')}  "
                f"RS={feat.get('relative_strength_state', 'n/a')}  "
                f"pullback={feat.get('pullback_depth_pct', 0):.1f}%"
            )
    else:
        lines.append("  No watchlist names today.")
    lines.append("")

    # Footer
    lines.append("---")
    lines.append("Arcis Systematic Equity Research")
    lines.append(f"EOD recap for {date_str}. Full post-trade review is only required for trades you actually execute.")

    return "\n".join(lines)


def get_shadow_data_for_recap(db_path: str = DB_PATH) -> dict:
    """Gather shadow ledger data for the EOD recap."""
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from src.config import load_config
    from src.journal.store import get_open_shadow_trades, get_closed_shadow_trades
    from src.shadow_trading.executor import _get_current_price_safe

    config = load_config()
    # Fix: timeout_days can be a string or dict from config/dashboard —
    # resolve to int to prevent str vs int comparison errors downstream.
    _raw_timeout = config.get("shadow_trading", {}).get("timeout_days", 15)
    if isinstance(_raw_timeout, dict):
        _raw_timeout = _raw_timeout.get("default", 15)
    timeout = int(_raw_timeout)
    et = ZoneInfo("America/New_York")
    today_str = datetime.now(et).strftime("%Y-%m-%d")

    open_trades = get_open_shadow_trades(db_path)
    closed_recent = get_closed_shadow_trades(days=1, db_path=db_path)

    # Filter to today's closes
    closed_today = [
        t for t in closed_recent
        if (t.get("actual_exit_time") or "")[:10] == today_str
    ]

    realized_pnl = sum(t.get("pnl_dollars", 0) or 0 for t in closed_today)

    # Open position details with current prices
    open_details = []
    unrealized_pnl = 0.0
    for t in open_trades:
        entry = t.get("actual_entry_price") or t.get("entry_price", 0)
        current = _get_current_price_safe(t["ticker"])
        if current and entry > 0:
            pnl = (current - entry) * (t.get("planned_shares", 1))
            pnl_pct = (current - entry) / entry * 100
            unrealized_pnl += pnl
            open_details.append({
                "ticker": t["ticker"],
                "entry": entry,
                "current": current,
                "pnl": pnl,
                "pnl_pct": pnl_pct,
                "days": t.get("duration_days", 0) or 0,
                "timeout": timeout,
            })

    # Closed today details
    closed_details = [
        {
            "ticker": t["ticker"],
            "exit_reason": t.get("exit_reason", "unknown"),
            "pnl": t.get("pnl_dollars", 0) or 0,
            "pnl_pct": t.get("pnl_pct", 0) or 0,
            "days": t.get("duration_days", 0) or 0,
        }
        for t in closed_today
    ]

    # Count trades opened today
    all_trades = get_open_shadow_trades(db_path)  # already filtered to open
    opened_today = sum(
        1 for t in all_trades
        if (t.get("created_at") or "")[:10] == today_str
    )

    return {
        "open_trades": len(open_trades),
        "opened_today": opened_today,
        "closed_today": len(closed_today),
        "realized_pnl": realized_pnl,
        "unrealized_pnl": unrealized_pnl,
        "closed_details": closed_details,
        "open_details": open_details,
    }
