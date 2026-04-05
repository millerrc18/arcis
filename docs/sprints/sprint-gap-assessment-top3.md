# Sprint: Gap Assessment — Top 3 Algorithm Improvements (v3 — Ralph ×3)

> **Priority:** HIGH — three highest-leverage improvements from deep research
> **Estimated time:** 5-7 hours CC time
> **Access:** LOCAL — CC has full access to codebase, tests, database, Ollama
> **Tag as v0.15.0 after merge.**
> **Issues:** Close #295, #296, #297 upon completion.

> ⚠️ **Read first:**
> - `MASTER.md` (repo root)
> - `docs/research/15_Algorithm_Gap_Assessment.md` — full research context

---

## Pre-Flight

1. Read `MASTER.md`
2. Run `python -m pytest tests/ -x -q` — record baseline count
3. **Verify dependencies exist** before starting any task:
   ```bash
   python -c "from sklearn.linear_model import LogisticRegression; print('sklearn OK')"
   python -c "from scipy.stats import beta; print('scipy OK')"
   python -c "import numpy; print('numpy OK')"
   python -c "import requests; r=requests.post('http://localhost:11434/api/embeddings', json={'model':'halcyon-v1.0.0','prompt':'test'}); print('Ollama embeddings:', 'OK' if r.status_code==200 else 'FAIL')"
   ```
   If sklearn or scipy missing: `pip install scikit-learn scipy --break-system-packages`
4. Read these existing files (they ALREADY exist — do NOT recreate):
   - `src/training/leakage_detector.py` (229 lines — has TF-IDF, needs embedding addition)
   - `scripts/diagnose_leakage.py` (266 lines — has 7 sections, add section 8)
   - `src/council/aggregation.py` (106 lines)
   - `src/council/constants.py` (has DOMAIN_WEIGHTS per session type: daily/weekly/monthly/strategic)
   - `src/council/value_tracker.py` (221 lines)
   - `src/council/engine.py` (443 lines — wires aggregation + value tracking)
   - `src/ranking/ranker.py` (226 lines — ALREADY has 7 regime-adaptive thresholds)
   - `src/universe/sectors.py` (126 lines — has SECTOR_MAP with names like "Technology")
   - `tests/test_leakage_detector.py`, `tests/test_council_aggregation.py`, `tests/test_ranker.py`

---

## Task 1: Embedding-Based Leakage Detection (Closes #295)

### Context
`src/training/leakage_detector.py` ALREADY EXISTS (229 lines) with a working TF-IDF approach.
Current thresholds: ≤55% balanced accuracy = "clean", 55-65% = "warning", >65% = "leaking".
The existing function is `check_outcome_leakage()`. Do NOT rewrite it.

### What to add

**1a. Add `check_embedding_leakage()` function to `src/training/leakage_detector.py`:**

```python
def check_embedding_leakage(db_path: str = DB_PATH,
                             model: str = "halcyon-v1.0.0",
                             timeout: int = 10,
                             max_examples: int = 500) -> dict:
    """Embedding-based leakage detection — catches semantic leakage TF-IDF misses.

    WHY: TF-IDF treats words independently. "The trade was profitable" and
    "the position yielded positive returns" share few tokens but both leak
    outcomes. Kapoor & Narayanan (2023, 369 citations) showed this blind spot
    exists across 294 published papers.

    HOW: Generate embeddings via Ollama /api/embeddings endpoint, then train
    a logistic regression classifier to predict outcome from embeddings.
    If balanced accuracy > 55%, the training data contains semantic leakage.

    Args:
        db_path: Path to SQLite database with training_data table
        model: Ollama model name for embedding generation
        timeout: Seconds per Ollama embedding request
        max_examples: Cap to prevent OOM on large datasets (random sample)

    Returns:
        dict with balanced_accuracy, leaking (bool), n_examples, cv_scores,
        class_distribution, embedding_dim, processing_time_seconds
    """
```

