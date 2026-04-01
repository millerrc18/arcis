# Sprint: Schema Registry — Single Source of Truth for Database Schema

> **Priority:** CRITICAL — Every database bug this session traces to schema drift between 6+ files.
> **Goal:** One file defines every table. Everything else reads from it. Agents cannot create or modify tables outside the registry. Violations are caught at startup, in CI, and in PR review.
> **Estimated scope:** 2-3 CC sessions. Do NOT rush this. Get it right.

**CRITICAL: Read the ENTIRE sprint before writing any code. Run `python -m pytest tests/ -x -q` before AND after ALL changes.**

---

## Context: Why This Matters

Every database bug from the March 31 – April 1 session traces to one root cause: **no single source of truth for the database schema.**

### Bugs caused by schema drift (this session alone):

| Bug | Root cause | Hours to fix |
|---|---|---|
| `regime_label` vs `market_regime` — 503 on 3 endpoints | trades.py used wrong column name for recommendations table | 1 |
| `estimated_cost` vs `cost_dollars` — API costs showed $0 | watch.py and versioning.py created api_costs with different column names | 0.5 |
| 7 missing Postgres tables — sync errors every cycle | sync config referenced tables that render_migrate.py didn't create | 2 |
| `actual_exit_time` NULL — closed trades invisible | reconcile.py bypassed close_shadow_trade(), used raw SQL missing a column | 3 |
| `activity_log.level` missing — sync errors | ALTER TABLE in render_migrate.py never applied | 0.5 |
| `signal_price` missing — shadow_trades won't sync | ALTER TABLE exists but Postgres didn't have it | 1 |
| Database corruption — total data loss | OneDrive + SQLite WAL (separate issue, but recovery was complicated by schema confusion) | 4 |

**Total: ~12 hours of debugging caused by schema drift.** This sprint prevents all future instances.

### Where tables are currently created (the problem):

```
src/journal/store.py          → shadow_trades, recommendations (via initialize_database)
src/scheduler/watch.py        → api_costs, training_examples, research_papers (startup)
src/training/versioning.py    → api_costs, audit_reports, metric_snapshots (DIFFERENT schema)
src/data_collection/*.py      → Each collector creates its own table
scripts/render_migrate.py     → Postgres DDL (CREATE TABLE + ALTER TABLE) — manually maintained
src/sync/render_sync.py       → SYNC_TABLES config dict — manually maintained
scripts/create_missing_tables.py → Yet another place tables are created
```

**Six or more files define the same tables independently. When one changes, the others don't.**

---

## Architecture: The Schema Registry

### Core Principle
```
ONE file defines every table, every column, every type, every index.
Everything else READS from this file. Nothing else creates tables.
```

### File: `src/schema/registry.py`

This is the single source of truth. It defines:
1. Every table name
2. Every column with its type (TEXT, REAL, INTEGER)
3. Primary keys and unique constraints
4. Indexes
5. Foreign key relationships
6. Which tables sync to Render Postgres
7. Which columns are required vs optional
8. Sync mode (incremental, full, latest_only)
9. Time column for incremental sync
10. Human-readable description of each table and column

### How it's consumed:

```
src/schema/registry.py          ← THE source of truth
    │
    ├── src/schema/sqlite.py     ← Generates CREATE TABLE for SQLite
    ├── src/schema/postgres.py   ← Generates CREATE TABLE for Postgres
    ├── src/schema/validator.py  ← Compares live DB against registry
    ├── src/schema/sync_config.py ← Generates SYNC_TABLES config
    │
    ├── src/journal/store.py     ← initialize_database() reads from registry
    ├── scripts/render_migrate.py ← Reads from registry (no more manual DDL)
    ├── src/sync/render_sync.py  ← SYNC_TABLES generated from registry
    │
    ├── tests/test_schema.py     ← Validates registry is consistent
    └── .claude/schema-rules.md  ← Agent instructions referencing registry
```

---

## Task 1: Define the Schema Registry

**File:** `src/schema/__init__.py` (empty)
**File:** `src/schema/registry.py`

Define every table using a structured format. Example:

