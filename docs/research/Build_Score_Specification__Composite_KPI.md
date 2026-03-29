# Build Score — Single Composite KPI Specification

> **Purpose:** One number (0-100) that answers "am I building a product day by day?"
> Displayed at the top of the dashboard. Updated daily. Decays on idle days.

---

## Formula

**Build Score = geometric_mean(gate_velocity, system_health, data_asset_value, model_quality, research_velocity, reliability)**

Geometric mean ensures ALL dimensions must be healthy simultaneously. If any dimension is zero, the entire score crashes. You can't game it by pumping one dimension while neglecting others.

**Daily decay:** On any calendar day with zero closed trades AND zero new training examples AND zero scan cycles, the Build Score drops 1 point. This encourages consistent daily engagement.

**Update frequency:** Computed at end of each trading day (4:30 PM ET) and stored in a `build_score_history` table.

---

## Component Definitions

### 1. Gate Velocity (weight in geometric mean: equal)

**What it measures:** Rate of progress toward the current phase gate.

**Computation:**
```python
# Phase 1: 50-trade gate
trades_closed_this_week = count(shadow_trades WHERE status='closed' AND actual_exit_time > 7_days_ago)
target_weekly_rate = 50 / 26  # ~1.92 trades/week (targeting 50 in 6 months)

if target_weekly_rate == 0:
    gate_velocity = 0
else:
    raw = (trades_closed_this_week / target_weekly_rate) * 50  # 50 = on pace
    gate_velocity = min(100, raw)
```

| Score | Meaning |
|---|---|
| 0 | No trades closed this week |
| 25 | Half the target rate |
| 50 | On pace for gate |
| 75 | 1.5× pace |
| 100 | 2× pace or better |

### 2. System Health (weight: equal)

**What it measures:** Current HSHS composite score.

**Computation:**
```python
from src.evaluation.hshs_live import compute_hshs
hshs = compute_hshs()
system_health = hshs["hshs"]  # Already 0-100
```

### 3. Data Asset Value (weight: equal)

**What it measures:** The competitive value of the training data — not just volume, but quality × diversity × freshness.

**Sub-components (weighted average within this dimension):**

#### 3a. Quality (40% of data asset score)
```python
# Average quality score of examples created in last 30 days
recent_quality = AVG(quality_score) FROM training_examples
                 WHERE created_at > 30_days_ago AND quality_score IS NOT NULL

# Normalize from 0-30 rubric to 0-100
quality_score = (recent_quality / 30) * 100

# If no scored examples in 30 days, score = 20 (penalty for no scoring)
if recent_quality is None:
    quality_score = 20
```

#### 3b. Diversity (35% of data asset score)
```python
# Three sub-metrics, averaged:

# Regime coverage: how many distinct regimes are represented?
# Target: 4 regimes (GREEN, YELLOW, RED, TRANSITION)
regime_count = COUNT(DISTINCT regime) FROM training_examples WHERE regime IS NOT NULL
regime_score = (regime_count / 4) * 100

# Outcome balance: how close to target distribution?
# Target: 40% WIN, 25% LOSS, 5% TIMEOUT, 15% PASS
# Measure via chi-squared distance from target, normalized
outcome_counts = COUNT(*) GROUP BY outcome FROM training_examples
# KL divergence from target → 0 = perfect match → score 100
# Simplified: just check if LOSS examples ≥ 15% of total
loss_pct = count_loss / total
outcome_score = min(100, (loss_pct / 0.15) * 50 + 50) if loss_pct > 0 else 25

# Ticker breadth: unique tickers / universe size
ticker_count = COUNT(DISTINCT ticker) FROM training_examples
ticker_score = min(100, (ticker_count / 100) * 100)  # S&P 100 universe

diversity_score = (regime_score + outcome_score + ticker_score) / 3
```

#### 3c. Freshness (25% of data asset score)
```python
# % of training set created or validated in last 90 days
total = COUNT(*) FROM training_examples
fresh = COUNT(*) FROM training_examples WHERE created_at > 90_days_ago
freshness_pct = fresh / total if total > 0 else 0
freshness_score = freshness_pct * 100
```

#### Combined data asset value:
```python
data_asset_value = (quality_score * 0.40) + (diversity_score * 0.35) + (freshness_score * 0.25)
```

### 4. Model Quality (weight: equal)

**What it measures:** Is the LLM producing useful output, not falling back to templates?

**Computation:**
```python
# 7-day rolling fallback rate
fb = SELECT SUM(llm_total - COALESCE(llm_success, 0)) AS failures,
            SUM(llm_total) AS total
     FROM scan_metrics WHERE created_at > 7_days_ago

if fb.total == 0:
    model_quality = 50  # No data, neutral
else:
    fallback_rate = fb.failures / fb.total
    model_quality = max(0, (1 - fallback_rate) * 100)
```

| Fallback Rate | Score |
|---|---|
| 0% | 100 |
| 5% | 95 |
| 10% | 90 |
| 20% | 80 |
| 50% | 50 |
| >80% | <20 (critical) |

### 5. Research Velocity (weight: equal)

**What it measures:** Are research findings being implemented? Is the system evolving?

