# 🎯 Arcis — System State (Single Source of Truth)

**This document is updated after every conversation with Claude. It IS the system state.**
**Claude: You MUST read this file at the start of every session and update it after every substantive change.**

> Last updated: April 1, 2026 (PM) · All sprints merged (4A-8 + reconciliation + analytics + dashboard redesign + log audit + data integrity + mega sprint). Mega Sprint: 15-min intra-day reconciliation, exit_failed recovery, Telegram gating, profit factor fix, React Flow pages, sidebar reorg, UI fixes. Tests: 1,228. 173 Python files, 101 test files, 16 dashboard pages, 40 sync tables. BSL 1.1 license.

---

## Current System State
- **Phase:** 1 (Bootcamp) — paper trading $100K + $100 live via Alpaca
- **Open positions:** 25
- **Closed trades:** 13 (need 50 for Phase 1 gate) — 12W/1L, 92% WR, $860 total P&L
- **Tests:** 1,228 test functions across 101 test files
- **Python files:** 173 | **Dashboard pages:** 16 | **Research docs:** 60
- **Monthly cost:** ~$64 (Render $7 + Ollama free + Claude API ~$50 + domain $7)
- **Model:** halcyonlatest / halcyon-v1.0.0 (Qwen3 8B, Q8_0 GGUF 8.7GB) via Ollama
- **Next model:** Qwen 2.5 14B or Qwen3 14B (requires RTX 3090, Phase 2)
- **Dashboard:** halcyonlab.app (Render) — Arcis branding, Palette H, dark/light toggle
- **Hardware:** RTX 3060 12GB, Windows 11 (RTX 3090 + headless Linux planned Phase 2)
- **GitHub Issues:** 5 open (from 87 — 82 closed this session), 3 milestones, CI on PRs
- **License:** BSL 1.1 (source-visible, no commercial use until 2030)
- **Release:** v0.1.0 — Arcis

---

## Configuration

**Two files, clear separation:**
- `config/settings.yaml` — ALL non-secret config (committed to git). Thresholds, intervals, feature flags, model names.
- `.env` — ALL secrets (gitignored). API keys, tokens, passwords. Documented in `.env.example`.

**How it works:** `load_dotenv()` runs at startup in `main.py`. Each module checks `os.environ.get()` first, falls back to YAML config. Both paths work simultaneously.

**Key YAML sections:**
- `bootcamp.*` — Phase 1: enabled, phase, max_positions (50), scan_interval, qualification_threshold (40), traffic_light_floor (0.5)
- `shadow_trading.*` — enabled, max_positions, timeout_days (default 7 pullback)
- `risk.*` — starting_capital, planned_risk_pct_min/max, risk_governor settings
- `llm.*` — model name, min_conviction_score, enabled
- `scheduler.*` — scan_interval_minutes, market hours
- `automation.*` — morning_watchlist_hour, eod_recap_hour
- `training.*` — auto_train_threshold
- `data_enrichment.*` — cache_hours
- `council.*` — session schedules, thresholds

**Secrets in .env:**
- `ALPACA_API_KEY`, `ALPACA_API_SECRET` — Paper trading
- `ALPACA_LIVE_API_KEY`, `ALPACA_LIVE_SECRET_KEY` — Live trading
- `ANTHROPIC_API_KEY` — Council sessions + quality scoring
- `FINNHUB_API_KEY` — Insider data, analyst estimates, news
- `FRED_API_KEY` — Macro data (Fed funds, yield curve, CPI, unemployment)
- `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` — Notifications
- `EMAIL_PASSWORD` — Email alerts (optional)
- `DATABASE_URL` — Render Postgres connection string

---

## Claude Code Automations

**Installed March 31, 2026.** Claude Code extensibility layer — MCP servers, hooks, skills, subagents, and project governance.

### MCP Servers (4)

| Server | Purpose | Config |
|---|---|---|
| **alpaca** | Direct Alpaca paper/live trading API access | `.mcp.json` (repo, gitignored) |
| **context7** | Live documentation lookup for all libraries (FastAPI, alpaca-py, React, yfinance, etc.) | `~/.claude.json` (project-scoped) |
| **github** | GitHub issues, PRs, actions — direct management without `gh` CLI | `~/.claude.json` (project-scoped) |
| **sqlite** | Direct SQL queries against `ai_research_desk.sqlite3` (40 tables) | `~/.claude.json` (project-scoped) |

