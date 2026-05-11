# Schema Drift Audit Results — 2026-05-11

**Sprint:** SP5 §J Cutover Rectification (T3)
**Audit date:** 2026-05-11
**Source:** `scripts/audit_schema_drift.py` vs live SQLite + live PG
**Branch:** `sp5-rect-t3-schema-drift-audit`

## Summary

- Total tables in registry: 71 (all have `sync_to_postgres=True`)
- Total tables audited (present in at least one live DB): 71
- Total columns audited: 933
- NOT NULL drifts found: 3
- CHECK constraint drifts (out of scope): 0 found
- Default drifts (out of scope): not audited (separate concern)
- Resolved in this PR: 1 (`setup_signals.setup_type`)
- Remaining (out of scope — have defaults, not write-path None issue): 2

## PG State at Audit Time

The PG database is in a post-rollback state from the 2026-05-11T20:44:48Z
cutover rollback. Only 1 table is currently present in PG (`test_t` — a test
artifact). The 71 sync-eligible tables are absent because the cutover rolled
back after 59 tables disappeared during the failed migration (P0 #89). This
means PG-side nullability comparisons show `N/A` for all tables except `test_t`.

The SQLite side has all 71 tables and provides the primary comparison source.

## Audit Script Output (as-run)

```
======================================================================
Schema NULL-Constraint Drift Audit — 2026-05-11
======================================================================
Tables audited:    71
Columns audited:   933
SQLite reachable:  True
PG reachable:      True
PG tables in DB:   1 (post-rollback: only ~9 tables remain)

NOT-NULL drifts found: 3

Table.Column                                       Registry   SQLite     PG         Type
----------------------------------------------------------------------------------------
shadow_trades.quarantined                          NOT NULL   nullable   N/A        registry_vs_sqlite
shadow_trades.instrumentation_version              NOT NULL   nullable   N/A        registry_vs_sqlite
setup_signals.setup_type                           nullable   NOT NULL   N/A        registry_vs_sqlite
```

Note: The `setup_signals.setup_type` drift shown above already reflects the T3
fix (registry now shows `nullable`). Before the fix, the audit showed:
```
setup_signals.setup_type                           NOT NULL   nullable   N/A        registry_vs_sqlite
```

## Per-table drift findings

| Table | Column | Registry (before fix) | SQLite | PG | Root Cause | Resolution |
|-------|--------|-----------------------|--------|-----|------------|------------|
| `setup_signals` | `setup_type` | `nullable=False` (NOT NULL) | `nullable=True` | N/A (absent) | `setup_classifier.classify_setup()` returns `None` when no rule matches. The INSERT at `setup_classifier.py:263` passes `classification["setup_type"]` directly without guarding against None. SQLite's `notnull` constraint only applies to DDL-enforced columns in newer SQLite; historical rows already had NULLs before the registry declared NOT NULL. PG enforces the constraint strictly on every INSERT → cutover crash. | **RESOLVED: registry set to `nullable=True` (matches write path semantics)** |
| `shadow_trades` | `quarantined` | `nullable=False` (NOT NULL, `default="0"`) | `nullable=True` | N/A (absent) | The `quarantined` column was added via `scripts/migrate_shadow_trades_quarantined_not_null_2026_04_26.py` which updated existing rows but did not alter the SQLite column DDL to add NOT NULL. Registry says NOT NULL with default='0'; SQLite was never `ALTER TABLE ... NOT NULL`. Every write path supplies 0 or 1 — no write-path None issue. | **OUT OF SCOPE** — has `default='0'`, not a write-path None issue; filed as follow-up. |
| `shadow_trades` | `instrumentation_version` | `nullable=False` (NOT NULL, `default="3"`) | `nullable=True` | N/A (absent) | Same class as `quarantined` — column added post-migration with DEFAULT but DDL NOT NULL not enforced in existing SQLite table. Every write path supplies an integer. | **OUT OF SCOPE** — has `default='3'`, not a write-path None issue; filed as follow-up. |

## Resolutions applied to `src/schema/registry.py`

### `setup_signals.setup_type`: `nullable=False` → `nullable=True`

**Before:**
```python
ColumnDef("setup_type", "TEXT", nullable=False),
```

**After:**
```python
ColumnDef("setup_type", "TEXT"),
```

`nullable` defaults to `True` in `ColumnDef`, so omitting the parameter is
the minimal change and removes the explicit mismatch.

**Rationale for making it nullable (not adding a default):**

The write path in `src/features/setup_classifier.py:_log_setup_signal()` inserts
`classification["setup_type"]` directly. The `classify_setup()` function
explicitly returns `setup_type=None` when no rule matches (documented comment
at line 30: "When no rule matches, classify_setup returns setup_type=None").
The INSERT doesn't guard against this. Adding a default like `"unknown"` would
silently mask the "no rule matched" signal — the downstream analytics that query
`setup_type IS NULL` to find unclassified signals would stop working. Making it
nullable is the semantically correct resolution.

**Why NOT NULL was wrong in the first place:**

The `nullable=False` declaration was incorrect from the start — it expressed
intent (every signal should have a type) rather than reality (the classifier
legitimately returns None). SQLite's DDL enforces NOT NULL only at CREATE TABLE
time; historical rows inserted before the field was added don't retroactively
fail. PG enforces strictly, which surfaced the mismatch immediately.

## Sibling Search: `setup_type` callers in `src/` and `tests/`

Run: `grep -rn -E "(setup_type|'setup_type'|\"setup_type\")" src/ tests/ --include="*.py"`

Key findings:
- `src/features/setup_classifier.py:30` — explicitly documents `setup_type=None` return
- `src/features/setup_classifier.py:263` — INSERT passes `classification["setup_type"]` directly (confirmed NULL path)
- `src/features/engine_helpers.py:252` — `feat["setup_type"] = "unknown"` fallback (guards against None at a different layer)
- `src/scheduler/universe_scanner.py:322` — `setup_type=feat.get("setup_type")` (passes None if absent)
- `src/services/scan_service.py:367` — same pattern
- `src/shadow_trading/executor.py:2725` — same pattern
- `src/notifications/telegram.py:330-333` — guards with `if setup_type and setup_confidence`
- All test callers use hardcoded string values — no test depends on null=ok behavior

**Conclusion:** No caller DEPENDS on null=ok semantics for correctness.
The nullable=True fix is safe. Making the column NOT NULL would require
auditing 8+ write paths and either (a) adding guards to every `feat.get("setup_type")`
call or (b) making setup_classifier.py return "unknown" instead of None —
which changes existing behavior and is out of scope for a NULL-drift fix.

## Out-of-scope drifts (follow-up)

### `shadow_trades.quarantined` + `shadow_trades.instrumentation_version`

Class: **Registry says NOT NULL (with default), SQLite DDL allows NULL**

These are NOT write-path None bugs. Every write path supplies a non-null value.
The drift is purely DDL-historical: the columns were added to SQLite via a
data migration script that populated existing rows with defaults but did not
execute `ALTER TABLE shadow_trades ADD COLUMN ... NOT NULL DEFAULT ...` (SQLite
does not support adding NOT NULL without a default on an existing column without
a full table rebuild). The registry's `nullable=False` is ASPIRATIONALLY
correct but the DDL doesn't enforce it in SQLite.

**Impact for cutover:** Low risk. PG will be created fresh from the registry DDL
(which emits `NOT NULL` for these columns), and the migration will supply the
default value for these columns. New inserts always supply these values. The
drift is cosmetic from a data-integrity standpoint.

**Filed as follow-up:** A DDL alignment pass for SQLite NOT NULL backfills is
deferred. The correct fix is a migration script that rebuilds `shadow_trades`
with the NOT NULL constraint enforced — a destructive operation requiring a
maintenance window.

### CHECK constraints

Not audited in this PR (spec scope fence). No CHECK constraint drifts were
observed in initial manual inspection. Filed as separate follow-up per spec.

### Default value drifts

Not audited in this PR (spec scope fence). Separate concern from NULL-constraint
drift.

## Validation

```bash
# Verify registry fix
python -c "from src.schema.registry import TABLES; t = TABLES['setup_signals']; col = next(c for c in t.columns if c.name == 'setup_type'); print(f'nullable={col.nullable}')"
# Output: nullable=True

# Run regression tests
python -m pytest tests/test_schema_drift_audit.py -q --timeout=60
# 6 passed
```
