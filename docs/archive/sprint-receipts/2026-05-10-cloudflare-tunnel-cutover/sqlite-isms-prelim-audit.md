# SQLite-isms Preliminary Audit — Modified-A Migration Scope

**Date:** 2026-05-10 (Sun evening, post-rollback)
**Status:** PRELIM grep-based heatmap. Deep audit dispatched to `arcis:design` as follow-up. This document is the design-team input artifact.

**Trigger:** The Modified-A connect_db precedence-flip attempt at 344e5e6 (later rolled back at 449dfc0) tripped on three SQLite-only downstream code paths within 2 min of going live:
1. `src/schema/sqlite.py:21` — `PRAGMA index_list(...)` against PG
2. `src/evaluation/system_validator.py:1039` — `INSERT INTO ... VALUES (?, ?, ...)` SQLite placeholders against PG
3. `src/schema/validator.py` — `SELECT name FROM sqlite_master` against PG

Production stayed on SQLite; PG holds a 1.32M-row snapshot from today's migration. The proper Modified-A migration is now SP5 §J5/§J6 scope — and it needs an audit-grounded spec.

---

## Headline numbers

| Metric | Value |
|---|---|
| Total files with any SQLite-ism | **73** |
| Total `?` placeholder occurrences in execute()/executemany() | 158 *(under-counted — many `?` calls live in multi-line SQL strings my regex missed; design team should refine)* |
| Total `INSERT OR REPLACE` / `INSERT OR IGNORE` | 21 |
| Total `PRAGMA` statements | 24 |
| Total `sqlite_master` references | 7 |
| Total `ROWID` references | 5 |
| Total `AUTOINCREMENT` references | 11 |
| `connect_db()` call sites total | 339 |
| `sqlite3` direct imports (mostly for exception types + Row factory; not all migration targets) | 114 files |

---

## SQLite-ism categories with migration approach

### 1. `?` placeholders → `%s` (HIGH VOLUME, MECHANICAL)

psycopg2 uses `%s` placeholders, not `?`. The migration approach options:

