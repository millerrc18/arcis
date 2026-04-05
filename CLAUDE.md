# CLAUDE.md — Arcis

## Governance

All project rules, architecture, data sources, and constraints are in **MASTER.md** — read it before making changes.

## Key Rules

- **Never commit secrets** — `.env`, `config/settings.local.yaml`, and `.mcp.json` are gitignored for a reason
- **Training data quality is #1** — never sacrifice quality for speed
- **Risk governor is sacred** — never bypass or weaken risk checks without explicit approval
- **Test count must not drop** — CI enforces a minimum of 1344 tests
- **Mock all external APIs in tests** — no network calls from pytest (Alpaca, Finnhub, yfinance, FRED, Ollama)
- **Schema registry is the single source of truth** — all 49 tables are defined in `src/schema/registry.py`. See "Database Schema Rules" below
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

## Startup / Restart Sequence

```bash
git pull origin main
python -m src.main startup                    # Validates everything, then launches watch loop
```

The `startup` command runs tiered validation (config, schema, environment, connectivity, services), auto-fixes schema drift, sends a Telegram notification with the results, and launches the watch loop with `--overnight` and `--email-mode digest` defaults.

**Flags:**
- `--check-only` — validate without launching the watch loop
- `--force` — bypass critical failures and launch anyway
- `--no-overnight` — disable overnight schedule
- `--email-mode silent|full_stream|daily_summary|digest` — override default digest mode

**Exit codes:** 0 = clean, 1 = critical blocked, 2 = check-only with warnings.

The watch loop uses a **PID lockfile** (`data/watch.lock`) to prevent duplicate instances. The `startup` command checks for this before running validation. If you see `Another watch loop is already running (PID ...)`, kill the existing process:

```bash
# Check what's running
powershell -Command "Get-CimInstance Win32_Process -Filter \"name='python.exe' and CommandLine like '%watch%'\" | Select-Object ProcessId, CreationDate | Format-List"

# Kill a stuck/duplicate watch loop
taskkill /PID <pid> /F /T

# Remove stale lockfile (only if no watch process is running)
rm data/watch.lock
```

### Postgres sync (after schema changes)
```bash
# Extract DATABASE_URL from config and run migrate:
DATABASE_URL=$(python -c "import yaml; cfg=yaml.safe_load(open('config/settings.local.yaml')); print(cfg['render']['database_url'])") python scripts/render_migrate.py

# Or set manually:
DATABASE_URL="<render-postgres-url>" python scripts/render_migrate.py
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

## Data Collection Rules

- **Collectors must raise on missing config** — use `CollectorConfigError` from `src/data_collection/errors.py` when a required API key is absent. Never return a success dict with an `error` field silently.
- **Surface mass failures** — if >50% of items in a batch fail, raise `CollectorPartialFailureError`. Individual item glitches are expected; mass failures must be visible.
- **Stats queries must reference real columns** — `test_stats_queries_reference_valid_columns` in `test_schema.py` validates all `/data-collection-stats` queries against the schema registry. It will fail if you reference a column that doesn't exist.
- **Overnight schedule runs 7 days/week** — data collection, news ingestion, and enrichment run daily (including weekends). Only VRAM handoff and pre-market tasks are weekday-gated.
- **`_safe_run` returns bool** — done-flags must be conditional: `if self._safe_run(...): self._done = True`. Never set a done-flag unconditionally after `_safe_run`.
- **Backoff is per-task** — the `_backoff` dict in `WatchLoop` keys by task name. A failure in one task never delays an unrelated task.

## Architecture Quick Ref

- **Backend**: Python 3.12, FastAPI, SQLite (raw sqlite3, no ORM)
- **Frontend**: React 19, Tailwind 4, Vite 8, TanStack Query
- **Deployment**: Render (static frontend + Python API)
- **Trading**: Alpaca paper + IB/Alpaca live via broker abstraction (`src/trading/`)
  - IB Gateway required for live IB trades (port 4002=paper, 4001=live)
- **LLM**: Ollama local (halcyon-v1, Qwen3 8B fine-tuned)
- **Config**: YAML (`config/settings.*.yaml`) + `.env` for secrets
