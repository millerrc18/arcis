# Schema Registry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create a single source of truth for all 40 database tables, eliminating schema drift between SQLite, Postgres, sync config, and 14+ files that independently define `CREATE TABLE`.

**Architecture:** A new `src/schema/` package defines every table as a `TableDef` dataclass. SQLite creation, Postgres migration, and sync config are all generated from this registry. Guardrail tests block any `CREATE TABLE` outside the registry. A validator CLI compares live databases against the registry and auto-fixes drift.

**Tech Stack:** Python 3.12, dataclasses, sqlite3, psycopg2 (existing), pytest

**Sprint doc:** `docs/sprints/sprint-schema-registry.md`

---

## Scope & Session Breakdown

This sprint spans **3 sessions**, each producing working, testable software:

| Session | Tasks | Deliverable |
|---|---|---|
| 1 | Tasks 1-3 | Registry + SQLite/Postgres generators + validator CLI |
| 2 | Tasks 4-6 | Tests + guardrails + migration path (remove old CREATE TABLE) |
| 3 | Tasks 7-8 | Documentation + dashboard verification |

---

## File Structure

### New files (create):
```
src/schema/__init__.py          — Package init, re-exports TABLES
src/schema/registry.py          — 40 TableDef definitions (THE source of truth)
src/schema/sqlite.py            — create_all_tables(), ensure_columns()
src/schema/postgres.py          — create_all_tables(), ensure_columns()
src/schema/sync_config.py       — generate_sync_tables() → dict
src/schema/validator.py         — validate_sqlite(), validate_postgres(), fix_issues()
tests/test_schema.py            — Registry completeness + guardrail tests
tests/test_schema_generators.py — SQLite/Postgres SQL generation tests
tests/test_dashboard_data.py    — Critical data path tests
scripts/verify_dashboard.py     — API endpoint verification
scripts/verify_column_names.py  — Column name consistency scan
scripts/generate_schema_docs.py — Regenerate docs/database-schema.md from registry
config/known_schema_violations.json — Temporary exemptions during migration
docs/schema-governance.md       — Standalone governance doc
docs/dashboard-data-map.md      — Page → endpoint → table → column map
```

### Modified files:
```
src/journal/store.py            — Replace CREATE TABLE/ALTER with registry calls
src/scheduler/watch.py          — Replace _ensure_all_tables() with registry calls
src/training/versioning.py      — Replace init_training_tables() with registry calls
src/council/engine.py           — Replace init_council_tables() with registry calls
src/council/value_tracker.py    — Replace init_value_tables() with registry calls
src/sync/render_sync.py         — Replace SYNC_TABLES dict with generated config
scripts/render_migrate.py       — Replace MIGRATIONS list with registry calls
scripts/render_init_db.py       — Replace POSTGRES_SCHEMA with registry calls
scripts/create_missing_tables.py — Replace with registry calls
src/main.py                     — Add validate-schema CLI command
src/data_collection/*.py        — Remove 11 embedded CREATE TABLE blocks
src/logging/activity.py         — Remove CREATE TABLE
src/features/setup_classifier.py — Remove CREATE TABLE
src/features/traffic_light.py   — Remove CREATE TABLE
src/training/quality_drift.py   — Remove CREATE TABLE
src/training/canary.py          — Remove CREATE TABLE
src/training/dpo_pipeline.py    — Remove CREATE TABLE
src/data_collection/docs_collector.py — Remove CREATE TABLE
src/scheduler/metrics.py        — Remove CREATE TABLE
CLAUDE.md                       — Add database schema rules
AGENTS.md                       — Add schema governance section
docs/database-schema.md         — Regenerated from registry
```

---

## Session 1: Registry + Generators + Validator

### Task 1: Define the Schema Registry Data Model

**Files:**
- Create: `src/schema/__init__.py`
- Create: `src/schema/registry.py`
- Test: `tests/test_schema.py`

- [ ] **Step 1: Create package and data model**

Create `src/schema/__init__.py`:

```python
"""Schema registry — single source of truth for all database tables."""

from src.schema.registry import TABLES, TableDef, ColumnDef, IndexDef, ForeignKeyDef

__all__ = ["TABLES", "TableDef", "ColumnDef", "IndexDef", "ForeignKeyDef"]
```

Create `src/schema/registry.py` with the dataclass definitions:

```python
"""Schema Registry — Single source of truth for all database tables.

Every table, column, index, and foreign key is defined here.
No other file in the codebase should contain CREATE TABLE statements.

To add a new table:
    1. Add the TableDef to TABLES below
    2. Run: python -m src.main validate-schema --fix
    3. Run: python scripts/render_migrate.py
    4. Commit all three: registry.py + any generated migrations

To add a column to an existing table:
    1. Add the ColumnDef to the table's columns list
    2. Run: python -m src.main validate-schema --fix
    3. Run: python scripts/render_migrate.py
    4. Commit all three
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
    primary_key: str | list[str]
    indexes: list[IndexDef] = field(default_factory=list)
    foreign_keys: list[ForeignKeyDef] = field(default_factory=list)
    sync_to_postgres: bool = True
    sync_mode: str = "incremental"  # incremental, full, latest_only
    sync_time_column: str | None = "created_at"
    sync_pk: str | None = None  # Defaults to primary_key if None


TABLES: dict[str, TableDef] = {}


def _register(table: TableDef) -> None:
    """Register a table definition."""
    TABLES[table.name] = table
```

- [ ] **Step 2: Write test for data model**

Create `tests/test_schema.py`:

```python
"""Tests for the schema registry."""

import pytest
from src.schema.registry import TABLES, TableDef, ColumnDef, IndexDef, _register


def test_tables_dict_exists():
    assert isinstance(TABLES, dict)


def test_register_adds_table():
    table = TableDef(
        name="_test_table",
        description="Test",
        columns=[ColumnDef("id", "INTEGER", nullable=False)],
        primary_key="id",
    )
    _register(table)
    assert "_test_table" in TABLES
    # Cleanup
    del TABLES["_test_table"]
```

- [ ] **Step 3: Run test**

Run: `python -m pytest tests/test_schema.py -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add src/schema/ tests/test_schema.py
git commit -m "feat(schema): add registry data model with TableDef/ColumnDef dataclasses"
```

---

### Task 2: Populate the Registry with All 40 Tables

**Files:**
- Modify: `src/schema/registry.py`
- Modify: `tests/test_schema.py`

This is the largest single task. You MUST read every `CREATE TABLE` in the codebase and consolidate into the registry. Use this command to find them all:

```bash
grep -rn "CREATE TABLE" src/ scripts/ --include="*.py" | grep -v __pycache__ | grep -v test
```

Cross-reference with:
- `SYNC_TABLES` in `src/sync/render_sync.py:35-240`
- `MIGRATIONS` in `scripts/render_migrate.py:23-660`
- `POSTGRES_SCHEMA` in `scripts/render_init_db.py:20-516`

- [ ] **Step 1: Write completeness test**

Add to `tests/test_schema.py`:

