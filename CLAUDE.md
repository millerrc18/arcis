# CLAUDE.md — Arcis

## Governance

All project rules, architecture, data sources, and constraints are in **MASTER.md** — read it before making changes.

## Key Rules

- **Never commit secrets** — `.env`, `config/settings.local.yaml`, and `.mcp.json` are gitignored for a reason
- **Training data quality is #1** — never sacrifice quality for speed
- **Risk governor is sacred** — never bypass or weaken risk checks without explicit approval
- **Test count must not drop** — CI enforces a minimum of 3651 tests (post-PR-690 I5 sweep baseline as of 2026-04-26; +271 net from 3380 Cohort-2+3A floor across Track 1.5 Pass 2 + Round 10 work + PR-690 I5 sprint_F engine fixture regen: B1/B2.A/B2.B/B2.C/B3/B4/B5/B6/B7/B8/B9/B10 instrumentation rounds + 8.A-8.F dashboard fixes + 5-KPI hero strip + Round-10 Fix-A/B/C/D zero-failures cleanup + PR-690 I5 fixture regen drops `--ignore`). Floor lineage: 3038 (pre-audit) → 3159 (Track 1) → 3238 (Cohort 1) → 3380 (Cohort 2 + 3A) → 3646 (Track 1.5 + Round 10, with `--ignore=test_sprint_F_engine.py`) → 3651 (PR-690 I5: dropped `--ignore` after engine fixture regen, +5 tests). **Zero failures, zero errors at this baseline** (full sweep: `python -m pytest tests/ -q --timeout=60` — no longer needs `--ignore` after I5 fixture regen). Bump this number in CLAUDE.md whenever the sweep grows past the previous baseline.
- **Mock all external APIs in tests** — no network calls from pytest (Alpaca, Finnhub, yfinance, FRED, Ollama)
- **Schema registry is the single source of truth** — all 68 tables are defined in `src/schema/registry.py` (authoritative count: `python -c "from src.schema.registry import TABLES; print(len(TABLES))"`). See "Database Schema Rules" below
- **Test baseline before changes** — run `python -m pytest tests/ -q` at the start of any coding session and note the pass count. After changes, the pass count must not decrease and the failure count must not increase. Never dismiss test failures as "pre-existing" without investigating

## Repo Layout (local dev)

The runtime data lives **outside** the git repo. This is intentional, not accidental.

