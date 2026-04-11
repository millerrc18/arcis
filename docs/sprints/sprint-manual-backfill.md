# Historical Backfill: Manual Generation Workflow

**Version:** 4.0 (redesigned for manual generation via Claude Max / ChatGPT Plus)
**Author:** Claude (Opus 4.6)
**Date:** April 11, 2026
**Status:** DESIGN SPEC — awaiting Ryan review before implementation plan

---

## 1. What Changed and Why

The original spec automated commentary generation via Claude API (~$26). Ryan proposed using his existing Claude Max and ChatGPT Plus subscriptions instead — zero marginal cost, higher quality models (Opus 4.6 vs Sonnet 4.6), and real-time human curation.

This is actually a better approach for three reasons:

**Higher quality ceiling.** Claude Opus 4.6 and GPT-4.5 are both stronger analytical writers than Sonnet 4.6. Manual curation means every example passes a human quality gate before it ever reaches the automated rubric — two quality layers instead of one.

**Multi-model diversity.** Using Claude AND ChatGPT produces natural variation in writing style, analytical framing, and vocabulary. This is exactly what the training data research recommends — diverse user message phrasings and output variation prevent the model from overfitting to a single "voice." The fine-tuned Qwen3 model learns the analytical *structure* (XML format, thesis-first, evidence-grounded) while absorbing diverse *expression*.

**Zero marginal cost.** Claude Max includes Opus 4.6 usage. ChatGPT Plus includes GPT-4.5 and o4-mini. No API billing, no Batch API complexity, no rate limiting.

The tradeoff: generation is slower (human in the loop) and spread across multiple sessions instead of one overnight batch. Target pace: ~20–30 examples per hour, ~500 total over 2–3 weeks of evening sessions.

---

## 2. Architecture: Automate Everything Except the Writing

```
┌─────────────────────────────────────────────────────┐
│  AUTOMATED (CC sprint, run once)                    │
│                                                     │
│  1. Scan 2021-2025 for qualifying setups            │
│  2. Compute features + FRED macro for each          │
│  3. Classify regimes, compute outcomes              │
│  4. Export individual prompt files by regime         │
│     └─ prompts/bull/001_AAPL_2021-03-15.md          │
│     └─ prompts/bear/042_MSFT_2022-06-10.md          │
│     └─ prompts/pass/085_XOM_2023-08-22.md           │
│                                                     │
│  5. Generate outcomes file (SEALED — do not read)   │
│     └─ outcomes/outcomes.json                       │
└─────────────────┬───────────────────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────────────────────┐
│  MANUAL (Ryan, evenings/weekends)                   │
│                                                     │
│  1. Open a prompt file                              │
│  2. Copy contents into Claude / ChatGPT             │
│  3. Get XML response                                │
│  4. Save response to results/ folder                │
│     └─ results/001_AAPL_2021-03-15.md               │
│  5. Repeat. Check progress anytime.                 │
└─────────────────┬───────────────────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────────────────────┐
│  AUTOMATED (run anytime, incremental)               │
│                                                     │
│  1. Import results — pair with outcomes              │
│  2. Validate XML format (Gate 1)                    │
│  3. Score against 6-dim rubric (Gate 2)             │
│  4. Run leakage detector (Gate 3)                   │
│  5. Insert into training_examples table             │
│  6. Print regime balance + progress report          │
└─────────────────────────────────────────────────────┘
```

---

## 3. Self-Blinding Design

This is the most critical architectural constraint. The model must never learn to associate features with outcomes — the commentary must reflect genuine uncertainty.

**How blinding is enforced:**

1. **Export script** strips all outcome data from feature snapshots. The `OUTCOME_FIELDS` deny-list (`pnl_dollars`, `pnl_pct`, `exit_reason`, `max_favorable_excursion`, `max_adverse_excursion`, `actual_exit_price`, `actual_exit_time`, `duration_days`, `status`, `outcome_type`) is enforced at the code level.

