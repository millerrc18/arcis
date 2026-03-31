# Arcis

Systematic equity research platform built on fine-tuned LLMs and a 5-agent AI council. Arcis scans the S&P 100 universe for high-conviction pullback setups, generates trade packets with local inference, and executes bracket orders through Alpaca — all governed by a hard risk stack and regime-aware sizing.

## Current Status

- **Phase 1 Bootcamp** — paper trading $100K with ~25 active positions, 5/5 winners
- **Model**: `halcyon-v1.0.0` (Qwen3 8B, QLoRA fine-tuned on 972 scored examples)
- **Dashboard**: [halcyonlab.app](https://halcyonlab.app) (14 pages, Palette H dark/light)
- **Quality scoring**: 972/972 examples scored (avg 3.44/5.0), automated via GuardedScorer

## Architecture

```
watch loop → scan universe (every 15 min) → compute features → rank (0-100)
    → LLM packet generation → governor risk checks (8 checks)
    → executor (bracket orders: entry + stop + target) → bracket monitor
    → training flywheel (self-blinded examples → quality scoring → retrain)
```

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
