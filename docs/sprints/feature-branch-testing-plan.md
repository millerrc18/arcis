# Feature Branch Testing Plan

> **When:** After CC completes the hotfix merge sprint (v0.14.1 on main)
> **Goal:** Verify each feature branch works before merging to main
> **Environment:** Local — `python -m src.main serve` + `npm run dev`
> **Rule:** NEVER merge a branch that fails any test. Fix on the branch first.

---

## Setup: Sync Every Branch with Main First

After the hotfix sprint lands on main, each feature branch is behind.
Rebase or merge main into each branch before testing:

```powershell
# For each feature branch:
git checkout feat/gap-assessment-top3
git merge main --no-edit
# Resolve any conflicts, then:
git push origin feat/gap-assessment-top3

# Repeat for:
git checkout feat/simulation-engine && git merge main --no-edit && git push origin feat/simulation-engine
git checkout feat/model-performance && git merge main --no-edit && git push origin feat/model-performance
git checkout feat/ui-bloomberg && git merge main --no-edit && git push origin feat/ui-bloomberg
```

---

## Branch 1: feat/gap-assessment-top3

**What it does:** Embedding leakage detection, Bayesian council weights, two-tier ranker RS
**Closes:** #295, #296, #297

### Automated Tests
```powershell
git checkout feat/gap-assessment-top3
python -m pytest tests/ -x -q                        # Full suite passes
python -m pytest tests/test_leakage_detector.py -v   # All leakage tests pass
python -m pytest tests/test_council_aggregation.py -v # All council tests pass
python -m pytest tests/test_ranker.py -v              # All ranker tests pass
cd frontend && npm run build && cd ..                 # Frontend builds
```

### Manual Verification
```powershell
# 1. Leakage detector — does it actually run against real data?
python -c "from src.training.leakage_detector import check_outcome_leakage; print(check_outcome_leakage())"
# Expected: dict with balanced_accuracy, is_leaking, n_examples
# FAIL if: KeyError, ImportError, or returns empty dict

# 2. Embedding leakage — does Ollama endpoint respond?
# (Requires Ollama running with halcyon-v1.0.0 loaded)
python -c "from src.training.leakage_detector import check_embedding_leakage; print(check_embedding_leakage())"
# Expected: dict with balanced_accuracy, leaking (bool), n_examples, cv_scores
# ACCEPTABLE if: returns {"error": "Ollama unavailable"} when Ollama is off
# FAIL if: crashes, hangs, or returns placeholder data

# 3. Council dynamic weights — does it fall back gracefully?
python -c "from src.council.aggregation import compute_dynamic_weights; print(compute_dynamic_weights())"
# Expected: None (falls back to static — not enough vote history yet)
# FAIL if: crashes or returns hardcoded mock weights

# 4. Ranker — does two-tier RS work?
python -c "
from src.ranking.ranker import _score_ticker
# Test WITHOUT sector RS (backward compat)
f = {'trend_state': 'strong_uptrend', 'relative_strength_state': 'strong_outperformer',
     'pullback_depth_pct': -5.0, 'dist_to_sma20_pct': -2.0, 'volume_ratio_20d': 0.7}
print(f'Score without sector RS: {_score_ticker(f)}')
# Expected: 100 (capped)
"
# FAIL if: score is 0, None, or crashes

# 5. Sector ETF mapping — is it complete?
python -c "
from src.universe.sectors import SECTOR_MAP, SECTOR_ETF_MAP, get_sector_etf
from src.universe.sp100 import get_sp100_universe
universe = get_sp100_universe()
unmapped = [t for t in universe if get_sector_etf(t) is None]
print(f'Universe: {len(universe)}, Unmapped: {len(unmapped)}')
if unmapped: print(f'Missing: {unmapped[:10]}')
"
# Expected: 0 unmapped tickers
# FAIL if: >5 unmapped (a few like BRK.B might be edge cases)
```

### Code Quality Checks
```powershell
# Check for stubs, TODOs, placeholders (rule #28)
findstr /s /i "TODO\|FIXME\|placeholder\|stub\|NotImplemented" src\training\leakage_detector.py src\council\aggregation.py src\council\constants.py src\ranking\ranker.py src\universe\sectors.py
# Expected: 0 results (or only pre-existing ones from main)
```

### Success Criteria
- [ ] All pytest tests pass (count >= main baseline)
- [ ] Frontend builds clean
- [ ] Leakage detector runs on real data without crashing
- [ ] Embedding detector gracefully handles Ollama being off
- [ ] Council falls back to static weights when insufficient data
- [ ] Ranker backward-compatible (no sector RS = same scores as before)
- [ ] All S&P 100 tickers mapped to sector ETFs
- [ ] Zero new TODO/FIXME/placeholder comments in changed files

---

## Branch 2: feat/simulation-engine

**What it does:** 13-scenario simulation engine, Monte Carlo, traffic light validation, dashboard page
**New files:** src/simulation/, scripts/simulation_engine.py, frontend/src/pages/Simulation.jsx