### Hooks (4)

| Hook | Trigger | What It Does |
|---|---|---|
| **Auto-lint Python** | PostToolUse (Edit/Write) | Runs `ruff check --fix` + `ruff format` on any edited `.py` file |
| **Auto-lint JSX** | PostToolUse (Edit/Write) | Runs `eslint --fix` on any edited `.js`/`.jsx` file in `frontend/src/` |
| **Block .env edits** | PreToolUse (Edit/Write) | Prevents Claude from modifying `.env` or `.env.*` files — must be edited manually |
| **Block lock file edits** | PreToolUse (Edit/Write) | Prevents Claude from directly editing `*lock.json` or `*lock` files |

Config: `.claude/settings.json`

### Skills (4)

| Skill | Invocation | Purpose |
|---|---|---|
| **gen-test** | `/gen-test src/risk/governor.py` | Generates pytest test files matching project conventions (class-based, mock-heavy, issue-tagged) |
| **post-close-check** | `/post-close-check` | Runs `post_close_check.py`, parses reconciliation results, suggests fixes for discrepancies |
| **config-check** | `/config-check` or `/config-check --fix` | Runs `check_config.py` to detect drift between `settings.example.yaml` and `settings.local.yaml`, also cross-checks `.env.example` vs `.env` |
| **market-monitor** | `/market-monitor 5m` | Wraps `/loop` to run post-close reconciliation on a recurring interval (default 10m). Stop with `/cancel-ralph`. |

All skills are user-only (`disable-model-invocation: true`). Config: `.claude/skills/<name>/SKILL.md`

### Subagents (3)

| Agent | Purpose | When to Use |
|---|---|---|
| **security-reviewer** | Credential exposure, SQL injection, risk governor bypass detection, API auth gaps | Before merging PRs touching `src/risk/`, `src/api/`, or `.env`-adjacent code |
| **test-runner** | Runs full pytest suite, groups failures by module, identifies root causes, checks CI guardian minimum (1105) | After any code changes, before commits |
| **migration-checker** | Reviews DB schema changes for idempotency, cross-script sync (`migrate_production_db.py` ↔ `render_migrate.py`), backwards compatibility | Any time columns or tables are added/modified |

Config: `.claude/agents/<name>.md`

### Project Governance

| File | Purpose |
|---|---|
| **CLAUDE.md** | Project root — key rules, common commands, architecture quick ref. Points to AGENTS.md for full governance. |
| **AGENTS.md** | Full system governance (architecture, data sources, conventions, module registry) |
| **.claude/settings.json** | Hooks configuration |
| **.claude/settings.local.json** | Permission allowlist for specific bash commands |

### Plugins (28 installed, 11 relevant)

| Plugin | Slash Commands / Features | Relevance |
|---|---|---|
| **commit-commands** | `/commit`, `/commit-push-pr`, `/clean_gone` | Git workflow |
| **code-simplifier** | `/simplify` — Opus-powered review of changed code | Post-edit quality |
| **ralph-loop** | `/loop 5m <cmd>`, `/cancel-ralph` | Recurring monitoring |
| **telegram** | `/telegram:configure`, `/telegram:access` | DM bot → Claude session |
| **claude-md-management** | `/revise-claude-md`, `/claude-md-improver` | CLAUDE.md maintenance |
| **claude-code-setup** | `/claude-automation-recommender` | Automation discovery |
| **skill-creator** | Create/test/eval custom skills | Skill development |
| **frontend-design** | Frontend component design guidance | React dashboard |
| **feature-dev** | Feature planning and implementation | Sprint planning |
| **pr-review-toolkit** | PR review checklists and analysis | PR workflow |
| **security-guidance** | Security best practices | Trading system security |

Also installed (not repo-relevant): hookify, playground, plugin-dev, mcp-server-dev, explanatory-output-style, code-review, context7, github, playwright, superpowers, 6 LSP plugins (rust, ruby, go, swift, clang, jdtls)

**Removed:** pyright-lsp (incompatible with Windows — tries to spawn `pyright-langserver` as Unix command)

### Telegram Channel