**Computation:**
```python
# Count of research-informed changes implemented this month
# Proxied by: ADR files modified + council parameter changes + config changes
# in the last 30 days

# Simple version: count of git commits with "research" or "decision" in message
# in last 30 days, normalized to 0-100

# Practical version for MVP:
# Track in a research_velocity table:
#   - research_doc_id, finding, implemented (bool), implemented_date
# Score = (implemented_this_month / total_pending) * 100

# Simplest MVP: manual field in System State page, updated weekly
# Until automated: use HSHS Flywheel Velocity dimension as proxy
research_velocity = hshs["dimensions"].get("flywheel_velocity", 50)
```

### 6. Reliability (weight: equal)

**What it measures:** Is the system running without errors?

**Computation:**
```python
# Scan success rate × uptime
scans_attempted = COUNT(*) FROM scan_metrics WHERE created_at > 7_days_ago
scans_succeeded = COUNT(*) FROM scan_metrics WHERE created_at > 7_days_ago
                  AND packet_worthy IS NOT NULL  # scan completed

scan_success_rate = scans_succeeded / scans_attempted if scans_attempted > 0 else 0

# Uptime: expected ~13 scans/day × 5 trading days = 65/week
expected_scans = 65
uptime = min(1.0, scans_attempted / expected_scans)

reliability = (scan_success_rate * 0.6 + uptime * 0.4) * 100
```

---

## Geometric Mean Calculation

```python
import math

def compute_build_score(components: dict) -> float:
    """Compute Build Score as geometric mean of 6 components.
    
    Each component is 0-100. Geometric mean penalizes zeros.
    A score of 0 in any dimension crashes the entire score.
    """
    values = [
        max(1, components["gate_velocity"]),      # Floor at 1 to avoid log(0)
        max(1, components["system_health"]),
        max(1, components["data_asset_value"]),
        max(1, components["model_quality"]),
        max(1, components["research_velocity"]),
        max(1, components["reliability"]),
    ]
    
    # Geometric mean
    log_sum = sum(math.log(v) for v in values)
    geo_mean = math.exp(log_sum / len(values))
    
    return round(min(100, geo_mean), 1)
```

---

## Decay Mechanic

```python
def apply_daily_decay(current_score: float, db_path: str) -> float:
    """Apply 1-point decay if no activity today.
    
    Activity = any of:
    - Closed trades today
    - New training examples today  
    - Scan cycles today
    """
    today = date.today().isoformat()
    
    has_trades = EXISTS(shadow_trades WHERE status='closed' AND DATE(actual_exit_time) = today)
    has_training = EXISTS(training_examples WHERE DATE(created_at) = today)
    has_scans = EXISTS(scan_metrics WHERE DATE(created_at) = today)
    
    if has_trades or has_training or has_scans:
        return current_score  # No decay
    else:
        return max(0, current_score - 1)  # Decay 1 point
```

---

## Database Schema

```sql
CREATE TABLE IF NOT EXISTS build_score_history (
    score_id TEXT PRIMARY KEY,
    score_date TEXT NOT NULL,
    build_score REAL NOT NULL,
    gate_velocity REAL,
    system_health REAL,
    data_asset_value REAL,
    model_quality REAL,
    research_velocity REAL,
    reliability REAL,
    decay_applied INTEGER DEFAULT 0,
    components_json TEXT,  -- Full breakdown for debugging
    created_at TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_build_score_date
    ON build_score_history(score_date);
```

---

## Dashboard Display

**Hero position:** Top of main dashboard, above P&L.

**Compact view:**
- Large number (48px): Build Score with color (green >70, amber >50, red <50)
- Weekly delta badge: "+4 this week" or "-2 this week"
- Phase progress: "5/50 trades · est. 6 weeks to gate"
- Segmented bar showing all 6 components

**Expanded view (tap):**
- Each component with its own progress bar
- Data asset value drills into quality/diversity/freshness
- 7-day trend chart
- Decay indicators (which idle days lost points)

---

## API Endpoint

```
GET /api/build-score
Response:
{
    "build_score": 68.2,
    "delta_7d": +4.1,
    "components": {
        "gate_velocity": 45,
        "system_health": 72,
        "data_asset_value": 61,
        "model_quality": 82,
        "research_velocity": 70,
        "reliability": 90
    },
    "data_asset_detail": {
        "quality": 61,
        "diversity": 55,
        "freshness": 72
    },
    "phase_progress": {
        "current_phase": 1,
        "trades_closed": 5,
        "trades_required": 50,
        "pct_complete": 10,
        "estimated_weeks_remaining": 6
    },
    "decay_today": false,
    "history_7d": [64, 65, 66, 65, 67, 66, 68]
}
```

---

## Implementation Notes

- Compute at 4:30 PM ET daily (after market close, after post-close bracket check)
- Store in `build_score_history` for trend analysis
- The geometric mean with floor of 1 means a zero in any component pulls the score to ~1, not 0
- Research velocity is the hardest to automate — start with HSHS Flywheel Velocity as proxy, add proper tracking in Phase 2
- The data asset value sub-score is the most novel component and the one most directly tied to the moat thesis
