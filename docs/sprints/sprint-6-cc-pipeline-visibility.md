# Sprint 6: Data Pipeline Visibility (Claude Code)

> **Executor:** Claude Code
> **Scope:** 7 tasks
> **Prerequisite:** Sprint 5 MERGED
> **Read first:** AGENTS.md, docs/conventions.md
> **Context:** The backend has API endpoints for data collection stats and training pipeline status, but the frontend never calls them. Ryan can't see if collectors are running or if training data is growing. All tasks are frontend-only except wiring api.js methods. The backend APIs already exist.
> **Test baseline:** 1,110 tests. Must not decrease.

---

## Existing Backend APIs (already built — DO NOT modify)

```
GET /api/data-collection-stats
  → Returns: { table_name: { total_records, latest_collection, coverage_count } }
  → Tables: options_chains, options_metrics, vix_term_structure, cboe_ratios,
            macro_snapshots, google_trends, earnings_calendar, sec_filings,
            insider_transactions, research_docs, analyst_estimates, short_interest

GET /api/training/status
  → Returns: { dataset_size, model_version, model_status, holdout_score,
               format_compliance: { xml, plain_text }, 
               quality: { avg_process_score, leakage_accuracy },
               quadrant_distribution: { good_good, good_bad, bad_good, bad_bad } }

GET /api/training/history
  → Returns: array of training runs with model_version, example_count, created_at

GET /api/scan/metrics
  → Returns: recent scan metrics (packet_worthy, llm_success, llm_total, avg_conviction)

GET /api/costs
  → Returns: API cost tracking (council sessions, training runs)
```

Verify these endpoints exist and what they return before building:
```bash
grep -n "data-collection-stats\|training/status\|training/history\|scan/metrics\|/costs" src/api/cloud_routes/*.py
```

---

## Pre-Sprint Checks (MANDATORY)

```bash
find src -name "*.py" ! -path "*__pycache__*" -exec sh -c 'lines=$(wc -l < "$1"); if [ "$lines" -gt 400 ]; then echo "VIOLATION: $1 ($lines lines)"; fi' _ {} \;
python3 -c "
import ast, pathlib
for p in pathlib.Path('src').rglob('*.py'):
    try:
        tree = ast.parse(p.read_text())
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                length = node.end_lineno - node.lineno
                if length > 60: print(f'VIOLATION: {p}:{node.name} ({length} lines)')
    except: pass
"
find tests -name "test_*.py" -exec grep -c "def test_" {} + | awk -F: '{s+=$2}END{print "Tests:", s}'
# Must be ≥ 1110
cd frontend && npm run build && cd ..
```

---

## Task 1: Wire API Methods in api.js

Add methods for the endpoints the frontend doesn't use yet:

```javascript
getDataCollectionStats: () => fetchApi('/data-collection-stats'),
getTrainingStatus: () => fetchApi('/training/status'),
getTrainingHistory: () => fetchApi('/training/history'),
getScanMetrics: (limit = 20) => fetchApi(`/scan/metrics?limit=${limit}`),
getCosts: () => fetchApi('/costs'),
```

Verify these don't already exist before adding (Sprint 4B/5 may have added some).

---

## Task 2: Data Collectors Grid on Training Page

Add a "Data Collectors" section to `frontend/src/pages/Training.jsx`:

**Layout:** Grid of 12 collector cards (3 columns desktop, 2 mobile, 1 on small mobile)

Each card shows:
- **Collector name** (e.g., "VIX Term Structure", "Options Chains", "Macro Snapshots")
- **Row count** (total_records) in `className="financial-data"`
- **Freshness indicator:**
  - 🟢 Green dot: latest_collection is today or yesterday
  - 🟡 Yellow dot: latest_collection is 2-7 days ago
  - 🔴 Red dot: latest_collection is >7 days ago or null
- **Last collected:** relative date ("2h ago", "yesterday", "3 days ago")
- **Coverage:** coverage_count if relevant (e.g., "102 tickers" for options)

**Data source:** `getDataCollectionStats()` with `useQuery` and 5-minute refetch interval (collectors run overnight, no need for frequent polling)

**Friendly names mapping:**
```javascript
const COLLECTOR_NAMES = {
  options_chains: "Options Chains",
  options_metrics: "Options Metrics",
  vix_term_structure: "VIX Term Structure",
  cboe_ratios: "CBOE Put/Call Ratios",
  macro_snapshots: "FRED Macro Data",
  google_trends: "Google Trends",
  earnings_calendar: "Earnings Calendar",
  sec_filings: "SEC EDGAR Filings",
  insider_transactions: "Insider Transactions",
  research_docs: "Research Docs",
  analyst_estimates: "Analyst Estimates",
  short_interest: "Short Interest",
};
```

---