2. **Outcomes file** (`outcomes/outcomes.json`) is generated separately and contains ONLY the outcome data keyed by prompt ID. This file has a prominent header: `DO NOT READ — outcomes are paired automatically during import.`

3. **Ryan never sees outcomes before generating.** The prompt files contain zero outcome information. The outcomes file exists only for the import script to label examples after generation.

4. **Import script** pairs commentary with outcomes programmatically. Ryan never manually associates a commentary with its outcome.

**What if Ryan accidentally recognizes a historical setup?** This is acceptable. Knowing "AAPL pulled back in March 2022" doesn't tell you the 5-day outcome of a specific bracket trade. The blinding prevents systematic outcome leakage, not incidental market knowledge. The leakage detector (Gate 3) catches any systematic correlation.

---

## 4. Prompt File Format

Each exported prompt file is self-contained — copy everything between the markers and paste into Claude or ChatGPT:

```markdown
# Setup 042 | MSFT | 2022-06-10 | Regime: BEAR | Score: 78

## System Prompt (paste this first, or set as system/custom instructions)

You are a senior equity analyst. Today is 2022-06-10. You are reviewing
a pullback-in-strong-trend setup for potential entry.
[... full BLINDED_ANALYSIS_PROMPT ...]

## Feature Data (paste this as your message)

=== TECHNICAL DATA ===
Ticker: MSFT (Microsoft Corporation)
Current Price: $259.34
Trend State: downtrend | SMA50 slope: -0.42 | SMA200 slope: -0.18
[... full feature snapshot ...]

=== MACRO CONTEXT ===
- VIX: 28.7 (elevated)
- Yield Curve (10Y-2Y): -0.08% (inverted)
- Fed Funds Rate: 1.58%
- Unemployment: 3.6%

=== TRADE PARAMETERS ===
Score: 78/100
Entry: $259.34 | Stop: $252.18 | Target 1: $268.72 | Target 2: $273.50
Event Risk: none

---
SAVE THE RESPONSE AS: results/042_MSFT_2022-06-10.md
```

For **PASS examples** (score 45–69), the system prompt changes to `PASS_ANALYSIS_PROMPT` and the header indicates `Type: PASS`:

```markdown
# Setup 085 | XOM | 2023-08-22 | Regime: HIGH_VOL | Score: 57 | Type: PASS

## System Prompt
You are a senior equity analyst. Today is 2023-08-22. You are reviewing
a potential pullback setup that scored below the qualification threshold...
[... PASS_ANALYSIS_PROMPT ...]
```

---

## 5. Regime Targets and Progress Tracking

### 5.1 Target Distribution

| Regime | Target | Prompts Exported | Notes |
|--------|--------|-----------------|-------|
| Bull Trend | 120 | ~180 (1.5× buffer) | Most common — easy to fill |
| Bear Trend | 80 | ~120 | 2022 H1 is the primary source |
| High Volatility | 80 | ~120 | VIX >25 episodes across 2021–2025 |
| Range Bound | 70 | ~100 | Sideways periods, choppy markets |
| Recovery/Transition | 60 | ~90 | Regime change periods |
| **PASS (no trade)** | **90** | **~130** | Score 45–69, across all regimes |
| **Total** | **500** | **~740** | 1.5× buffer for quality rejection |