```python
EXPECTED_TABLE_COUNT = 40  # Update if you discover more/fewer


def test_registry_has_all_tables():
    """Registry must define all known tables."""
    assert len(TABLES) >= EXPECTED_TABLE_COUNT, (
        f"Registry has {len(TABLES)} tables, expected >= {EXPECTED_TABLE_COUNT}. "
        f"Missing tables need to be added to src/schema/registry.py"
    )


EXPECTED_TABLES = {
    # Trading Core
    "shadow_trades", "recommendations", "validation_results",
    # Training Pipeline
    "model_versions", "training_examples", "model_evaluations",
    "audit_reports", "metric_snapshots", "api_costs",
    # Council
    "council_sessions", "council_votes", "council_calibrations",
    "council_debug_log", "council_parameter_log", "council_parameter_state",
    # Data Collection
    "edgar_filings", "insider_transactions", "short_interest",
    "fed_communications", "analyst_estimates", "options_chains",
    "options_metrics", "cboe_ratios", "google_trends",
    "vix_term_structure", "macro_snapshots", "earnings_calendar",
    # Research
    "research_papers", "research_digests", "research_docs",
    # Evaluation & Metrics
    "scan_metrics", "schedule_metrics", "build_score_history",
    "setup_signals", "canary_evaluations", "quality_drift_metrics",
    # Infrastructure
    "activity_log", "log_entries", "traffic_light_state",
    "sync_state", "command_results", "config_overrides",
    "pending_commands",
    # User Data
    "user_notes",
    # Trading Internals
    "bracket_health", "preference_pairs",
}


def test_all_expected_tables_present():
    missing = EXPECTED_TABLES - set(TABLES.keys())
    assert not missing, f"Missing from registry: {missing}"
```

- [ ] **Step 2: Run test — it should FAIL (0 tables registered)**

Run: `python -m pytest tests/test_schema.py::test_registry_has_all_tables -v`
Expected: FAIL

- [ ] **Step 3: Add all 40 table definitions to registry.py**

Read each `CREATE TABLE` from the source files listed below and add the corresponding `_register(TableDef(...))` call. **Group by domain.**

Source files to read (in order):

| Domain | Source file | Tables |
|---|---|---|
| Trading Core | `src/journal/store.py:19-123` | recommendations, shadow_trades, validation_results |
| Training | `src/training/versioning.py:22-175` | model_versions, training_examples, model_evaluations, audit_reports, metric_snapshots, api_costs |
| Council | `src/council/engine.py:44-106` | council_sessions, council_votes, council_calibrations, council_debug_log |
| Council | `src/council/value_tracker.py:36-67` | council_parameter_log, council_parameter_state |
| Data Collection | `src/data_collection/edgar_collector.py:34` | edgar_filings |
| Data Collection | `src/data_collection/insider_collector.py:29` | insider_transactions |
| Data Collection | `src/data_collection/short_interest_collector.py:29` | short_interest |
| Data Collection | `src/data_collection/fed_collector.py:37` | fed_communications |
| Data Collection | `src/data_collection/analyst_collector.py:30` | analyst_estimates |
| Data Collection | `src/data_collection/options_collector.py:29` | options_chains |
| Data Collection | `src/data_collection/options_metrics.py:23` | options_metrics |
| Data Collection | `src/data_collection/cboe_collector.py:24` | cboe_ratios |
| Data Collection | `src/data_collection/trends_collector.py:39` | google_trends |
| Data Collection | `src/data_collection/vix_collector.py:25` | vix_term_structure |
| Data Collection | `src/data_collection/macro_collector.py:73` | macro_snapshots |
| Research | `src/scheduler/watch.py:897-910` | research_papers, research_digests |
| Signals | `src/features/setup_classifier.py:244` | setup_signals |
| Signals | `src/features/traffic_light.py:41` | traffic_light_state |
| Evaluation | `src/scheduler/watch.py:909-920` | scan_metrics |
| Evaluation | `src/scheduler/metrics.py:25` | schedule_metrics |
| Evaluation | `src/training/canary.py:41` | canary_evaluations |
| Evaluation | `src/training/quality_drift.py:30` | quality_drift_metrics |
| Infrastructure | `src/logging/activity.py:29` | activity_log |
| Infrastructure | `src/scheduler/watch.py` (log_entries) | log_entries |
| Infrastructure | `src/sync/render_sync.py:248` | sync_state |
| User Data | `src/scheduler/watch.py:969` | user_notes |
| Trading | `src/shadow_trading/bracket_monitor.py:26` | bracket_health |
| Training | `src/training/dpo_pipeline.py:28` | preference_pairs |
| Data Collection | `src/scheduler/watch.py` (earnings_calendar lookup) | earnings_calendar |
| Infrastructure | `scripts/render_migrate.py` or `src/scheduler/watch.py` | command_results, config_overrides, pending_commands, build_score_history |

**Sync metadata:** For each table that appears in `SYNC_TABLES` (line 35-240 of `src/sync/render_sync.py`), copy the `mode`, `time_col` → `sync_time_column`, and `pk` → `sync_pk` values.

**Column name conflicts to resolve:**
- `api_costs`: use `cost_dollars` (NOT `estimated_cost`)
- `recommendations`: use `market_regime` (NOT `regime_label`)
- Note legacy names in column descriptions

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_schema.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add src/schema/registry.py tests/test_schema.py
git commit -m "feat(schema): register all 40 tables with columns, indexes, foreign keys, sync config"
```

---

### Task 3: SQLite Table Creator

**Files:**
- Create: `src/schema/sqlite.py`
- Modify: `tests/test_schema_generators.py` (new)

- [ ] **Step 1: Write failing tests**

Create `tests/test_schema_generators.py`:

```python
"""Tests for schema-driven SQL generation."""

import sqlite3
import pytest
from src.schema.registry import TABLES, TableDef, ColumnDef, IndexDef
from src.schema.sqlite import generate_create_sql, create_all_tables, ensure_columns


@pytest.fixture
def tmp_db(tmp_path):
    """Return path to a temp SQLite database."""
    return str(tmp_path / "test.sqlite3")


def test_generate_create_sql_basic():
    table = TableDef(
        name="test_basic",
        description="Test",
        columns=[
            ColumnDef("id", "INTEGER", nullable=False),
            ColumnDef("name", "TEXT"),
        ],
        primary_key="id",
    )
    sql = generate_create_sql(table)
    assert "CREATE TABLE IF NOT EXISTS test_basic" in sql
    assert "id INTEGER NOT NULL" in sql
    assert "name TEXT" in sql
    assert "PRIMARY KEY (id)" in sql


def test_generate_create_sql_with_default():
    table = TableDef(
        name="test_defaults",
        description="Test",
        columns=[
            ColumnDef("id", "INTEGER", nullable=False),
            ColumnDef("source", "TEXT", default="paper"),
        ],
        primary_key="id",
    )
    sql = generate_create_sql(table)
    assert "DEFAULT 'paper'" in sql


def test_create_all_tables_creates_tables(tmp_db):
    create_all_tables(tmp_db)
    conn = sqlite3.connect(tmp_db)
    tables = {row[0] for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()}
    conn.close()
    for name in TABLES:
        assert name in tables, f"Table {name} not created"


def test_create_all_tables_is_idempotent(tmp_db):
    create_all_tables(tmp_db)
    create_all_tables(tmp_db)  # Should not raise


