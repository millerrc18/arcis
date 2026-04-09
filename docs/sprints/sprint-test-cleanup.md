# Sprint: Test Suite Cleanup — Fix 62 Failures Across 6 Clusters

> **Branch:** `fix/test-cleanup`
> **Priority:** HIGH — audit quality gate is FAIL, CI is degraded
> **Estimated time:** 3-4 hours CC time
> **Tag on completion:** (no tag — this is a fix sprint, not a feature)

> ⚠️ **Read first:** `MASTER.md`, `docs/audits/audit-2026-04-09.md`, then this sprint.
> The audit identified 62 test failures and 16 collection errors across 6 root causes.
> None were introduced by recent work — they accumulated over multiple sprints where
> inline DDL in tests drifted from the schema registry.

---

## Pre-Flight

```bash
git checkout main
git pull origin main
git checkout -b fix/test-cleanup
python -m pytest tests/ -x -q --ignore=tests/test_ingestion.py --ignore=tests/test_broker_interface.py 2>&1 | tail -5
# Record: X passed, Y failed, Z errors
```

---

## Strategy

The root fix is simple: **replace inline CREATE TABLE statements in test files
with calls to `init_test_db()` from `tests/conftest.py`.** This function already
exists and creates tables from the registry, so schema drift is impossible.

There are 29 test files with inline DDL. Not all are failing — only those whose
hand-written DDL drifted from the registry. But ALL of them are ticking time bombs.
Fix them all in one pass.

**The pattern for each file:**

BEFORE (broken — schema drifts):
```python
conn.execute("""CREATE TABLE shadow_trades (
    trade_id TEXT PRIMARY KEY, ticker TEXT, status TEXT, ...
)""")
```

AFTER (uses registry — always correct):
```python
from tests.conftest import init_test_db
init_test_db(db_path, ["shadow_trades", "recommendations"])
```

Some tests create ALL tables, others only need specific ones. Use the minimal
set needed for each test to keep tests fast.

---

## Task 1: Fix `test_repo_structure.py` regex false positive

**Problem:** `test_every_new_table_in_render_migrate` regex matches `CREATE TABLE`
in docstrings and comments (e.g., `postgres.py` docstring), not just actual DDL.

**File:** `tests/test_repo_structure.py`

**Fix:** Add a filter to skip comment lines and docstrings. The regex at line 96
scans every `.py` file in `src/` for `CREATE TABLE IF NOT EXISTS`. Add a guard:

```python
# Skip lines that are comments or inside docstrings
stripped = line.strip()
if stripped.startswith("#") or stripped.startswith('"""') or stripped.startswith("'''"):
    continue
if stripped.startswith('"') or stripped.startswith("'"):
    continue
```

Place this BEFORE the regex match at line 96.

**Also fix:** `test_no_create_table_in_source` (line 141) — apply the same
docstring/comment filter so it doesn't flag registry.py's internal docstrings.

**Test:** Run `python -m pytest tests/test_repo_structure.py -v` — all should pass.

---

## Task 2: Migrate 29 test files from inline DDL to init_test_db()

**This is the bulk of the work.** For each file below:

1. Find all `CREATE TABLE` blocks
2. Identify which tables are being created
3. Replace with `from tests.conftest import init_test_db` + `init_test_db(db_path, [table_list])`
4. Remove the inline DDL
5. Verify the test still passes

**Files to migrate (29 total):**

```
tests/test_action_reminders.py
tests/test_activity_log.py
tests/test_activity_logger.py
tests/test_auditor.py
tests/test_bracket_monitor.py
tests/test_command_queue.py
tests/test_config_tech_debt.py
tests/test_council_aggregation.py
tests/test_data_collectors.py
tests/test_data_pipeline_robustness.py
tests/test_db_migration.py
tests/test_earnings_signals.py
tests/test_event_risk_score.py
tests/test_expanded_notifications.py
tests/test_hshs_live.py
tests/test_ingestion_gate.py
tests/test_leakage_detector.py
tests/test_local_api_routes.py
tests/test_local_routes.py
tests/test_model_monitor.py
tests/test_premarket.py
tests/test_production_sweep.py
tests/test_render_sync.py
tests/test_risk_governor.py
tests/test_schema.py
tests/test_schema_generators.py
tests/test_simulation_engine.py
tests/test_trading_logic_fixes.py
tests/test_training_pipeline_safety.py
tests/test_versioning.py
```

**IMPORTANT NOTES:**

- `tests/test_schema.py` and `tests/test_schema_generators.py` may legitimately
  test CREATE TABLE generation — these are testing the schema system itself. Leave
  the DDL if it's the SUBJECT of the test, not the SETUP.
- `tests/test_repo_structure.py` has DDL in test assertions (checking that DDL
  only exists in registry) — leave these as-is.
- `tests/test_render_sync.py` may need DDL for sync testing — use judgment.
- `tests/test_db_migration.py` tests migration itself — may need both old and new DDL.

For each file, the minimal pattern is:

```python
import tempfile, os
from tests.conftest import init_test_db

@pytest.fixture
def db_path(tmp_path):
    path = str(tmp_path / "test.db")
    init_test_db(path, ["shadow_trades", "recommendations", "training_examples"])
    return path
```

Then pass `db_path` to every test function that needs a database.

---

## Task 3: Fix test_council.py fixture — missing columns

**Problem:** Council test fixture inserts into `shadow_trades` without all
required NOT NULL columns (specifically `updated_at`).

**File:** `tests/test_council.py`

The fixture already uses `init_test_db` (good). The problem is the INSERT
statements are missing columns that the registry defines as NOT NULL.

**Fix:** Find all INSERT INTO shadow_trades and ensure they include every
NOT NULL column. Check the registry:

```bash
python3 -c "
from src.schema.registry import TABLES
t = TABLES['shadow_trades']
for c in t.columns:
    if not c.nullable and c.default is None:
        print(f'  {c.name} ({c.type}) — NOT NULL, no default')
"
```

Add any missing columns to the INSERT statements in the test fixture.

---

## Task 4: Add schema_db fixture to conftest.py

**Problem:** Many tests create their own temp DB with different patterns
(tempfile, tmp_path, module-level globals). Standardize.

**File:** `tests/conftest.py`

Add a reusable pytest fixture:

```python
@pytest.fixture
def schema_db(tmp_path):
    """Temp database with ALL schema tables created.

    Use this when a test needs database access but you don't want
    to specify individual tables. Slightly slower than init_test_db
    with a specific table list, but guaranteed to have everything.
    """
    path = str(tmp_path / "test.db")
    init_test_db(path)  # Creates ALL tables
    return path
```

Tests that need the full schema can use `schema_db` instead of
manually calling `init_test_db`. This is optional — existing tests
that already work with specific table lists don't need to change.

---

## Task 5: Add postgres.py docstring (if still missing)

**Problem:** Audit flagged `src/schema/postgres.py` missing standard docstring.

**File:** `src/schema/postgres.py`

**Check first** — the file may already have the docstring (I see it exists
in the current code). If it's there and matches the 5-field standard format,
skip this task. If not, add:

```python
"""Postgres schema operations driven by the registry.

Called by: scripts/render_migrate.py
Calls: src.schema.registry
Owns tables: none (generates DDL for Postgres mirrors)
Config keys: none
Tests: tests/test_repo_structure.py
"""
```

---

## Task 6: Mock yfinance/alpaca imports in affected tests

**Problem:** 22 tests fail because `yfinance` can't be imported, 5 because
`alpaca-py` can't be imported. These are external dependencies that aren't
always available in CI environments.

**File:** `tests/conftest.py` — the mock infrastructure already exists (see
the Alpaca mock section). Verify it's working:

```python
# conftest.py should already have something like:
if "alpaca" not in sys.modules:
    # Create mock alpaca modules
    ...
```

For yfinance, add a similar mock at the top of conftest.py:

```python
# Mock yfinance if not installed
if "yfinance" not in sys.modules:
    yf_mock = types.ModuleType("yfinance")
    yf_mock.download = MagicMock(return_value=None)
    yf_mock.Ticker = MagicMock
    sys.modules["yfinance"] = yf_mock
```

**IMPORTANT:** This should only mock the import, not the behavior. Tests
that actually test yfinance functionality (like `test_ingestion.py`) should
be skipped with `@pytest.mark.skipif(not HAS_YFINANCE, reason="yfinance not installed")`.

Check which of the 22 failing tests actually TEST yfinance behavior vs
just happen to import a module that transitively imports yfinance.

---

## Verification

```bash
# Run full test suite
python -m pytest tests/ -x -q --ignore=tests/test_ingestion.py --ignore=tests/test_broker_interface.py

# Target: 0 failures, 0 errors (excluding intentionally skipped)
# The pass count should INCREASE from 1212 (baseline) since previously
# failing tests are now fixed

# Run repo structure tests specifically
python -m pytest tests/test_repo_structure.py -v

# Build frontend (no changes expected, but verify)
cd frontend && npm run build && cd ..
```

---

## Commit Strategy

```bash
# Commit 1: conftest improvements + repo_structure regex fix
git add tests/conftest.py tests/test_repo_structure.py
git commit -m "fix: add schema_db fixture + fix repo_structure regex false positives

Add schema_db pytest fixture for full-schema temp databases.
Fix test_every_new_table_in_render_migrate regex to skip docstrings.
Mock yfinance import in conftest for CI environments."

# Commit 2: migrate inline DDL (bulk)
git add tests/
git commit -m "fix: migrate 29 test files from inline DDL to init_test_db()

Replace hand-written CREATE TABLE statements with calls to
init_test_db() from conftest.py. This prevents schema drift —
tests always use the registry-defined schema.

Fixes 62 test failures identified in audit-2026-04-09."

# Push
git push origin fix/test-cleanup
```

Do NOT merge to main. Push to branch only.
