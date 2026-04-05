# Sprint: Gap Assessment — Top 3 Algorithm Improvements

> **Priority:** HIGH — these are the three highest-leverage improvements identified by deep research
> **Estimated time:** 4-6 hours CC time
> **Access:** LOCAL — CC has full access to codebase, tests, database
> **Tag as v0.15.0 after merge.**
> **Issues:** Close #295, #296, #297 upon completion.

> ⚠️ **Read first:**
> - `MASTER.md` (repo root)
> - `docs/research/15_Algorithm_Gap_Assessment.md` — full research context
> - Each issue on GitHub for acceptance criteria

---

## Pre-Flight

1. Read `MASTER.md`
2. Run `python -m pytest tests/ -x -q` — record baseline
3. Read the 3 source files before modifying:
   - `src/training/leakage_detector.py` (or `scripts/diagnose_leakage.py`)
   - `src/council/aggregation.py` + `src/council/value_tracker.py` + `src/council/constants.py`
   - `src/ranking/ranker.py`

---

## Task 1: Embedding-Based Leakage Detection (Closes #295)

**File:** `src/training/leakage_detector.py` (create if not exists)

The current TF-IDF leakage detector cannot catch semantic leakage — paraphrased outcome
information passes undetected. Add an embedding-based classifier as a second detection layer.

### Implementation

1. **Create `src/training/leakage_detector.py`** with two functions:

```python
def tfidf_leakage_check(db_path: str = DB_PATH) -> dict:
    """Existing TF-IDF approach — move from diagnose_leakage.py."""
    # ... existing code ...

def embedding_leakage_check(db_path: str = DB_PATH, model: str = "halcyon-v1.0.0") -> dict:
    """Embedding-based leakage detection using the model's own encoder.
    
    Steps:
    1. Load all training examples from training_data table
    2. For each example, generate embedding via Ollama /api/embeddings endpoint
    3. Train LogisticRegression on embeddings to predict outcome (WIN vs LOSS)
    4. Compute balanced accuracy via 5-fold cross-validation
    5. If balanced accuracy > 55%, flag as LEAKING
    
    Returns:
        {"balanced_accuracy": float, "leaking": bool, "n_examples": int,
         "class_distribution": dict, "top_features": list}
    """
```

2. **Ollama embedding endpoint:**
```python
import requests

def get_embedding(text: str, model: str = "halcyon-v1.0.0") -> list[float]:
    resp = requests.post("http://localhost:11434/api/embeddings", json={
        "model": model,
        "prompt": text[:2000],  # Truncate to avoid context overflow
    })
    return resp.json()["embedding"]
```

3. **Classification pipeline:**
```python
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import cross_val_score

def embedding_leakage_check(db_path, model):
    examples = _load_training_examples(db_path)
    
    # Generate embeddings (this will take a few minutes for ~979 examples)
    embeddings = []
    labels = []
    for ex in examples:
        emb = get_embedding(ex["input_text"], model)
        embeddings.append(emb)
        labels.append(1 if ex["outcome"] in ("WIN", "target_1_hit", "target_2_hit") else 0)
    
    X = np.array(embeddings)
    y = np.array(labels)
    
    # 5-fold cross-validation with balanced accuracy
    clf = LogisticRegression(max_iter=1000, class_weight="balanced")
    scores = cross_val_score(clf, X, y, cv=5, scoring="balanced_accuracy")
    
    bal_acc = scores.mean()
    return {
        "balanced_accuracy": round(bal_acc, 4),
        "leaking": bal_acc > 0.55,
        "n_examples": len(examples),
        "cv_scores": scores.tolist(),
        "threshold": 0.55,
        "class_distribution": {"win": int(y.sum()), "loss": int(len(y) - y.sum())},
    }
```

4. **Update `scripts/diagnose_leakage.py`** to call both checks:
```python
print("\n=== Section 8: Embedding-Based Leakage Detection ===")
from src.training.leakage_detector import embedding_leakage_check
result = embedding_leakage_check()
print(f"  Balanced accuracy: {result['balanced_accuracy']:.4f}")
print(f"  Leaking: {result['leaking']}")
```

5. **Run the detector on current training data** and log the results.

### Tests

Create `tests/test_leakage_detector.py`:
- Test TF-IDF check runs without error
- Test embedding check with mock Ollama endpoint
- Test threshold logic (>0.55 = leaking)
- Test with intentionally leaked data (should detect)
- Test with clean data (should not detect)

---