### Automated Tests
```powershell
git checkout feat/simulation-engine
python -m pytest tests/ -x -q
python -m pytest tests/test_simulation_engine.py -v   # All simulation tests pass
cd frontend && npm run build && cd ..
```

### Manual Verification
```powershell
# 1. CLI dry run — does it print config without crashing?
python scripts/simulation_engine.py --dry-run
# Expected: prints 13 scenarios, bracket params, cache dir
# FAIL if: ImportError, crash, or prints nothing

# 2. Single scenario — does it actually run?
python scripts/simulation_engine.py --regime low_volatility
# Expected: downloads data (or reads cache), runs pipeline, prints heatmap row
# This will take 5-10 min on first run (no cache), <30 sec on repeat
# FAIL if: crashes, hangs, or produces 0 trades

# 3. Cache — did it actually cache?
dir data\simulation_cache\*.parquet /b | find /c /v ""
# Expected: >0 parquet files
# FAIL if: directory doesn't exist or is empty

# 4. Schema — is simulation_results registered?
python -c "from src.schema.registry import TABLES; print('simulation_results' in TABLES)"
# Expected: True
# FAIL if: False or KeyError

# 5. Results stored in DB?
python -c "
import sqlite3
conn = sqlite3.connect('ai_research_desk.sqlite3')
rows = conn.execute('SELECT COUNT(*) FROM simulation_results').fetchone()
print(f'Simulation results: {rows[0]}')
"
# Expected: >= 1 (from the single scenario run)
# FAIL if: table doesn't exist or 0 rows after running a scenario

# 6. Monte Carlo — does it produce confidence intervals?
python -c "
from src.simulation.monte_carlo import monte_carlo_resample
trades = [{'pnl_dollars': 50}, {'pnl_dollars': -30}, {'pnl_dollars': 75}, {'pnl_dollars': -20}] * 10
result = monte_carlo_resample(trades, n_simulations=100)
print(f'MC median equity: {result[\"median_equity\"]:.0f}')
print(f'MC p95 DD: {result[\"p95_dd\"]:.1f}%')
assert result['p5_equity'] < result['median_equity'] < result['p95_equity']
print('Monte Carlo OK')
"
# FAIL if: assertion fails or crashes

# 7. Dashboard page — does it render?
# Start backend: python -m src.main serve
# Start frontend: cd frontend && npm run dev
# Navigate to http://localhost:5173/simulation
# Expected: page loads, shows results if any exist, or empty state
# FAIL if: blank page, console errors, or 404

# 8. API endpoint — does it return data?
# (With backend running)
curl -s http://localhost:8000/api/simulation/results | python -m json.tool | head -10
# Expected: JSON array of results
# FAIL if: 404 or 500 error
```

### Success Criteria
- [ ] All pytest tests pass
- [ ] Frontend builds clean
- [ ] CLI --dry-run works
- [ ] At least 1 scenario runs end-to-end and produces trades
- [ ] Parquet cache populates correctly
- [ ] simulation_results table exists in schema registry
- [ ] Results persist to database
- [ ] Monte Carlo produces valid confidence intervals (p5 < median < p95)
- [ ] Dashboard page renders at /simulation
- [ ] API endpoint returns data
- [ ] Traffic light validation output shows expected vs actual TL per scenario
- [ ] Zero TODO/FIXME/placeholder in new files

---

## Branch 3: feat/model-performance

**What it does:** Model performance dashboard, per-model metrics API, regression alert
**Note:** This branch has cross-contamination (simulation + UI commits merged in).
May need extra care during testing.

### Automated Tests
```powershell
git checkout feat/model-performance
python -m pytest tests/ -x -q
cd frontend && npm run build && cd ..
```

### Manual Verification
```powershell
# 1. API endpoint — does it return model data?
# (Start backend first)
curl -s http://localhost:8000/api/model-performance | python -m json.tool | head -20
# Expected: JSON with "models" array containing halcyon-v1.0.0 entry
# Each model should have: version, live_metrics (trades, WR, PF, sharpe), equity_curve
# FAIL if: 404, empty models array, or placeholder data

# 2. Are metrics computed from REAL trade data?
python -c "
import sqlite3
conn = sqlite3.connect('ai_research_desk.sqlite3')
trades = conn.execute('SELECT COUNT(*), model_version FROM shadow_trades WHERE status=\"closed\" GROUP BY model_version').fetchall()
print(f'Closed trades by model: {trades}')
"
# Cross-reference with API output — numbers must match
# FAIL if: API shows different numbers than DB

# 3. Dashboard page — does it render?
# Navigate to http://localhost:5173/model-performance
# Expected: page loads, shows model metrics, equity curve renders
# FAIL if: blank page, console errors, or mock data visible

# 4. Regression alert — is it wired to watch loop?
grep -n "model_monitor\|regression\|model_performance" src/scheduler/watch.py
# Expected: at least 1 reference showing it's scheduled
# FAIL if: no references (function exists but isn't called)

# 5. Canary comparison section — honest about data?
# On the dashboard page, check the LLM vs Canary section
# Expected: shows "Insufficient data (N paired trades)" or real comparison
# FAIL if: shows fake comparison data or crashes
```

