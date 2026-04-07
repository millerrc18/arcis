# CC Orientation: Simulation Engine Sprint — Full System Context

Copy this entire block into the CC terminal that will run the simulation engine sprint.

---

```
## System Context — Read This First

You are one of 4 CC agents working in parallel on the Arcis autonomous equity trading system.
Here is the full plan so you understand where your work fits:

### The 4 Parallel Sprints

| # | Branch | Sprint File | What It Does | Status |
|---|--------|-------------|--------------|--------|
| 1 | feat/gap-assessment-top3 | docs/sprints/sprint-gap-assessment-top3.md | Embedding leakage detection, Bayesian council weights, two-tier ranker RS | IN PROGRESS |
| 2 | feat/simulation-engine | docs/sprints/sprint-simulation-engine.md | **YOUR SPRINT** — 13-regime simulation engine with Monte Carlo, traffic light validation, dashboard page | YOUR JOB |
| 3 | feat/ui-bloomberg | docs/sprints/sprint-ui-bloomberg.md | Bloomberg Terminal UI overhaul on all 18 dashboard pages | IN PROGRESS |
| 4 | feat/model-performance | docs/sprints/sprint-model-performance.md | Model performance tracking dashboard + regression alerts | QUEUED |

### File Ownership — Avoid These Files

Other agents are modifying these files. Do NOT touch them:
- **Gap assessment owns:** src/training/leakage_detector.py, src/council/*.py, src/ranking/ranker.py, src/universe/sectors.py
- **Bloomberg UI owns:** ALL files in frontend/src/ that already exist (it's restyling every page)

Your sprint CREATES new files that don't conflict:
- src/simulation/cache.py (NEW)
- src/simulation/monte_carlo.py (NEW)
- src/simulation/__init__.py (NEW)
- scripts/simulation_engine.py (NEW)
- frontend/src/pages/Simulation.jsx (NEW — the UI sprint won't know about this page)
- tests/test_simulation_engine.py (NEW)

You DO touch these shared files (coordinate carefully):
- src/schema/registry.py — ADD simulation_results table definition
- src/api/routes/system.py — ADD /simulation/results endpoint
- src/api/routes/actions.py — ADD simulation command handler
- src/scheduler/watch.py — ADD weekly simulation scheduling
- frontend/src/App.jsx — ADD /simulation route
- frontend/src/components/Layout.jsx — ADD sidebar nav entry

### Merge Order After All Sprints Complete

1. Gap assessment merges first (v0.15.0)
2. UI merges second
3. YOUR sprint merges third (v0.16.0)
4. Model performance merges last

This means your additions to Layout.jsx and App.jsx will be merged on top of
the UI sprint's changes. Keep your additions minimal (just add the route and nav item).

### What Your Sprint Delivers

The simulation engine answers the allocator's question: "In which market conditions
does this strategy make money, break even, or bleed?"

13 scenarios across ALL market conditions:
- 10 pure regimes: strong bull, euphoric bull, low vol, high vol, sideways chop, sector rotation, rate hiking, rate cutting, V-recovery, grinding bear
- 3 transitions: bull→bear, bear→bull, low→high vol

Key outputs:
- Regime heatmap (edge/neutral/marginal/bleeds per regime)
- Monte Carlo confidence intervals (1,000 reshuffles)
- SPY benchmark comparison
- Transaction cost model (9 bps round-trip)
- Traffic light validation (did our regime detection get it right?)
- Dashboard page with heatmap, equity curves, TL scorecard
- Weekly auto-run via watch loop (Sunday 10 PM ET)
- Post-retrain auto-trigger for regression detection

### Your 14 Tasks

Read docs/sprints/sprint-simulation-engine.md for full details:
1. Data cache layer (parquet)
2. Core simulation engine (13 scenarios, real pipeline)
3. Monte Carlo module
4. Verdict logic + heatmap output
5. Traffic light validation
6. Schema + storage
7. Reproducibility
8. CLI entrypoint
9. API endpoint + dashboard wiring
10. Render sync
11. Dashboard page (Simulation.jsx)
12. Route + sidebar nav
13. Watch loop scheduling
14. Post-retrain auto-trigger + command queue

### Now Execute

First, check out your feature branch:

git checkout main
git pull origin main
git checkout -b feat/simulation-engine

Then read the full sprint:

Read docs/sprints/sprint-simulation-engine.md and execute all 14 tasks.

Rules:
- Do NOT merge to main. Push to feat/simulation-engine only.
- Follow the 3× Ralph Loop protocol for each major deliverable.
- Run the full test suite before and after. Pass count must not decrease.
- Frontend must build: cd frontend && npm run build
- Update MASTER.md and RELEASES.md.
- Push to feature branch when complete.
```
