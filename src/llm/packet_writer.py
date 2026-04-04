"""LLM-enhanced trade packet writer with template fallback.

Called by: scheduler.watch, services.scan_service
Calls: llm.client, llm.grammar_client, llm.prompts, models, strategy.canary, universe.company_names
Owns tables: none
Config keys: enabled, llm, max_tokens, temperature, use_grammar_enforcement
Tests: tests/test_confidence.py, tests/test_grammar_client.py, tests/test_xml_format.py
"""

import logging
import re

from src.llm.client import is_llm_available, generate
from src.llm.prompts import PACKET_SYSTEM_PROMPT
from src.models import TradePacket
from src.universe.company_names import get_company_name

logger = logging.getLogger(__name__)

# #154: context window overflow protection — max tokens before truncation
_MAX_PROMPT_TOKENS = 7000

# #156: patterns to strip from enrichment text to block prompt injection
_INJECTION_TAG_RE = re.compile(r"<[^>]+>", re.DOTALL)
_INJECTION_INSTRUCTION_RE = re.compile(
    r"\b(?:you are|ignore previous)\b|"
    r"\b(?:system|assistant|human)\s*:",
    re.IGNORECASE,
)
_ENRICHMENT_CHAR_CAP = 500


def _sanitize_enrichment_text(text: str) -> str:
    """Strip injection patterns and cap length for enrichment sections.

    Removes XML-like tags, common instruction patterns, and limits
    text to _ENRICHMENT_CHAR_CAP characters.
    """
    if not text:
        return text
    cleaned = _INJECTION_TAG_RE.sub("", text)
    cleaned = _INJECTION_INSTRUCTION_RE.sub("", cleaned)
    # Collapse multiple whitespace from removals
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip()
    if len(cleaned) > _ENRICHMENT_CHAR_CAP:
        cleaned = cleaned[:_ENRICHMENT_CHAR_CAP] + "..."
        logger.debug("[LLM] Enrichment text truncated to %d chars", _ENRICHMENT_CHAR_CAP)
    return cleaned