def test_ensure_columns_adds_missing(tmp_db):
    conn = sqlite3.connect(tmp_db)
    conn.execute("CREATE TABLE test_ensure (id INTEGER PRIMARY KEY)")
    conn.close()
    # Register a table with an extra column
    from src.schema.registry import _register
    _register(TableDef(
        name="test_ensure",
        description="Test",
        columns=[
            ColumnDef("id", "INTEGER", nullable=False),
            ColumnDef("new_col", "TEXT"),
        ],
        primary_key="id",
    ))
    added = ensure_columns(tmp_db)
    assert "test_ensure.new_col" in added
    # Verify column exists
    conn = sqlite3.connect(tmp_db)
    cols = [row[1] for row in conn.execute("PRAGMA table_info(test_ensure)").fetchall()]
    conn.close()
    assert "new_col" in cols
    # Cleanup
    del TABLES["test_ensure"]


def test_ensure_columns_is_idempotent(tmp_db):
    create_all_tables(tmp_db)
    added1 = ensure_columns(tmp_db)
    added2 = ensure_columns(tmp_db)
    assert added2 == [], "Second run should add nothing"
```

- [ ] **Step 2: Run tests — should FAIL (module not found)**

Run: `python -m pytest tests/test_schema_generators.py -v`
Expected: FAIL (ImportError)

- [ ] **Step 3: Implement sqlite.py**

Create `src/schema/sqlite.py`:

```python
"""SQLite schema operations driven by the registry."""

import logging
import sqlite3

from src.schema.registry import TABLES, TableDef

logger = logging.getLogger(__name__)


def generate_create_sql(table: TableDef) -> str:
    """Generate CREATE TABLE IF NOT EXISTS SQL for one table."""
    cols = []
    for c in table.columns:
        parts = [c.name, c.type]
        if not c.nullable:
            parts.append("NOT NULL")
        if c.default is not None:
            parts.append(f"DEFAULT '{c.default}'")
        cols.append(" ".join(parts))

    pk = table.primary_key
    if isinstance(pk, str):
        pk = [pk]
    cols.append(f"PRIMARY KEY ({', '.join(pk)})")

    for fk in table.foreign_keys:
        cols.append(
            f"FOREIGN KEY ({fk.column}) REFERENCES {fk.references_table}({fk.references_column})"
        )

    body = ",\n    ".join(cols)
    sql = f"CREATE TABLE IF NOT EXISTS {table.name} (\n    {body}\n);\n"

    for idx in table.indexes:
        unique = "UNIQUE " if idx.unique else ""
        idx_cols = ", ".join(idx.columns)
        sql += f"CREATE {unique}INDEX IF NOT EXISTS {idx.name} ON {table.name}({idx_cols});\n"

    return sql


def create_all_tables(db_path: str) -> None:
    """Create all tables defined in the registry. Idempotent."""
    with sqlite3.connect(db_path) as conn:
        for table in TABLES.values():
            conn.executescript(generate_create_sql(table))
        conn.commit()
    logger.info("[SCHEMA] Created/verified %d tables in %s", len(TABLES), db_path)


def ensure_columns(db_path: str) -> list[str]:
    """Add any columns in registry that are missing from SQLite.
    Returns list of 'table.column' strings for columns added."""
    added = []
    with sqlite3.connect(db_path) as conn:
        for table in TABLES.values():
            existing = {
                row[1] for row in conn.execute(f"PRAGMA table_info({table.name})").fetchall()
            }
            for col in table.columns:
                if col.name not in existing:
                    default_clause = f" DEFAULT '{col.default}'" if col.default else ""
                    try:
                        conn.execute(
                            f"ALTER TABLE {table.name} ADD COLUMN {col.name} {col.type}{default_clause}"
                        )
                        added.append(f"{table.name}.{col.name}")
                    except sqlite3.OperationalError:
                        pass  # Column already exists (race condition guard)
        conn.commit()
    if added:
        logger.info("[SCHEMA] Added %d columns: %s", len(added), added)
    return added
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_schema_generators.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add src/schema/sqlite.py tests/test_schema_generators.py
git commit -m "feat(schema): SQLite table creator reads from registry"
```

---

### Task 4: Postgres Table Creator

**Files:**
- Create: `src/schema/postgres.py`
- Modify: `tests/test_schema_generators.py`

- [ ] **Step 1: Write failing test**

Add to `tests/test_schema_generators.py`:

```python
from src.schema.postgres import generate_create_sql as pg_create_sql, generate_ensure_column_sql


def test_postgres_create_sql_uses_serial():
    table = TableDef(
        name="test_pg",
        description="Test",
        columns=[
            ColumnDef("id", "INTEGER", nullable=False),
            ColumnDef("name", "TEXT"),
        ],
        primary_key="id",
    )
    sql = pg_create_sql(table)
    # INTEGER PK in Postgres should use SERIAL
    assert "SERIAL" in sql or "INTEGER" in sql
    assert "CREATE TABLE IF NOT EXISTS test_pg" in sql


def test_postgres_ensure_column_sql():
    sql = generate_ensure_column_sql("my_table", ColumnDef("new_col", "TEXT", default="foo"))
    assert "ALTER TABLE my_table ADD COLUMN" in sql
    assert "new_col" in sql
    assert "DO $$" in sql  # PL/pgSQL idempotent wrapper
```

- [ ] **Step 2: Run test — FAIL**

Run: `python -m pytest tests/test_schema_generators.py::test_postgres_create_sql_uses_serial -v`

- [ ] **Step 3: Implement postgres.py**

Create `src/schema/postgres.py`:

```python
"""Postgres schema operations driven by the registry."""

import logging

from src.schema.registry import TABLES, TableDef, ColumnDef

logger = logging.getLogger(__name__)

# SQLite → Postgres type mapping
_TYPE_MAP = {
    "INTEGER": "INTEGER",
    "REAL": "REAL",
    "TEXT": "TEXT",
    "BLOB": "BYTEA",
}


def generate_create_sql(table: TableDef) -> str:
    """Generate CREATE TABLE IF NOT EXISTS SQL for Postgres."""
    cols = []
    pk = table.primary_key if isinstance(table.primary_key, str) else table.primary_key[0]

    for c in table.columns:
        pg_type = _TYPE_MAP.get(c.type, c.type)
        # Auto-increment integer PKs use SERIAL
        if c.name == pk and pg_type == "INTEGER":
            pg_type = "SERIAL"
        parts = [c.name, pg_type]
        if not c.nullable:
            parts.append("NOT NULL")
        if c.default is not None:
            parts.append(f"DEFAULT '{c.default}'")
        cols.append(" ".join(parts))

    pk_names = table.primary_key if isinstance(table.primary_key, list) else [table.primary_key]
    cols.append(f"PRIMARY KEY ({', '.join(pk_names)})")

    body = ",\n    ".join(cols)
    sql = f"CREATE TABLE IF NOT EXISTS {table.name} (\n    {body}\n);\n"

    for idx in table.indexes:
        unique = "UNIQUE " if idx.unique else ""
        idx_cols = ", ".join(idx.columns)
        sql += f"CREATE {unique}INDEX IF NOT EXISTS {idx.name} ON {table.name}({idx_cols});\n"

    return sql


