"""Build a real TradePacket from computed features and config.

Called by: cli.commands, evaluation.backtester, scheduler.watch, services.scan_service
Calls: models, universe.company_names
Owns tables: none
Config keys: planned_risk_pct_max, risk, starting_capital
Tests: tests/test_packet_builders.py
"""

from src.models import PositionSizing, TradePacket
from src.universe.company_names import get_company_name


def build_packet_from_features(ticker: str, features: dict, config: dict) -> TradePacket:
    """Build a real TradePacket from computed features and config."""
    price = features.get("current_price", 0.0)
    atr = features.get("atr_14", 0.0)
    trend = features.get("trend_state", "neutral")
    rs = features.get("relative_strength_state", "neutral")
    pullback = features.get("pullback_depth_pct", 0.0)
    score = features.get("_score", 70)

    # Earnings / event risk
    event_risk_level = features.get("event_risk_level", "none")
    days_to_earnings = features.get("days_to_earnings")
    earnings_date = features.get("earnings_date")
    conservative_sizing = event_risk_level in ("elevated", "imminent")

    # Position sizing from config
    risk_cfg = config.get("risk", {})
    capital = risk_cfg.get("starting_capital", 1000)
    risk_pct = risk_cfg.get("planned_risk_pct_max", 0.01)
    max_risk_dollars = capital * risk_pct
    if conservative_sizing:
        max_risk_dollars *= 0.5  # Reduce position size by 50% for earnings risk
    stop_distance = 2 * atr if atr > 0 else price * 0.03
    shares = max(1, int(max_risk_dollars / stop_distance)) if stop_distance > 0 else 1
    allocation = float(int(shares) * float(price))
    allocation_pct = (allocation / capital * 100) if capital > 0 else 0

    # Confidence from score
    if score >= 90:
        confidence = 9
    elif score >= 80:
        confidence = 8
    else:
        confidence = 7

    # Why now
    why_now = (
        f"{ticker} is in a {trend.replace('_', ' ')} with "
        f"{rs.replace('_', ' ')} relative strength. "
        f"Pullback of {pullback:.1f}% from recent highs into a reward/risk zone."
    )

    # Entry, stop, targets
    entry_zone = f"${price:.2f} area"
    stop_price = price - stop_distance
    stop_invalidation = f"${stop_price:.2f} close basis"
    target_1 = price + 1.5 * atr
    target_2 = price + 3.0 * atr
    targets = f"${target_1:.2f} / ${target_2:.2f}"

    # Event risk text
    if event_risk_level == "imminent":
        event_risk = f"EARNINGS IMMINENT ({days_to_earnings} days) — high gap risk, conservative sizing applied"
    elif event_risk_level == "elevated":
        event_risk = f"Earnings in {days_to_earnings} days — elevated gap risk"
    else:
        event_risk = "Normal"

    # Deeper analysis
    deeper_analysis = (
        f"Trend: {trend.replace('_', ' ')}. SMA50 slope is {features.get('sma50_slope', 'n/a')}, "
        f"SMA200 slope is {features.get('sma200_slope', 'n/a')}. "
        f"Price is {features.get('price_vs_sma50_pct', 0):.1f}% from 50-day MA and "
        f"{features.get('price_vs_sma200_pct', 0):.1f}% from 200-day MA.\n"
        f"Relative strength: {rs.replace('_', ' ')}. "
        f"RS vs SPY — 1m: {features.get('rs_vs_spy_1m', 0):.1f}%, "
        f"3m: {features.get('rs_vs_spy_3m', 0):.1f}%, "
        f"6m: {features.get('rs_vs_spy_6m', 0):.1f}%.\n"
    )

    # Market context
    regime = features.get("regime_label")
    if regime:
        deeper_analysis += (
            f"Market regime: {regime.replace('_', ' ')} | "
            f"Breadth: {features.get('market_breadth_label', 'n/a')} | "
            f"SPY RSI: {features.get('spy_rsi_14', 'n/a')}.\n"
        )

    # Fundamental and insider context
    fund_summary = features.get("fundamental_summary")
    if fund_summary and fund_summary != "No fundamental data available":
        deeper_analysis += f"Fundamentals: {fund_summary}\n"

    insider_summary = features.get("insider_summary")
    if insider_summary and insider_summary != "No insider data available":
        deeper_analysis += f"{insider_summary}\n"

    deeper_analysis += (
        f"Pullback quality: {pullback:.1f}% decline from 50-day high. "
        f"ATR(14): ${atr:.2f} ({features.get('atr_pct', 0):.1f}% of price). "
        f"Volume ratio: {features.get('volume_ratio_20d', 0):.2f}x 20-day average.\n"
        f"Risk: Stop at ${stop_price:.2f} (2x ATR). "
        f"Planned risk ${max_risk_dollars:.2f} ({risk_pct*100:.1f}% of ${capital} capital)."
    )

    # Append earnings risk section to deeper analysis when relevant
    if conservative_sizing and earnings_date:
        deeper_analysis += (
            f"\nEvent Risk: Next earnings {earnings_date}. Hold window overlaps earnings.\n"
            f"Gap risk is elevated. Conservative sizing applied — position reduced 50%.\n"
            f"Thesis assumes exit before earnings / hold through event based on hold period."
        )

    return TradePacket(
        ticker=ticker,
        company_name=get_company_name(ticker),
        recommendation="Buy",
        setup_type="Pullback in strong trend / relative strength continuation",
        why_now=why_now,
        entry_zone=entry_zone,
        stop_invalidation=stop_invalidation,
        targets=targets,
        expected_hold_period="2 to 10 trading days",
        confidence=confidence,
        event_risk=event_risk,
        position_sizing=PositionSizing(
            allocation_dollars=round(allocation, 2),
            allocation_pct=round(allocation_pct, 1),
            estimated_risk_dollars=round(max_risk_dollars, 2),
        ),
        deeper_analysis=deeper_analysis,
    )


