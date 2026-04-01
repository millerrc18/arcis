# 🎯 Arcis — System State (Single Source of Truth)

**This document is updated after every conversation with Claude. It IS the system state.**
**Claude: You MUST read this file at the start of every session and update it after every substantive change.**

> Last updated: March 31, 2026 (end of session) · Sprints 5-8 + reconciliation + analytics migration + dashboard redesign ALL MERGED. 5 open issues remain (from 87). Tests: 1,235. 173 Python files, 101 test files. System in lockdown — 25 open positions, 5/5 winners. Dashboard fully functional on Render Postgres. BSL 1.1 license. CC tooling installed (GitHub MCP, Context7, SQLite MCP, ruff hooks, CLAUDE.md).

---

## Current System State
- **Phase:** 1 (Bootcamp) — paper trading $100K + $100 live via Alpaca
- **Open positions:** ~25
- **Closed trades:** 5 (need 50 for Phase 1 gate) — 5/5 winners, 4.1% avg gain, 2.2d hold
- **Tests:** 1,235 test functions across 101 test files
- **Python files:** 173 | **Dashboard pages:** 14 | **Research docs:** 77
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

### Hooks (2)

| Hook | Trigger | What It Does |
|---|---|---|
| **Auto-lint Python** | PostToolUse (Edit/Write) | Runs `ruff check --fix` + `ruff format` on any edited `.py` file |
| **Block .env edits** | PreToolUse (Edit/Write) | Prevents Claude from modifying `.env` or `.env.*` files — must be edited manually |

Config: `.claude/settings.json`

### Skills (3)

| Skill | Invocation | Purpose |
|---|---|---|
| **gen-test** | `/gen-test src/risk/governor.py` | Generates pytest test files matching project conventions (class-based, mock-heavy, issue-tagged) |
| **post-close-check** | `/post-close-check` | Runs `post_close_check.py`, parses reconciliation results, suggests fixes for discrepancies |
| **config-check** | `/config-check` or `/config-check --fix` | Runs `check_config.py` to detect drift between `settings.example.yaml` and `settings.local.yaml`, also cross-checks `.env.example` vs `.env` |

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

### Dependencies Added

| Package | Version | Purpose |
|---|---|---|
| **ruff** | 0.15.8 | Python linter + formatter (used by auto-lint hook) |

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
| Telegram | ✅ LIVE — 32 functions |
| Dashboard (Arcis) | ✅ LIVE — 14 pages, Sprint 5 polish merged |
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
| 6 remaining (CC) | Pending | Tasks 1-6: data collectors grid, training pipeline, scan metrics, card contrast |
| CC deep audit | ✅ Complete | 71 issues filed (#100-#169), health 6.5/10 |
| 7 (CC) | #172 ✅ | Reliability: crash handler, GTC brackets, heartbeat, TL stub, sync mutex, backoff (18 issues closed) |
| Reconciliation | #171 ✅ | Daily postclose paper trade reconciliation vs Alpaca |
| 8 (CC) | #173 ✅ | Comprehensive cleanup: 63 issues closed — training, council, LLM, data, trading, frontend, config |
| Analytics migration | #174 ✅ | Cloud endpoints read Postgres: HSHS, CTO Report, Build Score, Training Status, system/validation |
| Dashboard redesign | #175 ✅ | Shadow/Live Ledger redesign, CTO period selector, Validation feedback, Build Score scheduling |

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

## GitHub Issues (from audits)

| # | Label | Title | Status |
|---|---|---|---|
| #80 | bug | Duplicate /api/build-score route | ✅ Fixed |
| #81 | bug | Frontend calls nonexistent cloud endpoints | Sprint 6 Tasks 1-6 |
| #82 | tech-debt | Silent exception swallowing in council context | Open |
| #83 | tech-debt | Hardcoded ai_research_desk.sqlite3 in ~30 files | Open |
| #84 | documentation | .env.example missing 3 env vars | Sprint 6 Task 7 covers |
| #85 | test-gap | 73 modules without test files | Open (ongoing) |
| #86 | documentation | AGENTS.md route count stale (55 vs 76) | Open |
| #87 | documentation | Audit Summary — 6.5/10 health | Tracking |
| #89 | bug | Traffic Light API returns UNKNOWN (stub) | Open — P0 |
| #90 | bug | load_dotenv() missing from watch.py | Open — P1 |
| #91 | bug | Hardcoded Render URL in system_validator | Open — P1 |
| #92 | performance | No index on shadow_trades.status | Open — P2 |
| #93 | tech-debt | ~40 var(--slate-*) in Dashboard/Council | Sprint 6 Task 6 |
| #94 | tech-debt | Watch loop banner says HALCYON LAB | Open — P3 |
| #95 | tech-debt | config_overrides.py in wrong location | Open — P3 |
| #96 | tech-debt | build_score.py docstring says Halcyon Lab | Open — P3 |
| #97 | performance | No index on recommendations.created_at | Open — P3 |
| #98 | documentation | YAML config options undocumented | Open — P2 |

---

## Weekly Review Findings (March 30)
- 5/5 winners, $43.26 P&L, avg 4.1% in 2.2 days
- HSHS: 85.33
- Leakage: FALSE ALARM
- Class imbalance: 71.4% WIN / 28.6% LOSS (v2 targets 40/25/5/15)
- 972 training examples, 20 unique tickers
- Computer sleep issues resolved

---

## Phase Gates

| Gate | Requirement | Current | Status |
|---|---|---|---|
| Phase 1 → 2 | 50 closed trades, WR≥45%, Sharpe≥0.15, PF≥1.3, DD≤12% | 5 closed | 10% |
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
- RTX 3090 + headless Linux ($1,500 all-in) — Phase 2
- GRPO: RunPod A100 cloud ($14/mo), not local
- UPS: CyberPower CP1500PFCLCD (~$220) — non-negotiable

---

## TODO (non-urgent)
- [ ] Rename GitHub repo `halcyon-lab` → `arcis`
- [ ] GitHub Pro ($4/mo) for branch protection
- [ ] UPS: CyberPower CP1500PFCLCD (~$220)
- [ ] RTX 3090 + headless Linux machine ($1,500) — Phase 2
- [ ] Logo SVG cleanup — ChatGPT raster design chosen (top-left blue on black). Needs Fiverr ($50-100) to recreate as clean vector SVG. Current attempts in docs/logo-dark.svg and docs/logo-light.svg are placeholders.
- [ ] Domain: arcis.app or arciscapital.com
- [ ] Wyoming LLC formation (July 2026 target)
- [ ] WebSocket live endpoint (Phase 2+) — frontend client exists (WebSocketContext.jsx), needs backend `/ws/live` endpoint in watch loop. Low priority, polling works fine for 15-30 min scan intervals.

### Remaining GitHub Issues (5)
- [ ] #147 — No exponential backoff on network failures in enrichment
- [ ] #132 — Fallback to settings.example.yaml with placeholder keys — no validation
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