```python
"""Schema Registry — Single source of truth for all database tables.

Every table, column, index, and foreign key is defined here.
No other file in the codebase should contain CREATE TABLE statements.
All table creation, migration, and validation reads from this registry.

To add a new table:
    1. Add the TableDef to TABLES below
    2. Run: python -m src.schema.validate --fix
    3. Run: python scripts/render_migrate.py
    4. Commit all three: registry.py + any generated migrations

To add a column to an existing table:
    1. Add the ColumnDef to the table's columns list
    2. Run: python -m src.schema.validate --fix
    3. Run: python scripts/render_migrate.py
    4. Commit all three

NEVER create tables via raw SQL in any other file.
NEVER add columns via ALTER TABLE in any other file.
"""

from dataclasses import dataclass, field


@dataclass
class ColumnDef:
    name: str
    type: str  # TEXT, REAL, INTEGER, BLOB
    nullable: bool = True
    default: str | None = None
    description: str = ""


@dataclass
class IndexDef:
    name: str
    columns: list[str]
    unique: bool = False


@dataclass
class ForeignKeyDef:
    column: str
    references_table: str
    references_column: str


@dataclass
class TableDef:
    name: str
    description: str
    columns: list[ColumnDef]
    primary_key: str | list[str]  # Column name(s)
    indexes: list[IndexDef] = field(default_factory=list)
    foreign_keys: list[ForeignKeyDef] = field(default_factory=list)
    sync_to_postgres: bool = True
    sync_mode: str = "incremental"  # incremental, full, latest_only
    sync_time_column: str | None = "created_at"  # Column used for incremental sync
    sync_pk: str | None = None  # PK used for upsert (defaults to primary_key)


# ═══════════════════════════════════════════════════════════════════
# TABLE DEFINITIONS — This is the ONLY place tables are defined.
# ═══════════════════════════════════════════════════════════════════

TABLES: dict[str, TableDef] = {}


def _register(table: TableDef) -> None:
    """Register a table definition."""
    TABLES[table.name] = table


# ── Trading Core ──────────────────────────────────────────────────

_register(TableDef(
    name="shadow_trades",
    description="Paper and live trade lifecycle tracking",
    primary_key="trade_id",
    sync_mode="incremental",
    sync_time_column="updated_at",
    sync_pk="trade_id",
    columns=[
        ColumnDef("trade_id", "TEXT", nullable=False, description="UUID primary key"),
        ColumnDef("ticker", "TEXT", nullable=False),
        ColumnDef("status", "TEXT", nullable=False, description="open, closed, exit_pending, exit_failed"),
        ColumnDef("source", "TEXT", description="paper or live"),
        ColumnDef("direction", "TEXT", default="long"),
        ColumnDef("entry_price", "REAL"),
        ColumnDef("actual_entry_price", "REAL"),
        ColumnDef("stop_price", "REAL"),
        ColumnDef("target_1", "REAL"),
        ColumnDef("target_2", "REAL"),
        ColumnDef("planned_shares", "INTEGER"),
        ColumnDef("actual_shares", "INTEGER"),
        ColumnDef("actual_exit_price", "REAL"),
        ColumnDef("actual_exit_time", "TEXT", description="ISO timestamp — MUST be set on close"),
        ColumnDef("exit_reason", "TEXT"),
        ColumnDef("pnl_dollars", "REAL"),
        ColumnDef("pnl_pct", "REAL"),
        ColumnDef("duration_days", "INTEGER"),
        ColumnDef("max_favorable_excursion", "REAL"),
        ColumnDef("max_adverse_excursion", "REAL"),
        ColumnDef("recommendation_id", "TEXT"),
        ColumnDef("alpaca_order_id", "TEXT"),
        ColumnDef("strategy_type", "TEXT", default="pullback"),
        ColumnDef("signal_price", "REAL"),
        ColumnDef("fill_price", "REAL"),
        ColumnDef("implementation_shortfall_bps", "REAL"),
        ColumnDef("order_type", "TEXT"),
        ColumnDef("created_at", "TEXT"),
        ColumnDef("updated_at", "TEXT"),
    ],
    indexes=[
        IndexDef("idx_shadow_trades_status", ["status"]),
        IndexDef("idx_shadow_trades_ticker", ["ticker"]),
        IndexDef("idx_shadow_trades_created", ["created_at"]),
    ],
    foreign_keys=[
        ForeignKeyDef("recommendation_id", "recommendations", "recommendation_id"),
    ],
))

# Continue for ALL 40+ tables...
# Each table gets the same level of detail.
# USE the existing code as reference — read every CREATE TABLE in the codebase
# and consolidate here.
```