## Task 2: Dynamic Bayesian Agent Weighting (Closes #296)

**Files:** `src/council/aggregation.py`, `src/council/value_tracker.py`, `src/council/constants.py`

Replace static domain weights with track-record-based dynamic weights.

### Implementation

1. **In `src/council/constants.py`**, add:
```python
# Dynamic weight parameters
INITIAL_AGENT_ALPHA = 1.0   # Beta distribution prior: alpha (successes)
INITIAL_AGENT_BETA = 1.0    # Beta distribution prior: beta (failures)
WEIGHT_EMA_DECAY = 0.9      # EMA decay factor for weight updates
MIN_AGENT_WEIGHT = 0.05     # Floor: no agent drops below 5% weight
VALUE_TRACKER_WINDOW_WEEKS = 12  # Extended from 8 weeks
```

2. **In `src/council/aggregation.py`**, add dynamic weight computation:
```python
def compute_dynamic_weights(agent_track_records: dict[str, dict],
                             session_type: str = "daily") -> dict[str, float]:
    """Compute Bayesian-weighted agent weights from track records.
    
    Each agent's weight is proportional to E[accuracy] from its Beta posterior:
        weight_i = (alpha_i) / (alpha_i + beta_i)
    
    where alpha_i = prior + correct predictions, beta_i = prior + incorrect.
    Normalized so all weights sum to 1.0, with MIN_AGENT_WEIGHT floor.
    """
    from scipy.stats import beta as beta_dist
    
    raw_weights = {}
    for agent, record in agent_track_records.items():
        alpha = INITIAL_AGENT_ALPHA + record.get("correct", 0)
        beta_param = INITIAL_AGENT_BETA + record.get("incorrect", 0)
        # Expected accuracy from Beta posterior
        raw_weights[agent] = alpha / (alpha + beta_param)
    
    # Apply floor and normalize
    total = sum(max(w, MIN_AGENT_WEIGHT) for w in raw_weights.values())
    return {
        agent: max(w, MIN_AGENT_WEIGHT) / total
        for agent, w in raw_weights.items()
    }
```

3. **Modify `aggregate_votes()`** to accept and use dynamic weights:
```python
def aggregate_votes(assessments, session_type="daily", 
                    dynamic_weights=None):
    # If dynamic weights provided, use them instead of static DOMAIN_WEIGHTS
    weights = dynamic_weights or DOMAIN_WEIGHTS
    # ... rest of aggregation logic using weights ...
```

4. **In `src/council/value_tracker.py`**, extend evaluation window:
- Change `EVALUATION_WINDOW_WEEKS = 8` → `12`
- Add method to compute per-agent track records from `council_votes` table
- Add method to persist agent weights to `council_parameter_state`

5. **In `src/council/engine.py`**, wire it together:
```python
# Before aggregation, load dynamic weights
track_records = value_tracker.get_agent_track_records(db_path)
dynamic_weights = compute_dynamic_weights(track_records)
result = aggregate_votes(assessments, dynamic_weights=dynamic_weights)
# Log weight changes
logger.info("[COUNCIL] Dynamic weights: %s", dynamic_weights)
```

### Tests

Update `tests/test_council_aggregation.py`:
- Test dynamic weight computation with mock track records
- Test floor enforcement (no agent below 5%)
- Test normalization (weights sum to 1.0)
- Test with empty track records (should fall back to equal weights)
- Test Bayesian update: agent with 8/10 correct gets higher weight than 5/10

---

## Task 3: Two-Tier RS + Regime-Adaptive Threshold (Closes #297)

**File:** `src/ranking/ranker.py`

### Implementation

1. **Add sector ETF mapping** (create `src/universe/sectors.py` or add to `sp100.py`):
```python
SECTOR_ETF_MAP = {
    "Information Technology": "XLK",
    "Health Care": "XLV",
    "Financials": "XLF",
    "Consumer Discretionary": "XLY",
    "Communication Services": "XLC",
    "Industrials": "XLI",
    "Consumer Staples": "XLP",
    "Energy": "XLE",
    "Utilities": "XLU",
    "Real Estate": "XLRE",
    "Materials": "XLB",
}

# Map each S&P 100 ticker to its sector ETF
TICKER_SECTOR = {
    "AAPL": "XLK", "MSFT": "XLK", "GOOGL": "XLC", "AMZN": "XLY",
    "JPM": "XLF", "JNJ": "XLV", "XOM": "XLE", "PG": "XLP",
    # ... complete mapping for all 103 tickers
}
```

