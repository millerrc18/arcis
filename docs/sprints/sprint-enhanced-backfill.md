# Historical Backfill Enhancement: Building a Better Training Foundation

**Version:** 3.0 (final — spec + implementation plan)
**Author:** Claude (Opus 4.6)
**Date:** April 11, 2026
**Status:** APPROVED — ready for CC execution
**Purpose:** Expand the training dataset from 1,019 → ~1,500 examples via regime-diverse historical backfill, closing critical coverage gaps without waiting months for live outcome data.

---

## 1. Problem Statement

The model (halcyon-v1.0.0) was trained on 1,019 SFT examples. After the April 10 data quarantine, only 18 verified closed trades exist — far too few to generate meaningful outcome-labeled training data from live trading alone. The model needs a stronger foundation now.

The existing `backfill.py` pipeline (445 lines, 10-step process with two-stage self-blinding) already handles the core mechanics. Three specific gaps limit its effectiveness:

**Gap 1: Regime blindness.** The pipeline generates examples proportional to when setups naturally occur — bull markets produce the most pullback signals, so the dataset is dominated by easy-mode examples. The model has near-zero exposure to bear markets (2022), high-volatility episodes (Aug–Oct 2023, Apr 2025), or regime transitions.

**Gap 2: Shallow data enrichment.** Historical scans insert placeholder text for fundamentals, insider activity, and macro context ("Not available for historical scan"). In production, the model receives 7–9 rich data sections. This train/serve mismatch means the model hasn't learned to integrate macro data.

**Gap 3: No "when to say no" examples.** Every training example is a setup deemed worth trading. The model has never seen an example where the correct answer is "don't trade this." Conviction calibration is impossible without PASS examples.

### What This Spec Is NOT

This is Phase 1 of the v2 training data expansion (2,800 SFT + 400 DPO target). This spec targets ~500 new examples. The remaining ~1,300 come from live outcome data (flywheel), DPO pairs (100+ trades), and GRPO (RTX 3090).

---

## 2. Design Goals

1. Generate **400–500 new high-quality training examples** from 2021–2025 historical data
2. Achieve explicit **regime coverage** across 5 major market environments
3. Enrich historical examples with **real FRED macro data** (not placeholders)
4. Add **PASS/no-trade examples** (score 45–69) that teach the model when NOT to trade
5. Score every example against the **6-dimension rubric** before admission (minimum 3.5/5.0)
6. Maintain the **self-blinding architecture** — zero outcome leakage
7. Stay within **~$25–30 Claude API budget** using Sonnet 4.6 (~$13 with Batch API)
8. Keep the dataset within the **golden ratio safe zone** (synthetic ≤ 38% of total)

---

## 3. Regime-Targeted Scanning

### 3.1 Regime Classification

Use the existing `compute_market_regime()` from `src/features/regime.py` which already returns 5 labels: `calm_uptrend`, `volatile_uptrend`, `calm_downtrend`, `volatile_downtrend`, `transitional`. Map these to the target categories:

| Regime Label | Maps To | Target % | Count |
|-------------|---------|----------|-------|
| `calm_uptrend` | Bull Trend | 24% | 120 |
| `calm_downtrend` + `volatile_downtrend` | Bear Trend | 16% | 80 |
| `volatile_uptrend` + `volatile_downtrend` (VIX >25) | High Volatility | 16% | 80 |
| Days within ±4% of 200 EMA, 15+ day streak | Range Bound | 14% | 70 |
| `transitional` | Recovery/Transition | 12% | 60 |

**Priority for overlap:** High Volatility > Bear > Recovery > Range > Bull. A volatile_downtrend day counts as High Volatility, not Bear, to avoid double-counting.

### 3.2 PASS Category

**90 additional examples** (18%) from setups scoring 45–69. Split: ~45 at score 45–59 (clear deficiency), ~45 at score 60–69 (borderline). Sampled across all regimes.

**Total target: ~500 examples (410 regime-qualified + 90 PASS).**

### 3.3 Key Historical Periods

