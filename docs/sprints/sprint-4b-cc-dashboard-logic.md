# Sprint 4B: Dashboard Logic & Redesign (Claude Code)

> **Executor:** Claude Code (complex logic, multiple data sources, React component design)
> **Prerequisite:** Sprint 4A MUST be merged first (brand, palette, fonts, toggle are in place)
> **Estimated scope:** 8 tasks
> **Codebase guardrails:** No src/ file over 400 lines. No function over 60 lines. Run checks BEFORE starting.

## Context

You are working on Arcis (formerly halcyon-lab), an autonomous AI-powered equity trading system.
Sprint 4A has already been merged — the codebase is rebranded to Arcis, Palette H (Electric Focus)
is applied, Inter + JetBrains Mono fonts are loaded, and dark/light toggle is wired.

The dashboard at halcyonlab.app needs its main pages redesigned to surface data that exists
in the backend but isn't shown to the user. The Build Score is a new composite KPI that needs
both a backend computation module and a frontend display.

**Key reference docs:**
- `docs/research/Build_Score_Specification__Composite_KPI.md` — full Build Score spec
- `docs/research/Brand_Identity_System__AI_Trading_Platform.pdf` — typography hierarchy, dashboard layout spec
- `docs/research/Hardware_Deployment_Strategy__Multi-Desk_GPU_Roadmap.pdf` — hardware context
- Notion Dashboard Redesign page — priority ranking, page-by-page redesign spec

**Dashboard priority ranking (what Ryan sees first on phone):**
1. P&L + Build Score ("how am I doing overall?")
2. Council direction + confidence ("what does the AI think?")
3. Traffic Light + event risk ("is it safe to trade today?")
4. Open positions + bracket health ("are my positions protected?")

**Palette H (already applied by Sprint 4A):**
- Dark: Background #050507, Surface #0C0C10, Accent #3B82F6, Text #E4E4E7
- Light: Background #F8FAFC, Surface #FFFFFF, Accent #2563EB, Text #0F172A
- Use CSS custom properties: `var(--arcis-accent)`, `var(--arcis-bg-surface)`, etc.

## Pre-sprint checks

Run these BEFORE starting any tasks:

```bash
# File size guardrail
find src -name "*.py" ! -path "*__pycache__*" -exec sh -c 'lines=$(wc -l < "$1"); if [ "$lines" -gt 400 ]; then echo "VIOLATION: $1 ($lines lines)"; fi' _ {} \;

# Function length guardrail
python3 -c "
import ast, pathlib
for p in pathlib.Path('src').rglob('*.py'):
    try:
        tree = ast.parse(p.read_text())
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                length = node.end_lineno - node.lineno
                if length > 60:
                    print(f'VIOLATION: {p}:{node.name} ({length} lines)')
    except: pass
"

# Verify Sprint 4A was merged (Arcis branding should exist)
grep -r "ARCIS\|Arcis" frontend/src/App.jsx | head -3

# Current test count
find tests -name "test_*.py" -exec grep -c "def test_" {} + | awk -F: '{s+=$2}END{print "Tests:", s}'
```

Fix any violations BEFORE starting feature work.

---

## Tasks

### Task 1: Build Score computation module

Create `src/evaluation/build_score.py` following the spec in `docs/research/Build_Score_Specification__Composite_KPI.md`.

**6 components, geometric mean:**
1. **Gate velocity:** closed trades this week / target weekly rate (50 trades / 26 weeks)
2. **System health:** HSHS composite score (from `src/evaluation/hshs_live.py`)
3. **Data asset value:** quality (40%) + diversity (35%) + freshness (25%)
   - Quality: avg quality_score of training examples created in last 30 days, normalized 0-100
   - Diversity: regime coverage + outcome balance + ticker breadth, averaged
   - Freshness: % of training set created in last 90 days
4. **Model quality:** 100 - (7-day fallback rate × 100)
5. **Research velocity:** proxy from HSHS Flywheel Velocity dimension
6. **Reliability:** (scan success rate × 0.6 + uptime ratio × 0.4) × 100

