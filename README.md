# Arcis

![version](https://img.shields.io/badge/version-v0.25.0-blue?style=flat-square)
![phase](https://img.shields.io/badge/phase-1%20diagnostic-orange?style=flat-square)
![tests](https://img.shields.io/badge/tests-2%2C272%20passing-brightgreen?style=flat-square)
![walkforward](https://img.shields.io/badge/walkforward--v1-three--state-amber?style=flat-square)
![python](https://img.shields.io/badge/python-3.12-3776AB?style=flat-square&logo=python&logoColor=white)
![model](https://img.shields.io/badge/model-Qwen3%208B-purple?style=flat-square)
![license](https://img.shields.io/badge/license-BSL%201.1-yellow?style=flat-square)
![issues](https://img.shields.io/github/issues/millerrc18/halcyon-lab?style=flat-square)
![dashboard](https://img.shields.io/badge/dashboard-halcyonlab.app-00C7B7?style=flat-square&logo=render&logoColor=white)

Systematic equity research platform built on fine-tuned LLMs and a 5-agent AI council. Arcis scans the S&P 100 universe for high-conviction pullback setups, generates trade packets with local inference, and executes bracket orders through Alpaca or Interactive Brokers — all governed by a hard risk stack, regime-aware sizing, and a score-gated dual-broker router.

## Current Status

- **Phase 1 Diagnostic** — paper trading $100K, 85 closed trades. Per SD#41 REVISED: halt optimization, run diagnostics first (D1 done v0.19.0, D2 done v0.22.0, D3 done v0.20.0).
- **Model**: `halcyon-v1.0.0` (Qwen3 8B, QLoRA fine-tuned); v2.0.0 retrain gated on excess-Sharpe validation
- **Dashboard**: [halcyonlab.app](https://halcyonlab.app) (25 pages including Trade History with excess-Sharpe lead panel, mobile-responsive sidebar, dark/light toggle)
- **IB integration**: cold-stored per SD#41 — code intact, `trading.ib_enabled=false` default. Reactivation is a single flag flip; all modules, tests, table, and dependency preserved.
- **Phase 1→2 gate (SD#41 REVISED):** excess-return Sharpe ≥ 0.5 at t ≥ 2.0 over 150 OOS trades (raw Sharpe gate deprecated — was trivially passed by bull-market SPY beta).
- **Current counts**: See [MASTER.md](MASTER.md) Section 2 for live metrics (tests, files, tables, etc.)

## Architecture

<p align="center">
  <img src="docs/architecture.svg" alt="Arcis System Architecture" width="100%"/>
</p>

See [MASTER.md](MASTER.md) Section 4 for the schema summary (53 tables). Full DDL in `src/schema/registry.py`.

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
