"""Build a real TradePacket from computed features and config.

Called by: cli.commands, evaluation.backtester, scheduler.watch, services.scan_service
Calls: models, universe.company_names
Owns tables: none
Config keys: planned_risk_pct_max, risk, starting_capital
Tests: tests/test_packet_builders.py
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from src.models import PositionSizing, TradePacket
from src.universe.company_names import get_company_name

if TYPE_CHECKING:
    from src.platform.strategy_spec import StrategySpec

logger = logging.getLogger(__name__)


def _is_unit_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and 0.0 <= value <= 1.0


def _resolve_strategy_regime_key(features: dict) -> str | None:
    for key in ("regime_key", "_regime_key", "regime_type"):
        value = features.get(key)
        if isinstance(value, str) and value:
            return value

    try:
        from src.features.regime import classify_regime

        regime_key = classify_regime(features)
    except Exception:
        return None
    return regime_key if isinstance(regime_key, str) and regime_key else None


def _resolve_strategy_position_multiplier(
    features: dict,
    strategy: "StrategySpec" | None,
) -> float:
    if strategy is None:
        return 1.0

    sizing = getattr(strategy, "position_sizing", {}) or {}
    if sizing.get("method") != "regime_adaptive":
        return 1.0

    regimes = sizing.get("regimes")
    if not isinstance(regimes, dict):
        return 1.0

    regime_key = _resolve_strategy_regime_key(features)
    if not regime_key:
        return 1.0

    entry = regimes.get(regime_key)
    if not isinstance(entry, dict):
        return 1.0

    position_pct = entry.get("position_pct")
    if _is_unit_number(position_pct):
        return float(position_pct)
    return 1.0


def _resolve_strategy_brackets(
    price: float,
    atr: float,
    strategy: "StrategySpec" | None,
) -> tuple[float, list[float], str] | None:
    if strategy is None or price <= 0 or atr <= 0:
        return None

    exit_block = getattr(strategy, "exit", {}) or {}
    if exit_block.get("kind") != "mechanical":
        return None

    stop_block = exit_block.get("stop")
    targets_block = exit_block.get("targets")
    if not isinstance(stop_block, dict) or not isinstance(targets_block, list) or not targets_block:
        return None

    stop_mult = stop_block.get("atr_multiple")
    if not isinstance(stop_mult, (int, float)) or isinstance(stop_mult, bool) or stop_mult <= 0:
        return None

    target_prices: list[float] = []
    for target in targets_block:
        if not isinstance(target, dict):
            continue
        atr_multiple = target.get("atr_multiple")
        if isinstance(atr_multiple, (int, float)) and not isinstance(atr_multiple, bool) and atr_multiple > 0:
            target_prices.append(price + float(atr_multiple) * atr)
    if not target_prices:
        return None

    stop_price = price - float(stop_mult) * atr
    return stop_price, target_prices, f"{float(stop_mult):g}x ATR"


def _resolve_expected_hold_period(strategy: "StrategySpec" | None) -> str:
    if strategy is None:
        return "2 to 10 trading days"

    exit_block = getattr(strategy, "exit", {}) or {}
    timeout_days = exit_block.get("timeout_days")
    if isinstance(timeout_days, int) and timeout_days > 0:
        return f"Up to {timeout_days} trading days"
    return "2 to 10 trading days"


def build_packet_from_features(
    ticker: str,
    features: dict,
    config: dict,
    strategy: "StrategySpec" | None = None,
) -> TradePacket | None:
    """Build a real TradePacket from computed features and config.

    Returns None when current_price <= 0 (#621). The upstream feature
    pipeline can silently return current_price=0 for tickers that fail
    a fetch (observed for ~14 specific tickers daily during 4/21–4/23,
    causing 390 'zero allocation' rejections and ~110 min/day of
    wasted LLM compute). Refusing here closes the wasted-compute path
    and surfaces the affected ticker to operators.
    """
    price = features.get("current_price", 0.0)
    if price is None or price <= 0:
        logger.warning(
            "[PACKET] Refusing to build packet for %s — current_price=%r "
            "invalid (upstream feature pipeline silently failed). "
            "Skipping LLM + governor — fix the feature fetch instead. (#621)",
            ticker, price,
        )
        return None
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
    from src.risk.governor import get_effective_risk_pct
    risk_pct, _tier = get_effective_risk_pct(config)
    position_multiplier = _resolve_strategy_position_multiplier(features, strategy)
    max_risk_dollars = capital * risk_pct * position_multiplier
    if conservative_sizing:
        max_risk_dollars *= 0.5  # Reduce position size by 50% for earnings risk
    bracket_override = _resolve_strategy_brackets(price, atr, strategy)
    if bracket_override is None:
        stop_distance = 2 * atr if atr > 0 else price * 0.03
        stop_price = price - stop_distance
        target_prices = [price + 1.5 * atr, price + 3.0 * atr]
        stop_descriptor = "2x ATR"
    else:
        stop_price, target_prices, stop_descriptor = bracket_override
        stop_distance = max(price - stop_price, 0.0)
    shares = max(1, int(max_risk_dollars / stop_distance)) if stop_distance > 0 else 1
    allocation = float(int(shares) * float(price))
    # Cap allocation at the governor's max_position_pct so the packet never
    # arrives at validate_packet with an allocation that will be rejected for
    # exceeding the portfolio cap (2026-04-14 EXC 30.5% / SO 32.6% rejections).
    # The sizer must respect the cap at the source, not rely on downstream
    # rejection to enforce it.
    max_position_pct = config.get("risk_governor", {}).get("max_position_pct", 0.25)
    if capital > 0 and allocation > max_position_pct * capital:
        capped_allocation = max_position_pct * capital
        if price > 0:
            shares = max(1, int(capped_allocation / price))
            allocation = float(int(shares) * float(price))
        else:
            allocation = capped_allocation
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
    stop_invalidation = f"${stop_price:.2f} close basis"
    targets = " / ".join(f"${target_price:.2f}" for target_price in target_prices)
    expected_hold_period = _resolve_expected_hold_period(strategy)

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
        f"Risk: Stop at ${stop_price:.2f} ({stop_descriptor}). "
        f"Planned risk ${max_risk_dollars:.2f} "
        f"({((max_risk_dollars / capital) * 100) if strategy is not None and capital > 0 else (risk_pct * 100):.1f}% of ${capital} capital)."
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
        expected_hold_period=expected_hold_period,
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
