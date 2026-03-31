# Sprint 4B: Dashboard Logic & Redesign (Claude Code)

> **Executor:** Claude Code
> **Scope:** 9 tasks
> **Prerequisite:** Sprint 4A MERGED. Verify: `grep "ARCIS\|Arcis" frontend/src/components/Layout.jsx`
> **New session:** Do NOT reuse Sprint 4A session

---

## System Overview

Arcis (repo: `halcyon-lab`) is an autonomous AI equity trading system. S&P 100 stocks, Alpaca bracket orders, fine-tuned Qwen3 8B via Ollama, 5-agent AI council, React 18 dashboard on Render (halcyonlab.app). Phase 1 bootcamp: ~25 open positions, ~5 closed toward 50-trade gate.

**Sprint 4A was run by Codex with these choices:**
- "Safe-only rename" — display text only, not Render/config/model IDs
- "Separate prereq sprint" — fixed pre-existing file size/function violations first
- "Keep model IDs stable" — `halcyonlatest`, `halcyon-v1` unchanged

**Before starting, verify what 4A actually did:**
1. CSS variable names: `grep "arcis-bg-primary" frontend/src/index.css`
2. Font loading: `grep "Inter\|JetBrains" frontend/public/index.html`
3. Theme toggle: `ls frontend/src/components/ThemeToggle.jsx`
4. **Adapt your implementation to match what Codex built, not what this spec assumes.**

---

## Key References

| What | Where |
|---|---|
| Build Score full spec | `docs/research/Build_Score_Specification__Composite_KPI.md` |
| Brand identity research | `docs/research/Brand_Identity_System__AI_Trading_Platform.pdf` |
| Palette H hex values | `docs/roadmap-additions-2026-03-28.md` (search "Palette Decision") |

---

## Key DB Tables

```sql
shadow_trades (trade_id, ticker, status, pnl_dollars, pnl_pct, signal_price, fill_price,
               implementation_shortfall_bps, strategy_type, exit_reason, actual_entry_time,
               actual_exit_time, planned_allocation, created_at)
training_examples (example_id, created_at, quality_score, source, regime, outcome_type, ticker)
council_sessions (session_id, session_type, status, result_json, total_cost, created_at)
council_votes (vote_id, session_id, round_number, agent_name, direction, confidence, parameters_json, reasoning)
council_parameter_log (log_id, session_id, parameter_name, default_value, council_value, applied_value)
scan_metrics (metric_id, packet_worthy, llm_success, llm_total, avg_conviction, created_at)
traffic_light_state (id, current_regime, last_total_score)
vix_term_structure (id, collected_date, vix, vix9d, vix3m)
```

**Existing API:** `/api/shadow/open`, `/api/shadow/closed`, `/api/shadow/account`, `/api/shadow/metrics`, `/api/health/hshs`, `/api/council/latest`, `/api/council/history`, `/api/council/session/{id}`, `/api/activity/feed`, `/api/scan/metrics`, `/api/build-score` (STUB), `/api/traffic-light/current` (STUB)

