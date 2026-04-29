"""LLM-enhanced trade packet writer with template fallback.

Called by: scheduler.watch, services.scan_service
Calls: llm.client, llm.grammar_client, llm.prompts, models, strategy.canary, universe.company_names
Owns tables: none
Config keys: enabled, llm, max_tokens, temperature, use_grammar_enforcement
Tests: tests/test_confidence.py, tests/test_grammar_client.py, tests/test_xml_format.py

WHY this module exists:
    Deterministic scoring (features/engine.py) decides WHAT to trade and at
    what size. The LLM adds WHY-NOW prose and a conviction score that serves
    two purposes: (1) human-readable trade packets for the journal, and
    (2) a second opinion that feeds the champion-challenger canary framework.

    The LLM NEVER overwrites deterministic fields (entry, stop, targets, sizing,
    confidence, event_risk). This separation is sacred -- #6 established that
    mechanical parameters must remain rules-based until 200+ live trades provide
    enough data for the LLM to earn trust.

WHY so many conviction-parsing fallbacks (#183):
    Qwen3 8B produces conviction scores in wildly different formats across runs:
    XML tags, markdown bold, "Conviction: 7/10", bare numbers, etc. Each fallback
    was added in response to a production failure where conviction parsed as None,
    causing trades to silently default to conviction=5 (#168). The cascade order
    matters -- XML (most structured) is tried first, then progressively looser
    patterns, with prose fallback as the last resort.
"""

import logging
import random
import re
from datetime import datetime

from src.llm.client import is_llm_available, generate
from src.llm.prompts import PACKET_SYSTEM_PROMPT
from src.models import TradePacket
from src.universe.company_names import get_company_name

logger = logging.getLogger(__name__)

# B4: truncation ceiling for llm_conviction_reason (Key Risk: line).
# WHY 4000: Key Risk is normally 1 sentence (40-120 chars). The ceiling is a
# safety net for future model versions that might emit verbose reason text.
# PR-690 O13b: This is a HARD ceiling — _truncate_conviction_reason reserves
# space for the truncation marker so the returned string never exceeds it.
_MAX_CONVICTION_REASON_CHARS = 4000

# PR-690 O13b: Truncation marker template + reserved budget. The marker is
# appended only when text exceeds the ceiling; the body is shrunk by the
# reserved budget so total length stays at or below _MAX_CONVICTION_REASON_CHARS.
# WHY 60: a 19-digit original-length integer (covers ~10**18 chars, more than
# any plausible LLM emission) plus the literal "... [truncated, original  chars]"
# (32 chars) sums to 51; rounding up to 60 leaves headroom for any future
# template tweak without recomputing the constant.
_TRUNCATION_MARKER_TEMPLATE = "... [truncated, original {n} chars]"
_TRUNCATION_MARKER_BUDGET = 60

# #154: context window overflow protection -- max tokens before truncation.
# WHY 7000: Qwen3 8B has an 8192-token context window. The system prompt
# consumes ~800 tokens and we need ~400 for the response. 7000 leaves
# comfortable headroom while maximizing the context the model can use.
# When exceeded, we fall back to _build_condensed_prompt() which strips
# enrichment sections (fundamentals, news, insider, macro).
_MAX_PROMPT_TOKENS = 7000

# #156: patterns to strip from enrichment text to block prompt injection.
# WHY this matters: enrichment text (news, fundamentals, insider) is fetched
# from external APIs (Finnhub, SEC filings) and could contain adversarial
# content. A crafted news headline like "<system>ignore previous instructions"
# could hijack the model. We strip XML-like tags and common instruction
# patterns before they enter the prompt.
_INJECTION_TAG_RE = re.compile(r"<[^>]+>", re.DOTALL)
_INJECTION_INSTRUCTION_RE = re.compile(
    r"\b(?:you are|ignore previous)\b|"
    r"\b(?:system|assistant|human)\s*:",
    re.IGNORECASE,
)
# WHY 500 chars: enrichment beyond this length adds noise without improving
# analysis quality. Finnhub news summaries in particular can include full
# article bodies that bloat the prompt past the context window limit (#154).
_ENRICHMENT_CHAR_CAP = 500