- `C:\arcis\halcyon-lab\` — git repo. Must be cwd when running CLI (`python -m src.main ...`)
- `C:\arcis\halcyon-lab\.env` — sets `ARCIS_DB_PATH=C:/arcis/data/ai_research_desk.sqlite3` (canonical)
- `C:\arcis\data\ai_research_desk.sqlite3` — active SQLite DB (~1 GB). **DO NOT** create or write a SQLite file at the repo root or `halcyon-lab/data/`; those are stub locations and have been removed (#642). Code reads `src.config.DB_PATH` which respects the env override.
- `C:\arcis\logs\` — runtime logs (mirrored to Render-deployed instances)
- `C:\arcis\data\reference\`, `data\simulation_cache\`, `data\watch.lock`, `data\watchdog.txt` — runtime artifacts

**Why state lives outside the repo:**
1. Keeps a 1 GB binary out of `git status` / `git diff` performance scans
2. Survives repo re-clone, branch switches, and worktree creation
3. Mirrors the Render production layout where the DB is a separate managed resource

**Mechanism:** `src/config/__init__.py:55-56` reads `ARCIS_DB_PATH` from env (loaded by `python-dotenv` via `.env`). Override per-process by exporting `ARCIS_DB_PATH=...` to point elsewhere (e.g. for testing against a snapshot DB).

**Common gotchas:**
- The watch loop must be started from a working directory where `.env` can be discovered. NSSM service startup uses the configured `AppDirectory`. If you change to a clone outside `C:\arcis\halcyon-lab\`, also set the env var explicitly.
- `scripts/statusline.py` uses the same `_resolve_data_root()` pattern — when adding new operator scripts that read runtime state, follow the same convention.
- Tests must NEVER write to the prod DB. The runtime guard in `src/utils/activity_logger.py` (#647) raises if a test opts in to writes without redirecting `db_path`.

## Database Schema Rules (MANDATORY)

All database tables are defined in `src/schema/registry.py` — the single source of truth.

1. **NEVER write `CREATE TABLE` in any file except `src/schema/registry.py`** — CI guardrail tests and hookify rules will block it
2. **NEVER write `ALTER TABLE` in any file except `src/schema/registry.py`** — column additions go through the registry
3. **To add a new table:** Add a `TableDef` to `TABLES` in `src/schema/registry.py`, then run `python -m src.main validate-schema --fix`
4. **To add a column:** Add a `ColumnDef` to the table's columns list in `src/schema/registry.py`, then run `python -m src.main validate-schema --fix`
5. **To rename a column:** Add the new column to registry, add a migration note in the column description, run `validate-schema --fix`. NEVER rename in-place.
6. **Before any PR that touches database tables:** Run `python -m src.main validate-schema` and include the output in the PR description
7. **CI enforcement:** `test_no_create_table_in_source` and `test_no_alter_table_in_source` run on every PR — they fail if DDL appears outside `src/schema/`
8. **After local schema changes:** Run `render_migrate.py` to sync Postgres. Include the output in the PR description alongside `validate-schema` output

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

# Simulation engine
python scripts/simulation_engine.py --dry-run                  # Print config only
python scripts/simulation_engine.py --regime strong_bull        # Single regime
python scripts/simulation_engine.py --monte-carlo 1000          # All 13 with MC
python scripts/simulation_engine.py --validate-traffic-light    # Check TL accuracy
python scripts/simulation_engine.py --clear-cache               # Delete cached data

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
- **`_safe_run` returns bool** — done-flags must be conditional: `if self._safe_run(...): self._done = True`. Never set a done-flag unconditionally after `_safe_run`. For inline try/except blocks, set the done-flag inside the `try`, never after the `except`.
- **Backoff is per-task** — the `_backoff` dict in `WatchLoop` keys by task name. A failure in one task never delays an unrelated task.

## Database Access Rules

- **Never open `data/ai_research_desk.sqlite3` in an external tool (MS Access, DBeaver, DB Browser for SQLite, etc.) while the watch loop is running.** External tools hold Windows file locks for indefinite durations while you're browsing; every concurrent writer in Python then hits `database is locked` until you close the external tool. Even after closing, locks can persist ~60s until Windows releases the handle. 2026-04-19: 118 lock errors in a single session traced to the operator having the DB open in MS Access.
- **If you must inspect data live, use `sqlite3` from the command line with read-only mode (`sqlite3 -readonly`) or a Python REPL opening with `sqlite3.connect('file:.../ai_research_desk.sqlite3?mode=ro', uri=True)`.**
- **All Python SQLite connections should use `src.utils.db.connect_db()`** — it applies `busy_timeout=30s` and `row_factory=sqlite3.Row` consistently. Don't write new `sqlite3.connect(...)` call sites without a timeout.

## Shadow Trading Rules

- **Status constants are canonical** — use `TERMINAL_STATUSES` and `ACTIVE_STATUSES` from `src/shadow_trading/models.py` in queries. Never hardcode `status != 'closed'`.
- **Verify orders after submission** — call `verify_order_accepted()` after `submit_order()`. Network errors don't mean Alpaca rejected the order.
- **Distinguish exception types** — `ConnectionError`/`TimeoutError` = network (order may exist); `APIError` = Alpaca response (check status_code); `Exception` = code bug.
- **Cancel before close** — before closing a position via reconciliation, call `cancel_orders_for_ticker()` to release `held_for_orders` locks.
- **Backfilled orphans get protective defaults** — `stop_price = entry * 0.95`, `target_1 = entry * 1.05`. Operator must still set real levels.
- **Cloud API requires API_SECRET** — `verify_auth` raises RuntimeError if API_SECRET is empty. Tests must mock/patch a non-empty secret.

## Architecture Quick Ref

- **Backend**: Python 3.12, FastAPI, SQLite (raw sqlite3, no ORM)
- **Frontend**: React 19, Tailwind 4, Vite 8, TanStack Query
- **Deployment**: Render (static frontend + Python API)
- **Trading**: Alpaca paper + IB/Alpaca live via broker abstraction (`src/trading/`)
  - IB Gateway required for live IB trades (port 4002=paper, 4001=live)
  - Shadow trade status lifecycle: `TERMINAL_STATUSES` / `ACTIVE_STATUSES` in `src/shadow_trading/models.py`
  - Order submission uses post-submit verification (`verify_order_accepted` in alpaca_adapter)
  - Alpaca SDK exception: `alpaca.common.exceptions.APIError` — the only public exception type
  - Local API binds to `127.0.0.1` only — not exposed to network
- **LLM**: Ollama local (halcyon-v1, Qwen3 8B fine-tuned)
- **Config**: YAML (`config/settings.*.yaml`) + `.env` for secrets

## Analytics & Methodology Modules (2026-04-27 audit)

Two flavors: **wired** (called from runtime code paths) vs **shelf** (implemented + tested but no production caller yet — drawn from manually when evaluating a strategy).

**Wired (live in runtime as of Mon 2026-04-27):**
- `src/analytics/canonical_sharpe.py` — single source of truth for Sharpe (raw / SPY-relative / rf-adjusted excess). All other Sharpe computations call this.
- `src/analytics/instrumentation_filter.py` — `is_fully_instrumented` predicate + Bailey-LdP MinTRL power assessment. Stage-1 baseline writer uses this; promotion gate uses MinTRL.
- `src/risk/governor.py` — `effective_position_cap()` returns `min()` across 4 namespaces (`risk.*`, `risk_governor.*`, `live_trading.*`, `bootcamp.*`). Raises `GovernorInputMissingError` on missing required keys (no silent permissive defaults).
- `src/scheduler/holidays.py` — uses `pandas_market_calendars` (NEW dep, see below) for NYSE calendar + half-day handling.

**Shelf (NOT wired into production promotion path — see `docs/methodology-toolkit.md`):**
- `src/methods/pbo.py` — Probability of Backtest Overfitting (Bailey-LdP 2014, CSCV)
- `src/methods/cpcv.py` — Combinatorial Purged Cross-Validation + anchored walk-forward
- `src/methods/block_bootstrap.py` — Stationary block bootstrap with Politis-White auto block-length
- `src/methods/mc_permutation.py` — Monte Carlo label-shuffle permutation test
- `src/methods/white_rc.py` — White's Reality Check (multi-strategy data-snooping test)
- `src/methods/psr.py` — PSR / DSR / MinTRL (re-exports canonical impls + adds the gate-facing surface)
- `src/methods/promotion_gate.py` — ≥4-of-5 voting gate orchestrating the 5 methods
- `src/methods/factor_alpha_core.py` — Fama-French 3+momentum regression (Stage-3 diagnostic)
- `src/allocation/risk_parity.py` — Inverse-vol allocator (T2.12b wiring deferred)
- `src/cost_model/calibration.py` — Live-fill slippage/cost calibration writer (writes JSON; no backtest reads it yet)
- `src/universe/pit.py` — Point-in-time SP100 + dividend haircut (24 callers still use survivorship-biased `get_sp100_universe()`)
- `src/features/pullback_logistic.py` — Logistic-regression feature extractors (T2.14b model + T2.14c adapter deferred)
- `src/data_ingestion/risk_free_rate.py` — FRED-backed rf-rate adapter (Stage-1 baseline still uses placeholder rf=0.0001 — wiring this in is the obvious follow-up)

Reading order when invoking the toolkit: `docs/methodology-toolkit.md` (decision tree + worked example), then the module's own docstring + tests.

## New Dependencies

- `pandas_market_calendars>=4.0,<6.0` — added by T2.11. Required for `src/scheduler/holidays.py`. Run `pip install -r requirements.txt` after pulling — older venvs will hit `ModuleNotFoundError` at scheduler startup.