def _build_feature_prompt(packet: TradePacket, features: dict) -> str:
    """Build a multi-source prompt from all available data."""
    ticker = packet.ticker
    company_name = packet.company_name

    # SECTION 1: Technical Data (existing)
    prompt = f"""=== TECHNICAL DATA ===
Ticker: {ticker} ({company_name})
Current Price: ${features.get('current_price', 0):.2f}
Trend State: {features.get('trend_state', 'n/a')} | SMA50 slope: {features.get('sma50_slope', 'n/a')} | SMA200 slope: {features.get('sma200_slope', 'n/a')}
Price vs SMA50: {features.get('price_vs_sma50_pct', 0):.1f}% | Price vs SMA200: {features.get('price_vs_sma200_pct', 0):.1f}%
Relative Strength: {features.get('relative_strength_state', 'n/a')}
RS vs SPY — 1m: {features.get('rs_vs_spy_1m', 0):.1f}% | 3m: {features.get('rs_vs_spy_3m', 0):.1f}% | 6m: {features.get('rs_vs_spy_6m', 0):.1f}%
Pullback Depth: {features.get('pullback_depth_pct', 0):.1f}% from 50-day high
ATR(14): ${features.get('atr_14', 0):.2f} ({features.get('atr_pct', 0):.1f}% of price)
Volume Ratio: {features.get('volume_ratio_20d', 0):.2f}x 20-day average
Distance to SMA20: {features.get('dist_to_sma20_pct', 0):.1f}%"""

    # SECTION 2: Market Regime (new)
    prompt += f"""

=== MARKET REGIME ===
Market Trend: {features.get('market_trend', 'n/a')} | SPY RSI(14): {features.get('spy_rsi_14', 'n/a')}
Volatility: {features.get('volatility_regime', 'n/a')} ({features.get('vix_proxy', 0):.1f}% realized vol)
SPY: {features.get('spy_20d_return', 0):+.1f}% (20d) | {features.get('spy_drawdown_from_high', 0):.1f}% from 52-week high
Breadth: {features.get('market_breadth_label', 'n/a')} ({features.get('market_breadth_pct', 0):.0f}% above 50d MA)
Regime: {features.get('regime_label', 'n/a')}"""

    # SECTION 3: Sector Context (enhanced 9C)
    sector_factors = features.get('sector_key_factors', [])
    factors_str = "\n".join(f"  - {f}" for f in sector_factors) if sector_factors else "  No sector-specific factors available"
    prompt += f"""

=== SECTOR CONTEXT ===
Sector: {features.get('sector', 'n/a')} | Rank: {features.get('sector_rs_rank', 'n/a')} | Sector Avg Score: {features.get('sector_avg_score', 0):.0f}
Typical pullback depth: {features.get('sector_pullback_depth', 'n/a')} | Recovery: {features.get('sector_recovery_speed', 'n/a')}
Sector-specific factors:
{factors_str}"""

    # SECTION 4: Fundamental Snapshot (new)  — #156: sanitize enrichment
    fundamental_text = _sanitize_enrichment_text(
        features.get('fundamental_summary', 'No fundamental data available')
    )
    prompt += f"""

=== FUNDAMENTAL SNAPSHOT ===
{fundamental_text}"""

    # SECTION 5: Insider Activity (new)  — #156: sanitize enrichment
    insider_text = _sanitize_enrichment_text(
        features.get('insider_summary', 'No insider data available')
    )
    prompt += f"""

=== INSIDER ACTIVITY ===
{insider_text}"""

    # SECTION 6: Recent News  — #156: sanitize enrichment
    news_text = _sanitize_enrichment_text(
        features.get('news_summary', 'No recent news')
    )
    prompt += f"""

=== RECENT NEWS ===
{news_text}"""

    # SECTION 7: Macro Context  — #156: sanitize enrichment
    macro_text = _sanitize_enrichment_text(
        features.get('macro_summary', 'No macro data available')
    )
    prompt += f"""

=== MACRO CONTEXT ===
{macro_text}"""

    # SECTION 7.5: Options Context (9A)
    iv_rank = features.get('iv_rank')
    if iv_rank is not None:
        prompt += f"""

=== OPTIONS CONTEXT ===
IV Rank: {iv_rank:.0f} | Put/Call Vol: {features.get('put_call_vol_ratio', 0):.2f} | Put/Call OI: {features.get('put_call_oi_ratio', 0):.2f}
IV Skew: {features.get('iv_skew', 0):.2f} | Unusual Activity: {'YES' if features.get('unusual_options_activity') else 'No'}"""

    # SECTION 7.6: Event Context (9B)
    event_type = features.get('event_proximity_type')
    if event_type:
        prompt += f"""

=== EVENT CONTEXT ===
{event_type} in {features.get('event_proximity_days', '?')} day(s): {features.get('event_proximity_desc', '')}
Events within 3 days: {features.get('events_within_3d', 0)}"""

    # SECTION 7.7: Earnings Context (PEAD)
    earnings = features.get("earnings_signals", {})
    if earnings.get("include_in_prompt", False):
        earnings_lines = ["\n=== EARNINGS CONTEXT ==="]
        proximity = earnings.get("earnings_proximity_days")
        if proximity is not None:
            earnings_lines.append(f"Days to next earnings: {proximity}")
        surprise = earnings.get("last_surprise_pct")
        if surprise is not None:
            direction = earnings.get("last_surprise_direction", "unknown")
            earnings_lines.append(f"Last earnings surprise: {surprise:+.1f}% ({direction})")
        concordant = earnings.get("last_revenue_eps_concordant")
        if concordant is not None:
            earnings_lines.append(f"Revenue-EPS concordance: {'concordant' if concordant else 'mixed'}")
        rev_vel = earnings.get("analyst_revision_velocity_30d")
        if rev_vel is not None:
            trend_word = "rising" if rev_vel > 0 else "falling" if rev_vel < 0 else "stable"
            earnings_lines.append(f"Analyst revision trend (30d): {trend_word} ({rev_vel:+.1f}%)")
        inconsistent = earnings.get("recommendation_inconsistency")
        if inconsistent is not None:
            earnings_lines.append(f"Recommendation vs surprise: {'inconsistent (stronger signal)' if inconsistent else 'consistent'}")
        strength = earnings.get("earnings_signal_strength", "none")
        earnings_lines.append(f"Earnings signal strength: {strength}")
        prompt += "\n".join(earnings_lines)

    # SECTION 8: Entry/Stop/Targets
    prompt += f"""

=== TRADE PARAMETERS ===
Score: {features.get('_score', 0):.0f}/100 | Confidence: {packet.confidence}/10
Entry Zone: {packet.entry_zone} | Stop: {packet.stop_invalidation} | Targets: {packet.targets}
Position Size: ${packet.position_sizing.allocation_dollars:.0f} ({packet.position_sizing.allocation_pct:.1f}% of capital) | Risk: ${packet.position_sizing.estimated_risk_dollars:.2f}
Event Risk: {packet.event_risk}"""

    return prompt