- **Bot token**: Copied from `.env` to `~/.claude/channels/telegram/.env`
- **Runtime**: Bun 1.3.11
- **To activate**: `claude --channels plugin:telegram@claude-plugins-official`
- **Then pair**: DM bot on Telegram → `/telegram:access pair <code>` → `/telegram:access policy allowlist`

### Dependencies Added

| Package | Version | Purpose |
|---|---|---|
| **ruff** | 0.15.8 | Python linter + formatter (used by auto-lint hook) |
| **pyright** | 1.1.408 | Python static type checker (venv only — plugin removed, use `pyright src/` manually) |
| **bun** | 1.3.11 | JavaScript runtime (required by telegram plugin MCP server) |
| **@xyflow/react** | latest | React Flow library for Architecture + DB Schema pages |

### Config Files Added

| File | Purpose |
|---|---|
| **pyrightconfig.json** | Pyright config — scans `src/`, `scripts/`, `tests/` with basic type checking, uses `.venv` |

---

## What's Deployed & Running

| Component | Status |
|---|---|
| Watch loop (scan + monitor) | ✅ LIVE — 13 scans/day, overnight mode, sleep fixed |
| Traffic Light | ✅ FIXED — wired into scan cycle, bootcamp floor 0.5 (was 0.1) |
| Scan metrics recording | ✅ FIXED (4E) — every scan cycle writes a row |
| Council v2 (5 agents) | ✅ FIXED (4E) — failure sends Telegram alert |
| Build Score KPI | ✅ LIVE — 6-component geometric mean, API endpoint |
| Command queue | ✅ LIVE (4C) — pull-based, 10 command types |
| Config overrides | ✅ LIVE (4C) — whitelisted dashboard-editable settings |
| .env secret migration | ✅ LIVE — 10 modules, env-first with YAML fallback |
| Between-scan quality scoring | ✅ LIVE — GuardedScorer Ollama (free, automatic). 972/972 scored, avg 3.44 |
| PEAD enrichment | ✅ DEPLOYED — 5 signals |
| Implementation Shortfall | ✅ DEPLOYED |
| HSHS health score | ✅ DEPLOYED — 85.33 |
| Risk governor | ✅ DEPLOYED — 8 checks |
| 12 overnight collectors | ✅ RUNNING |
| Telegram | ✅ LIVE — 32 functions, gated behind trade_id (no spam on rejected trades) |
| Intra-day reconciliation | ✅ LIVE — every 15 min during market hours, resolves exit_failed/exit_pending trades |
| Dashboard (Arcis) | ✅ LIVE — 16 pages (+Architecture, DB Schema), sidebar sections, chart visibility fix |
| Render sync | ✅ LIVE — 40/40 tables configured, all Postgres CREATE TABLE entries present |
| Module registry (AGENTS.md) | ✅ LIVE — 138 entries |
| Automated guardrails | ✅ LIVE — test_repo_structure.py |
| CI on PRs | ✅ LIVE — tests + guardrails + frontend build |

---

## Sprint Status