**IMPORTANT: You MUST define ALL tables.** Read every file in the codebase that contains `CREATE TABLE` and consolidate into this registry. Use this command to find them all:

```bash
grep -rn "CREATE TABLE" src/ scripts/ --include="*.py" | grep -v __pycache__ | grep -v test
```

Cross-reference with `SYNC_TABLES` in `render_sync.py` and `MIGRATIONS` in `render_migrate.py` to ensure nothing is missed.

**For column names that conflict** (e.g., `cost_dollars` vs `estimated_cost`), choose ONE canonical name and note the legacy name in the column description. The validator (Task 3) will catch any code still using the old name.

---

## Task 2: Schema-Driven Table Creation

### 2A: SQLite Table Creator

**File:** `src/schema/sqlite.py`

```python
def create_all_tables(db_path: str) -> None:
    """Create all tables defined in the registry. Idempotent."""

def ensure_columns(db_path: str) -> list[str]:
    """Add any columns in registry that are missing from SQLite.
    Returns list of columns added."""

def generate_create_sql(table: TableDef) -> str:
    """Generate CREATE TABLE IF NOT EXISTS SQL for SQLite."""
```

### 2B: Postgres Table Creator

**File:** `src/schema/postgres.py`

```python
def create_all_tables(database_url: str) -> None:
    """Create all Postgres tables from registry. Idempotent."""

def ensure_columns(database_url: str) -> list[str]:
    """Add missing columns to Postgres (idempotent DO $$ BEGIN ... EXCEPTION)."""

def generate_create_sql(table: TableDef) -> str:
    """Generate CREATE TABLE IF NOT EXISTS SQL for Postgres.
    Maps TEXT→TEXT, REAL→REAL, INTEGER→INTEGER.
    Uses SERIAL PRIMARY KEY for auto-increment integer PKs."""
```

### 2C: Sync Config Generator

**File:** `src/schema/sync_config.py`

```python
def generate_sync_tables() -> dict:
    """Generate SYNC_TABLES config from registry.
    Only includes tables where sync_to_postgres=True."""
```

### 2D: Rewire initialize_database()

**File:** `src/journal/store.py`

Replace ALL manual CREATE TABLE and ALTER TABLE statements with:

```python
from src.schema.sqlite import create_all_tables, ensure_columns

def initialize_database(db_path="ai_research_desk.sqlite3"):
    create_all_tables(db_path)
    added = ensure_columns(db_path)
    if added:
        logger.info("[DB] Added %d columns: %s", len(added), added)
    # Keep the backfill migration for actual_exit_time (temporary)
```

### 2E: Rewire render_migrate.py

**File:** `scripts/render_migrate.py`

Replace the entire 700-line MIGRATIONS list with:

```python
from src.schema.postgres import create_all_tables, ensure_columns

def main():
    create_all_tables(DATABASE_URL)
    added = ensure_columns(DATABASE_URL)
    print(f"Schema sync complete. {len(added)} columns added.")
```

### 2F: Rewire render_sync.py

**File:** `src/sync/render_sync.py`

Replace the hardcoded SYNC_TABLES dict with:

```python
from src.schema.sync_config import generate_sync_tables
SYNC_TABLES = generate_sync_tables()
```

### 2G: Remove all other CREATE TABLE statements

Search the entire codebase and remove/replace every CREATE TABLE outside the registry:

```bash
grep -rn "CREATE TABLE" src/ scripts/ --include="*.py" | grep -v __pycache__ | grep -v test | grep -v schema/
```

Every hit must either be removed or replaced with a call to the registry. **Document each removal** — which file, which table, what it was replaced with.

---

## Task 3: Schema Validator