### Success Criteria
- [ ] All pytest tests pass
- [ ] Frontend builds clean
- [ ] API returns real model data (not placeholders)
- [ ] Metrics match actual database trade counts
- [ ] Dashboard page renders with equity curve
- [ ] Regression alert wired into watch loop
- [ ] Canary comparison honestly reports data availability
- [ ] Sidebar nav entry exists and links correctly
- [ ] Zero TODO/FIXME/placeholder in new files

---

## Branch 4: feat/ui-bloomberg

**What it does:** Bloomberg Terminal aesthetic across all 18 dashboard pages
**Note:** Frontend-only. If not on remote yet, CC may still be working.

### Automated Tests
```powershell
git checkout feat/ui-bloomberg
cd frontend && npm install && npm run build && cd ..
# The ONLY test that matters for a UI sprint is: does it build?
python -m pytest tests/ -x -q   # Backend tests should be unchanged
```

### Manual Verification — Click Through Every Page

Start the dev server: `cd frontend && npm run dev`

**For each of the 18 pages, check:**

| Check | What to look for |
|---|---|
| Page loads | No blank screen, no console errors |
| Data connections | Real data rendering (not "Loading..." stuck or "No data" when data exists) |
| No teal | Zero teal-colored elements anywhere. Blue accent, green/red for P&L only |
| Monospace numbers | Every price, %, count, ratio uses JetBrains Mono |
| Squared corners | No rounded pills or large border-radius elements |
| No shadows | No box-shadow on cards or panels |
| Status bar | Top bar shows LLM status, market state, traffic light, positions, time |
| Dark mode | Fully styled, near-black background |
| Light mode | Fully styled, professional |

**Page-by-page quick check:**
```
Dashboard        — KPIs render, equity curve shows, activity feed works
ShadowLedger     — Trade table loads, P&L colored, sortable
CTOReport        — Report generates, sections render, metrics display
Roadmap          — Progress bars blue (not teal), gate metrics show
LiveLedger       — Live trades render (or empty state if none)
Council          — Council history loads, vote display works
Health           — HSHS score renders, dimensions show
Training         — Training status, version history
Validation       — Validation results display
StressTest       — Stress test results render, charts work
Attribution      — Attribution data or empty state
Settings         — Config loads, toggles work
Logs             — Log viewer loads, scrollable
Notes            — Notes render, editable
Docs             — Doc list loads, viewer works
Packets          — Packet list renders
Architecture     — Diagram displays
DBSchema         — Schema tables list
```

### Success Criteria
- [ ] Frontend builds with zero errors
- [ ] Backend tests unchanged (no backend files modified)
- [ ] All 18 pages load without console errors
- [ ] All data connections render real data
- [ ] Zero teal visible on any page (grep confirms: `grep -r "teal" frontend/src/ | wc -l` = 0)
- [ ] Status bar visible and showing live data
- [ ] Monospace on all numeric values
- [ ] Dark mode fully styled
- [ ] Light mode fully styled
- [ ] Agent auditor scored every page >= 9.0/10

---

## Merge Order After All Tests Pass

```powershell
git checkout main && git pull origin main

# 1. Gap assessment (smallest, highest priority)
git merge feat/gap-assessment-top3 --no-ff
python -m pytest tests/ -x -q && cd frontend && npm run build && cd ..
git push origin main

# 2. Bloomberg UI (frontend-only, no conflicts with #1)
git merge feat/ui-bloomberg --no-ff
cd frontend && npm run build && cd ..
python -m pytest tests/ -x -q
git push origin main

# 3. Simulation engine (adds new files, minor Layout.jsx conflict)
git merge feat/simulation-engine --no-ff
# If conflict in Layout.jsx or App.jsx: keep both route/nav additions
python -m pytest tests/ -x -q && cd frontend && npm run build && cd ..
git push origin main

# 4. Model performance (adds new files, minor Layout.jsx conflict)
git merge feat/model-performance --no-ff
# If conflict in Layout.jsx or App.jsx: keep both route/nav additions
python -m pytest tests/ -x -q && cd frontend && npm run build && cd ..
git push origin main

# Tag
git tag -a v0.15.0 -m "v0.15.0 — 4 feature sprints: gap assessment, simulation engine, model performance, Bloomberg UI"
git push origin main --tags

# Cleanup
git branch -d feat/gap-assessment-top3 feat/simulation-engine feat/model-performance feat/ui-bloomberg
git push origin --delete feat/gap-assessment-top3 feat/simulation-engine feat/model-performance feat/ui-bloomberg
```

---

## If a Branch Fails Testing

**Do NOT merge it.** Fix on the branch:

```powershell
git checkout feat/broken-branch
# Fix the issue
git add -A && git commit -m "fix: [description of what was wrong]"
git push origin feat/broken-branch
# Re-test from the top of that branch's test plan
```

If the fix is non-trivial, fire CC on the branch:
```
You are on branch feat/broken-branch. The following test failed: [paste the failure].
Fix it, verify all tests pass, and push to the feature branch.
```