def build_demo_packet() -> str:
    packet = TradePacket(
        ticker="AAPL",
        company_name="Apple Inc.",
        recommendation="Watch",
        setup_type="Pullback in strong trend / relative strength continuation",
        why_now="Constructive pullback into support while relative strength remains intact.",
        entry_zone="$212 - $215",
        stop_invalidation="$207 close basis",
        targets="$220 / $225",
        expected_hold_period="2 to 10 trading days",
        confidence=7,
        event_risk="Normal",
        position_sizing=PositionSizing(
            allocation_dollars=250.0,
            allocation_pct=25.0,
            estimated_risk_dollars=7.5,
        ),
        deeper_analysis=(
            "Trend remains constructive, pullback is orderly, and broader market context is neutral-to-supportive. "
            "Packet is a demo only and should not be treated as a real recommendation."
        ),
    )
    return render_packet(packet)



def render_packet(packet: TradePacket) -> str:
    return f"""[TRADE DESK] Action Packet - {packet.ticker}

Quick Bullet Brief
- Ticker / Company: {packet.ticker} / {packet.company_name}
- Recommendation: {packet.recommendation}
- Setup Type: {packet.setup_type}
- Why now: {packet.why_now}
- Entry Zone: {packet.entry_zone}
- Stop / Invalidation: {packet.stop_invalidation}
- Targets: {packet.targets}
- Expected Hold Period: {packet.expected_hold_period}
- Suggested Position Size: ${packet.position_sizing.allocation_dollars:.0f} ({packet.position_sizing.allocation_pct:.1f}% of capital), est. risk ${packet.position_sizing.estimated_risk_dollars:.2f}
- Event Risk: {packet.event_risk}
- Confidence: {packet.confidence}/10

Deeper Analysis
{packet.deeper_analysis}
"""