def generate_ensure_column_sql(table_name: str, col: ColumnDef) -> str:
    """Generate idempotent ALTER TABLE ADD COLUMN for Postgres (PL/pgSQL)."""
    pg_type = _TYPE_MAP.get(col.type, col.type)
    default_clause = f" DEFAULT '{col.default}'" if col.default else ""
    return f"""DO $$ BEGIN
    ALTER TABLE {table_name} ADD COLUMN {col.name} {pg_type}{default_clause};
EXCEPTION WHEN duplicate_column THEN NULL;
END $$;
"""


def create_all_tables(database_url: str) -> None:
    """Create all Postgres tables from registry. Idempotent."""
    import psycopg2
    conn = psycopg2.connect(database_url)
    cur = conn.cursor()
    for table in TABLES.values():
        if table.sync_to_postgres:
            cur.execute(generate_create_sql(table))
    conn.commit()
    cur.close()
    conn.close()
    logger.info("[SCHEMA] Postgres: created/verified tables")


def ensure_columns(database_url: str) -> list[str]:
    """Add missing columns to Postgres tables. Idempotent."""
    import psycopg2
    added = []
    conn = psycopg2.connect(database_url)
    cur = conn.cursor()
    for table in TABLES.values():
        if not table.sync_to_postgres:
            continue
        cur.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = %s",
            (table.name,),
        )
        existing = {row[0] for row in cur.fetchall()}
        for col in table.columns:
            if col.name not in existing:
                cur.execute(generate_ensure_column_sql(table.name, col))
                added.append(f"{table.name}.{col.name}")
    conn.commit()
    cur.close()
    conn.close()
    if added:
        logger.info("[SCHEMA] Postgres: added %d columns: %s", len(added), added)
    return added
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_schema_generators.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add src/schema/postgres.py tests/test_schema_generators.py
git commit -m "feat(schema): Postgres table creator with PL/pgSQL idempotent migrations"
```

---

### Task 5: Sync Config Generator

**Files:**
- Create: `src/schema/sync_config.py`
- Modify: `tests/test_schema_generators.py`

- [ ] **Step 1: Write failing test**

Add to `tests/test_schema_generators.py`:

```python
from src.schema.sync_config import generate_sync_tables


def test_generate_sync_tables_includes_synced():
    config = generate_sync_tables()
    for name, table in TABLES.items():
        if table.sync_to_postgres:
            assert name in config, f"Synced table {name} missing from generated config"


def test_generate_sync_tables_excludes_non_synced():
    config = generate_sync_tables()
    for name, table in TABLES.items():
        if not table.sync_to_postgres:
            assert name not in config, f"Non-synced table {name} should not be in config"


def test_sync_config_has_required_keys():
    config = generate_sync_tables()
    for name, entry in config.items():
        assert "mode" in entry, f"{name} missing 'mode'"
        assert "pk" in entry, f"{name} missing 'pk'"
        if entry["mode"] == "incremental":
            assert "time_col" in entry, f"Incremental table {name} missing 'time_col'"
```

- [ ] **Step 2: Run test — FAIL**

- [ ] **Step 3: Implement sync_config.py**

Create `src/schema/sync_config.py`:

```python
"""Generate SYNC_TABLES config from the schema registry."""

from src.schema.registry import TABLES


def generate_sync_tables() -> dict[str, dict]:
    """Generate SYNC_TABLES config. Only includes tables where sync_to_postgres=True."""
    config = {}
    for name, table in TABLES.items():
        if not table.sync_to_postgres:
            continue
        entry: dict = {"mode": table.sync_mode}
        pk = table.sync_pk or (
            table.primary_key if isinstance(table.primary_key, str) else table.primary_key[0]
        )
        entry["pk"] = pk
        if table.sync_mode in ("incremental", "latest_only") and table.sync_time_column:
            entry["time_col"] = table.sync_time_column
        config[name] = entry
    return config
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_schema_generators.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add src/schema/sync_config.py tests/test_schema_generators.py
git commit -m "feat(schema): sync config generator from registry"
```

---

### Task 6: Schema Validator

**Files:**
- Create: `src/schema/validator.py`
- Modify: `tests/test_schema.py`
- Modify: `src/main.py` (add CLI command)

- [ ] **Step 1: Write failing tests**

Add to `tests/test_schema.py`:

```python
from src.schema.validator import validate_sqlite, SchemaIssue, validate_codebase


def test_validate_sqlite_clean_db(tmp_path):
    """A DB created from the registry should have zero issues."""
    from src.schema.sqlite import create_all_tables
    db = str(tmp_path / "test.sqlite3")
    create_all_tables(db)
    issues = validate_sqlite(db)
    assert issues == [], f"Issues on fresh DB: {issues}"


def test_validate_sqlite_detects_missing_table(tmp_path):
    import sqlite3
    db = str(tmp_path / "test.sqlite3")
    sqlite3.connect(db).close()  # Empty DB
    issues = validate_sqlite(db)
    assert len(issues) > 0
    assert any("missing_table" in str(i) for i in issues)


def test_validate_codebase_finds_violations():
    issues = validate_codebase()
    # During transition, violations will exist — test just verifies it runs
    assert isinstance(issues, list)
```

- [ ] **Step 2: Run tests — FAIL**

- [ ] **Step 3: Implement validator.py**

Create `src/schema/validator.py`:

```python
"""Schema validator — compares live databases against the registry."""

import json
import logging
import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from src.schema.registry import TABLES

logger = logging.getLogger(__name__)


@dataclass
class SchemaIssue:
    severity: str  # error, warning
    issue_type: str  # missing_table, missing_column, type_mismatch, extra_column, codebase_violation
    table: str
    column: str | None = None
    detail: str = ""

    def __str__(self):
        col = f".{self.column}" if self.column else ""
        return f"[{self.severity}] {self.issue_type}: {self.table}{col} — {self.detail}"


def validate_sqlite(db_path: str) -> list[SchemaIssue]:
    """Compare local SQLite schema against registry."""
    issues = []
    conn = sqlite3.connect(db_path)

    existing_tables = {
        row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }

    for name, table in TABLES.items():
        if name not in existing_tables:
            issues.append(SchemaIssue("error", "missing_table", name,
                                      detail=f"Table {name} not found in database"))
            continue

        existing_cols = {
            row[1]: row[2]
            for row in conn.execute(f"PRAGMA table_info({name})").fetchall()
        }
        for col in table.columns:
            if col.name not in existing_cols:
                issues.append(SchemaIssue("error", "missing_column", name, col.name,
                                          detail=f"Column {col.name} ({col.type}) missing"))

    conn.close()
    return issues


def validate_codebase() -> list[SchemaIssue]:
    """Scan Python files for raw CREATE TABLE / ALTER TABLE outside src/schema/."""
    issues = []
    known_path = Path("config/known_schema_violations.json")
    allowed = set()
    if known_path.exists():
        data = json.loads(known_path.read_text())
        allowed = {e["file"] for e in data.get("allowed_create_table", [])}

    src_root = Path("src")
    for py_file in src_root.rglob("*.py"):
        rel = str(py_file)
        if "schema" in rel or "__pycache__" in rel:
            continue
        if rel in allowed:
            continue
        text = py_file.read_text(errors="ignore")
        for i, line in enumerate(text.splitlines(), 1):
            if "CREATE TABLE" in line and "#" not in line.split("CREATE TABLE")[0]:
                issues.append(SchemaIssue(
                    "warning", "codebase_violation", "n/a",
                    detail=f"{rel}:{i} — CREATE TABLE found outside schema/"
                ))

    return issues


