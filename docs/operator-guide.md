# Arcis Operator's Guide

> **Single-source operational runbook.** When something needs doing, breaking, or unbreaking — start here. Updated regularly; if you encounter a procedure that isn't here, add it.

## Sprint 3 Cockpit Coherence (2026-05-07) — operator-visible changes

After Sprint 3 deploys to main + Render rebuilds, halcyonlab.app will render:
- Header `TL: GREEN/AMBER/RED` (was `TL: NOT SET` — now read from `/api/kpis` `stage_traffic_light`; 3-state fallback: `TL: ...` pending, `TL: COMPUTING` if loaded-but-null, `TL: ERR` on API failure)
- Cohort badges (e.g. `n=5 · canonical`) under rf-adjusted excess Sharpe + win rate KPI cards, and under Excess Sharpe in Trade History
- LoadingState component on broker exceptions, DB schema, health, monitoring widgets — error states render explicit retry button instead of infinite spinner
- ActionButton variants: `[CLI only]` badge for ops requiring local broker auth (Live Ledger reconcile, IB toggles)
- Settings IB toggles (`live_trading.ib.shadow_mode`, `live_trading.ib.paper_routing`) are now visually disabled with "Effect requires local IB Gateway connection" reason text
- Settings risk inputs no longer show float artifacts (`0.0049999...` → `0.005`)
- Monitoring page gracefully handles `system_metrics is local-only` on Render (was 500/503 infinite spinner)

### New CI guardrails (Sprint 3)

- `tests/test_calmar_canonical_only.py`: any `def *calmar*` outside `src/evaluation/statistics.py` fails CI
- `tests/test_eslint_queryfn_guardrail.py`: bare-queryFn refs in `useQuery` fail via ESLint rule (`npm --prefix frontend run lint:queryfn`)
- `tests/test_dashboard_reconciliation.py`: cohort-aware reconciliation across 5 endpoints (`/api/cto-report`, `/api/shadow/metrics`, `/api/status`, `/api/attribution/stats`, `/api/stress-test/results`)

### Sprint 4 follow-up issues to track

After Sprint 3 merges, create these GitHub issues (see `docs/audits/2026-05-06-cockpit-coherence-sprint/sp4-followups.md` for full issue bodies):
- `#SP4-shadow-metrics-live-cohort`: wire `source='live'` SQL filter for `/api/shadow/metrics` when `desk='live'`
- `#SP4-status-open-positions-cohort`: align `/api/status._meta.open_positions` cohort label with SQL filter
- `#SP4-calmar-debt`: migrate 3 hand-rolled Calmar sites (cto_report.py, engine.py, backtester.py) to canonical helper
- `#SP4-stop-loss-fallback`: locate and fix downstream stop_loss display sign-inversion
- `#SP4-render-pg-reconcile`: extend T16 reconciliation test to Postgres
- `#SP4-kpis-meta-reconciliation-test`: regression-lock `/api/kpis` `_meta` envelope
- `#SP4-tanstack-strategyresearch-platformstatus`: bare-ref `queryFn` at `StrategyResearch.jsx:41` + `PlatformStatusWidget.jsx:13`
- `#SP3-T12-pnl-card`: no dollar P&L primary card in 5-card KPIStrip — design decision needed

### Visual-verify checklist

Full operator validation checklist for halcyonlab.app post-Render-rebuild: `docs/audits/2026-05-06-cockpit-coherence-sprint/visual-verify-checklist.md`

---

## Table of contents

