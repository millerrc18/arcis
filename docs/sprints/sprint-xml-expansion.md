# Sprint: Expand Training XML 7→11 Sections + Random Source Subsetting

> **Priority:** MEDIUM — improves training data quality and model robustness
> **Estimated time:** 3-4 hours CC time
> **Branch:** `feat/xml-expansion`
> **Access:** LOCAL — requires reading current prompts and training data

> ⚠️ **Files touched:** `src/llm/packet_writer.py`, `src/llm/prompts.py`,
> `src/training/data_collector.py`, `src/training/outcome_prompts.py`,
> `src/features/engine.py`, `tests/test_xml_format.py`
> Zero overlap with gap-assessment, simulation-engine, or ui-bloomberg sprints.

---

## Context

The LLM prompt currently has 7 main sections + 3 sub-sections (7.5, 7.6, 7.7):

1. Technical Data (price, trend, RS, pullback, ATR, volume)
2. Market Regime (SPY, VIX, breadth, regime label)
3. Sector Context (sector performance, relative positioning)
4. Fundamental Snapshot (from Finnhub — news sentiment, analyst estimates)
5. Insider Activity (from Finnhub — buys/sells, net shares)
6. Recent News (from Finnhub — headlines, sentiment)
7. Macro Context (from FRED — rates, yield curve, CPI)
7.5. Options Context (IV rank, put/call ratio — basic)
7.6. Event Context (earnings proximity, FOMC flag)
7.7. Earnings Context (surprise history)

The roadmap item specifies 4 new sections plus random source subsetting.

---

## Pre-Flight

1. Read `MASTER.md`
2. Read `src/llm/packet_writer.py` — specifically `_build_feature_prompt()` (the main prompt builder)
3. Read `src/llm/prompts.py` — the system prompt
4. Read `src/training/data_collector.py` — how training examples are generated
5. Read `src/training/outcome_prompts.py` — outcome-conditioned templates
6. Run `python -m pytest tests/test_xml_format.py -v` — baseline XML tests
7. Check current prompt token count: `python -c "from src.llm.packet_writer import _build_feature_prompt; print(len(_build_feature_prompt({}, 'TEST').split()))"`

---

## Task 1: Restructure to Clean 11 Sections

Refactor `_build_feature_prompt()` in `src/llm/packet_writer.py` to have clean numbered sections:

```
Section 1:  TECHNICAL DATA (existing — keep as-is)
Section 2:  MARKET REGIME (existing — keep as-is)
Section 3:  SECTOR RELATIVE (enhanced — add sector ETF RS, sector rotation signal)
Section 4:  FUNDAMENTAL SNAPSHOT (existing — keep as-is)
Section 5:  INSIDER ACTIVITY (existing — keep as-is)
Section 6:  RECENT NEWS (existing — keep as-is)
Section 7:  MACRO CONTEXT (existing — keep as-is)
Section 8:  OPTIONS FLOW (enhanced — expand from 7.5 with skew interpretation)
Section 9:  EVENT CALENDAR (enhanced — expand from 7.6 with countdown + compound risk)
Section 10: EARNINGS SIGNALS (promoted from 7.7 — add revision momentum)
Section 11: CROSS-ASSET CORRELATION (NEW — bond yields, dollar, oil, VIX term structure)
```

### Section 3 Enhancement: SECTOR RELATIVE

