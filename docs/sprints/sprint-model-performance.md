# Sprint: Model Performance Tracking Dashboard

> **Priority:** MEDIUM — closes a gap identified in the 15-algorithm assessment
> **Estimated time:** 2-3 hours CC time
> **Access:** LOCAL
> **Branch:** `feat/model-performance`

> ⚠️ **Read first:** `MASTER.md`, `docs/research/15_Algorithm_Gap_Assessment.md`

---

## The Gap

We track model versions (training stats, holdout scores) and tag every trade with its
model version. But there's no unified view answering: "Is the current model better or
worse than the previous one on LIVE trades?"

**What exists:**
- `model_versions` table — version_id, holdout_score, training stats
- `shadow_trades.model_version` column — every trade tagged
- `_compute_by_model_version()` in CTO report — trades/WR/expectancy per version
- Champion-challenger in trainer.py — holdout evaluation before promotion

**What's missing:**
- No dashboard page showing live performance per model version over time
- No Sharpe/PF/DD breakdown per model (CTO report only shows WR + expectancy)
- No visual comparison between model versions (side-by-side)
- No automated alert when current model underperforms previous on live trades
- No equity curve per model version

---

## Pre-Flight

1. Read `MASTER.md`
2. `python -m pytest tests/ -x -q` — record baseline
3. Read `src/evaluation/cto_report.py` — find `_compute_by_model_version()`
4. Read `src/schema/registry.py` — find `model_versions` table definition
5. Read `frontend/src/pages/Training.jsx` — current model display

---

## Task 1: Enhanced Model Performance API Endpoint

**Create or add to `src/api/routes/training.py` (or `cloud_routes/training.py`):**

```python
@router.get("/model-performance")
def model_performance():
    """Per-model-version live performance metrics."""
```

This endpoint should return:
```json
{
  "models": [
    {
      "version": "halcyon-v1.0.0",
      "status": "active",
      "created_at": "2026-03-27",
      "training_examples": 979,
      "holdout_score": 0.72,
      "live_metrics": {
        "trades": 18,
        "wins": 12,
        "losses": 1,
        "timeouts": 5,
        "win_rate": 0.667,
        "profit_factor": 2.45,
        "expectancy_dollars": 42.50,
        "sharpe_ratio": 0.85,
        "max_drawdown_pct": 3.2,
        "avg_holding_days": 4.7,
        "total_pnl_pct": 8.5
      },
      "equity_curve": [
        {"date": "2026-03-27", "cumulative_pnl": 0},
        {"date": "2026-03-28", "cumulative_pnl": 125.50},
        ...
      ]
    }
  ],
  "comparison": {
    "current_vs_previous": {
      "current": "halcyon-v1.0.0",
      "previous": null,
      "sharpe_delta": null,
      "wr_delta": null,
      "verdict": "insufficient_data"
    }
  },
  "canary_comparison": {
    "llm_win_rate": 0.667,
    "canary_win_rate": null,
    "paired_trades": 0,
    "mcnemar_pvalue": null,
    "verdict": "insufficient_data"
  }
}
```

**Implementation:** Query `shadow_trades` JOIN `model_versions`, group by model_version,
compute per-group: WR, PF, Sharpe (from pnl_pct series), max DD, expectancy, equity curve.

Include canary comparison data if `canary_score` column exists in recommendations table.

---

## Task 2: Model Performance Dashboard Page

**Create `frontend/src/pages/ModelPerformance.jsx`:**

### Layout (Bloomberg-style, match the UI sprint aesthetic):

**Section 1: Active Model Summary** (top, full width)
- Model name, version, created date, training examples, holdout score
- Status badge (active/retired/testing)
- Days in production, trades generated

**Section 2: Live Metrics Grid** (6-8 KPIs)
- Trades, WR, PF, Sharpe, DD, Expectancy, Avg Hold, Total P&L
- All monospace, green/red for P&L, compared against previous version with delta arrows

**Section 3: Per-Model Comparison Table**
- One row per model version
- Columns: Version, Status, Trades, WR, PF, Sharpe, DD, Expectancy, Holdout Score
- Sortable. Active model highlighted.

**Section 4: Equity Curve per Model**
- Recharts LineChart with one series per model version
- Different colors per version
- Toggleable via legend

**Section 5: LLM vs Canary** (when data available)
- Side-by-side: LLM conviction vs Canary score, paired trade count
- McNemar test p-value (when n >= 50 paired trades)
- Verdict: "LLM adds value" / "No statistical difference" / "Canary outperforms"

**Data source:** `api.getModelPerformance()` → `GET /model-performance`

---

## Task 3: Route + Sidebar Nav

**In `frontend/src/App.jsx`:**
```jsx
import ModelPerformance from './pages/ModelPerformance'
<Route path="/model-performance" element={<ErrorBoundary><ModelPerformance /></ErrorBoundary>} />
```

**In `frontend/src/components/Layout.jsx`:**
Add to "Intelligence" section (after Attribution):
```jsx
{ to: '/model-performance', icon: Cpu, label: 'Model Perf' },
```

---

## Task 4: Automated Regression Alert

**In `src/evaluation/model_monitor.py` (create):**

```python
def check_model_regression(db_path: str = DB_PATH,
                            min_trades_per_model: int = 10) -> dict:
    """Compare current active model against previous on live trade metrics.
    
    Returns regression alert if current model underperforms previous by
    a meaningful margin (>10% relative decline in Sharpe or win rate).
    """
```

**Wire into the watch loop** as a daily check (e.g., 5 PM ET after market close):
- If current model has 10+ trades AND previous model had 10+ trades
- Compare Sharpe, WR, PF
- If any metric declined by >10% relative, log WARNING
- If Sharpe went negative, log CRITICAL + Telegram alert

**This is a lightweight check** — not the full simulation regression (Task 14 in the
simulation sprint). This monitors LIVE performance, not backtested performance.

---

## Task 5: Render Sync

Add `model_versions` to sync config if not already synced (check `sync_to_postgres`
flag in registry). The performance endpoint queries `shadow_trades` which IS synced,
but model_versions itself may not be.

---

## Verification

```bash
python -m pytest tests/ -x -q
cd frontend && npm run build && cd ..

# API returns data
curl -s localhost:8000/api/model-performance | python -m json.tool | head -20

# Dashboard page loads
# (verify at localhost:5173/model-performance)
```

---

## Commit

```bash
git add src/api/ src/evaluation/model_monitor.py frontend/src/pages/ModelPerformance.jsx \
       frontend/src/App.jsx frontend/src/components/Layout.jsx tests/
git commit -m "feat: model performance tracking dashboard + regression alerts

New /model-performance page: per-model live metrics (WR, PF, Sharpe, DD),
equity curve per version, LLM vs canary comparison, version comparison table.
API endpoint: GET /model-performance with full per-version breakdown.
Automated regression alert: daily check, WARNING if >10% decline, CRITICAL
if Sharpe goes negative.

Closes gap identified in 15-Algorithm Gap Assessment."
```

Do NOT merge to main. Push to `feat/model-performance` only.
