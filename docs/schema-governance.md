# Schema Governance

How the Halcyon Lab database schema is defined, enforced, and migrated.

---

## Why the registry exists

On March 31 and April 1, 2026, the project lost roughly 12 hours to bugs caused by a single root problem: **no single source of truth for the database schema.** Six or more files independently defined the same tables with subtly different column names, types, and indexes. When one file changed, the others did not.

### The bugs

| Bug | Root cause | Hours |
|---|---|---|
| `regime_label` vs `market_regime` -- 503 on 3 API endpoints | `trades.py` used wrong column name for recommendations table | 1 |
| `estimated_cost` vs `cost_dollars` -- API costs showed $0 | `watch.py` and `versioning.py` created `api_costs` with different column names | 0.5 |
| 7 missing Postgres tables -- sync errors every cycle | Sync config referenced tables that `render_migrate.py` didn't create | 2 |
| `actual_exit_time` NULL -- closed trades invisible | `reconcile.py` bypassed `close_shadow_trade()`, used raw SQL missing a column | 3 |
| `activity_log.level` missing -- sync errors | ALTER TABLE in `render_migrate.py` never applied | 0.5 |
| `signal_price` missing -- shadow_trades won't sync | ALTER TABLE exists but Postgres didn't have it | 1 |
| Database corruption -- total data loss | OneDrive + SQLite WAL conflict ([Issue #181](https://github.com/millerrc18/halcyon-lab/issues/181)) | 4 |

After recovery, three more bugs were discovered that the registry would have prevented outright:

- **Issue #184** -- 11 SQLite tables missing time columns after recovery from Postgres backup
- **Issue #185** -- Postgres duplicate key violations because recovery pulled data FROM Postgres and sync tried to INSERT the same rows back
- **Issue #186** -- `traffic_light_state.last_transition_at` missing in Postgres because `render_migrate.py` had not been run

Full bug table: [`docs/sprints/sprint-schema-registry.md`](sprints/sprint-schema-registry.md)

### Where tables were defined before (the problem)

```
src/journal/store.py          -> shadow_trades, recommendations (initialize_database)
src/scheduler/watch.py        -> api_costs, training_examples, research_papers (startup)
src/training/versioning.py    -> api_costs, audit_reports, metric_snapshots (DIFFERENT schema)
src/data_collection/*.py      -> Each collector created its own table
scripts/render_migrate.py     -> Postgres DDL (CREATE TABLE + ALTER TABLE) -- manually maintained
src/sync/render_sync.py       -> SYNC_TABLES config dict -- manually maintained
scripts/create_missing_tables.py -> Yet another place tables were created
```

Six or more files defining the same tables independently. When one changed, the others didn't.

---

## Architecture

### Core principle

```
ONE file defines every table, every column, every type, every index.
Everything else READS from this file. Nothing else creates tables.
```

### The registry: `src/schema/registry.py`

This is the single source of truth. It defines 46 tables with 552 columns, 32 indexes, and 3 foreign key relationships using four dataclass types:

| Dataclass | Purpose |
|---|---|
| `ColumnDef` | Column name, type (TEXT/REAL/INTEGER/BLOB), nullable, default, description |
| `IndexDef` | Index name, column list, unique flag |
| `ForeignKeyDef` | Column, referenced table, referenced column |
| `TableDef` | Table name, description, columns, primary key, indexes, foreign keys, sync config |

Each `TableDef` also carries sync metadata:

| Field | Purpose |
|---|---|
| `sync_to_postgres` | Whether this table syncs to Render Postgres (40 of 46 do) |
| `sync_mode` | `incremental` (31), `full` (3), or `latest_only` (6) |
| `sync_time_column` | Column used for incremental/latest_only sync cursors |
| `sync_pk` | Primary key used for upserts (defaults to `primary_key`) |

Tables are organized into groups:

| Group | Count | Examples |
|---|---|---|
| Trading Core | 3 | `recommendations`, `shadow_trades`, `validation_results` |
| Training Pipeline | 8 | `model_versions`, `training_examples`, `api_costs`, `canary_evaluations` |
| Council | 6 | `council_sessions`, `council_votes`, `council_parameter_log` |
| Data Collection | 12 | `edgar_filings`, `options_chains`, `macro_snapshots`, `vix_term_structure` |
| Research | 3 | `research_papers`, `research_digests`, `research_docs` |
| Signals | 2 | `setup_signals`, `traffic_light_state` |
| Evaluation & Metrics | 4 | `scan_metrics`, `build_score_history`, `quality_drift_metrics` |
| Infrastructure | 6 | `activity_log`, `log_entries`, `sync_state`, `pending_commands` |
| User Data | 1 | `user_notes` |
| Trading Internals | 1 | `bracket_health` |

### How it's consumed

```
src/schema/registry.py            <-- THE source of truth (46 TableDefs)
    |
    |-- src/schema/sqlite.py      <-- CREATE TABLE + ALTER TABLE for SQLite
    |-- src/schema/postgres.py    <-- CREATE TABLE + ALTER TABLE for Postgres (PL/pgSQL)
    |-- src/schema/sync_config.py <-- Generates SYNC_TABLES dict for render_sync.py
    |-- src/schema/validator.py   <-- Compares live DB against registry
    |
    |-- src/scheduler/watch.py    <-- Calls create_all_tables + ensure_columns at startup
    |-- src/cli/commands.py       <-- validate-schema CLI command
    |-- tests/test_schema.py      <-- CI guardrail tests
```

### What each consumer does

**`src/schema/sqlite.py`** -- Generates `CREATE TABLE IF NOT EXISTS` and `ALTER TABLE ADD COLUMN` statements from `TableDef` objects. Two entry points:

- `create_all_tables(db_path)` -- Creates all 46 tables. Idempotent.
- `ensure_columns(db_path)` -- Scans every table for missing columns and adds them via ALTER TABLE. Returns list of columns added. Handles race conditions (duplicate column errors).

**`src/schema/postgres.py`** -- Same as SQLite but for Postgres. Maps SQLite types to Postgres types (INTEGER -> SERIAL for auto-increment PKs, BLOB -> BYTEA). Uses PL/pgSQL `DO $$ BEGIN ... EXCEPTION WHEN duplicate_column THEN NULL; END $$` wrappers for idempotent ALTER TABLE.

- `create_all_tables(database_url)` -- Creates tables where `sync_to_postgres=True`.
- `ensure_columns(database_url)` -- Adds missing columns using `information_schema.columns`.

**`src/schema/sync_config.py`** -- Generates the `SYNC_TABLES` dictionary that `render_sync.py` uses to decide which tables to sync, what mode to use, what the primary key is, and what time column drives incremental syncs.

**`src/schema/validator.py`** -- Three functions:

- `validate_sqlite(db_path)` -- Compares live SQLite tables/columns against registry. Returns `SchemaIssue` objects for missing tables and missing columns.
- `validate_codebase()` -- Scans all `.py` files under `src/` (excluding `src/schema/`) for raw `CREATE TABLE` statements. Returns codebase violation issues. Respects `config/known_schema_violations.json` for temporary exemptions.
- `fix_issues(issues, db_path)` -- Auto-fixes missing tables and columns by calling `create_all_tables` and `ensure_columns`.

---

## How to add a new table

### Step 1: Define the table in the registry

Edit `src/schema/registry.py`. Add a `_register(TableDef(...))` call in the appropriate section:

```python
_register(TableDef(
    name="my_new_table",
    description="What this table stores and why",
    columns=[
        ColumnDef("id", "TEXT", nullable=False),
        ColumnDef("created_at", "TEXT", nullable=False),
        ColumnDef("ticker", "TEXT", nullable=False),
        ColumnDef("value", "REAL"),
        ColumnDef("notes", "TEXT"),
    ],
    primary_key="id",
    indexes=[
        IndexDef("idx_my_new_table_ticker", ["ticker"]),
        IndexDef("idx_my_new_table_created", ["created_at"]),
    ],
    # Sync configuration
    sync_to_postgres=True,           # Set False for local-only tables
    sync_mode="incremental",         # incremental, full, or latest_only
    sync_time_column="created_at",   # Column for incremental sync cursor
    sync_pk="id",                    # PK for upserts (defaults to primary_key)
))
```

### Step 2: Validate and apply

```bash
python -m src.main validate-schema --fix
```

This creates the table in SQLite and reports any issues.

### Step 3: Update Postgres (if synced)

```bash
python scripts/render_migrate.py
```

### Step 4: Update tests

Add the table name to `EXPECTED_TABLES` in `tests/test_schema.py` and update `EXPECTED_TABLE_COUNT` if needed.

### Step 5: Commit

Commit all changed files together: `registry.py`, any migration scripts, and `test_schema.py`.

---

## How to add a column to an existing table

### Step 1: Add the ColumnDef

Find the table's `_register(TableDef(...))` call in `src/schema/registry.py` and add the column to the `columns` list:

```python
# Existing columns...
ColumnDef("existing_column", "TEXT"),
# Add your new column here:
ColumnDef("new_column", "REAL", description="What this column stores"),
```

### Step 2: Validate and apply

```bash
python -m src.main validate-schema --fix
```

The `ensure_columns` function will detect the missing column in the live database and issue an `ALTER TABLE ADD COLUMN` statement automatically.

### Step 3: Update Postgres (if the table syncs)

```bash
python scripts/render_migrate.py
```

### What NOT to do

- Do NOT write `ALTER TABLE ADD COLUMN` in any file outside `src/schema/`.
- Do NOT add a column to `CREATE TABLE IF NOT EXISTS` in any file -- that statement is a no-op on existing tables and will NOT add the column.
- Do NOT manually edit the Postgres schema. Let the registry generate the migration.

---

## How validation works

### Startup check (watch.py)

Every time the watch loop starts, it calls:

```python
from src.schema.sqlite import create_all_tables, ensure_columns
create_all_tables(DB_PATH)
ensure_columns(DB_PATH)
```

This guarantees the local SQLite database matches the registry before any scans run. Missing tables are created. Missing columns are added. This is fully idempotent.

### CLI command

```bash
# Check for issues (read-only)
python -m src.main validate-schema

# Check and auto-fix
python -m src.main validate-schema --fix

# Also check Postgres
python -m src.main validate-schema --postgres
```

The CLI runs both `validate_sqlite` (database structure) and `validate_codebase` (source code scan for raw DDL).

### CI guardrail tests (`tests/test_schema.py`)

Four categories of tests run on every push:

**1. Registry completeness**
- `test_registry_has_all_tables` -- Registry defines at least 40 tables.
- `test_all_expected_tables_present` -- Every table in the `EXPECTED_TABLES` set exists in the registry.

**2. Registry consistency**
- `test_every_foreign_key_references_valid_table` -- Every `ForeignKeyDef` points to a table that exists.
- `test_every_sync_table_has_time_column` -- Tables with `incremental` or `latest_only` sync have a valid `sync_time_column` that matches an actual column.
- `test_every_table_has_primary_key_in_columns` -- The declared `primary_key` exists in the columns list.
- `test_no_duplicate_column_names` -- No table has two columns with the same name.

**3. Codebase guardrails**
- `test_no_create_table_in_source` -- Scans all `.py` files under `src/` (excluding `src/schema/` and `__pycache__`) for `CREATE TABLE` statements. Fails if any are found.
- `test_no_alter_table_in_source` -- Same scan for `ALTER TABLE` statements.

Both guardrail tests respect `config/known_schema_violations.json` for temporary exemptions during ongoing migrations. That file is currently empty (all violations cleared).

---

## What happens when rules are violated

The schema registry has three enforcement layers: edit-time, test-time, and runtime.

### Edit-time: hookify blocks the edit

The hookify rule at `.claude/hookify.block-schema-drift.local.md` fires when any AI agent (Claude Code) attempts to write `CREATE TABLE` or `ALTER TABLE ... ADD COLUMN` in a `.py` file outside `src/schema/`. The agent sees:

> **Schema registry violation detected.**
> You are adding `CREATE TABLE` or `ALTER TABLE` to a Python file outside of `src/schema/`.

The edit is blocked before it reaches the filesystem. The agent is instructed to add the table/column to the registry instead.

### Test-time: CI tests fail

If a `CREATE TABLE` or `ALTER TABLE` somehow makes it past the hookify rule:

- `test_no_create_table_in_source` fails with the file path and line number.
- `test_no_alter_table_in_source` fails with the file path and line number.
- The failure message directs the developer to `src/schema/registry.py`.

If a table is added to the registry but not to `EXPECTED_TABLES` in the test file:
- `test_registry_has_all_tables` may fail if the count drops.
- Consistency tests catch broken foreign keys, missing sync columns, and other structural errors.

### Runtime: validator catches drift

If the database gets out of sync with the registry (e.g., manual SQLite edits, partial recovery):

- `validate-schema` CLI reports every missing table and column.
- `validate-schema --fix` auto-creates missing tables and adds missing columns.
- The watch loop startup check (`create_all_tables` + `ensure_columns`) silently fixes drift on every restart.

---

## Migration history

### Before the registry (pre-April 1, 2026)

Tables were created in 28+ locations across the codebase. Each file used its own `CREATE TABLE IF NOT EXISTS` statement. The typical pattern:

```python
# In src/journal/store.py
CREATE_SHADOW_TRADES = """
CREATE TABLE IF NOT EXISTS shadow_trades (
    trade_id TEXT PRIMARY KEY,
    ticker TEXT NOT NULL,
    ...40 more columns defined here...
)"""

# In src/training/versioning.py (DIFFERENT column list)
CREATE_API_COSTS = """
CREATE TABLE IF NOT EXISTS api_costs (
    cost_id TEXT PRIMARY KEY,
    estimated_cost REAL NOT NULL,  -- <-- called "cost_dollars" elsewhere
    ...
)"""
```

When a developer added a column to one file, the other files defining the same table were not updated. `CREATE TABLE IF NOT EXISTS` is a no-op on existing tables -- it does not add missing columns. This meant columns existed in code but not in the actual database, causing silent failures, NULL values, and sync errors.

### The migration (April 1, 2026)

The schema registry was built in the `fix/schema-drift-training-tables` branch across multiple sessions. The sprint plan is documented in `docs/sprints/sprint-schema-registry.md`.

Key steps:

1. **Audit** -- Every `CREATE TABLE` in the codebase was found and catalogued.
2. **Registry creation** -- All 46 tables consolidated into `src/schema/registry.py` with `TableDef` dataclasses.
3. **Consumer modules** -- `sqlite.py`, `postgres.py`, `sync_config.py`, and `validator.py` built to read from the registry.
4. **Source cleanup** -- All `CREATE TABLE` and `ALTER TABLE` statements removed from non-schema files.
5. **Guardrail tests** -- `test_no_create_table_in_source` and `test_no_alter_table_in_source` added.
6. **Hookify rule** -- Edit-time block added for AI agents.
7. **Known violations file** -- `config/known_schema_violations.json` created for temporary exemptions during the transition (now empty).

### Current state

- `config/known_schema_violations.json` has zero exemptions -- all source files are clean.
- All 46 tables are defined exclusively in the registry.
- Every startup verifies the database matches the registry.
- CI blocks any attempt to reintroduce inline DDL.

---

## Quick reference

| Action | Command |
|---|---|
| Add a table | Edit `src/schema/registry.py`, run `validate-schema --fix` |
| Add a column | Edit `src/schema/registry.py`, run `validate-schema --fix` |
| Check schema health | `python -m src.main validate-schema` |
| Auto-fix drift | `python -m src.main validate-schema --fix` |
| Update Postgres | `python scripts/render_migrate.py` |
| Run guardrail tests | `python -m pytest tests/test_schema.py -v` |
| View all tables | `python -c "from src.schema.registry import TABLES; print(sorted(TABLES.keys()))"` |

## Key files

| File | Role |
|---|---|
| `src/schema/registry.py` | Single source of truth -- all 46 table definitions |
| `src/schema/sqlite.py` | SQLite DDL generation and column migration |
| `src/schema/postgres.py` | Postgres DDL generation with PL/pgSQL idempotent wrappers |
| `src/schema/sync_config.py` | Generates SYNC_TABLES config for render_sync.py |
| `src/schema/validator.py` | Compares live DB against registry, scans codebase for violations |
| `tests/test_schema.py` | CI guardrail tests (completeness, consistency, no raw DDL) |
| `config/known_schema_violations.json` | Temporary exemptions for files with legacy DDL (currently empty) |
| `.claude/hookify.block-schema-drift.local.md` | Hookify rule blocking AI agents from writing DDL outside schema/ |