def _truncate_conviction_reason(text: str) -> str:
    """Truncate conviction reason so the result never exceeds _MAX_CONVICTION_REASON_CHARS.

    When ``len(text) > _MAX_CONVICTION_REASON_CHARS``, the body is sliced to
    ``_MAX_CONVICTION_REASON_CHARS - _TRUNCATION_MARKER_BUDGET`` characters and
    a marker like ``"... [truncated, original 4523 chars]"`` is appended. The
    returned string length is therefore guaranteed to be <= the ceiling.

    PR-690 O13b: previously the marker was appended to a body already at the
    ceiling, so the stored value could overrun by ~30 chars and the docstring
    description ("truncated at 4000 chars") was misleading.
    """
    if len(text) <= _MAX_CONVICTION_REASON_CHARS:
        return text
    original_len = len(text)
    body_budget = _MAX_CONVICTION_REASON_CHARS - _TRUNCATION_MARKER_BUDGET
    body = text[:body_budget]
    marker = _TRUNCATION_MARKER_TEMPLATE.format(n=original_len)
    return body + marker


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


def _interpret_skew(features: dict) -> str:
    """Interpret IV skew value for the OPTIONS FLOW section.

    Returns a human-readable description of what the 25-delta skew implies
    about market positioning.
    """
    skew = features.get('iv_skew_25d')
    if skew is None:
        return 'n/a'
    try:
        skew = float(skew)
    except (ValueError, TypeError):
        return 'n/a'
    if skew > 0.05:
        return 'Elevated put demand (bearish hedging)'
    if skew < -0.02:
        return 'Call skew (bullish speculation)'
    return 'Normal skew'


# Sections that are always included regardless of subsetting.
# Technical (1), Market Regime (2), Macro (7), Event Calendar (9).
_REQUIRED_SECTIONS = {1, 2, 7, 9}
# Sections eligible for random omission during training subsetting.
_OPTIONAL_SECTIONS = {3, 4, 5, 6, 8, 10, 11}


def _build_feature_prompt(features: dict, ticker: str, subsetting: bool = False) -> str:
    """Build a multi-source prompt from all available data.

    WHY 11 sections in this specific order: the model performs best when
    technical data (most structured) comes first, followed by contextual
    overlays (regime, sector, fundamentals), then event/options/earnings
    signals, and cross-asset context last. This mirrors how an analyst
    reads a setup: price action first, then context, then what could
    catalyze or derail the trade. The order also matches the training
    data format from data_collector.py, so the model sees prompts at
    inference time that match its training distribution.

    When subsetting=True (training only), 1-3 optional sections are
    randomly omitted ~30% of the time to teach the model robustness
    when data sources are unavailable.
    """
    company_name = features.get('company_name', get_company_name(ticker))

    # Determine which sections to skip for training subsetting.
    # WHY 30%: we want the model to see full data most of the time,
    # but occasionally train on partial data so it doesn't collapse
    # when a data source is unavailable during live inference.
    skip_sections = set()
    if subsetting and random.random() < 0.3:
        n_drop = random.randint(1, 3)
        skip_sections = set(random.sample(sorted(_OPTIONAL_SECTIONS), n_drop))

    prompt = ""

    # SECTION 1: Technical Data (required)
    prompt += f"""=== TECHNICAL DATA ===
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

    # SECTION 2: Market Regime (required)
    prompt += f"""

=== MARKET REGIME ===
Market Trend: {features.get('market_trend', 'n/a')} | SPY RSI(14): {features.get('spy_rsi_14', 'n/a')}
Volatility: {features.get('volatility_regime', 'n/a')} ({features.get('vix_proxy', 0):.1f}% realized vol)
SPY: {features.get('spy_20d_return', 0):+.1f}% (20d) | {features.get('spy_drawdown_from_high', 0):.1f}% from 52-week high
Breadth: {features.get('market_breadth_label', 'n/a')} ({features.get('market_breadth_pct', 0):.0f}% above 50d MA)
Regime: {features.get('regime_label', 'n/a')}"""

    # SECTION 3: Sector Relative (optional, enhanced)
    if 3 not in skip_sections:
        prompt += f"""

