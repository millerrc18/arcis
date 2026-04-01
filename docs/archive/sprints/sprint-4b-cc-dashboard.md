# Sprint 4B: Dashboard Logic & Redesign (CC)
# Complex component work — Build Score, page redesigns, data wiring.
# Fire to CC. Fresh session. After Sprint 4A (Codex) merges.

> **CONTEXT:** Arcis (formerly Halcyon Lab) is an autonomous AI-powered equity
> trading system. Sprint 4A just completed the brand rename and theme infrastructure
> (Palette B: deep indigo + teal + cyan, Inter + JetBrains Mono, dark/light toggle).
> All CSS variables are defined. All API stubs exist. This sprint implements the
> actual computation logic and redesigns the dashboard pages.
>
> **PALETTE B (applied by Sprint 4A):**
> - Background: #0B1120 (dark), #F0FDFA (light)
> - Surface: #141B2D (dark), #FFFFFF (light)
> - Primary: #14B8A6 (teal)
> - Accent: #06B6D4 (cyan)
> - Secondary: #1E1B4B (deep indigo)
> - Text: #ECFDF5 (dark), #134E4A (light)
> - All colors available as CSS variables: var(--color-primary), var(--bg-surface), etc.
>
> **BUILD SCORE SPEC:** docs/research/Build_Score_Specification__Composite_KPI.md
>
> **DASHBOARD PRIORITY (phone-first, in order):**
> 1. Build Score + P&L + HSHS ("how am I doing?")
> 2. Council direction + confidence ("what does the AI think?")
> 3. Traffic Light + Event Risk ("is it safe to trade today?")
> 4. Positions + Bracket Health ("are positions protected?")
>
> **RULES:**
> - ≤10 tasks. No scope expansion.
> - Use CSS variables (var(--*)) for ALL colors — no hardcoded hex.
> - Use var(--font-mono) for all financial data (prices, P&L, tickers).
> - ▲/▼ arrows mandatory alongside green/red for colorblind accessibility.
> - Mobile-first: design for 420px viewport, scale up for desktop.
> - Run verify_counts.py at the end.

---

## Pre-read (mandatory):
```
cat docs/research/Build_Score_Specification__Composite_KPI.md
cat frontend/src/theme.css
cat frontend/src/pages/Dashboard.jsx
cat frontend/src/pages/ShadowLedger.jsx
cat frontend/src/pages/Council.jsx
cat frontend/src/pages/Health.jsx
cat frontend/src/api.js
cat src/api/cloud_routes/analytics.py
cat src/evaluation/hshs_live.py
cat src/features/traffic_light.py
cat src/features/event_risk_score.py
cat src/shadow_trading/bracket_monitor.py
cat src/council/value_tracker.py
```

**Run before starting:** `python -m pytest tests/ -x -q`

---

## Task 1: Build Score computation module

Create `src/evaluation/build_score.py`:

```python
"""Build Score — single composite KPI (0-100) for system progress.

Called by: cloud_routes/analytics.py (GET /api/build-score)
Calls: sqlite3, hshs_live.py
"""
```

Implement EXACTLY per the spec in docs/research/Build_Score_Specification__Composite_KPI.md:

**6 components, geometric mean:**
1. Gate velocity: closed trades this week / target weekly rate
2. System health: HSHS composite (direct)
3. Data asset value: quality (40%) × diversity (35%) × freshness (25%)
4. Model quality: 100 - (fallback_rate × 100)
5. Research velocity: HSHS flywheel_velocity as proxy
6. Reliability: scan success rate × uptime

**Decay:** -1 point per idle day (no trades, no training examples, no scans).

**DB table:**
```sql
CREATE TABLE IF NOT EXISTS build_score_history (
    score_id TEXT PRIMARY KEY,
    score_date TEXT NOT NULL UNIQUE,
    build_score REAL NOT NULL,
    gate_velocity REAL, system_health REAL, data_asset_value REAL,
    model_quality REAL, research_velocity REAL, reliability REAL,
    decay_applied INTEGER DEFAULT 0,
    components_json TEXT,
    created_at TEXT NOT NULL
);
```

**Functions:**
- `compute_build_score(db_path) -> dict` — computes all 6 components + geometric mean
- `store_daily_score(db_path)` — called at 4:30 PM ET, stores to build_score_history
- `get_build_score_api(db_path) -> dict` — returns current score + 7-day history for API

**Tests:** 5+ tests covering component computation, geometric mean, decay, empty DB handling.

## Task 2: Wire Build Score API endpoint

Replace the stub in `src/api/cloud_routes/analytics.py`:
```python
@router.get("/api/build-score")
async def build_score():
    from src.evaluation.build_score import get_build_score_api
    return get_build_score_api()
```