**File:** `src/schema/validator.py`

Validates that live databases match the registry. Runs on startup and on-demand.

```python
def validate_sqlite(db_path: str) -> list[SchemaIssue]:
    """Compare local SQLite schema against registry.
    Returns list of issues: missing tables, missing columns,
    type mismatches, extra columns not in registry."""

def validate_postgres(database_url: str) -> list[SchemaIssue]:
    """Compare Render Postgres schema against registry.
    Same checks as SQLite."""

def validate_sync_config() -> list[SchemaIssue]:
    """Verify every table with sync_to_postgres=True has a valid
    sync_time_column and sync_pk."""

def validate_codebase() -> list[SchemaIssue]:
    """Scan Python files for raw CREATE TABLE / ALTER TABLE statements
    outside of src/schema/. Flag as violations."""

def fix_issues(issues: list[SchemaIssue], db_path: str = None,
               database_url: str = None) -> list[str]:
    """Auto-fix: create missing tables, add missing columns.
    Returns list of actions taken."""
```

### CLI command:

```python
# In src/main.py
validate_schema_parser = subparsers.add_parser("validate-schema")
validate_schema_parser.add_argument("--fix", action="store_true")
validate_schema_parser.add_argument("--postgres", action="store_true")
```

### Startup integration:

In `watch.py` WatchLoop.run(), after initialize_database():

```python
from src.schema.validator import validate_sqlite
issues = validate_sqlite("ai_research_desk.sqlite3")
if issues:
    logger.warning("[SCHEMA] %d schema issues found: %s",
                   len(issues), [str(i) for i in issues[:5]])
    # Telegram alert
    from src.notifications.telegram import send_telegram, is_telegram_enabled
    if is_telegram_enabled():
        send_telegram(f"⚠️ Schema drift detected: {len(issues)} issues. Run validate-schema --fix")
```

---

## Task 4: Tests

**File:** `tests/test_schema.py`

### 4A: Registry completeness tests

```python
def test_all_sync_tables_in_registry():
    """Every table in the old SYNC_TABLES must be in TABLES."""

def test_all_create_tables_in_registry():
    """Scan codebase for CREATE TABLE — all must be in registry
    or in src/schema/."""

def test_no_raw_create_table_outside_schema():
    """No Python file outside src/schema/ and tests/ should contain
    CREATE TABLE. This is the guardrail test."""

def test_no_raw_alter_table_outside_schema():
    """No Python file outside src/schema/ should contain ALTER TABLE."""

def test_registry_column_names_consistent():
    """Verify no two tables define the same semantic column with
    different names (e.g., cost_dollars vs estimated_cost)."""

def test_every_foreign_key_references_valid_table():
    """Every ForeignKeyDef references a table that exists in TABLES."""

def test_every_sync_table_has_time_column():
    """Tables with sync_mode='incremental' must have sync_time_column
    that exists in their columns list."""
```

### 4B: Schema generation tests

```python
def test_sqlite_create_sql_is_valid():
    """Generated SQL parses without error in SQLite."""

def test_postgres_create_sql_is_valid():
    """Generated SQL is valid Postgres syntax (mock connection)."""

def test_ensure_columns_is_idempotent():
    """Running ensure_columns twice produces no errors and no duplicates."""
```

### 4C: Codebase guardrail tests (run in CI)

```python
def test_no_create_table_in_source():
    """Scan all .py files in src/ (except src/schema/) for
    'CREATE TABLE' — fail if found. This prevents schema drift."""
    import os
    violations = []
    for root, dirs, files in os.walk("src"):
        dirs[:] = [d for d in dirs if d not in ("__pycache__", "schema")]
        for f in files:
            if f.endswith(".py"):
                path = os.path.join(root, f)
                with open(path) as fh:
                    for i, line in enumerate(fh, 1):
                        if "CREATE TABLE" in line and "test" not in path:
                            violations.append(f"{path}:{i}")
    assert violations == [], f"CREATE TABLE found outside schema/: {violations}"

def test_no_alter_table_in_source():
    """Same for ALTER TABLE."""
    # Same pattern as above
```

---

## Task 5: Agent Guardrails