2. **Modify `_score_ticker()` in ranker.py:**
```python
def _score_ticker(features: dict, sector_rs: float = None) -> float:
    score = 0
    
    # Trend (unchanged): +30
    # ...
    
    # Relative strength: now two-tier
    market_rs = features.get("rs_3m_vs_spy", 0)
    if sector_rs is not None:
        # 60% market RS + 40% sector RS
        combined_rs = 0.6 * _rs_score(market_rs) + 0.4 * _rs_score(sector_rs)
    else:
        combined_rs = _rs_score(market_rs)
    score += combined_rs  # max 25
    
    # Pullback depth: narrowed sweet spot for S&P 100
    pullback = features.get("pullback_depth_pct", 0) or 0
    if 3.0 <= pullback <= 8.0:    # Was 10.0
        score += 25
    elif 8.0 < pullback <= 12.0:  # Reduced credit for deeper pullbacks
        score += 10
    
    # Volume contraction: increased weight
    vol_ratio = features.get("volume_ratio_20d", 1.0) or 1.0
    if vol_ratio < 0.8:
        score += 15  # Was 10
    
    # ... rest unchanged ...
```

3. **Add regime-adaptive threshold:**
```python
def _get_adaptive_threshold(regime_label: str, vix: float = None) -> int:
    """Adjust packet_worthy threshold based on market conditions."""
    if vix is not None and vix < 15:
        return 50  # High bar in low-vol bull
    elif vix is not None and vix > 25:
        return 35  # Lower bar in volatile correction
    elif regime_label in ("calm_downtrend", "volatile_downtrend"):
        return 50  # High bar in bearish regimes
    return 40  # Default
```

4. **Compute sector-relative RS in `rank_universe()`:**
```python
def rank_universe(features, spy_data=None, sector_data=None):
    # Fetch sector ETF data if not provided
    if sector_data is None:
        sector_data = _fetch_sector_etfs()
    
    for ticker, feat in features.items():
        sector_etf = TICKER_SECTOR.get(ticker)
        sector_rs = _compute_sector_rs(feat, sector_data.get(sector_etf))
        score = _score_ticker(feat, sector_rs=sector_rs)
        # ...
```

### Tests

Update `tests/test_ranker.py`:
- Test two-tier RS computation
- Test sector ETF mapping completeness (all 103 tickers mapped)
- Test regime-adaptive thresholds for each VIX range
- Test narrowed pullback sweet spot
- Test increased volume weight
- Test backward compatibility (results with sector_rs=None match old behavior)

---

## Verification

```bash
python -m pytest tests/ -x -q          # Pass count >= baseline
python -m pytest tests/test_leakage_detector.py -v
python -m pytest tests/test_council_aggregation.py -v
python -m pytest tests/test_ranker.py -v
cd frontend && npm run build            # Succeeds

# Run embedding leakage check on actual data (requires Ollama running)
# python -c "from src.training.leakage_detector import embedding_leakage_check; print(embedding_leakage_check())"
```

---

## Commit

```bash
# Commit 1: Leakage detection
git add -A
git commit -m "feat: embedding-based leakage detection (#295)

Replace TF-IDF-only leakage detection with two-layer approach:
Layer 1: TF-IDF balanced accuracy (fast, token-level)
Layer 2: Embedding classifier via Ollama (semantic-level)
Catches 2-3x more subtle leakage patterns.

Closes #295"

# Commit 2: Council dynamic weights
git add -A
git commit -m "feat: dynamic Bayesian agent weighting for AI Council (#296)

Replace static DOMAIN_WEIGHTS with track-record-based EMA weights.
Beta distribution posterior for per-agent accuracy estimation.
Evaluation window extended from 8 to 12 weeks.
Min weight floor at 5% prevents total agent silencing.

Closes #296"

# Commit 3: Ranker improvements
git add -A
git commit -m "feat: two-tier RS + regime-adaptive threshold in ranker (#297)

Two-tier relative strength: 60% vs SPY + 40% vs sector ETF.
Regime-adaptive threshold: 50 (low-vol), 40 (normal), 35 (volatile).
Volume contraction weight increased 10 -> 15.
Pullback sweet spot narrowed -3% to -8% (was -10%) for S&P 100.

Closes #297"

# Tag
git tag -a v0.15.0 -m "v0.15.0 — Gap assessment top 3: leakage detection, council weights, ranker RS"
git push origin main && git push origin v0.15.0
```

Update MASTER.md (strategy decisions 25→28, issues closed) and RELEASES.md.