## Task 3: Training Pipeline Status on Training Page

Add a "Training Pipeline" section to Training.jsx above or below the existing training examples section:

**Layout:**
1. **Active model card:** Large display of current model name + status badge (active/evaluation/previous). Show holdout_score if available.
2. **Pipeline readiness indicators:**
   - Unscored examples remaining (total - scored)
   - Auto-scoring progress bar (scored / total, with percentage)
   - Average quality score (from quality_score_auto)
   - Class balance bar (WIN % / LOSS % / other) — compare to v2 targets (40/25/5/15)
3. **Format compliance:** XML vs plain_text count
4. **Leakage test:** Show latest balanced accuracy + status (OK/MARGINAL/LEAKING)
5. **Quadrant distribution:** Small 2×2 grid showing good_process/good_outcome counts

**Data source:** `getTrainingStatus()` with `useQuery` and 60s refetch

---

## Task 4: Model History on Health Page

Add a "Model History" section to `frontend/src/pages/Health.jsx` below the Build Score:

**Layout:** Timeline or table showing:
- Model version name
- Status (active/evaluation/previous/rejected) with colored badge
- Training example count at time of training
- Holdout score (if available)
- Created date
- Promotion/rejection date (if applicable)

**Data source:** `getTrainingHistory()` with `useQuery` and 5-minute refetch

When there's only 1 model (current state), show a single card with "First model — no comparisons yet. Next model will be trained after more closed trades accumulate."

---

## Task 5: Scan Metrics Trend on Dashboard

Add a small scan metrics sparkline or summary to the main Dashboard page:

**Layout:** Below the existing sections, add:
- **Today's scans:** X scans, Y packets generated, Z LLM successes
- **7-day trend sparkline:** Recharts tiny LineChart showing daily scan counts
- **LLM success rate:** percentage with color (green >90%, yellow 70-90%, red <70%)

**Data source:** `getScanMetrics(50)` with `useQuery` and 60s refetch. Aggregate by day for the sparkline.

---

## Task 6: Fix KPI Card Contrast on Dashboard

**Problem:** KPI cards and the dashboard background are both so dark they blend together — everything looks like one black surface. Cards need visible separation from the background.

**Fix across ALL pages that use cards (Dashboard, Health, Training, Settings, CTO Report):**

1. **Card background:** Change from `var(--arcis-bg-surface)` (#0C0C10) to `var(--arcis-bg-elevated)` (#12121A). This gives a subtle but visible lift above the background (#050507).
2. **Card border:** Add `border: 1px solid var(--arcis-border)` (rgba blue, 8% opacity). Subtle but provides edge definition.
3. **Card shadow (dark mode only):** Add `box-shadow: 0 1px 3px rgba(0,0,0,0.4)` for depth perception.
4. **Section headers:** Ensure section titles above card groups use `var(--arcis-text-secondary)` — not muted, not primary. They need to be visible but not dominant.
5. **Hover state on interactive cards:** On hover, lighten the border to `var(--arcis-border-hover)` (rgba blue, 15% opacity).
6. **Light mode check:** Verify these changes look good in light mode too — light mode already has better contrast, so the changes should be subtle or no-op there.

**Create a shared CSS class** (e.g., `.arcis-card`) in `index.css` so all pages use the same card styling:
```css
.arcis-card {
  background: var(--arcis-bg-elevated);
  border: 1px solid var(--arcis-border);
  border-radius: 8px;
  padding: 16px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.4);
  transition: border-color 0.15s ease;
}
.arcis-card:hover {
  border-color: var(--arcis-border-hover);
}
[data-theme="light"] .arcis-card {
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.08);
}
```

Apply `.arcis-card` to every card/panel across all dashboard pages. This creates consistency and makes future styling changes a single-line CSS update.

---

## Task 7: Documentation Update (MANDATORY)

Run verification from `docs/sprint-checklist.md`. Update:
- AGENTS.md counts
- CHANGELOG.md (Sprint 6 entry)

```bash
python -m pytest tests/ -x -q
cd frontend && npm run build && cd ..
find tests -name "test_*.py" -exec grep -c "def test_" {} + | awk -F: '{s+=$2}END{print "Tests:", s}'
```

Paste and complete sprint checklist.

---

## Design Notes

- All new sections use `var(--arcis-*)` CSS variables. No hardcoded colors.
- Financial numbers in `className="financial-data"` (JetBrains Mono)
- Mobile-first: collector grid collapses to single column on small screens
- Freshness indicators use `var(--arcis-success)`, `var(--arcis-warning)`, `var(--arcis-danger)`
- Empty states: when a collector has 0 records, show "No data collected yet" not a blank card
- All `useQuery` hooks should have appropriate refetch intervals (not too frequent — these are background processes, not real-time data)