The gap assessment sprint (#297) adds two-tier RS to the ranker. Use the same sector
RS data in the prompt:

```python
# SECTION 3: Sector Relative (enhanced)
sector = features.get('sector', 'n/a')
sector_etf = features.get('sector_etf', 'n/a')
prompt += f"""

=== SECTOR RELATIVE ===
Sector: {sector} ({sector_etf})
Stock vs SPY (3m): {features.get('rs_vs_spy_3m', 0):+.1f}%
Stock vs Sector ETF (3m): {features.get('rs_vs_sector_3m', 'n/a')}
Sector vs SPY (3m): {features.get('sector_vs_spy_3m', 'n/a')}
Sector Rotation Signal: {features.get('sector_rotation_signal', 'n/a')}
Sector Rank (of 11): {features.get('sector_rank', 'n/a')}"""
```

If sector RS data is unavailable (gap assessment sprint hasn't merged yet),
gracefully fall back to existing Section 3 format. Use `features.get()` with defaults.

### Section 8: OPTIONS FLOW (enhanced)

```python
# SECTION 8: Options Flow (enhanced from 7.5)
prompt += f"""

=== OPTIONS FLOW ===
ATM IV (30d): {features.get('atm_iv_30d', 'n/a')}
IV Rank: {features.get('iv_rank', 'n/a')} | IV Percentile: {features.get('iv_percentile', 'n/a')}
IV Skew (25Δ): {features.get('iv_skew_25d', 'n/a')}
Skew Interpretation: {_interpret_skew(features)}
Put/Call Volume Ratio: {features.get('put_call_vol_ratio', 'n/a')}
Put/Call OI Ratio: {features.get('put_call_oi_ratio', 'n/a')}"""
```

Add helper:
```python
def _interpret_skew(features):
    skew = features.get('iv_skew_25d')
    if skew is None: return 'n/a'
    if skew > 0.05: return 'Elevated put demand (bearish hedging)'
    if skew < -0.02: return 'Call skew (bullish speculation)'
    return 'Normal skew'
```

### Section 9: EVENT CALENDAR (enhanced)

```python
# SECTION 9: Event Calendar (enhanced from 7.6)
prompt += f"""

=== EVENT CALENDAR ===
Days to Next Earnings: {features.get('days_to_earnings', 'n/a')}
Earnings Timing: {features.get('earnings_timing', 'n/a')}  (pre/post market)
Days to Next FOMC: {features.get('days_to_fomc', 'n/a')}
Days to Next OPEX: {features.get('days_to_opex', 'n/a')}
Combined Event Risk Score: {features.get('event_risk_score', 'n/a')}/10
Active Events: {features.get('active_events_description', 'None')}"""
```

### Section 10: EARNINGS SIGNALS (promoted)

```python
# SECTION 10: Earnings Signals (promoted from 7.7)
prompt += f"""

=== EARNINGS SIGNALS ===
Last EPS Surprise: {features.get('last_eps_surprise_pct', 'n/a')}%
Last Revenue Surprise: {features.get('last_revenue_surprise_pct', 'n/a')}%
Surprise Streak: {features.get('surprise_streak', 'n/a')} quarters
Analyst Revision Momentum: {features.get('revision_momentum', 'n/a')}
EPS Estimate Trend (90d): {features.get('eps_estimate_trend', 'n/a')}"""
```

Note: Some of these fields depend on the earnings_signals fix from the log audit sprint
(#248 — missing eps_actual/revenue_actual columns). If fields are None, show 'n/a'.

### Section 11: CROSS-ASSET CORRELATION (NEW)

```python
# SECTION 11: Cross-Asset Correlation (new)
prompt += f"""

=== CROSS-ASSET CONTEXT ===
US 10Y Yield: {features.get('us_10y_yield', 'n/a')}% ({features.get('us_10y_change_1m', 'n/a')} 1m)
US Dollar Index: {features.get('dxy_level', 'n/a')} ({features.get('dxy_change_1m', 'n/a')} 1m)
VIX Term Structure: {features.get('vix_term_structure', 'n/a')}
HY Credit Spread: {features.get('hy_oas', 'n/a')} bps ({features.get('hy_oas_z_score', 'n/a')} Z)
Gold: {features.get('gold_change_1m', 'n/a')} (1m) — risk appetite proxy"""
```

**Data sources for Section 11:**
- US 10Y: already in FRED macro_snapshots
- DXY: add to macro_collector (UUP ETF as proxy, or FRED DX-Y.N)
- VIX term structure: already in vix_term_structure table
- HY credit spread: already in macro_snapshots (via FRED BAMLH0A0HYM2)
- Gold: add to macro_collector (GLD ETF via yfinance)

If any data source is unavailable, omit that line entirely (don't show 'n/a' for entire
section — just skip missing lines). The section should degrade gracefully.

---

## Task 2: Update Feature Engine for New Data

In `src/features/engine.py`, ensure `compute_all_features()` or `enrich_features()` includes:

```python
# Cross-asset data (Section 11)
features["us_10y_yield"] = macro.get("treasury_10y")
features["us_10y_change_1m"] = macro.get("treasury_10y_change_1m")
features["dxy_level"] = macro.get("dxy")  # Need to add to macro_collector
features["dxy_change_1m"] = macro.get("dxy_change_1m")
features["vix_term_structure"] = _classify_vix_term_structure(macro)
features["hy_oas"] = macro.get("hy_oas")
features["hy_oas_z_score"] = macro.get("hy_oas_z_score")
features["gold_change_1m"] = macro.get("gold_change_1m")  # Need to add to macro_collector

# Sector relative (Section 3 enhancement)
features["sector_etf"] = sectors.get_sector_etf(ticker)
features["sector_rotation_signal"] = _compute_sector_rotation(sector_data)
```

For DXY and Gold: add simple yfinance fetches to `src/data_collection/macro_collector.py`:
```python
# Add to collect_macro_snapshots():
try:
    gold = yf.download("GLD", period="2mo", progress=False, auto_adjust=True)
    if gold is not None and len(gold) > 20:
        snapshot["gold_change_1m"] = round((gold["Close"].iloc[-1] / gold["Close"].iloc[-21] - 1) * 100, 2)
except Exception:
    pass
```

---

## Task 3: Random Source Subsetting for Robustness

**WHY:** If the model always sees all 11 sections, it may learn to over-rely on a specific
section. Random subsetting during TRAINING forces the model to make decisions with incomplete
information — matching real-world conditions where some data sources may be unavailable.

**Implementation in `src/training/data_collector.py`:**

```python
import random

OPTIONAL_SECTIONS = [3, 4, 5, 6, 8, 10, 11]  # Sections that can be randomly omitted
REQUIRED_SECTIONS = [1, 2, 7, 9]  # Always included: Technical, Regime, Macro, Events

def _apply_source_subsetting(full_prompt: str, subsetting_rate: float = 0.3) -> str:
    """Randomly omit 1-3 optional sections from the training prompt.
    
    WHY: Forces model to reason from incomplete data, matching real-world conditions.
    Rate: 30% of training examples get subsetting (70% see all sections).
    Never omit Sections 1, 2, 7, 9 (core technical + regime + macro + events).
    """
    if random.random() > subsetting_rate:
        return full_prompt  # 70% of examples: use full prompt
    
    n_to_omit = random.randint(1, 3)
    sections_to_omit = random.sample(OPTIONAL_SECTIONS, min(n_to_omit, len(OPTIONAL_SECTIONS)))
    
    for section_num in sections_to_omit:
        section_header = _section_headers[section_num]  # e.g., "=== OPTIONS FLOW ==="
        # Remove from section header to next section header
        full_prompt = _remove_section(full_prompt, section_header)
    
    return full_prompt
```

**Apply during training data generation only** — never during live inference.
The live pipeline always sees all available sections.

**Add metadata tag for subsetting:**
In the training example metadata, record which sections were omitted:
```python
metadata["sections_omitted"] = sections_to_omit  # e.g., [5, 8, 11]
metadata["subsetting_applied"] = True
```

---

## Task 4: Update Training Templates

In `src/training/outcome_prompts.py`, update the outcome-conditioned templates to reference
the new section names where relevant:

- WIN templates: reference specific sections that supported the trade
- LOSS templates: reference which sections had warning signs
- TIMEOUT templates: reference event calendar proximity
- PASS templates: reference why the risk/reward wasn't favorable

No structural changes needed — just update section name references in template text.

---

## Task 5: Update System Prompt

In `src/llm/prompts.py`, update `PACKET_SYSTEM_PROMPT` to reflect the 11-section structure:

```python
PACKET_SYSTEM_PROMPT = """You are a senior equity research analyst at Arcis Research.
You receive structured data about a potential trade setup in 11 sections:
Technical Data, Market Regime, Sector Relative, Fundamental Snapshot,
Insider Activity, Recent News, Macro Context, Options Flow, Event Calendar,
Earnings Signals, and Cross-Asset Context.

Not all sections may be present — some data sources are periodically unavailable.
Base your analysis on whatever sections are provided.

Respond in structured XML format:
<why_now>1-2 sentences on why this setup is actionable RIGHT NOW</why_now>
<analysis>3-5 sentences of deeper analysis covering risk/reward</analysis>
<metadata>Conviction: [1-10]
Direction: [long/short/pass]
Time Horizon: [days]
Key Risk: [one sentence]</metadata>
"""
```

The key addition: "Not all sections may be present" — this prepares the model for
source subsetting during inference too (if a data source is down).

---

## Task 6: Context Window Budget

**CRITICAL:** Qwen3 8B has 8,192 token context. Current prompt uses ~800 tokens for system
prompt + ~3,000-4,000 for the 7-section feature prompt + ~400 for response = ~4,200-5,200.

Adding 4 sections adds ~400-600 tokens. New total: ~4,600-5,800. Still within budget.

However, verify after implementation:
```python
python -c "
from src.llm.packet_writer import _build_feature_prompt
# Use a feature dict with all sections populated
prompt = _build_feature_prompt(test_features, 'AAPL')
tokens = len(prompt.split()) * 1.3  # rough token estimate
print(f'Prompt words: {len(prompt.split())}')
print(f'Est tokens: {tokens:.0f}')
print(f'Budget remaining: {7000 - tokens:.0f} tokens')
assert tokens < 7000, f'OVER BUDGET: {tokens} tokens'
"
```

If over budget, prioritize: keep Sections 1-2-7-9 (required), then trim enrichment
sections to shorter formats.

---

## Tests

Update `tests/test_xml_format.py`:
- `test_11_sections_present()` — verify all 11 section headers in prompt
- `test_source_subsetting_rate()` — run 100 iterations, verify ~30% get subsetting
- `test_required_sections_never_omitted()` — verify Sections 1,2,7,9 always present
- `test_graceful_degradation()` — verify prompt builds even with missing feature data
- `test_context_window_budget()` — verify total tokens < 7000
- `test_skew_interpretation()` — verify helper function
- `test_cross_asset_section_partial_data()` — verify missing DXY/Gold doesn't break prompt
- `test_subsetting_metadata_recorded()` — verify training examples record omitted sections

---

## Verification

```bash
python -m pytest tests/ -x -q                    # All tests pass
python -m pytest tests/test_xml_format.py -v      # All new tests pass
cd frontend && npm run build && cd ..             # Succeeds

# Manual: generate a prompt and inspect
python -c "
from src.features.engine import compute_all_features
from src.llm.packet_writer import _build_feature_prompt
# Build prompt for a real ticker
prompt = _build_feature_prompt({'trend_state': 'uptrend', 'current_price': 150}, 'AAPL')
print(prompt[:2000])
print(f'\\n...\\nTotal length: {len(prompt)} chars, ~{len(prompt.split())} words')
"
```

---

## Commit

```bash
git add src/llm/ src/training/ src/features/engine.py src/data_collection/macro_collector.py tests/
git commit -m "feat: expand training XML 7→11 sections + random source subsetting

11 clean sections: Technical, Regime, Sector Relative, Fundamentals,
Insider, News, Macro, Options Flow, Event Calendar, Earnings Signals,
Cross-Asset Correlation.

New data: DXY proxy (UUP), Gold (GLD), sector rotation signal,
skew interpretation, event countdown, revision momentum.

Random source subsetting (30% rate): omits 1-3 optional sections
during training to force model robustness with incomplete data.
Required sections (Technical, Regime, Macro, Events) never omitted.

Context window verified: ~5,500 tokens (budget: 7,000)."
```

Do NOT merge to main. Push to `feat/xml-expansion` only.