def _build_condensed_prompt(packet: TradePacket, features: dict) -> str:
    """Build a condensed prompt with only technical data and trade parameters.

    Used as a retry when the full prompt (with enrichment context) times out.
    """
    ticker = packet.ticker
    company_name = packet.company_name

    return f"""=== TECHNICAL DATA ===
Ticker: {ticker} ({company_name})
Current Price: ${features.get('current_price', 0):.2f}
Trend State: {features.get('trend_state', 'n/a')} | SMA50 slope: {features.get('sma50_slope', 'n/a')} | SMA200 slope: {features.get('sma200_slope', 'n/a')}
Price vs SMA50: {features.get('price_vs_sma50_pct', 0):.1f}% | Price vs SMA200: {features.get('price_vs_sma200_pct', 0):.1f}%
Relative Strength: {features.get('relative_strength_state', 'n/a')}
Pullback Depth: {features.get('pullback_depth_pct', 0):.1f}% from 50-day high
ATR(14): ${features.get('atr_14', 0):.2f} ({features.get('atr_pct', 0):.1f}% of price)
Volume Ratio: {features.get('volume_ratio_20d', 0):.2f}x 20-day average

=== TRADE PARAMETERS ===
Score: {features.get('_score', 0):.0f}/100 | Confidence: {packet.confidence}/10
Entry Zone: {packet.entry_zone} | Stop: {packet.stop_invalidation} | Targets: {packet.targets}
Position Size: ${packet.position_sizing.allocation_dollars:.0f} ({packet.position_sizing.allocation_pct:.1f}% of capital)
Event Risk: {packet.event_risk}"""


