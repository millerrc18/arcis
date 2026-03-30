# Sprint 4B: Dashboard Logic & Redesign

> **Executor:** Claude Code
> **Scope:** 9 tasks | Build Score module + dashboard redesign + page updates + .env secrets
> **Prerequisite:** Sprint 4A MUST be merged first (Arcis rename, Palette H, fonts, toggle all in place)
> **New session:** Do NOT run in the same session as Sprint 4A

---

## System Overview

You are working on Arcis (GitHub repo: `halcyon-lab`), an autonomous AI-powered equity trading system. This system:

- Trades S&P 100 stocks via Alpaca bracket orders
- Uses a locally fine-tuned Qwen3 8B LLM (Q8_0 GGUF 8.7GB) via Ollama for trade analysis
- Has a 5-agent AI council (tactical_operator, strategic_architect, red_team, innovation_engine, macro_navigator) for portfolio-level strategic decisions using a vote-first Modified Delphi protocol
- Runs 13 scans/day during market hours via an APScheduler watch loop
- Has a React 18 dashboard served via Render at halcyonlab.app
- Has 165 Python files, 78 test files, 1,083 test functions, 66 research documents
- Is in Phase 1 (bootcamp) with ~25 open positions, ~5 closed trades toward a 50-trade gate
- Phase 1 gate criteria: 50 closed trades, win rate ≥45%, Sharpe ≥0.15, profit factor ≥1.3, max DD ≤12%

Sprint 4A has already been merged. The codebase is rebranded to "Arcis", Palette H (Electric Focus) CSS variables are in place, Inter + JetBrains Mono fonts are loaded, and a dark/light mode toggle is wired.

**IMPORTANT:** Sprint 4A was run by Codex with "safe-only rename" and "separate prereq sprint" options. Before starting, verify:
1. What Codex actually renamed (display text only, not Render/config/model IDs)
2. Whether Codex fixed pre-existing file size/function length violations
3. The exact CSS variable names and font class names Codex chose (may differ slightly from this spec)
Adjust your implementation to match what actually exists in the codebase, not what this spec assumes.

---

## Codebase Architecture

### Backend
```
src/
├── api/
│   ├── cloud_app.py              # 200 lines — thin bootstrap, imports routers
│   ├── cloud_routes/             # core.py, trades.py, training.py, notes.py, council.py, analytics.py
│   ├── routes/system.py          # Local API routes
│   └── websocket.py
├── cli/commands.py               # CLI command handlers
├── council/                      # 10 modules: agents.py, agent_data.py, prompts.py, protocol.py,
│                                 #   parsing.py, aggregation.py, context.py, rate_limiter.py,
│                                 #   constants.py, engine.py, value_tracker.py
├── evaluation/
│   ├── hshs_live.py              # compute_hshs(db_path) → dict with "hshs" (0-100) + "dimensions"
│   ├── gate_evaluator.py         # Phase gate evaluation
│   └── quality_rubric.py         # Training data quality scoring
├── features/
│   ├── traffic_light.py          # Regime overlay (GREEN/YELLOW/RED)
│   └── event_risk_score.py       # 0-10 continuous event risk
├── notifications/telegram.py     # 32 notification functions
├── risk/governor.py              # 8 risk checks
├── scheduler/watch.py            # Main watch loop
├── services/scan_service.py      # Scan pipeline
├── shadow_trading/
│   ├── executor.py               # Trade execution with strategy_type tagging
│   └── bracket_monitor.py        # Bracket health verification
├── sync/render_sync.py           # SQLite → Render Postgres sync
├── training/
│   ├── generator.py              # Training data generation
│   └── ingestion_gate.py         # Data quality gates
└── main.py                       # 250 lines — CLI entry point
```

