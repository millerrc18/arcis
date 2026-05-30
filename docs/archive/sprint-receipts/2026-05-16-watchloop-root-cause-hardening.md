# Watch Loop Root-Cause Hardening - 2026-05-16

## Scope

This note covers the watch-loop failure class observed after 4:00 PM ET on
2026-05-15. The fix is intentionally app-layer hardening. Do not reset the
database for this class unless a separate integrity check proves physical
corruption or unrecoverable schema loss.

## Observed Symptoms After 4 PM On 2026-05-15

- Attribution resolution hit a PostgreSQL dialect error shaped like
  `date(text, unknown)` from SQLite date-modifier SQL.
- Stress-test result persistence hit PostgreSQL syntax failure on
  `INSERT OR REPLACE`.
- The training pipeline reached the fine-tuning handoff with zero holdout rows,
  then remained vulnerable to Windows subprocess decode failures.
- Post-close reconciliation reported stale rows as failures even when the
  reconciler had auto-closed them.
- Audit output did not deterministically surface high unknown-exit ratios,
  missing bracket coverage, stale reconciliations, drawdown breach, or model
  win-rate failure.
- YAML email-password warnings repeated even though `.env` / `EMAIL_PASSWORD`
  is the supported secret source.
- Historical yfinance gaps in stress scenarios appeared as noisy failures
  instead of structured caveats.

## Root Causes

- PG cutover exposed raw SQLiteisms in PG-routed paths:
  `DATE(scan_timestamp, '+8 days')` and `INSERT OR REPLACE`.
- The training scheduler checked only example volume and age; it did not prove
  the temporal split could produce a validation holdout before scheduling GPU
  work.
- Promotion activation was fail-open: canary failures could be non-blocking and
  the model could become active before the promotion gate result was known.
- Reconciliation output mixed auto-resolved stale rows with unresolved stale
  debt, forcing operators to read resolved rows as active failures.
- Exit-reason integrity relied on call sites rather than the terminal journal
  writer.
- Deterministic audit checks were missing for data-quality/risk facts that can
  be proven without an LLM.
- Config warnings and expected historical-data gaps were emitted as repeated
  operational noise instead of deduplicated warnings or structured caveats.

## Code Rectification

- `src/attribution/logger.py`
  - Computes the eight-day attribution cutoff in Python and binds it as a
    timestamp parameter.
  - Adds regression coverage that recent rows stay pending while elapsed rows
    resolve.
- `scripts/stress_test.py`
  - Uses `engine_aware_upsert` into `stress_test_results`.
  - Uses a deterministic UUID5 `result_id` keyed by scenario/start/end/model.
  - Adds `market_data_gaps` and `caveats` for expected yfinance historical gaps.
- `src/training/trainer.py`
  - Adds a pure `get_training_split_viability()` helper.
  - Blocks `should_train()` and `run_fine_tune()` when the 5-day holdout is
    empty.
  - Forces UTF-8 subprocess env and captured-output encoding.
  - Keeps new models evaluation-only until holdout, canary, and promotion gate
    all pass.
- `src/shadow_trading/reconcile.py` and `src/scheduler/overnight.py`
  - Return/report `resolved_stale` separately from `unresolved_stale`.
  - Treat auto-closed stale rows as resolved in the nightly status line.
- `src/journal/store.py`
  - Coerces terminal `close_shadow_trade()` exit reasons through the controlled
    vocabulary before writing.
- `src/evaluation/auditor.py` and `src/risk/governor.py`
  - Add deterministic audit prechecks for unknown exits, bracket coverage,
    stale reconciliation, drawdown, and model win rate.
  - Suppress new entries when the latest recent deterministic audit is critical,
    without writing the operator-only kill switch.
- `src/email/notifier.py` and `config/settings.example.yaml`
  - Emit the YAML password warning once per process.
  - Keep the YAML password field empty; use `EMAIL_PASSWORD` in `.env`.

## Data Rectification Rules

- Repair `unknown` exit reasons only when broker/order evidence proves the
  terminal condition.
- Leave ambiguous rows as manual-review data-quality debt.
- Do not mass rewrite unknown exits to target/stop/timeout based on P&L alone.
- Do not reset the DB for PG dialect errors, empty holdout, stale reconciliation
  reporting, config-warning noise, or expected yfinance historical gaps.

## Validation Commands

Run targeted compile and tests before PR submission:

```bash
python3 -m py_compile \
  src/evaluation/auditor.py src/risk/governor.py src/training/trainer.py \
  src/attribution/logger.py scripts/stress_test.py src/scheduler/overnight.py \
  src/shadow_trading/reconcile.py src/journal/store.py src/email/notifier.py \
  src/utils/db.py

python3 -m pytest \
  tests/attribution/test_resolver.py \
  tests/test_stress_test_methodology.py \
  tests/test_trainer_holdout_alert.py \
  tests/test_auditor.py \
  tests/email/test_notifier.py \
  tests/test_reconcile.py \
  tests/scheduler/test_overnight_encoding.py \
  tests/test_journal_store_schema_filter.py \
  tests/test_db_engine_aware_upsert.py
```

PG smoke focus:

- Attribution resolver with `ARCIS_PG_CUTOVER_ENABLED=1`: elapsed pending rows
  resolve; fresh rows remain pending; no `date(text, unknown)` error.
- Stress-test persistence with `ARCIS_PG_CUTOVER_ENABLED=1`: one scenario can be
  stored twice without duplicate rows or `INSERT OR REPLACE` syntax errors.
- Training export/skip: empty holdout emits one structured alert and no training
  subprocess starts.
- Post-close reconciliation: auto-closed stale rows appear as resolved stale;
  unresolved stale rows remain failures.

## Post-Deploy Monitoring Checklist

- Watch one evening/post-close cycle for absence of:
  - `date(text, unknown)`
  - `INSERT OR REPLACE`
  - `UnicodeDecodeError`
  - reconciliation failure where all stale rows were auto-closed
- Confirm Telegram/email receives at most one empty-holdout alert per export
  run and one YAML-password warning per process.
- Confirm latest audit `full_report.deterministic_prechecks` is populated.
- If deterministic audit is critical, confirm new entries are rejected by the
  risk governor while exits/reconciliation continue.
- Confirm model activation does not occur unless holdout, canary, and promotion
  gate all pass.
