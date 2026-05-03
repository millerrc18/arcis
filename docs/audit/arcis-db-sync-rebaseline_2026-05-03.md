# SQLite <-> Postgres Sync Rebaseline Report

**Generated:** 2026-05-03T08:18:14-04:00
**SQLite:** `C:\arcis\data\ai_research_desk.sqlite3`
**Postgres:** `dpg-d72kjk8gjchc7386lsqg-a.virginia-postgres.render.com/halcyon_zjdk`
**Registry tables:** 69 total / 60 synced / 9 local-only

## Missing Tables

| Category | Tables |
| --- | --- |
| Synced registry missing in SQLite | None |
| Synced registry missing in Postgres | None |
| SQLite tables not in registry | sqlite_sequence |
| Postgres tables not in registry | None |

## Missing Columns

_None._

## Type Mismatches

| Table | Column | Target | Registry | Actual |
| --- | --- | --- | --- | --- |
| shadow_trades | actual_shares | postgres | REAL | integer |
| shadow_trades | planned_shares | postgres | REAL | integer |

## PK / Conflict Target Mismatches

| Table | Kind | Expected | Actual |
| --- | --- | --- | --- |
| training_examples | postgres_pk | example_id | id |
| api_costs | postgres_pk | cost_id | id |
| canary_evaluations | postgres_pk | eval_id | id |
| macro_snapshots | postgres_conflict_target | series_id | id |
| setup_signals | postgres_pk | signal_id | id |
| quality_drift_metrics | postgres_pk | metric_id | id |

## Local-Only Tables

| Category | Tables |
| --- | --- |
| Registry local-only present in SQLite | bracket_health, config_overrides, daily_ib_health, data_freshness, model_evaluations, operator_view_state, preference_pairs, sync_state, system_metrics |
| Registry local-only present in Postgres | config_overrides, sync_state |
| Registry local-only missing in SQLite | None |
| SQLite-only unregistered | sqlite_sequence |

## Sync Smoke

This section comes from one live `run_sync_cycle()` invocation after the read-only tri-diff.

| Metric | Value |
| --- | --- |
| Smoke scope | tri-diff risk tables |
| Tables considered | api_costs, canary_evaluations, macro_snapshots, quality_drift_metrics, setup_signals, training_examples, shadow_trades |
| First failing table | None |
| First error | None |
| Errors | 0 |
| Tables synced | 1 |
| Tables with row activity | macro_snapshots=31 |
| create_all_tables added | None |
| ensure_columns added | None |

### Per-Table Errors

_None._