### Frontend (post-Sprint 4A)
```
frontend/src/
├── api.js                        # API client — has getBuildScore(), getTrafficLightCurrent() stubs
├── App.jsx                       # Router, QueryClient
├── config.js                     # API_BASE, IS_CLOUD
├── index.css                     # Palette H CSS variables (--arcis-*)
├── components/
│   ├── Layout.jsx                # Sidebar: "ARCIS" header, 13 nav items, ThemeToggle
│   ├── ThemeToggle.jsx           # Dark/light mode toggle
│   └── ...
└── pages/
    ├── Dashboard.jsx             # Main page — NEEDS REDESIGN (Task 3)
    ├── ShadowLedger.jsx          # Paper trades — NEEDS IS COLUMNS (Task 4)
    ├── Council.jsx               # Council sessions — NEEDS REDESIGN (Task 5)
    ├── Health.jsx                # System health — NEEDS BUILD SCORE (Task 6)
    ├── Notes.jsx, Training.jsx, CTOReport.jsx, etc.
    └── ... (13 total)
```

### Key Database Tables
```sql
-- Closed/open trades
shadow_trades (trade_id, ticker, status, pnl_dollars, pnl_pct, signal_price, fill_price,
               implementation_shortfall_bps, strategy_type, exit_reason, max_adverse_excursion,
               actual_entry_time, actual_exit_time, planned_allocation, created_at)

-- Training data
training_examples (example_id, created_at, quality_score, quality_score_auto, source,
                   difficulty, curriculum_stage, regime, outcome_type, ticker)

-- Council
council_sessions (session_id, session_type, status, result_json, total_cost, created_at)
council_votes (vote_id, session_id, round_number, agent_name, direction, confidence,
               parameters_json, reasoning, created_at)
council_parameter_log (log_id, session_id, parameter_name, default_value, council_value,
                       applied_value, agent_name, attribution_start, attribution_end, created_at)
council_parameter_state (parameter_name, current_value, updated_at)

-- Scans and metrics
scan_metrics (metric_id, scan_time, packet_worthy, llm_success, llm_total, avg_conviction, created_at)
recommendations (recommendation_id, ticker, priority_score, confidence_score, market_regime, created_at)

-- Regime
traffic_light_state (id, current_regime, last_total_score)
vix_term_structure (id, collected_date, vix, vix9d, vix3m, vix1y)

-- Model
model_versions (version_id, version_name, status, created_at, training_examples_count)
```

### Existing API Endpoints (relevant)
```
GET /api/status               → system status
GET /api/shadow/open          → open paper trades
GET /api/shadow/closed        → closed paper trades (accepts ?days=N)
GET /api/shadow/account       → account equity, cash, buying power
GET /api/shadow/metrics       → trade statistics
GET /api/health/hshs          → HSHS composite score + dimensions
GET /api/health/score         → detailed health breakdown
GET /api/council/latest       → latest council session
GET /api/council/history      → recent council sessions
GET /api/council/session/{id} → full session detail with votes
GET /api/activity/feed        → recent system actions
GET /api/scan/latest          → latest scan results
GET /api/scan/metrics         → scan success/failure metrics
GET /api/training/status      → training pipeline status
GET /api/costs                → API cost tracking
GET /api/build-score          → STUB from Sprint 4A (returns zeros)
GET /api/traffic-light/current → STUB from Sprint 4A (returns UNKNOWN)
```

### CSS Variables Available (Palette H, set by Sprint 4A)
```css
--arcis-bg-primary     /* #050507 dark / #F8FAFC light */
--arcis-bg-surface     /* #0C0C10 dark / #FFFFFF light */
--arcis-bg-elevated    /* #12121A dark / #F1F5F9 light */
--arcis-accent         /* #3B82F6 dark / #2563EB light */
--arcis-accent-hover   /* #2563EB dark / #1D4ED8 light */
--arcis-accent-muted   /* rgba(37,99,235,0.08) dark / rgba(37,99,235,0.06) light */
--arcis-text-primary   /* #E4E4E7 dark / #0F172A light */
--arcis-text-secondary /* #A1A1AA dark / #475569 light */
--arcis-text-muted     /* #52525B dark / #64748B light */
--arcis-border         /* rgba(37,99,235,0.08) dark / #E2E8F0 light */
--arcis-border-hover   /* rgba(37,99,235,0.15) dark / #CBD5E1 light */
--arcis-success        /* #22C55E (both) */
--arcis-danger         /* #EF4444 (both) */
--arcis-warning        /* #F59E0B (both) */
--arcis-teal           /* #0D9488 (both) */
--arcis-teal-light     /* #14B8A6 (both) */
--arcis-info           /* #3B82F6 (both) */
--chart-1 through --chart-8
```