- **Option A (preferred): wrapper-level transparent rewrite.** Extend `PostgresConnectionWrapper.execute()` / `.executemany()` to regex-replace `?` → `%s` in SQL strings before passing to psycopg2. Caveats: must be careful inside string literals (`SELECT * FROM t WHERE name LIKE '?%'` shouldn't be touched). A token-aware rewrite or a leading-only-outside-quotes regex.
- **Option B: rewrite every call site.** Mechanical sed across 158+ occurrences. Higher disruption, no runtime overhead.
- **Option C: use psycopg2's `cursor.execute(sql, params)` parameter-mark feature.** psycopg2 expects `%s` regardless of how params are passed.

**Recommendation:** Option A. Single 10-line change in the wrapper unlocks hundreds of call sites for free.

**Caveat:** the design team should validate that no production SQL string actually contains a literal `?` (outside placeholder use). Quick grep estimate: low risk.

### 2. `INSERT OR REPLACE` / `INSERT OR IGNORE` → `ON CONFLICT ... DO UPDATE/DO NOTHING` (21 occurrences, 17 files)

SQLite's UPSERT syntax differs from Postgres. Conversion:
- `INSERT OR REPLACE INTO t (cols) VALUES (...)` → `INSERT INTO t (cols) VALUES (...) ON CONFLICT (pk_cols) DO UPDATE SET col1 = EXCLUDED.col1, ...`
- `INSERT OR IGNORE INTO t (cols) VALUES (...)` → `INSERT INTO t (cols) VALUES (...) ON CONFLICT (pk_cols) DO NOTHING`

This requires per-call-site knowledge of the conflict key (PK or unique constraint). Wrapper can't transparently do this.

**Top offenders** (files with INSERT OR REPLACE/IGNORE):
- `src/api/routes/system.py`
- `src/council/protocol.py`
- `src/council/value_tracker.py`
- `src/data_collection/{analyst,edgar,fed,insider,research,short_interest}_collector.py` (7 files)
- `src/data_enrichment/staleness.py`
- `src/evaluation/build_score.py`
- `src/monitoring/system_metrics.py`
- `src/notifications/platform_events.py`
- `src/platform/rigor/walkforward_runner.py`
- `src/platform/rigor/walkforward_universe.py`
- `src/simulation/engine.py`
- `src/sync/render_sync.py` (file being retired entirely; not a migration target)

**Recommendation:** per-site rewrite using the registry's primary_key / sync_conflict_col metadata to determine the conflict target. Same pattern `scripts/sqlite_to_pg_migrate.py` uses for migration INSERTs.

### 3. `PRAGMA` statements (24 occurrences, 12 files)

PRAGMA is SQLite-only. PG equivalent depends on what's being queried:
- `PRAGMA index_list(table)` → `SELECT indexname FROM pg_indexes WHERE tablename = %s`
- `PRAGMA index_info(idx)` → `SELECT * FROM pg_index ... JOIN pg_attribute ...`
- `PRAGMA table_info(table)` → `SELECT column_name, data_type FROM information_schema.columns WHERE table_name = %s`
- `PRAGMA foreign_key_list(table)` → query `information_schema.referential_constraints` + `key_column_usage`
- `PRAGMA busy_timeout` / `PRAGMA journal_mode` etc. → no-op for PG (they're SQLite-internal)

**Files with PRAGMA:**
- `src/data_collection/edgar_collector.py`
- `src/data_collection/retention.py`
- `src/evaluation/model_monitor.py`
- `src/evaluation/system_validator.py`
- `src/features/event_risk_score.py`
- `src/platform/features/cosine_similarity.py`
- `src/scheduler/watch.py` (backup API — already uses sqlite3.connect direct; OK)
- `src/schema/sqlite.py` (SQLite-only by design; uses _sqlite_only_connect helper; OK)
- `src/schema/validator.py`
- `src/sync/reconcile.py`
- `src/sync/render_sync.py` (being retired; OK)
- `src/utils/db.py` (shim's own PRAGMA — applies only to SQLite branch; OK)

**Recommendation:** Migrate the non-SQLite-only files. Files marked "OK" above are correctly SQLite-only.

### 4. `sqlite_master` references (7 occurrences, 5 files)

SQLite system table for schema introspection. PG equivalent: `information_schema.tables` or `pg_catalog.pg_class`.

Conversion: `SELECT name FROM sqlite_master WHERE type='table'` → `SELECT tablename FROM pg_catalog.pg_tables WHERE schemaname='public'` (or use `information_schema.tables`).

**Files:**
- `src/data_collection/retention.py`
- `src/evaluation/system_validator.py`
- `src/schema/validator.py` (was the CRITICAL startup blocker)
- `src/startup_checks.py`
- `src/utils/db.py` (shim — see below)

**Recommendation:** Add an `engine_aware_table_list(conn)` helper to `src/utils/db.py` that issues the right query per engine. Call sites use the helper.

### 5. `ROWID` (5 occurrences, 3 files)

SQLite's implicit per-table row ID. PG doesn't have an equivalent. Code that uses ROWID for ordering or deduplication needs a real PK reference.

**Files:** `src/schema/registry.py` (schema-definition only; OK), `src/schema/sqlite.py` (SQLite-only; OK), `src/sync/render_sync.py` (being retired; OK).

**Recommendation:** No active migration work needed — all 3 files are either SQLite-only by design or being retired.

### 6. `AUTOINCREMENT` (11 occurrences, 2 files)

SQLite-only keyword. PG uses `SERIAL` or `GENERATED AS IDENTITY`. Schema generators in `src/schema/sqlite.py` + `src/schema/postgres.py` already produce correct SQL per engine; the AUTOINCREMENT references are in TableDef declarations + the SQLite generator.

**Files:** `src/schema/registry.py`, `src/schema/sqlite.py`. Both correctly handled — registry declares the abstract concept; sqlite.py / postgres.py generate engine-appropriate DDL.

**Recommendation:** No migration work needed.

---

## Top-10 hottest files (by ism count)

| File | PRAGMA | sql_master | INS_OR | ROWID | AUTOINC | `?` | TOTAL |
|---|---|---|---|---|---|---|---|
| `src/sync/render_sync.py` | 1 | 0 | 1 | 3 | 0 | 9 | 14 |
| `src/journal/store.py` | 0 | 0 | 0 | 0 | 0 | 12 | 12 |
| `src/schema/sqlite.py` | 7 | 0 | 0 | 1 | 3 | 0 | 11 |
| `src/shadow_trading/reconcile.py` | 0 | 0 | 0 | 0 | 0 | 11 | 11 |
| `src/schema/registry.py` | 0 | 0 | 0 | 1 | 8 | 0 | 9 |
| `src/platform/promotion.py` | 0 | 0 | 0 | 0 | 0 | 8 | 8 |
| `src/council/engine.py` | 0 | 0 | 0 | 0 | 0 | 7 | 7 |
| `src/council/value_tracker.py` | 0 | 0 | 1 | 0 | 0 | 5 | 6 |
| `src/scheduler/reports.py` | 0 | 0 | 0 | 0 | 0 | 6 | 6 |
| `src/scheduler/watch.py` | 4 | 0 | 0 | 0 | 0 | 2 | 6 |

**Notes on the top-10:**
- `render_sync.py` (#1) is being **deleted entirely** in SP5 §J6 (the cloud sync layer retires). Not a migration target.
- `journal/store.py` (#2) is hot with `?` placeholders. If wrapper auto-rewrites `?` → `%s`, this file becomes trivial.
- `schema/sqlite.py` (#3) and `schema/registry.py` (#5) are **SQLite-by-design**. Not migration targets (schema generation has separate `postgres.py` sibling).
- `shadow_trading/reconcile.py` (#4) is `?`-only — would be unlocked by wrapper rewrite.
- The remaining hot files mostly have `?` placeholders that the wrapper would handle.

---

## SQLite-only-by-design files (no migration needed)

These files SHOULD continue using SQLite directly post-Modified-A — they're for SQLite backup, SQLite schema migration, or SQLite-specific introspection:

- `src/schema/sqlite.py` — engine-specific schema migration
- `src/schema/registry.py` — abstract schema authority (generates engine-aware DDL)
- `src/scheduler/watch.py` (backup API at line 1164-1165 only — uses `sqlite3.connect` direct)
- `src/training/trainer.py` (training data writer)

`render_sync.py` and `cloud_app.py` go away entirely in §J6.

---

## Migration sequencing recommendation

Spec for the design team to refine:

**Phase 0 (preparatory):** add transparent `?` → `%s` rewrite to `PostgresConnectionWrapper.execute()` / `.executemany()`. Tests on the wrapper to confirm literal `?` inside strings aren't touched. ~1 day.

**Phase 1 (UPSERT-heavy files):** 17 files with `INSERT OR REPLACE/IGNORE`. Per-site rewrite using registry conflict_col metadata. ~2-3 days.

**Phase 2 (PRAGMA / sqlite_master):** 12 + 5 = ~15 files. Add `engine_aware_*` helpers in `src/utils/db.py`. Refactor call sites to use them. ~1-2 days.

**Phase 3 (post-rewrite gate):** Run the cutover migration again. NSSM env update. Restart watch loop. Verify writes land in PG over 24h. ~1 day including observation.

**Phase 4 (retirement):** Delete `render_sync.py` + `cloud_app.py` + `schema/sqlite.py` SQLite-only generator. Collapse `cloud_routes/*` dual-mode branches to PG-only. ~1 day.

**Estimated total:** ~5-7 person-days for the SP5 §J5/§J6 dispatch.

---

## Open questions for design team

1. **`?` rewrite — wrapper-level vs explicit migration?** Wrapper-level is cheap but slightly magical. Explicit rewrite is verbose but auditable. Operator preference matters.

2. **Tests fixture migration timing — pre or post Phase 1-3?** The 4995-test suite uses SQLite fixtures throughout (`tests/conftest.py::init_test_db`). When does that get rewritten?

3. **Bind-mount cleanup discipline** (from `reference_docker_bind_mount_persistence` memory) — Docker PG password rotation requires manual `rm -rf` of `pg-data` dir; should be encoded in the Wave-4-redo runbook.

4. **Trading interruption window for Phase 3 watch loop restart** — best to do during a non-market-hours window. Saturday morning preferred over weekday market-open risk.

5. **Composite-PK ON CONFLICT** (fixed at bc6043f for the migration script) — does the wrapper need a similar helper for production `ON CONFLICT (pk_cols)` SQL builders?

---

## Tools deferred to design team

- **`gitleaks`** / **`trufflehog`** for the secrets-history audit (SP5 §J1 — separate concern from SQLite-isms but on the same SP5 sprint)
- **`vulture`** / **`deadcode`** for the dead-code audit (SP5 §J5)
- **`sqlfluff`** or **psycopg2's `quote_ident`** for SQL parsing if needed
- Optional: build a small static analyzer (`src/utils/sqlite_ism_scanner.py`) that catalogs every `?` placeholder in execute() calls + their surrounding context. Useful for ongoing regression-locks (CI gate: "no new SQLite-isms in non-SQLite-only files").

---

## Data file: detailed heatmap CSV

For the full per-file breakdown, see the grep output captured in the chat session log. Re-runnable via:

```python
import re
from pathlib import Path
patterns = {
    'PRAGMA': re.compile(r'PRAGMA\s+\w+', re.I),
    'sqlite_master': re.compile(r'sqlite_master', re.I),
    'INSERT_OR': re.compile(r'INSERT OR (REPLACE|IGNORE)', re.I),
    'ROWID': re.compile(r'\bROWID\b', re.I),
    'AUTOINCREMENT': re.compile(r'AUTOINCREMENT', re.I),
    'q_placeholder': re.compile(r'(execute|executemany)\([^)]*\?'),
}
for path in Path('src').rglob('*.py'):
    text = path.read_text(encoding='utf-8', errors='ignore')
    hits = {k: len(p.findall(text)) for k, p in patterns.items()}
    if any(v > 0 for v in hits.values()):
        print(path, hits)
```

---

This document is preliminary. The design team's deeper analysis will refine these numbers, surface edge cases my grep missed, and produce the actionable SP5 §J5/§J6 spec.