=== SECTOR RELATIVE ===
Sector: {features.get('sector', 'n/a')} ({features.get('sector_etf', 'n/a')})
Stock vs SPY (3m): {features.get('rs_vs_spy_3m', 0):+.1f}%
Stock vs Sector ETF (3m): {features.get('rs_vs_sector_3m', 'n/a')}
Sector vs SPY (3m): {features.get('sector_vs_spy_3m', 'n/a')}
Sector Rotation Signal: {features.get('sector_rotation_signal', 'n/a')}
Sector Rank (of 11): {features.get('sector_rank', 'n/a')}"""

    # SECTION 4: Fundamental Snapshot (optional) -- #156: sanitize enrichment
    if 4 not in skip_sections:
        fundamental_text = _sanitize_enrichment_text(
            features.get('fundamental_summary', 'No fundamental data available')
        )
        prompt += f"""

=== FUNDAMENTAL SNAPSHOT ===
{fundamental_text}"""

    # SECTION 5: Insider Activity (optional) -- #156: sanitize enrichment
    if 5 not in skip_sections:
        insider_text = _sanitize_enrichment_text(
            features.get('insider_summary', 'No insider data available')
        )
        prompt += f"""

=== INSIDER ACTIVITY ===
{insider_text}"""

    # SECTION 6: Recent News (optional) -- #156: sanitize enrichment
    if 6 not in skip_sections:
        news_text = _sanitize_enrichment_text(
            features.get('news_summary', 'No recent news')
        )
        prompt += f"""

=== RECENT NEWS ===
{news_text}"""

    # SECTION 7: Macro Context (required) -- #156: sanitize enrichment
    macro_text = _sanitize_enrichment_text(
        features.get('macro_summary', 'No macro data available')
    )
    prompt += f"""

=== MACRO CONTEXT ===
{macro_text}"""

    # SECTION 8: Options Flow (optional, enhanced from old 7.5)
    if 8 not in skip_sections:
        prompt += f"""

=== OPTIONS FLOW ===
ATM IV (30d): {features.get('atm_iv_30d', 'n/a')}
IV Rank: {features.get('iv_rank', 'n/a')} | IV Percentile: {features.get('iv_percentile', 'n/a')}
IV Skew (25d): {features.get('iv_skew_25d', 'n/a')}
Skew Interpretation: {_interpret_skew(features)}
Put/Call Volume Ratio: {features.get('put_call_vol_ratio', 'n/a')}
Put/Call OI Ratio: {features.get('put_call_oi_ratio', 'n/a')}"""

    # SECTION 9: Event Calendar (required, enhanced from old 7.6)
    prompt += f"""

=== EVENT CALENDAR ===
Days to Next Earnings: {features.get('days_to_earnings', 'n/a')}
Earnings Timing: {features.get('earnings_timing', 'n/a')}
Days to Next FOMC: {features.get('days_to_fomc', 'n/a')}
Days to Next OPEX: {features.get('days_to_opex', 'n/a')}
Combined Event Risk Score: {features.get('event_risk_score', 'n/a')}/10
Active Events: {features.get('active_events_description', 'None')}"""

    # SECTION 10: Earnings Signals (optional, promoted from old 7.7)
    if 10 not in skip_sections:
        prompt += f"""

=== EARNINGS SIGNALS ===
Last EPS Surprise: {features.get('last_eps_surprise_pct', 'n/a')}%
Last Revenue Surprise: {features.get('last_revenue_surprise_pct', 'n/a')}%
Surprise Streak: {features.get('surprise_streak', 'n/a')} quarters
Analyst Revision Momentum: {features.get('revision_momentum', 'n/a')}
EPS Estimate Trend (90d): {features.get('eps_estimate_trend', 'n/a')}"""

    # SECTION 11: Cross-Asset Context (optional, NEW)
    if 11 not in skip_sections:
        prompt += f"""