| Period | Regime | Significance |
|--------|--------|-------------|
| Jan–Nov 2021 | Bull | Ideal pullback conditions |
| Jan–Jun 2022 | Bear, high vol | Rate hiking, sustained downtrend |
| Jun–Oct 2022 | Bear, range | Choppy bottom, false rallies |
| Nov 2022–Mar 2023 | Recovery | Trend reversal |
| Aug–Oct 2023 | High vol correction | 10% drawdown, VIX spike |
| Apr 2025 | Extreme vol | VIX >50 tariff shock |

### 3.4 Lookback

Extend `lookback_years` from 2 → 5 (Jan 2021 – present). yfinance provides split-adjusted daily OHLCV at no cost. 20-day outcome buffer means latest scan date ≈ March 20, 2026.

---

## 4. Data Enrichment

### 4.1 FRED Macro Enrichment

Fetch full 2021–2025 time series for 4 FRED indicators (one API call per series, cached locally):

| Series | FRED ID | Frequency |
|--------|---------|-----------|
| VIX Close | VIXCLS | Daily |
| 10Y-2Y Spread | T10Y2Y | Daily |
| Unemployment | UNRATE | Monthly |
| Fed Funds Rate | FEDFUNDS | Monthly |

For each scan date, look up the most recent value available as of that date (point-in-time correct — no lookahead). Format as natural language for the `macro_summary` feature field:

```
MACRO CONTEXT as of {DATE}:
- VIX: {value} ({regime_label})
- Yield Curve (10Y-2Y): {value}bp ({inverted/normal/flat})
- Fed Funds Rate: {value}%
- Unemployment: {value}%
```

### 4.2 Handling Unavailable Sections

For fundamentals/insider where historical data is limited, use regime-contextual text instead of empty placeholders:

**Instead of:** "Not available for historical scan"
**Use:** "Fundamental data not available for this historical period. {ticker} is a {sector} company in the S&P 100."

This prevents the model from learning to ignore these sections.

---

## 5. Outcome Diversity

### 5.1 Outcome Types from Historical Scanning

`compute_outcome()` produces: `clean_win`, `clean_loss`, `messy`, `timeout`. "Stale" exits only occur in live trading.

### 5.2 Target Distribution

| Category | Target % | Count | Teaching Signal |
|---------|---------|-------|-----------------|
| `clean_win` | 25% | 125 | Clean execution |
| `clean_loss` | 15% | 75 | Thesis failures |
| `messy` | 15% | 75 | Ambiguous, calibration |
| `timeout` | 9% | 45 | Time-based exit discipline |
| **PASS** | 18% | 90 | When NOT to trade |
| **Regime-cautious** | 18% | 90 | Lower conviction in difficult environments |

### 5.3 Process-Outcome Matrix

After generation, audit: "good process / bad outcome" (rubric ≥ 3.5, P&L ≤ 0) should be ≥ 15% of the dataset. Reject any example with rubric < 3.5 regardless of outcome.

---

## 6. PASS Prompt Design

New prompt for setups scoring 45–69:

```
You are a senior equity analyst. Today is {date}. You are reviewing a 
potential pullback setup that has been flagged by the screening system 
but scored below the qualification threshold.

Your job: Analyze the setup and determine whether it meets the quality 
bar for entry. If it does not, explain SPECIFICALLY which factors are 
deficient and why the setup should be passed on.

A well-calibrated analyst passes on more setups than they take. Saying 
"no" with clear reasoning is as valuable as saying "yes."

[Same RULES and OUTPUT FORMAT as BLINDED_ANALYSIS_PROMPT, except:]

For PASS setups, use:
- Conviction: [1-4] — honest about the marginal quality
- Direction: NEUTRAL
- Time Horizon: N/A — setup does not qualify
- Key Risk: [the specific deficiency that disqualifies the trade]
```

Same XML format (`<why_now>`, `<analysis>`, `<metadata>`) so the model learns structured output for every decision type.

---

## 7. Quality Pipeline

Three gates, unchanged from existing infrastructure:

1. **Gate 1:** `validate_training_example()` — schema compliance, length, no prompt leakage
2. **Gate 2:** `quality_filter.py` — 6-dimension rubric, minimum 3.5/5.0, no dimension below 2.0
3. **Gate 3:** `leakage_detector.py` — TF-IDF accuracy < 55%

Expected yield: ~600 generated → ~475 admitted (~20% rejection).