**Decay:** -1 point per idle day (no trades closed AND no training examples AND no scans).

**DB table:** `build_score_history` (score_id, score_date, build_score, all 6 components, decay_applied, components_json, created_at)

Create `init_build_score_tables()`, `compute_build_score(db_path)`, and `apply_daily_decay(db_path)`.

Write tests in `tests/test_build_score.py` (≥10 tests covering each component, geometric mean, decay, edge cases).

### Task 2: Build Score API endpoint (replace stub)

Replace the stub from Sprint 4A in `src/api/cloud_routes/analytics.py` with the real implementation:

```
GET /api/build-score → {
    build_score, delta_7d, components: {gate_velocity, system_health, data_asset_value,
    model_quality, research_velocity, reliability}, data_asset_detail: {quality, diversity, freshness},
    phase_progress: {current_phase, trades_closed, trades_required, pct_complete, estimated_weeks},
    decay_today, history_7d: [scores]
}
```

Also implement `GET /api/traffic-light/current` (replace stub):
Query `traffic_light_state` table for current regime, score, and VIX from `vix_term_structure`.

Wire into `frontend/src/api.js`.

### Task 3: Dashboard main page redesign — "The Glance"

Redesign `frontend/src/pages/Dashboard.jsx` with this layout (mobile-first, top to bottom):

1. **Build Score hero** — large number (32px), weekly delta badge, component bar
2. **P&L + Stats row** — 2-column grid: total P&L (today/week/all) | win rate + expectancy
3. **Equity curve** — Recharts AreaChart, 1W/1M/ALL toggle
4. **Council compact** — direction badge + consensus + confidence, expandable
5. **Traffic Light + Event Risk** — 2-column: regime dot + score | event score + next event
6. **Positions compact** — open/green/red counts + bracket status badge
7. **Activity feed** — last 3-5 system actions with timestamps

Use CSS variables from Palette H. Financial data in JetBrains Mono with `tabular-nums`.
All P&L must include ▲/▼ arrows alongside green/red for colorblind accessibility.

### Task 4: ShadowLedger additions

Add columns to `frontend/src/pages/ShadowLedger.jsx`:
- `strategy_type` — pill badge (pullback, mean_reversion, pead)
- `signal_price` vs `fill_price` — IS tracking with bps displayed
- `implementation_shortfall_bps` — colored by magnitude
- Days held vs timeout — progress bar showing 3/7 days

These columns already exist in the backend (`shadow_trades` table). Wire them through the API.

### Task 5: Council page redesign

Redesign `frontend/src/pages/Council.jsx`:
- 5 agent cards with v2 names and direction badges (bullish/neutral/bearish)
- Consensus visualization (horizontal bar showing vote distribution)
- Parameter adjustment history table (from `council_parameter_log`)
- Strategic question input form
- Session history timeline (from `council_sessions`)
- Value attribution summary when data exists (from `compute_attribution()`)

### Task 6: Health page — Build Score integration

Update `frontend/src/pages/Health.jsx`:
- Add Build Score display at top (hero number + 7-day trend sparkline)
- Keep existing HSHS radar chart
- Add Build Score component breakdown bars
- Add data asset value detail (quality/diversity/freshness bars)
- Add scan success rate trend (7-day rolling)
- Add fallback rate trend (7-day rolling)

### Task 7: Render sync for new tables

Update `src/sync/render_sync.py` and `scripts/render_migrate.py` to sync:
- `build_score_history` table
- Any new columns added to existing synced tables

### Task 8: Documentation update (MANDATORY)

- Update AGENTS.md with all current counts (run verification commands)
- Update CHANGELOG.md with Sprint 4B entry
- Update architecture.md with Build Score module, new API endpoints
- Verify all counts match code reality

---

## Sprint Checklist (MANDATORY)

Paste the contents of `docs/sprint-checklist.md` here and complete every applicable item.
Run all verification commands before marking the sprint complete.
