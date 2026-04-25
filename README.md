# Arcis

![version](https://img.shields.io/badge/version-v0.27.0-blue?style=flat-square)
![phase](https://img.shields.io/badge/phase-1%20honest%20baseline-orange?style=flat-square)
![tests](https://img.shields.io/badge/tests-3%2C500%20passing-brightgreen?style=flat-square)
![audit](https://img.shields.io/badge/audit--2026--04--27-signed-blue?style=flat-square)
![python](https://img.shields.io/badge/python-3.12-3776AB?style=flat-square&logo=python&logoColor=white)
![model](https://img.shields.io/badge/model-Qwen3%208B-purple?style=flat-square)
![license](https://img.shields.io/badge/license-BSL%201.1-yellow?style=flat-square)
![issues](https://img.shields.io/github/issues/millerrc18/arcis?style=flat-square)
![dashboard](https://img.shields.io/badge/dashboard-halcyonlab.app-00C7B7?style=flat-square&logo=render&logoColor=white)

Systematic equity research platform built on fine-tuned LLMs and a 5-agent AI council. Arcis scans the S&P 100 universe for high-conviction pullback setups, generates trade packets with local inference, and executes bracket orders through Alpaca or Interactive Brokers — all governed by a hard risk stack, regime-aware sizing, and a score-gated dual-broker router.

## Current Status

- **Phase 1 Honest Baseline + Track 1.5 instrumentation gaps closed** (Track 1.5 PR on `feature/track-1.5-instrumentation-gaps`; audit closed 2026-04-25; signed memo at [`audits/2026-04-27/stage1_baseline_memo.md`](audits/2026-04-27/stage1_baseline_memo.md), commit `d651160`). Bootcamp paper trading archived to `C:/arcis/data/archive/ai_research_desk_bootcamp_2026-04-24.sqlite3`; current DB is fresh post-archive. Live deploy deferred per fix-now-before-trade principle (SD#46) until instrumentation gaps are confirmed closed and a strategy with positive expected alpha exists.
- **3-stage roadmap (audit-spec §3.1, supersedes SD#41 REVISED):** Stage 1 = honest signed baseline (DONE); Stage 2 = excess Sharpe ≥ 0.5 at p < 0.05 over 150 OOS via block bootstrap + ≥4-of-5 promotion gate; Stage 3 = > 1.0 at p < 0.05 over 300 OOS.
- **Stage-1 numbers (n=35 fully-instrumented from archive):** rf-adjusted excess Sharpe 6.14 (literal verdict GREEN per §3.1 Decision Matrix); SPY-relative non-significant at p=0.43 (the diagnostic gate — strategy not yet differentiated from passive long-SPY).
- **Track 1.5 instrumentation gaps closed (v0.27.0):** exit slippage (B1), broker exception logging (B2.A/B/C), exit_reason taxonomy (B3), LLM Key Risk persistence (B4), instrumentation_version sentinel (B5), B6 end-to-end test, LLM timeout persistence (B8), dashboard timeout visibility (B9), 5-KPI hero strip (Round 8.B), broker_exceptions panel (Round 8.C), preflight gate UI echo (Round 8.D). See `docs/audits/2026-04-27-trading-readiness/SHIPPED.md` for full scorecard.
- **Model**: `halcyon-v1.0.0` (Qwen3 8B, QLoRA fine-tuned); v2.0.0 retrain gated on Stage-2 promotion
- **Dashboard**: [halcyonlab.app](https://halcyonlab.app) (28 pages including 5-KPI hero strip, broker exceptions panel, preflight gate echo, Trade History with timeout visibility, mobile-responsive sidebar, dark/light toggle)
- **IB integration**: cold-stored per SD#41 — code intact, `trading.ib_enabled=false` default. Reactivation is a single flag flip; all modules, tests, table, and dependency preserved.
- **Current counts**: ~3,500 tests passing (Track 1.5 sweep pending) / 67 schema tables / 28 dashboard pages. See [MASTER.md](MASTER.md) Section 2 for full live metrics.

## 2026-04-27 Audit Artifacts

- [`docs/audits/2026-04-27-trading-readiness/SHIPPED.md`](docs/audits/2026-04-27-trading-readiness/SHIPPED.md) — what got delivered (26 commits, +342 net tests, +6 new module families)
- [`docs/audits/2026-04-27-trading-readiness/audit-spec.md`](docs/audits/2026-04-27-trading-readiness/audit-spec.md) — original spec (sections 3.1, 9, F-1 through F-16)
- [`audits/2026-04-27/stage1_baseline_memo.md`](audits/2026-04-27/stage1_baseline_memo.md) — signed memo (the artifact Mon's go/halt rests on)
- [`audits/2026-04-27/devils_advocate_stage1.md`](audits/2026-04-27/devils_advocate_stage1.md) — pre-sign-off skeptic checklist (5 categories)
- [`docs/methodology-toolkit.md`](docs/methodology-toolkit.md) — when to use CPCV / block bootstrap / MC perm / PSR-DSR-MinTRL / White RC / promotion gate

## Architecture

<p align="center">
  <img src="docs/architecture.svg" alt="Arcis System Architecture" width="100%"/>
</p>

See [MASTER.md](MASTER.md) Section 4 for the schema summary (67 tables). Full DDL in `src/schema/registry.py`.

See [Interactive Architecture (5W detail)](https://halcyonlab.app/architecture.html) for the full system diagram with expandable component details.

The scheduler runs 24/7: pre-market watchlist, intraday scans every 15 min, EOD recaps, overnight data collection (12 collectors), daily council sessions, and weekly training cycles.

## Quick Start

```bash
# Set up environment
python -m venv .venv && .venv\Scripts\activate  # Windows
pip install -r requirements.txt

# Configure secrets (.env) and settings (YAML)
cp .env.example .env           # Fill in API keys, tokens
cp config/settings.example.yaml config/settings.local.yaml  # Adjust thresholds

# Initialize DB + pull model
python -m src.main init-db
ollama pull qwen3:8b

# Test scan
python -m src.main scan --verbose --dry-run

# Start autonomous scheduler (validates config, schema, env, connectivity first)
python -m src.main startup
```

## Dashboard

Local: `python -m src.main dashboard` (localhost:8000)
Cloud: [halcyonlab.app](https://halcyonlab.app) (Render + Postgres sync)

## Tech Stack

- **Backend**: Python 3.12, FastAPI, SQLite (local), Postgres (cloud sync)
- **Frontend**: React 19, Vite 8, Tailwind 4, Recharts
- **Inference**: Ollama (Qwen3 8B), Anthropic Claude (council + quality scoring)
- **Broker**: Alpaca (paper + live, active) / Interactive Brokers (dormant per SD#41) via broker abstraction (`src/trading/`)
- **Data**: Finnhub, FRED, SEC EDGAR, Yahoo Finance, 12 overnight collectors
- **Ops**: Telegram alerts, Render sync, CI on PRs, command queue from dashboard

## Development Workflow

All code changes go through Claude Code (CC) sprints with strict guardrails:

**Sprint Rules:**
- ≤10 tasks per sprint; never refactor and add features in the same sprint
- Every sprint ends with a mandatory documentation update (see MASTER.md Section 9)
- No `src/` file exceeds 400 lines; no function exceeds 60 lines
- Refactor by extraction, not rewrite

**PR Review Discipline (human reviewer):**
- Fetch and read EVERY changed file before approving
- Check for: functions returning empty/default values, TODO/FIXME/placeholder comments, error handlers that just `pass`, missing implementations behind if/else branches, hardcoded mock data
- Do not merge until every file is verified

**CC Mandatory Steps (every sprint):**
1. Read `MASTER.md` before writing any code
2. Run `python -m pytest tests/ -x -q` before and after all changes
3. Run `npm run build` in `frontend/` to verify no build regressions
4. Run `python scripts/verify_docs.py` to check documentation drift
5. Update `MASTER.md` Section 2 and `CHANGELOG.md`
6. Update `scripts/render_migrate.py` if any new tables or columns were added
7. Update `config/settings.example.yaml` if any new config keys were added
8. Commit with descriptive messages referencing issue numbers

**Governance hierarchy:** `MASTER.md` → Charter → Blueprint → Code

## Research

91 documents in `docs/research/` covering regime detection, position sizing, risk management, training methodology, market microstructure, model degradation prevention, hardware deployment strategy, capital velocity optimization, and IB integration best practices (6 IB deep-research docs).

## SEC Compliance

All trading activity is AI-informed, systematic, and research-driven. The system operates under paper trading during the bootcamp phase. No advisory services are provided.

## License

[Business Source License 1.1](LICENSE) — source-visible, no commercial use. Converts to Apache 2.0 on 2030-03-31.