def _parse_llm_response(response: str) -> tuple[int | None, str | None, str | None]:
    """Parse XML-tagged response into conviction, why_now, and deeper_analysis.

    Expected format:
        <why_now>...</why_now>
        <analysis>...</analysis>
        <metadata>Conviction: N\nDirection: ...\nTime Horizon: ...\nKey Risk: ...</metadata>

    Falls back to plain-text parsing if XML tags are not found (backward compat).

    Returns (conviction, why_now, deeper_analysis) or (None, None, None) on failure.
    """
    import re

    conviction = None
    why_now = None
    deeper_analysis = None

    # Diagnostic logging — raw response structure (#183)
    logger.info("[LLM] Raw response length: %d chars", len(response))
    logger.info("[LLM] First 200 chars: %s", response[:200].replace('\n', '\\n'))
    logger.info("[LLM] Last 200 chars: %s", response[-200:].replace('\n', '\\n'))
    tags_found = re.findall(r'<(\w+)[^>]*>', response)
    logger.info("[LLM] XML tags found: %s", list(set(tags_found)))

    # Strip markdown code fences if present (```xml ... ```)
    cleaned = re.sub(r'^```(?:xml)?\s*\n?', '', response.strip(), flags=re.MULTILINE)
    cleaned = re.sub(r'\n?```\s*$', '', cleaned.strip(), flags=re.MULTILINE)
    response = cleaned

    # Try XML parsing first (case-insensitive)
    wn_match = re.search(r'<why_now>(.*?)</why_now>', response, re.DOTALL | re.IGNORECASE)
    an_match = re.search(r'<analysis>(.*?)</analysis>', response, re.DOTALL | re.IGNORECASE)
    md_match = re.search(r'<metadata>(.*?)</metadata>', response, re.DOTALL | re.IGNORECASE)

    if wn_match:
        why_now = wn_match.group(1).strip()
    if an_match:
        deeper_analysis = an_match.group(1).strip()
    if md_match:
        metadata_text = md_match.group(1).strip()
        conv_match = re.search(r'Conviction:\s*(\d+)', metadata_text)
        if conv_match:
            raw_conv = int(conv_match.group(1))
            # #169: flag hallucinated conviction before clamping
            if raw_conv < 1 or raw_conv > 10:
                logger.warning("[LLM] Conviction %d outside 1-10 range — clamping", raw_conv)
            conviction = max(1, min(10, raw_conv))

    # Fallback to plain-text parsing for backward compatibility
    if why_now is None and "WHY NOW:" in response.upper():
        upper = response.upper()
        why_now_marker = "WHY NOW:"
        deeper_marker = "DEEPER ANALYSIS:"

        why_idx = upper.find(why_now_marker)
        deeper_idx = upper.find(deeper_marker)

        if why_idx != -1 and deeper_idx != -1:
            why_start = why_idx + len(why_now_marker)
            why_now = response[why_start:deeper_idx].strip()
            deeper_start = deeper_idx + len(deeper_marker)
            deeper_analysis = response[deeper_start:].strip()

    # Fallback conviction from CONVICTION: line (old format)
    if conviction is None and "CONVICTION:" in response.upper():
        conv_match = re.search(r'CONVICTION:\s*(\d+)', response, re.IGNORECASE)
        if conv_match:
            raw_conv = int(conv_match.group(1))
            # #169: flag hallucinated conviction before clamping
            if raw_conv < 1 or raw_conv > 10:
                logger.warning("[LLM] Conviction %d outside 1-10 range — clamping", raw_conv)
            conviction = max(1, min(10, raw_conv))

    # Fallback: <conviction>N</conviction> tag (#183)
    if conviction is None:
        conv_tag = re.search(r'<conviction[^>]*>\s*(\d+)', response, re.IGNORECASE)
        if conv_tag:
            raw_conv = int(conv_tag.group(1))
            if raw_conv < 1 or raw_conv > 10:
                logger.warning("[LLM] Conviction %d outside 1-10 range — clamping", raw_conv)
            conviction = max(1, min(10, raw_conv))

    # Fallback: "Conviction: 7/10" or "Conviction Score: 7" (#183)
    if conviction is None:
        conv_score = re.search(
            r'conviction\s*(?:score)?[:\s]+(\d+)(?:/10)?', response, re.IGNORECASE
        )
        if conv_score:
            raw_conv = int(conv_score.group(1))
            if raw_conv < 1 or raw_conv > 10:
                logger.warning("[LLM] Conviction %d outside 1-10 range — clamping", raw_conv)
            conviction = max(1, min(10, raw_conv))

    # Fallback: **Conviction:** 7 (markdown bold) (#183)
    if conviction is None:
        conv_md = re.search(r'\*\*conviction\*\*[:\s]+(\d+)', response, re.IGNORECASE)
        if conv_md:
            raw_conv = int(conv_md.group(1))
            if raw_conv < 1 or raw_conv > 10:
                logger.warning("[LLM] Conviction %d outside 1-10 range — clamping", raw_conv)
            conviction = max(1, min(10, raw_conv))

    # Fallback: if response has substantial prose but no tags, use first paragraph as why_now
    if not why_now and not deeper_analysis and len(response) > 200:
        paragraphs = [p.strip() for p in response.split('\n\n') if p.strip()]
        if len(paragraphs) >= 2:
            why_now = paragraphs[0]
            deeper_analysis = '\n\n'.join(paragraphs[1:])
            logger.debug("[LLM] Used prose fallback parsing (no XML tags found)")

    if not why_now or not deeper_analysis:
        logger.debug("[LLM] Raw response (parse failure): %s", response[:500])
        return conviction, None, None

    return conviction, why_now, deeper_analysis