**Implementation details CC must follow:**
- Use `requests.post("http://localhost:11434/api/embeddings", json={"model": model, "prompt": text[:2000]}, timeout=timeout)`
- Extract embedding from `response.json()["embedding"]`
- If Ollama is down, return `{"error": "Ollama unavailable", "leaking": None}`
- If fewer than 20 examples, return `{"error": "Insufficient data", "n_examples": n}`
- Use `sklearn.model_selection.cross_val_score` with `cv=5` and `scoring="balanced_accuracy"`
- Use `sklearn.linear_model.LogisticRegression(max_iter=1000, class_weight="balanced")`
- Progress logging: print every 50 embeddings ("Embedding 50/979...")
- Cap at `max_examples=500` with random sampling if dataset is larger (speed)
- Store processing time in result dict
- WIN/LOSS classification: map outcomes from `training_data.outcome` column
  - WIN: "target_1_hit", "target_2_hit", "WIN"
  - LOSS: "stop_hit", "timeout", "LOSS"
  - Skip examples with NULL or ambiguous outcomes

**1b. Add `check_all_leakage()` convenience function:**

```python
def check_all_leakage(db_path: str = DB_PATH) -> dict:
    """Run both TF-IDF and embedding leakage checks. Returns combined results."""
    tfidf = check_outcome_leakage(db_path)
    embedding = check_embedding_leakage(db_path)
    return {
        "tfidf": tfidf,
        "embedding": embedding,
        "overall_leaking": tfidf.get("is_leaking", False) or embedding.get("leaking", False),
        "recommendation": _recommend(tfidf, embedding),
    }

def _recommend(tfidf: dict, embedding: dict) -> str:
    if embedding.get("leaking"):
        return "CRITICAL: Semantic leakage detected. Audit training templates immediately."
    if tfidf.get("is_leaking"):
        return "WARNING: Token-level leakage detected. Check for outcome keywords."
    return "CLEAN: No leakage detected at token or semantic level."
```

**1c. Add Section 8 to `scripts/diagnose_leakage.py`:**
After the existing Section 7, add:
```python
print("\n" + "="*60)
print("  Section 8: Embedding-Based Semantic Leakage Detection")
print("="*60)
from src.training.leakage_detector import check_embedding_leakage
result = check_embedding_leakage()
if "error" in result:
    print(f"  Skipped: {result['error']}")
else:
    print(f"  Balanced accuracy: {result['balanced_accuracy']:.4f}")
    print(f"  Semantic leaking: {'YES — INVESTIGATE' if result['leaking'] else 'No'}")
    print(f"  Examples analyzed: {result['n_examples']}")
    print(f"  CV scores: {result.get('cv_scores', [])}")
    print(f"  Processing time: {result.get('processing_time_seconds', 0):.1f}s")
```

**1d. Run the detector on actual training data and log results:**
```bash
python scripts/diagnose_leakage.py 2>&1 | tee docs/audits/leakage-audit-2026-04-05.md
```
Store the output as an audit trail.

### Tests — update `tests/test_leakage_detector.py`

Add these test cases (do NOT delete existing TF-IDF tests):
- `test_embedding_leakage_with_mock_ollama()` — mock the requests.post call, verify classifier runs
- `test_embedding_leakage_ollama_down()` — mock ConnectionError, verify graceful fallback
- `test_embedding_leakage_insufficient_data()` — fewer than 20 examples returns error
- `test_embedding_leakage_threshold()` — verify >55% = leaking, ≤55% = clean
- `test_check_all_leakage_combines_results()` — verify combined function works
- `test_embedding_leakage_class_balance()` — verify class_weight="balanced" prevents majority-class bias

---

## Task 2: Dynamic Bayesian Agent Weighting (Closes #296)

### Context
`src/council/constants.py` has static DOMAIN_WEIGHTS with **4 session types** (daily, weekly, monthly, strategic), each with 5 agent weights. The current weights are fixed multipliers (0.6-1.5).

`src/council/aggregation.py` already has `aggregate_votes()` which uses DOMAIN_WEIGHTS.

`src/council/value_tracker.py` tracks counterfactual P&L but doesn't compute per-agent accuracy.

### What to change

**2a. Add to `src/council/constants.py`:**
```python
# Dynamic weight parameters (Ralph Loop 1: added for Bayesian agent weighting)
DYNAMIC_WEIGHT_ENABLED = True          # Feature flag — can disable without code change
INITIAL_AGENT_ALPHA = 1.0              # Beta distribution prior: successes
INITIAL_AGENT_BETA = 1.0               # Beta distribution prior: failures
WEIGHT_EMA_DECAY = 0.9                 # EMA decay for weight smoothing
MIN_AGENT_WEIGHT = 0.05                # Floor: no agent below 5% of total weight
VALUE_TRACKER_WINDOW_WEEKS = 12        # Extended from 8 (was too short — ~2.25 trades/agent/cycle)
MIN_VOTES_FOR_DYNAMIC = 10            # Fall back to static weights if fewer than 10 votes per agent
```