Wire the daily computation into `watch.py` at 4:30 PM ET alongside post-close bracket check.

## Task 3: Wire Traffic Light API endpoint

Replace the stub:
```python
@router.get("/api/traffic-light/current")
async def traffic_light_current():
    # Query traffic_light_state table directly
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM traffic_light_state WHERE id = 1").fetchone()
    if not row:
        return {"regime": "UNKNOWN", "score": 0}
    return {"regime": row["current_regime"], "score": row["last_total_score"]}
```

## Task 4: Redesign Dashboard.jsx — "The Glance"

Complete rewrite of the main dashboard page. Mobile-first (420px).

**Layout (top to bottom):**

1. **Build Score hero card** (full width):
   - Large number (32px, var(--color-primary), font-weight 700)
   - Weekly delta badge (+4 / -2)
   - Phase progress: "5/50 trades · ~6 wks to gate"
   - 6-component segmented bar (thin horizontal bar, each segment proportional)
   - Component labels below bar (10px, var(--text-dim))

2. **P&L + Stats row** (2-column grid):
   - Left: Total P&L (large number, var(--profit) or var(--loss)), today + week below
   - Right: Win rate (large %) + W/L count + expectancy per trade

3. **Equity curve** (full width):
   - Recharts AreaChart with 1W/1M/ALL toggle
   - Line color: var(--color-primary)
   - Fill: var(--color-primary) at 10% opacity
   - Baseline reference line at starting equity

4. **Council (compact, expandable)**:
   - Single line: "Council" label + direction badge (bullish/neutral/bearish) + consensus + confidence
   - Expand (click) → 5 agent pills with direction + reasoning preview

5. **Traffic Light + Event Risk** (2-column grid):
   - Left: regime dot + name + score
   - Right: event score + next event label

6. **Positions (compact)**:
   - Open count + green count + red count + "Brackets OK" badge
   - Best/worst tickers with P&L

7. **Activity feed** (last 5 items):
   - Timestamp + action description
   - Compact single-line format

**Data sources:**
- GET /api/build-score
- GET /api/shadow/account
- GET /api/shadow/open
- GET /api/shadow/closed
- GET /api/traffic-light/current
- GET /api/council/latest
- GET /api/health/hshs

Use React Query with 60-second refetch for all except Build Score (300-second).

## Task 5: Add IS tracking columns to ShadowLedger.jsx

Add three new columns to the trade table:
- `strategy_type` — pullback/mean_reversion/pead (text badge)
- `signal_price` → `fill_price` with IS bps (formatted as "+2.3 bps" or "-1.1 bps")
- `days_held` / `timeout_days` displayed as "3/7" with progress indicator

Use var(--font-mono) for all price and bps values.
Color IS bps: green if negative (good execution), red if positive (slippage cost).

## Task 6: Update Council.jsx for Palette B

Sprint 4A renamed agents and applied theme variables. This task adds:
- Parameter adjustments section: table showing previous → recommended → applied
- Value attribution summary (if data exists from GET /api/council/value-summary)
- Strategic question input: text field + "Ask Council" button
- Session history: expandable list of recent sessions with timestamps + direction

## Task 7: Update Health.jsx — Build Score integration

Add Build Score to the Health page alongside existing HSHS radar:
- Build Score trend chart (7-day and 30-day)
- Component breakdown with progress bars (expandable)
- Data asset value detail: quality / diversity / freshness sub-bars
- Decay indicators (which days lost points)

## Task 8: Colorblind accessibility pass

Across ALL pages, verify:
- Every green/red indicator also has ▲/▼ arrows or text labels
- Traffic Light regime states include text: "RISK-ON", "CAUTION", "RISK-OFF"
- P&L always shows +$amount or -$amount (not just color)
- Chart tooltips include directional text, not just color

## Task 9: All tests pass + frontend builds + verify_counts

```bash
python -m pytest tests/ -v --tb=short
cd frontend && npm run build && cd ..
python scripts/verify_counts.py
```

## Task 10: Documentation update

- AGENTS.md: updated counts
- CHANGELOG.md: Sprint 4B entry (Build Score, dashboard redesign, IS tracking, accessibility)
- docs/architecture.md: add build_score.py module, new API endpoints

---

# Sprint Documentation Checklist

### Tier 1 (MANDATORY):
- [ ] AGENTS.md counts match
- [ ] CHANGELOG.md entry
- [ ] Build Score module + tests
- [ ] Dashboard.jsx redesigned with all 7 sections
- [ ] All financial data uses var(--font-mono)
- [ ] All colors use CSS variables
- [ ] ▲/▼ arrows on all P&L indicators
- [ ] All tests pass
- [ ] Frontend builds
- [ ] verify_counts.py passes