=== CROSS-ASSET CONTEXT ===
US 10Y Yield: {features.get('us_10y_yield', 'n/a')}% ({features.get('us_10y_change_1m', 'n/a')} 1m)
US Dollar Index: {features.get('dxy_level', 'n/a')} ({features.get('dxy_change_1m', 'n/a')} 1m)
VIX Term Structure: {features.get('vix_term_structure', 'n/a')}
HY Credit Spread: {features.get('hy_oas', 'n/a')} bps ({features.get('hy_oas_z_score', 'n/a')} Z)
Gold: {features.get('gold_change_1m', 'n/a')} (1m)"""

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


_PROMPT_LEAK_MARKERS = [
    "Write a concise trade commentary",
    "OUTPUT FORMAT:",
    "RULES:",
    "Detailed analysis here",
    "Strong momentum setup</why_now><analysis>Detailed analysis here",
]


def _validate_llm_output(response: str, ticker: str) -> str | None:
    """Reject contaminated LLM responses before they reach the parser (#384).

    Returns the cleaned response, or None if the response is unsalvageable.
    Detects: prompt leakage, template stubs, degenerate repetition loops.
    """
    if not response or not response.strip():
        return None

    # Prompt leakage: system instructions echoed in output
    for marker in _PROMPT_LEAK_MARKERS:
        if marker in response:
            logger.warning("[LLM] Prompt leakage detected for %s: '%s'",
                           ticker, marker[:40])
            return None

    # Degenerate repetition: same line repeated 5+ times
    lines = response.strip().splitlines()
    if len(lines) >= 10:
        from collections import Counter
        counts = Counter(line.strip() for line in lines if line.strip())
        most_common_count = counts.most_common(1)[0][1] if counts else 0
        if most_common_count >= 5:
            logger.warning("[LLM] Repetition loop detected for %s: line repeated %d times",
                           ticker, most_common_count)
            return None

    return response


def _detect_conviction_strategy(response: str) -> str | None:
    """Return the stable identifier of the conviction-parse strategy that
    `_parse_llm_response` would use for this raw response, or None if all
    strategies miss. Sprint 1.C Phase 4 follow-up #98.

    Mirrors the cascade in `_parse_llm_response` exactly — same order, same
    cleaning, same regexes. Run as a separate post-hoc pass so the parser's
    5-tuple return shape stays stable for the dozens of existing callers and
    test sites.

    Strategy identifiers (the dataset contract — must not change once written):

      metadata_block    — XML <metadata>Conviction: N</metadata>
      plain_conviction  — Plain "CONVICTION: N" (legacy pre-XML format)
      conviction_tag    — <conviction>N</conviction> tag
      conviction_score  — "Conviction: N/10" / "Conviction Score: N"
      markdown_bold     — **Conviction:** N (markdown bold)
      catchall          — Stage 6 (#309): any digit within 20 chars of "conviction"
      confidence_label  — Stage 7 (#329): "confidence: N" / "conviction level: N"
      bare_score        — Stage 8 (#329): standalone "N/10" on a line
    """
    if not response:
        return None

    # Same cleaning as _parse_llm_response — strip markdown fences and the
    # section-header regurgitation. Drift between the two cleaners would cause
    # the strategy label to disagree with the actual conviction extraction.
    cleaned = re.sub(r'^```(?:xml)?\s*\n?', '', response.strip(), flags=re.MULTILINE)
    cleaned = re.sub(r'\n?```\s*$', '', cleaned.strip(), flags=re.MULTILINE)
    cleaned = re.sub(r'^={2,}\s*[A-Z][A-Z /&]+\s*={2,}\s*$', '', cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r'\n{3,}', '\n\n', cleaned).strip()

    # Strategy 1: metadata_block — only fires when the conviction is INSIDE
    # the <metadata> block. We must scope the match to that substring or a
    # `<metadata>...Conviction: N...</metadata>` would also satisfy the more
    # permissive later regexes and we'd mislabel which one fired.
    md_match = re.search(r'<metadata>(.*?)</metadata>', cleaned, re.DOTALL | re.IGNORECASE)
    if md_match:
        if re.search(r'Conviction:\s*\d+', md_match.group(1)):
            return "metadata_block"

    # Strategy 2: plain_conviction
    if "CONVICTION:" in cleaned.upper() and re.search(r'CONVICTION:\s*\d+', cleaned, re.IGNORECASE):
        return "plain_conviction"

    # Strategy 3: conviction_tag
    if re.search(r'<conviction[^>]*>\s*\d+', cleaned, re.IGNORECASE):
        return "conviction_tag"

    # Strategy 4: conviction_score
    if re.search(r'conviction\s*(?:score)?[:\s]+\d+(?:/10)?', cleaned, re.IGNORECASE):
        return "conviction_score"

    # Strategy 5: markdown_bold
    if re.search(r'\*\*conviction\*\*[:\s]+\d+', cleaned, re.IGNORECASE):
        return "markdown_bold"

    # Strategy 6: catchall — guarded by 1<=N<=10 to mirror the parser's filter
    catchall = re.search(r'(?i)conviction\D{0,20}(\d{1,2})', cleaned)
    if catchall and 1 <= int(catchall.group(1)) <= 10:
        return "catchall"

    # Strategy 7: confidence_label — guarded by 1<=N<=10
    conf_match = re.search(
        r'(?:confidence|conviction)\s*(?:level)?[:\s]+(\d+)\s*(?:/\s*10)?',
        cleaned, re.IGNORECASE,
    )
    if conf_match and 1 <= int(conf_match.group(1)) <= 10:
        return "confidence_label"

    # Strategy 8: bare_score — guarded by 1<=N<=10
    line_match = re.search(r'^(\d+)\s*/\s*10\s*$', cleaned, re.MULTILINE)
    if line_match and 1 <= int(line_match.group(1)) <= 10:
        return "bare_score"

    return None


def _parse_llm_response(response: str) -> tuple[
    int | None, str | None, str | None, str | None, int | None
]:
    """Parse XML-tagged response into conviction, why_now, deeper_analysis,
    conviction_reason (B4), and timeout_days (B8).

    Expected format:
        <why_now>...</why_now>
        <analysis>...</analysis>
        <metadata>
        Conviction: N
        Direction: LONG
        Time Horizon: ...
        Key Risk: [one sentence]
        Expected Holding Period: N days
        </metadata>

    Falls back to plain-text parsing if XML tags are not found (backward compat).

    Returns (conviction, why_now, deeper_analysis, conviction_reason, timeout_days).
    All fields are None on failure; conviction defaults to 5 in the caller (#168).

    Which conviction-parse strategy fired is NOT returned here — call
    ``_detect_conviction_strategy(response)`` separately for that label
    (Sprint 1.C Phase 4 follow-up #98). Splitting the two keeps this function's
    5-tuple return shape stable for the dozens of existing call/test sites.

    B4: Key Risk: line → llm_conviction_reason (multi-line capture via DOTALL,
        whitespace-normalized, total length <= _MAX_CONVICTION_REASON_CHARS).
    B8: Expected Holding Period: N days → llm_timeout_days (validated 1-60, int).
        Out-of-range or non-integer → NULL + [LLM_TIMEOUT_INVALID] warning.

    #183 — This function has 8 conviction extraction strategies because Qwen3 8B
    is inconsistent about output format across temperature=0.7 runs. Each fallback
    was added after a production incident where conviction parsed as None. The
    strategy identifiers (defined in ``_CONVICTION_STRATEGY_LABELS``) are STABLE
    — they're recorded on each CorpusEntry via `parser_strategy_succeeded` and
    consumed by Stage 1 walk-forward analysis.

      1. metadata_block   — XML <metadata>Conviction: N</metadata>
      2. plain_conviction — Plain text "CONVICTION: N" (legacy pre-XML format)
      3. conviction_tag   — <conviction>N</conviction> tag (Qwen invents this)
      4. conviction_score — "Conviction: 7/10" or "Conviction Score: 7"
      5. markdown_bold    — **Conviction:** 7
      6. catchall         — Stage 6 (#309): any digit within 20 chars of "conviction"
      7. confidence_label — Stage 7 (#329): "confidence: N" or "conviction level: N"
      8. bare_score       — Stage 8 (#329): standalone "N/10" on a line

    If all 8 fail, #168 sets conviction=5 in the caller (neutral default for
    paper trading where a missing conviction should not block the trade).
    """
    import re

    conviction = None
    why_now = None
    deeper_analysis = None
    conviction_reason = None
    timeout_days = None

    # Diagnostic logging — raw response structure (#183)
    logger.info("[LLM] Raw response length: %d chars", len(response))
    logger.info("[LLM] First 200 chars: %s", response[:200].replace('\n', '\\n'))
    logger.info("[LLM] Last 200 chars: %s", response[-200:].replace('\n', '\\n'))
    tags_found = re.findall(r'<(\w+)[^>]*>', response)
    logger.info("[LLM] XML tags found: %s", list(set(tags_found)))

    # WHY strip markdown code fences: Qwen3 frequently wraps XML output in
    # ```xml ... ``` blocks, which breaks the regex tag extraction below.
    cleaned = re.sub(r'^```(?:xml)?\s*\n?', '', response.strip(), flags=re.MULTILINE)
    cleaned = re.sub(r'\n?```\s*$', '', cleaned.strip(), flags=re.MULTILINE)

    # #251: Strip raw template headers the LLM regurgitates from the prompt.
    # WHY this happens: the input prompt uses "=== TECHNICAL DATA ===" section
    # headers, and Qwen3 sometimes echoes these back verbatim as part of its
    # response. This pollutes the stored why_now/deeper_analysis with formatting
    # artifacts that confuse the frontend display and degrade training data quality.
    cleaned = re.sub(r'^={2,}\s*[A-Z][A-Z /&]+\s*={2,}\s*$', '', cleaned, flags=re.MULTILINE)
    # Collapse resulting blank lines from header removal
    cleaned = re.sub(r'\n{3,}', '\n\n', cleaned).strip()

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

        # B4: Extract Key Risk line → conviction_reason (truncate at 4000 chars).
        # PR-690 O13a: Use re.DOTALL so '.' matches newlines. The prompt
        # (src/llm/prompts.py) instructs the model to emit Key Risk as ONE
        # sentence, but Qwen3 occasionally wraps the sentence across newlines,
        # which previously caused silent truncation at the first '\n'. We
        # capture up to the next metadata field (Expected Holding Period) or
        # end-of-block, then collapse internal whitespace so the dashboard's
        # inline quote (frontend/src/pages/{TradeHistory,ShadowLedger}.jsx)
        # renders cleanly on a single line. End-marker is anchored on a line
        # boundary to avoid swallowing the next field.
        key_risk_match = re.search(
            r'Key Risk:\s*(.+?)(?=\n\s*(?:Expected Holding Period|Direction|Time Horizon|Conviction)\s*:|\Z)',
            metadata_text,
            re.DOTALL | re.IGNORECASE,
        )
        if key_risk_match:
            raw_risk = key_risk_match.group(1).strip()
            # Collapse newlines and runs of whitespace into single spaces so
            # multi-line capture is preserved as a single visual line.
            normalized_risk = re.sub(r'\s+', ' ', raw_risk).strip()
            conviction_reason = _truncate_conviction_reason(normalized_risk)

        # B8: Extract Expected Holding Period: N [days] → timeout_days (validate 1-60)
        # Capture the full remainder of the line so "2 weeks" is not truncated to "2".
        holding_match = re.search(r'Expected Holding Period:\s*(.+)', metadata_text)
        if holding_match:
            raw_hp = holding_match.group(1).strip()
            # Strip trailing "days" suffix (case-insensitive) before int conversion
            stripped_hp = re.sub(r'\s+days?\s*$', '', raw_hp, flags=re.IGNORECASE).strip()
            try:
                parsed_hp = int(stripped_hp)
                if 1 <= parsed_hp <= 60:
                    timeout_days = parsed_hp
                else:
                    logger.warning(
                        "[LLM_TIMEOUT_INVALID] received=%r fallback=NULL", raw_hp
                    )
            except (ValueError, TypeError):
                logger.warning(
                    "[LLM_TIMEOUT_INVALID] received=%r fallback=NULL", raw_hp
                )

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

    # Stage 6: Catch-all — any digit within 20 chars of "conviction" (#309)
    if conviction is None:
        conv_catchall = re.search(r'(?i)conviction\D{0,20}(\d{1,2})', response)
        if conv_catchall:
            raw_conv = int(conv_catchall.group(1))
            if 1 <= raw_conv <= 10:
                conviction = raw_conv
                logger.debug("[LLM] Stage 6 catch-all matched conviction=%d", conviction)

    # Stage 7 (#329): "confidence: N/10", "confidence level: N", or bare
    # "N/10" on a line by itself. The model sometimes uses "confidence"
    # instead of "conviction", or outputs a standalone score line.
    if conviction is None:
        conf_match = re.search(
            r'(?:confidence|conviction)\s*(?:level)?[:\s]+(\d+)\s*(?:/\s*10)?',
            response, re.IGNORECASE,
        )
        if conf_match:
            raw_conv = int(conf_match.group(1))
            if 1 <= raw_conv <= 10:
                conviction = raw_conv
                logger.debug("[LLM] Stage 7 confidence/conviction matched=%d", conviction)

    # Stage 8 (#329): "N/10" standalone on a line — common in short responses
    if conviction is None:
        line_match = re.search(r'^(\d+)\s*/\s*10\s*$', response, re.MULTILINE)
        if line_match:
            raw_conv = int(line_match.group(1))
            if 1 <= raw_conv <= 10:
                conviction = raw_conv
                logger.debug("[LLM] Stage 8 standalone N/10 matched=%d", conviction)

    # Prose fallback: if the response has substantial text but no XML tags or
    # section markers, split on paragraph boundaries. First paragraph becomes
    # why_now (the "hook"), remainder becomes deeper_analysis.
    # WHY 200-char minimum: short responses are usually error messages or
    # partial generations, not usable prose. Below 200 chars we'd rather
    # return None and let the caller fall back to template text.
    if not why_now and not deeper_analysis and len(response) > 200:
        paragraphs = [p.strip() for p in response.split('\n\n') if p.strip()]
        if len(paragraphs) >= 2:
            why_now = paragraphs[0]
            deeper_analysis = '\n\n'.join(paragraphs[1:])
            logger.debug("[LLM] Used prose fallback parsing (no XML tags found)")

    if not why_now or not deeper_analysis:
        logger.debug("[LLM] Raw response (parse failure): %s", response[:500])
        return conviction, None, None, None, None

    return conviction, why_now, deeper_analysis, conviction_reason, timeout_days


def enhance_packet_with_llm(packet: TradePacket, features: dict,
                            config: dict) -> TradePacket:
    """Enhance a trade packet with LLM-written prose.

    If LLM is disabled or unavailable, returns the packet unchanged.
    Never modifies deterministic fields (entry, stop, targets, sizing,
    confidence, event_risk). This separation is critical -- see #6: equal
    weight between rules-based and LLM systems is maintained until 200+
    trades validate the LLM's conviction calibration. The LLM writes prose
    and provides a conviction score, but the mechanical system controls
    all trade parameters and sizing. #18: bracket exits are always mechanical.

    The retry cascade is:
    1. Grammar-constrained generation (if enabled) -- most structured output
    2. Full prompt via Ollama -- all 11 context sections
    3. Condensed prompt via Ollama -- technical data + trade params only
    4. Template fallback -- returns packet unchanged with default prose

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

    packet.llm_conviction_parse_failed = False

    prompt = _build_feature_prompt(features, packet.ticker)

    # Append trade parameters (not part of the 11 data sections)
    prompt += f"""

=== TRADE PARAMETERS ===
Score: {features.get('_score', 0):.0f}/100 | Confidence: {packet.confidence}/10
Entry Zone: {packet.entry_zone} | Stop: {packet.stop_invalidation} | Targets: {packet.targets}
Position Size: ${packet.position_sizing.allocation_dollars:.0f} ({packet.position_sizing.allocation_pct:.1f}% of capital) | Risk: ${packet.position_sizing.estimated_risk_dollars:.2f}
Event Risk: {packet.event_risk}"""

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

    # #384: reject contaminated responses before parsing
    response = _validate_llm_output(response, packet.ticker)
    if response is None:
        logger.warning("[LLM] Response rejected by validation — fallback to template for %s",
                       packet.ticker)
        packet.llm_conviction = 5
        packet.llm_conviction_parse_failed = True
        return packet

    conviction, why_now, deeper_analysis, conviction_reason, timeout_days = _parse_llm_response(response)

    # #98: surface which conviction-parse strategy fired (or None) so the
    # corpus generator can record it on each CorpusEntry. The label is
    # produced by an independent post-hoc cascade so `_parse_llm_response`'s
    # 5-tuple return shape stays stable for the dozens of existing callers.
    packet.parser_strategy_succeeded = _detect_conviction_strategy(response)

    if why_now is None or deeper_analysis is None:
        logger.warning("[LLM] Failed to parse response — fallback to template for %s", packet.ticker,
                       extra={"ctx": {"event": "parse_failure", "ticker": packet.ticker}})
        # #318: set conviction before returning so it never leaks as None
        packet.llm_conviction = conviction if conviction is not None else 5
        packet.llm_conviction_parse_failed = True
        return packet

    # #168: if conviction is None after all 5 parsing strategies, default to 5.
    # WHY 5 and not reject: during paper trading, a missing conviction should
    # not block the trade -- we need live trade data to improve the model.
    # 5 is the midpoint of the 1-10 scale, expressing no directional opinion.
    # In live trading this default should be reconsidered (likely reject).
    if conviction is None:
        conviction = 5
        packet.llm_conviction_parse_failed = True
        _raw_preview = repr(response[:500]) if response else "EMPTY"
        logger.warning(
            "[LLM] Conviction is None for %s — defaulting to %d. "
            "Response preview: %s",
            packet.ticker, conviction, _raw_preview,
            extra={"ctx": {"event": "conviction_default", "ticker": packet.ticker, "default": conviction}},
        )
        # Write full response to debug file for offline analysis (#312)
        try:
            from pathlib import Path
            debug_dir = Path("logs/llm_debug")
            debug_dir.mkdir(exist_ok=True)
            (debug_dir / f"{packet.ticker}_{datetime.now().strftime('%H%M%S')}.txt").write_text(
                response or "EMPTY", encoding="utf-8")
        except Exception:
            pass
    else:
        packet.llm_conviction_parse_failed = False

    # Only update prose fields — never touch deterministic fields
    packet.why_now = why_now
    packet.deeper_analysis = deeper_analysis
    packet.llm_conviction = conviction
    packet.llm_conviction_reason = conviction_reason
    packet.llm_timeout_days = timeout_days
    logger.info("[LLM] Enhanced packet for %s (conviction: %s)", packet.ticker,
                conviction if conviction else "n/a")

    # WHY canary scoring runs here: the champion-challenger framework logs
    # both the LLM conviction and a pure rules-based score for every trade.
    # Over time, comparing the two reveals whether the LLM adds alpha or
    # just noise. This is the data that will eventually justify moving past
    # #6's equal-weight constraint once we have 200+ trades.
    # Fix for #268: corrected import path (function is canary_score, not compute_canary_score)
    try:
        from src.strategy.canary import canary_score
        score = canary_score(features)
        logger.info("[CANARY] %s: rules-based score=%d, LLM conviction=%s",
                    packet.ticker, score, conviction or "n/a")
    except Exception as e:
        logger.debug("[CANARY] Scoring failed for %s: %s", packet.ticker, e)

    return packet