**2b. Add `compute_dynamic_weights()` to `src/council/aggregation.py`:**

```python
def compute_dynamic_weights(db_path: str = DB_PATH,
                             session_type: str = "daily") -> dict[str, float] | None:
    """Compute Bayesian agent weights from vote accuracy history.

    WHY: Static weights can't adapt. Yue (2025, ICAID) showed dynamic weighting
    improves Sharpe by 38.5%. Beta distribution provides uncertainty-aware estimates
    that naturally revert to equal weights when data is sparse.

    Returns None if insufficient data (falls back to static DOMAIN_WEIGHTS).
    """
    if not DYNAMIC_WEIGHT_ENABLED:
        return None

    # Query council_votes table for each agent's directional accuracy
    # Compare agent's vote direction against actual trade outcome
    # ...
```

**Key implementation details:**
- Query `council_votes` JOIN `shadow_trades` to find which agent directions matched actual outcomes
- Each agent gets (correct_count, incorrect_count) from last `VALUE_TRACKER_WINDOW_WEEKS`
- If ANY agent has fewer than `MIN_VOTES_FOR_DYNAMIC` votes, return None (use static)
- Compute `expected_accuracy = alpha / (alpha + beta)` per agent from Beta posterior
- Apply `MIN_AGENT_WEIGHT` floor
- Normalize so all weights sum to 1.0 (matching current DOMAIN_WEIGHTS contract)
- Return dict with same agent keys as DOMAIN_WEIGHTS[session_type]
- Log weight changes: `logger.info("[COUNCIL] Dynamic weights: %s", weights)`

**2c. Modify `aggregate_votes()` in `src/council/aggregation.py`:**

The existing function signature is:
```python
def aggregate_votes(assessments: list[dict], session_type: str = "daily") -> dict:
```

Add dynamic weight lookup at the top:
```python
def aggregate_votes(assessments: list[dict], session_type: str = "daily",
                    db_path: str = DB_PATH) -> dict:
    # Try dynamic weights first
    dynamic = compute_dynamic_weights(db_path, session_type)
    weights = dynamic if dynamic else DOMAIN_WEIGHTS.get(session_type, DOMAIN_WEIGHTS["daily"])
    # ... rest of aggregation uses `weights` instead of DOMAIN_WEIGHTS directly
```

**CRITICAL:** Do NOT break the existing aggregation logic. The dynamic weights must be a drop-in
replacement for the static weights dict. If anything goes wrong, fallback to static weights.

**2d. Add per-agent track record to `src/council/value_tracker.py`:**

```python
def get_agent_track_records(db_path: str = DB_PATH,
                             window_weeks: int = VALUE_TRACKER_WINDOW_WEEKS) -> dict:
    """Get per-agent directional accuracy over the evaluation window.

    Returns: {agent_name: {"correct": int, "incorrect": int, "total": int}}
    """
```

**2e. Extend evaluation window:**
Find the existing 8-week constant and change to 12 weeks. Search for `8` in value_tracker.py
near window/threshold logic. Also check `engine.py` for hardcoded 8-week references.

**2f. Wire into `src/council/engine.py`:**
In the `_run_session()` or equivalent method that calls `aggregate_votes()`, pass db_path
so dynamic weights can be computed. Add logging showing which weight mode was used.

### Tests — update `tests/test_council_aggregation.py`

Add:
- `test_dynamic_weights_computation()` — mock DB with known vote history, verify weights
- `test_dynamic_weights_floor_enforcement()` — verify no agent below MIN_AGENT_WEIGHT
- `test_dynamic_weights_normalization()` — verify weights sum to 1.0
- `test_dynamic_weights_insufficient_data_fallback()` — fewer than MIN_VOTES returns None
- `test_dynamic_weights_feature_flag_disabled()` — DYNAMIC_WEIGHT_ENABLED=False returns None
- `test_aggregate_votes_uses_dynamic_when_available()` — verify integration

---

## Task 3: Two-Tier RS + Enhanced Ranker (Closes #297)

