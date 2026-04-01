# CLAUDE.md — Halcyon Lab

## Governance

All project rules, architecture, data sources, and constraints are in **AGENTS.md** — read it before making changes.

## Key Rules

- **Never commit secrets** — `.env`, `config/settings.local.yaml`, and `.mcp.json` are gitignored for a reason
- **Training data quality is #1** — never sacrifice quality for speed
- **Risk governor is sacred** — never bypass or weaken risk checks without explicit approval
- **Test count must not drop** — CI enforces a minimum of 1105 tests
- **Mock all external APIs in tests** — no network calls from pytest (Alpaca, Finnhub, yfinance, FRED, Ollama)
- **Schema migrations required** — adding a column to any `CREATE TABLE IF NOT EXISTS` constant also requires a corresponding `ALTER TABLE ADD COLUMN` migration (wrapped in try/except) that runs BEFORE any indexes on that column. `CREATE TABLE IF NOT EXISTS` is a no-op on existing tables — it does NOT add missing columns
- **Test baseline before changes** — run `python -m pytest tests/ -q` at the start of any coding session and note the pass count. After changes, the pass count must not decrease and the failure count must not increase. Never dismiss test failures as "pre-existing" without investigating

## Common Commands

```bash
# Run tests
python -m pytest tests/ -v

# Preflight check
python -m src.main preflight

# Dry-run scan
python -m src.main scan --verbose --dry-run

# Shadow trading status
python -m src.main shadow-status

# Training status
python -m src.main training-status

# Post-close reconciliation
python scripts/post_close_check.py

# Frontend dev
cd frontend && npm run dev

# Lint Python (if ruff installed)
python -m ruff check src/ tests/ --fix
python -m ruff format src/ tests/
```

## Architecture Quick Ref

- **Backend**: Python 3.12, FastAPI, SQLite (raw sqlite3, no ORM)
- **Frontend**: React 19, Tailwind 4, Vite 8, TanStack Query
- **Deployment**: Render (static frontend + Python API)
- **Trading**: Alpaca paper trading (bracket orders, GTC)
- **LLM**: Ollama local (halcyon-v1, Qwen3 8B fine-tuned)
- **Config**: YAML (`config/settings.*.yaml`) + `.env` for secrets
