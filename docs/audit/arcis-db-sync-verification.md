# Verification Report: SQLite <-> PostgreSQL Sync Rebaseline

**Date:** 2026-05-03
**Purpose:** verify the current live sync state against the repo, the live SQLite database, and the live Postgres database
**Primary artifact:** `docs/audit/arcis-db-sync-rebaseline_2026-05-03.md`

## Verification Inputs

- Read-only tri-diff from `scripts/audit_db_sync.py`
- One targeted live `run_sync_cycle()` smoke over the risk tables surfaced by that tri-diff
- Current registry and sync code in `src/schema/registry.py`, `src/schema/sync_config.py`, and `src/sync/render_sync.py`
- Focused regression tests:
  - `cmd.exe /C py -3 -m pytest tests/test_render_sync.py tests/test_sync_config.py tests/test_sync_composite_pk.py tests/test_schema_generators.py`
  - Result: `81 passed in 14.11s`

## Verified Current Facts

| Area | Verdict | Notes |
| --- | --- | --- |
| Synced tables present in both databases | CONFIRMED | No synced registry tables are missing in SQLite or Postgres |
| Synced registry columns present in Postgres | CONFIRMED | No current synced-column gaps remain in PG |
| `SELECT *` stale-column insert failures | NOT REPRODUCED | Sync code now filters through registry and live PG columns before insert |
| Composite-PK conflict handling | FIXED IN REPO | FK-safe ordering and composite conflict coverage are now tested |
| Access `LONGCHAR` findings | ACCESS-ONLY | Still relevant for the viewer, not a current `psycopg2` sync blocker |
| Remaining live drift | CONFIRMED | Limited to two PG type mismatches and six PG key/conflict mismatches |

## Remaining Confirmed Drift

### Type mismatches

- `shadow_trades.planned_shares`: registry `REAL`, Postgres `integer`
- `shadow_trades.actual_shares`: registry `REAL`, Postgres `integer`

### PK / conflict mismatches

- `api_costs`: registry expects `cost_id`, Postgres PK is `id`
- `canary_evaluations`: registry expects `eval_id`, Postgres PK is `id`
- `quality_drift_metrics`: registry expects `metric_id`, Postgres PK is `id`
- `setup_signals`: registry expects `signal_id`, Postgres PK is `id`
- `training_examples`: registry expects `example_id`, Postgres PK is `id`
- `macro_snapshots`: registry expects conflict target `series_id`, Postgres still conflicts on `id`

## Live Smoke Result

The smoke scope was intentionally narrowed to the current risk tables:

- `api_costs`
- `canary_evaluations`
- `macro_snapshots`
- `quality_drift_metrics`
- `setup_signals`
- `training_examples`
- `shadow_trades`

Observed result on 2026-05-03:

- errors: none
- first failing table: none
- schema auto-heal additions from `create_all_tables()` / `ensure_columns()`: none
- row activity during smoke: `macro_snapshots=31`

Interpretation:

- The sync path no longer immediately fails on schema drift.
- The smoke only exercised one risk table with fresh rows, so dormant drift on the other six tables still needs schema cleanup or targeted table-level verification.

## Earlier Claims That Are Now Stale

- "3 missing `id` columns in Postgres" is no longer the right diagnosis. The live issue is legacy Postgres `id` keys where the registry now expects natural keys.
- "23 unregistered tables" is stale and should not be used for current planning.
- "175 LONGCHAR mismatches" should stay in the Access/ODBC viewer bucket, not in the sync-blocker count.
- Composite-PK `ON CONFLICT` handling should not be tracked as an open current defect in the repo.

## Conclusion

The sync problem set is materially smaller than the original docs suggested. The current repo fixes have removed the broad `SELECT *` insertion failure mode and restored host-level sync-state visibility. What remains is a short list of live Postgres schema mismatches that should be migrated deliberately, plus separate Access viewer cleanup that should not be counted as sync failure.