0. [System Overview](#0-system-overview) — what ARCIS is and how it fits together
1. [Quick Start](#1-quick-start) — first-time setup
2. [Daily Operations](#2-daily-operations) — startup, monitor, recap
3. [Common Commands](#3-common-commands) — cheat sheet
4. [Key File Paths](#4-key-file-paths) — where things live
5. [Troubleshooting Decision Trees](#5-troubleshooting-decision-trees) — what to do when X breaks
6. [Recovery Patterns](#6-recovery-patterns) — lost commits, stuck positions, corrupted state
7. [Maintenance Tasks](#7-maintenance-tasks) — corpus regen, schema migration, cleanup
8. [Glossary](#8-glossary) — term definitions
9. [Roadmap pointer](#9-roadmap-pointer) — strategic direction
10. [Daily methodology-gate workflow](#10-daily-methodology-gate-workflow) — reading the gate digest, interpreting evidence, acting on proposals
11. [Update Protocol](#11-update-protocol) — keeping this doc fresh
12. [Notification Troubleshooting](#12-notification-troubleshooting) — bot silent, token rotated, email stopped, health check
13. [Known design decisions / WON'T-FIX notes](#known-design-decisions--wont-fix-notes) — `#SP4-settings-backend-float32-storage` and similar

---

## 0. System Overview

> **5-minute onboarding.** If you've never touched ARCIS before, read this section end-to-end. By the time you finish, you should know what ARCIS does, how the pieces fit, and where to look first when something breaks. Read §1 onward only after you have this mental model.

### 0.1 What is ARCIS?

ARCIS is a **single-operator autonomous trading research desk** that generates equity trade ideas with a locally-fine-tuned LLM, executes them on Alpaca's paper broker, tracks every trade with strict instrumentation, and validates whether its strategy is actually profitable through a three-stage statistical ladder before any live capital is allocated. The system is paper-only post-bootcamp; live trading is gated behind explicit statistical evidence of edge.

**Current maturity** (as of 2026-05-06): Stage-1 honest baseline signed (`d651160`, n=35 instrumented trades, regime-tailwind suspected). Stage-1 OOS sub-validation has not yet started — the system is in the **bootcamp-archived / pre-Stage-1-OOS** window, accumulating new paper trades. Stage 2 IB-eligibility (and the methodology gate that gates it) is the next strategic milestone. Treat ARCIS as **alpha-stage research infrastructure**, not a finished product.

The codename "arcis" / "halcyon-lab" refers to the same project. The currently-active model in Ollama is `arcis:v1.0.0` (Qwen3-8B fine-tune; `halcyon-v1` is an older alias retained for fallback). The system runs on a single Windows machine with an RTX 3060 (12 GiB VRAM).

### 0.2 The strategic goal — 3-stage validation ladder

Per `MASTER.md` SD#43, real-money allocation depends on clearing three statistical bars:

| Stage | Threshold | What unlocks |
|---|---|---|
| **Stage 1** | Baseline signed at commit `d651160` (35 instrumented trades, rf-adjusted excess Sharpe = 6.14, but SPY-relative p=0.43 — regime-tailwind suspected). Sub-validation: excess-mean > 0 at t > 1.0 over 30 OOS trades. | Permission to keep paper-trading and accumulate OOS data |
| **Stage 2** | Excess Sharpe ≥ 0.5 at p < 0.05 over 150 OOS trades **AND** ≥4-of-5 promotion gate (PSR/DSR + PBO + CPCV + MC permutation + White's Reality Check) | IB Gateway live-trading eligibility |
| **Stage 3** | Excess Sharpe > 1.0 at p < 0.05 over 300 OOS trades | Full capital ramp |

The methodology gate (Stage 2 prerequisite) is live as of Sprint 2 — implementation in `docs/audits/2026-05-05-methodology-gate-wiring/`. See §10 "Daily methodology-gate workflow" for the operational guide.

### 0.3 System anatomy — what runs where

```
┌─────────────────────────────── Operator's machine (Windows, RTX 3060) ──────────────────────────────┐
│                                                                                                       │
│   Watch loop ─────────────────────►  Scheduler (5-min intraday, premarket, post-close, overnight)    │
│   (single instance,                       │                                                           │
│    PID lockfile in                        ├─► Universe scanner ─► LLM packet writer (Ollama)          │
│    data/watch.lock)                       ├─► Risk governor ────► Order submitter (Alpaca SDK)        │
│                                           ├─► Reconciler  ──────► shadow_trades table updates        │
│                                           ├─► Render sync ──────► Cloud Postgres (every 5 min)       │
│                                           └─► Build score / HSHS / dashboard refresh                  │
│                                                                                                       │
│   Ollama daemon ─────────────────►  Qwen3-8B fine-tune (arcis:v1.0.0) on GPU                         │
│   (separate process,                  Watchdog (scripts/ollama_watchdog.ps1) auto-restarts on death  │
│    poll-restarted by watchdog)                                                                        │
│                                                                                                       │
│   SQLite DB  C:\arcis\data\ai_research_desk.sqlite3  (~1 GB, 70 schema-registered tables)            │
│                                                                                                       │
│   Corpus runner ─────────────────►  Generates Stage-1 training data (Ollama-driven).                 │
│   (long-lived bg process,             ~67,681 entries; ~23-day full run at NUM_PARALLEL=2.           │
│    only when training)                Output: data/corpus/stage1-001/entries.jsonl                    │
│                                                                                                       │
└───────────────────────────────────────────┬──────────────────────────────────────────────────────────┘
                                            │
                                            │  RenderSyncThread replicates per-table cursors via sync_state
                                            ▼
┌─────────────────────────────── Render (cloud) ──────────────────────────────────────────────────────┐
│                                                                                                       │
│   FastAPI service (src/api/) ────►  Read-only API on cloud Postgres mirror                           │
│   React frontend (frontend/) ────►  Dashboard UI at https://halcyonlab.app                           │
│                                                                                                       │
└──────────────────────────────────────────────────────────────────────────────────────────────────────┘
```

**Single point of truth: the local SQLite.** Everything else (cloud Postgres, dashboard, APIs) is downstream. Cloud is for visibility, not control. If local and cloud disagree, local wins by definition.

### 0.4 The trade lifecycle

A trading day proceeds through five phases. Each phase has a dedicated watch-loop slot.

**Pre-market (07:00–09:30 ET)**
- Universe scanner — point-in-time SP100 lookup (`src/universe/pit.py`)
- Data collectors — fundamentals, news, insider, macro snapshots
- Premarket scorer — rules-based score per ticker

**Intraday (09:30–16:00 ET, 5-min scan cadence)**

Each scan cycle:
1. Filter universe by liquidity / regime / build score
2. For each surviving candidate, assemble a "packet" (price + technicals + news + fundamentals)
3. LLM call (Ollama) — returns `conviction` (1–10), `direction`, `time_horizon`, `key_risk`
4. Risk governor — enforces `effective_position_cap()` (`min()` across four namespaces: `risk.*`, `risk_governor.*`, `live_trading.*`, `bootcamp.*`)
5. Submit bracket order via Alpaca paper SDK
   - Three legs: entry + take-profit + stop-loss
   - Multipliers config-driven via `live_trading.risk.{target,stop}_atr_multiplier` (typical: 1.5×ATR target / 1.0×ATR stop in paper; 2.0×ATR target in live config — see PR #943 for rationale)
   - OCO topology when entry already filled and only protection legs remain (PR #943/#944)

In parallel, the bracket monitor runs every 5 min:
- Verify both legs of every bracket are active or healthy-completion
- False-alert quarantine on broken topology (PR #944)

**Post-close (16:00–16:35 ET)**
- `reconcile_paper_trades` — reconcile local DB against Alpaca broker state
- `reconcile_live_trades` — same for live broker (currently moot; paper-only)
- EOD report — Telegram digest + email summary
- Build score recompute — dashboard refresh

**Methodology gate (16:35 ET — live as of Sprint 2)**
- Daily run of the 5-method voting gate over each active/backtested strategy
- Persists `triggered_by='gate_proposal'` rows in `strategy_promotion_events` (informational; `from_status==to_status`)
- Operator reviews evidence and confirms via `confirm-promotion` CLI to actually transition the strategy
- See §10 for full operational guide: reading the digest, interpreting evidence, troubleshooting defer

**Overnight (16:35 ET – 07:00 ET)**
- Data collection sweep — fresh fundamentals, news, macros (runs 7 days/week per CLAUDE.md)
- VRAM handoff — Ollama unloads, training process can claim GPU
- Training cycle (when corpus + outcomes ready) — retrains on accumulated trade outcomes
- VRAM handoff back — training releases, Ollama reloads before pre-market

### 0.5 The data lifecycle

Two flows feed each other:

**Flow 1 — Trade outcomes feed Stage 1/2/3 grading**

`Strategy candidate (LLM call)` → `bracket order` → `closed trade` → `shadow_trades row` → graded by build score / HSHS / Stage-N stats.

Two filters gate which rows count:
- `instrumentation_filter.is_fully_instrumented()` — requires every required telemetry column populated (cost, slippage, fundamental snapshot, etc.). Trades missing any column are excluded from Stage 1/2/3 statistics. **Roughly 30–60% of paper trades fail instrumentation in early operations** — that's by design, not a bug.
- `outcome_stats_filter_sql()` — drops `reconciled_stale` rows (bookkeeping artifacts of reconciler closures, not real strategy outcomes). Per Wave 4 H5; enforced by `tests/test_outcome_stats_filter_coverage.py`.

The instrumentation filter is the discipline that lets ARCIS make calibrated promotion decisions. Missing it means we can't tell whether a trade closed because the strategy worked or because we lacked the data to know.

**Flow 2 — Trade context feeds the LLM training corpus**

`PIT-clean inputs (packet)` → `prompt` → `Ollama call` → `response` → `entries.jsonl row`.

Where `packet_writer.py` orchestrates: it builds prompts from PIT-clean fundamentals/news/technicals snapshots, calls Ollama, parses the response, and appends a row to `data/corpus/stage1-001/entries.jsonl`. When Ollama fails, packet_writer falls back to a hand-written template — and **currently those template rows share `model_version="arcis:v1.0.0"` with real entries (a forthcoming packet_writer change will tag fallback rows distinctly so they can be filtered at training time)**. See §5 "Ollama crashes / corpus producing template fallbacks" for detection + cleanup.

The corpus is then fed to training (`src/training/trainer.py`) to produce new model versions when accumulated outcomes warrant retraining.

### 0.6 Key invariants (don't break these)

These rules are enforced by code, tests, or operator discipline. Breaking any of them silently corrupts the validation ladder.

| Invariant | Where enforced | Why it matters |
|---|---|---|
| Schema registry is single source of truth | `src/schema/registry.py` + `test_no_create_table_in_source` / `test_no_alter_table_in_source` CI tests | Drift between Postgres / SQLite / code → silent data loss |
| Risk governor is sacred | `src/risk/governor.py` (`min()` across 4 namespaces) | Bypass = unbounded position size; instant blow-up risk |
| PIT discipline | `src/universe/pit.py` + tests | Future-data leakage invalidates backtest results |
| Training data quality #1 | Corpus discriminator (`<1500` chars + rigid prefix) + forthcoming `model_version=template_fallback` tagging | Polluted training data → polluted future model |
| Test count must not drop | CI floor at 3682 in `CLAUDE.md` | Catches accidental test deletion / bypass |
| Worktree isolation for parallel agents | `CLAUDE.md` + `.claude/agent-scope.json` pre-commit hook | Index races between parallel agents → mixed-attribution commits |
| `outcome_stats_filter_sql()` on every shadow_trades aggregation | `tests/test_outcome_stats_filter_coverage.py` static-analysis test | `reconciled_stale` rows aren't real outcomes; uncounted-out → wrong win-rate / wrong gate decision |
| Mock all external APIs in tests | `tests/conftest.py` fixtures + per-test patches | Pytest must never make a network call to Alpaca / Finnhub / yfinance / FRED / Ollama. Tests that hit live APIs are flaky and contaminate rate limits |

### 0.7 What you'll actually be doing

If you're stepping in as a new operator, these are the recurring real-world tasks (in expected frequency order, most → least common):

1. **Daily monitor** (5 min/day): Telegram digest pre-market + EOD; glance at https://halcyonlab.app for traffic light + KPIs. If green, no action.
2. **Reconciler intervention** (~weekly): Stuck Alpaca paper positions show up as repeated `reconciled_stale` rows. Cancel orders + close positions in Alpaca UI, restart watch loop. See §6 "Stuck Alpaca paper positions".
3. **PR review + merge** (~daily during active sprints): Sprint agents open PRs that need operator review. Merge via squash + delete-branch.
4. **Corpus generation supervision** (~as-needed, multi-day runs): Stage 1 baseline + retraining. Watchdog handles uptime; you watch for fallback contamination via §5 "Ollama crashes" recipe.
5. **Schema migration after PR merges** (~per-PR that touches schema): `validate-schema --fix` + `render_migrate.py`. Documented in PR body.
6. **Recovery from incidents** (~rare): WAL corruption, lost commits, broken cloud sync. §6 has tested recipes for each.
7. **Strategic decisions** (~quarterly): Stage gate promotions, model retrains, methodology toolkit additions, infra changes. Higher leverage; longer thinking.

### 0.8 Where to look first when something breaks

| Symptom | First place to look |
|---|---|
| Watch loop won't start | `logs/arcis.log` tail + §5 "Watch loop won't start" decision tree |
| Cloud dashboard shows wrong numbers | `logs/arcis.log` + §5 "Cloud dashboard shows wrong numbers" |
| Corpus stalled / producing fallback | `logs/corpus-stage1-001.err` + `logs/ollama-watchdog.log` + §5 "Ollama crashes" |
| Trade in shadow_trades table looks wrong | sqlite3 readonly query + cross-reference Alpaca UI; §6 "Stuck Alpaca paper positions" if recurring |
| Test failures after pull | §5 "Tests failing on test_repo_structure.py" or "ModuleNotFoundError" |
| DB locked errors | §5 "Database is locked" |
| SSH session closing kills your work | §5 "Long-running process won't survive my SSH session" + §7 "SSH-safe process launch" |
| Process crashed; need to recover work | §6 "Lost work after stash-pop" |
| **"Something feels wrong, I don't know what"** | §0.10 quick health check, then §6 "Total restart from a bad state" if multiple components are red |

### 0.9 The mental model in one paragraph

ARCIS is a tight feedback loop: **scan universe → LLM-score candidates → submit bracket orders → reconcile broker state → grade outcomes → (eventually, when corpus + outcomes are ready) retrain the LLM**. Everything else (schema discipline, instrumentation filter, methodology gate, three-stage ladder, render sync, dashboard) is in service of making that loop *honest* — i.e., resistant to overfitting, look-ahead bias, statistical artifacts, regime tailwinds, and silent data corruption. The reason the validation ladder is so strict is because the operator is one person betting their own capital; we'd rather discover after 300 OOS trades that the strategy works than after 30 OOS trades that it doesn't.

### 0.10 Quick health check (the 3am-incident one-liner)

When something feels wrong but you don't know what, run this from PowerShell on the operator machine. It surfaces the four things that have to be true for ARCIS to be healthy:

```powershell
Write-Output "=== Watch loop ==="; Get-CimInstance Win32_Process -Filter "name='python.exe'" | ?{ $_.CommandLine -match 'src.main startup' } | Select-Object ProcessId, @{n='age_min';e={[math]::Round(((Get-Date)-$_.CreationDate).TotalMinutes,1)}} | Format-Table
Write-Output "=== Ollama ==="; Get-Process -Name "ollama*" -ErrorAction SilentlyContinue | Select-Object Id, @{n='age_min';e={[math]::Round(((Get-Date)-$_.StartTime).TotalMinutes,1)}} | Format-Table
try { $r = Invoke-WebRequest -Uri "http://127.0.0.1:11434/api/tags" -UseBasicParsing -TimeoutSec 5; Write-Output "Ollama API: $($r.StatusCode) (200=healthy)" } catch { Write-Output "Ollama API: DOWN" }
Write-Output "=== Watchdog ==="; Get-CimInstance Win32_Process -Filter "name='powershell.exe'" | ?{ $_.CommandLine -match 'ollama_watchdog' } | Select-Object ProcessId | Format-Table
Write-Output "=== Last 3 watchdog log lines ==="; Get-Content C:\arcis\halcyon-lab\logs\ollama-watchdog.log -Tail 3 -ErrorAction SilentlyContinue
Write-Output "=== Watch loop heartbeat ==="; Get-Item C:\arcis\data\watchdog.txt -ErrorAction SilentlyContinue | Select-Object LastWriteTime
```

Healthy state:
- One python `src.main startup` process, age >0 min (single instance per host)
- One or more `ollama*` processes
- Ollama API returns `200`
- Watchdog (powershell + `ollama_watchdog`) running iff you're in a corpus / training session
- `data/watchdog.txt` LastWriteTime within the last few minutes (watch-loop heartbeat)

Anything else → drop into §5 troubleshooting using the symptom table in §0.8.

---

## 1. Quick Start

### Prerequisites

| Component | Where it lives | Notes |
|-----------|----------------|-------|
| Repo | `C:\arcis\halcyon-lab\` | Must be cwd when running CLI (`python -m src.main ...`) |
| `.env` | `C:\arcis\halcyon-lab\.env` | Sets `ARCIS_DB_PATH=C:/arcis/data/ai_research_desk.sqlite3`. Gitignored — secrets only here |
| `.venv` | `C:\arcis\halcyon-lab\.venv\` | Gitignored. Created via `python -m venv .venv && .venv\Scripts\pip install -r requirements.txt` |
| SQLite DB | `C:\arcis\data\ai_research_desk.sqlite3` | ~1 GB active runtime DB — outside repo on purpose |
| Logs | `C:\arcis\logs\` and `C:\arcis\halcyon-lab\logs\` | Watch loop, sync, corpus, telegram, etc. |
| Hardware | NVIDIA GPU with ≥12 GB VRAM | Required for Ollama inference. Current: RTX 3060 12 GB; planned upgrade to RTX 3090 24 GB. VRAM directly gates `--num-parallel` throughput for corpus generation and model inference — see §5 "Ollama crashes / corpus producing template fallbacks" and §7 "Stage 1 corpus regeneration / resume" for VRAM math. |

### First-time setup checklist

```bash
# 1. Clone + install
git clone https://github.com/millerrc18/arcis.git C:/arcis/halcyon-lab
cd C:/arcis/halcyon-lab
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt

# 2. Copy + edit config
copy config\settings.example.yaml config\settings.local.yaml
# Edit settings.local.yaml — set Alpaca paper credentials, Telegram tokens, etc.

# 3. Create .env (NOT in repo, gitignored)
# Required:
#   ARCIS_DB_PATH=C:/arcis/data/ai_research_desk.sqlite3
#   ALPACA_API_KEY=...
#   ALPACA_API_SECRET=...
#   ANTHROPIC_API_KEY=...
#   FINNHUB_API_KEY=...
#   FRED_API_KEY=...
#   TELEGRAM_BOT_TOKEN=...
#   TELEGRAM_CHAT_ID=...

# 4. Install git hooks (one-time)
bash scripts/install-hooks.sh

# 5. Initialize / verify schema
python -m src.main validate-schema --fix

# 6. First startup
python -m src.main startup
```

### Optional but recommended

- **Post-bootcamp graduation** (after Stage 1 baseline signed): add `live_trading.post_bootcamp: true` to `settings.local.yaml`. Sticky — keeps `bootcamp_mode=False` so ordinary CRITICAL audit flags halt trading instead of being downgraded to alerts.
- **UPS hardware** — listed as known blocker in MASTER.md. CyberPower CP1500PFCLCD ~$220 prevents WAL corruption from unexpected power loss.

---

## 2. Daily Operations

### Morning (pre-market)

1. **Check watch loop is running:**
   ```powershell
   powershell -Command "Get-CimInstance Win32_Process -Filter \"name='python.exe' and CommandLine like '%watch%'\" | Select-Object ProcessId, CreationDate | Format-List"
   ```
   If no watch process → start it: `python -m src.main startup`

2. **Glance at the dashboard:**
   - Local: http://localhost:8000 (operator-only, bound to 127.0.0.1)
   - Cloud: https://halcyonlab.app (Render-deployed; mirrors local data via RenderSyncThread)
   - KPI tiles, traffic light, build score, HSHS health, recent trades

3. **Check overnight Telegram digest** — if running with `--email-mode digest` (default), summary lands in your bot before 09:00 ET

### Mid-day (during market hours)

- Watch loop runs scans on its configured cadence (intraday at 5-min cadence default; pre-market and post-close on schedule).
- Trades open via Alpaca paper bracket orders.
- Reconciler runs periodically to catch broker drift.
- No operator action normally needed.

### Evening (post-close)

- EOD recap via Telegram (`scheduler/reports.py`).
- Post-close reconciliation script: `python scripts/post_close_check.py` (also runs automatically).
- Dashboard updates with closed trades + P&L.

### Watching the system live

- **Tail watch loop log:** `tail -f C:/arcis/halcyon-lab/logs/arcis.log`
- **Tail corpus generator (current run):** `tail -f C:/arcis/halcyon-lab/logs/corpus-stage1-001.err` (progress + Ollama messages go to stderr; legacy filename `stage1-corpus.log` is from earlier runs only)
- **Tail Ollama watchdog:** `tail -f C:/arcis/halcyon-lab/logs/ollama-watchdog.log` (start/restart/circuit-break events)
- **Tail Ollama daemon stderr:** `tail -f C:/arcis/halcyon-lab/logs/ollama-daemon.err` (CUDA / runner output — diagnostic on next crash)
- **Sync thread health:** check `data/watch.lock` exists and modification time is recent
- **DB lock checks:** never open `data/ai_research_desk.sqlite3` in MS Access / DBeaver while watch loop runs — Windows holds the file lock and writers will hit "database is locked"

---

## 3. Common Commands

### CLI entry points (`python -m src.main`)

```bash
python -m src.main startup                    # Full validated start (preferred)
python -m src.main startup --check-only       # Validate, don't launch
python -m src.main startup --force            # Bypass critical failures, launch anyway
python -m src.main startup --no-overnight     # Disable overnight schedule
python -m src.main preflight                  # Tiered validation report
python -m src.main scan --dry-run --verbose   # Dry-run a scan
python -m src.main shadow-status              # Open / closed shadow trade summary
python -m src.main training-status            # Training pipeline status
python -m src.main validate-schema            # Check schema drift
python -m src.main validate-schema --fix      # Auto-create missing tables/columns
python -m src.main reset-live-prices-watermark # Cap live_prices first-cycle backlog to 24h (post H3 merge)
```

#### Strategy promotion confirmation (Sprint 2 T5)

After the daily gate runs and emits a `gate_proposal` row with `decision='defer'`,
the operator reviews the evidence and confirms via:

```bash
# Review and confirm a deferred gate proposal (prompts y/N):
python -m src.main confirm-promotion \
  --strategy <strategy_id> \
  --justification "Why this strategy is ready for shadow_trading after reviewing evidence..."

# Skip y/N prompt (for scripted / overnight use):
python -m src.main confirm-promotion \
  --strategy <strategy_id> \
  --justification "Why this strategy is ready for shadow_trading after reviewing evidence..." \
  --yes

# Promote to a different target status:
python -m src.main confirm-promotion \
  --strategy <strategy_id> \
  --justification "Stage-2 review passed; promoting to production after 60+ days shadow." \
  --target-status production \
  --yes
```

**Pre-checks performed by the CLI (operator-ergonomic):**
- Justification must be >= 40 characters
- A `gate_proposal` row must exist for the strategy (from the daily gate or `run-promotion-gate`)
- The proposal must be < 24 hours old (Decision 14 stale-proposal guard)
- The proposal's `decision` must be `'defer'` — `'reject'` is NOT overridable

**On success:** prints `event_id=<N> final_status=<status>` and exits 0.
**On server-side re-fire rejection:** prints the rejection reason and exits non-zero (no event_id).

### Tests

```bash
python -m pytest tests/ -q --timeout=60                  # Full sweep (~3-5 min)
python -m pytest tests/test_render_sync.py -v            # Single file
python -m pytest tests/shadow_trading/ -v                # Subdirectory
python -m pytest tests/test_repo_structure.py -v         # File-size / docstring guardrails
python -m pytest tests/ -q --timeout=60 -x               # Stop on first failure
```

### Postgres / Render sync

```bash
# After schema changes, sync Postgres:
DATABASE_URL=$(python -c "import yaml; cfg=yaml.safe_load(open('config/settings.local.yaml')); print(cfg['render']['database_url'])") python scripts/render_migrate.py
```

### Corpus generation

**Prerequisite: Ollama watchdog MUST be running** (see §7 "Ollama watchdog"). Without it, a single Ollama crash will silently produce template-fallback entries that pollute training data — see §5 "Corpus producing template fallbacks".

```bash
# 0. Start the watchdog (one-time per machine boot, see §7 for WMI variant)
scripts\start_ollama_watchdog.bat

# 1. Initial launch (Stage 1) — NUM_PARALLEL=2 is the validated stable config
#    on the RTX 3060 (12 GiB VRAM). At --num-parallel 4 the runner CUDA-OOMs.
#    See §5 "Ollama crashes" for VRAM math.
python scripts/generate_llm_corpus.py \
  --corpus-id stage1-001 \
  --window-start 2023-09-01 \
  --window-end 2026-04-28 \
  --num-parallel 2

# 2. Resume after stop / hang:
python scripts/generate_llm_corpus.py \
  --corpus-id stage1-001 \
  --window-start 2023-09-01 \
  --window-end 2026-04-28 \
  --resume \
  --num-parallel 2
```

`OLLAMA_NUM_PARALLEL` user env var must be set to `2` to match — **one-time per-machine setup; the watchdog does NOT manage this**. Set via PowerShell `[Environment]::SetEnvironmentVariable("OLLAMA_NUM_PARALLEL","2","User")` or `setx OLLAMA_NUM_PARALLEL 2` BEFORE starting the watchdog (Ollama reads it on its own startup, not from the watchdog process env). Mismatch (e.g. corpus `--num-parallel 4` vs `OLLAMA_NUM_PARALLEL=1`) causes Ollama to spawn N runner subprocesses, each loading a separate model copy → VRAM exhaustion → silent crash.

**For SSH-disconnect-safe runs**, use the WMI launch pattern in §7 "SSH-safe process launch" instead of running the command directly in your shell.

### Frontend

```bash
cd frontend
npm install     # Once
npm run dev     # Dev server on :3000
npm run build   # Production bundle
```

### Lint / format

```bash
python -m ruff check src/ tests/ --fix
python -m ruff format src/ tests/
```

---

## 4. Key File Paths

### Inside repo (`C:\arcis\halcyon-lab\`)

| Path | Purpose |
|------|---------|
| `src/` | All Python source |
| `src/main.py` | CLI entry point dispatcher |
| `src/scheduler/watch.py` | Main watch loop |
| `src/schema/registry.py` | **Single source of truth** for all 70 tables. NEVER write CREATE/ALTER outside this file |
| `src/shadow_trading/exit_reason.py` | Exit reason vocabulary + `outcome_stats_filter_sql()` helper |
| `src/sync/render_sync.py` | Local SQLite → Render Postgres replication |
| `tests/` | Pytest suite. Mirrors src/ layout |
| `tests/_helpers/seed_closed_trades.py` | Shared fixture for win-rate / outcome filter tests |
| `config/settings.local.yaml` | **Operator config** — gitignored, contains your secrets/preferences |
| `config/settings.example.yaml` | Documented template, committed |
| `config/known_violations.json` | Grandfathered file/function-size violations |
| `CHANGELOG.md` | `[Unreleased]` section gets one bullet per PR |
| `MASTER.md` | Canonical project state (sprint history, current metrics, blockers) |
| `CLAUDE.md` | Rules for AI agents working on the codebase |
| `docs/operator-guide.md` | **This file** |
| `docs/audits/` | Sprint specs, audit reports, gap lists |
| `docs/methodology-toolkit.md` | Reference for shelf statistical methods (PBO, CPCV, etc.) |
| `data/watch.lock` | PID lockfile for the watch loop |
| `.claude/agent-scope.json` | Per-worktree scope-check fence (PM-written before agent dispatch) |

### Outside repo (runtime artifacts)

| Path | Purpose |
|------|---------|
| `C:\arcis\data\ai_research_desk.sqlite3` | Active SQLite DB (~1 GB) |
| `C:\arcis\data\reference\` | Reference data (sp100_history.json, etc.) |
| `C:\arcis\data\simulation_cache\` | Cached simulation outputs |
| `C:\arcis\data\watchdog.txt` | Watch loop heartbeat |
| `C:\arcis\logs\` | Runtime logs |
| `C:\arcis\halcyon-lab\logs\arcis.log` | Main watch loop log |
| `C:\arcis\halcyon-lab\logs\corpus-stage1-001.out` | Corpus generator stdout (current run) |
| `C:\arcis\halcyon-lab\logs\corpus-stage1-001.err` | Corpus generator stderr — **progress lines + Ollama interactions go HERE** (Python loggers default to stderr) |
| `C:\arcis\halcyon-lab\logs\stage1-corpus.log` | Legacy corpus log filename — earlier runs only |
| `C:\arcis\halcyon-lab\logs\ollama-watchdog.log` | Watchdog event log (start, restart, circuit-break events) |
| `C:\arcis\halcyon-lab\logs\ollama-daemon.err` | Captured stderr from Ollama daemon — diagnostic on next runner crash |
| `C:\arcis\halcyon-lab\logs\ollama-daemon.out` | Captured stdout from Ollama daemon |
| `C:\arcis\halcyon-lab\data\corpus\stage1-001\entries.jsonl` | Generated corpus entries (append-only) |
| `C:\arcis\halcyon-lab\data\corpus\stage1-001\entries.jsonl.bak.<N>` | Manual backups — `.bak.<line-count>` convention before any destructive trim |
| `C:\arcis\halcyon-lab\scripts\ollama_watchdog.ps1` | Ollama watchdog (poll /api/tags, restart, capture stderr, circuit-breaker) |
| `C:\arcis\halcyon-lab\scripts\start_ollama_watchdog.bat` | Convenience launcher for the watchdog |
| `C:\arcis\halcyon-lab\.venv\` | Python virtualenv (gitignored) |
| `C:\arcis\halcyon-lab\.env` | Secrets (gitignored) |
| `C:\arcis\halcyon-lab\.claude\worktrees\` | Agent worktrees (auto-managed; safe to bulk-prune merged) |

### Render (cloud)

| Service | URL | Notes |
|---------|-----|-------|
| Cloud dashboard | https://halcyonlab.app | Static frontend + Python API |
| Postgres | Render-managed | Auto-set `DATABASE_URL` env var on cloud; mirror of local SQLite |

---

## 5. Troubleshooting Decision Trees

### "Watch loop won't start"

```
Did `python -m src.main startup` exit with error?
├─ "Another watch loop is already running (PID ...)"
│    → kill the existing PID:
│      taskkill /PID <pid> /F /T
│    → if no python process exists, lockfile is stale:
│      rm data/watch.lock
│    → retry startup
│
├─ "ARCIS_DB_PATH not set"
│    → check .env exists at C:\arcis\halcyon-lab\.env
│    → confirm ARCIS_DB_PATH=C:/arcis/data/ai_research_desk.sqlite3 is set
│
├─ "Schema drift detected"
│    → python -m src.main validate-schema --fix
│    → retry startup
│
├─ "ModuleNotFoundError: pandas_market_calendars"
│    → pip install -r requirements.txt (in .venv)
│
└─ Other → check logs/arcis.log for stack trace
```

### "Cloud dashboard shows wrong numbers"

```
Compare local vs cloud:
├─ Local /api/kpis returns expected → cloud Render didn't auto-deploy
│    → check Render service status; trigger manual redeploy if needed
│
├─ Local also returns wrong → SQLite data issue
│    → grep src/api/cloud_routes/* for the metric site
│    → check if site is using outcome_stats_filter_sql() (Wave 4 H5 work)
│    → query DB directly to see source data
│
├─ Local OK but cloud lags → RenderSyncThread issue
│    → check sync_state table for stuck in_flight rows
│    → if stuck >10 min: post-Wave-4-H1 this auto-clears on watch restart
│    → manual fix: UPDATE sync_state SET status='idle', in_flight_since=NULL WHERE host='SWIFT-PC'
│
└─ Numbers look LOW (e.g., 6 closed instead of 50) → H5 working as intended
   → reconciled_stale rows excluded from outcome counters
   → see EXCLUDED_FROM_OUTCOME_STATS in src/shadow_trading/exit_reason.py
```

### "Sync stuck"

```
1. Check sync_state for in-flight lock:
   sqlite3 C:/arcis/data/ai_research_desk.sqlite3 "SELECT * FROM sync_state WHERE status='in_progress'"

2. If row exists with old in_flight_since:
   - Post-Wave-4-H1: restart watch loop and the auto-clear runs. Fixed.
   - Pre-H1: manual UPDATE to clear status='idle'

3. If sync table cursor is wrong (last_synced_at stuck in past):
   - For live_prices specifically: python -m src.main reset-live-prices-watermark
   - For others: UPDATE sync_state SET last_synced_at = '<recent timestamp>' WHERE table_name = '<table>'
```

### "Tests failing on `tests/test_repo_structure.py`"

```
Three known patterns:
├─ test_no_file_over_400_lines:
│    → either split the file, or add to config/known_violations.json with rationale
│
├─ test_no_function_over_60_lines:
│    → extract a helper to bring it under 60
│
└─ test_todos_have_issue_numbers:
   → either add #NNNN reference to TODO comment, or remove the TODO
```

### "ModuleNotFoundError or import errors"

```
Most common: stale .venv after pulling new deps.
   → cd C:/arcis/halcyon-lab && .venv\Scripts\pip install -r requirements.txt

In a worktree (NOT main checkout):
   → worktrees don't carry .venv (gitignored)
   → use parent .venv: C:/arcis/halcyon-lab/.venv/Scripts/python.exe -m pytest ...

If tests fail in worktree but pass in main:
   → probably env-var dependency (.env not carried into worktree)
   → check tests/conftest.py for proper hermetic fixtures
```

### "Ollama crashes / corpus producing template fallbacks"

**Symptom:** `logs/corpus-stage1-001.err` shows `WARNING [src.llm.packet_writer] [LLM] Generation failed -- fallback to template for <TICKER>` repeatedly. Or `Ollama unresponsive` warnings. Or the corpus runner silently appends entries that look terse (~750-800 chars) and start with `<TICKER> is in a [strong/weak/neutral] [uptrend/downtrend/neutral]`.

```
1. Verify the watchdog is running:
   Get-Process -Name ollama* | Select-Object Id, @{n='age_min';e={[math]::Round(((Get-Date)-$_.StartTime).TotalMinutes,1)}}
   Get-CimInstance Win32_Process -Filter "name='powershell.exe'" | ?{ $_.CommandLine -match 'ollama_watchdog' } | Format-List
   - If neither: start the watchdog (see §7 "Ollama watchdog")
   - If watchdog up but circuit-broken: read logs/ollama-watchdog.log tail; circuit pause is 5 min

2. Check OLLAMA_NUM_PARALLEL matches corpus --num-parallel:
   [Environment]::GetEnvironmentVariable("OLLAMA_NUM_PARALLEL","User")
   - This rig (RTX 3060 12 GiB) is validated at 2. Higher values OOM the runner subprocess.
   - VRAM math: arcis:v1.0.0 model = ~9.12 GiB resident at NUM_PARALLEL=2.
     Browser/desktop GPU consumers (Edge, Chrome, VS Code) use ~1.5 GiB. Total ~10.6 GiB
     of 12 GiB available; ~1.7 GiB cushion. NUM_PARALLEL=4 needs ~10.4 GiB resident
     leaving ~0.4 GiB cushion — any GPU spike (browser tab, video) tips it over.

3. Audit existing entries for fallback contamination:
   python -c "import json,re,sys; t=re.compile(r'^[A-Z]+ is in a (strong |weak |)?(uptrend|downtrend|neutral)'); short_template=long_real=0
   with open('data/corpus/stage1-001/entries.jsonl','rb') as f:
     for line in f:
       try: e=json.loads(line); c=len(e.get('response','')); m=t.match(e.get('response',''))
       except: continue
       if c<1500 and m: short_template+=1
       elif c>=1500 and not m: long_real+=1
   print(f'definite fallback: {short_template}; definite real: {long_real}')"
   - If fallback count is non-zero: trim before resuming (next step)

4. Trim fallback contamination (DESTRUCTIVE — keep backup):
   cd data/corpus/stage1-001
   cp entries.jsonl entries.jsonl.bak.$(wc -l < entries.jsonl | tr -d ' ')
   python -c "import json,re; t=re.compile(r'^[A-Z]+ is in a (strong |weak |)?(uptrend|downtrend|neutral)')
   with open('entries.jsonl','rb') as i, open('entries.jsonl.tmp','wb') as o:
     for line in i:
       try: e=json.loads(line); c=len(e.get('response','')); m=t.match(e.get('response',''))
       except: o.write(line); continue
       if c<1500 and m: continue
       o.write(line)"
   mv entries.jsonl.tmp entries.jsonl

5. Restart Ollama clean:
   - Watchdog will detect stale daemon and restart automatically
   - Or manually: Get-Process -Name ollama* | Stop-Process -Force; & "C:\Users\mille\AppData\Local\Programs\Ollama\ollama.exe" serve

6. Resume corpus with --num-parallel 2 (see §3 "Corpus generation")
```

Root cause finding (2026-05-06): `packet_writer.py` has 5 fallback paths that all silently write template entries with the same `model_version="arcis:v1.0.0"` — indistinguishable from real LLM at training time. Discriminator: real LLM responses are 2400-3000 chars and start with natural-language analysis; templates are 750-800 chars and start with the rigid `<TICKER> is in a <trend>` prefix. Permanent fix is a forthcoming packet_writer change: either skip-write on fallback OR distinguish via `model_version="template_fallback"`.

### "Corpus is not progressing"

The corpus runner appears to be running (`python scripts/generate_llm_corpus.py` process is up) but the entry count in `entries.jsonl` is not growing, or is growing much slower than the expected ~2 entries/min at `--num-parallel 2`.

```
1. Is Ollama responding?
   curl http://127.0.0.1:11434/api/tags
   ├─ Returns JSON within 1s → Ollama is healthy; skip to step 2
   ├─ Returns JSON but takes >5s → Ollama is under memory pressure; reduce parallelism
   └─ No response / empty after 5s → Ollama is hung
         → Check the watchdog: Get-CimInstance Win32_Process -Filter "name='powershell.exe'" |
           ?{ $_.CommandLine -match 'ollama_watchdog' }
         → If watchdog is up: wait for it to auto-restart Ollama (up to 30s poll interval)
         → If watchdog is down: restart it (see §7 "Ollama watchdog")
         → If watchdog circuit-broken: tail logs/ollama-watchdog.log — 3 restarts in 10min
           pause it; investigate logs/ollama-daemon.err before resuming

2. Is --num-parallel exceeding available VRAM?
   nvidia-smi
   ├─ GPU memory: if "MiB used" is near total (e.g., 11500/12288 MiB) → OOM risk
   ├─ GPU utilization: if oscillating 0→100 rapidly or showing throttle events → pressure
   └─ Confirmed OOM → restart corpus with --num-parallel 1 (halves throughput but stable)
   VRAM math for RTX 3060 (12 GiB):
   - arcis:v1.0.0 at NUM_PARALLEL=2: ~9.12 GiB model + ~1.5 GiB browser/desktop = ~10.6 GiB
   - Browser tabs / VS Code GPU usage can push this to 11+ GiB → OOM crash
   - RTX 3090 (24 GiB) will support NUM_PARALLEL=4 comfortably (~11 GiB + 4 GiB headroom)
   Fix: close GPU-heavy browser tabs, reduce Chrome/Edge hardware acceleration, or drop
   --num-parallel to 1

3. Is the watch loop competing for GPU during market hours?
   During US market hours (09:30–16:00 ET), the intraday scan loop makes Ollama inference
   calls every 5 minutes. These starve the corpus generator on the same GPU context.
   Symptom: corpus throughput drops from ~2 entries/min to ~0.5 or stalls entirely during
   market hours; resumes overnight when the scan loop is idle.
   Fix: schedule corpus generation to run overnight only (16:00 ET → 07:00 ET). Use the
   WMI launch pattern (see §7 "SSH-safe process launch") with a start-time delay, or
   simply stop/resume the corpus runner around market hours manually.

4. If none of the above — check for fallback contamination:
   python -c "import json,re,sys; t=re.compile(r'^[A-Z]+ is in a'); count=0
   with open('data/corpus/stage1-001/entries.jsonl','rb') as f:
     for line in f:
       try: e=json.loads(line); c=len(e.get('response','')); m=t.match(e.get('response',''))
       except: continue
       if c<1500 and m: count+=1
   print(f'template fallback entries: {count}')"
   - Non-zero count means Ollama was crashing silently → see §5 "Ollama crashes" for cleanup
```

### "Database is locked" errors

```
Most common: external tool holding file handle.
├─ Close MS Access / DBeaver / DB Browser for SQLite
├─ Wait ~60 seconds for Windows to release the handle
└─ Retry the operation

If watch loop is the culprit (rare):
   → use sqlite3 -readonly for inspection
   → or read-only Python connection: sqlite3.connect('file:...?mode=ro', uri=True)
```

### "Long-running process won't survive my SSH session closing"

```
Symptom: corpus runner / watchdog dies when you close PuTTY / OpenSSH client.
Root cause: `Start-Process` and `python ... &` both spawn child processes
that inherit the SSH session's job object. Closing SSH terminates the job.

Fix: launch via WMI Win32_Process.Create. The Task Scheduler / service
infrastructure spawns the process in Session 0 (the services session), so
it persists across user/SSH session changes.

# PowerShell pattern:
$cmd = 'cmd.exe /c "cd /d C:\arcis\halcyon-lab && B:\Python\python.exe scripts/foo.py >> logs/foo.out 2>> logs/foo.err"'
$result = Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{CommandLine = $cmd}
Write-Output "PID: $($result.ProcessId), ReturnValue: $($result.ReturnValue)"  # 0 = success

# Verify the process is in Session 0 (not your user session):
Get-CimInstance Win32_Process -Filter "ProcessId=$($result.ProcessId)" | Select-Object SessionId
# Compare with $PID's session — should differ if your shell is in a user session.

# To stop the WMI-launched process:
Stop-Process -Id <pid> -Force
```

See §7 "SSH-safe process launch" for the canonical patterns (corpus runner + watchdog).

---

## 6. Recovery Patterns

### Lost work after stash-pop or interrupted commit

```bash
# Find dangling commits (recoverable for ~90 days before git gc)
git fsck --lost-found
# Inspect each:
git show <sha>
# Restore to a recovery branch:
git checkout -b recovery/<name> <sha>
```

### Corrupted SQLite WAL after power loss

```bash
# 1. Make a backup
copy C:\arcis\data\ai_research_desk.sqlite3 C:\arcis\data\ai_research_desk.sqlite3.bak

# 2. Try recovery
sqlite3 C:/arcis/data/ai_research_desk.sqlite3 ".recover" > recovery.sql
sqlite3 C:/arcis/data/ai_research_desk_recovered.sqlite3 < recovery.sql

# 3. Validate
python -m src.main validate-schema  # against the recovered DB

# 4. UPS investment recommended to prevent recurrence (CyberPower CP1500PFCLCD ~$220)
```

### Stuck Alpaca paper positions (phantom orphans)

Symptom: same tickers re-appearing in shadow_trades as `order_type='reconciled'` with `exit_reason='reconciled_stale'` repeatedly.

```
1. Log into Alpaca paper account UI (paper.alpaca.markets)
2. Cancel all open orders for the affected tickers
3. If positions show, use "Close All Positions"
4. Restart watch loop
5. Verify no new reconciled_stale rows for 24h:
   sqlite3 C:/arcis/data/ai_research_desk.sqlite3 \
     "SELECT ticker, COUNT(*) FROM shadow_trades WHERE exit_reason='reconciled_stale' AND created_at > datetime('now', '-1 day') GROUP BY ticker"
```

This is the operator-side companion to Wave 5's code-level guard (6h re-backfill cooldown in `reconcile.py`).

### Reverting a bad PR

```
NEVER force-push to main.

Safe rollback:
1. Find the merge commit SHA: git log origin/main --oneline
2. Create a revert PR:
   git checkout -b revert/<pr-num> origin/main
   git revert -m 1 <merge-sha>
   git push origin revert/<pr-num>
   gh pr create --title "revert: PR #NNN" --body "..."
3. Merge the revert PR.
```

### CHANGELOG.md conflict during sequential PR merges

```
Symptom: PR you opened earlier is now CONFLICTING after another PR merged
to main, conflict is in CHANGELOG.md only.

Root cause: both PRs added a new bullet at the top of the [Unreleased]
section. Git's auto-merge can't decide ordering — it surfaces a conflict.

Resolution (one-shot):
1. git checkout -b <pr-branch>-resolve origin/<pr-branch>
2. git merge origin/main
   → Auto-merging CHANGELOG.md
   → CONFLICT (content): Merge conflict in CHANGELOG.md
3. Open CHANGELOG.md, locate the conflict block:
   <<<<<<< HEAD
   - **<your PR's entry>**
   =======
   - **<the entry that landed first>**
   >>>>>>> origin/main
4. Keep both entries, in order: yours first (it's the "newer" one being
   merged on top), the other entry second. Remove the conflict markers.
5. git add CHANGELOG.md && git commit -m "Merge origin/main into <branch>
   -- resolve CHANGELOG conflict (keep both entries)"
6. git push origin <pr-branch>-resolve:<pr-branch>

The squash-merge will collapse the merge commit; only your original
content shows up in main's history.
```

### Total restart from a bad state (the "I don't know what's wrong, just get me back to clean")

When sanity is lost — duplicate watch loops, stale lockfile, Ollama in unknown state, corpus runner orphaned, stuck broker state — and you want to get back to a known-good baseline without forensics. Run in this exact order; each step is idempotent.

```powershell
# 1. Stop EVERYTHING ARCIS-related on this machine.
Get-CimInstance Win32_Process -Filter "name='python.exe'" | ?{ $_.CommandLine -match 'src.main|generate_llm_corpus|ollama_watchdog' } | %{ Stop-Process -Id $_.ProcessId -Force }
Get-CimInstance Win32_Process -Filter "name='powershell.exe'" | ?{ $_.CommandLine -match 'ollama_watchdog' } | %{ Stop-Process -Id $_.ProcessId -Force }
Get-Process -Name "ollama*" -ErrorAction SilentlyContinue | Stop-Process -Force

# 2. Clear any stale lockfiles. (PID lock check would refuse startup otherwise.)
Remove-Item C:\arcis\halcyon-lab\data\watch.lock -ErrorAction SilentlyContinue

# 3. Confirm broker state. Open paper.alpaca.markets in a browser. Note: are
#    there positions / open orders that don't appear in your local DB? If yes,
#    follow §6 "Stuck Alpaca paper positions" before continuing.

# 4. Verify schema (auto-fix any drift).
cd C:\arcis\halcyon-lab
python -m src.main validate-schema --fix

# 5. (Optional) Health check the database file.
python -c "import sqlite3; c=sqlite3.connect('file:C:/arcis/data/ai_research_desk.sqlite3?mode=ro',uri=True); c.execute('PRAGMA quick_check').fetchone()"
# Should print ('ok',). Anything else → §6 "Corrupted SQLite WAL after power loss".

# 6. Restart Ollama watchdog (will start Ollama itself).
$cmd = 'powershell.exe -NoProfile -ExecutionPolicy Bypass -File C:\arcis\halcyon-lab\scripts\ollama_watchdog.ps1'
Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{CommandLine = $cmd}

# 7. Restart watch loop.
python -m src.main startup

# 8. Verify with the §0.10 quick health check.
```

After step 8, run the §0.10 health-check one-liner. If everything is green, you're back to operational. If anything is still red, you're past "just-restart" territory — drop into the targeted §5 troubleshooting tree for that specific symptom.

### Worktree cleanup (post-merge)

```bash
# Find merged worktrees:
git worktree list

# Remove a specific worktree:
git worktree remove C:/arcis/halcyon-lab-wt-XXX

# If permission denied (Windows file lock):
# - Close any IDE / editor open on that path
# - Wait for any background pytest processes to release .pytest_cache locks
# - Retry, or use PowerShell:
#   powershell -Command "Remove-Item -Recurse -Force C:\arcis\halcyon-lab-wt-XXX"

# Bulk-prune metadata for already-deleted worktrees:
git worktree prune

# After all worktrees gone, delete merged branches:
git branch -D <branch-name>
```

---

## 7. Maintenance Tasks

### Daily strategy promotion confirmation (Sprint 2 T5)

The methodology gate runs nightly (via the watch loop or manually). When it emits a
`gate_proposal` row with `decision='defer'`, the operator reviews the evidence and
either confirms or ignores the proposal.

**Typical daily workflow:**
1. Review today's gate proposals (check Telegram notification or query the DB):
   ```sql
   SELECT strategy_id, gate_result_json, timestamp
   FROM strategy_promotion_events
   WHERE triggered_by = 'gate_proposal'
     AND timestamp > datetime('now', '-24 hours')
   ORDER BY timestamp DESC;
   ```

2. If the evidence looks good, confirm via the CLI:
   ```bash
   python -m src.main confirm-promotion \
     --strategy <strategy_id> \
     --justification "30-day shadow pass rate 88%; DSR 0.97; WF outcome PASS. Ready for shadow." \
     --yes
   ```

3. The CLI delegates to `promote(triggered_by='operator_confirm')` which:
   - Re-fires `check_promotion_gate` server-side (catches data drift between proposal and confirm)
   - Writes the audit row with `triggered_by='operator_confirm'` and `from_status != to_status`
   - Exits 0 on success, prints `event_id=<N> final_status=<status>`

**If the re-fire rejects:** the CLI prints the rejection reason and exits non-zero.
No event row is written. Re-run the daily gate after the data is corrected.

**Decision 4 guard:** If the latest proposal has `decision='reject'`, the CLI refuses
before prompting. A reject is not operator-overridable via this command.

**Staleness guard (Decision 14):** Proposals older than 24h are rejected at the CLI level.
Re-run the daily gate to generate a fresh proposal before confirming.

### Stage 1 corpus regeneration / resume

The Stage 1 corpus is generated by Ollama (local fine-tuned Qwen3-8B) over a multi-day run. Goal: 67,681 entries covering 2023-09-01 to 2026-04-28.

**Two prerequisites before any corpus run:**
1. Watchdog must be running (see "Ollama watchdog" below). Without it, an Ollama crash silently produces template-fallback entries (~16% of historical corpus was contaminated this way pre-2026-05-06; see §5 "Ollama crashes").
2. `OLLAMA_NUM_PARALLEL=2` user env var. Validated stable on RTX 3060 12 GiB. NUM_PARALLEL=4 OOMs the runner subprocess.

**To start fresh:**
```bash
python scripts/generate_llm_corpus.py \
  --corpus-id stage1-001 \
  --window-start 2023-09-01 \
  --window-end 2026-04-28 \
  --num-parallel 2
```

**To resume after stop / hang / restart:**
```bash
python scripts/generate_llm_corpus.py \
  --corpus-id stage1-001 \
  --window-start 2023-09-01 \
  --window-end 2026-04-28 \
  --resume \
  --num-parallel 2
```

The `--resume` flag dedup's by `(as_of, ticker)` against existing entries.jsonl — safe to invoke repeatedly.

**To monitor progress:**
```bash
# Logs (current run uses .out and .err split):
tail -f C:/arcis/halcyon-lab/logs/corpus-stage1-001.err   # progress lines + Ollama messages here
tail -f C:/arcis/halcyon-lab/logs/corpus-stage1-001.out   # stdout (typically empty unless Python prints)

# Entry count:
wc -l C:/arcis/halcyon-lab/data/corpus/stage1-001/entries.jsonl

# Quick fallback-contamination audit (real LLM should dominate):
grep -c "Using Ollama path" C:/arcis/halcyon-lab/logs/corpus-stage1-001.err
grep -c "fallback to template" C:/arcis/halcyon-lab/logs/corpus-stage1-001.err
```

**Healthy throughput:** ~2 entries/min at `--num-parallel 2` → ~67,681 entries / (2 × 60 × 24) ≈ 23 days for a full run from scratch. From a partial state (e.g. 27,000 already generated), remaining ETA scales accordingly.

**For SSH-disconnect-safe runs**, use the WMI launch pattern below ("SSH-safe process launch") instead of running the command directly in your shell.

### Ollama watchdog

Background-monitor that polls `http://127.0.0.1:11434/api/tags` every 30s and auto-restarts Ollama on death. Closes the diagnostic gap from running `Start-Process -WindowStyle Hidden` (which discards stderr); the watchdog redirects stderr to `logs/ollama-daemon.err` so the next CUDA OOM is operator-visible.

**Start (operator at console / RDP):**
```bash
scripts\start_ollama_watchdog.bat
```
Logs accumulate at `logs/ollama-watchdog.log`. Tail to monitor.

**Start (SSH-disconnect-safe):** use the WMI pattern in "SSH-safe process launch" below with this command:
```powershell
$cmd = 'powershell.exe -NoProfile -ExecutionPolicy Bypass -File C:\arcis\halcyon-lab\scripts\ollama_watchdog.ps1'
Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{CommandLine = $cmd}
```

**Verify it's working:**
```powershell
Get-CimInstance Win32_Process -Filter "name='powershell.exe'" | ?{ $_.CommandLine -match 'ollama_watchdog' } | Format-List ProcessId, CreationDate
Invoke-WebRequest -Uri "http://127.0.0.1:11434/api/tags" -UseBasicParsing -TimeoutSec 5
```

**Stop the watchdog:**
```powershell
Get-CimInstance Win32_Process -Filter "name='powershell.exe'" | ?{ $_.CommandLine -match 'ollama_watchdog' } | %{ Stop-Process -Id $_.ProcessId -Force }
```

**Circuit breaker:** 3 restarts in any rolling 10-minute window pauses the watchdog for 5 minutes and dumps last 10 lines of `daemon.err` to the watchdog log. Indicates persistent driver/hardware issue (not transient OOM). Investigate before resuming the corpus.

**Configuration overrides:** `$env:OLLAMA_EXE` to override the Ollama binary path; otherwise resolution is `$env:OLLAMA_EXE → on PATH → C:\Users\mille\AppData\Local\Programs\Ollama\ollama.exe`.

### SSH-safe process launch (Win32_Process via WMI)

When you launch a long-running process from an SSH session — corpus runner, watchdog, anything — `Start-Process` and `python ... &` both inherit your SSH session's job object. Closing SSH terminates the job, killing all children. **WMI Win32_Process.Create launches in Session 0 (services), independent of any user / SSH session.**

**Canonical pattern (single command):**
```powershell
$cmd = 'cmd.exe /c "cd /d C:\arcis\halcyon-lab && set PYTHONUNBUFFERED=1 && B:\Python\python.exe scripts/foo.py >> logs/foo.out 2>> logs/foo.err"'
$result = Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{CommandLine = $cmd}
Write-Output "PID: $($result.ProcessId), ReturnValue: $($result.ReturnValue)"   # 0 = success
```

**Verify Session 0 (the persistence guarantee):**
```powershell
Get-CimInstance Win32_Process -Filter "ProcessId=$($result.ProcessId)" | Select-Object SessionId, ParentProcessId
# SessionId should be 0
```

**Two specific recipes:**

1. **Corpus runner** (the one you'll use most):
   ```powershell
   $cmd = 'cmd.exe /c "cd /d C:\arcis\halcyon-lab && set PYTHONUNBUFFERED=1 && B:\Python\python.exe scripts/generate_llm_corpus.py --corpus-id stage1-001 --window-start 2023-09-01 --window-end 2026-04-28 --num-parallel 2 --resume >> logs/corpus-stage1-001.out 2>> logs/corpus-stage1-001.err"'
   Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{CommandLine = $cmd}
   ```

2. **Watchdog**:
   ```powershell
   $cmd = 'powershell.exe -NoProfile -ExecutionPolicy Bypass -File C:\arcis\halcyon-lab\scripts\ollama_watchdog.ps1'
   Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{CommandLine = $cmd}
   ```

**To stop a WMI-launched process:** `Stop-Process -Id <pid> -Force`. The WMI launch was just a means of detachment; once running, it's a normal process.

**Caveats:**
- Win32_Process inherits the calling user's environment. If you've `setx OLLAMA_NUM_PARALLEL 2` in another session, this session may not see it until shell restart.
- `cmd.exe /c` wrapping is needed for shell features (`cd /d`, `&&` chaining, redirects). Without it, the command runs raw with no cwd / no redirects.
- SessionId=0 is the services session — no GUI. Anything requiring a GUI (Excel automation, etc.) should NOT use this pattern.

### Watchdog timeout signs

The watch loop writes a heartbeat to `data/watchdog.txt` on each iteration. This is your primary liveness indicator.

**Normal heartbeat cadence:**
- During US market hours (09:30–16:00 ET): file `LastWriteTime` updates every ~30s (scan loop runs every 5 min; heartbeat written at the top of each iteration before task dispatch)
- Outside market hours (overnight, weekends): updates every 5–10 min (overnight tasks are longer; the loop blocks on them)
- During corpus generation (watch loop idle, corpus running): the watch loop still ticks but may pause for 60–90s on long scans

**Signs the watch loop is stuck (>5 min stale heartbeat during market hours):**

```powershell
# Quick check:
Get-Item C:\arcis\data\watchdog.txt | Select-Object LastWriteTime
# If LastWriteTime is >5 min ago during trading hours → investigate

# Full health check (§0.10 one-liner):
Get-CimInstance Win32_Process -Filter "name='python.exe'" |
  ?{ $_.CommandLine -match 'src.main startup' } |
  Select-Object ProcessId, @{n='age_min';e={[math]::Round(((Get-Date)-$_.CreationDate).TotalMinutes,1)}}
# If no process → loop died; if process exists but heartbeat stale → loop is blocked
```

**When to investigate:**
- Heartbeat >5 min stale during 09:30–16:00 ET → likely blocked on Ollama call or DB lock
- Heartbeat >15 min stale at any time → treat as hung; restart with NSSM (`nssm restart arcis-watch`)
- Heartbeat file missing entirely → watch loop never started; check `data/watch.lock` for stale PID

**Cross-reference:** The Ollama watchdog (§7 "Ollama watchdog") is a SEPARATE process from the watch loop. `data/watchdog.txt` is written by the watch loop (`src/scheduler/watch.py`), not the Ollama watchdog script. Both can be alive independently.

**Kill-switch policy (post Sprint 4 hotfix #1038):** Auto-halts no longer fire from the auditor. The risk governor (`src/risk/governor.py`) enforces operator-only halt sources via `_HALT_ALLOWED_SOURCES = {"cli", "dashboard", "api", "test"}`. Any attempt to halt trading from an auditor code path raises `HaltSourceForbiddenError`. Manual halt paths: (1) CLI: `python -m src.main halt`, (2) Dashboard: kill-switch button, (3) API: `POST /api/halt`. A stale `watchdog.txt` is NOT an automatic halt signal — investigate and restart manually.

### Schema migration to Render Postgres

After any schema change in `src/schema/registry.py`:
```bash
# 1. Update local SQLite
python -m src.main validate-schema --fix

# 2. Sync to Postgres
python scripts/render_migrate.py
# (DATABASE_URL must be set; pulls from settings.local.yaml or env)

# 3. Verify Postgres matches registry
# (script reports any drift)
```

### Dependabot bulk merge

Periodically the repo accumulates dependabot PRs (Python deps + frontend deps).
```
Process:
1. gh pr list --author app/dependabot --json number,headRefName,mergeStateStatus
2. For each CLEAN PR: review the diff, gh pr merge <num> --squash --delete-branch
3. UNSTABLE PRs: usually base is stale — gh pr comment <num> "@dependabot rebase"
4. After bulk merges: pull main + run `pip install -r requirements.txt`
```

### Worktree + branch hygiene

Quarterly (or when worktrees exceed ~30):
```
1. git worktree list | wc -l   # how many worktrees?
2. git branch | wc -l           # how many branches?

3. Identify safe-to-prune (per session 2026-05-04 audit pattern):
   - Branches that are ancestors of origin/main (merged via fast-forward / merge-commit)
   - Branches matching headRefName of merged PRs (squash-merged)
   - Detached HEADs reachable via origin/* refs

4. Bulk prune (see Recovery Patterns § Worktree cleanup)

5. Delete merged branches: git branch -D <branch>
```

### Watch loop restart sequence

```bash
# Clean restart (preferred):
1. taskkill /PID <watch-pid> /F /T
2. rm data/watch.lock  # if stale
3. python -m src.main startup

# After PR merges that change config or schema:
1. git pull origin main
2. python -m src.main validate-schema --fix
3. python scripts/render_migrate.py  # if schema changed
4. (any post-merge runbook actions per PR body)
5. python -m src.main startup
```

---

## 8. Glossary

| Term | Definition |
|------|------------|
| **Alpaca paper** | Alpaca's simulated trading environment; uses real market data but no real money |
| **Backtester** | `src/evaluation/backtester.py` — runs strategy against historical data via `backtest_model()` |
| **Bootcamp mode** | Auditor flag (`bootcamp_mode = closed_count < 50`) that downgrades CRITICAL alerts to ALERTs during early data-collection phase. Post-Wave-4-H7: sticky once operator sets `live_trading.post_bootcamp: true` |
| **Build score** | Composite quality score for the strategy. Built from many counters; key inputs come from `src/evaluation/build_score.py` |
| **Corpus** | LLM-generated training data. Stage 1 = baseline data (~67K entries); Stage 2 = post-baseline retraining data |
| **Excess Sharpe** | Sharpe of (strategy returns - SPY returns). The promotion gate target is excess Sharpe ≥ 0.5 over 150 OOS trades |
| **HSHS** | "Halcyon Self-Health Score" — composite system health metric in `src/evaluation/hshs.py` and `src/evaluation/hshs_live.py` |
| **Instrumented trade** | A closed trade with all required telemetry columns populated (per `src/analytics/instrumentation_filter.py`). Stage 1 baseline cohort uses only instrumented trades |
| **MinTRL** | Bailey-LdP "Minimum Track Record Length" — sample size needed to detect a Sharpe at given confidence. ~80-150 trades for Sharpe ≥ 0.5 detection |
| **OOS** | Out-of-sample. Stage 1 OOS validation = 30+ trades at t > 1.0 (sub-validation completing Stage 1, NOT Stage 2). See §9 for the canonical ladder |
| **PBO** | Probability of Backtest Overfitting (Bailey-LdP 2014, CSCV). On the methodology shelf |
| **PIT** | Point-in-time. A PIT-clean computation only uses data that was available AT the as_of date. SP100 PIT membership lookup in `src/universe/pit.py` |
| **Promotion gate** | ≥4-of-5 voting gate (PSR/DSR/PBO/MC permutation/White's RC) in `src/methods/promotion_gate.py`. Live in production as of Sprint 2; fires daily at 16:35 ET via watch.py. See §10 for operational guide |
| **Reconciled_stale** | `exit_reason` value set when reconciler closes a shadow_trade that no longer exists at the broker. NOT a real strategy outcome — a bookkeeping artifact. Excluded from outcome stats (Wave 4 H5 + #919/#920 — `EXCLUDED_FROM_OUTCOME_STATS` constant) |
| **RenderSyncThread** | Background thread (`src/sync/render_sync.py`) that replicates local SQLite → Render Postgres. Per-table cursor in `sync_state` table |
| **SD#NN** | Strategic Decision identifier. Used in `MASTER.md` as governing-decision tags (e.g., SD#41 REVISED, SD#43, SD#46). Each SD documents an operator-level decision with rationale that subsequent code changes must respect. Example: SD#43 is the 3-stage validation ladder definition; any code change to the promotion gate logic must cite and respect SD#43. SD numbers are assigned sequentially as new governing decisions are made. |
| **Shadow trade** | Paper trade tracked in our DB (`shadow_trades` table). Mirrors broker-side state |
| **Sprint base branch** | A branch holding sprint specs as deliverable-0 commits (e.g. `sprint/wave-4-hotfixes/base`). Code lands via separate PRs against main |
| **Stage 1 / 2 / 3** | Three-stage validation ladder per MASTER.md SD#43. Stage 1 = baseline signed (`d651160`) + Stage 1 OOS sub-validation (excess-mean > 0 at t > 1.0 over 30 OOS); Stage 2 = IB-eligibility (excess Sharpe ≥ 0.5 over 150 OOS + ≥4-of-5 promotion gate); Stage 3 = full ramp (excess Sharpe > 1.0 over 300 OOS). See §9 for canonical text |
| **Subtract_trading_days** | NYSE-calendar-aware helper in `src/scheduler/holidays.py`. ALWAYS use for fetch anchors / lookback windows. Background: #888 / #106 incident traced corpus + backtester silent data gaps to 365-day calendar approximation drift |
| **T-A1, T-B3, etc.** | Sprint task identifiers (T = Task). e.g., Sprint 1.A Wave 2/3 had T-A1 (live_prices time column), T-B3 (backtester subtract_trading_days), etc. |
| **Walkforward** | `src/evaluation/walkforward.py` — anchored cross-validation. R1-R8 rigor requirements per pre-reg addendum |
| **Watch loop** | Main runtime daemon (`src/scheduler/watch.py::WatchLoop`). Single instance per host (PID lockfile) |
| **(Ollama) Watchdog** | `scripts/ollama_watchdog.ps1` — separate from the watch loop. Polls `/api/tags` every 30s, auto-restarts Ollama on death, captures daemon stderr to `logs/ollama-daemon.err` for crash diagnostics. Required before any corpus generation run. See §7 |
| **Worktree** | Independent git working directory sharing the same `.git` repo. Used for parallel agent isolation |
| **Template-fallback entry** | A corpus entry written by `packet_writer.py` when the LLM call failed (Ollama unreachable / parse failure / etc.). Discriminator: response < 1500 chars AND starts with rigid `<TICKER> is in a [strong\|weak]? (uptrend\|downtrend\|neutral)` prefix. Currently shares `model_version="arcis:v1.0.0"` with real LLM entries — a forthcoming packet_writer change will add distinct tagging. Real LLM responses are 2400-3000 chars and start with natural-language analysis |
| **WMI launch / Session 0** | `Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{CommandLine=...}`. Launches a process detached from the calling session — survives SSH disconnect. Process lands in Session 0 (services), no GUI. Use for corpus + watchdog + any long-running ops process. See §7 |

---

## 9. Roadmap pointer

The strategic roadmap lives in **MASTER.md**:
- **§Sprint queue** — what's planned
- **§Current state metrics** — closed trades, model version, baseline status
- **§Sprint history** — what's been done
- **§Known blockers** — open obstacles to live trading

The 3-stage validation ladder for live trading (canonical: MASTER.md SD#43):

1. **Stage 1** — Baseline signed (`d651160`); 35 instrumented trades; rf-adjusted excess Sharpe 6.14 (regime-tailwind suspected); SPY-relative p=0.43 (non-significant)
   - *Stage 1 OOS validation*: excess-mean > 0 at t > 1.0 over 30 OOS trades (NOT YET STARTED)
2. **Stage 2** — IB-eligibility threshold: excess Sharpe ≥ 0.5 at p < 0.05 over 150 OOS trades + ≥4-of-5 promotion gate (PSR/DSR/PBO/MC permutation/White's RC). Gate is now live in the promotion path (Sprint 2). See §10 for operational detail.
3. **Stage 3** — Full ramp threshold: excess Sharpe > 1.0 at p < 0.05 over 300 OOS trades.

The methodology gate is **live** as of Sprint 2 (T1–T8 merged). The daily 16:35 ET sweep fires it automatically. See §10 "Daily methodology-gate workflow" for the full operational guide.

---

## 10. Daily methodology-gate workflow

> **Sprint 2 closeout section.** The methodology gate is live. This section is your operational reference for reading the daily gate digest, interpreting evidence JSON, troubleshooting defer outcomes, and knowing when (and how) to promote. For the CLI syntax, see §3 "Strategy promotion confirmation". This section covers the *interpretation* layer on top of that mechanical layer.
>
> **Spec reference**: `docs/audits/2026-05-05-methodology-gate-wiring/spec.md` §T9 + §1.2 + §1.3.1 + §3.2 + §9.1.

### 10.1 What the daily 16:35 ET sweep does

Every trading day at 16:35 ET, immediately after post-close reconciliation completes, `watch.py` fires the methodology gate orchestrator:

```
WatchLoop._run_sync_body  →  run_daily_gate_for_all_active_strategies(db_path, notify=...)
```

The orchestrator iterates every strategy returned by `get_strategies_by_status(['shadow_trading', 'backtested'])` and for each one:

1. Loads the strategy's shadow trades, keeping only rows where `is_fully_instrumented(row) == True` AND `actual_entry_time IS NOT NULL` AND `pnl_pct IS NOT NULL`. Partially-instrumented or undated rows are silently excluded; their count is recorded in `details.instrumentation_excluded_count`.
2. Builds the `MethodInputs` payload (returns, dates, directions). The system is long-only, so `directions = [+1] * N`.
3. Calls the 4-of-5 voting gate (`src/methods/promotion_gate.py`).
4. Persists a **`triggered_by='gate_proposal'`** row to the `strategy_promotion_events` table with `from_status == to_status` (no actual transition) and `justification_note = NULL`. This is an audit / observation row only.
5. If `is_telegram_enabled()`, sends a Telegram message via `_notify_gate_proposal`. Regardless of Telegram, logs `[METHODOLOGY_GATE] proposal for <id>: decision=<decision>` to `logs/arcis.log`.

**Key points:**
- The gate fires exactly once per trading day (idempotent flag `_strategy_gate_done`).
- If the watch loop restarts mid-day after 16:35, the flag stays `False` until the day rolls; the gate re-runs.
- With `METHODOLOGY_GATE_ENABLED=false`, the gate short-circuits: `(True, {'decision':'skipped'})` is returned, NO row is written, NO Telegram is sent. See §10.7 for the full flag matrix.

### 10.2 How to read the daily digest

**Telegram** (when enabled): You receive one message per strategy evaluated. Typical format:

```
[METHODOLOGY_GATE] proposal for <strategy_id>: decision=defer
```

**`logs/arcis.log`**: Same message, always written regardless of Telegram status. Search for `METHODOLOGY_GATE` to find all gate events for a day.

**Database** (authoritative record):
```sql
SELECT strategy_id, from_status, gate_result_json, timestamp
FROM strategy_promotion_events
WHERE triggered_by = 'gate_proposal'
  AND timestamp > datetime('now', '-24 hours')
ORDER BY timestamp DESC;
```

The `gate_result_json` column holds the complete evidence dict — this is what you need to interpret (see §10.3).

**When `decision='promote'`**: The methodology gate saw ≥4-of-5 (or ≥4-of-4 under fallback) passing votes. Check `composed_pass` in the evidence to see if the full AND-composition (methodology + walkforward + DSR + PBO) also cleared. You MUST still run the confirm-promotion CLI to actuate the transition — see §10.4.

**When `decision='defer'`**: The gate could not reach quorum (too many abstentions). Review the evidence (§10.3) and troubleshoot (§10.5).

**When `decision='reject'`**: ≥2 votes failed or the inverse hard-block fired. This is NOT operator-overridable via the CLI. Fix the underlying issue.

### 10.3 How to interpret the evidence JSON

The `gate_result_json` column stores a nested dict. Key fields:

```json
{
  "methodology_gate": {
    "decision": "promote | reject | defer",
    "threshold_used": "4_of_5 | 4_of_4_no_white_rc",
    "votes": {
      "cpcv":            true | false | null,
      "block_bootstrap": true | false | null,
      "mc_perm":         true | false | null,
      "psr_dsr":         true | false | null,
      "white_rc":        true | false | null
    },
    "details": {
      "n_pass":        2,
      "n_fail":        1,
      "n_abstentions": 2,
      "instrumentation_excluded_count": 5,
      "cpcv":            { "value": 0.72, "threshold": 0.6, ... },
      "block_bootstrap": { "value": 0.04, "threshold": 0.05, ... },
      "mc_perm":         { "value": 1.0,  "threshold": 0.05, "reason": "long-only degeneracy" },
      "psr_dsr":         { "value": 0.91, "threshold": 0.5,  ... },
      "white_rc":        { "value": null, "threshold": null,  "reason": "abstained: insufficient candidate_pool" }
    }
  },
  "walkforward_status":       "no_data_yet | pass | fail | inconclusive",
  "walkforward_outcome_state": "...",
  "composed_pass": true | false
}
```

**Field-by-field reference** (spec §3.2):

| Field | Possible values | What it means |
|---|---|---|
| `decision` | `'promote'`, `'reject'`, `'defer'` | Gate conclusion for this run |
| `threshold_used` | `'4_of_5'` (default), `'4_of_4_no_white_rc'` | Fallback when `candidate_pool < 2` (White RC cannot vote without peers) |
| `votes.<name>` | `true`, `false`, `null` | `null` = abstention (method could not run; does NOT count as fail) |
| `details.n_pass` | integer | Count of `true` votes |
| `details.n_fail` | integer | Count of `false` votes |
| `details.n_abstentions` | integer | Count of `null` votes |
| `details.instrumentation_excluded_count` | integer | Rows dropped by `is_fully_instrumented` filter before the gate ran |
| `details.<name>.value` | numeric or null | The test statistic for this method |
| `details.<name>.threshold` | numeric or null | The pass/fail threshold |
| `details.<name>.reason` | string (when present) | Why the method abstained or produced an unusual result |
| `walkforward_status` | `'no_data_yet'`, `'pass'`, `'fail'`, `'inconclusive'` | Walkforward gate result (see §10.6 for `'no_data_yet'`) |
| `walkforward_outcome_state` | same values or `None` | Legacy column; kept for backwards-compat alongside `walkforward_status` |

**Vote names are exact** — `mc_perm` (not `mc_permutation`), `psr_dsr` (not `psr` or `dsr`). No `pbo` key exists in the `votes` dict (PBO is a separate legacy gate surfaced in `existing_gates.pbo_passes`, not a methodology vote). No top-level `tally` key (counts are in `details`).

### 10.4 Running confirm-promotion end-to-end

The confirm-promotion CLI is documented in §3 "Strategy promotion confirmation". Cross-reference that section for the full command syntax. **Do not duplicate it here.**

The bridge between the daily gate and an actual status transition:

1. The daily gate emits a proposal. `decision='promote'` means the gate clears on its own merits. `decision='defer'` is also confirm-promotion-able if you have a justification ≥40 chars explaining why you believe the strategy is ready despite the abstentions.
2. You review the evidence via the SQL query in §10.2.
3. You run the CLI:
   ```bash
   python -m src.main confirm-promotion \
     --strategy <strategy_id> \
     --justification "Your 40+ character rationale here explaining the evidence review..." \
     --yes
   ```
4. The CLI is a **thin wrapper around `promote(triggered_by='operator_confirm', ...)`**. It does NOT bypass the server-side gate re-fire. `promote()` re-runs `check_promotion_gate` at the moment you confirm — catching any data drift between proposal time and confirm time. If the re-fire rejects, the CLI prints the reason and exits non-zero; no transition row is written.

**Critical-1 design constraint**: The CLI never calls `_apply_gate_outcome` with a synthetic outcome. The gate re-fire at confirm time is the authoritative enforcement point. This is locked by `test_operator_confirm_calls_promote_not_synthetic_outcome` (PR #981).

**`decision='reject'` is not overridable.** If the proposal carries `decision='reject'`, the CLI refuses before prompting. Fix the underlying methodology issue, wait for a new proposal.

**Staleness guard**: Proposals older than 24h are rejected at the CLI level (Decision 14). Re-run the daily gate to generate a fresh proposal if the window passed.

### 10.5 Troubleshooting defer outcomes

`decision='defer'` means the gate could not reach a confident decision — insufficient quorum, not a hard failure.

**Diagnostic query:**
```sql
SELECT gate_result_json FROM strategy_promotion_events
WHERE triggered_by = 'gate_proposal'
  AND strategy_id = '<your_id>'
ORDER BY timestamp DESC
LIMIT 1;
```

Then inspect `methodology_gate.details.n_abstentions` and `methodology_gate.details.<vote_name>.reason` for each abstaining method.

**Common abstention causes:**

| Symptom | Root cause | Action |
|---|---|---|
| `mc_perm: null` | `directions` is None (abstention semantics per `promotion_gate_helpers.py`); OR n_obs < 30 (insufficient power) | Under the daily orchestrator, directions are always `[+1]*N`; if null, check the gate was called correctly. Under trainer/kpi paths see §10.8 |
| `mc_perm: false` | Long-only degeneracy (p=1.0 always) — see §10.8 | This is expected under trainer/kpi paths; not a strategy problem |
| `psr_dsr: null` | n_obs < 30 (PSR power requirement) | Accumulate more instrumented shadow trades |
| `white_rc: null` | `candidate_pool < 2` (need ≥2 strategies for White RC) | Normal at single-strategy stage; gate falls back to `4_of_4_no_white_rc` threshold |
| All methods abstain | `instrumentation_excluded_count == N` (all trades excluded) | Check `is_fully_instrumented` failures — missing cost, slippage, or fundamental snapshot columns |
| `psr_dsr: null` with `reason: 'insufficient_dated_returns'` | All rows have NULL `actual_entry_time` | Check shadow_trades for entry-time population; may need reconciler intervention |

**General formula:**
1. Check `details.n_abstentions` — if ≥2, you're short of quorum due to abstentions.
2. For each abstaining method, read `details.<name>.reason`.
3. Address the data gap (more trades, better instrumentation) or wait for the daily gate to re-evaluate tomorrow.

**Note**: `decision='defer'` is operator-overridable via the confirm-promotion CLI if you have sufficient justification (≥40 chars, fresh proposal). `decision='reject'` is not.

### 10.6 Bootstrap-window `walkforward_status='no_data_yet'`

During the first ~30 days after a strategy enters `shadow_trading`, the walkforward rolling-window evaluation has not yet produced data. When `walkforward_results` has no rows for the strategy, `_evaluate_walkforward_gate` sets:

```
walkforward_status = 'no_data_yet'
walkforward_outcome_state = None
```

**This is informational, not a failure.** The gate correctly emits `no_data_yet` (not `'inconclusive'`) to distinguish "waiting for first window" from "inconclusive evidence."

**Effect on promotion:** The composed shadow_trading gate evaluates to False in the bootstrap window — correct behavior. You cannot promote without walkforward data. The evidence dict makes the cause visible; the dashboard can surface it without treating it as a methodology problem.

**Action**: Run `scripts/smoke_gate_9_fold1.bat` manually to populate walkforward_results once the corpus is sufficient (typically after 30+ days of instrumented shadow trades). After that initial run, daily gate proposals will carry `walkforward_status='pass' | 'fail' | 'inconclusive'` instead.

**Do NOT** interpret `decision='defer'` or `composed_pass=false` in the bootstrap window as evidence of a methodology problem. Look at `walkforward_status` first.

### 10.7 Feature-flag + STRICT_GATE matrix

Two environment variables govern gate behavior:

| `METHODOLOGY_GATE_ENABLED` | `STRICT_GATE` | Behavior |
|---|---|---|
| `true` | `true` | Gate fires AND-composes. PASS proposals **auto-promote** (no operator confirm required). Evidence persisted. Most strict — use with caution. |
| `true` | `false` | Gate fires AND-composes. PASS proposals **notify operator**. Operator confirms via CLI. Evidence persisted. **(Default)** |
| `false` | `true` | Methodology side short-circuits to `(True, {'decision':'skipped'})`. Existing walkforward+DSR+PBO checks still gate. NO row written. NO Telegram. PASS auto-promotes. |
| `false` | `false` | Methodology side short-circuits. Existing checks notify. Operator confirms. Effectively pre-Sprint-2 behavior. NO row written. NO Telegram. |

**Production default**: `METHODOLOGY_GATE_ENABLED=true`, `STRICT_GATE=false` — gate fires, evidence persisted, operator confirmation required. Set `STRICT_GATE=true` only if you want PASS proposals to auto-promote without manual confirmation.

**Emergency disable**: Set `METHODOLOGY_GATE_ENABLED=false` to short-circuit the methodology side entirely if a methodology-side bug blocks all promotions during a market event. All other gates (walkforward, DSR, PBO) continue to enforce normally.

Spec reference: `docs/audits/2026-05-05-methodology-gate-wiring/spec.md` §9.1.

### 10.8 Sprint 2 limitations — long-only MC permutation degeneracy

**Do not misread `decision='reject'` from the trainer/KPI call paths as a methodology problem.**

The system is long-only (`recommendations.direction` defaults to `'long'`, `src/schema/registry.py:202`). When `directions = [+1]*N`, the MC permutation shuffle is identity — every permutation produces the same test statistic, so `p_value = 1.0` deterministically. The `mc_perm` vote is always `False` (`passed = p_value < alpha` → `1.0 < 0.05` → False).

This is a structural property of the test, not a bug:

| Call path | `mc_perm` vote | `white_rc` vote | Maximum achievable | Possible decisions |
|---|---|---|---|---|
| `trainer.py` (n_trials > 1, no candidate_pool) | Always FAIL (p=1.0) | Abstain | **3-of-5** | `'reject'` or `'defer'` only |
| `kpis_compute.py` (n_trials=1, no pool) | Always FAIL (p=1.0) | Abstain (n_trials=1) | **3-of-5** | `'reject'` or `'defer'` only |
| `watch.py` daily orchestrator (with candidate_pool) | Always FAIL (p=1.0) | **Can pass** when pool ≥ 2 | **4-of-5** | `'promote'`, `'reject'`, or `'defer'` |

**What this means operationally:**
- If you see `decision='reject'` or `decision='defer'` from the trainer/KPI call paths, look at `mc_perm.value ≈ 1.0` in the evidence. That is the expected degeneracy, not a strategy flaw.
- The **promote-capable** evaluation runs through the `watch.py` daily orchestrator (16:35 ET), where `active_research_strategies` provides the `candidate_pool` that allows White RC to vote (lifting the ceiling to 4-of-5).
- The degeneracy is **regression-locked** by `test_trainer_promotion_gate_currently_cannot_promote_long_only` (PR #975, #981). A future sprint will refactor MC permutation to use a non-degenerate test (e.g., shuffling entry timestamps across the trading-day universe rather than direction labels).

Spec reference: `docs/audits/2026-05-05-methodology-gate-wiring/spec.md` §1.3.1.

### 10.9 Production-gate asymmetry

**The shadow_trading and production gate transitions enforce different preconditions.** This is intentional.

| Transition | Gate composition |
|---|---|
| `backtested → shadow_trading` | Methodology gate AND walkforward AND DSR AND PBO |
| `shadow_trading → production` | Methodology gate AND DSR only (PBO and oos_efficiency are Sprint-4 placeholders, currently `None`) |

**Why:** Moving into shadow_trading requires the full evidence set — you need walkforward data, DSR threshold, and PBO before risking shadow capital. Moving from shadow_trading to production has a lighter per-strategy gate at this stage because the production-side PBO and oos_efficiency wiring is deferred to Sprint 4. The `_evaluate_production_gate` function explicitly sets `evidence['pbo'] = None` and `evidence['oos_efficiency'] = None` at lines 326-327 of `src/platform/promotion.py`.

**Do not assume both transitions enforce identical preconditions** — they don't. If a strategy passes the shadow_trading gate but you're promoting it to production, the methodology gate AND-composes with DSR only. Walkforward and PBO are not re-checked at the production gate boundary (they were already cleared at the shadow_trading boundary).

This asymmetry is locked by `test_production_gate_methodology_compose_with_dsr_only` (PR #981).

Spec reference: `docs/audits/2026-05-05-methodology-gate-wiring/spec.md` §1.2.

---

## 11. Update Protocol

**This doc is updated in any PR that introduces a new operator-relevant runbook procedure.**

Triggers:
- New CLI command added → update §3 Common Commands
- New env var or config key required → update §1 Quick Start + §4 Key File Paths
- New troubleshooting recipe discovered → update §5 Troubleshooting Decision Trees
- New recovery pattern from an incident → update §6 Recovery Patterns
- New maintenance task → update §7 Maintenance Tasks
- New term introduced → update §8 Glossary
- Sprint boundary closing → update §9 Roadmap pointer (or just confirm MASTER.md link is still right)

When updating:
1. Edit this file in the same PR that introduces the new procedure
2. Cross-reference: if relevant, link from CLAUDE.md or MASTER.md to this doc
3. Don't bloat — terse entries beat verbose ones

When a future agent or operator hits a procedure not documented here: **add it before moving on**. The next operator (or future-you in 6 months) shouldn't have to re-derive it.

---

## Modified-A — Local Postgres (post-2026-05-10 cutover)

### Where data lives

After the Cloudflare Tunnel + Modified-A cutover (2026-05-10), the database tier moves from a SQLite-only architecture (with Render PG mirror via `RenderSyncThread`) to a Docker-Postgres-as-primary architecture. SQLite remains on disk during a migration window for rollback insurance.

| Layer | Pre-cutover | Post-cutover |
|---|---|---|
| Watch loop writer | Local SQLite at `C:/arcis/data/ai_research_desk.sqlite3` | Local Docker Postgres at `localhost:5433`, db `halcyon`, user `halcyon` |
| Dashboard mirror | Render-hosted Postgres (RenderSyncThread pushes 61/70 tables) | Same Docker Postgres — single source of truth |
| Dashboard frontend | Render `halcyon-frontend` static service | Local FastAPI's `StaticFiles` mount (served via Cloudflare Tunnel from operator's machine) |
| Dashboard API | Render `halcyon-api` FastAPI service | Local FastAPI on `127.0.0.1:8000` (NSSM service `ArcisDashboard`, exposed via Cloudflare Tunnel as `halcyonlab.app`) |

### Inspect data live (post-Wave-4)

The connection string lives in `.env` as `DATABASE_URL`:

```bash
psql $DATABASE_URL
# or
psql "postgresql://halcyon:<DOCKER_PG_PASSWORD>@localhost:5433/halcyon"
```

In pgAdmin, register the server as `Halcyon Local (Docker)` with host `localhost`, port `5433`, db `halcyon`, user `halcyon`, password from `.env` `DOCKER_PG_PASSWORD`.

**Don't** open the SQLite file in MS Access or similar tools while the watch loop is running — see "Database Access Rules" in CLAUDE.md (the same MS-Access-lock incident from 2026-04-19 still applies if you're inspecting the cold backup `ai_research_desk-2026-05-10-precutover.sqlite3`).

### Rollback to SQLite (emergency)

If the post-cutover watch loop fails to start or shows persistent PG connection errors:

```powershell
nssm stop ArcisWatchLoop

# Drop DATABASE_URL from the NSSM service env — connect_db falls back to SQLite path automatically
nssm set ArcisWatchLoop AppEnvironmentExtra ARCIS_DB_PATH=C:/arcis/data/ai_research_desk.sqlite3

# Restart — watch loop is now on SQLite again; sync thread tries to push to a now-non-existent Render PG
nssm start ArcisWatchLoop
```

The pre-cutover SQLite snapshot at `C:/arcis/data/ai_research_desk-2026-05-10-precutover.sqlite3` (507 MB, captured on cutover day) is the worst-case restoration point.

### Why no more Render PG

See `docs/audits/2026-05-10-cloudflare-tunnel-cutover/spec.md` for the Modified-A migration design. TL;DR: eliminating the Render-hosted Postgres tier removes ~600 LOC of `render_sync.py` complexity (3 sync modes, strip-id rules, savepoint logic), eliminates the asymmetric trading-state coupling described in spec §1, and saves the operator the Render PG monthly bill. Cloudflare Tunnel exposes the local FastAPI to `halcyonlab.app` via a TLS-terminated tunnel, so the dashboard remains publicly reachable from any device.

### Render PG retention

The Render PG instance is retained as a cold backup until **2026-05-17** (7 days post-cutover). To dispose: delete from Render dashboard → confirm. The `pg_dump` snapshot at `C:/arcis/data/render-pg-snapshot-2026-05-10.sql` (478 MB) is on disk indefinitely.

---

## Postgres Cutover (SP5 §J5/§J6 Phase 3-revised — one-DB)

### When to use this runbook

After PR `sp5-phase-3rev` integration merges to main, the operator executes
the steps below to flip production from SQLite to Postgres. Code-side
plumbing is complete after merge; this runbook is the operational sequence.

This runbook supersedes the Phase 3 cutover in the original spec
(`docs/audits/2026-05-11-modified-a-migration/spec.md`) for the re-cutover
attempt. The Phase 3-revised PR corrected the PR #1054 gap where only ~5 of
336 `connect_db()` call sites routed to PG. Under Phase 3-revised, the
precedence inversion is complete — every `connect_db()` call routes to PG
when `ARCIS_PG_CUTOVER_ENABLED=1` is set, regardless of how `db_path` was
passed (SP-ONEDB-001). See the CHANGELOG entry for T1–T6 code change details.

### Prerequisites (all must be satisfied)

- Both NSSM services (`ArcisWatchLoop`, `ArcisDashboard`) running on current `origin/main` with the Phase 3-revised code merged
- `halcyon-pg` Docker container running and healthy (`docker ps --filter "name=halcyon-pg"`)
- `.env` contains `DOCKER_PG_PASSWORD=<64-char-hex>` (random — set during cutover Wave 1)
- Local SQLite snapshot available at `C:/arcis/data/ai_research_desk-YYYY-MM-DD-precutover.sqlite3`
- `ARCIS_PG_CUTOVER_ENABLED` env var NOT YET set on either service

### Step 1 — Pre-flight verification

Before starting the cutover, verify the pre-smoke gates from
`docs/audits/2026-05-11-modified-a-migration/t3.4-smoke-checklist.md` §0,
adapted for the Phase 3-revised (one-DB) scenario:

| # | Check | Command | Expected |
|---|-------|---------|----------|
| 0.1 | Both NSSM services have baseline env but NOT yet `ARCIS_PG_CUTOVER_ENABLED` | `nssm get ArcisWatchLoop AppEnvironmentExtra` | Contains `ARCIS_DB_PATH=...` AND `PYTHONUTF8=1`; does NOT yet contain `ARCIS_PG_CUTOVER_ENABLED=1` |
| 0.2 | Both services are RUNNING | `Get-Service ArcisWatchLoop, ArcisDashboard` | Status=Running for both |
| 0.3 | Docker PG is healthy | `docker ps --filter "name=halcyon-pg" --format "{{.Names}}\t{{.Status}}"` | `halcyon-pg   Up X minutes (healthy)` |
| 0.4 | `data/watchdog.txt` absent or empty | `Test-Path C:\arcis\data\watchdog.txt` | File absent or empty (no PG_CONNECT_FAIL content) |
| 0.5 | PG schema has 71 tables (Phase 3-revised removes `sync_state`) | `docker exec halcyon-pg psql -U halcyon -d halcyon -c "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='public';"` | `71` (SP-ONEDB-002: sync_state removed; was 72 in Phase 3) |

**Note on §0.5:** The Phase 3 smoke checklist (`t3.4-smoke-checklist.md` §0.6) expected 72 tables. Phase 3-revised removes `sync_state` (deprecated alongside `render_sync.py`). If you see 72, the Phase 3-revised schema migration has not run — re-run `python scripts/render_migrate.py` before continuing.

### Step 0.5 — Verify pgAdmin isolation

Before starting the cutover, confirm pgAdmin (or any GUI tool) is either
disconnected from halcyon-pg OR authenticated as `halcyon_readonly`
(read-only, can't issue DDL). Run:

```powershell
docker exec halcyon-pg psql -U halcyon -d halcyon -c \
  "SELECT application_name, usename, client_addr FROM pg_stat_activity \
   WHERE datname='halcyon' AND application_name LIKE '%pgAdmin%' \
   AND usename != 'halcyon_readonly';"
```

Expected: zero rows. If non-empty, disconnect pgAdmin or switch its
connection to use the `halcyon_readonly` role (see post-merge PG role
setup section). A pgAdmin connection as `halcyon` superuser can
accidentally DROP tables via GUI actions — confirmed risk during the
2026-05-11 cutover attempt.

### Step 2 — Stop services

```powershell
nssm stop ArcisWatchLoop
nssm stop ArcisDashboard
Get-Service ArcisWatchLoop, ArcisDashboard  # both should be Stopped
```

Wait until both services show `Stopped` status before proceeding. Any in-flight SQLite writes during shutdown are safe — the pre-cutover snapshot (Step 3) captures the final state.

### Step 3 — Fresh snapshots

```powershell
$ts = Get-Date -Format "yyyy-MM-dd"
Copy-Item C:/arcis/data/ai_research_desk.sqlite3 "C:/arcis/data/ai_research_desk-$ts-precutover.sqlite3"
docker exec halcyon-pg pg_dump -U halcyon halcyon > "C:/arcis/data/pg-pre-cutover-$ts.sql"
```

These are the rollback artifacts. The SQLite snapshot is the worst-case restoration point. The PG dump captures any prior PG state before the fresh migration overwrite.

### Step 4 — Re-mirror schema + migrate data

This step syncs the PG schema to the Phase 3-revised registry (71 tables) and copies all sync-eligible rows from SQLite to PG.

```powershell
# Build DATABASE_URL from .env
$pgPass = (Get-Content C:\arcis\halcyon-lab\.env | Where-Object { $_ -match '^DOCKER_PG_PASSWORD=' } | ForEach-Object { $_ -replace '^DOCKER_PG_PASSWORD=', '' }).Trim()
$env:DATABASE_URL = "postgresql://halcyon:$pgPass@localhost:5433/halcyon"

# Sync schema (creates/drops tables to match registry — 71 tables expected)
python scripts/render_migrate.py

# Migrate data from SQLite → PG
python scripts/sqlite_to_pg_migrate.py
```

**Expected output from `render_migrate.py`:** 71 tables synced. If `sync_state` still appears, the Phase 3-revised schema change hasn't merged — stop and investigate.

**Expected output from `sqlite_to_pg_migrate.py`:** 1.4M+ rows migrated across the sync-eligible tables (63 of 71). The 8 newly-flipped tables (see §"Data verification" below) should now have non-zero PG row counts.

**Data verification — the 8 newly-flipped tables must have data in PG:**

```powershell
docker exec halcyon-pg psql -U halcyon -d halcyon -c "
SELECT
  'system_metrics' AS t, COUNT(*) FROM system_metrics UNION ALL
  SELECT 'bracket_health', COUNT(*) FROM bracket_health UNION ALL
  SELECT 'data_freshness', COUNT(*) FROM data_freshness UNION ALL
  SELECT 'daily_ib_health', COUNT(*) FROM daily_ib_health UNION ALL
  SELECT 'model_evaluations', COUNT(*) FROM model_evaluations UNION ALL
  SELECT 'preference_pairs', COUNT(*) FROM preference_pairs UNION ALL
  SELECT 'config_overrides', COUNT(*) FROM config_overrides UNION ALL
  SELECT 'operator_view_state', COUNT(*) FROM operator_view_state;
"
```

All 8 should show counts > 0 (or 0 for tables that were genuinely empty in SQLite — that is acceptable; the critical check is that the table exists in PG and the migration ran without errors).

Note: For the password-construction approach used above, see memory `reference_docker_bind_mount_persistence` — the same `.env` pattern applies.

### Step 5 — NSSM env APPEND (the cutover moment)

This is the point of no return for the active write path. The APPEND syntax preserves all existing env vars (PYTHONUTF8, ARCIS_DB_PATH, OLLAMA_BASE_URL, etc.) and adds the two cutover keys.

```powershell
# Verify the current baseline before appending:
nssm get ArcisWatchLoop AppEnvironmentExtra
# Record the full output — you will need it for Step 8 rollback if required.

# Append cutover env vars (do NOT use nssm set with only the new vars — that overwrites):
$pgPass = (Get-Content C:\arcis\halcyon-lab\.env | Where-Object { $_ -match '^DOCKER_PG_PASSWORD=' } | ForEach-Object { $_ -replace '^DOCKER_PG_PASSWORD=', '' }).Trim()
$pgUrl = "postgresql://halcyon:$pgPass@localhost:5433/halcyon"

# ArcisWatchLoop: existing baseline + cutover keys
# Replace <EXISTING_ENV_STRING> with the full string from nssm get above:
nssm set ArcisWatchLoop AppEnvironmentExtra "<EXISTING_ENV_STRING> DATABASE_URL=$pgUrl ARCIS_PG_CUTOVER_ENABLED=1"

# ArcisDashboard: typically empty baseline + cutover keys
nssm set ArcisDashboard AppEnvironmentExtra "DATABASE_URL=$pgUrl ARCIS_PG_CUTOVER_ENABLED=1"
```

**CRITICAL:** Verify that PYTHONUTF8=1 and ARCIS_DB_PATH are still present after the set:

```powershell
nssm get ArcisWatchLoop AppEnvironmentExtra
# Must contain: PYTHONUTF8=1, ARCIS_DB_PATH=C:/arcis/data/ai_research_desk.sqlite3, DATABASE_URL=..., ARCIS_PG_CUTOVER_ENABLED=1
```

If PYTHONUTF8 or ARCIS_DB_PATH is missing, the TRL training pipeline will break silently. STOP and redo Step 5 with the correct APPEND approach (M5 mitigation from the spec).

### Step 6 — Start both services

```powershell
nssm start ArcisWatchLoop
nssm start ArcisDashboard
Get-Service ArcisWatchLoop, ArcisDashboard  # both must be Running
```

Wait 60 seconds after start before proceeding to Step 7. Check `data/watchdog.txt` — if it contains `PG_CONNECT_FAIL:`, the PG connection failed at startup (M3 fast-exit fired). Investigate Docker PG health before retrying.

### Step 7 — Smoke verification (30 min)

Follow `docs/audits/2026-05-11-modified-a-migration/t3.4-smoke-checklist.md` for the full 30-minute smoke checklist, with the following **CRITICAL additions** for Phase 3-revised (one-DB):

**Addition §1.A — SQLite must show ZERO new rows during the gate-on window.**

The PR #1054 failure mode was writes silently routing to SQLite even with the gate on. This assertion catches that regression in 30 seconds. Run this every 5 min during the smoke window:

```python
import sqlite3
conn = sqlite3.connect("file:C:/arcis/data/ai_research_desk.sqlite3?mode=ro", uri=True)
rows = conn.execute(
    "SELECT COUNT(*) FROM shadow_trades WHERE updated_at >= datetime('now', '-5 minutes')"
).fetchone()
assert rows[0] == 0, f"SQLite received {rows[0]} writes during gate-on — cutover regression!"
conn.close()
```

If this assertion fails, STOP immediately and proceed to Step 8 rollback. This is a NON-NEGOTIABLE check — it is the assertion that would have caught PR #1054 in 30 seconds.

**Addition: PG schema check expects 71 tables (not 72).** The t3.4-smoke-checklist.md §0.6 expects 72 — for Phase 3-revised, the expected count is 71 (`sync_state` removed per SP-ONEDB-002).

**Addition: All 8 newly-flipped tables must show writes in PG.** The Phase 3 smoke only verified 5 write paths (system_metrics, shadow_trades, activity_log, notifications_dedup, scan_metrics). Phase 3-revised adds 8 more tables to the sync-to-PG set. Spot-check at minute 10:

```powershell
docker exec halcyon-pg psql -U halcyon -d halcyon -c "
SELECT 'bracket_health' AS t, MAX(updated_at) FROM bracket_health UNION ALL
SELECT 'data_freshness', MAX(updated_at) FROM data_freshness UNION ALL
SELECT 'config_overrides', MAX(updated_at) FROM config_overrides UNION ALL
SELECT 'operator_view_state', MAX(updated_at) FROM operator_view_state;
"
```

Post-cutover timestamps in any of these tables confirm the engine_aware_upsert writers are routing to PG correctly.

**Expected smoke PASS criteria (Phase 3-revised):**

- All §0 pre-smoke gates pass (using 71 not 72 for §0.5/§0.6 counts)
- §1.A SQLite-zero-writes assertion holds for all 5-min checks during the window
- §1 write paths: all 5 original paths + spot-check of ≥2 of the 8 newly-flipped tables
- §2 read paths: ≥6/7 endpoints clean
- §3 C1 LIKE regression: §3.1 or §3.2 passes
- §4 log sweep: zero CRITICAL patterns; `_DB_PATH_WARNED` WARN lines in `arcis.log` are expected (one per distinct `db_path` override, by design — see SP-ONEDB-009)

### Step 7.5 — Capture pg_stat_activity during smoke

In a SEPARATE PowerShell terminal (so it doesn't block the main cutover
flow), run:

```powershell
.\scripts\capture_pg_activity.ps1
```

This loops every 30s capturing pg_stat_activity to
`C:/arcis/logs/pg-activity-<timestamp>.log`. Continues until you press
Ctrl+C. Should run for the entire 30-min smoke window. If the cutover
fails, the log will show every connection's queries — invaluable
forensic data for diagnosing the 2026-05-11-class table-disappearance
issue (which had no log trail under default PG settings).

### Step 8 — Rollback (only if Step 7 FAILS)

If any CRITICAL failure occurs during the smoke:

```powershell
# Single env unset reverts cutover — SQLite resumes as primary on next connect_db() call
nssm set ArcisWatchLoop AppEnvironmentExtra "ARCIS_DB_PATH=C:/arcis/data/ai_research_desk.sqlite3 PYTHONUTF8=1 SYNC_THREAD_ENABLED=false"
nssm set ArcisDashboard AppEnvironmentExtra ""
nssm restart ArcisWatchLoop
nssm restart ArcisDashboard
```

After rollback, verify that `Get-Content C:\arcis\logs\watch.log -Tail 20` shows SQLite-backed activity (no psycopg2 errors) within ~30 seconds of restart.

After rollback: investigate the failure pattern via `logs/arcis_err.log` and `logs/dashboard-stderr.log`. File a P0 incident with the Step 7 sub-step that failed (§1.A failure = writes still routing to SQLite = connect_db gate regression; §4 CRITICAL pattern = schema drift or PG unreachable).

### Known considerations

- `_DB_PATH_WARNED` WARN log appears in `arcis.log` exactly ONCE per distinct `db_path` passed to `connect_db()` under gate-on. This is by design — see SP-ONEDB-009. It confirms the gate intercepted an explicit `db_path` override. Multiple WARN lines for the same path indicate a cold-start sequence or multiple processes; not a concern unless the count grows unboundedly.
- SQLite remains on disk post-cutover as a stale snapshot for rollback safety. Writes during gate-on do NOT mirror back to SQLite. See SP-ONEDB-001 + SP-ONEDB-005. The file at `ai_research_desk-YYYY-MM-DD-precutover.sqlite3` is the canonical cold backup.
- `render_sync.py` and `reconcile.py` were deleted in T7 of this PR — do NOT attempt to import them or invoke the legacy `reset-live-prices-watermark` CLI subcommand. The subcommand is removed from `src/cli/main.py`.
- The `sync_state` table is absent from the Phase 3-revised schema (removed along with `render_sync.py`). If any legacy script references it, it will receive a `relation "sync_state" does not exist` error from PG. File as a follow-up; does not block the cutover.
- `cloud_routes/` manual `if database_url:` branches are now redundant under the one-DB invariant but each has independent quirks. Cleanup is tracked as post-merge backlog (SP-ONEDB-011); do NOT modify these branches as part of the cutover — they are harmless no-ops under gate-on.

---

## PG application roles (post-merge one-time setup)

After merging the cutover-rectification PR, run the role-setup script before
the next cutover attempt:

1. Add to `.env`:
   ```
   DOCKER_PG_APP_PASSWORD=<64-char-hex>  # generate with: openssl rand -hex 32
   DOCKER_PG_RO_PASSWORD=<64-char-hex>
   ```
2. Run: `python scripts/setup_pg_roles.py`
3. Verify roles exist:
   ```
   docker exec halcyon-pg psql -U halcyon -d halcyon -c "\du"
   ```
   Should show `halcyon_app` (no superuser) and `halcyon_readonly` (no
   superuser, no createdb).

Future cutovers should set `DATABASE_URL` to use the `halcyon_app` role
instead of `halcyon` superuser. pgAdmin connections should authenticate
as `halcyon_readonly` so the GUI cannot accidentally DROP/TRUNCATE.

### Rotating role passwords

The setup script is idempotent on role *existence* but does NOT rotate passwords on
re-run. To rotate a password:

1. Generate new password: `openssl rand -hex 32`
2. Connect to PG as superuser and rotate via `\password` (interactive, never echoes):
   ```
   docker exec -it halcyon-pg psql -U halcyon -d halcyon
   halcyon=# \password halcyon_app
   Enter new password: <paste>
   Enter it again: <paste>
   ```
3. Update `.env` with the new password under `DOCKER_PG_APP_PASSWORD=` and restart services.

**Do NOT use `ALTER ROLE halcyon_app WITH PASSWORD '<value>'` from the command line** — that command echoes the password to PG logs and shell history. Always use `\password` for interactive rotation.

---

## Training Environment — Required Python Env Vars

### PYTHONUTF8=1 (training pipeline encoding requirement)

**What:** `PYTHONUTF8=1` is a Python env var that forces UTF-8 mode regardless of the
platform default locale.

**Why:** The TRL training pipeline reads and writes corpus JSONL files that contain
non-ASCII characters (company names, news headlines, Unicode punctuation). On Windows,
Python's default encoding is `cp1252` (Windows-1252). When `PYTHONUTF8` is absent,
`open()` calls without an explicit `encoding=` argument silently use `cp1252` — any
character outside ASCII is corrupted or raises a `UnicodeDecodeError` at read time, and
the corruption is not always loud. The result is a poisoned training batch that produces
garbage token sequences or a hard crash mid-epoch.

**Where to set it (3 locations):**

**1. NSSM ArcisWatchLoop service env** — for training subprocesses spawned by the watch loop:

```powershell
# Read existing env first — NEVER overwrite with only the new var (that wipes the rest):
nssm get ArcisWatchLoop AppEnvironmentExtra

# Append PYTHONUTF8 to the existing string; replace <EXISTING_ENV_STRING> below:
nssm set ArcisWatchLoop AppEnvironmentExtra "<EXISTING_ENV_STRING> PYTHONUTF8=1"

# Verify it is present alongside ARCIS_DB_PATH and any other required vars:
nssm get ArcisWatchLoop AppEnvironmentExtra
# Expected: ... ARCIS_DB_PATH=C:/arcis/data/ai_research_desk.sqlite3 PYTHONUTF8=1 ...
```

The NSSM env is the load-bearing setting — all training subprocesses (`overnight_train.py`,
`trainer.py`, `verify_training_readiness.py`) are spawned as children of the watch-loop
NSSM service and inherit its environment. If PYTHONUTF8 is only set at User scope (step 2)
but not in NSSM, the watch-loop-launched training will still use `cp1252`.

**2. User-scope env var** — for operator shell invocations (`python -m src.main training-status`,
manual corpus runs, etc.):

```powershell
[Environment]::SetEnvironmentVariable('PYTHONUTF8', '1', 'User')
```

This persists across shell sessions for the current Windows user. Requires opening a new
PowerShell window after setting (existing windows don't see the change until restarted).

**3. System-scope env var** — only needed on multi-user machines. On a single-operator
box (the standard Arcis setup), User-scope (step 2) is sufficient for interactive shells.
If a CI agent or second user account runs training scripts, set it at system scope instead:

```powershell
[Environment]::SetEnvironmentVariable('PYTHONUTF8', '1', 'Machine')  # requires admin
```

**How to verify:**

```powershell
python -c "import sys; print(sys.flags.utf8_mode)"
```

Expected output: `1`. If it returns `0`, the var is not visible to the Python process you
just ran — check which scope (User vs NSSM vs System) is missing and apply the relevant
step above.

**Cross-reference:** The env-var inventory for the ArcisWatchLoop NSSM service (including
PYTHONUTF8, ARCIS_DB_PATH, DATABASE_URL, ARCIS_PG_CUTOVER_ENABLED) is maintained in the
Postgres Cutover runbook → Step 5 (line ~1643) and the Step 1 pre-flight table (line ~1556).
If you add or remove env vars from NSSM, update those two references to stay in sync.

---

## See also

- [`CLAUDE.md`](../CLAUDE.md) — rules for AI agents working on the codebase (governance + schema discipline + worktree pattern)
- [`MASTER.md`](../MASTER.md) — canonical project state (architecture + sprint queue + current metrics)
- [`docs/methodology-toolkit.md`](methodology-toolkit.md) — reference for shelf statistical methods
- [`docs/dashboard-data-map.md`](dashboard-data-map.md) — dashboard tile data sources
- [`docs/audits/`](audits/) — sprint specs, audit reports, gap lists
- [`CHANGELOG.md`](../CHANGELOG.md) — release history under `[Unreleased]` and prior versions

---

## Notification dedup migration (Sprint 4 T15a)

### What changed

The notification deduplication window (`_DEDUP_CACHE`) was previously an in-memory Python dict. After T15a it persists to the `notifications_dedup` SQLite table, so the 24-hour window survives NSSM restarts of the watch loop.

### Expected behaviour on first NSSM restart post-merge

**One-shot duplicate alert risk:** On the first NSSM restart after T15a merges to main, the in-memory `_DEDUP_CACHE` is empty (the old code), but the `notifications_dedup` table is also empty (T15a has never run). This means any notification that would have been suppressed by the prior in-memory window may fire again.

This is a one-time event. After the first restart, the DB table is populated and dedup works normally across all subsequent restarts.

### Optional post-deploy dedup seed (eliminates the duplicate)

If you want to prevent the one-shot duplicates entirely, run this script in the halcyon-lab repo root after merging but before the NSSM restart:

```python
# scripts/seed_dedup_from_sent.py (optional one-shot)
import sqlite3, os
from datetime import datetime, timedelta, timezone

DB_PATH = os.environ.get("ARCIS_DB_PATH", "C:/arcis/data/ai_research_desk.sqlite3")
cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()

conn = sqlite3.connect(DB_PATH)
rows = conn.execute(
    "SELECT event_type, event_type || '::' || sent_at AS dedup_key, sent_at"
    " FROM notifications_sent WHERE sent_at >= ? AND status='ok'",
    (cutoff,),
).fetchall()
for event_type, dedup_key, sent_at in rows:
    conn.execute(
        "INSERT OR IGNORE INTO notifications_dedup (event_type, dedup_key, sent_at)"
        " VALUES (?, ?, ?)",
        (event_type, dedup_key, sent_at),
    )
conn.commit()
conn.close()
print(f"Seeded {len(rows)} dedup rows from notifications_sent.")
```

Run with: `python scripts/seed_dedup_from_sent.py`

---

## 12. Notification Troubleshooting

### 12.1 "Bot is silent"

The Telegram bot has stopped sending messages.

**Decision tree:**

1. **Check subsystem health** — `curl http://127.0.0.1:8765/api/notifications/health` (or `curl http://127.0.0.1:8080/api/notifications/health` on the default local API port). A `success_rate < 0.8` or non-empty `oldest_unack_alert` indicates delivery failures. See [T15 endpoint](../tests/api/test_notifications_health.py) for the response shape.

2. **Check the NSSM watch loop** — open PowerShell and run:
   ```powershell
   nssm status arcis-watch
   # Expected: SERVICE_RUNNING
   # If stopped:
   nssm restart arcis-watch
   ```
   If the service is not registered: `python -m src.main startup` from `C:\arcis\halcyon-lab`.

3. **Check `data/watch.lock`** — a stale lockfile prevents the watch loop from starting:
   ```powershell
   Get-Content C:\arcis\data\watch.lock   # shows PID
   Get-CimInstance Win32_Process -Filter "ProcessId=<pid>"  # check if PID is alive
   # If no such process exists, the lockfile is stale:
   Remove-Item C:\arcis\data\watch.lock
   nssm restart arcis-watch
   ```

4. **Check Telegram config** — verify `config/settings.local.yaml` has `telegram.enabled: true`, a valid `bot_token`, and the correct `chat_id`. Use `/start` in your Telegram chat to ping the bot manually.

### 12.2 "Bot token rotated"

You have regenerated the bot token via BotFather and need to update ARCIS.

1. Copy the new token from `@BotFather`.
2. Update `.env` (or `config/settings.local.yaml`):
   ```yaml
   telegram:
     bot_token: "<new-token>"
   ```
3. Restart the NSSM watch loop:
   ```powershell
   nssm restart arcis-watch
   ```
4. Send `/status` in Telegram to verify delivery.

**Note:** The old token is immediately invalidated — all in-flight requests with the old token will fail with a `401 Unauthorized` from the Telegram API.

### 12.3 "Email digest stopped arriving"

The daily email digest (`notify_eod_report` or weekly `notify_weekly_digest`) is not being delivered.

**Decision tree:**

1. **Check SMTP config** — verify `config/settings.local.yaml`:
   ```yaml
   email:
     smtp_host: smtp.gmail.com
     smtp_port: 587
     from_address: your@gmail.com
     to_addresses: [your@gmail.com]
     # password must be in .env as EMAIL_PASSWORD, NOT here
   ```
   If `EMAIL_PASSWORD` is missing from `.env`, `send_email` will emit a warning but not send.

2. **Check the `notifications_sent` table for failures**:
   ```python
   import sqlite3
   DB = "C:/arcis/data/ai_research_desk.sqlite3"
   conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
   rows = conn.execute(
       "SELECT event_type, status, error_msg, sent_at"
       " FROM notifications_sent WHERE channel='email' AND status='failed'"
       " ORDER BY sent_at DESC LIMIT 10"
   ).fetchall()
   for r in rows: print(r)
   ```
   Common `error_msg` values and fixes:
   - `"SMTP AUTH failed"` → check `EMAIL_PASSWORD` in `.env`
   - `"Connection refused"` → check `smtp_host`/`smtp_port` in settings
   - `"Recipient refused"` → verify `to_addresses` list

3. **Manually send a test email**:
   ```bash
   python -m src.main send-test-email
   ```
   Watches logs for SMTP errors.

### 12.4 How to verify subsystem health

Use the T15 health endpoint to confirm the notification pipeline is live:

```bash
curl http://127.0.0.1:8765/api/notifications/health
```

Expected response shape (see T15 spec):
```json
{
  "success_rate": 0.97,
  "fail_count": 1,
  "dedup_hits": 12,
  "oldest_unack_alert": null
}
```

| Field | Healthy | Warning |
|-------|---------|---------|
| `success_rate` | ≥ 0.95 | < 0.80 |
| `fail_count` | 0–2 in 24h | > 5 in 24h |
| `oldest_unack_alert` | `null` | any non-null value |

If `oldest_unack_alert` is non-null, an alert fired but was never acknowledged — check `notifications_sent` for the corresponding row and investigate the `error_msg`.

### Notification health dashboard widget

`GET /api/notifications/health` returns `{success_rate, fail_count, dedup_hits, oldest_unack_alert}` for the last 24 hours. The `NotificationsHealthPanel` widget on the dashboard polls this endpoint every 5 minutes. A `success_rate < 0.80` or `fail_count > 0` indicates a delivery problem worth investigating.

---

## Drift detection

The manual-intervention drift detector (Wave C T4 / #45) fires a Telegram alert when the operator closes a paper position directly in the Alpaca dashboard but the local `shadow_trades` row still shows `active`. This prevents silent divergence between broker state and DB intent.

### What it watches

Every 30 minutes the watch loop compares active `shadow_trades` rows against Alpaca's live paper positions. A "drift" is when:
- Broker says position is closed (qty = 0 or absent)
- Local DB says position is active (`status IN ('active', 'open', ...)`)

### Threshold and dedup

- Divergence must persist for **≥ 30 minutes** before an alert fires (avoids transient Alpaca API hiccups).
- Once alerted, the same divergence is **suppressed for 24 hours** (operator has been notified; they may be investigating).
- On broker outage (Alpaca unreachable), **no alerts fire** — cannot distinguish drift from API failure.

### State file

`data/drift_detector_state.json` — atomic-write singleton tracking first-seen timestamps and last-alert timestamps per ticker. To silence an alert without fixing the underlying drift: delete the file or remove the ticker entry.

### Forensic trail

Every emitted finding writes a row to `platform_events`:

```
sqlite3 data/ai_research_desk.sqlite3 \
  "SELECT * FROM platform_events WHERE source='drift_detector' ORDER BY created_at DESC LIMIT 10"
```

Fields: `event_type='drift_detected'`, `severity='high'`, `source='drift_detector'`, `payload_json` containing `ticker`, `expected_state`, `actual_state`, `divergence_age_minutes`.

### How to silence

1. Investigate the divergence — does the Alpaca position match the DB row?
2. If already resolved: delete `data/drift_detector_state.json` (or just the stale ticker key) so the next tick starts fresh.
3. If you want to temporarily stop drift checks: stop the watch loop (`nssm stop <svc>`) — the state file persists across restarts.

### How to investigate

```bash
# Check what the DB says
sqlite3 data/ai_research_desk.sqlite3 \
  "SELECT ticker, status, updated_at FROM shadow_trades WHERE status IN ('active', 'open') ORDER BY updated_at DESC"

# Check the drift forensic trail
sqlite3 data/ai_research_desk.sqlite3 \
  "SELECT created_at, payload_json FROM platform_events WHERE source='drift_detector' ORDER BY created_at DESC LIMIT 5"

# Check current state file
type data\drift_detector_state.json
```

---

## Notifications routing

> Added T10 Sprint 5 Wave D D1. T12 D3 wired `safe_send` to consult the policy gate; digest queue dispatcher replaced stub. Controls which events are sent immediately, digested for batch delivery, or muted.

### Where to edit

Edit `config/settings.local.yaml` (gitignored — your local override). The `notifications:` section is fully optional; missing keys use the defaults shown in `config/settings.example.yaml`. Never edit `settings.example.yaml` for per-operator values.

### safe_send verdict-dispatch matrix (T12 D3)

`safe_send` now consults `should_dispatch(event_type, severity, now_et, config)` on every call and branches on the returned `PolicyDecision.verdict`:

| verdict   | action                                                              |
|-----------|---------------------------------------------------------------------|
| `send`    | `_do_dispatch` — calls notify_fn directly, writes ok row           |
| `digest`  | `DigestQueue.enqueue` — buffered for batch delivery                 |
| `mute`    | Log + return False (silent drop)                                    |
| `escalate`| `_do_dispatch_escalated` — all configured channels, sequential      |

`force=True` bypasses the policy gate entirely and always routes to the `send` path via telegram. Use for manual overrides from the CLI only.

### Decision 20: no bypass_severity knob

There is no `bypass_severity` config key and there never will be. **Severity `high` and `critical` ALWAYS send immediately** — this is Rule #1 in the routing gate and cannot be overridden by any other policy (mute list, quiet hours, digest_low). Adding `bypass_severity` to your config will cause startup to fail with `NotificationsConfigError`. **This lockdown is now enforced recursively** — a `bypass_severity` key nested inside `routing_overrides.X` will also raise. If you want a specific event_type to never send, add it to `mute_event_types` — but high/critical events of that type will still send.

### routing_overrides key allowlist (T12 D3 #110)

Each entry under `routing_overrides` must be a dict with keys drawn exclusively from `{'telegram', 'email', 'escalation_after_attempts'}`. Unknown keys (e.g. typo `telgram`) will raise `NotificationsConfigError` with the offending key path. This prevents silent misconfiguration.

```yaml
notifications:
  routing_overrides:
    manual_intervention_drift:
      telegram: true
      email: true
      escalation_after_attempts: 3   # escalate after 3 failed send attempts
```

### Quiet hours

```yaml
notifications:
  quiet_hours_start: "22:00"   # 10pm ET
  quiet_hours_end: "06:00"     # 6am ET — cross-midnight (start > end)
  quiet_digest: true           # true = buffer to digest; false = mute entirely
```

Times are Eastern Time (ET), `HH:MM` format. Cross-midnight is supported — if `start > end`, the window wraps midnight. Setting `start == end` disables quiet hours entirely (all times fall through). Invalid time strings (e.g. `"25:00"`) raise `NotificationsConfigError` at startup.

During the quiet window:
- severity=high and severity=critical: still send immediately (Rule #1)
- all other severities: DIGEST (if `quiet_digest: true`) or MUTE (if `quiet_digest: false`)

### Mute list

```yaml
notifications:
  mute_event_types:
    - scan_result            # silence routine scan result noise
    - scoring_summary        # silence daily score batch summary
```

Events in `mute_event_types` are silenced regardless of severity — **except** high/critical, which still bypass (Rule #1).

### Low-severity digest

```yaml
notifications:
  digest_low: true   # severity=low events go to digest queue instead of immediate send
```

When `true`, events with `severity=low` are batched for the digest queue (T11 D2 implements the queue). When `false`, they follow default routing.

### Channel routing

```yaml
notifications:
  default_routing:
    telegram: true
    email: false
  routing_overrides:
    manual_intervention_drift:
      telegram: true
      email: true             # escalate this event type to email as well
      escalation_after_attempts: 3   # T12 D3 retry knob
```

`default_routing` applies to all events not listed in `routing_overrides`. Each override entry specifies `telegram` and `email` booleans plus optional `escalation_after_attempts`. Only event_type keys registered in `src.notifications.telegram._EVENT_MAP` are valid — unknown event types raise `NotificationsConfigError` at startup. Unknown override dict keys also raise (see routing_overrides key allowlist above).

### Cadence throttling

```yaml
notifications:
  cadence_minutes_per_event_type:
    manual_intervention_drift: 30   # re-alert at most every 30 minutes
    alert_silence: 60
```

Values must be in `[1, 1440]` (1 minute to 24 hours). Unknown event_type keys raise at startup.

### Retry

```yaml
notifications:
  retry:
    attempts: 3
    backoff_seconds: [1, 5, 15]   # length must equal attempts
```

`attempts` must be in `[1, 10]`. `len(backoff_seconds)` must equal `attempts`.

### Digest queue

> Added T11 Sprint 5 Wave D D2. Persistence layer for `PolicyDecision(verdict='digest')` outputs.

The digest queue stores notifications that the routing policy has decided to batch for later delivery. The watch loop drains the queue every `digest_flush_minutes` minutes.

#### Config knob

```yaml
notifications:
  digest_flush_minutes: 60   # [5, 1440] — how often the watch loop drains the queue
```

Values outside `[5, 1440]` raise `NotificationsConfigError` at startup.

#### `flush_status` lifecycle

```
pending → in_progress → sent              (success path)
pending → in_progress → pending           (dispatcher raised; attempts < retry.attempts)
pending → in_progress → abandoned         (dispatcher raised; attempts == retry.attempts)
```

Rows in `in_progress` that survive a process crash are recovered on the next flush tick: the tick promotes them to `pending` (if under the retry limit) or `abandoned` (if exhausted).

`abandoned` rows are operator-visible forensic state. The watch loop will **never** re-pick them up automatically.

#### Forensic query — abandoned rows

```sql
SELECT * FROM notifications_digest_queue
WHERE flush_status = 'abandoned'
ORDER BY created_at DESC
LIMIT 10;
```

#### Manual recovery — re-queue an abandoned row

```sql
UPDATE notifications_digest_queue
SET flush_status = 'pending',
    flush_attempts = 0,
    flush_error = NULL
WHERE id = <row_id>;
```

After this UPDATE, the next watch loop tick will attempt dispatch again.

---

## Known design decisions / WON'T-FIX notes

### `#SP4-settings-backend-float32-storage` WON'T FIX

**Context:** The Settings page risk inputs (`risk.planned_risk_pct_min` and `risk.planned_risk_pct_max`) were displaying float32 representational noise in the browser — e.g., a value set to `0.005` would render as `0.0049999...` or `0.00500000007...`. Sprint 4 T11 (Sprint 3) added a frontend clamp in `frontend/src/components/...` (MetricCard and Settings form inputs) that rounds displayed values to remove the noise.

**Decision:** The backend storage of these config values remains float32 in SQLite. We are NOT migrating the backend to float64 or Python `Decimal` for these fields. Rationale:

1. The storage is functionally correct — `0.0049999...` IS `0.005` to float32 precision; the risk governor reads and compares it correctly at runtime.
2. The bug was purely a display artifact. The frontend clamp eliminates the operator-visible symptom entirely.
3. A backend migration to float64/Decimal would require schema changes, a migration script, validation across all 4 namespace consumers of the risk governor, and re-testing of the promotion gate's risk-threshold comparisons — disproportionate investment for a display-only fix.

**Trade-off operators must know:** External tools that read `config/settings.local.yaml` or query the `settings` table directly (e.g., scripts using `yaml.safe_load` or raw SQLite queries) will still see the raw float32 representation. If you build automation that parses these values, round them to 4 significant figures at the consumption point. The dashboard and CLI always display the clamped value.

---

## Stale-base CI check (`.github/workflows/stale-base-check.yml`)

### What it does

Every PR opened or updated against `main` triggers a GitHub Actions job that verifies the PR branch has been rebased onto the current tip of `main`. The check computes `merge-base(PR HEAD, origin/main)` and fails if it does not equal `origin/main HEAD`.

This is the server-side complement to the client-side `pre-push` hook at `scripts/hooks/pre-push`. The CI check closes the bypass gap: `git push --no-verify` and absent hook installs can circumvent the client hook, but they cannot skip CI.

### Why this matters

Five stale-base incidents (#769, #816, #829, #840, #841 — one per day) shipped PRs whose squash-merge would have silently reverted intervening work from main. The diff of a stale branch against current main shows the commits added since the branch was cut as deletions — exactly the bytes that would disappear from main post-squash-merge. Each incident was caught at review time by the operator; this guard moves detection to push/open time.

### What you see when the check fails

```
============================================================
STALE BASE — PR branch is 3 commits behind origin/main
============================================================

merge-base : abc1234...
main HEAD  : def5678...

Squash-merging this PR would silently revert the 3 commit(s)
on main that your branch has not yet incorporated.

Resolution:
  git fetch origin main
  git rebase origin/main
  # resolve any conflicts, re-run your tests
  git push
```

### Resolution

```bash
git fetch origin main
git rebase origin/main
# resolve any conflicts, then:
git push
```

After the push, GitHub re-runs the check on the updated branch. If the merge-base now equals `origin/main HEAD`, the check passes and the PR unblocks.

### Relationship to the client-side hook

| Layer | File | Trigger | Bypassable? |
|-------|------|---------|-------------|
| Client (dev machine) | `scripts/hooks/pre-push` | `git push` | Yes — `git push --no-verify` |
| Server (GitHub Actions) | `.github/workflows/stale-base-check.yml` | PR open / push | No — CI must pass for merge |

Both layers emit the same actionable error message and reference the same incident history. The client hook fires earlier (at push time, before a PR even opens), which is preferable. The CI check is the backstop when the client hook is absent or bypassed.

**Tag:** `#SP4-settings-backend-float32-storage WON'T FIX` — resolved by T11 frontend clamp. Backend storage unchanged by design.

---

## Sprint 5 closeout state (v0.35.0 — 2026-05-13)

This section captures the operationally-relevant deltas in v0.35.0 that
the operator may need to consult when running daily ops. Full release
notes live in `CHANGELOG.md`; this is the curated subset.

### Phase-3-revised cutover (SQLite → local Postgres)

Sprint 5 completed the Phase-3-revised cutover from a SQLite-only data
backend to a dual-engine (SQLite + Postgres) setup. The runtime engine
is selected by the `ARCIS_PG_CUTOVER_ENABLED` environment variable:

| `ARCIS_PG_CUTOVER_ENABLED` | `connect_db()` returns |
|---|---|
| Unset or `0` (default) | SQLite — `sqlite3.Connection` on `ARCIS_DB_PATH` |
| `1` | Postgres — `PostgresConnectionWrapper` on `DATABASE_URL` |

Production runs the SQLite engine; the operator's local cutover sandbox
uses the PG engine via `DATABASE_URL=postgresql://halcyon:halcyon@localhost:5433/halcyon`.

**Operationally:** if you see `KeyError: 0` from a `.fetchone()[0]` call
after enabling the PG engine, it's a row-shape mismatch — Postgres
returns `RealDictCursor` rows (dict-like, not tuple-like). Use
`src.utils.db._scalar(row)` to extract the first column engine-agnostically.

### Wave D notification subsystem

The notification routing layer added in Sprint 5 (Wave D) introduces
four behaviors the operator should be aware of:

1. **Policy gate** (`src/notifications/policy.py`): every `notify_*` call
   passes through a policy decision (`send` / `digest` / `mute` /
   `escalate`). The decision is recorded in `notifications_sent.policy_decision`
   for forensic audit. See §11 of this guide for the policy YAML truth table.
2. **Digest queue** (`notifications_digest_queue` table): `verdict=digest`
   events are persisted with `flush_status='pending'` and drained every
   30 minutes during quiet hours. See §11 "Digest queue" for the lifecycle.
3. **Alert silence detector**: a watch-loop task (`tick_alert_silence`,
   fires every 5 min) checks `MAX(sent_at)` across `notifications_sent`,
   `notifications_digest_queue.flushed_at`, and `notifications_digest_queue.created_at`.
   Silence > 60 minutes during market hours emits a high-severity
   `alert_silence` event + writes a `platform_events` row for forensic
   trail.
4. **HTML escape**: all `notify_*` functions emit Telegram-safe HTML
   via `_html_escape()` — operator does NOT need to manually escape
   ticker symbols or news headlines passed via payload dataclasses.

### Wave C7a/C7b LLM packet enrichment

The LLM prompt now includes 8 new sections that the operator may see
referenced in trade-packet logs:

- **STRATEGY CONTEXT** header preamble (T20)
- **COUNCIL CONSENSUS** (T17, indexed 4.4)
- **HISTORICAL CREDIBILITY** (T18)
- **RECENT ATTRIBUTION** (T19, 30-day window default)
- **INSTITUTIONAL FLOW** (T21, plan-gated on `institutional_ownership`)
- **MATERIAL EVENTS** (T22+T23 wrapper, plan-gated sub-blocks)
- **FUNDAMENTAL SNAPSHOT** live-enrichment trailer (T24)
- **DATA CONTEXT** header (T24, prepended when ≥1 Tier-2 section omits)

The DATA CONTEXT header distinguishes plan-gated absence (Decision 30)
from transient data gaps (sink JSON missing); it carries explicit
`omitted: <section>` notes so the LLM doesn't conflate the two states.

### Dual-GPU deferral (Wave E)

The dual-GPU workload-separation work (RTX 3060 for serving + RTX 3090
for training) is **deferred to the first post-Sprint-5 maintenance window**
per the Wave E disposition doc at
`docs/audits/2026-05-12-dual-gpu-ideation/disposition.md`. The canonical
design spec is preserved at
`docs/audits/2026-05-12-dual-gpu-ideation/specs/2026-05-12-dual-gpu-workload-separation-design.md`
— operator can review when scoping the next training cycle.

Until then: training runs on the RTX 3090 (24 GB VRAM) using
Transformers + PEFT + TRL (Unsloth dependency removed per the 2026-05-10
GPU swap). Set `NUM_PARALLEL=4` for the new card.

---

## NSSM environment configuration

The watch loop is managed by NSSM as a Windows service. The service
inherits environment variables from the system + the NSSM service config.
Use `nssm restart <svc>` to restart (NOT `python -m src.main startup` —
that creates a duplicate process that races the NSSM-managed instance;
observed 2026-05-06).

### Environment variable inventory

Every variable below is read at watch-loop startup. Categorized by
purpose; required vars marked **(required)**.

**Secrets** — never commit; live in `.env` or NSSM service config (not in YAML):

| Variable | Purpose |
|---|---|
| `ALPACA_API_KEY` **(required for paper)** | Alpaca paper trading API key |
| `ALPACA_API_SECRET` **(required for paper)** | Alpaca paper trading API secret |
| `ALPACA_LIVE_API_KEY` (optional) | Alpaca live trading API key — only set when going live |
| `ALPACA_LIVE_SECRET_KEY` (optional) | Alpaca live trading API secret — same gating |
| `ALPACA_RESEARCH_API_KEY` (optional) | Research-tier API key for historical data |
| `ALPACA_RESEARCH_API_SECRET` (optional) | Research-tier API secret |
| `FINNHUB_API_KEY` **(required)** | Finnhub API token (free or fundamental-1 tier) |
| `FRED_API_KEY` **(required)** | FRED macro data key |
| `TELEGRAM_BOT_TOKEN` / `ARCIS_TELEGRAM_TOKEN` | Telegram bot token (either name supported; the latter takes precedence) |

**Connection / database** — wire the engine + endpoints:

| Variable | Purpose |
|---|---|
| `ARCIS_DB_PATH` **(required)** | SQLite database path. Canonical value: `C:/arcis/data/ai_research_desk.sqlite3` |
| `DATABASE_URL` (cutover-only) | PG connection string when `ARCIS_PG_CUTOVER_ENABLED=1` |
| `TEST_DATABASE_URL` (CI-only) | PG connection string for pytest parametrized_conn fixture |

**Feature flags / runtime modes**:

| Variable | Purpose |
|---|---|
| `ARCIS_PG_CUTOVER_ENABLED` | `0`/unset → SQLite; `1` → Postgres via DATABASE_URL |
| `ALPACA_PAPER_TRADE` | `1` → paper mode; `0` → live mode |
| `ARCIS_LOG_ACTIVITY_IN_PYTEST` | Allow `activity_logger` writes during pytest (default: blocked, raises) |
| `ARCIS_SHOW_WARNINGS` | `1` → emit data-collection warning categories to stderr; default: silent |
| `FINNHUB_PLAN` | `auto` / `free` / `fundamental-1` — overrides `config.data_enrichment.finnhub_plan`. Note: env wins over config arg per `get_finnhub_plan()` precedence |
| `PYTHONUTF8` | Set to `1` for training (TRL/jinja codec compatibility; required since 2026-05-10 GPU swap) |
| `UNSLOTH_DISABLE_FUSED_CROSS_ENTROPY` | Training-time Unsloth flag (legacy — Unsloth deprecated 2026-05-10 per `project_gpu_upgrade`; training migrated to Transformers + PEFT + TRL pipeline. Wave E dual-GPU workload-separation deferred post-Sprint-5; flag preserved for backward-compat reading only) |

**Paths / runtime locations**:

| Variable | Purpose |
|---|---|
| `ARCIS_DATA_DIR` | Runtime data root (defaults to `C:/arcis/data/`) |
| `ARCIS_CORPUS_ROOT` | Corpus generation output root |
| `ARCIS_SIM_CACHE_ROOT` | Simulation cache directory |
| `ARCIS_SETTINGS_PATH` | Override path to `settings.yaml` |
| `ALPACA_BASE_URL` (optional) | Override Alpaca API base URL (testnet / custom) |

**Public IDs / non-secret config**:

| Variable | Purpose |
|---|---|
| `TELEGRAM_CHAT_ID` | Telegram chat ID for notifications |
| `ARCIS_LOCAL_API_TOKEN` | Local API auth token (binds 127.0.0.1 only) |
| `ARCIS_NOTIFICATION_SOURCE` | Set by pytest conftest to `"pytest:<worktree>"` for test isolation; production unset |

### Setting variables in NSSM

```cmd
nssm set <svc-name> AppEnvironmentExtra ARCIS_DB_PATH=C:\arcis\data\ai_research_desk.sqlite3 ^
                                       FINNHUB_API_KEY=<token> ^
                                       FRED_API_KEY=<token> ^
                                       TELEGRAM_BOT_TOKEN=<token> ^
                                       TELEGRAM_CHAT_ID=<id> ^
                                       ALPACA_API_KEY=<key> ^
                                       ALPACA_API_SECRET=<secret> ^
                                       ALPACA_PAPER_TRADE=1
nssm restart <svc-name>
```

After updating env vars, verify the watch loop picked them up:
```cmd
type C:\arcis\logs\watch.log | findstr "startup"
```

---

## Phase-3-revised cutover finalization checklist (#113)

When the operator runs the SQLite → PG cutover finalization (one-DB
discipline), follow this checklist to verify the cutover is complete
without orphaned state:

- [ ] `ARCIS_PG_CUTOVER_ENABLED=1` set in NSSM service env
- [ ] `DATABASE_URL` points to the canonical PG instance (`localhost:5433/halcyon` for local, or the Render PG URL for cloud)
- [ ] Run `python scripts/render_to_local_migrate.py --dry-run` and review the migration plan
- [ ] Run `python scripts/render_to_local_migrate.py` (with `--yes` for scripted) and verify row counts match the source SQLite
- [ ] Run `python -m src.main validate-schema` and confirm 0 drift items
- [ ] Run a SCAN cycle in dry-run mode (`python -m src.main scan --verbose --dry-run`) and confirm no `KeyError(0)` from a leaked `.fetchone()[0]` site
- [ ] Restart watch loop via `nssm restart <svc>` and check `C:\arcis\logs\watch.log` for `[STARTUP]` lines
- [ ] Confirm the AST scanner test `tests/test_no_fetchone_int_index_in_pg_unsafe_files.py` passes (`pytest tests/test_no_fetchone_int_index_in_pg_unsafe_files.py`)
- [ ] Confirm `tests/test_finnhub_plan_runtime_coverage.py` passes (matrix + runtime coverage invariants)
- [ ] Move the old SQLite file to `C:\arcis\data\archive\` (do NOT delete — operator may need it for forensic comparison per `#112`)

After cutover: `ARCIS_PG_CUTOVER_ENABLED=0` reverts to SQLite — the
engine routing is symmetric and bidirectional. Cutover is reversible.

---

## Walk-Forward Validation Gate (v1 — Sprint 6)

The walk-forward gate is a runtime promotion-gate component that requires a
strategy to demonstrate out-of-sample (OOS) performance across multiple
non-overlapping windows BEFORE moving from shadow_trading to production.
Wired in Sprint 6 (v0.36.0); see `docs/audits/2026-05-11-stage1-completion/walkforward-spec-v1.md`.

### Quick reference

- **Sentinel env var:** `WALKFORWARD_GATE_ENABLED` (default `true`). Set to
  `"false"` (case-insensitive `false`, `0`, `no`, or any non-canonical
  string) to disable the gate. Strict-on semantics — see T1 docstring at
  `src/platform/promotion.py::_evaluate_walkforward_gate`.
- **CLI:** `python -m scripts.backtest.run_walkforward --strategy <id>
  [--corpus-id <stage1-001>] [--excess-sharpe-min 0.3]
  [--backtest-result-id <id>] [--auto-fire] [--force]`
- **Auto-fire env var:** `WALKFORWARD_AUTOFIRE_ENABLED` (default `true`).
  Controls whether `scripts/run_backtest.py` post-persist hook spawns a
  detached walkforward subprocess after each backtest persists.
- **Stage-1 corpus:** `data/corpus/stage1-001/manifest.json` (filesystem-based;
  not in DB). Admissibility checked via the canonical
  `src/evaluation/walkforward._gate_corpus_or_raise` (load manifest +
  is_admissible + window coverage).

### Three-state outcome model

The walk-forward gate produces one of three outcomes — **never collapse to
boolean**:
- `PASS` — Sharpe ≥ 0.3 in ≥4 of 5 windows + criterion 2 (power) + criterion 3 (drawdown) + criterion 4 (heavy tail) + criterion 5 (VIX coverage).
- `FAIL` — explicit rejection (criterion 1 or 2 fails in ≥2 windows).
- `INCONCLUSIVE` — insufficient data (<10 trades in ≥2 windows) OR insufficient power (MDE > threshold in ≥2 windows) OR insufficient duration (<6 months in ≥2 windows).

### DA-1 freshness cap (production-only)

When a strategy reaches production candidacy, the production gate at
`_evaluate_production_gate` adds a freshness check on top of the standard
walkforward composition:

- `walkforward_results.code_git_sha` MUST equal current
  `backtest_results.code_git_sha` (strict sha-match).
- `walkforward_results.created_at` MUST be within the last 30 days.

On staleness: `evidence['walkforward_stale'] = True`,
`evidence['walkforward_stale_reason']` set to `'code_git_sha mismatch'` or
`'older than 30 days'`. Gate returns `False`.

### Falsifiability queries (SP-WF-016)

Three queries can be run against `walkforward_results` to falsify the
walk-forward gate's invariants. If any returns rows, Sprint 6 has shipped
a regression. Look up the EXACT SQL bodies in
`docs/audits/2026-05-13-sprint-6-walkforward-impl/specs/2026-05-13-sprint-6-walkforward-impl-design.md`
under §"SP-WF-016 — Falsifiability triggers for T13 + T14":

1. **Orphan-backtest query** — finds `backtest_results` rows without matching
   `walkforward_results` after the 7-day auto-fire reconciler window. If
   non-empty: the reconciler has failed to converge.
2. **Production-walkforward-evidence query** — finds `strategy_promotion_events`
   rows promoted to production WITHOUT a walkforward_outcome_state in the
   evidence dict. If non-empty: a strategy bypassed the production gate.
3. **Auto-fire-failure-rate query** — finds `platform_events` of type
   `walkforward_auto_fire_*` summarized by event_type over the last 7 days.
   If the giveup rate is non-trivial: investigate auto-fire stability.

```sql
-- Orphan backtest check (SP-WF-016 query 1)
SELECT br.result_id, br.strategy_id, br.created_at
FROM backtest_results br
LEFT JOIN walkforward_results wfr ON wfr.derived_from_backtest_id = br.result_id
WHERE br.created_at < datetime('now', '-2 hours')
  AND wfr.run_id IS NULL;

-- Production-promotion walkforward-evidence check (SP-WF-016 query 2)
SELECT spe.strategy_id, spe.timestamp
FROM strategy_promotion_events spe
WHERE spe.to_status = 'production'
  AND spe.timestamp > '2026-05-13'
  AND json_extract(spe.gate_result_json, '$.walkforward_outcome_state') IS NULL;

-- Auto-fire failure-rate check (SP-WF-016 query 3)
SELECT event_type, COUNT(*)
FROM platform_events
WHERE event_type LIKE 'walkforward_auto_fire%'
  AND timestamp > datetime('now', '-7 days')
GROUP BY event_type;
```

Operator should run these queries weekly during shadow→production promotion
cycles, OR after any change to the walkforward modules in
`src/platform/rigor/walkforward_*`.

### Runbook: disabling the gate (emergency)

To temporarily disable walkforward gating (e.g., during a known-good migration
window):

```bash
# Per-process override (preferred):
$env:WALKFORWARD_GATE_ENABLED = "false"
nssm restart ArcisWatchLoop

# Service-level (persistent across restarts):
nssm set ArcisWatchLoop AppEnvironmentExtra "ARCIS_DB_PATH=...;DATABASE_URL=...;WALKFORWARD_GATE_ENABLED=false"
nssm restart ArcisWatchLoop
```

Confirm disabled via `[6/6] Services` startup output —
`walkforward_gate_enabled=False` will appear in the next gate evidence dict.

---

End of Walk-Forward Validation Gate section.