The 1.5× buffer accounts for ~20% quality gate rejection + natural attrition (some prompts won't produce good results from any model).

### 5.2 Progress Tracking

The export script generates a `progress.json` in the project root:

```json
{
  "bull": {"target": 120, "exported": 180, "completed": 0, "imported": 0},
  "bear": {"target": 80, "exported": 120, "completed": 0, "imported": 0},
  ...
}
```

A progress check script shows regime balance at any time:

```bash
python scripts/backfill_progress.py
```
```
BACKFILL PROGRESS — 2026-04-12
═══════════════════════════════
Bull:       ████████░░░░ 47/120 (39%)
Bear:       ██░░░░░░░░░░ 12/80  (15%) ← FOCUS HERE
High Vol:   ███░░░░░░░░░ 18/80  (23%)
Range:      █████░░░░░░░ 28/70  (40%)
Recovery:   ██████░░░░░░ 31/60  (52%)
PASS:       ████░░░░░░░░ 22/90  (24%)

Total: 158/500 (32%)  |  Imported: 142  |  Rejected: 16 (10%)
```

This lets Ryan prioritize underrepresented regimes during his sessions.

### 5.3 Session Workflow

A typical evening session (~1 hour, 20–30 examples):

1. Run `python scripts/backfill_progress.py` — see which regimes need attention
2. Open the regime folder with the biggest gap (e.g., `prompts/bear/`)
3. Pick 20–25 prompt files
4. For each: copy into Claude or ChatGPT, get response, save to `results/`
5. Run `python scripts/import_backfill_results.py` — imports what's new, shows updated progress

**Model rotation suggestion:** Alternate between Claude Opus and ChatGPT across sessions (or even within a session) for maximum output diversity. The import script tags each example with the model used.

---

## 6. Multi-Model Diversity

Using multiple models is an explicit design advantage:

| Model | Strengths | Suggested Use |
|-------|-----------|---------------|
| Claude Opus 4.6 | Nuanced risk analysis, calibrated uncertainty language | Complex bear/high-vol setups |
| Claude Sonnet 4.6 | Fast, clean structure, good evidence grounding | Bull setups, high-volume sessions |
| GPT-4.5 | Different analytical framing, strong quantitative synthesis | Recovery/transition setups |
| o4-mini | Concise, efficient reasoning | PASS examples (brevity is appropriate) |

The import script records which model generated each example in the `source` field:
- `manual_claude_opus`
- `manual_claude_sonnet`
- `manual_chatgpt`
- `manual_other`

Ryan specifies the model when saving (or the import script asks).

---

## 7. Outcome Types from Historical Scanning

`compute_outcome()` simulates bracket execution and classifies:

| Outcome | Exit Reason | Description |
|---------|------------|-------------|
| `clean_win` | `target_1_hit` / `target_2_hit` | Target hit, MFE > 2× MAE |
| `clean_loss` | `stop_hit` | Stop hit, MAE > 2× MFE |
| `messy` | target or stop hit | Significant excursion both ways |
| `timeout` | `timeout` | Neither triggered in 15 days |
| `pass` | N/A | Score 45–69, no trade taken |

Target outcome distribution in final admitted examples:

| Category | Target % | Count |
|---------|---------|-------|
| `clean_win` | 25% | 125 |
| `clean_loss` | 15% | 75 |
| `messy` | 15% | 75 |
| `timeout` | 9% | 45 |
| `pass` | 18% | 90 |
| Regime-cautious (cross-cutting) | 18% | 90 |

---

## 8. Quality Pipeline

### 8.1 Gate 1: Human Curation (during generation)

Ryan eyeballs each response before saving. Obvious garbage (template leakage, incoherent text, wrong XML format) gets regenerated on the spot. This is the first quality gate and it's free.

### 8.2 Gate 2: Automated Format Validation (at import)

The import script runs `validate_training_example()` on every response:
- XML tags present (`<why_now>`, `<analysis>`, `<metadata>`)
- Conviction score parseable and in range (1–10 for TRADE, 1–4 for PASS)
- Minimum length thresholds
- No template/prompt leakage

### 8.3 Gate 3: LLM-as-Judge Rubric Scoring (batch, periodic)

After importing a batch, run the rubric scorer:
```bash
python -m src.main score-training --source manual_claude_opus
```

This uses the existing `quality_filter.py` with the 6-dimension rubric. Examples scoring below 3.5/5.0 are flagged for review. Any dimension below 2.0 triggers rejection.

**Cost:** This DOES use the API (~$0.01–0.02 per example via Haiku 4.5). For 500 examples: ~$5–10. This is the only API cost in the entire pipeline.

### 8.4 Gate 4: Leakage Detection (after full batch)

Run after all examples are imported:
```bash
python -m src.main check-leakage
```

TF-IDF accuracy > 55% = something is wrong. Investigate before training.

---

## 9. Data Enrichment

Same as previous spec — the export script enriches each feature snapshot with real FRED macro data:

| Section | Source | Historical Availability |
|---------|--------|----------------------|
| Technical indicators | yfinance OHLCV | Full (2021–2025) |
| Market regime | SPY computation | Full |
| Sector context | yfinance sector + RS | Full |
| FRED macro | FRED API (4 series) | Full |
| Fundamentals | Contextual sentence | Partial (company + sector) |
| News | Finnhub (1-year lookback) | Partial |
| Insider | Finnhub (1-year lookback) | Partial |

The key improvement: every prompt file includes real VIX, yield curve, fed funds rate, and unemployment data — not placeholders.

---

## 10. Cost Analysis

| Component | Cost |
|-----------|------|
| Scanning + feature computation | $0 (local CPU) |
| FRED API calls (4 series × 1 call each) | $0 (free tier) |
| Commentary generation (Claude Max / ChatGPT Plus) | $0 (subscription) |
| Rubric scoring (~500 × $0.01 via Haiku) | ~$5 |
| **Total** | **~$5** |

Compare to automated pipeline: $13–26. Manual generation saves $8–21 and produces higher-quality results.

---

## 11. Timeline

| Week | Activity | Examples |
|------|----------|---------|
| Week 0 | CC sprint: build export/import pipeline | 0 |
| Week 1 | Ryan generates 25–30/evening, 3–4 sessions | ~100 |
| Week 2 | Continue generation, focus on underrepresented regimes | ~150 |
| Week 3 | Continue generation, begin PASS examples | ~150 |
| Week 4 | Finish remaining, run rubric scoring + leakage check | ~100 |
| Week 4 weekend | Retrain halcyon-v2.0.0 on expanded dataset | — |

Total: ~500 examples over ~4 weeks of casual evening sessions. Not a grind — 3–4 hours per week.

---

## 12. Claude Project Optimization

Ryan has Claude Max with Projects. The most efficient workflow:

1. **Create a Claude Project** called "Arcis Training Data"
2. **Set the Project system prompt** to `BLINDED_ANALYSIS_PROMPT`
3. **Each conversation:** paste just the feature data (not the system prompt)
4. **For PASS examples:** switch Project prompt to `PASS_ANALYSIS_PROMPT`, or use a second Project

This eliminates re-pasting the system prompt every time — just paste the feature data, get the response. ~90 seconds per example at steady state.

For ChatGPT: use Custom Instructions or a GPT with the system prompt baked in.

---

## 13. Success Criteria

1. ≥400 new examples pass all quality gates and are stored in the database
2. No single regime exceeds 35% of new examples; bear + high-vol ≥ 25%
3. ≥60 PASS examples admitted
4. TF-IDF leakage accuracy < 55%
5. Average rubric score ≥ 3.5/5.0; no dimension below 3.0
6. ≥70 S&P 100 tickers represented in combined dataset
7. Total dataset between 1,400–1,600 examples
8. Multi-model: at least 2 different models used across the dataset
9. "Good process / bad outcome" ≥ 15% of new examples
10. Retrained model matches or beats v1.0.0 on held-out eval

---

## 14. Known Issues to Fix

**Source tag resumability bug** (from previous spec): `_example_exists()` checks wrong source tag. Must fix before any import runs. Not strictly required for the manual pipeline (which uses a different import script), but should be fixed for consistency.

**Existing export/import scripts** (`scripts/export_chatgpt_inputs.py`, `scripts/import_chatgpt_outputs.py`): These work from live `shadow_trades` + `recommendations` tables, not from historical scanning. New scripts are needed — the old ones remain for the live pipeline.

---

## 15. Risks

| Risk | Mitigation |
|------|-----------|
| Ryan gets bored at example 200 | Progress tracker shows regime balance. Focus on underrepresented regimes to stay motivated — each one fills a real gap. |
| Quality drops during long sessions | Gate 2 rubric catches degradation. Cap sessions at ~30 examples. |
| Model produces non-XML output | Regenerate in the same conversation — "please format your response in the XML structure." |
| Ryan accidentally reads outcomes | Outcomes are in a separate sealed file. Even if accidentally seen for 1–2 examples, the leakage detector catches systematic bias. |
| Uneven regime coverage | Progress tracker makes gaps visible. Ryan prioritizes gaps each session. |
| ChatGPT produces different XML format | Import script validates XML tags. Minor format differences (extra whitespace, different tag casing) are normalized. |

---

# IMPLEMENTATION PLAN

> **Branch:** `feat/manual-backfill`
> **Priority:** HIGH — blocks v2.0.0 model training
> **Estimated CC time:** 4–6 hours
> **Pre-flight:**
> ```bash
> git checkout main && git pull origin main
> git checkout -b feat/manual-backfill
> python -m pytest tests/ -x -q --ignore=tests/test_ingestion.py
> ```

---

## Task 1: Add FRED historical series fetcher

**File:** `src/training/historical_data.py` (156 lines → ~235)

Add `fetch_fred_history()` — fetches full 2021–2025 time series for VIXCLS, T10Y2Y, UNRATE, FEDFUNDS. Caches to `training_data/fred_history.pkl`. Add `get_fred_value_as_of()` for point-in-time lookups.

Import `_get_fred_api_key` from `src/data_collection/macro_collector.py`.

**Test:** `tests/test_fred_history.py`
- `test_fred_lookup_returns_point_in_time` — Feb 15 lookup returns Feb value, not March
- `test_fred_missing_returns_none` — lookup for a date before series start returns None

**Commit:** `feat(historical_data): FRED historical series fetch + point-in-time lookup`

---

## Task 2: Add PASS analysis prompt

**File:** `src/llm/prompts.py` (283 lines → ~320)

Add `PASS_ANALYSIS_PROMPT` constant after `QUALITY_ENHANCEMENT_PROMPT`. Same XML format (`<why_now>`, `<analysis>`, `<metadata>`) but with NEUTRAL direction and conviction 1–4. Full text is in §6 of the design spec above.

**No test needed** — string constant, validated at integration.

**Commit:** `feat(prompts): add PASS_ANALYSIS_PROMPT for below-threshold setups`

---

## Task 3: Add regime-targeted date sampler

**File:** Create `src/training/regime_sampler.py` (~150 lines)

Functions:
- `classify_dates_by_regime(spy_df)` — uses existing `compute_market_regime()`, returns `dict[str, list[str]]`
- `sample_regime_balanced_dates(regime_dates, targets)` — stratified sampling to hit target counts
- `format_macro_summary(fred_data, scan_date)` — formats FRED values into natural language macro context

Map the 5 `regime_label` values from `features.regime` to target categories with priority ordering: High Vol > Bear > Recovery > Range > Bull.

Also move `_balance_dataset()`, `_deduplicate_candidates()`, `_cap_and_diversify()` from `backfill.py` into this file. This reduces `backfill.py` from 445 → ~365 lines (under the 400 guardrail) while the new file stays at ~200 lines.

**Test:** `tests/test_regime_sampler.py`
- `test_classify_returns_multiple_regimes`
- `test_sample_respects_targets`
- `test_format_macro_summary_no_placeholder`

**Commit:** `feat(regime_sampler): regime-targeted date selection + refactor helpers from backfill.py`

---

## Task 4: Enrich historical scanner with FRED macro

**File:** `src/training/historical_scanner.py` (349 lines → ~395)

Add `fred_data: dict | None = None` parameter to `scan_historical_date()`.

When `fred_data` is provided:
- Call `format_macro_summary(fred_data, scan_date)` from `regime_sampler.py`
- Set `features["macro_summary"]` to real macro data instead of placeholder
- Set `features["fundamental_summary"]` to contextual sentence instead of placeholder

Add `scan_historical_date_pass()` function for PASS examples — same scanning logic but with score range 45–69 and no outcome computation.

Update `generate_backfill_example()` to handle `outcome=None` for PASS examples, using `PASS_ANALYSIS_PROMPT` instead of `BLINDED_ANALYSIS_PROMPT`.

**Test:** Update `tests/test_backfill.py`
- `test_macro_summary_uses_fred_data`
- `test_pass_example_has_neutral_direction`

**Commit:** `feat(historical_scanner): FRED macro enrichment + PASS example generation`

---

## Task 5: Build export script

**File:** Create `scripts/export_backfill_prompts.py` (~200 lines)

This is the core deliverable. The script:

1. Downloads historical data via `fetch_historical_universe(lookback_years=5)`
2. Fetches FRED history via `fetch_fred_history()`
3. Classifies all dates by regime via `classify_dates_by_regime()`
4. Samples dates to hit regime targets via `sample_regime_balanced_dates()`
5. Scans each date for qualifying setups (score ≥70 for TRADE, 45–69 for PASS)
6. Exports individual prompt files to `training_data/prompts/{regime}/`
7. Exports sealed outcomes to `training_data/outcomes/outcomes.json`
8. Generates `training_data/progress.json`

Each prompt file contains:
- Header with ID, ticker, date, regime, score, type (TRADE/PASS)
- System prompt (BLINDED or PASS variant)
- Feature data (enriched with FRED macro)
- Save instruction with target filename

**CLI:**
```bash
python scripts/export_backfill_prompts.py \
  --lookback-years 5 \
  --max-per-regime 180 \
  --pass-count 130 \
  --output-dir training_data/prompts
```

**Commit:** `feat(scripts): export_backfill_prompts — regime-targeted prompt files for manual generation`

---

## Task 6: Build import script

**File:** Create `scripts/import_backfill_results.py` (~180 lines)

Reads completed results from `training_data/results/`, pairs with outcomes from `training_data/outcomes/outcomes.json`, validates, and inserts into `training_examples`.

```bash
python scripts/import_backfill_results.py \
  --results-dir training_data/results \
  --outcomes training_data/outcomes/outcomes.json \
  --model claude_opus
```

The script:
1. Scans `results/` for new `.md` files not yet imported (tracks via `training_data/imported.json`)
2. Extracts XML content from each file
3. Validates XML format (Gate 1)
4. Looks up outcome from `outcomes.json` using the prompt ID from the filename
5. Inserts into `training_examples` with:
   - `source`: `manual_{model}` (e.g., `manual_claude_opus`)
   - `trade_outcome`: JSON from outcomes file
   - `regime`: from prompt metadata
   - `outcome_type`: from outcomes file
6. Updates `progress.json` with new counts
7. Prints import summary + updated regime progress

**Handles edge cases:**
- Missing XML tags → skip with warning
- Duplicate import → skip silently (idempotent)
- PASS examples → no outcome pairing needed, `outcome_type = 'pass'`

**Commit:** `feat(scripts): import_backfill_results — validate, pair outcomes, insert training examples`

---

## Task 7: Build progress tracker

**File:** Create `scripts/backfill_progress.py` (~60 lines)

Reads `training_data/progress.json` and prints a visual progress bar for each regime. Also queries the database for imported/scored counts.

```bash
python scripts/backfill_progress.py
```

Shows: exported count, results saved, imported, rubric-scored, rejected — per regime.

**Commit:** `feat(scripts): backfill_progress — visual regime balance tracker`

---

## Task 8: Update backfill.py imports after refactor

**File:** `src/training/backfill.py` (445 → ~365 lines)

After Task 3 moved `_balance_dataset`, `_deduplicate_candidates`, and `_cap_and_diversify` to `regime_sampler.py`, update imports in `backfill.py`:

```python
from src.training.regime_sampler import (
    balance_dataset,
    deduplicate_candidates,
    cap_and_diversify,
)
```

Verify all existing tests still pass — the automated backfill pipeline must not break.

**Commit:** `refactor(backfill): import helpers from regime_sampler — backfill.py now ≤400 lines`

---

## Task 9: Tests

**New test files:**
- `tests/test_fred_history.py` (~50 lines)
- `tests/test_regime_sampler.py` (~80 lines)

**Updated:**
- `tests/test_backfill.py` — verify imports still work after refactor

**Run:**
```bash
python -m pytest tests/test_fred_history.py tests/test_regime_sampler.py tests/test_backfill.py -v
```

**Commit:** `test: FRED history, regime sampler, backfill refactor verification`

---

## Task 10: Documentation

**Files:**
- `docs/sprints/sprint-manual-backfill.md` — this file
- `CHANGELOG.md` — add entry
- `MASTER.md` — add to sprint queue, note manual backfill pipeline

Also create `training_data/README.md`:
```markdown
# Training Data — Manual Backfill

## Workflow
1. Run: `python scripts/export_backfill_prompts.py`
2. Generate: copy prompts into Claude/ChatGPT, save responses to `results/`
3. Import: `python scripts/import_backfill_results.py --model claude_opus`
4. Check: `python scripts/backfill_progress.py`

## Folder Structure
- `prompts/` — exported feature snapshots organized by regime (DO NOT EDIT)
- `results/` — your saved responses (one file per prompt)
- `outcomes/` — sealed outcome data (DO NOT READ before generating)
- `progress.json` — auto-updated regime balance tracker

## Self-Blinding
The prompts contain ZERO outcome data. Outcomes are paired automatically
during import. Do not read outcomes.json before generating all responses.
```

**Commit:** `docs: manual backfill workflow + training_data README`

---

## File Size Guardrails

| File | Before | After | Action |
|------|--------|-------|--------|
| `backfill.py` | 445 | ~365 | Helpers moved to `regime_sampler.py` ✅ |
| `historical_scanner.py` | 349 | ~395 | FRED + PASS additions |
| `historical_data.py` | 156 | ~235 | FRED fetch + lookup |
| `prompts.py` | 283 | ~320 | PASS prompt |
| `regime_sampler.py` | 0 (new) | ~200 | Sampling + moved helpers |
| `export_backfill_prompts.py` | 0 (new) | ~200 | Export script |
| `import_backfill_results.py` | 0 (new) | ~180 | Import script |
| `backfill_progress.py` | 0 (new) | ~60 | Progress tracker |

No file exceeds 400 lines.

---

## Verification Checklist

```bash
# All existing tests pass
python -m pytest tests/ -x -q --ignore=tests/test_ingestion.py

# New tests pass
python -m pytest tests/test_fred_history.py tests/test_regime_sampler.py -v

# backfill.py is SMALLER
wc -l src/training/backfill.py  # should be ≤400

# Export runs without error (produces prompt files)
python scripts/export_backfill_prompts.py --max-per-regime 5 --pass-count 5 --output-dir /tmp/test_prompts

# Import handles empty results dir gracefully
python scripts/import_backfill_results.py --results-dir /tmp/empty --outcomes /tmp/test_prompts/../outcomes/outcomes.json --model test

# Frontend builds
cd frontend && npm run build && cd ..
```

**Push:**
```bash
git push origin feat/manual-backfill
```