---

## Pre-Sprint Checks (MANDATORY)

```bash
# File size guardrail — no src/ file over 400 lines
find src -name "*.py" ! -path "*__pycache__*" -exec sh -c 'lines=$(wc -l < "$1"); if [ "$lines" -gt 400 ]; then echo "VIOLATION: $1 ($lines lines)"; fi' _ {} \;

# Function length guardrail — no function over 60 lines
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

# Verify Sprint 4A was merged
grep -r "ARCIS\|Arcis" frontend/src/components/Layout.jsx | head -3
# Should show "ARCIS" in the sidebar header

# Verify Palette H is in place
grep "arcis-bg-primary" frontend/src/index.css | head -1
# Should show #050507

# Current test count baseline
find tests -name "test_*.py" -exec grep -c "def test_" {} + | awk -F: '{s+=$2}END{print "Tests:", s}'
# Must be ≥ 1083
```

Fix any violations BEFORE starting feature work.

---

## Task 1: Build Score Computation Module

**Goal:** Create `src/evaluation/build_score.py` — a single composite KPI (0-100) that answers "am I building a product day by day?"

**Reference:** `docs/research/Build_Score_Specification__Composite_KPI.md` (full spec with formulas)

### The Build Score = geometric mean of 6 components

Each component is scored 0-100. Geometric mean ensures ALL dimensions must be healthy simultaneously — a zero in any component crashes the entire score.

#### Component 1: Gate Velocity
How fast are you closing trades toward the 50-trade Phase 1 gate?

```python
def _compute_gate_velocity(conn: sqlite3.Connection) -> float:
    """Score: 0 = no trades, 50 = on pace, 100 = 2x pace."""
    closed_this_week = conn.execute(
        "SELECT COUNT(*) FROM shadow_trades "
        "WHERE status = 'closed' AND actual_exit_time > datetime('now', '-7 days')"
    ).fetchone()[0]

    target_weekly_rate = 50 / 26  # ~1.92 trades/week targeting 50 in 6 months
    if target_weekly_rate == 0:
        return 0.0
    raw = (closed_this_week / target_weekly_rate) * 50  # 50 = on pace
    return min(100.0, raw)
```

#### Component 2: System Health
Direct HSHS composite score (already exists).

```python
def _compute_system_health(db_path: str) -> float:
    """Score: 0-100 from HSHS."""
    from src.evaluation.hshs_live import compute_hshs
    try:
        result = compute_hshs(db_path)
        return float(result.get("hshs", 0))
    except Exception:
        return 50.0  # Neutral on error
```

#### Component 3: Data Asset Value
The moat metric — measures quality × diversity × freshness of training data.