### 5A: Update CLAUDE.md

Add to the project root `CLAUDE.md`:

```markdown
## Database Schema Rules (MANDATORY)

1. **NEVER write CREATE TABLE in any file except `src/schema/registry.py`.**
2. **NEVER write ALTER TABLE in any file except `src/schema/registry.py`.**
3. **To add a new table:** Add a `TableDef` to `TABLES` in `src/schema/registry.py`, then run `python -m src.main validate-schema --fix`.
4. **To add a column:** Add a `ColumnDef` to the table's columns list in `src/schema/registry.py`, then run `python -m src.main validate-schema --fix`.
5. **To rename a column:** Add the new column to registry, add a migration note in the column description, run validate-schema --fix. NEVER rename in-place.
6. **Column name conflicts:** If two modules use different names for the same concept, the registry name wins. Update all references.
7. **Before any PR that touches database tables:** Run `python -m src.main validate-schema` and include the output in the PR description.
8. **CI will reject PRs that contain CREATE TABLE or ALTER TABLE outside of src/schema/.**
```

### 5B: Update AGENTS.md

Add a "Database Schema" section:

```markdown
## Database Schema Governance

**Source of truth:** `src/schema/registry.py`
**Table count:** 40+ (auto-counted from registry)
**Validation:** `python -m src.main validate-schema [--fix] [--postgres]`

### Rules for AI agents (Claude Code, Codex, etc.)
- You MUST NOT write CREATE TABLE or ALTER TABLE outside `src/schema/registry.py`
- You MUST add new tables/columns to the registry FIRST, then run validate-schema
- You MUST run `python -m src.main validate-schema` before submitting any PR that touches the database
- Tests will fail if CREATE TABLE appears outside the schema module (test_schema.py guardrail)
- The CI pipeline runs these tests on every PR

### Adding a new table (step by step)
1. Add `TableDef` to `TABLES` in `src/schema/registry.py`
2. Run `python -m src.main validate-schema --fix` — creates the table in SQLite
3. Run `python scripts/render_migrate.py` — creates the table in Postgres
4. Add sync config if needed (set `sync_to_postgres=True` in the TableDef)
5. Commit registry.py + any code that uses the new table

### Adding a column (step by step)
1. Add `ColumnDef` to the table's columns list in `src/schema/registry.py`
2. Run `python -m src.main validate-schema --fix` — adds column to SQLite
3. Run `python scripts/render_migrate.py` — adds column to Postgres (idempotent)
4. Commit registry.py + any code that uses the new column
```

### 5C: Add `.claude/hooks` schema check

If not already present, add a pre-commit style check to `.claude/settings.json`:

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Edit|Write",
        "command": "grep -l 'CREATE TABLE\\|ALTER TABLE' $FILE 2>/dev/null | grep -v schema/ | grep -v test | grep -v __pycache__",
        "failIf": "outputNotEmpty",
        "message": "❌ CREATE TABLE / ALTER TABLE detected outside src/schema/. Add to registry.py instead."
      }
    ]
  }
}
```

**Note:** Verify this hook syntax works with the existing hook configuration. If it conflicts, add it as a separate hook entry. The goal is to block CC from writing CREATE TABLE outside the schema module.

### 5D: CI guardrail test

The `test_no_create_table_in_source()` test in Task 4C runs in CI on every PR. If CC (or any agent) introduces a CREATE TABLE outside the schema module, CI fails and the PR cannot merge.

This is the automated enforcement layer — even if the agent ignores CLAUDE.md instructions, the test catches it.

---

## Task 6: Migration Path (handle the transition)

### 6A: Consolidate conflicting schemas

Where two modules defined the same table with different column names:

| Table | Conflict | Resolution |
|---|---|---|
| `api_costs` | `cost_dollars` (versioning.py) vs `estimated_cost` (watch.py) | Registry uses `cost_dollars`. Add migration to rename. |
| `recommendations` | `market_regime` (store.py) vs `regime_label` (some queries) | Registry uses `market_regime`. Already fixed. |

For each conflict:
1. Choose the canonical name (put in registry)
2. Add the old name as a column description note: `description="API cost in dollars. Legacy: was 'estimated_cost' in some modules."`
3. Search codebase for old name, update all references
4. Add a data migration to rename the column (or copy values if rename isn't safe)

### 6B: Known violations file

During the transition, some CREATE TABLE statements may need to remain temporarily (e.g., in test fixtures). Track these in `config/known_schema_violations.json`:

```json
{
  "allowed_create_table": [
    {"file": "tests/conftest.py", "reason": "Test fixture creates temp tables"},
    {"file": "scripts/recover_from_postgres.py", "reason": "Recovery tool creates tables from Postgres schema"}
  ]
}
```

The guardrail test reads this file and exempts listed files.

---

## Task 7: Comprehensive Documentation Update

### 7A: Update `docs/database-schema.md`

Rewrite to be generated FROM the registry:

```python
# scripts/generate_schema_docs.py
"""Generate docs/database-schema.md from the schema registry."""
from src.schema.registry import TABLES

