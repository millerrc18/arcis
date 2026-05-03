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

The read-only report generated after the 2026-05-03 Postgres migration shows no
remaining synced-table type mismatches and no remaining PK / conflict-target
mismatches.

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
- Explicit natural-key conflict targets now exist for `analyst_estimates`, `earnings_calendar`, `fed_communications`, `macro_snapshots`, and `short_interest`.
- `macro_snapshots` now syncs as retained history with `conflict_col="series_id, collected_date"` instead of latest-only replacement semantics.

## Live Smoke Result

The post-migration report at `docs/audit/arcis-db-sync-rebaseline_2026-05-03.md`
shows:

- no synced missing tables
- no synced missing columns
- no type mismatches
- no PK / conflict-target mismatches

The smoke section in that artifact is not a schema failure. It was blocked by a
stale `SWIFT-PC` host row in local `sync_state` left by an overlapping audit
process.

Interpretation:

- The schema drift investigation is effectively closed.
- Any remaining `in_flight` smoke failures should be treated as operational lock
  cleanup, not as evidence of SQLite -> Postgres drift.

## Action List

1. Rerun one clean smoke or normal watch-loop sync cycle after confirming no stale `audit_db_sync.py` process is holding the `SWIFT-PC` host row.
2. Leave `config_overrides` and `sync_state` out of the sync severity count; they are local-only tables that also exist in Postgres for operational reasons.
3. Fix quoted numeric defaults in `src/schema/postgres.py`, but keep that separate from the now-resolved live sync-drift incident.
4. Handle Access linked-table refresh and relinking as a separate viewer-maintenance task, not a sync remediation step.

## Operational Note

An interrupted full-cycle smoke left the host row `SWIFT-PC` marked `in_progress` in local `sync_state`. After confirming the watch loop was no longer running, that stale row was cleared with `mark_sync_failed()` and the targeted smoke completed normally. That is an operational cleanup case, not evidence of current schema drift.
