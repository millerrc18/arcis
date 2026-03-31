# Arcis

Arcis is an autonomous AI-powered equity trading system for S&P 100 swing trades. It combines systematic scoring, multi-source enrichment, local LLM trade commentary, Alpaca bracket execution, a hard risk governor, and a self-improving training pipeline built around self-blinded data quality.

## Current Surface

- **Strategy**: pullback-in-strong-trend equity trading with bracket orders and regime-aware sizing
- **Model**: `halcyon-v1` on Qwen3 8B, served locally through Ollama for packet generation
- **Risk stack**: validator, 8-check governor, kill switch, traffic-light overlay, system validation, and live/cloud diagnostics
- **Dashboard**: 13 pages across local/cloud surfaces, including Council, Health, Validation, Notes, Live Ledger, and CTO Report
- **Brand system**: Arcis identity with Palette H, refreshed PWA metadata, and a persisted dark/light dashboard theme
- **Data moat**: 12 nightly collectors plus enrichment for technicals, regime, sector, fundamentals, insiders, news, macro, filings, earnings, and options context
- **Research library**: 66 synced research documents plus governance and architecture docs
- **Cloud mirror**: Render frontend + FastAPI + Postgres read replica kept fresh by the local render sync thread

## Key Capabilities

- **Systematic scoring**: 0-100 setup ranking from technical, regime, sector, and event-aware features
- **Multi-source enrichment**: SEC EDGAR, Finnhub, FRED, options/VIX, analyst estimates, insider activity, short interest, and Fed communications
- **LLM packet writing**: XML trade commentary with `why_now`, `analysis`, and `metadata` blocks
- **Council and governance**: 5-agent council, parameter adjustments, calibration tracking, HSHS health scoring, and validation results
- **Training flywheel**: self-blinded generation, quality scoring, leakage checks, curriculum SFT, canary evaluation, and rollback protection
- **Operations**: 24/7 scheduler, render sync, Telegram alerts, postmortems, nightly collection, and weekly reporting

## Prerequisites

- Python 3.12+
- Node.js 18+ for the frontend
- Ollama for local inference
- NVIDIA GPU with 12GB+ VRAM recommended for the local model/training workflow
- Alpaca paper/live credentials
- API keys for Finnhub, FRED, and Anthropic if you want the full enrichment and training loop

## Quick Start

```bash
# 1. Clone and set up the environment
git clone <repo-url> && cd halcyon-lab
python -m venv .venv

# Windows
.venv\Scripts\activate

# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
```

```bash
# 2. Configure local settings
cp config/settings.example.yaml config/settings.local.yaml
# Fill in API keys, broker credentials, and optional Render sync settings
```

```bash
# 3. Initialize the database
python -m src.main init-db
```

```bash
# 4. Pull the local model (or register your fine-tuned build)
ollama pull qwen3:8b
```

```bash
# 5. Run a dry scan
python -m src.main scan --verbose --dry-run
```

```bash
# 6. Build the frontend and start the dashboard
cd frontend && npm install && npm run build && cd ..
python -m src.main dashboard
```

```bash
# 7. Start the autonomous scheduler
python -m src.main watch --email-mode daily_summary --overnight
```

## Common Workflows

```bash
# Full training pipeline
python -m src.main train-pipeline --force

# Manual data collection
python -m src.main collect-data

# Morning / end-of-day ops
python -m src.main morning-watchlist
python -m src.main eod-recap

# Reporting and health
python -m src.main cto-report
python -m src.main evaluate-gate
python -m src.main check-leakage
```

## Cloud Deployment

Render deployment and sync setup are documented in [docs/deployment.md](docs/deployment.md). The cloud surface is read-only: local trading, training, and collection remain the source of truth, while Render hosts the remote dashboard and Postgres mirror.

## Documentation

- [Architecture](docs/architecture.md) — system modules, route surfaces, data flow, and council architecture
- [Deployment](docs/deployment.md) — Render blueprint, Postgres migration, sync setup, auth, and verification
- [Roadmap](docs/roadmap.md) — phase plan and gating milestones
- [Training Guide](docs/training-guide.md) — training data, quality scoring, curriculum, and evaluation
- [CLI Reference](docs/cli-reference.md) — command surface and flags

## License

MIT