---

## 8. Model and Cost

### 8.1 Model: Claude Sonnet 4.6

Config override:
```yaml
api:
  models:
    backfill_blinded: claude-sonnet-4-6
    backfill_enhancement: claude-sonnet-4-6
```

Sonnet 4.6: $3/$15 per MTok input/output. Training data quality justifies the premium over Haiku.

### 8.2 Cost

| Component | Per Example | × 600 | Total |
|-----------|-----------|-------|-------|
| Stage 1 (Sonnet, ~600 in + ~800 out) | $0.014 | 600 | $8.28 |
| Stage 2 (Sonnet, ~1400 in + ~800 out) | $0.016 | 600 | $9.72 |
| Gate 2 rubric (Sonnet, ~2000 in + ~500 out) | $0.014 | 600 | $8.10 |
| **Standard total** | | | **~$26** |
| **With Batch API (50% off)** | | | **~$13** |

Recommend Batch API for 50% savings — 24-hour turnaround is fine for a weekend run.

### 8.3 Compute: ~5–9 hours wall clock. Run on a weekend.

---

## 9. Success Criteria

1. ≥400 new examples pass all three quality gates
2. No single regime exceeds 35% of new examples; bear + high-vol ≥ 25%
3. ≥60 PASS examples admitted
4. TF-IDF leakage accuracy < 55%
5. Average rubric score ≥ 3.5/5.0; no dimension below 3.0
6. ≥70 S&P 100 tickers in combined dataset
7. Total dataset 1,400–1,600 examples
8. "Good process / bad outcome" ≥ 15% of new examples
9. API spend ≤ $30
10. Retrained model matches or beats v1.0.0 on held-out eval

---

## 10. Known Bug: Source Tag Resumability

`_example_exists()` (line 188) checks `source = 'historical_backfill'` but stored source is `blinded_win`/`blinded_loss` (line 378). Resumability is broken — crashes create duplicates. Must fix as Task 1.

---

# IMPLEMENTATION PLAN

> **Branch:** `feat/enhanced-backfill`
> **Priority:** HIGH — blocks v2.0.0 model training
> **Estimated CC time:** 6–8 hours (code changes) + overnight API run (unattended)
> **Estimated API cost:** ~$13–26 (Batch API recommended)
>
> **Pre-flight:**
> ```bash
> git checkout main && git pull origin main
> git checkout -b feat/enhanced-backfill
> python -m pytest tests/ -x -q --ignore=tests/test_ingestion.py
> # Verify backfill.py is at 445 lines (known — do NOT increase)
> wc -l src/training/backfill.py
> ```

---

## Task 1: Fix source tag resumability bug

**File:** `src/training/backfill.py` (line ~188)

The `_example_exists()` function checks for `source = 'historical_backfill'` but examples are stored with `source = 'blinded_win'` or `'blinded_loss'`. Fix the check to match what's actually stored:

```python
# BEFORE (line ~188):
row = conn.execute(
    """SELECT 1 FROM training_examples
       WHERE source = 'historical_backfill'
       AND ticker = ?
       AND feature_snapshot LIKE ?
       LIMIT 1""",
    (ticker, f"%{scan_date}%"),
).fetchone()

# AFTER:
row = conn.execute(
    """SELECT 1 FROM training_examples
       WHERE source IN ('blinded_win', 'blinded_loss', 'blinded_timeout',
                        'blinded_partial', 'regime_backfill', 'regime_pass')
       AND ticker = ?
       AND feature_snapshot LIKE ?
       LIMIT 1""",
    (ticker, f"%{scan_date}%"),
).fetchone()
```

**Test:**
```bash
python -c "
from src.training.backfill import _example_exists
# Should not crash
result = _example_exists('ai_research_desk.sqlite3', 'AAPL', '2025-01-15')
print(f'Exists: {result}')
print('✓ _example_exists works')
"
```

**Commit:** `fix(backfill): source tag check matches stored values — fixes resumability`

---

## Task 2: Add FRED historical series fetcher

**File:** `src/training/historical_data.py` (currently 156 lines — room to add ~80)

Add a function to fetch and cache full FRED time series for point-in-time lookups:

