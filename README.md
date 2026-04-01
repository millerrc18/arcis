# Arcis

![version](https://img.shields.io/badge/version-v0.1.0-blue?style=flat-square)
![phase](https://img.shields.io/badge/phase-1%20bootcamp-orange?style=flat-square)
![tests](https://img.shields.io/badge/tests-1%2C225%20passing-brightgreen?style=flat-square)
![python](https://img.shields.io/badge/python-3.12-3776AB?style=flat-square&logo=python&logoColor=white)
![model](https://img.shields.io/badge/model-Qwen3%208B-purple?style=flat-square)
![license](https://img.shields.io/badge/license-BSL%201.1-yellow?style=flat-square)
![issues](https://img.shields.io/github/issues/millerrc18/halcyon-lab?style=flat-square)
![dashboard](https://img.shields.io/badge/dashboard-halcyonlab.app-00C7B7?style=flat-square&logo=render&logoColor=white)

Systematic equity research platform built on fine-tuned LLMs and a 5-agent AI council. Arcis scans the S&P 100 universe for high-conviction pullback setups, generates trade packets with local inference, and executes bracket orders through Alpaca — all governed by a hard risk stack and regime-aware sizing.

## Current Status

- **Phase 1 Bootcamp** — paper trading $100K with ~25 active positions, 5/5 winners
- **Model**: `halcyon-v1.0.0` (Qwen3 8B, QLoRA fine-tuned on 972 scored examples)
- **Dashboard**: [halcyonlab.app](https://halcyonlab.app) (14 pages, Palette H dark/light)
- **Quality scoring**: 972/972 examples scored (avg 3.44/5.0), automated via GuardedScorer

## Architecture

<p align="center">
  <img src="docs/architecture.svg" alt="Arcis System Architecture" width="100%"/>
</p>

The scheduler runs 24/7: pre-market watchlist, intraday scans every 15 min, EOD recaps, overnight data collection (12 collectors), daily council sessions, and weekly training cycles.

## Quick Start

```bash
# Set up environment
python -m venv .venv && .venv\Scripts\activate  # Windows
pip install -r requirements.txt

# Configure secrets (.env) and settings (YAML)
cp .env.example .env           # Fill in API keys, tokens
cp config/settings.example.yaml config/settings.yaml  # Adjust thresholds

# Initialize DB + pull model
python -m src.main init-db
ollama pull qwen3:8b

# Test scan
python -m src.main scan --verbose --dry-run

# Start autonomous scheduler
python -m src.main watch --email-mode digest --overnight
```

## Dashboard

Local: `python -m src.main dashboard` (localhost:8000)
Cloud: [halcyonlab.app](https://halcyonlab.app) (Render + Postgres sync)

## Tech Stack

- **Backend**: Python 3.12, FastAPI, SQLite (local), Postgres (cloud sync)
- **Frontend**: React 18, Vite, Tailwind CSS, Recharts
- **Inference**: Ollama (Qwen3 8B), Anthropic Claude (council + quality scoring)
- **Broker**: Alpaca (paper + live, bracket orders)
- **Data**: Finnhub, FRED, SEC EDGAR, Yahoo Finance, 12 overnight collectors
- **Ops**: Telegram alerts, Render sync, CI on PRs, command queue from dashboard

## Research

67 documents in `docs/research/` covering regime detection, position sizing, risk management, training methodology, market microstructure, model degradation prevention, and hardware deployment strategy.

## SEC Compliance

All trading activity is AI-informed, systematic, and research-driven. The system operates under paper trading during the bootcamp phase. No advisory services are provided.

## License

MIT