```python
def _compute_data_asset_value(conn: sqlite3.Connection) -> float:
    """Score: weighted average of quality (40%), diversity (35%), freshness (25%)."""

    # Quality: avg quality_score of examples created in last 30 days, normalized 0-100
    quality_row = conn.execute(
        "SELECT AVG(quality_score) FROM training_examples "
        "WHERE created_at > datetime('now', '-30 days') AND quality_score IS NOT NULL"
    ).fetchone()
    avg_quality = quality_row[0] if quality_row[0] is not None else None
    quality_score = (avg_quality / 30.0) * 100 if avg_quality is not None else 20.0
    quality_score = min(100.0, max(0.0, quality_score))

    # Diversity: regime coverage + outcome balance + ticker breadth, averaged
    regime_count = conn.execute(
        "SELECT COUNT(DISTINCT regime) FROM training_examples WHERE regime IS NOT NULL"
    ).fetchone()[0]
    regime_score = min(100.0, (regime_count / 4.0) * 100)  # 4 regime types

    total_examples = conn.execute("SELECT COUNT(*) FROM training_examples").fetchone()[0]
    if total_examples > 0:
        loss_count = conn.execute(
            "SELECT COUNT(*) FROM training_examples WHERE outcome_type = 'LOSS'"
        ).fetchone()[0]
        loss_pct = loss_count / total_examples
        outcome_score = min(100.0, (loss_pct / 0.15) * 50 + 50) if loss_pct > 0 else 25.0
    else:
        outcome_score = 0.0

    ticker_count = conn.execute(
        "SELECT COUNT(DISTINCT ticker) FROM training_examples WHERE ticker IS NOT NULL"
    ).fetchone()[0]
    ticker_score = min(100.0, (ticker_count / 100.0) * 100)  # S&P 100 universe

    diversity_score = (regime_score + outcome_score + ticker_score) / 3.0

    # Freshness: % of training set created in last 90 days
    if total_examples > 0:
        fresh = conn.execute(
            "SELECT COUNT(*) FROM training_examples WHERE created_at > datetime('now', '-90 days')"
        ).fetchone()[0]
        freshness_score = (fresh / total_examples) * 100
    else:
        freshness_score = 0.0

    return (quality_score * 0.40) + (diversity_score * 0.35) + (freshness_score * 0.25)
```

#### Component 4: Model Quality
Is the LLM producing useful output?

```python
def _compute_model_quality(conn: sqlite3.Connection) -> float:
    """Score: 100 - (7-day fallback rate * 100)."""
    row = conn.execute(
        "SELECT SUM(llm_total), SUM(llm_success) FROM scan_metrics "
        "WHERE created_at > datetime('now', '-7 days')"
    ).fetchone()
    total = row[0] or 0
    success = row[1] or 0
    if total == 0:
        return 50.0  # No data, neutral
    fallback_rate = (total - success) / total
    return max(0.0, (1.0 - fallback_rate) * 100)
```

#### Component 5: Research Velocity
Are findings being implemented? Proxy from HSHS Flywheel Velocity until proper tracking exists.

```python
def _compute_research_velocity(db_path: str) -> float:
    """Proxy: HSHS Flywheel Velocity dimension."""
    from src.evaluation.hshs_live import compute_hshs
    try:
        result = compute_hshs(db_path)
        dims = result.get("dimensions", {})
        return float(dims.get("flywheel_velocity", 50))
    except Exception:
        return 50.0
```

#### Component 6: Reliability
Is the system running without errors?

```python
def _compute_reliability(conn: sqlite3.Connection) -> float:
    """Score: (scan success rate * 0.6 + uptime ratio * 0.4) * 100."""
    row = conn.execute(
        "SELECT COUNT(*), SUM(CASE WHEN packet_worthy IS NOT NULL THEN 1 ELSE 0 END) "
        "FROM scan_metrics WHERE created_at > datetime('now', '-7 days')"
    ).fetchone()
    attempted = row[0] or 0
    succeeded = row[1] or 0

    scan_success_rate = succeeded / attempted if attempted > 0 else 0
    expected_scans = 65  # ~13/day * 5 trading days
    uptime = min(1.0, attempted / expected_scans)

    return (scan_success_rate * 0.6 + uptime * 0.4) * 100
```

#### Geometric Mean + Decay

