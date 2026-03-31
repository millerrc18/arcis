# Arcis

Systematic equity research platform built on fine-tuned LLMs and a 5-agent AI council. Arcis scans the S&P 100 universe for high-conviction pullback setups, generates trade packets with local inference, and executes bracket orders through Alpaca -- all governed by a hard risk stack and regime-aware sizing.

## Current Status

- **Phase 1 Bootcamp** -- paper trading with ~25 active positions
- **Model**: `halcyon-v1` (Qwen3 8B, QLoRA fine-tuned on 790 examples)
- **Dashboard**: [halcyonlab.app](https://halcyonlab.app) (14 pages)

## Architecture

```
watch loop -> scan universe -> compute features -> rank
    -> LLM packet generation -> governor risk checks
    -> executor (bracket orders) -> bracket monitor
    -> training flywheel (self-blinded examples)
```

The scheduler runs 24/7: pre-market watchlist, intraday scans every 30 min, EOD recaps, overnight data collection, and weekly training cycles.

## Quick Start

```bash
# Set up environment
python -m venv .venv && .venv\Scripts\activate  # Windows
pip install -r requirements.txt

# Configure
cp config/settings.example.yaml config/settings.local.yaml
# Fill in API keys and broker credentials

# Initialize DB + pull model
python -m src.main init-db
ollama pull qwen3:8b

# Test scan
python -m src.main scan --verbose --dry-run

# Start autonomous scheduler
python -m src.main watch --email-mode daily_summary --overnight
```

## Dashboard

Local: `python -m src.main dashboard` (localhost:8000)
Cloud: [halcyonlab.app](https://halcyonlab.app) (Render + Postgres read replica)

```bash
cd frontend && npm install && npm run build && cd ..
```

## Tech Stack

- **Backend**: Python 3.12, FastAPI, SQLite (local), Postgres (cloud)
- **Frontend**: React 18, Vite, Tailwind CSS
- **Inference**: Ollama (Qwen3 8B), Anthropic Claude (council)
- **Broker**: Alpaca (paper + live)
- **Data**: Finnhub, FRED, SEC EDGAR, Yahoo Finance
- **Ops**: Telegram alerts, Render sync, 12 nightly data collectors

## Research

67 documents in `docs/research/` covering regime detection, position sizing, risk management, training methodology, and market microstructure.

## SEC Compliance

All trading activity is AI-informed, systematic, and research-driven. The system operates under paper trading during the bootcamp phase. No advisory services are provided.

## License

MIT