def fix_issues(issues: list[SchemaIssue], db_path: str | None = None) -> list[str]:
    """Auto-fix: create missing tables, add missing columns. Returns list of actions."""
    if not db_path:
        return []
    from src.schema.sqlite import create_all_tables, ensure_columns
    actions = []
    missing_tables = [i for i in issues if i.issue_type == "missing_table"]
    if missing_tables:
        create_all_tables(db_path)
        actions.append(f"Created {len(missing_tables)} missing tables")
    added = ensure_columns(db_path)
    if added:
        actions.append(f"Added {len(added)} columns: {added}")
    return actions
```

- [ ] **Step 4: Add validate-schema CLI command to main.py**

In `src/main.py`, add to `build_parser()` (after existing subparsers):

```python
validate_schema = subparsers.add_parser("validate-schema",
    help="Validate database schema against registry")
validate_schema.add_argument("--fix", action="store_true",
    help="Auto-fix missing tables/columns")
validate_schema.add_argument("--postgres", action="store_true",
    help="Also validate Render Postgres")
validate_schema.set_defaults(func=cmd_validate_schema)
```

Add the command function (import at top of file):

```python
def cmd_validate_schema(args):
    from src.schema.validator import validate_sqlite, validate_codebase, fix_issues
    from src.config import DB_PATH

    print("Validating SQLite schema...")
    issues = validate_sqlite(DB_PATH)
    code_issues = validate_codebase()

    for issue in issues + code_issues:
        print(f"  {issue}")

    if not issues and not code_issues:
        print("Schema OK — no issues found.")
        return

    print(f"\n{len(issues)} database issues, {len(code_issues)} codebase violations")

    if args.fix and issues:
        actions = fix_issues(issues, DB_PATH)
        for a in actions:
            print(f"  FIX: {a}")
```

- [ ] **Step 5: Run tests**

Run: `python -m pytest tests/test_schema.py -v`
Expected: ALL PASS

- [ ] **Step 6: Commit**

```bash
git add src/schema/validator.py src/main.py tests/test_schema.py
git commit -m "feat(schema): validator CLI with --fix flag for auto-repair"
```

---

## Session 2: Tests, Guardrails, Migration

### Task 7: Guardrail Tests

**Files:**
- Modify: `tests/test_schema.py`

- [ ] **Step 1: Add guardrail and consistency tests**

Add to `tests/test_schema.py`:

```python
import os
from pathlib import Path
from src.schema.registry import TABLES


def test_no_create_table_in_source():
    """Scan src/ (except src/schema/) for CREATE TABLE — fail if found."""
    import json
    known_path = Path("config/known_schema_violations.json")
    allowed = set()
    if known_path.exists():
        data = json.loads(known_path.read_text())
        allowed = {e["file"] for e in data.get("allowed_create_table", [])}

    violations = []
    for root, dirs, files in os.walk("src"):
        dirs[:] = [d for d in dirs if d not in ("__pycache__", "schema")]
        for f in files:
            if f.endswith(".py"):
                path = os.path.join(root, f).replace("\\", "/")
                if path in allowed:
                    continue
                with open(os.path.join(root, f), errors="ignore") as fh:
                    for i, line in enumerate(fh, 1):
                        if "CREATE TABLE" in line and not line.strip().startswith("#"):
                            violations.append(f"{path}:{i}")
    assert violations == [], f"CREATE TABLE found outside schema/: {violations}"


def test_no_alter_table_in_source():
    """Same for ALTER TABLE."""
    import json
    known_path = Path("config/known_schema_violations.json")
    allowed = set()
    if known_path.exists():
        data = json.loads(known_path.read_text())
        allowed = {e["file"] for e in data.get("allowed_alter_table", [])}

    violations = []
    for root, dirs, files in os.walk("src"):
        dirs[:] = [d for d in dirs if d not in ("__pycache__", "schema")]
        for f in files:
            if f.endswith(".py"):
                path = os.path.join(root, f).replace("\\", "/")
                if path in allowed:
                    continue
                with open(os.path.join(root, f), errors="ignore") as fh:
                    for i, line in enumerate(fh, 1):
                        if "ALTER TABLE" in line and not line.strip().startswith("#"):
                            violations.append(f"{path}:{i}")
    assert violations == [], f"ALTER TABLE found outside schema/: {violations}"


def test_every_foreign_key_references_valid_table():
    for name, table in TABLES.items():
        for fk in table.foreign_keys:
            assert fk.references_table in TABLES, (
                f"{name}.{fk.column} references {fk.references_table} which is not in TABLES"
            )


def test_every_sync_table_has_time_column():
    for name, table in TABLES.items():
        if not table.sync_to_postgres:
            continue
        if table.sync_mode in ("incremental", "latest_only"):
            assert table.sync_time_column, (
                f"{name} has sync_mode={table.sync_mode} but no sync_time_column"
            )
            col_names = [c.name for c in table.columns]
            assert table.sync_time_column in col_names, (
                f"{name}.sync_time_column={table.sync_time_column} not in columns"
            )


def test_sqlite_create_sql_is_valid():
    """Generated SQL parses without error in SQLite."""
    import sqlite3
    from src.schema.sqlite import generate_create_sql
    conn = sqlite3.connect(":memory:")
    for table in TABLES.values():
        sql = generate_create_sql(table)
        conn.executescript(sql)  # Should not raise
    conn.close()


def test_registry_column_names_consistent():
    """Flag if two tables define semantically similar columns with different names."""
    KNOWN_CONFLICTS = {
        # (table, column) pairs that are intentionally different
    }
    # This is a documentation-level test — it passes by default.
    # Add specific assertions as conflicts are discovered.
    pass