```python
import math

def compute_build_score(db_path: str = DEFAULT_DB_PATH) -> dict:
    """Compute the Build Score: geometric mean of 6 components with daily decay."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    components = {
        "gate_velocity": _compute_gate_velocity(conn),
        "system_health": _compute_system_health(db_path),
        "data_asset_value": _compute_data_asset_value(conn),
        "model_quality": _compute_model_quality(conn),
        "research_velocity": _compute_research_velocity(db_path),
        "reliability": _compute_reliability(conn),
    }

    # Geometric mean with floor of 1 (avoids log(0))
    values = [max(1.0, v) for v in components.values()]
    log_sum = sum(math.log(v) for v in values)
    geo_mean = math.exp(log_sum / len(values))
    build_score = round(min(100.0, geo_mean), 1)

    conn.close()
    return {
        "build_score": build_score,
        "components": {k: round(v, 1) for k, v in components.items()},
        # ... additional fields for API response
    }
```

#### Daily Decay
```python
def apply_daily_decay(db_path: str = DEFAULT_DB_PATH) -> float:
    """Apply 1-point decay if no activity today. Returns new score."""
    conn = sqlite3.connect(db_path)
    today = date.today().isoformat()

    has_trades = conn.execute(
        "SELECT 1 FROM shadow_trades WHERE status='closed' AND DATE(actual_exit_time) = ?", (today,)
    ).fetchone()
    has_training = conn.execute(
        "SELECT 1 FROM training_examples WHERE DATE(created_at) = ?", (today,)
    ).fetchone()
    has_scans = conn.execute(
        "SELECT 1 FROM scan_metrics WHERE DATE(created_at) = ?", (today,)
    ).fetchone()

    if has_trades or has_training or has_scans:
        return current_score  # No decay
    else:
        return max(0, current_score - 1)  # Decay 1 point
```

#### Database Table
```sql
CREATE TABLE IF NOT EXISTS build_score_history (
    score_id TEXT PRIMARY KEY,
    score_date TEXT NOT NULL UNIQUE,
    build_score REAL NOT NULL,
    gate_velocity REAL,
    system_health REAL,
    data_asset_value REAL,
    model_quality REAL,
    research_velocity REAL,
    reliability REAL,
    decay_applied INTEGER DEFAULT 0,
    components_json TEXT,
    created_at TEXT NOT NULL
);
```

### Tests Required
Create `tests/test_build_score.py` with ≥10 tests:
- Each component function returns 0-100 on empty DB
- Each component function returns expected values on populated DB
- Geometric mean calculation is correct
- Score floors at 1 per component (no log(0))
- Decay applies only when no activity
- Decay does not apply when any activity exists
- Full compute_build_score returns complete structure
- Data asset value weights sum to 1.0
- History table stores correctly

---

## Task 2: Build Score + Traffic Light API Endpoints (Replace Stubs)

Replace the stub endpoints created in Sprint 4A with real implementations.

**`GET /api/build-score`:**
```python
@router.get("/api/build-score")
async def get_build_score(db=Depends(get_db)):
    """Build Score composite KPI."""
    from src.evaluation.build_score import compute_build_score
    result = compute_build_score(db)

    # Add 7-day history
    with sqlite3.connect(db) as conn:
        rows = conn.execute(
            "SELECT build_score, score_date FROM build_score_history "
            "ORDER BY score_date DESC LIMIT 7"
        ).fetchall()
    result["history_7d"] = [r[0] for r in reversed(rows)]

    # Add phase progress
    with sqlite3.connect(db) as conn:
        closed = conn.execute(
            "SELECT COUNT(*) FROM shadow_trades WHERE status = 'closed'"
        ).fetchone()[0]
    result["phase_progress"] = {
        "current_phase": 1,
        "trades_closed": closed,
        "trades_required": 50,
        "pct_complete": round(closed / 50 * 100, 1),
        "estimated_weeks_remaining": round((50 - closed) / 1.92, 0) if closed < 50 else 0,
    }

    return result
```

**`GET /api/traffic-light/current`:**
```python
@router.get("/api/traffic-light/current")
async def get_traffic_light_current(db=Depends(get_db)):
    """Current Traffic Light regime."""
    with sqlite3.connect(db) as conn:
        conn.row_factory = sqlite3.Row
        tl = conn.execute(
            "SELECT current_regime, last_total_score FROM traffic_light_state WHERE id = 1"
        ).fetchone()
        vix = conn.execute(
            "SELECT vix FROM vix_term_structure ORDER BY collected_date DESC LIMIT 1"
        ).fetchone()
    return {
        "regime": tl["current_regime"] if tl else "UNKNOWN",
        "score": tl["last_total_score"] if tl else 0,
        "vix": round(vix["vix"], 2) if vix else 0,
    }
```

