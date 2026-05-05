# Arcis Operator's Guide

> **Single-source operational runbook.** When something needs doing, breaking, or unbreaking — start here. Updated regularly; if you encounter a procedure that isn't here, add it.

## Table of contents

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
- **Tail corpus generator (when running):** `tail -f C:/arcis/halcyon-lab/logs/stage1-corpus.log`
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

```bash
# Initial launch (Stage 1):
python scripts/generate_llm_corpus.py \
  --corpus-id stage1-001 \
  --window-start 2023-09-01 \
  --window-end 2026-04-28 \
  --num-parallel 4

# Resume after stop / hang:
python scripts/generate_llm_corpus.py \
  --corpus-id stage1-001 \
  --window-start 2023-09-01 \
  --window-end 2026-04-28 \
  --resume \
  --num-parallel 4
```

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
| `C:\arcis\halcyon-lab\logs\stage1-corpus.log` | Corpus generator log |
| `C:\arcis\halcyon-lab\data\corpus\stage1-001\entries.jsonl` | Generated corpus entries |
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

**To start fresh:**
```bash
python scripts/generate_llm_corpus.py \
  --corpus-id stage1-001 \
  --window-start 2023-09-01 \
  --window-end 2026-04-28 \
  --num-parallel 4
```

**To resume after stop / hang / restart:**
```bash
python scripts/generate_llm_corpus.py \
  --corpus-id stage1-001 \
  --window-start 2023-09-01 \
  --window-end 2026-04-28 \
  --resume \
  --num-parallel 4
```

The `--resume` flag dedup's via `prompt_sha256` against existing entries.jsonl — safe to invoke repeatedly.

**To monitor progress:**
```bash
tail -f C:/arcis/halcyon-lab/logs/stage1-corpus.log
wc -l C:/arcis/halcyon-lab/data/corpus/stage1-001/entries.jsonl
```

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
| **Worktree** | Independent git working directory sharing the same `.git` repo. Used for parallel agent isolation |

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
