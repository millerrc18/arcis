# Arcis Operator's Guide

> **Single-source operational runbook.** When something needs doing, breaking, or unbreaking — start here. Updated regularly; if you encounter a procedure that isn't here, add it.

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
10. [Update Protocol](#10-update-protocol) — keeping this doc fresh

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

The methodology gate (Stage 2 prerequisite) is being wired into the live evaluation path under Sprint 2 — implementation in `docs/audits/2026-05-05-methodology-gate-wiring/`. Until then, promotion is operator-judgment.

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

```
Pre-market (07:00-09:30 ET):
  Universe scanner ─► point-in-time SP100 lookup (src/universe/pit.py)
  Data collectors ──► fundamentals, news, insider, macro snapshots
  Premarket scorer ─► rules-based score per ticker

Intraday (09:30-16:00 ET, 5-min cadence):
  Scan cycle:
    1. Filter universe by liquidity / regime / build score
    2. For each candidate: assemble "packet" (price, technicals, news, fundamentals)
    3. LLM call (Ollama) ─► returns conviction (1-10), direction, time horizon, key risks
    4. Risk governor ────► enforce position cap (min across 4 namespaces)
    5. Submit bracket order via Alpaca paper SDK
       - Bracket = entry + take-profit + stop-loss legs
       - Multipliers are config-driven via `live_trading.risk.{target,stop}_atr_multiplier`
         (typical values: 1.5×ATR target / 1.0×ATR stop in paper; 2.0×ATR target in live config —
         see PR #943 doc note for the asymmetry rationale)
       - OCO topology used when entry already filled and only protection legs remain
  Bracket monitor (every 5 min):
    - Verify both legs of every bracket are still active or healthy-completion
    - False-alert quarantine if not (PR #944)

Post-close (16:00-16:35 ET):
  reconcile_paper_trades  ──► reconcile local DB with broker state
  reconcile_live_trades   ──► same for live broker
  EOD report               ──► Telegram digest + email summary
  Build score recompute    ──► dashboard refresh

Methodology gate (16:35 ET, in flight via Sprint 2):
  Daily run of the 5-method voting gate over each strategy
  - Persists gate_proposal rows (informational)
  - Operator confirms via CLI to actually promote strategy

Overnight (16:35 ET - 07:00 ET):
  Data collection sweep   ─► fresh fundamentals, news, macros (7 days/week)
  VRAM handoff           ──► Ollama unload, training process can claim GPU
  Training cycle          ─► retrain on accumulated outcomes (when corpus ready)
  VRAM handoff           ──► training releases, Ollama reload before pre-market
```

### 0.5 The data lifecycle

```
Trade outcomes ──────────────►  shadow_trades table  ──► instrumentation filter ──► Stage 1/2/3 ladder
                                                                ▲
                                                                │
                                                       outcome_stats_filter_sql()
                                                       drops reconciled_stale rows
                                                       (Wave 4 H5)

Strategy candidate (LLM call) ──► trade ──► outcome ──► graded by build score / HSHS
                                                ▲
                                                │
                                            instrumentation_filter is_fully_instrumented()
                                            requires every telemetry column populated

LLM training data (corpus) ────►  data/corpus/stage1-001/entries.jsonl  ──► training pipeline ──► new model version
                                                ▲
                                                │
                                       packet_writer.py builds prompts from PIT-clean inputs;
                                       Ollama generates response; entry written if NOT a fallback.
                                       (fallback = Ollama failure ─► template; current bug task #52
                                        means fallback shares model_version with real entries)
```

**The instrumentation filter is the discipline that lets ARCIS make calibrated promotion decisions.** A trade missing any required column (cost, slippage, fundamental snapshot, etc.) is excluded from Stage 1/2/3 statistics. Roughly 30-60% of paper trades fail instrumentation in early operations and are excluded from the bar.

### 0.6 Key invariants (don't break these)

These rules are enforced by code, tests, or operator discipline. Breaking any of them silently corrupts the validation ladder.

| Invariant | Where enforced | Why it matters |
|---|---|---|
| Schema registry is single source of truth | `src/schema/registry.py` + `test_no_create_table_in_source` / `test_no_alter_table_in_source` CI tests | Drift between Postgres / SQLite / code → silent data loss |
| Risk governor is sacred | `src/risk/governor.py` (`min()` across 4 namespaces) | Bypass = unbounded position size; instant blow-up risk |
| PIT discipline | `src/universe/pit.py` + tests | Future-data leakage invalidates backtest results |
| Training data quality #1 | Corpus discriminator + (forthcoming) `model_version=template_fallback` tagging (#52) | Polluted training data → polluted future model |
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

### 0.9 The mental model in one paragraph

ARCIS is a tight feedback loop: **scan universe → LLM-score candidates → submit bracket orders → reconcile broker state → grade outcomes → (eventually, when corpus + outcomes are ready) retrain the LLM**. Everything else (schema discipline, instrumentation filter, methodology gate, three-stage ladder, render sync, dashboard) is in service of making that loop *honest* — i.e., resistant to overfitting, look-ahead bias, statistical artifacts, regime tailwinds, and silent data corruption. The reason the validation ladder is so strict is because the operator is one person betting their own capital; we'd rather discover after 300 OOS trades that the strategy works than after 30 OOS trades that it doesn't.

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

`OLLAMA_NUM_PARALLEL` user env var must be set to `2` to match (set via watchdog or `[Environment]::SetEnvironmentVariable("OLLAMA_NUM_PARALLEL","2","User")`). Mismatch (e.g. corpus `--num-parallel 4` vs `OLLAMA_NUM_PARALLEL=1`) causes Ollama to spawn N runner subprocesses, each loading a separate model copy → VRAM exhaustion → silent crash.

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
│    → manual fix: UPDATE sync_state SET status='idle', in_flight_since=NULL WHERE host_id='SWIFT-PC'
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

Root cause finding (2026-05-06): `packet_writer.py` has 5 fallback paths that all silently write template entries with the same `model_version="arcis:v1.0.0"` — indistinguishable from real LLM at training time. Discriminator: real LLM responses are 2400-3000 chars and start with natural-language analysis; templates are 750-800 chars and start with the rigid `<TICKER> is in a <trend>` prefix. Permanent fix is task #52 (skip-write or distinct `model_version="template_fallback"`).

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
| **Promotion gate** | ≥4-of-5 voting gate (PSR/DSR/PBO/MC permutation/White's RC) in `src/methods/promotion_gate.py`. Built but not yet wired into the live promotion path |
| **Reconciled_stale** | `exit_reason` value set when reconciler closes a shadow_trade that no longer exists at the broker. NOT a real strategy outcome — a bookkeeping artifact. Excluded from outcome stats (Wave 4 H5 + #919/#920 — `EXCLUDED_FROM_OUTCOME_STATS` constant) |
| **RenderSyncThread** | Background thread (`src/sync/render_sync.py`) that replicates local SQLite → Render Postgres. Per-table cursor in `sync_state` table |
| **Shadow trade** | Paper trade tracked in our DB (`shadow_trades` table). Mirrors broker-side state |
| **Sprint base branch** | A branch holding sprint specs as deliverable-0 commits (e.g. `sprint/wave-4-hotfixes/base`). Code lands via separate PRs against main |
| **Stage 1 / 2 / 3** | Three-stage validation ladder per MASTER.md SD#43. Stage 1 = baseline signed (`d651160`) + Stage 1 OOS sub-validation (excess-mean > 0 at t > 1.0 over 30 OOS); Stage 2 = IB-eligibility (excess Sharpe ≥ 0.5 over 150 OOS + ≥4-of-5 promotion gate); Stage 3 = full ramp (excess Sharpe > 1.0 over 300 OOS). See §9 for canonical text |
| **Subtract_trading_days** | NYSE-calendar-aware helper in `src/scheduler/holidays.py`. ALWAYS use for fetch anchors / lookback windows. Background: #888 / #106 incident traced corpus + backtester silent data gaps to 365-day calendar approximation drift |
| **T-A1, T-B3, etc.** | Sprint task identifiers (T = Task). e.g., Sprint 1.A Wave 2/3 had T-A1 (live_prices time column), T-B3 (backtester subtract_trading_days), etc. |
| **Walkforward** | `src/evaluation/walkforward.py` — anchored cross-validation. R1-R8 rigor requirements per pre-reg addendum |
| **Watch loop** | Main runtime daemon (`src/scheduler/watch.py::WatchLoop`). Single instance per host (PID lockfile) |
| **(Ollama) Watchdog** | `scripts/ollama_watchdog.ps1` — separate from the watch loop. Polls `/api/tags` every 30s, auto-restarts Ollama on death, captures daemon stderr to `logs/ollama-daemon.err` for crash diagnostics. Required before any corpus generation run. See §7 |
| **Worktree** | Independent git working directory sharing the same `.git` repo. Used for parallel agent isolation |
| **Template-fallback entry** | A corpus entry written by `packet_writer.py` when the LLM call failed (Ollama unreachable / parse failure / etc.). Discriminator: response < 1500 chars AND starts with rigid `<TICKER> is in a [strong\|weak]? (uptrend\|downtrend\|neutral)` prefix. Currently shares `model_version="arcis:v1.0.0"` with real LLM entries — task #52 will add distinct tagging. Real LLM responses are 2400-3000 chars and start with natural-language analysis |
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
2. **Stage 2** — IB-eligibility threshold: excess Sharpe ≥ 0.5 at p < 0.05 over 150 OOS trades + ≥4-of-5 promotion gate (PSR/DSR/PBO/MC permutation/White's RC). Toolkit is built but not yet wired into the live path.
3. **Stage 3** — Full ramp threshold: excess Sharpe > 1.0 at p < 0.05 over 300 OOS trades.

The methodology toolkit (`src/methods/`) is currently **shelf** — implemented but not wired. Wiring this into a live promotion path is the highest-leverage strategic work after operational stability lands.

---

## 10. Update Protocol

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

## See also

- [`CLAUDE.md`](../CLAUDE.md) — rules for AI agents working on the codebase (governance + schema discipline + worktree pattern)
- [`MASTER.md`](../MASTER.md) — canonical project state (architecture + sprint queue + current metrics)
- [`docs/methodology-toolkit.md`](methodology-toolkit.md) — reference for shelf statistical methods
- [`docs/dashboard-data-map.md`](dashboard-data-map.md) — dashboard tile data sources
- [`docs/audits/`](audits/) — sprint specs, audit reports, gap lists
- [`CHANGELOG.md`](../CHANGELOG.md) — release history under `[Unreleased]` and prior versions
