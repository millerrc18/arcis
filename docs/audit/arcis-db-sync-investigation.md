# SQLite <-> PostgreSQL Sync Rebaseline Investigation

**Date:** 2026-05-03
**Scope:** current SQLite -> Postgres sync path only (`src/sync/render_sync.py`)
**Separate track:** `live_state_analysis_2026-04-20.md` and `root_cause_investigation_2026-04-21.md` remain Alpaca/reconcile incident docs, not sync root-cause counts.
**Canonical artifact:** `docs/audit/arcis-db-sync-rebaseline_2026-05-03.md`
**Verification command:** `cmd.exe /C py -3 scripts/audit_db_sync.py --sync-smoke --output docs/audit/arcis-db-sync-rebaseline_2026-05-03.md`

## Rebaseline Summary

The 2026-05-02 sync docs mixed together three different issue classes:

- real SQLite -> Postgres drift
- Access/ODBC linked-table issues
- findings that were valid before later schema and sync fixes landed

The 2026-05-03 rebaseline keeps only issues that still survive a live registry vs SQLite vs Postgres comparison.

## Current Live State

- Synced registry tables missing in SQLite: none
- Synced registry tables missing in Postgres: none
- Synced registry columns missing in Postgres: none
- Postgres tables not in the registry: none
- SQLite-only unregistered table: `sqlite_sequence`
- Registry local-only tables also present in Postgres: `config_overrides`, `sync_state`

### Remaining Live Drift

| Category | Current live drift |
| --- | --- |
| Postgres type mismatch | `shadow_trades.planned_shares` is `integer` in PG but `REAL` in the registry |
| Postgres type mismatch | `shadow_trades.actual_shares` is `integer` in PG but `REAL` in the registry |
| Legacy Postgres PK | `api_costs` still uses `id` in PG; registry expects `cost_id` |
| Legacy Postgres PK | `canary_evaluations` still uses `id` in PG; registry expects `eval_id` |
| Legacy Postgres PK | `quality_drift_metrics` still uses `id` in PG; registry expects `metric_id` |
| Legacy Postgres PK | `setup_signals` still uses `id` in PG; registry expects `signal_id` |
| Legacy Postgres PK | `training_examples` still uses `id` in PG; registry expects `example_id` |
| Legacy Postgres conflict target | `macro_snapshots` still conflicts on `id` in PG; registry expects `series_id` |

## What Is No Longer Current

These earlier claims should not be used as current sync blockers:

- The `LONGCHAR` / ODBC collapse is an Access viewer problem, not a `psycopg2` sync failure.
- The old "3 missing `id` PK columns" framing is stale. The live problem is the opposite: Postgres still has legacy `id` primary keys where the registry now expects natural keys.
- The old "23 unregistered tables" count is stale. Several tables named in that section are already registered.
- Composite-PK `ON CONFLICT` handling is no longer an open sync bug in the repo.

## Current Code State

These repo-level fixes are now in place:

- Sync column selection is filtered through the registry and live Postgres columns instead of blindly trusting `SELECT *`.
- Numeric coercion now follows registry types, so `planned_shares` is no longer coerced as an integer in sync code.
- Host sync lifecycle is now persisted in local `sync_state` via `mark_sync_in_flight()`, `mark_sync_completed()`, and `mark_sync_failed()`.
- Sync table ordering now uses FK-safe topological ordering from `generate_sync_tables()`.
- Explicit natural-key conflict targets now exist for `analyst_estimates`, `earnings_calendar`, `fed_communications`, and `short_interest`.

## Live Smoke Result

The live smoke run was narrowed to the risk tables surfaced by the tri-diff:

- `api_costs`
- `canary_evaluations`
- `macro_snapshots`
- `quality_drift_metrics`
- `setup_signals`
- `training_examples`
- `shadow_trades`

Result on 2026-05-03:

- first failing table: none
- errors: none
- schema auto-heal additions: none
- table activity observed during smoke: `macro_snapshots=31`

Interpretation:

- The current sync code no longer fails immediately on stale-column drift.
- Zero smoke errors does not mean every remaining mismatch is harmless; it means only `macro_snapshots` had live row activity during this smoke, so the other drift paths were not exercised by fresh data.

## Action List

1. Migrate Postgres `shadow_trades.planned_shares` and `shadow_trades.actual_shares` from `integer` to `REAL`.
2. Resolve legacy Postgres key drift on `api_costs`, `canary_evaluations`, `quality_drift_metrics`, `setup_signals`, and `training_examples`.
3. Align `macro_snapshots` so the live conflict target matches the registry expectation of `series_id`.
4. Leave `config_overrides` and `sync_state` out of the sync severity count; document them as local-only tables that also exist in Postgres for operational reasons.
5. Fix quoted numeric defaults in `src/schema/postgres.py`, but keep that separate from the current sync-breaker count.
6. Handle Access linked-table refresh and relinking as a separate viewer-maintenance task, not a sync remediation step.

## Operational Note

An interrupted full-cycle smoke left the host row `SWIFT-PC` marked `in_progress` in local `sync_state`. After confirming the watch loop was no longer running, that stale row was cleared with `mark_sync_failed()` and the targeted smoke completed normally. That is an operational cleanup case, not evidence of current schema drift.