**Palette H CSS vars (verify exact names from 4A):** `--arcis-bg-primary`, `--arcis-bg-surface`, `--arcis-accent`, `--arcis-text-primary`, `--arcis-text-secondary`, `--arcis-text-muted`, `--arcis-border`, `--arcis-success` (#22C55E), `--arcis-danger` (#EF4444), `--arcis-warning` (#F59E0B), `--arcis-teal` (#0D9488)

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
```

Fix NEW violations before starting.

---

## Task 1: Build Score Computation Module

Create `src/evaluation/build_score.py`. Full spec: `docs/research/Build_Score_Specification__Composite_KPI.md`

**Geometric mean of 6 components (each 0-100, floored at 1):**

1. **Gate velocity** — closed trades this week / target rate (50/26 weeks). Score 50 = on pace, 100 = 2× pace.
2. **System health** — direct from `compute_hshs(db_path)["hshs"]`
3. **Data asset value** — quality 40% (avg quality_score last 30d, normalize 0-30 → 0-100) + diversity 35% (regime coverage + outcome balance + ticker breadth, averaged) + freshness 25% (% created in last 90d)
4. **Model quality** — `100 - (7d fallback rate × 100)`. Fallback = `(llm_total - llm_success) / llm_total`
5. **Research velocity** — proxy: HSHS Flywheel Velocity dimension
6. **Reliability** — `(scan_success_rate × 0.6 + uptime_ratio × 0.4) × 100`

**Decay:** -1 point per day with zero trades closed AND zero training examples AND zero scans.

**DB table:** `build_score_history` (score_id TEXT PK, score_date TEXT UNIQUE, build_score REAL, gate_velocity REAL, system_health REAL, data_asset_value REAL, model_quality REAL, research_velocity REAL, reliability REAL, decay_applied INTEGER DEFAULT 0, components_json TEXT, created_at TEXT)

**Implement:** `init_build_score_tables()`, `compute_build_score(db_path) → dict`, `apply_daily_decay(db_path) → float`

**Tests:** `tests/test_build_score.py` ≥10 tests: each component on empty/populated DB, geometric mean, floor at 1, decay logic, history storage.

---

## Task 2: Replace API Stubs

Replace stubs in `src/api/cloud_routes/analytics.py`:

**GET /api/build-score** → `compute_build_score()` + `history_7d` (last 7 scores) + `phase_progress` (closed count vs 50, pct, estimated weeks)

**GET /api/traffic-light/current** → query `traffic_light_state` for regime/score + `vix_term_structure` for latest VIX

Update `frontend/src/api.js` methods.

---

## Task 3: Dashboard Main Page — "The Glance"

Redesign `Dashboard.jsx`. Mobile-first, single column, priority order:

1. **Build Score hero + P&L** — 2-column: large Build Score (32px) with delta | total P&L with today/week
2. **Win rate + Gate progress** — 2-column: win rate + W/L count | 5/50 trades with ETA
3. **Equity curve** — Recharts AreaChart. Cumulative P&L from closed trades, starting at $100K. Toggle: 1W/1M/ALL. Default ALL when <30 trades. Placeholder if <3 data points.
4. **Council compact** — direction badge + consensus + confidence, expandable for agent details
5. **Traffic Light + Event Risk** — 2-column: regime dot + score | event score + next event
6. **Positions + Bracket Health** — open/green/red counts + bracket OK badge
7. **Activity feed** — last 3-5 system actions with timestamps

**Rules:** Financial data in `className="financial-data"` (JetBrains Mono tabular-nums). All P&L includes ▲/▼ arrows. Build Score color: teal >70, warning >50, danger <50. `useQuery` with 60s refetch.

---

## Task 4: ShadowLedger IS Columns

Add to `ShadowLedger.jsx` (data exists in `shadow_trades`, just not displayed):

1. **Strategy type** — pill badge: blue=pullback, amber=mean_reversion, teal=pead
2. **Signal → Fill** — `$127.40 → $127.55` with IS bps
3. **IS bps** — green <5, amber 5-20, red >20
4. **Days held** — `3/7d` with progress bar toward timeout

Verify API returns these fields from `src/api/cloud_routes/trades.py`.

---

## Task 5: Council Page Redesign

Redesign `Council.jsx`:

1. **Latest session header** — direction badge, consensus (4-1), confidence %, timestamp
2. **5 agent cards** — name + icon, direction badge, confidence, reasoning (2 lines), risk (1 line). Agents: tactical_operator (target), strategic_architect (blueprint), red_team (shield), innovation_engine (lightbulb), macro_navigator (globe)
3. **Consensus bar** — horizontal stacked bar showing vote distribution
4. **Parameter adjustments table** — from `council_parameter_log`
5. **Strategic question input** — submits `POST /api/actions/council` with `session_type: "strategic"`
6. **Session history** — recent sessions list with direction + consensus type

Data: `getLatestCouncil()`, `getCouncilHistory()`, `getCouncilSession(id)`

---

## Task 6: Health Page — Build Score Integration

Update `Health.jsx`:

1. **Build Score hero** — 32px number, weekly delta, 7-day sparkline
2. **Component breakdown** — 6 horizontal bars (0-100)
3. **Data asset detail** — quality / diversity / freshness sub-bars
4. Keep existing HSHS radar (moves below Build Score)
5. Add scan success rate + fallback rate 7d sparklines

---

## Task 7: Render Sync + DB Tables

Add `build_score_history` to `src/sync/render_sync.py`: `{"mode": "incremental", "time_col": "created_at", "pk": "score_id"}`

Add CREATE TABLE to `scripts/render_migrate.py` (Postgres) and `scripts/create_missing_tables.py` (SQLite).

---

## Task 8: Wire Secrets Through .env

**Check first:** `grep -r "load_dotenv\|python-dotenv" src/ requirements.txt` — skip if 4A already did this.

1. `pip install python-dotenv`, add to `requirements.txt`
2. `from dotenv import load_dotenv; load_dotenv()` at top of `src/main.py` and `src/scheduler/watch.py`
3. Wire through `os.environ.get()`: council/protocol.py → `ANTHROPIC_API_KEY`, finnhub_collector → `FINNHUB_API_KEY`, fred_collector → `FRED_API_KEY`, telegram.py → `TELEGRAM_BOT_TOKEN`, email_notifier → `EMAIL_PASSWORD`. (alpaca_adapter + cloud_app already done.)
4. Replace secrets in `config/settings.example.yaml` with comments pointing to `.env.example`
5. Keep all non-secret config in `settings.yaml`

---

## Task 9: Documentation Update (MANDATORY)

Run verification commands from `docs/sprint-checklist.md`. Update AGENTS.md counts, CHANGELOG.md, architecture.md (Build Score module, new endpoints, new table). Paste and complete sprint checklist.

```bash
python -m pytest tests/ -x -q
cd frontend && npm run build && cd ..
python3 -c "from src.evaluation.build_score import compute_build_score; print(compute_build_score())"
```