Update `frontend/src/api.js` to use these real endpoints (methods already exist from Sprint 4A stubs).

---

## Task 3: Dashboard Main Page Redesign — "The Glance"

**Goal:** Redesign `Dashboard.jsx` so Ryan sees everything he needs in 2 seconds on his phone.

**Priority order (top to bottom):**
1. Build Score hero + P&L + stats
2. Equity curve
3. Council compact (expandable)
4. Traffic Light + Event Risk
5. Positions + Bracket Health
6. Activity feed

**Key data sources (already available via API):**
- `getBuildScore()` → build_score, components, phase_progress, history_7d
- `getAccount()` → equity, cash, buying_power
- `getOpenTrades()` → array of open trades
- `getClosedTrades(days)` → array of closed trades
- `api.getStatus()` → system status
- `getTrafficLightCurrent()` → regime, score, vix
- `api.getLatestCouncil()` → latest council session (direction, consensus)
- `api.getActivityFeed()` → recent actions

**Layout specification:**

```
┌────────────────────────────────────────┐
│ Build Score: 68 (+4)  │  P&L: +$1,247 │
│ ▓▓▓▓▓▓▓▓▓▓░░░░░ 68%  │  Today +$84   │
├────────────────────────────────────────┤
│ Win Rate: 60%         │  Gate: 5/50   │
│ 3W / 2L · $249/trade  │  ~6 weeks     │
├────────────────────────────────────────┤
│ Equity Curve                [1W 1M ALL]│
│ ╱‾‾‾╲╱‾‾‾‾‾‾‾╱‾‾‾‾‾‾╱‾‾‾‾‾‾‾╱‾‾    │
├────────────────────────────────────────┤
│ Council: [Bullish] 4-1 · 78%      [▾] │
├───────────────────┬────────────────────┤
│ ● Green 5/6       │ Event: 3/10 NFP 2d│
├───────────────────┴────────────────────┤
│ 25 open · 17 ▲ · 8 ▼   [Brackets OK]  │
├────────────────────────────────────────┤
│ Opened RTX @ $127.40           11:32   │
│ Council: bullish 4-1            9:35   │
│ Scan: 3 packets, 1 traded      9:31   │
└────────────────────────────────────────┘
```

**Implementation notes:**
- Use Recharts `AreaChart` for equity curve (import already available in the project)
- Equity curve data: compute from closed trades. Start at starting_capital ($100,000), add cumulative pnl_dollars from each closed trade ordered by actual_exit_time. If fewer than 3 data points, show a "Not enough data" placeholder instead of a flat line.
- Time range toggle: 1W (last 7 days), 1M (last 30 days), ALL (all time). Default to ALL when <30 trades, 1M when 30-100, 1W when >100.
- All financial numbers in JetBrains Mono: `className="financial-data"`
- All P&L values must include ▲/▼ arrows for colorblind accessibility
- Build Score color: `var(--arcis-teal)` when >70, `var(--arcis-warning)` when >50, `var(--arcis-danger)` when <50
- Use `useQuery` hooks with 60-second refetch intervals (consistent with existing pattern)
- Mobile-first: single column, no horizontal scroll

---

## Task 4: ShadowLedger IS Columns

**Goal:** Add implementation shortfall tracking columns to `ShadowLedger.jsx`.

The `shadow_trades` table already has these columns — they just aren't displayed:
- `strategy_type` TEXT (e.g., "pullback", "mean_reversion", "pead")
- `signal_price` REAL (price when signal was generated)
- `fill_price` REAL (price when order was filled — may come from Alpaca)
- `implementation_shortfall_bps` REAL (slippage in basis points)