### Context
`src/ranking/ranker.py` ALREADY has regime-adaptive thresholds (7 levels: BULL_LOW_VOL=40
through CRISIS=90). The sprint enhances the RS scoring, NOT the threshold system.

`src/universe/sectors.py` ALREADY exists (126 lines) with SECTOR_MAP mapping tickers to
sector names ("Technology", "Financials", etc). Needs SECTOR_ETF_MAP added.

### What to change

**3a. Add sector ETF mapping to `src/universe/sectors.py`:**

```python
# Sector ETF map — for two-tier relative strength computation
SECTOR_ETF_MAP: dict[str, str] = {
    "Technology": "XLK",
    "Communication Services": "XLC",
    "Consumer Discretionary": "XLY",
    "Consumer Staples": "XLP",
    "Energy": "XLE",
    "Financials": "XLF",
    "Health Care": "XLV",
    "Industrials": "XLI",
    "Materials": "XLB",
    "Real Estate": "XLRE",
    "Utilities": "XLU",
}

def get_sector_etf(ticker: str) -> str | None:
    """Get the sector ETF ticker for a given stock."""
    sector = SECTOR_MAP.get(ticker)
    if sector:
        return SECTOR_ETF_MAP.get(sector)
    return None
```

**3b. Add sector RS computation to `src/ranking/ranker.py`:**

Add a helper function:
```python
def _compute_sector_rs(ticker_features: dict, sector_ohlcv: pd.DataFrame | None) -> float | None:
    """Compute relative strength vs sector ETF over 1m/3m/6m periods.

    Returns combined RS score (0-25) or None if sector data unavailable.
    Uses same methodology as existing SPY RS but against sector ETF.
    """
    if sector_ohlcv is None or sector_ohlcv.empty:
        return None
    # ... compute 1m, 3m, 6m returns vs sector ETF
    # ... classify as strong_outperformer/outperformer/neutral/underperformer
    # ... return score 0-25
```

**3c. Modify `_score_ticker()` to use two-tier RS:**

Current RS scoring (lines ~125-130):
```python
rs = features.get("relative_strength_state", "")
if rs == "strong_outperformer":
    score += 25
elif rs == "outperformer":
    score += 15
```

Replace with:
```python
# Two-tier relative strength: 60% vs SPY + 40% vs sector ETF
market_rs = features.get("relative_strength_state", "")
market_rs_score = 25 if market_rs == "strong_outperformer" else 15 if market_rs == "outperformer" else 0

sector_rs_score = features.get("_sector_rs_score")  # Computed in rank_universe()
if sector_rs_score is not None:
    combined_rs = 0.6 * market_rs_score + 0.4 * sector_rs_score
else:
    combined_rs = market_rs_score  # Fallback to market-only
score += combined_rs
```

**3d. Modify `rank_universe()` to fetch sector ETF data and compute sector RS:**

In the main loop over tickers, before calling `_score_ticker()`:
```python
from src.universe.sectors import get_sector_etf

# Fetch sector ETF OHLCV data (once per unique sector, not per ticker)
sector_etf_data = {}
for sector, etf in SECTOR_ETF_MAP.items():
    if etf not in sector_etf_data:
        try:
            sector_etf_data[etf] = _fetch_ohlcv(etf, ...)  # Same yfinance fetch as SPY
        except Exception:
            pass

# In the per-ticker scoring loop:
for ticker, feat in features.items():
    etf = get_sector_etf(ticker)
    if etf and etf in sector_etf_data:
        feat["_sector_rs_score"] = _compute_sector_rs(feat, sector_etf_data[etf])
    score = _score_ticker(feat)
```

**3e. Narrow pullback sweet spot and increase volume weight:**

In `_score_ticker()`, change:
```python
# Pullback depth: narrowed for S&P 100 large-caps
if -8 <= pullback <= -3:        # Was -10
    score += 25
elif -12 <= pullback < -8:      # Was -15
    score += 10

# Volume contraction: increased weight (research supports higher)
if vol_ratio < 0.8:
    score += 15                  # Was 10
```

**IMPORTANT:** The total max score changes from 100 to 105 due to volume increase.
Either reduce another weight by 5 or cap at 100. Recommend keeping the cap at 100
(already in `max(0, min(100, score))` at the end).