```python
FRED_SERIES_FOR_BACKFILL = {
    "VIXCLS": "VIX Close",
    "T10Y2Y": "10Y-2Y Treasury Spread",
    "UNRATE": "Unemployment Rate",
    "FEDFUNDS": "Fed Funds Rate",
}

def fetch_fred_history(
    start_date: str = "2020-01-01",
    end_date: str | None = None,
) -> dict[str, pd.DataFrame]:
    """Fetch full historical FRED series for backfill macro enrichment.

    Returns: {"VIXCLS": DataFrame(date, value), ...}
    Caches to training_data/fred_history.pkl (24h TTL).
    """
```

Implementation:
- Use the FRED API (`api.stlouisfed.org/fred/series/observations`) with `observation_start` and `observation_end`
- Get the API key from `_get_fred_api_key()` in `macro_collector.py` (import it)
- Cache to `training_data/fred_history.pkl` alongside the existing OHLCV cache
- Return a dict of DataFrames indexed by date

Add a point-in-time lookup helper:

```python
def get_fred_value_as_of(
    fred_data: dict[str, pd.DataFrame],
    series_id: str,
    as_of_date: str,
) -> float | None:
    """Get the most recent FRED value available on or before as_of_date."""
```

**Test:** `tests/test_fred_history.py`
```python
def test_fred_lookup_returns_point_in_time():
    # Mock a small DataFrame
    df = pd.DataFrame({"value": [1.5, 2.0, 2.5]},
                      index=pd.to_datetime(["2024-01-01", "2024-02-01", "2024-03-01"]))
    fred_data = {"UNRATE": df}
    # As of Feb 15, should return Feb value (2.0), not March
    val = get_fred_value_as_of(fred_data, "UNRATE", "2024-02-15")
    assert val == 2.0
```

**Commit:** `feat(historical_data): FRED historical series fetch + point-in-time lookup`

---

## Task 3: Add PASS analysis prompt

**File:** `src/llm/prompts.py` (currently 283 lines)

Add after `QUALITY_ENHANCEMENT_PROMPT`:

```python
PASS_ANALYSIS_PROMPT = """You are a senior equity analyst. Today is {date}. You are reviewing a potential pullback setup that has been flagged by the screening system but scored below the qualification threshold.

Your job: Analyze the setup and determine whether it meets the quality bar for entry. If it does not, explain SPECIFICALLY which factors are deficient and why the setup should be passed on.

A well-calibrated analyst passes on more setups than they take. Saying "no" with clear reasoning is as valuable as saying "yes."

RULES:
- Be specific about which factors fail the quality bar. Name the exact indicators or conditions.
- Compare what this setup lacks vs what a qualifying setup would show.
- If any aspect looks promising, acknowledge it — but explain why it's insufficient.
- Your conviction score MUST be 1-4 for below-threshold setups.
- Do NOT use language suggesting you would take this trade.

OUTPUT FORMAT:

<why_now>
[2-3 sentences stating that this setup does not qualify and the primary deficiency]
</why_now>

<analysis>
[4-6 paragraphs: what looks acceptable, what's specifically deficient, why the deficiency matters for this strategy, what would need to change to make this tradeable]
</analysis>

<metadata>
Conviction: [1-4]
Direction: NEUTRAL
Time Horizon: N/A — setup does not qualify
Key Risk: [the specific deficiency that disqualifies the trade]
</metadata>
"""
```

**No test needed** — this is a string constant. Validated at integration test time.

**Commit:** `feat(prompts): add PASS_ANALYSIS_PROMPT for below-threshold setups`

---

## Task 4: Add regime-targeted date sampler

**File:** Create `src/training/regime_sampler.py` (~120 lines)

This is a new file — keeps `backfill.py` from growing further (already at 445 lines).