Add to the trades table:
1. **Strategy type** — pill badge colored by type (blue for pullback, amber for mean_reversion, teal for pead)
2. **Signal → Fill** — show `$127.40 → $127.55` with IS in bps
3. **IS bps** — colored by magnitude (green <5bps, amber 5-20bps, red >20bps)
4. **Days held** — show "3/7d" with a tiny progress bar toward timeout

Ensure the API returns these fields (check `src/api/cloud_routes/trades.py` — they should already be in the SELECT).

---

## Task 5: Council Page Redesign

**Goal:** Redesign `Council.jsx` to show the v2 agent architecture properly.

**Layout:**
1. **Latest session header** — direction badge (Bullish/Neutral/Bearish), consensus type (4-1, 3-2), confidence %, timestamp
2. **5 agent cards** — one per agent, showing:
   - Agent name + emoji/icon
   - Direction badge
   - Confidence %
   - Key reasoning (truncated to 2 lines)
   - Key risk (1 line)
3. **Consensus visualization** — horizontal stacked bar showing vote distribution
4. **Parameter adjustments** — table from `council_parameter_log` (session, parameter, old → new, agent)
5. **Strategic question input** — text input for ad-hoc strategic questions (calls `POST /api/actions/council` with `session_type: "strategic"`)
6. **Session history** — list of recent sessions with direction, consensus type, date

**Agent names and roles:**
| Agent | Role | Icon suggestion |
|---|---|---|
| tactical_operator | Short-term technical + momentum | Target/crosshair |
| strategic_architect | Portfolio construction + allocation | Blueprint/grid |
| red_team | Devil's advocate + risk identification | Shield/warning |
| innovation_engine | Novel signals + research integration | Lightbulb/spark |
| macro_navigator | Macro regime + economic indicators | Globe/compass |

**Data sources:**
- `api.getLatestCouncil()` → latest session with result_json containing votes
- `api.getCouncilHistory()` → list of recent sessions
- `api.getCouncilSession(sessionId)` → full detail with all votes

---

## Task 6: Health Page — Build Score Integration

**Goal:** Add Build Score display to the top of `Health.jsx`, above the existing HSHS radar chart.

**Add to Health page:**
1. **Build Score hero** — large number (32px), weekly delta, 7-day sparkline (Recharts `LineChart`, tiny, no axis)
2. **Component breakdown** — 6 horizontal bars showing each component's score (0-100)
3. **Data asset detail** — expand the data_asset_value into quality/diversity/freshness bars
4. **Keep existing** — HSHS radar chart stays, but moves below the Build Score section

**Also add below HSHS:**
5. **Scan success rate** — 7-day rolling trend (tiny sparkline)
6. **Fallback rate** — 7-day rolling trend (inverse of model quality, tiny sparkline)

---

## Task 7: Render Sync for New Tables

**Goal:** Add `build_score_history` to the Render Postgres sync pipeline.

Update `src/sync/render_sync.py` — add the table to the sync config:
```python
"build_score_history": {
    "mode": "incremental",
    "time_col": "created_at",
    "pk": "score_id",
},
```

