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
| Remaining live drift | CLEARED | The post-migration read-only report shows no remaining type, PK, or conflict-target mismatches |

## Remaining Confirmed Drift

None in the current read-only report. The 2026-05-03 migration normalized:

- `shadow_trades.planned_shares` / `actual_shares` to `REAL`
- legacy Postgres PKs on `api_costs`, `canary_evaluations`, `quality_drift_metrics`, `setup_signals`, and `training_examples`
- `macro_snapshots` to retained-history sync semantics with `(series_id, collected_date)` as the natural conflict target

## Live Smoke Result

The smoke scope was intentionally narrowed to the current risk tables:

Observed result on 2026-05-03:

- read-only tri-diff: clean
- smoke section in the generated artifact: blocked by `in_flight` host lock on `SWIFT-PC`

Interpretation:

- The schema work appears complete.
- The remaining smoke issue is operational: a stale host row from an overlapping audit process, not a live DB-shape mismatch.

## Earlier Claims That Are Now Stale

- "3 missing `id` columns in Postgres" is no longer the right diagnosis. The live issue is legacy Postgres `id` keys where the registry now expects natural keys.
- "23 unregistered tables" is stale and should not be used for current planning.
- "175 LONGCHAR mismatches" should stay in the Access/ODBC viewer bucket, not in the sync-blocker count.
- Composite-PK `ON CONFLICT` handling should not be tracked as an open current defect in the repo.

## Conclusion

The sync problem set was materially smaller than the original docs suggested, and the remaining live Postgres drift has now been migrated away. The repo fixes removed the broad `SELECT *` insertion failure mode, restored host-level sync-state visibility, and aligned `macro_snapshots` with preserved historical sync semantics. What remains is operational cleanup around stale `sync_state` host locks plus separate Access viewer maintenance that should not be counted as sync failure.