def enhance_packet_with_llm(packet: TradePacket, features: dict,
                            config: dict) -> TradePacket:
    """Enhance a trade packet with LLM-written prose.

    If LLM is disabled or unavailable, returns the packet unchanged.
    Never modifies deterministic fields (entry, stop, targets, sizing, confidence, event_risk).

    Args:
        packet: The trade packet built from features.
        features: The raw feature dict for this ticker.
        config: Application config dict.

    Returns:
        The packet, potentially with enhanced why_now and deeper_analysis.
    """
    llm_cfg = config.get("llm", {})
    if not llm_cfg.get("enabled", False):
        logger.info("[LLM] Disabled in config — fallback to template for %s", packet.ticker)
        return packet

    prompt = _build_feature_prompt(packet, features)

    # #154: context window overflow protection
    estimated_tokens = len(prompt) // 4
    if estimated_tokens > _MAX_PROMPT_TOKENS:
        logger.warning(
            "[LLM] Prompt ~%d tokens exceeds %d limit for %s — using condensed prompt",
            estimated_tokens, _MAX_PROMPT_TOKENS, packet.ticker,
        )
        prompt = _build_condensed_prompt(packet, features)

    response = None
    grammar_enabled = llm_cfg.get("use_grammar_enforcement", False)

    if grammar_enabled:
        try:
            from src.llm.grammar_client import generate_with_grammar
            response = generate_with_grammar(
                prompt,
                PACKET_SYSTEM_PROMPT,
                max_tokens=llm_cfg.get("max_tokens", 1500),
                temperature=llm_cfg.get("temperature", 0.7),
            )
            if response is not None:
                logger.info("[LLM] Using grammar-constrained path for %s", packet.ticker)
        except Exception as exc:
            logger.warning("[LLM] Grammar path unavailable for %s: %s", packet.ticker, exc)

    if response is None:
        if not is_llm_available():
            logger.warning("[LLM] Ollama not reachable — fallback to template for %s", packet.ticker)
            return packet
        logger.info("[LLM] Using Ollama path for %s", packet.ticker)
        response = generate(prompt, PACKET_SYSTEM_PROMPT)

    if response is None:
        # Retry with condensed prompt (technical + trade params only, no enrichment)
        logger.info("[LLM] Full prompt timed out for %s, retrying with condensed prompt",
                    packet.ticker)
        condensed = _build_condensed_prompt(packet, features)
        response = generate(condensed, PACKET_SYSTEM_PROMPT)

    if response is None:
        logger.warning("[LLM] Generation failed — fallback to template for %s", packet.ticker)
        return packet

    conviction, why_now, deeper_analysis = _parse_llm_response(response)

    if why_now is None or deeper_analysis is None:
        logger.warning("[LLM] Failed to parse response — fallback to template for %s", packet.ticker)
        return packet

    # #168: if conviction is None after parsing, default to 5 for paper trades
    if conviction is None:
        conviction = 5
        logger.warning("[LLM] Conviction is None for %s — defaulting to %d", packet.ticker, conviction)

    # Only update prose fields — never touch deterministic fields
    packet.why_now = why_now
    packet.deeper_analysis = deeper_analysis
    packet.llm_conviction = conviction
    logger.info("[LLM] Enhanced packet for %s (conviction: %s)", packet.ticker,
                conviction if conviction else "n/a")

    # Run canary rules-based scorer alongside LLM for comparison
    try:
        from src.strategy.canary import compute_canary_score
        canary = compute_canary_score(features)
        canary_score = canary.get("score") if isinstance(canary, dict) else canary
        logger.info("[CANARY] %s: rules-based score=%.1f, LLM conviction=%s",
                    packet.ticker, canary_score or 0, conviction or "n/a")
    except Exception as e:
        logger.debug("[CANARY] Scoring failed for %s: %s", packet.ticker, e)

    return packet