**3f. Do NOT modify the existing regime-adaptive thresholds.** They already cover 7 regime
levels (BULL_LOW_VOL=40 through CRISIS=90). The gap assessment recommended simpler
VIX-based thresholds, but the existing implementation is MORE sophisticated. Keep it.

### Tests — update `tests/test_ranker.py`

Add:
- `test_two_tier_rs_with_sector_data()` — verify combined RS scoring
- `test_two_tier_rs_fallback_no_sector()` — verify fallback to market-only RS
- `test_sector_etf_mapping_completeness()` — verify all 103 tickers in SECTOR_MAP have a matching SECTOR_ETF_MAP entry
- `test_narrowed_pullback_sweet_spot()` — verify -8% boundary (was -10%)
- `test_increased_volume_weight()` — verify +15 (was +10)
- `test_score_capped_at_100()` — verify max(0, min(100, score)) still enforced
- `test_backward_compatibility_no_sector()` — verify that when sector data is None, scores match old behavior exactly

---

## Verification

```bash
# All tests pass
python -m pytest tests/ -x -q                          # Pass count >= baseline

# Specific test files
python -m pytest tests/test_leakage_detector.py -v      # All new + existing tests pass
python -m pytest tests/test_council_aggregation.py -v   # All new + existing tests pass
python -m pytest tests/test_ranker.py -v                # All new + existing tests pass

# Frontend builds
cd frontend && npm run build && cd ..

# Manual verification (requires Ollama running):
python -c "from src.training.leakage_detector import check_all_leakage; import json; print(json.dumps(check_all_leakage(), indent=2))"

# Ranker backward compatibility check:
python -c "
from src.ranking.ranker import _score_ticker
# Verify old-style features (no sector RS) produce same score as before
features = {'trend_state': 'strong_uptrend', 'relative_strength_state': 'strong_outperformer', 'pullback_depth_pct': -5.0, 'dist_to_sma20_pct': -2.0, 'volume_ratio_20d': 0.7}
score = _score_ticker(features)
print(f'Score (no sector RS): {score}')
# Expected: 30 + 25 + 25 + 10 + 15 = 105 -> capped at 100
assert score == 100, f'Expected 100, got {score}'
print('Backward compatibility OK')
"
```

---

## Commit Strategy

3 commits for clean history, then tag:

```bash
# Commit 1: Leakage detection
git add src/training/leakage_detector.py scripts/diagnose_leakage.py tests/test_leakage_detector.py docs/audits/leakage-audit-*.md
git commit -m "feat: embedding-based semantic leakage detection (#295)

Add check_embedding_leakage() and check_all_leakage() to leakage_detector.py.
Uses Ollama /api/embeddings + LogisticRegression for semantic-level detection.
TF-IDF catches token leakage; embeddings catch paraphrased outcome information.
Section 8 added to diagnose_leakage.py. Audit results stored.

Closes #295"

# Commit 2: Council dynamic weights
git add src/council/constants.py src/council/aggregation.py src/council/value_tracker.py src/council/engine.py tests/test_council_aggregation.py
git commit -m "feat: dynamic Bayesian agent weighting for AI Council (#296)

Replace static DOMAIN_WEIGHTS with track-record-based dynamic weights.
Beta distribution posterior for per-agent accuracy estimation.
Feature flag DYNAMIC_WEIGHT_ENABLED for safe rollback.
Evaluation window extended 8 -> 12 weeks. MIN_VOTES_FOR_DYNAMIC = 10
ensures fallback to static weights when data is sparse.

Closes #296"

# Commit 3: Ranker enhancements
git add src/ranking/ranker.py src/universe/sectors.py tests/test_ranker.py
git commit -m "feat: two-tier relative strength + ranker enhancements (#297)

Two-tier RS: 60% vs SPY + 40% vs sector ETF (11 sector ETFs mapped).
Volume contraction weight increased 10 -> 15 (research: Cartea et al.).
Pullback sweet spot narrowed -3% to -8% (was -10%) for S&P 100.
Backward compatible: falls back to market-only RS when sector data unavailable.
Existing 7-level regime-adaptive thresholds preserved.

Closes #297"

# Tag + push
git tag -a v0.15.0 -m "v0.15.0 — Gap assessment: leakage detection, council weights, ranker RS"
git push origin main && git push origin v0.15.0
```

Update MASTER.md Section 2 (strategy decisions 25→28, issues, test count) and add v0.15.0 to RELEASES.md.
