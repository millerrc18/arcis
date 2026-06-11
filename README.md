# Arcis

![version](https://img.shields.io/badge/version-v0.37.0-blue?style=flat-square)
![tests](https://img.shields.io/badge/tests-5%2C467%20floor%20(SQLite)-brightgreen?style=flat-square)
![python](https://img.shields.io/badge/python-3.12-3776AB?style=flat-square&logo=python&logoColor=white)
![model](https://img.shields.io/badge/model-Qwen3%208B-purple?style=flat-square)
![license](https://img.shields.io/badge/license-BSL%201.1-yellow?style=flat-square)
![dashboard](https://img.shields.io/badge/dashboard-halcyonlab.app-00C7B7?style=flat-square)

Arcis (Adaptive Regime Classification & Intelligence Systems) is a systematic equity-research platform built on a fine-tuned local LLM and a 5-agent AI council. It scans the S&P 100 for high-conviction pullback setups, generates institutional-quality trade packets with local inference, and executes bracket orders through Alpaca (Interactive Brokers dormant per SD#41) — all governed by an 8-check risk governor, regime-aware sizing, and a score-gated dual-broker router.

This README is the public-facing overview. The authoritative references are:

- **[MASTER.md](MASTER.md)** — single source of truth: system identity, current state, architecture, schema, strategy decisions, phase gates, conventions, and principles. Read this before making any change.
- **[CLAUDE.md](CLAUDE.md)** — engineering rules and local-dev workflow: schema-registry discipline, test floor, worktree discipline, repo layout, and common commands.
- **[RELEASES.md](RELEASES.md)** — release history, versioning policy, and the path to v1.0.0.
- **[docs/operator-guide.md](docs/operator-guide.md)** — daily ops cadence, troubleshooting decision trees, recovery patterns, CLI commands, and glossary.

## Quick Start (operator)

The runtime DB is **local Docker PostgreSQL** as of the 2026-05 SQLite→Postgres cutover. The git repo at `C:\arcis\halcyon-lab\` must be the working directory for every CLI invocation.

```bash
# 1. Environment (Windows)
python -m venv .venv && .venv\Scripts\activate
pip install -r requirements.txt

# 2. Secrets + config (never commit these — both are gitignored)
cp .env.example .env                                          # API keys, tokens
cp config/settings.example.yaml config/settings.local.yaml    # thresholds

# 3. Schema + model
python -m src.main validate-schema --fix                      # create/sync all tables from the registry
ollama pull qwen3:8b

# 4. Dry-run scan (no orders placed)
python -m src.main scan --verbose --dry-run

# 5. Launch the autonomous watch loop
#    Validates config/schema/env/connectivity, auto-fixes schema drift,
#    sends a Telegram start notification, then runs with --overnight defaults.
python -m src.main startup
```

The watch loop is managed by NSSM in production — restart it via `nssm restart ArcisWatchLoop`, **not** by re-running `python -m src.main startup` (that spawns a duplicate that races the managed instance). Full ops cadence, restart sequences, and stuck-position/lost-commit recovery live in the [operator guide](docs/operator-guide.md). Local-dev rules (schema registry, test discipline, worktree isolation) live in [CLAUDE.md](CLAUDE.md).

## Architecture

<p align="center">
  <img src="docs/architecture.svg" alt="Arcis System Architecture" width="100%"/>
</p>

See [MASTER.md](MASTER.md) Section 4 for the schema summary. The schema registry in `src/schema/registry.py` is the single source of truth for every table; get the authoritative count with:

```bash
python -c "from src.schema.registry import TABLES; print(len(TABLES))"
```

See [Interactive Architecture (5W detail)](https://halcyonlab.app/architecture.html) for the full system diagram with expandable component details.

The scheduler runs 24/7: pre-market watchlist, intraday scans every 15 min, EOD recaps, overnight data collection (12 collectors), daily council sessions, and weekly training cycles.

## Repo Layout

Runtime state lives **outside** the git repo by design — see [CLAUDE.md](CLAUDE.md) "Repo Layout (local dev)" for the full rationale and mechanism.

```
arcis/
├── src/             Python backend (FastAPI, scheduler, trading, training, schema registry)
│   ├── schema/      Schema registry — the ONLY place CREATE TABLE / ALTER TABLE may appear
│   ├── scheduler/   Watch loop + multi-cadence scanners
│   ├── shadow_trading/  Alpaca adapter, bracket orders, reconciliation
│   ├── risk/        8-check risk governor + kill switch
│   ├── council/     5-agent AI council (Modified Delphi protocol)
│   ├── llm/         Ollama client, packet writer, conviction parser
│   ├── training/    QLoRA training pipeline + quality gates
│   ├── platform/    Backtest engine + statistical rigor stack
│   └── simulation/  Trading-day lifecycle simulator + gates
├── tests/           pytest suite (SQLite floor 5,467 — see below)
├── frontend/        React 19 dashboard (Vite 8, Tailwind 4)
├── scripts/         Operator + maintenance scripts (migration, audit, backfill)
├── config/          YAML settings, guardrail baselines, known-violations allowlists
├── docs/            Research, audits, decisions, guides, operator-guide.md
├── MASTER.md        Single source of truth (read first)
├── CLAUDE.md        Engineering rules + local-dev workflow
└── RELEASES.md      Release history + versioning policy
```

The active database is **not** in the repo: `.env` sets the runtime DB location, and a 1 GB binary is kept out of `git status` / `git diff`. See [DIRECTORY.md](DIRECTORY.md) for the auto-generated full tree (regenerated each sprint via `scripts/generate_directory.py`).

## Dashboard

- **Local:** `python -m src.main dashboard` (localhost:8000)
- **Cloud:** [halcyonlab.app](https://halcyonlab.app) — the local dashboard exposed publicly via Cloudflare Tunnel (the `ArcisDashboard` NSSM service). Render hosting was decommissioned 2026-05 (see `docs/operations/render-decommission.md`).

Multi-page cockpit with a 5-KPI hero strip, broker-exceptions panel, preflight-gate echo, Trade History with timeout visibility, mobile-responsive sidebar, and a dark/light toggle.

## Tech Stack

- **Backend:** Python 3.12, FastAPI, PostgreSQL (local Docker — runtime DB since the 2026-05 SQLite→Postgres cutover; raw SQL via a thin engine-aware adapter, no ORM)
- **Frontend:** React 19, Vite 8, Tailwind 4, TanStack Query, Recharts
- **Inference:** Ollama (halcyon-v1.0.0, Qwen3 8B QLoRA fine-tuned), Anthropic Claude (council + quality scoring)
- **Training:** PEFT + TRL + BitsAndBytes on RTX 3090 24GB (RTX 3060 12GB secondary)
- **Broker:** Alpaca (paper + live, active) / Interactive Brokers (dormant per SD#41, `trading.ib_enabled=false`) via broker abstraction (`src/trading/`)
- **Data:** Finnhub, FRED, SEC EDGAR, Yahoo Finance, 12 overnight collectors
- **Ops:** Telegram alerts, Cloudflare Tunnel public access, NSSM-managed services, CI on PRs, command queue from the dashboard

## Testing

```bash
python -m pytest tests/ -q          # full suite
python -m src.main preflight        # operator preflight check
```

- **SQLite test floor: 5,467.** CI enforces that the SQLite-path suite never drops below this count (see [CLAUDE.md](CLAUDE.md) "Test count must not drop" for the full floor lineage). The floor is a regression tripwire — bump it in CLAUDE.md whenever the suite grows past it.
- **PostgreSQL CI floor: 5,267.** The PG-aware sweep (`.github/workflows/pg-tests.yml`) runs the full suite against a Postgres service and enforces a deliberately lower floor, because the chronic-failure class (worktree env-drift, hardcoded fixtures, env-pollution) costs the hosted-runner sweep a few hundred tests relative to the local SQLite run.
- **External APIs are always mocked** — no network calls from pytest (Alpaca, Finnhub, yfinance, FRED, Ollama).

## Development

All code changes go through Claude Code sprints with strict guardrails. The complete rules — schema-registry discipline (`CREATE TABLE` only in `src/schema/registry.py`), the test floor, parallel-agent worktree discipline, data-collection contracts, and the per-PR checklist — live in **[CLAUDE.md](CLAUDE.md)**. Highlights:

- No `src/` file exceeds 400 lines; no function exceeds 60 lines (`tests/test_repo_structure.py` enforces this).
- Never refactor and add features in the same sprint; refactor by extraction, not rewrite.
- Every PR updates `CHANGELOG.md` under `[Unreleased]`; releases bump `src/version.py` and create a git tag.
- Governance hierarchy: `MASTER.md` → Charter → Blueprint → Code.

## Research

The `docs/research/` corpus covers regime detection, position sizing, risk management, training methodology, market microstructure, model-degradation prevention, hardware deployment strategy, capital-velocity optimization, and IB integration best practices. The statistical-rigor toolkit (CPCV, block bootstrap, Monte Carlo permutation, PSR/DSR/MinTRL, White's Reality Check, and the ≥4-of-5 promotion gate) is documented in [docs/methodology-toolkit.md](docs/methodology-toolkit.md).

## SEC Compliance

All trading activity is AI-informed, systematic, and research-driven. The system operates under paper trading. No advisory services are provided.

## License

[Business Source License 1.1](LICENSE) — source-visible, no commercial use. Converts to Apache 2.0 on 2030-03-31.
