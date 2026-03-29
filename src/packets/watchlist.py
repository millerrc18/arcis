"""Morning watchlist email formatter."""

from src.universe.company_names import get_company_name


def build_morning_watchlist(watchlist: list[dict], packet_worthy: list[dict],
                            date_str: str, narrative: str | None = None) -> str:
    """Build a formatted plain-text morning watchlist email body.

    Args:
        watchlist: List of watchlist candidate dicts from get_top_candidates.
        packet_worthy: List of packet-worthy candidate dicts from get_top_candidates.
        date_str: Date string for the header (YYYY-MM-DD).
        narrative: Optional LLM-generated narrative summary.

    Returns:
        Formatted plain-text email body.
    """
    lines = []

    # Header
    lines.append(f"[TRADE DESK] Morning Watchlist - {date_str}")
    lines.append("")
    lines.append("Quick Summary:")
    lines.append(f"  - {len(watchlist)} names on watchlist")
    lines.append(f"  - {len(packet_worthy)} names packet-worthy (action packets to follow)")
    lines.append("")

    # Market context (from first packet-worthy or watchlist candidate with regime data)
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
        macro = regime_source.get("macro_summary")
        if macro and macro != "No macro data available":
            lines.append(f"  {macro}")
        lines.append("")

    # LLM narrative (if available)
    if narrative:
        lines.append("ANALYST BRIEFING:")
        lines.append(narrative)
        lines.append("")

    # Packet-worthy section
    lines.append(f"PACKET-WORTHY ({len(packet_worthy)}):")
    if packet_worthy:
        for c in packet_worthy:
            feat = c["features"]
            name = get_company_name(c["ticker"])
            flag = ""
            if c.get("earnings_risk"):
                flag = "  [EARNINGS RISK]"
            lines.append(
                f"  {c['ticker']:6s}  {name:20s}  score={c['score']:.0f}  "
                f"trend={feat.get('trend_state', 'n/a')}  "
                f"RS={feat.get('relative_strength_state', 'n/a')}  "
                f"pullback={feat.get('pullback_depth_pct', 0):.1f}%{flag}"
            )
    else:
        lines.append("  No packet-worthy setups today.")
    lines.append("")

    # Watchlist section
    lines.append(f"WATCHLIST ({len(watchlist)}):")
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
    lines.append("Halcyon Lab AI Research Desk")
    lines.append("Quality over quantity. No packets is a valid answer.")

    return "\n".join(lines)