```python
"""Regime-targeted date sampling for historical backfill.

Called by: training.backfill
Calls: features.regime, training.historical_data
Owns tables: none
"""

def classify_dates_by_regime(
    spy_df: pd.DataFrame,
) -> dict[str, list[str]]:
    """Classify every trading day into a regime bucket.

    Uses compute_market_regime() from features.regime on SPY data.

    Returns: {"calm_uptrend": ["2021-01-04", ...], ...}
    """

def sample_regime_balanced_dates(
    regime_dates: dict[str, list[str]],
    targets: dict[str, int],
    priority: list[str] | None = None,
) -> list[str]:
    """Sample scan dates to hit regime distribution targets.

    Args:
        regime_dates: Output of classify_dates_by_regime().
        targets: {"calm_uptrend": 120, "bear": 80, ...}
        priority: Regime priority for overlap resolution.

    Returns: List of scan dates, balanced across regimes.
    """
```

Map the 5 `regime_label` values to the target categories:
- `calm_uptrend` → Bull (target 120 dates)
- `calm_downtrend` → Bear (target 40 dates)
- `volatile_downtrend` → Bear OR High Vol based on VIX (VIX>25 → High Vol)
- `volatile_uptrend` → High Vol if VIX>25, else Bull
- `transitional` → Recovery (target 30 dates)

For Range Bound: identify runs of 15+ days where SPY stays within ±4% of 200 EMA.

**Test:** `tests/test_regime_sampler.py`
```python
def test_classify_returns_all_regime_types():
    # Use real SPY data from 2021-2025 (yfinance) or mock
    # Verify at least 3 of 5 regime types have dates

def test_sample_respects_targets():
    regime_dates = {"calm_uptrend": [f"2021-{m:02d}-01" for m in range(1,13)],
                    "volatile_downtrend": [f"2022-{m:02d}-01" for m in range(1,7)]}
    targets = {"calm_uptrend": 3, "volatile_downtrend": 3}
    result = sample_regime_balanced_dates(regime_dates, targets)
    assert len(result) == 6
```

**Commit:** `feat(regime_sampler): regime-targeted date selection for backfill diversity`

---

## Task 5: Enrich historical scanner with FRED macro data

**File:** `src/training/historical_scanner.py` (349 lines — room for ~50 more)

In `scan_historical_date()`, after the existing regime computation (~line 57), add FRED macro lookup:

```python
# After: regime = compute_market_regime(spy_df, ohlcv_dict)
# Add:
if fred_data:
    from src.training.historical_data import get_fred_value_as_of
    vix = get_fred_value_as_of(fred_data, "VIXCLS", scan_date)
    t10y2y = get_fred_value_as_of(fred_data, "T10Y2Y", scan_date)
    unrate = get_fred_value_as_of(fred_data, "UNRATE", scan_date)
    fedfunds = get_fred_value_as_of(fred_data, "FEDFUNDS", scan_date)

    curve_label = "inverted" if (t10y2y or 0) < 0 else "normal" if (t10y2y or 0) > 0.5 else "flat"

    macro_summary = (
        f"MACRO CONTEXT as of {scan_date}:\n"
        f"- VIX: {vix:.1f}\n" if vix else ""
        f"- Yield Curve (10Y-2Y): {t10y2y:.2f}% ({curve_label})\n" if t10y2y else ""
        f"- Fed Funds Rate: {fedfunds:.2f}%\n" if fedfunds else ""
        f"- Unemployment: {unrate:.1f}%\n" if unrate else ""
    )
```

Then in the feature computation loop, replace the placeholder:

```python
# BEFORE:
features["macro_summary"] = "Not available for historical scan"

# AFTER:
features["macro_summary"] = macro_summary if fred_data else "Macro data not available for this historical period."
```

Also replace the fundamental placeholder with contextual text:

```python
# BEFORE:
features["fundamental_summary"] = "Not available for historical scan"

# AFTER:
features["fundamental_summary"] = (
    f"Fundamental data not available for this historical period. "
    f"{company_name} is a {features.get('sector', 'unknown')} company in the S&P 100."
)
```

**Add `fred_data` parameter** to `scan_historical_date()` signature (default `None` for backward compatibility):

```python
def scan_historical_date(data: dict, scan_date: str, fred_data: dict = None) -> list[dict]:
```

**Test:** Update `tests/test_backfill.py` — verify that when `fred_data` is provided, `macro_summary` contains real values, not placeholder text.

**Commit:** `feat(historical_scanner): real FRED macro data in backfill examples`

---

## Task 6: Add PASS example generation path

**File:** `src/training/historical_scanner.py`

Add a function to generate below-threshold examples:

