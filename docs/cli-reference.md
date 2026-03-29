# CLI Command Reference

All commands are invoked via `python -m src.main <command> [options]`.

## Core Pipeline (8 commands)

| Command | Description | Options |
|---------|-------------|---------|
| `init-db` | Initialize the SQLite journal database | `--db-path` (default: `ai_research_desk.sqlite3`) |
| `demo-packet` | Print a demo trade packet to stdout | |
| `send-test-email` | Send a test email to verify delivery | |
| `send-test-telegram` | Send a test Telegram notification | |
| `ingest` | Fetch OHLCV data for entire universe + SPY benchmark | |
| `scan` | Run full scan cycle (rank, qualify, write packets, execute) | `--verbose`, `--email`, `--dry-run`, `--no-shadow` |
| `morning-watchlist` | Generate pre-market watchlist | `--email`, `--dry-run` |
| `eod-recap` | Generate end-of-day recap | `--email`, `--dry-run` |

## Shadow Trading (4 commands)

| Command | Description | Options |
|---------|-------------|---------|
| `shadow-status` | List all open shadow (paper) trades with live P&L | |
| `shadow-history` | Show closed paper trades with aggregate metrics | `--days` (default: 30) |
| `shadow-close` | Manually close a paper position | `<ticker>` (required), `--reason` (default: manual) |
| `shadow-account` | Show Alpaca paper account balance and positions | |

## Live Trading (3 commands)

| Command | Description | Options |
|---------|-------------|---------|
| `live-status` | Show live account balance and open positions | |
| `live-history` | Show live trade history (open and closed) | `--days` (default: 30) |
| `live-close` | Manually close a live position | `<ticker>` (required), `--reason` (default: manual) |

## Review & Analysis (6 commands)

| Command | Description | Options |
|---------|-------------|---------|
| `review` | List pending reviews or review a specific trade | `[recommendation_id]` (optional; omit to list) |
| `mark-executed` | Mark a recommendation as manually executed | `<ticker>` (required) |
| `review-scorecard` | Print weekly review scorecard | `--weeks` (default: 1), `--email` |
| `review-bootcamp` | Print bootcamp progress report | `--days` (default: 30), `--email` |
| `postmortems` | List recent postmortem summaries | `--limit` (default: 10), `--ticker` |
| `postmortem` | Show full postmortem detail for a trade | `<recommendation_id>` (required) |

## Training Data (5 commands)

| Command | Description | Options |
|---------|-------------|---------|
| `training-status` | Show active model, dataset size, train readiness | |
| `training-history` | Show model version history with metrics | |
| `training-report` | Print detailed training pipeline report | `--email` |
| `bootstrap-training` | Generate synthetic training data via Claude | `--count` (default: 500), `--yes` |
| `backfill-training` | Backfill training examples from historical trades | `--months` (default: 12), `--max-examples` (default: 2000), `--min-score` (default: 70), `--include-messy`, `--yes` |

## Training Quality (5 commands)

| Command | Description | Options |
|---------|-------------|---------|
| `classify-training-data` | Classify examples into curriculum difficulty stages | |
| `score-training-data` | Run LLM-as-judge scoring on unscored examples | |
| `validate-training-data` | Validate dataset health (balance, format, duplicates) | |
| `generate-contrastive` | Generate contrastive training example pairs | `--max-pairs` (default: 50) |
| `generate-preferences` | Generate DPO preference pairs (chosen vs rejected) | `--count` (default: 100) |

## Training Execution (2 commands)

| Command | Description | Options |
|---------|-------------|---------|
| `train` | Run QLoRA fine-tuning (or export/rollback) | `--force`, `--rollback`, `--export` |
| `train-pipeline` | Run full pipeline: score, leakage check, classify, train | `--force` (continue despite leakage) |

## Evaluation (7 commands)

| Command | Description | Options |
|---------|-------------|---------|
| `cto-report` | Generate CTO performance analytics report | `--days` (default: 7), `--json`, `--email` |
| `evaluate-holdout` | Evaluate model on chronological holdout set | `--model` (default: halcyon-latest) |
| `model-evaluation-status` | Show A/B evaluation progress and recommendation | |
| `promote-model` | Promote evaluation model to active | `--force` |
| `feature-importance` | Compute feature importance from closed trades | `--days` (default: 30) |
| `backtest` | Walk-forward backtest a model | `--model` (default: halcyon-latest), `--months` (default: 6) |
| `compare-models` | Compare two models head-to-head | `--model-a` (required), `--model-b` (required), `--months` (default: 3) |

## Operations (9 commands)

| Command | Description | Options |
|---------|-------------|---------|
| `check-leakage` | Run outcome leakage detection on training data | |
| `collect-data` | Run full overnight data collection pipeline (7 stages) | |
| `fetch-earnings` | Fetch upcoming earnings dates for entire universe | |
| `halt-trading` | Emergency halt -- blocks all new positions immediately | |
| `resume-trading` | Resume trading after a halt | |
| `preflight` | Run system preflight check (config, APIs, LLM, DB) | |
| `council` | Run an AI Council deliberation session | `--type` (daily, strategic, on_demand) |
| `watch` | Start the automated scan/monitor loop | `--email-mode` (full_stream, daily_summary, silent), `--overnight` |
| `dashboard` | Start the FastAPI + React dashboard server | `--port` (default: 8000) |

## Command Count Summary

| Category | Count |
|----------|-------|
| Core Pipeline | 8 |
| Shadow Trading | 4 |
| Live Trading | 3 |
| Review & Analysis | 6 |
| Training Data | 5 |
| Training Quality | 5 |
| Training Execution | 2 |
| Evaluation | 7 |
| Operations | 9 |
| **Total** | **49** |
