# Halcyon Lab

An autonomous AI trading system that scans equities, generates institutional-quality trade commentary using a fine-tuned Qwen3 8B model, executes bracket orders via Alpaca paper trading, and continuously improves through a self-blinding training pipeline with quality gates. Business model: investing returns, not newsletter.

## Features

- **Systematic Scoring**: 0-100 composite score from 20+ technical indicators
- **7+ Data Sources**: Technical, regime, sector, fundamentals, insiders, news, macro
- **Fine-Tuned LLM**: halcyon-v1 (Qwen3 8B fine-tuned on 790 self-blinded examples)
- **Bracket Orders**: Automated entry + stop + target via Alpaca paper trading
- **Risk Governor**: 8 safety checks + kill switch to halt all trading
- **Self-Blinding Pipeline**: Claude generates training data WITHOUT seeing outcomes
- **Training Pipeline**: Score → leakage check → classify → 3-stage curriculum SFT
- **Walk-Forward Backtesting**: Validate model performance on historical data
- **A/B Model Evaluation**: Shadow evaluation before model promotion
- **Dashboard**: React web interface with 9 pages, WebSocket live updates, action buttons
- **24/7 Operations**: Overnight schedule for data collection, training, and enrichment
- **Data Collection**: Options chains, VIX term structure, macro indicators, Google Trends
- **13 Research Documents**: Training methodology, strategy, business/fund path, options
- **24/7 Compute Scheduler**: Between-scan scoring, VRAM handoffs, overnight training (2%→73% GPU)
- **Telegram Notifications**: Real-time push alerts for trades, earnings, system events

## Prerequisites

- Python 3.12+
- Node.js 18+ (for dashboard)
- Ollama (for local LLM inference)
- NVIDIA GPU with 12GB+ VRAM (RTX 3060 minimum)
- Alpaca paper trading account
- API keys: Finnhub (free), FRED (free), Anthropic (for training data generation)

## Quick Start

```bash
# 1. Clone and setup
git clone <repo-url> && cd halcyon-lab
python -m venv .venv && source .venv/bin/activate  # or .venv\Scripts\activate on Windows
pip install -r requirements.txt

# 2. Configure
cp config/settings.example.yaml config/settings.local.yaml
# Edit config/settings.local.yaml with your API keys

# 3. Initialize
python -m src.main init-db

# 4. Pull LLM model (or use fine-tuned halcyon-v1)
ollama pull qwen3:8b

# 5. Run a scan
python -m src.main scan --verbose --dry-run

# 6. Start the dashboard
cd frontend && npm install && npm run build && cd ..
python -m src.main dashboard

# 7. Start the automated watch loop (with overnight schedule)
python -m src.main watch --email-mode daily_summary --overnight
```

## Training

```bash
# Full unified pipeline (recommended)
python -m src.main train-pipeline --force

# Or step by step:
python -m src.main backfill-training --months 12 --yes   # Generate training data
python -m src.main score-training-data                      # Score with LLM-as-judge
python -m src.main check-leakage                            # Verify no outcome leakage
python -m src.main classify-training-data                   # Assign curriculum stages
python -m src.main train --force                            # Fine-tune
```

## Data Collection

```bash
# Run all data collection manually
python -m src.main collect-data

# Runs automatically at 9:30 PM ET with --overnight flag
# Collects: options chains, VIX term structure, CBOE ratios, FRED macro, Google Trends
```

## Architecture

See [docs/architecture.md](docs/architecture.md) for the full system architecture, database schema, and data flow diagrams.

## Documentation

- [Architecture](docs/architecture.md) — System design, database schema, API routes
- [Training Guide](docs/training-guide.md) — Training data pipeline, quality scoring, curriculum
- [Roadmap](docs/roadmap.md) — 5-phase development plan with performance gates
- [Email Setup](docs/guides/email_setup.md) — SMTP configuration guide

## License

MIT