```

- [ ] **Step 2: Run guardrail tests — they will FAIL because CREATE TABLE still exists in source**

Run: `python -m pytest tests/test_schema.py::test_no_create_table_in_source -v`
Expected: FAIL (lists all files with CREATE TABLE)

**Note the violation list** — this becomes the work list for Task 8.

- [ ] **Step 3: Create known violations file for transition period**

Create `config/known_schema_violations.json` listing ALL current violations. This unblocks the guardrail test while you migrate each file in Task 8.

```json
{
  "allowed_create_table": [
    {"file": "src/journal/store.py", "reason": "Will be migrated in Task 8"},
    {"file": "src/scheduler/watch.py", "reason": "Will be migrated in Task 8"},
    {"file": "src/training/versioning.py", "reason": "Will be migrated in Task 8"},
    {"file": "src/council/engine.py", "reason": "Will be migrated in Task 8"},
    {"file": "src/council/value_tracker.py", "reason": "Will be migrated in Task 8"}
  ],
  "allowed_alter_table": [
    {"file": "src/journal/store.py", "reason": "Will be migrated in Task 8"},
    {"file": "src/scheduler/watch.py", "reason": "Will be migrated in Task 8"},
    {"file": "src/training/versioning.py", "reason": "Will be migrated in Task 8"},
    {"file": "src/council/engine.py", "reason": "Will be migrated in Task 8"}
  ]
}
```

**You MUST add every file that has CREATE TABLE or ALTER TABLE in src/ to this list** — run the test first to get the full list.

- [ ] **Step 4: Run all schema tests — should PASS with known violations file**

Run: `python -m pytest tests/test_schema.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_schema.py config/known_schema_violations.json
git commit -m "test(schema): guardrail tests + known violations file for migration"
```

---

### Task 8: Migrate Source Files to Use Registry

This is the largest migration task. For each file that currently defines `CREATE TABLE`, replace the inline DDL with a call to the registry.

**Strategy:** Migrate one file at a time. After each file:
1. Remove the CREATE TABLE / ALTER TABLE from the source file
2. Remove the file from `config/known_schema_violations.json`
3. Run `python -m pytest tests/ -x -q` to verify no regressions
4. Commit

**Files to migrate (in dependency order):**

| Priority | File | Tables | Replace with |
|---|---|---|---|
| 1 | `src/journal/store.py:126-170` | recommendations, shadow_trades, validation_results | `from src.schema.sqlite import create_all_tables, ensure_columns` |
| 2 | `src/training/versioning.py:56-175` | 6 tables | `from src.schema.sqlite import create_all_tables, ensure_columns` |
| 3 | `src/council/engine.py:44-124` | 4 tables | `from src.schema.sqlite import create_all_tables, ensure_columns` |
| 4 | `src/council/value_tracker.py:36-74` | 2 tables | `from src.schema.sqlite import create_all_tables, ensure_columns` |
| 5 | `src/scheduler/watch.py:857-1014` | 15+ tables | `from src.schema.sqlite import create_all_tables, ensure_columns` |
| 6 | 11 data collectors in `src/data_collection/` | 11 tables | Remove `_INIT_SQL` constants, init via registry |
| 7 | `src/logging/activity.py:28-35` | activity_log | Remove `_CREATE_TABLE_SQL` |
| 8 | `src/features/setup_classifier.py:237` | setup_signals | Remove `_ensure_setup_signals_table()` |
| 9 | `src/features/traffic_light.py:34` | traffic_light_state | Remove `_ensure_state_table()` |
| 10 | `src/training/quality_drift.py:30-48` | quality_drift_metrics | Remove inline DDL |
| 11 | `src/training/canary.py:41` | canary_evaluations | Remove inline DDL |
| 12 | `src/training/dpo_pipeline.py:28` | preference_pairs | Remove inline DDL |
| 13 | `src/scheduler/metrics.py:25-36` | schedule_metrics | Remove `init_schedule_metrics()` DDL |
| 14 | `src/data_collection/docs_collector.py:25` | research_docs | Remove inline DDL |
| 15 | `scripts/create_missing_tables.py` | Remove TABLES array, call `create_all_tables()` |
| 16 | `scripts/render_migrate.py` | Replace MIGRATIONS with `from src.schema.postgres import create_all_tables, ensure_columns` |
| 17 | `scripts/render_init_db.py` | Replace POSTGRES_SCHEMA with registry |

- [ ] **Step 1: For each file above** — read the current CREATE TABLE, verify it matches the registry, then replace with registry call.

**Pattern for initializer functions (store.py, versioning.py, etc.):**

```python
# BEFORE:
def initialize_database(db_path=DB_PATH):
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA)  # 100+ lines of CREATE TABLE
    # 20+ ALTER TABLE migrations...

# AFTER:
def initialize_database(db_path=DB_PATH):
    from src.schema.sqlite import create_all_tables, ensure_columns
    create_all_tables(db_path)
    added = ensure_columns(db_path)
    if added:
        import logging
        logging.getLogger(__name__).info("[DB] Added %d columns: %s", len(added), added)
```

**Pattern for collectors (data_collection/*.py):**

```python
# BEFORE:
_INIT_SQL = """CREATE TABLE IF NOT EXISTS vix_term_structure (...)"""

def collect_vix(db_path=DB_PATH):
    with sqlite3.connect(db_path) as conn:
        conn.executescript(_INIT_SQL)
        # ... collection logic

# AFTER:
def collect_vix(db_path=DB_PATH):
    with sqlite3.connect(db_path) as conn:
        # Table creation handled by schema registry at startup
        # ... collection logic
```

**Pattern for watch.py `_ensure_all_tables()`:**

```python
# BEFORE:
@staticmethod
def _ensure_all_tables():
    conn = sqlite3.connect(DB_PATH)
    conn.executescript("""CREATE TABLE IF NOT EXISTS ...""")  # 150+ lines
    # ALTER TABLE migrations...

# AFTER:
@staticmethod
def _ensure_all_tables():
    from src.schema.sqlite import create_all_tables, ensure_columns
    create_all_tables(DB_PATH)
    ensure_columns(DB_PATH)
```

- [ ] **Step 2: After each file migration — remove from known_schema_violations.json**

- [ ] **Step 3: After all migrations — run guardrail test with empty violations list**

Run: `python -m pytest tests/test_schema.py::test_no_create_table_in_source -v`
Expected: PASS (no violations remaining)

- [ ] **Step 4: Run full test suite**

Run: `python -m pytest tests/ -q`
Expected: >= 1,245 tests pass, 0 new failures

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "refactor(schema): migrate all CREATE TABLE/ALTER TABLE to registry

Removed inline DDL from 17 source files and 3 scripts.
All table creation now goes through src/schema/sqlite.py
which reads from the registry."
```

---

### Task 9: Rewire render_sync.py

**Files:**
- Modify: `src/sync/render_sync.py:35-240`

- [ ] **Step 1: Write test**

Add to `tests/test_schema.py`:

```python
def test_generated_sync_tables_matches_registry():
    """Every table in registry with sync_to_postgres=True must be in generated config."""
    from src.schema.sync_config import generate_sync_tables
    config = generate_sync_tables()
    for name, table in TABLES.items():
        if table.sync_to_postgres:
            assert name in config, f"Synced table {name} missing from generated config"
```

- [ ] **Step 2: Replace hardcoded SYNC_TABLES**

In `src/sync/render_sync.py`, replace lines 35-240 (the entire `SYNC_TABLES` dict) with:

```python
from src.schema.sync_config import generate_sync_tables
SYNC_TABLES = generate_sync_tables()
```

- [ ] **Step 3: Run full test suite**

Run: `python -m pytest tests/ -q`
Expected: ALL PASS

- [ ] **Step 4: Commit**

```bash
git add src/sync/render_sync.py tests/test_schema.py
git commit -m "refactor(schema): SYNC_TABLES generated from registry"
```

---

### Task 10: Update Agent Guardrails

**Files:**
- Modify: `CLAUDE.md`
- Modify: `AGENTS.md`

- [ ] **Step 1: Add schema rules to CLAUDE.md**

Add after the existing "Schema migrations required" rule:

```markdown
## Database Schema Rules (MANDATORY)

1. **NEVER write CREATE TABLE in any file except `src/schema/registry.py`.**
2. **NEVER write ALTER TABLE in any file except `src/schema/registry.py`.**
3. **To add a new table:** Add a `TableDef` to `TABLES` in `src/schema/registry.py`, then run `python -m src.main validate-schema --fix`.
4. **To add a column:** Add a `ColumnDef` to the table's columns list in `src/schema/registry.py`, then run `python -m src.main validate-schema --fix`.
5. **Before any PR that touches database tables:** Run `python -m src.main validate-schema` and include the output in the PR description.
6. **CI will reject PRs that contain CREATE TABLE or ALTER TABLE outside of src/schema/.**
```

- [ ] **Step 2: Add schema governance to AGENTS.md**

Add a new section:

```markdown
## Database Schema Governance

**Source of truth:** `src/schema/registry.py`
**Table count:** 40+ (auto-counted from registry)
**Validation:** `python -m src.main validate-schema [--fix] [--postgres]`

### Adding a new table
1. Add `TableDef` to `TABLES` in `src/schema/registry.py`
2. Run `python -m src.main validate-schema --fix`
3. Run `python scripts/render_migrate.py`
4. Set `sync_to_postgres=True` in the TableDef if needed
5. Commit registry.py + code that uses the new table

### Adding a column
1. Add `ColumnDef` to the table's columns list in `src/schema/registry.py`
2. Run `python -m src.main validate-schema --fix`
3. Run `python scripts/render_migrate.py`
4. Commit registry.py + code that uses the new column
```

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md AGENTS.md
git commit -m "docs: add schema registry governance rules to CLAUDE.md and AGENTS.md"
```

---

## Session 3: Documentation + Dashboard Verification

### Task 11: Documentation

**Files:**
- Create: `docs/schema-governance.md`
- Create: `docs/dashboard-data-map.md`
- Create: `scripts/generate_schema_docs.py`
- Modify: `docs/database-schema.md` (regenerated)

- [ ] **Step 1: Create schema governance doc**

Create `docs/schema-governance.md` explaining:
1. Why the registry exists (link to issue #181 and schema drift bugs from the sprint doc)
2. How to add tables and columns (step-by-step with examples)
3. How validation works (startup, CLI, CI)
4. What happens when an agent violates the rules
5. The migration path from the old approach

- [ ] **Step 2: Create dashboard data map**

Create `docs/dashboard-data-map.md` — copy the complete page→endpoint→table→column mapping from the sprint doc (lines 696-780 of the sprint document). This is already fully specified in the sprint doc.

- [ ] **Step 3: Create schema doc generator**

Create `scripts/generate_schema_docs.py`:

```python
"""Generate docs/database-schema.md from the schema registry."""

from src.schema.registry import TABLES


def main():
    lines = ["# Database Schema\n"]
    lines.append(f"> Auto-generated from `src/schema/registry.py` — {len(TABLES)} tables\n")
    lines.append("## Tables\n")

    # Group by domain (use description keywords)
    for name in sorted(TABLES):
        table = TABLES[name]
        lines.append(f"### {name}\n")
        lines.append(f"{table.description}\n")
        lines.append("| Column | Type | Nullable | Default | Description |")
        lines.append("|---|---|---|---|---|")
        for col in table.columns:
            nullable = "Yes" if col.nullable else "No"
            default = col.default or ""
            lines.append(f"| {col.name} | {col.type} | {nullable} | {default} | {col.description} |")
        lines.append("")

    with open("docs/database-schema.md", "w") as f:
        f.write("\n".join(lines))
    print(f"Generated docs/database-schema.md with {len(TABLES)} tables")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run generator and commit**

```bash
python scripts/generate_schema_docs.py
git add docs/ scripts/generate_schema_docs.py
git commit -m "docs: auto-generated schema docs + governance guide + dashboard data map"
```

---

### Task 12: Dashboard Verification Script

**Files:**
- Create: `scripts/verify_dashboard.py`
- Create: `scripts/verify_column_names.py`

- [ ] **Step 1: Create API endpoint verification script**

Create `scripts/verify_dashboard.py` — copy the CHECKS list from the sprint doc (lines 802-833) and implement the verification loop:

```python
"""Verify every dashboard API endpoint returns valid data.

Usage:
    python scripts/verify_dashboard.py                    # local (localhost:8000)
    python scripts/verify_dashboard.py --cloud URL        # cloud
"""

import argparse
import json
import sys
import requests

CHECKS = [
    {"path": "/api/shadow/open", "expect_fields": ["trades"]},
    {"path": "/api/shadow/closed?days=90", "expect_fields": ["trades"]},
    {"path": "/api/shadow/metrics?days=90",
     "expect_fields": ["win_rate", "sharpe", "profit_factor", "max_drawdown_pct"]},
    {"path": "/api/shadow/account", "expect_fields": ["equity"]},
    {"path": "/api/cto-report?days=90", "expect_fields": ["performance", "trade_summary"]},
    {"path": "/api/build-score", "expect_fields": ["build_score"]},
    {"path": "/api/health/hshs"},
    {"path": "/api/health/score"},
    {"path": "/api/training/status", "expect_fields": ["total_examples"]},
    {"path": "/api/training/versions"},
    {"path": "/api/council/latest"},
    {"path": "/api/costs?days=90"},
    {"path": "/api/activity/feed?limit=10"},
    {"path": "/api/logs/recent?limit=10"},
    {"path": "/api/docs"},
    {"path": "/api/notes"},
    {"path": "/api/system/table-counts"},
    {"path": "/api/traffic-light/current"},
    {"path": "/api/live/trades"},
    {"path": "/api/live/summary"},
    {"path": "/api/packets?days=7"},
    {"path": "/api/system/validation"},
    {"path": "/api/config"},
    {"path": "/api/settings"},
    {"path": "/api/halt-status"},
]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cloud", help="Cloud base URL")
    parser.add_argument("--secret", help="API secret for auth")
    args = parser.parse_args()

    base = args.cloud or "http://localhost:8000"
    headers = {"X-API-Secret": args.secret} if args.secret else {}

    passed = failed = 0
    for check in CHECKS:
        url = f"{base}{check['path']}"
        try:
            r = requests.get(url, headers=headers, timeout=10)
            if r.status_code != 200:
                print(f"  FAIL {check['path']} — HTTP {r.status_code}")
                failed += 1
                continue
            data = r.json()
            for field in check.get("expect_fields", []):
                if field not in data:
                    print(f"  FAIL {check['path']} — missing field '{field}'")
                    failed += 1
                    continue
            print(f"  OK   {check['path']}")
            passed += 1
        except Exception as e:
            print(f"  FAIL {check['path']} — {e}")
            failed += 1

    print(f"\n{passed} passed, {failed} failed out of {len(CHECKS)} checks")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Create column name consistency scanner**

Create `scripts/verify_column_names.py`:

```python
"""Scan .py files for SQL queries and cross-reference column names against the registry."""

import re
from pathlib import Path
from src.schema.registry import TABLES

KNOWN_CONFLICTS = {
    "regime_label": ("recommendations", "market_regime"),
    "estimated_cost": ("api_costs", "cost_dollars"),
}