| Sprint | PR | Key Deliverable |
|---|---|---|
| 4A (Codex) | #73 ✅ | Arcis rebrand, Palette H, v0.1.0 |
| 4B (CC) | #75 ✅ | Build Score, dashboard hero, .env wiring |
| 4C (CC) | #76 ✅ | Command queue, config overrides, Logs page |
| 4D (Codex) | #74 ✅ | Module registry, 138 docstrings, conventions.md |
| 4E (CC) | #77 ✅ | DB migration, Traffic Light, scan recording, README |
| 5 (CC) | #78 ✅ | Dashboard polish (8 pages redesigned) |
| 6 partial (CC) | #88 ✅ | .env secret migration — 10 modules, 11 tests |
| CC deep audit | ✅ Complete | 71 issues filed (#100-#169), health 6.5/10 |
| 7 (CC) | #172 ✅ | Reliability: crash handler, GTC brackets, heartbeat, TL stub, sync mutex, backoff (18 issues closed) |
| Reconciliation | #171 ✅ | Daily postclose paper trade reconciliation vs Alpaca |
| 8 (CC) | #173 ✅ | Comprehensive cleanup: 63 issues closed — training, council, LLM, data, trading, frontend, config |
| Analytics migration | #174 ✅ | Cloud endpoints read Postgres: HSHS, CTO Report, Build Score, Training Status, system/validation |
| Dashboard redesign | #175 ✅ | Shadow/Live Ledger redesign, CTO period selector, Validation feedback, Build Score scheduling |
| Log audit | #176 ✅ | Double logging fix, idempotent ALTER TABLEs, validate-system, DNS retry, SQLite retry, LLM timing |
| Data integrity | #177 ✅ | Reconciliation actual_exit_time fix, paper trade auto-close, bracket status constant, backfill migration |

### Mega Sprint (April 1 PM)
- ✅ **Intra-day reconciliation** — every 15 min during market hours (was only 4:30 PM post-close)
- ✅ **exit_failed recovery** — reconciler now resolves stuck trades: gone from Alpaca → close with P&L, still on Alpaca → revert to open
- ✅ **Position existence check** — executor pre-fetches Alpaca positions, logs WARNING for vanished tickers
- ✅ **Telegram gating** — broadcast_sync, Telegram, live trade, email all gated behind `if trade_id:` (no spam on risk-rejected)
- ✅ **Profit factor** — backend returns `None` (not 99/999) for infinite; frontend shows ∞ symbol
- ✅ **Ticker logos** — lowercased URLs + dot-to-dash for BRK.B-style tickers; onError fallback already existed
- ✅ **Chart visibility** — fillOpacity 0.1→0.25, strokeWidth=2 on all Area charts (ShadowLedger, LiveLedger, Dashboard)
- ✅ **Activity feed** — cloud normalizer now maps `event_type` (not `event`), parses JSON `detail` field
- ✅ **Sidebar** — grouped into 4 sections (Trading, Intelligence, System, Reference) with section headers
- ✅ **React Flow** — Architecture page (interactive system diagram) + DB Schema page (40-table ERD with live row counts)
- ✅ **Data recovery** — 8 exit_failed trades closed (DUK, EXC, SO, COST, BK, CAT, CVX, BMY), 3 premature exits reverted to open (PFE, COP, MO)
- ✅ **table-counts API** — new `/api/system/table-counts` endpoint for DB Schema page (local + cloud)

### Post-Merge Hotfixes (April 1 AM)
- ✅ VRAM handoff complete: torch.cuda.empty_cache(), ollama_llama_server kill, 45s timeout, Ollama restart on failure
- ✅ 7 missing Postgres tables added to render_migrate.py (build_score_history, audit_reports, metric_snapshots, earnings_calendar, macro_snapshots, options_metrics, vix_term_structure)
- ✅ `recommendations.regime_label` → `market_regime` — fixed 503 on shadow/open, shadow/closed, cto-report
- ✅ API costs $0.00 — endpoint read `estimated_cost`, data in `cost_dollars` — fixed with COALESCE
- ✅ WebSocket console spam — exponential backoff + max 5 retries
- ✅ Pre-market brief S&P futures + 10Y yield — was hardcoded 0.0, now pulls from yfinance (ES=F, ^TNX)

---

## Lockdown Plan (Active Now)

**Daily (Mon-Fri):** System trades autonomously. Don't touch it.
**After close (optional):** `python scripts/post_close_check.py` — 8-point confidence check (1 min)
**Saturday:** Weekly retrain IF ≥10 new closed trades: `python -m src.main train-pipeline` (5 min trigger, 2-4 hrs GPU)
**Sunday:** `python scripts/weekly_review.py` → paste to Claude → audit + Monday action items (30 min)

**Only intervene for:** Telegram CRITICAL (bracket failure, kill switch), VIX >40, system offline.

**Key scripts:**
- `post_close_check.py` — daily confidence (scans, TL, positions, council, scoring, collectors, errors, sync)
- `weekly_review.py` — 7-section review with data inventory + week-over-week deltas
- `diagnose_leakage.py` — TF-IDF leakage investigation (run before any retrain)

---

## Key Decisions This Session (March 31)

- **Bootcamp Traffic Light floor:** 0.5 (was 0.1). Paper trading collects data in ALL regimes.
- **settings.yaml committed to git** — secrets removed to .env, YAML safe to track
- **Leakage investigation:** CLOSED. False alarm — balanced accuracy 0.613 can't beat 71.4% majority baseline.
- **Quality scoring automated** — GuardedScorer runs Ollama between scans (free). 972/972 complete.
- **One machine, all desks** — multi-LoRA serving via llama-server, not one machine per desk
- **Model roadmap:** Qwen3 8B (now) → Qwen 14B (Phase 2, RTX 3090) → strategy-specific 14B adapters (Phase 3+)
- **LLM role:** Phase 1 = commentary engine (doesn't gate paper trades). Phase 2+ = decision-maker with conviction gating.
- **System State moved from Notion to repo** — version controlled, no MCP dependency

---

## GitHub Issues

87 issues filed across two audits (Codex + CC deep). 82 closed via Sprints 7-8. **5 remaining:**

| # | Priority | Title |
|---|---|---|
| #147 | P2 | No exponential backoff on network failures in enrichment |
| #132 | P2 | Fallback to settings.example.yaml with placeholder keys — no validation |
| #112 | P2 | VRAM not freed after training — GPU memory leak |
| #106 | P2 | Kill switch not atomic, no staleness check |
| #82 | P3 | Silent exception swallowing in council/context.py |

---

## Weekly Review Findings (March 30)
- 13 closed (after exit_failed recovery): 12W/1L, $860 total P&L, 92% WR
- HSHS: 85.33
- Leakage: FALSE ALARM
- Class imbalance: 71.4% WIN / 28.6% LOSS (v2 targets 40/25/5/15)
- 972 training examples, 20 unique tickers
- Computer sleep issues resolved
- 11 exit_failed trades found — 8 truly exited (closed), 3 premature (reverted to open)

---

## Phase Gates

| Gate | Requirement | Current | Status |
|---|---|---|---|
| Phase 1 → 2 | 50 closed trades, WR≥45%, Sharpe≥0.15, PF≥1.3, DD≤12% | 13 closed, 92% WR | 26% |
| Phase 2 → 3 | 100 closed + Strategy #2 live + RTX 3090 | 0 | Not started |
| GRPO | 100+ closed trades | 0 | Blocked on data |
| Fund formation | Track record + $2M AUM | N/A | Year 3+ |

---

## Model Roadmap

| Phase | GPU | Model | Status |
|---|---|---|---|
| Phase 1 (now) | RTX 3060 12GB | Qwen3 8B (Q8_0) | ACTIVE |
| Phase 2 | RTX 3090 24GB | Qwen 2.5 14B or Qwen3 14B | After 50-trade gate |
| Phase 3+ | RTX 3090 + multi-LoRA | Strategy-specific 14B adapters | After 100 trades |
| Stretch | Second 3090 or RTX 5090 | Qwen3 30B-A3B MoE | If 14B hits ceiling |

GRPO training: RunPod A100 cloud ($14/mo), not local hardware.

---

## Strategy Decisions (16 confirmed)
1. Strategy #1 = Pullback-in-uptrend (LIVE)
2. Strategy #2 = Mean Reversion / Connors RSI(2) (Phase 2)
3. Strategy #3 = Evolved PEAD (Phase 3)
4. RL = Dr. GRPO (at 100 trades)
5. Breakout = pullback feature, not separate strategy
6. Traffic Light RED=0.1 safety override (bootcamp floor 0.5)
7. Volatility-adaptive sizing → Phase 2
8. Event calendar = 0-10 continuous scoring
9. Equal-weight until 200+ trades/strategy
10. Tax strategy (475f/TTS) tabled
11. Holding periods: pullback 7d, MR 5d, PEAD 10d
12. Council: portfolio-level only Phase 1
13. Council: hardcoded thresholds
14. Council: alert 8wk, auto-tighten 12wk, restore 4wk
15. Council: holistic + per-agent value tracking
16. Council: daily + weekly, monthly after 3 months

---

## Brand Decisions (finalized)
- **Name:** Arcis (Adaptive Regime Classification & Intelligence Systems)
- **Entity:** Arcis → Arcis Capital Management, LLC → Arcis Labs
- **Palette:** H (Electric Focus) — #050507 + #3B82F6
- **Typography:** Inter + JetBrains Mono
- **Voice:** 65% academic / 35% tech startup
- **SEC language:** "AI-informed", "systematic", "research-driven"

---

## Hardware Decisions
- Keep Q8_0 quantization — quality is king
- GRPO: RunPod A100 cloud ($14/mo), not local
- **UPS: CyberPower CP1500PFCLCD (~$220) — BUY IMMEDIATELY** (contributing factor in DB corruption incident #181)

### Phase 2: Dedicated Trading Server (~$1,300)

**Trigger:** Phase 1 gate passed (50 closed trades) OR database corruption recurrence.

| Component | Spec | Cost | Why |
|---|---|---|---|
| GPU | RTX 3090 24GB (used) | ~$700 | 14B model, GRPO, multi-LoRA serving |
| CPU | Ryzen 5 5600 or i5-12400 | ~$120 | 6 cores — GPU does the heavy lifting |
| RAM | 32GB DDR4 | ~$60 | Postgres + Python + Ollama headroom |
| Storage | 1TB NVMe | ~$70 | Fast DB I/O, model storage |
| Case + PSU | Basic mATX + 750W | ~$120 | 3090 needs 350W TDP |
| UPS | CyberPower CP1500PFCLCD | ~$220 | Non-negotiable after incident #181 |
| **Total** | | **~$1,290** | |

**Software stack:**
- Ubuntu Server 24.04 (headless, no desktop, no cloud sync)
- PostgreSQL 16 (local primary — replaces SQLite entirely)
- Ollama (inference + training, 24GB VRAM)
- Watch loop runs 24/7, no sleep/restart interruptions
- Render Postgres becomes cloud read-replica (keep for dashboard)
- SSH from Windows machine for management + Claude Code sessions

**Architecture after Phase 2:**
```
[Dedicated Linux Server]               [Render Cloud]
  PostgreSQL 16 (primary) ──sync────→  PostgreSQL (read replica)
  Ollama (halcyon-v1 / v2)              FastAPI (cloud_app.py)
  Watch Loop (24/7)                     React Dashboard
  Training Pipeline                     halcyonlab.app
  12 Data Collectors

[Windows PC]
  SSH → Linux server
  Claude Code sessions
  Development only — no production data
```

**What this eliminates:**
- OneDrive/cloud sync corruption (incident #181 root cause)
- SQLite concurrency issues (Postgres handles natively)
- Power loss corruption (UPS)
- GPU contention with daily use
- Windows sleep/restart interruptions
- VRAM handoff complexity (24GB = inference + training without swapping)

---

## CC Sprint Queue

| Priority | Sprint | Prompt | Status |
|---|---|---|---|
| 1 | **Schema Registry** | `docs/sprints/sprint-schema-registry.md` | QUEUED — **fire next** (prevents all schema-drift bugs) |
| 2 | React Flow interactive diagrams | `docs/sprints/sprint-react-flow.md` | ✅ DONE — PR #178 (Architecture + DB Schema pages) |
| 3 | Repo reorganization | TBD | Backlog |
| 4 | architecture.md refresh | TBD | Backlog |

---

## TODO (non-urgent)

### CRITICAL — Database Corruption Corrective Actions (Issue #181)
- [ ] **Move repo off OneDrive** — DB corrupted April 1 due to OneDrive sync conflict with WAL files. Move to `C:\Projects\halcyon-lab` or exclude `*.sqlite3*` from OneDrive sync. ROOT CAUSE of corruption.
- [ ] **Add `*.sqlite3*` to `.gitignore`** — WAL and SHM files tracked in git compound the problem
- [ ] **Startup integrity check** — `PRAGMA integrity_check` on startup, Telegram alert if malformed, refuse to overwrite with empty DB
- [ ] **Startup row count sanity check** — if shadow_trades drops from 50+ to 0, alert and abort instead of silently running on empty DB
- [ ] **Automated daily SQLite backup** — copy DB to `backups/` at EOD, keep 7 days, Telegram alert on backup failure
- [ ] **UPS: CyberPower CP1500PFCLCD (~$220)** — non-negotiable, prevents power-loss WAL corruption
- [ ] **Local PostgreSQL server (Phase 2)** — eliminates SQLite corruption risk entirely. Postgres handles concurrent writes, WAL, and crash recovery natively. Replaces SQLite as primary local store, Render Postgres becomes cloud replica.

### Infrastructure
- [ ] **Repo reorganization** — file structure needs cleanup: stale sprint docs, duplicate scripts, orphaned files, inconsistent naming
- [ ] **architecture.md refresh** — 1,245-line module registry is stale (counts from March 27). CC sprint task: read all 175 Python files and regenerate.
- [ ] Rename GitHub repo `halcyon-lab` → `arcis`
- [ ] GitHub Pro ($4/mo) for branch protection
- [ ] RTX 3090 + headless Linux machine ($1,500) — Phase 2
- [ ] Logo SVG cleanup — ChatGPT raster design chosen (top-left blue on black). Needs Fiverr ($50-100) to recreate as clean vector SVG.
- [ ] Domain: arcis.app or arciscapital.com
- [ ] Wyoming LLC formation (July 2026 target)
- [ ] WebSocket live endpoint (Phase 2+) — frontend client exists (WebSocketContext.jsx), needs backend `/ws/live` endpoint in watch loop. Low priority.

### Remaining GitHub Issues (12)

**Critical (real money / data integrity):**
- [ ] #182 — Intra-day reconciliation crashes: `name 'now' is not defined` (PR #178 bug)
- [ ] #183 — LLM conviction parsing 99% broken — 143/145 return None, all trades use default=5
- [ ] #184 — Recovery DB missing 11 time columns — sync fails for 11 tables every cycle
- [ ] #185 — Postgres duplicate key violations after recovery — sync inserts conflict
- [ ] #186 — Postgres missing `traffic_light_state.last_transition_at` — 28 sync errors
- [ ] #187 — 44 failed shadow trades — insufficient buying power, retries every scan
- [ ] #188 — PFE backfilled with -14 shares — short position in long-only system
- [ ] #181 — [INCIDENT] SQLite database corruption — RCCA + corrective actions documented

**Pre-existing:**
- [ ] #147 — No exponential backoff on network failures in enrichment
- [ ] #132 — Fallback to settings.example.yaml with placeholder keys
- [ ] #112 — VRAM not freed after training — GPU memory leak
- [ ] #106 — Kill switch not atomic, no staleness check
- [ ] #82 — Silent exception swallowing in council/context.py

### Completed This Session (March 31)
- [x] ~~Sprint 5~~ PR #78 — Dashboard polish (8 pages)
- [x] ~~Sprint 6 partial~~ PR #88 — .env secret migration (10 modules)
- [x] ~~Sprint 7~~ PR #172 — Reliability (18 issues closed)
- [x] ~~Sprint 8~~ PR #173 — Comprehensive cleanup (63 issues closed)
- [x] ~~Reconciliation~~ PR #171 — Daily postclose Alpaca reconciliation
- [x] ~~Analytics migration~~ PR #174 — Cloud endpoints read Postgres
- [x] ~~Dashboard redesign~~ PR #175 — Ledger redesign, CTO period selector, Build Score scheduling
- [x] ~~VRAM handoff fix~~ — torch.cuda.empty_cache(), ollama_llama_server kill, Ollama restart on failure
- [x] ~~Bootcamp TL floor~~ — 0.5 (was 0.1) for data collection in volatile regimes
- [x] ~~.env migration complete~~ — enricher.py FRED/Finnhub fix
- [x] ~~License~~ — MIT → BSL 1.1
- [x] ~~README badges~~ — shields.io (version, phase, tests, python, model, license, issues, dashboard)
- [x] ~~Config documentation~~ — settings.example.yaml expanded from 208 → 423 lines
- [x] ~~CC tooling installed~~ — GitHub MCP, Context7, SQLite MCP, ruff hooks, CLAUDE.md, skills, subagents
- [x] ~~87 → 5 open issues~~ — two audits (Codex + CC deep) filed 87 issues, 82 closed
- [x] ~~Log audit~~ PR #176 — Double logging, idempotent ALTER TABLEs, DNS retry, SQLite retry, LLM timing
- [x] ~~Data integrity~~ PR #177 — Reconciliation actual_exit_time fix, paper auto-close, bracket constant
- [x] ~~Mega Sprint~~ PR #178 — Intra-day reconciliation (15 min), exit_failed recovery, Telegram gating, profit factor ∞, React Flow (Architecture + DB Schema), sidebar sections, ticker logos, chart visibility, activity feed normalizer, position existence check
- [x] ~~SQLite DB recovery~~ — Corrupted by OneDrive sync; recreated fresh, data safe on Render Postgres
- [x] ~~Plugin fixes~~ — Alpaca MCP wrapped with `cmd /c` for Windows; pyright-lsp removed (Windows incompatible)
- [x] ~~gh CLI re-authenticated~~ — PAT token refreshed