```python
def scan_historical_date_pass(
    data: dict, scan_date: str, fred_data: dict = None,
    min_score: float = 45, max_score: float = 69,
) -> list[dict]:
    """Scan for marginal setups that should NOT be traded.

    Same as scan_historical_date() but with a lower threshold
    and using PASS_ANALYSIS_PROMPT instead of BLINDED_ANALYSIS_PROMPT.
    """
```

This function:
- Uses the same `compute_features()` and `_score_ticker()` pipeline
- Filters for scores between `min_score` and `max_score`
- Returns candidates tagged with `is_pass=True`
- No outcome computation needed — PASS examples don't have trades

In `generate_backfill_example()`, handle PASS candidates:

```python
def generate_backfill_example(candidate: dict, outcome: dict | None = None) -> dict:
    # If outcome is None, this is a PASS example
    if outcome is None:
        return {
            "instruction": PASS_ANALYSIS_PROMPT.format(date=candidate["scan_date"]),
            "input_text": input_text,  # same feature format
            "output_text": None,
            "metadata": {
                "scan_date": candidate["scan_date"],
                "ticker": candidate["ticker"],
                "score": candidate["score"],
                "outcome_quality": "pass",
            },
        }
```

**Test:** `tests/test_backfill.py` — add test for PASS example generation with score in 45–69 range.

**Commit:** `feat(historical_scanner): PASS example generation for below-threshold setups`

---

## Task 7: Update backfill orchestrator with regime balancing

**File:** `src/training/backfill.py`

Replace `_balance_dataset()` with `_balance_by_regime_and_outcome()`. Since `backfill.py` is already at 445 lines, **refactor to move the new balancing logic into `regime_sampler.py`** and import it.

In `regime_sampler.py`, add:

```python
def balance_by_regime_and_outcome(
    examples: list[dict],
    regime_targets: dict[str, int],
    outcome_targets: dict[str, float],
    max_per_ticker: int = 25,
) -> list[dict]:
    """Balance examples across regime AND outcome dimensions.

    Two-pass approach:
    1. Bucket by regime, cap per regime per target
    2. Within each regime bucket, balance outcomes to target ratios
    3. Cap per-ticker to max_per_ticker
    """
```

In `backfill.py`, update `run_historical_backfill()`:

1. Add `lookback_years=5` parameter (was hardcoded to 2 via `fetch_historical_universe`)
2. Add `fred_data = fetch_fred_history()` call at Step 1
3. Pass `fred_data` to `scan_historical_date()` at Step 3
4. Use `regime_sampler.sample_regime_balanced_dates()` for date selection at Step 2
5. Add PASS example generation after Step 3 using `scan_historical_date_pass()`
6. Replace `_balance_dataset()` call at Step 6 with `balance_by_regime_and_outcome()`
7. Update source tags at Step 9: use `regime_backfill` for regime examples, `regime_pass` for PASS examples

**Important:** To keep `backfill.py` from growing, move `_balance_dataset()`, `_deduplicate_candidates()`, and `_cap_and_diversify()` into `regime_sampler.py` as well. This should net ~80 lines freed from `backfill.py` while adding ~30 lines of new import/integration code, keeping it ≤ 400 lines.

**Commit:** `refactor(backfill): regime-balanced distribution + PASS generation + FRED enrichment`

---

## Task 8: Add enhanced backfill CLI parameters

**File:** `src/main.py` (add arguments to existing `backfill-training` command)

```python
backfill_training.add_argument("--lookback-years", type=int, default=5)
backfill_training.add_argument("--regime-balanced", action="store_true",
    help="Use regime-targeted date sampling instead of sequential")
backfill_training.add_argument("--include-pass", action="store_true",
    help="Generate PASS examples for below-threshold setups (score 45-69)")
backfill_training.add_argument("--pass-count", type=int, default=90,
    help="Number of PASS examples to generate")
backfill_training.add_argument("--model-override", type=str, default=None,
    help="Claude model to use (e.g. claude-sonnet-4-6)")
```

Update `cmd_backfill_training()` in `src/cli/commands.py` to pass these through to `run_historical_backfill()`.

**Commit:** `feat(cli): enhanced backfill parameters — regime-balanced, PASS, lookback, model override`