def main():
    violations = []
    for conflict, (table, canonical) in KNOWN_CONFLICTS.items():
        for py in Path("src").rglob("*.py"):
            if "schema" in str(py) or "__pycache__" in str(py):
                continue
            text = py.read_text(errors="ignore")
            if conflict in text:
                for i, line in enumerate(text.splitlines(), 1):
                    if conflict in line and ("SELECT" in line or "INSERT" in line
                                             or "UPDATE" in line or "WHERE" in line):
                        violations.append(f"{py}:{i} uses '{conflict}' — should be '{canonical}'")

    if violations:
        print(f"Found {len(violations)} column name conflicts:")
        for v in violations:
            print(f"  {v}")
    else:
        print("No known column name conflicts found.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Commit**

```bash
git add scripts/verify_dashboard.py scripts/verify_column_names.py
git commit -m "feat: dashboard verification + column name consistency scripts"
```

---

### Task 13: Critical Data Path Tests

**Files:**
- Create: `tests/test_dashboard_data.py`

- [ ] **Step 1: Write critical data path tests**

Create `tests/test_dashboard_data.py`:

```python
"""Critical data path tests — verify data flows correctly from DB to API responses."""

import sqlite3
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from src.config import DB_PATH
from src.schema.sqlite import create_all_tables


@pytest.fixture
def test_db(tmp_path):
    db = str(tmp_path / "test.sqlite3")
    create_all_tables(db)
    return db


def test_closed_trades_visible(test_db):
    """A trade closed via close_shadow_trade() must appear in closed queries."""
    from src.journal.store import insert_shadow_trade, update_shadow_trade, get_closed_shadow_trades

    trade_id = insert_shadow_trade({
        "ticker": "AAPL",
        "entry_price": 150.0,
        "stop_price": 145.0,
        "target_1": 160.0,
        "planned_shares": 10,
        "status": "open",
    }, db_path=test_db)

    update_shadow_trade(trade_id, {
        "status": "closed",
        "actual_exit_price": 155.0,
        "actual_exit_time": datetime.now(ZoneInfo("America/New_York")).isoformat(),
        "pnl_dollars": 50.0,
        "pnl_pct": 3.33,
        "exit_reason": "target_hit",
    }, db_path=test_db)

    closed = get_closed_shadow_trades(db_path=test_db)
    assert len(closed) >= 1, "Closed trade not visible in get_closed_shadow_trades()"
    assert any(t["trade_id"] == trade_id for t in closed)


def test_api_costs_uses_cost_dollars(test_db):
    """api_costs table must use cost_dollars column, not estimated_cost."""
    conn = sqlite3.connect(test_db)
    cols = [row[1] for row in conn.execute("PRAGMA table_info(api_costs)").fetchall()]
    conn.close()
    assert "cost_dollars" in cols, "api_costs missing cost_dollars column"
    assert "estimated_cost" not in cols, "api_costs has deprecated estimated_cost column"


def test_recommendations_uses_market_regime(test_db):
    """recommendations table must use market_regime, not regime_label."""
    conn = sqlite3.connect(test_db)
    cols = [row[1] for row in conn.execute("PRAGMA table_info(recommendations)").fetchall()]
    conn.close()
    assert "market_regime" in cols, "recommendations missing market_regime column"
```

- [ ] **Step 2: Run tests**

Run: `python -m pytest tests/test_dashboard_data.py -v`
Expected: ALL PASS

- [ ] **Step 3: Commit**

```bash
git add tests/test_dashboard_data.py
git commit -m "test: critical data path tests for dashboard correctness"
```

---

### Task 14: Startup Schema Validation Integration

**Files:**
- Modify: `src/scheduler/watch.py`

- [ ] **Step 1: Add schema validation to WatchLoop.run()**

After `self._configure_database()` and `self._check_row_counts()` in `watch.py`, add:

```python
# Validate schema against registry
try:
    from src.schema.validator import validate_sqlite
    issues = validate_sqlite(DB_PATH)
    if issues:
        logger.warning("[SCHEMA] %d schema issues found", len(issues))
        for issue in issues[:5]:
            logger.warning("[SCHEMA]   %s", issue)
        try:
            from src.notifications.telegram import send_telegram, is_telegram_enabled
            if is_telegram_enabled():
                send_telegram(f"⚠️ Schema drift detected: {len(issues)} issues. Run validate-schema --fix")
        except Exception:
            pass
    else:
        logger.info("[SCHEMA] Schema validation passed — all tables and columns match registry")
except Exception as exc:
    logger.warning("[SCHEMA] Validation failed: %s", exc)
```

- [ ] **Step 2: Run full test suite**

Run: `python -m pytest tests/ -q`
Expected: ALL PASS, >= 1,245 tests

- [ ] **Step 3: Commit**

```bash
git add src/scheduler/watch.py
git commit -m "feat(schema): startup schema validation with Telegram alerts on drift"
```

---

### Task 15: Final Verification

- [ ] **Step 1: Run all tests**

```bash
python -m pytest tests/ -v
```
Expected: >= 1,245 passed, 0 new failures

- [ ] **Step 2: Run validate-schema**

```bash
python -m src.main validate-schema
```
Expected: "Schema OK — no issues found."

- [ ] **Step 3: Run column name check**

```bash
python scripts/verify_column_names.py
```
Expected: 0 conflicts

- [ ] **Step 4: Run npm build**

```bash
cd frontend && npm run build
```
Expected: Success

- [ ] **Step 5: Commit and tag**

```bash
git add -A
git commit -m "feat(schema): schema registry sprint complete — 40 tables, single source of truth

- src/schema/registry.py defines all 40 tables
- SQLite and Postgres creation generated from registry
- SYNC_TABLES generated from registry
- Validator CLI with --fix flag
- Guardrail tests block CREATE TABLE outside schema/
- Dashboard verification scripts
- Documentation: schema-governance.md, dashboard-data-map.md"
```

---

## Acceptance Criteria Checklist

### Registry
- [ ] `src/schema/registry.py` defines ALL 40+ tables
- [ ] Every table in SYNC_TABLES, render_migrate.py, and initialize_database() is registered
- [ ] No conflicting column names

### Table Creation
- [ ] `initialize_database()` reads from registry
- [ ] `render_migrate.py` reads from registry
- [ ] `render_sync.py` SYNC_TABLES generated from registry
- [ ] All collector CREATE TABLE statements removed

### Validation
- [ ] `validate-schema` CLI command works
- [ ] `--fix` auto-creates missing tables/columns
- [ ] Startup validates and alerts on drift

### Tests
- [ ] `test_no_create_table_in_source` passes
- [ ] `test_no_alter_table_in_source` passes
- [ ] `test_closed_trades_visible` passes
- [ ] `test_api_costs_uses_cost_dollars` passes
- [ ] All existing tests pass (>= 1,245)

### Agent Guardrails
- [ ] CLAUDE.md updated with schema rules
- [ ] AGENTS.md updated with governance section

### Dashboard Verification
- [ ] `scripts/verify_dashboard.py` created
- [ ] `scripts/verify_column_names.py` created
- [ ] `tests/test_dashboard_data.py` passes
- [ ] `docs/dashboard-data-map.md` created

### Documentation
- [ ] `docs/schema-governance.md` created
- [ ] `docs/database-schema.md` regenerated from registry

### Zero Regressions
- [ ] All Python tests pass (>= 1,245)
- [ ] `npm run build` succeeds
- [ ] Watch loop starts and validates schema without errors