Update `scripts/render_migrate.py` — add the CREATE TABLE statement for Postgres:
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
    components_json TEXT,
    created_at TEXT NOT NULL
);
```

Also update `scripts/create_missing_tables.py` with the SQLite version.

---

## Task 8: Wire Secrets Through .env

**Note:** Sprint 4A may have partially addressed this. Check first: `grep -r "load_dotenv\|python-dotenv" src/ requirements.txt`. If already wired, skip to verifying all secret references.

A `.env.example` already exists in the repo root with all secret keys documented.
The goal: `settings.yaml` holds ONLY non-secret config (committed to git). All secrets load from `.env` via `python-dotenv`.

Steps:
1. `pip install python-dotenv` and add to `requirements.txt`
2. Add `from dotenv import load_dotenv; load_dotenv()` at the top of `src/main.py` and `src/scheduler/watch.py`
3. Wire ALL secret references through `os.environ.get()`:
   - `src/council/protocol.py` → `ANTHROPIC_API_KEY`
   - `src/data_collection/finnhub_collector.py` → `FINNHUB_API_KEY`
   - `src/data_collection/fred_collector.py` → `FRED_API_KEY`
   - `src/notifications/telegram.py` → `TELEGRAM_BOT_TOKEN`
   - `src/notifications/email_notifier.py` → `EMAIL_PASSWORD`
   - `src/shadow_trading/alpaca_adapter.py` → already uses env vars ✓
   - `src/api/cloud_app.py` → already uses env vars ✓
4. In `config/settings.example.yaml`, replace all secret values with comments:
   ```yaml
   # api_key: loaded from ALPACA_API_KEY env var (see .env.example)
   ```
5. Keep ALL non-secret config in `settings.yaml` (thresholds, intervals, feature flags, etc.)

After this, `settings.yaml` can be committed freely. Only `.env` (gitignored) holds secrets.

---

## Task 9: Documentation Update (MANDATORY)

1. **AGENTS.md** — Verify ALL counts match reality:
```bash
echo "Python files:" && find src -name "*.py" ! -path "*__pycache__*" | wc -l
echo "Test files:" && find tests -name "*.py" | wc -l
echo "Tests:" && find tests -name "*.py" -exec grep -c "def test_" {} + | awk -F: '{s+=$2}END{print s}'
echo "Dashboard pages:" && ls frontend/src/pages/*.jsx | wc -l
echo "API routes:" && grep -c "@router\.\|@app\." src/api/cloud_routes/*.py src/api/routes/*.py 2>/dev/null | awk -F: '{s+=$2}END{print s}'
echo "DB tables:" && grep -rn "CREATE TABLE" src/ scripts/ --include="*.py" | grep -v __pycache__ | sed 's/.*CREATE TABLE IF NOT EXISTS //;s/ (.*//' | sort -u | wc -l
echo "Research docs:" && ls docs/research/*.md docs/research/*.pdf 2>/dev/null | wc -l
```

2. **CHANGELOG.md** — Add Sprint 4B entry:
```markdown
## Sprint 4B: Dashboard Logic & Redesign (YYYY-MM-DD)
- Added: Build Score composite KPI (6 components, geometric mean, daily decay)
- Added: Build Score API endpoint + computation module
- Added: Traffic Light current regime API endpoint
- Redesigned: Dashboard main page ("The Glance") with Build Score hero, equity curve, council compact
- Redesigned: Council page with 5 agent cards, consensus visualization, strategic input
- Updated: ShadowLedger with IS tracking columns (strategy_type, signal→fill, IS bps, days held)
- Updated: Health page with Build Score integration above HSHS radar
- Added: Render sync for build_score_history table
```

3. **docs/architecture.md** — Add Build Score module, new API endpoints, new DB table

4. **Verify all counts match code reality** — run the commands above

---

## Final Verification

```bash
# 1. All tests pass
python -m pytest tests/ -x -q

# 2. Test count hasn't decreased (should increase due to test_build_score.py)
find tests -name "test_*.py" -exec grep -c "def test_" {} + | awk -F: '{s+=$2}END{print "Tests:", s}'

# 3. Frontend builds
cd frontend && npm run build && cd ..

# 4. No file over 400 lines
find src -name "*.py" ! -path "*__pycache__*" -exec sh -c 'lines=$(wc -l < "$1"); if [ "$lines" -gt 400 ]; then echo "VIOLATION: $1 ($lines lines)"; fi' _ {} \;

# 5. Build Score computes without error
python3 -c "from src.evaluation.build_score import compute_build_score; print(compute_build_score())"

# 6. API stubs replaced (should return non-zero structure)
# Test locally: python -m src.api.app then curl localhost:8000/api/build-score
```

---

## Sprint Checklist

Paste the contents of `docs/sprint-checklist.md` here and complete every applicable item before marking this sprint done.