def main():
    # Generate Mermaid ERD from TABLES
    # Generate table index with columns, types, descriptions
    # Write to docs/database-schema.md
```

### 7B: Update SYSTEM_STATE.md

- Add schema registry to "What's Deployed & Running"
- Update the Configuration section to reference the registry
- Note the guardrail tests in the CI section

### 7C: Update README.md

Add a note under Architecture:

```markdown
**Database schema** is governed by a central registry (`src/schema/registry.py`). 
All 40+ tables are defined once. SQLite and Postgres schemas are generated from 
this registry. CI rejects PRs that create tables outside the registry.
```

### 7D: Create `docs/schema-governance.md`

A standalone document explaining:
1. Why the registry exists (link to incident #181 and the schema drift bugs)
2. How to add tables and columns (step-by-step with examples)
3. How validation works (startup, CLI, CI)
4. What happens when an agent violates the rules (test failure, hook block)
5. The migration path from the old approach
6. How the registry feeds into SQLite creation, Postgres migration, and Render sync

---

## Acceptance Criteria

### Registry
- [ ] `src/schema/registry.py` defines ALL 40+ tables with columns, types, PKs, indexes, FKs
- [ ] Every table currently in `SYNC_TABLES`, `render_migrate.py`, and `initialize_database()` is in the registry
- [ ] No two tables have conflicting column names for the same concept

### Table Creation
- [ ] `initialize_database()` reads from registry (no manual CREATE TABLE)
- [ ] `render_migrate.py` reads from registry (no manual MIGRATIONS list)
- [ ] `render_sync.py` SYNC_TABLES generated from registry
- [ ] All individual collector CREATE TABLE statements removed

### Validation
- [ ] `python -m src.main validate-schema` runs and reports issues
- [ ] `--fix` flag auto-creates missing tables/columns
- [ ] `--postgres` flag validates Render Postgres
- [ ] Startup runs validation and alerts on drift

### Tests
- [ ] `test_no_create_table_in_source` — fails if CREATE TABLE found outside schema/
- [ ] `test_no_alter_table_in_source` — same for ALTER TABLE
- [ ] `test_all_sync_tables_in_registry` — every synced table is registered
- [ ] `test_registry_column_names_consistent` — no naming conflicts
- [ ] `test_every_foreign_key_references_valid_table`
- [ ] `test_ensure_columns_is_idempotent`
- [ ] All existing tests still pass (>= 1,245)

### Agent Guardrails
- [ ] CLAUDE.md updated with database schema rules
- [ ] AGENTS.md updated with schema governance section + step-by-step guides
- [ ] `.claude/hooks` or `.claude/settings.json` blocks CREATE TABLE outside schema/
- [ ] CI guardrail test runs on every PR

### Documentation
- [ ] `docs/schema-governance.md` created with full explanation
- [ ] `docs/database-schema.md` regenerated from registry
- [ ] SYSTEM_STATE.md updated
- [ ] README.md updated

### Zero regressions
- [ ] All Python tests pass (>= 1,245)
- [ ] `npm run build` succeeds
- [ ] `python scripts/render_migrate.py` runs clean
- [ ] Watch loop starts and validates schema without errors
- [ ] Render sync works for all 40 tables