---

## Task 9: Tests

**Files:**
- `tests/test_regime_sampler.py` (new — ~80 lines)
- `tests/test_fred_history.py` (new — ~50 lines)
- Update `tests/test_backfill.py` (~30 lines added)

Test matrix:

| Test | What It Verifies |
|------|-----------------|
| `test_classify_returns_all_regimes` | Regime classifier produces multiple categories |
| `test_sample_respects_targets` | Stratified sampling hits target counts |
| `test_sample_no_duplicates` | No date appears twice |
| `test_fred_point_in_time` | Lookup returns value as-of, not future |
| `test_fred_missing_returns_none` | Graceful handling of gaps |
| `test_pass_example_has_neutral_direction` | PASS examples use NEUTRAL metadata |
| `test_pass_score_range` | PASS examples have score 45–69 |
| `test_example_exists_matches_stored_source` | Resumability bug fix verified |
| `test_macro_summary_not_placeholder` | FRED data replaces "Not available" |

```bash
python -m pytest tests/test_regime_sampler.py tests/test_fred_history.py tests/test_backfill.py -v
```

**Commit:** `test: regime sampler, FRED history, enhanced backfill coverage`

---

## Task 10: Documentation update

**Files:**
- `MASTER.md` — Add enhanced backfill to sprint queue, note in Section 2
- `CHANGELOG.md` — Add entry
- `docs/sprints/sprint-enhanced-backfill.md` — This file (copy from spec)

**Commit:** `docs: enhanced backfill spec + changelog`

---

## Task 11: Execution (SEPARATE from code sprint — run manually)

After Tasks 1–10 are merged, run the backfill on a weekend:

```powershell
# Step 1: Verify
python -m pytest tests/ -x -q --ignore=tests/test_ingestion.py

# Step 2: Run enhanced backfill
python -m src.main backfill-training \
  --lookback-years 5 \
  --regime-balanced \
  --include-pass \
  --pass-count 90 \
  --max-examples 600 \
  --model-override claude-sonnet-4-6 \
  --yes

# Step 3: Verify quality
python -c "
import sqlite3
conn = sqlite3.connect('ai_research_desk.sqlite3')
total = conn.execute('SELECT COUNT(*) FROM training_examples').fetchone()[0]
new = conn.execute(\"SELECT COUNT(*) FROM training_examples WHERE source IN ('regime_backfill','regime_pass')\").fetchone()[0]
regimes = conn.execute(\"SELECT regime, COUNT(*) FROM training_examples WHERE source = 'regime_backfill' GROUP BY regime\").fetchall()
print(f'Total examples: {total}')
print(f'New from enhanced backfill: {new}')
for r, c in regimes:
    print(f'  {r}: {c}')
"

# Step 4: Run leakage detector
python -m src.main check-leakage

# Step 5: Score new examples
python -m src.main score-training --source regime_backfill
python -m src.main score-training --source regime_pass
```

---

## File Size Guardrails

| File | Before | After (target) | Action |
|------|--------|----------------|--------|
| `backfill.py` | 445 | ≤400 | Refactor: move 3 helper functions to `regime_sampler.py` |
| `historical_scanner.py` | 349 | ~395 | Add PASS scan + FRED integration (~46 lines) |
| `historical_data.py` | 156 | ~235 | Add FRED fetch + lookup (~79 lines) |
| `prompts.py` | 283 | ~315 | Add PASS prompt (~32 lines) |
| `regime_sampler.py` | 0 (new) | ~200 | New file: sampling + balancing |

No file exceeds 400 lines. No function exceeds 60 lines.

---

## Verification Checklist

```bash
# All tests pass
python -m pytest tests/ -x -q --ignore=tests/test_ingestion.py

# New tests pass
python -m pytest tests/test_regime_sampler.py tests/test_fred_history.py -v

# File sizes
find src/ -name "*.py" -not -path "*/__pycache__/*" -exec wc -l {} + | sort -rn | head -10

# backfill.py is SMALLER than before
wc -l src/training/backfill.py  # should be ≤400

# Frontend still builds
cd frontend && npm run build && cd ..
```

**Push:**
```bash
git push origin feat/enhanced-backfill
```
