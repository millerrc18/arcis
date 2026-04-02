# CLAUDE.md — Halcyon Lab

## Governance

All project rules, architecture, data sources, and constraints are in **AGENTS.md** — read it before making changes.

## Key Rules

- **Never commit secrets** — `.env`, `config/settings.local.yaml`, and `.mcp.json` are gitignored for a reason
- **Training data quality is #1** — never sacrifice quality for speed
- **Risk governor is sacred** — never bypass or weaken risk checks without explicit approval
- **Test count must not drop** — CI enforces a minimum of 1105 tests
- **Mock all external APIs in tests** — no network calls from pytest (Alpaca, Finnhub, yfinance, FRED, Ollama)
- **Schema registry is the single source of truth** — all 46 tables are defined in `src/schema/registry.py`. See "Database Schema Rules" below
- **Test baseline before changes** — run `python -m pytest tests/ -q` at the start of any coding session and note the pass count. After changes, the pass count must not decrease and the failure count must not increase. Never dismiss test failures as "pre-existing" without investigating

## Database Schema Rules (MANDATORY)

All database tables are defined in `src/schema/registry.py` — the single source of truth.

1. **NEVER write `CREATE TABLE` in any file except `src/schema/registry.py`** — CI guardrail tests and hookify rules will block it
2. **NEVER write `ALTER TABLE` in any file except `src/schema/registry.py`** — column additions go through the registry
3. **To add a new table:** Add a `TableDef` to `TABLES` in `src/schema/registry.py`, then run `python -m src.main validate-schema --fix`
4. **To add a column:** Add a `ColumnDef` to the table's columns list in `src/schema/registry.py`, then run `python -m src.main validate-schema --fix`
5. **To rename a column:** Add the new column to registry, add a migration note in the column description, run `validate-schema --fix`. NEVER rename in-place.
6. **Before any PR that touches database tables:** Run `python -m src.main validate-schema` and include the output in the PR description
7. **CI enforcement:** `test_no_create_table_in_source` and `test_no_alter_table_in_source` run on every PR — they fail if DDL appears outside `src/schema/`

### Schema commands
```bash
python -m src.main validate-schema          # Check schema drift
python -m src.main validate-schema --fix    # Auto-fix missing tables/columns
python scripts/render_migrate.py            # Sync Postgres schema from registry
```

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
