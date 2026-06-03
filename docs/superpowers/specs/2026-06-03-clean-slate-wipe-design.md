# `scripts/clean_slate_wipe.py` — Design Spec (W21 Capstone #95) — REV 2

> **Revision note (2026-06-03, post-feasibility+DA review):** Surgical hardening of REV 1. Changes: (CR-1) corrected `len(registry.TABLES)` ~71→**80** everywhere; ruled `daily_ib_health`→WIPE so WIPE∪KEEP is exhaustive (53+27=80, disjoint). (CR-2) added Phase-0 **live-schema + live-FK reconciliation** against the actual prod DSN (registry guard is necessary-NOT-sufficient). (CR-3) verify-restore now uses a **fresh ephemeral scratch DB**, never the shared 5434 test DB. (MAJ-1) CREATE-count shortfall→hard REFUSE. (MAJ-2) watch-loop **re-checked inside the TRUNCATE boundary** + NSSM-stopped required; **open broker positions = hard ABORT** by default. (MAJ-3) full equity-input enumeration + a **`--verify-config` loop** asserting config/Ollama reset. (MAJ-4) **already-clean short-circuit** + empty-state backup tagging. Minors folded: removed `@safety_window('market_hours')` (key does not exist → would ValueError), `--emergency` is a reserved no-op flag, prod-touch-on-read documented, interrupted-run forensic marker + test added.

## 1. Overview

`scripts/clean_slate_wipe.py` is the W21 capstone: a single audited, idempotent, **dry-run-by-default**, ProdGuard-gated, backup-first destructive script that resets the Arcis platform to a clean-slate state against **PROD PG 5433** so the platform restarts as a proven-sound stable release (sim STABLE gate GREEN — #132 / v0.36.84).

What it does (auto): reconciles the live schema against the registry, backs up prod PG, verify-restores into a **fresh ephemeral scratch DB** (created+dropped on the 5434 server — NOT the shared test DB), single-transaction TRUNCATEs the trade/learning table set (preserving market-data tables), retires (archives) the legacy SQLite trade/learning residue, and emits a structured audit trail + forensic markers.

What it does NOT do (emits operator runbook instead): edit prod YAML config (`llm.model`, `risk.starting_capital`, `post_bootcamp`), pull the Ollama base tag at the OS level, flatten the Alpaca broker, or execute the wipe without `--confirm`.

**Capital resets emergently, not by edit (paper path).** Realized live equity is computed as `risk.starting_capital + SUM(shadow_trades.pnl_dollars)` over closed, non-quarantined trades (governor.py:393-399 / drawdown 336-352). TRUNCATE-ing `shadow_trades` zeroes the PnL term; the config step only *confirms* `risk.starting_capital=100000`. The script never touches `live_trading.starting_capital` ($100 live account). **Exception (drives a hard gate):** when the live broker is IB, `get_current_equity` returns the broker's reported `acct.equity` (governor.py:374-382), which reflects OPEN POSITIONS and is independent of the DB — see §3.6 and the broker-flat hard gate (§5.4).

This spec is for the SCRIPT. EXECUTION stays gated on operator GO + a clean prod window.

### Goals
1. Dry-run default: print WIPE list + **LIVE row-count deltas** + reset actions; no mutation unless `--confirm`.
2. Explicit reviewed `WIPE_TABLES`/`KEEP_TABLES` classification (exhaustive over the **80** registered tables) + a CI completeness guard.
3. **Live-schema reconciliation:** abort unless the live prod public schema == `set(registry.TABLES)` AND live FK edges touching WIPE == the 6 proven edges (authoritative gate; registry guard alone is insufficient under drift).
4. ProdGuard: prod-signature DSN refused without `ARCIS_ALLOW_PROD_PG=1` AND `confirm=True`.
5. Backup-first + verify-restore-into-ephemeral-DB-or-REFUSE; CREATE-count shortfall is a hard REFUSE.
6. Single-transaction `TRUNCATE <wipe> RESTART IDENTITY CASCADE`, **re-checking watch-loop-stopped immediately before commit**; print row delta.
7. Model reset (DB layer) + emitted instructions for config/Ollama layers + a `--verify-config` loop that READS and ASSERTS the post-reset config/Ollama state.
8. Retire legacy SQLite residue (archive-fsync-then-empty, never blind-delete).
9. Hard preconditions: watch-loop NSSM-stopped (re-checked) and **broker-flat** (open positions ABORT by default).
10. Idempotent (incl. already-clean short-circuit) + structured audit events + forensic markers for every destructive action.

### Non-Goals (explicit out-of-scope)
- Running the wipe (spec/script only — execution is operator-gated).
- Alpaca/IB flatten (broker step) — the script ABORTS on open positions; it does not place orders.
- The Ollama-tag OS step (operator/runbook); the script only READS the loaded tag to verify.
- Auto-editing prod YAML.
- DROP SCHEMA or any DROP of a registered table (TRUNCATE only; the only CREATE/DROP is of the ephemeral verify DB).
- An RTH market-hours safety_window (the config key does not exist; filed as follow-up — see §5.3 + DD-WINDOW).
- #132 follow-ups.

## 2. Architecture

### 2.1 New & touched files

| File | New? | Role |
|---|---|---|
| `scripts/clean_slate_wipe.py` | NEW | Main script: CLI, decorated entry point, phase orchestration, banner, forensic markers. |
| `scripts/_clean_slate/__init__.py` | NEW | Package marker for helper modules. |
| `scripts/_clean_slate/classification.py` | NEW | `WIPE_TABLES`, `KEEP_TABLES`, `EXPECTED_FK_EDGES`, `UNREGISTERED_NOTES`, `assert_partition_complete()`. Single human-reviewed source of truth. |
| `scripts/_clean_slate/live_schema.py` | NEW | `reconcile_live_schema(dsn)` + `reconcile_live_fk_edges(dsn)`: query `information_schema.tables` / `pg_constraint`; abort on any drift. |
| `scripts/_clean_slate/backup.py` | NEW | `pg_dump` via docker exec → docker cp → verify (size/SHA/CREATE-count) → create EPHEMERAL scratch DB → restore → count-compare → DROP ephemeral. |
| `scripts/_clean_slate/sqlite_retire.py` | NEW | Archive (VACUUM INTO/copy) the canonical SQLite + WAL/SHM, **fsync**, then empty-in-place (never delete). |
| `scripts/_clean_slate/config_verify.py` | NEW | `verify_post_reset_config(config_path)`: READ config + Ollama loaded tag, assert llm.model/post_bootcamp/starting_capital reset. |
| `tests/scripts/test_clean_slate_classification.py` | NEW | CI completeness guard (partition exhaustive over 80 + disjoint; FK-edge constant matches §3.5). |
| `tests/scripts/test_clean_slate_live_schema.py` | NEW | Live-schema + FK reconciliation: drift → abort (verify-by-mutation on a scratch DB). |
| `tests/scripts/test_clean_slate_wipe.py` | NEW | Decorator gating, dry-run, TRUNCATE-by-mutation, refuse/abort paths, idempotency, already-clean, interrupted-run/forensic-marker. |
| `tests/scripts/test_clean_slate_backup.py` | NEW | Backup verify-or-refuse + ephemeral-scratch lifecycle (mocked docker + real ephemeral DB on 5434). |
| `docs/runbooks/clean_slate_wipe.md` | NEW | Operator runbook + manifest schema. |

Reused **read-only** (imported, not modified): `src/tools/_safety.py` (`safe_op`, `prod_guard`), `src/tools/_db.py` (`pg_connect`), `src/tools/_execution_log.py` (`write_event`), `src/schema/registry.py` (`TABLES`), `scripts/archive_bootcamp_2026_04_24.py` (`_check_watch_loop_running`, `_check_alpaca_positions`, `_check_open_shadow_trades`, manifest writer).

### 2.2 Layered structure

```
scripts/clean_slate_wipe.py
  ├─ CLI (argparse)  ── --confirm / --dsn / --scratch-server-dsn / --out-dir
  │                     --skip-sqlite / --i-have-flattened-broker / --verify-config / --emergency(reserved no-op)
  ├─ clean_slate_wipe(*, dsn, confirm=False, ...)   ← DECORATED public entry point
  │     @safe_op(name='clean_slate_wipe', mutates=True, describe=_describe)
  │     @prod_guard(dsn_param='dsn')                 ← NO @safety_window (see §5.3)
  │     └─ _run_clean_slate(dsn, ...)                ← internal orchestrator (NOT a public bypass)
  │           PHASE 0 preflight+reconcile+already-clean → PHASE 1 backup+verify(ephemeral)
  │           → PHASE 2 dry-run preview → [confirm gate]
  │           → PHASE 3 (re-check watch-loop) TRUNCATE txn → forensic 'wipe-committed' marker
  │           → PHASE 4 model/config reset+instructions → PHASE 5 SQLite retire(fsync)
  │           → PHASE 6 post-verify(+optional config-verify) → PHASE 7 audit/manifest/banner
  └─ scripts/_clean_slate/{classification,live_schema,backup,sqlite_retire,config_verify}.py
```

**Critical footgun avoidance (memory: feedback_cli_decorated_public_api):** the CLI `__main__` calls the DECORATED `clean_slate_wipe(...)`, never `_run_clean_slate`. The prod DSN MUST be passed as the `dsn=` kwarg — `prod_guard` reads `kwargs.get(dsn_param)` (_safety.py:372); a positional or mis-named DSN makes the guard silently never fire.

**Decorator execution order (REVIEWED — minor (b)):** decorators apply bottom-up at definition, so `@prod_guard` is the innermost wrapper and `@safe_op` the outermost. At call time the OUTER `safe_op` runs first: for `mutates=True` without `confirm`, `safe_op` returns a `DryRunResult` WITHOUT calling the inner chain (_safety.py:197) — so in a dry run `prod_guard` never even evaluates. With `confirm=True`, `safe_op` calls through and `prod_guard` then enforces the prod-DSN+env gate before `_run_clean_slate` executes any mutation.

**Prod is TOUCHED on the read path even when no mutation occurs (REVIEWED — minor (b)):** `prod_guard` gates the *call to the wrapped function* (the mutation), not raw reads. The Phase-0 reconciliation, the Phase-1 `pg_dump`, and the Phase-2 preview all open read connections to (and fully dump) prod **before** any confirm/guard decision short-circuits. This is intentional and safe (read-only / off-box dump), but it means: a dry run still connects to and dumps prod. This is a reviewed, documented decision, surfaced in the banner ("dry-run still reads + dumps prod").

### 2.3 Connection discipline

Use `src/tools/_db.py::pg_connect(dsn, ...)` with the **literal prod DSN** read from `.env DATABASE_URL`. **Do NOT** use `src.utils.db.connect_db` — its cutover-gate (db.py:614-641) silently routes to SQLite when `ARCIS_PG_CUTOVER_ENABLED` is absent, which would wipe the wrong store. The DSN is sourced once in the CLI layer (`os.environ['DATABASE_URL']` via `python-dotenv`) and threaded as `dsn=` through every layer so `prod_guard` sees the prod signature.

## 3. Data Model — Classification (the reviewed partition)

The registry has **no category field** (`TableDef`, registry.py:73-93 — sync-config only). The partition is an **explicit hardcoded constant pair** in `scripts/_clean_slate/classification.py`, reviewed once against the inventory below, and enforced by a CI completeness guard (§3.4). **Authoritative registered universe: `set(src.schema.registry.TABLES)` — exactly 80 tables (verified 2026-06-03).** The registry guard is necessary but **NOT sufficient**; the authoritative runtime gate is the live-schema reconciliation in §3.7.

### 3.1 WIPE_TABLES (trade/learning state — TRUNCATE) — 53 tables

```python
WIPE_TABLES = frozenset({
  # core trade + recommendation
  "recommendations", "shadow_trades", "ib_shadow_log", "attribution_trades",
  "bracket_health", "broker_exceptions", "preflight_runs", "setup_signals",
  # learning / model / training
  "validation_results", "model_versions", "training_examples", "model_evaluations",
  "preference_pairs", "canary_evaluations",
  # council (votes/sessions/calibration/logs/params)
  "council_sessions", "council_votes", "council_calibrations", "council_debug_log",
  "council_parameter_log", "council_parameter_state",
  # audit/metrics/costs/ops-logs (per-run derived)
  "audit_reports", "metric_snapshots", "api_costs", "scan_metrics",
  "schedule_metrics", "quality_drift_metrics", "build_score_history",
  "activity_log", "log_entries", "command_results",
  # backtest / strategy / research-quant outputs
  "stress_test_results", "simulation_results", "backtest_results", "backtest_trades",
  "strategy_registry", "strategy_promotion_events", "trials_registry",
  "correlation_matrices", "factor_loadings", "walkforward_results", "walkforward_trades",
  # notifications (per-run send state) + platform events
  "notifications_sent", "notifications_dedup", "notifications_digest_queue",
  "platform_events",
  # runtime quote cache (re-derives from collectors)
  "live_prices",
  # local IB-gateway infra-health telemetry (see DD-IBHEALTH)
  "daily_ib_health",
  # AMBIGUOUS → ruled WIPE (see Decisions Log):
  "traffic_light_state", "data_freshness", "pending_commands",
  "diagnostic_runs", "diagnostic_run_plots", "system_metrics",
})
```

### 3.2 KEEP_TABLES (market-data / collector / operator-authored — PRESERVE) — 27 tables

```python
KEEP_TABLES = frozenset({
  "edgar_filings", "insider_transactions", "short_interest", "short_volume_daily",
  "fed_communications", "analyst_estimates", "options_chains", "options_metrics",
  "cboe_ratios", "google_trends", "vix_term_structure", "macro_snapshots",
  "earnings_calendar", "research_papers", "research_digests", "research_docs",
  "minute_bars", "sp100_historical_constituents", "institutional_holdings",
  "filings_sentiment", "press_releases", "company_executives", "stock_financials",
  "price_targets",
  # AMBIGUOUS → ruled KEEP (see Decisions Log):
  "config_overrides", "user_notes", "operator_view_state",
})
```

**Counts: WIPE=53, KEEP=27, sum=80 == `len(registry.TABLES)`.** Verified disjoint and exhaustive via script against the live registry on 2026-06-03 (missing=[], extra=[], overlap=[]). Every classified name is asserted to exist in `registry.TABLES` by the §3.4 guard.

### 3.3 AMBIGUOUS / notable rulings (each in Decisions Log; defaults shown)

| Table | Ruling | One-line rationale |
|---|---|---|
| `daily_ib_health` (394) | **WIPE** | Local-only IB-gateway infra-health telemetry (registry:390-393 — not synced, infra not trading). IB is dormant (SD#41); its 30-day stability gate is moot post-clean-slate. (DD-IBHEALTH) |
| `live_prices` | **WIPE** | Runtime quote cache; re-derives from collectors on next scan. |
| `traffic_light_state` | **WIPE** | Regime-state singleton encoding prior-run posture; must reset for clean slate. |
| `council_parameter_state` | **WIPE** | Learned council params; part of learning state being reset. |
| `data_freshness` | **WIPE** | Collector staleness cursors — stale post-wipe; reset lets first scan repopulate. |
| `config_overrides` | **KEEP** | Operator dashboard settings (intentional config), not trade/learning state. |
| `pending_commands` | **WIPE** | Queued operator commands — must not survive a clean-slate restart (could fire stale actions). |
| `diagnostic_runs` + `diagnostic_run_plots` | **WIPE (same bucket)** | Derived diagnostic artifacts; FK-paired so kept together for CASCADE safety. |
| `user_notes` | **KEEP** | Operator-authored content; not machine-derived state. |
| `operator_view_state` | **KEEP** | UI/operator preference state; harmless, operator-owned. |
| `system_metrics` | **WIPE** | Per-run host/process telemetry; derived, regenerates. |

**`sync_state` (render-sync):** referenced by archive_bootcamp:188 but is **NOT a registered `TableDef`** and lives only in SQLite. It is NOT in either PG set; it is handled by the SQLite-archive phase (§4.5) and listed in `UNREGISTERED_NOTES` so the guard does not flag it. (Render is inert post-cutover; archiving the SQLite captures it regardless.)

### 3.4 Completeness CI guard (mirror of `_require_classified_replace`, db.py:820-836)

```python
def assert_partition_complete() -> None:
    universe = set(registry.TABLES)              # exactly 80
    wipe, keep = set(WIPE_TABLES), set(KEEP_TABLES)
    missing = universe - (wipe | keep)
    extra   = (wipe | keep) - universe
    overlap = wipe & keep
    if missing or extra or overlap:
        raise AssertionError(
            f"clean-slate partition drift: missing={sorted(missing)} "
            f"extra={sorted(extra)} overlap={sorted(overlap)} — "
            f"re-review classification.py against src/schema/registry.TABLES (n={len(universe)}).")
```

CI test asserts `set(WIPE)|set(KEEP)==set(registry.TABLES)`, `set(WIPE)&set(KEEP)==∅`, AND `len(universe)==80` (a count-pin so a registry add/remove that happens to keep the partition valid still surfaces). Any new registered table is a hard CI failure until a human classifies it (drift-proof).

### 3.5 FK topology (proves single-statement TRUNCATE is safe) — the 6 expected edges

Exactly 6 FK edges, **all wipe→wipe, none touch keep-set** (registry line refs): `shadow_trades.recommendation_id→recommendations` (341), `shadow_trades.strategy_id→strategy_registry` (342, deferred), `council_votes.session_id→council_sessions` (744), `council_debug_log.session_id→council_sessions` (799), `diagnostic_run_plots.run_id→diagnostic_runs` (1711), `attribution_trades.recommendation_id→recommendations` (1837). A single multi-table `TRUNCATE ... RESTART IDENTITY CASCADE` CANNOT reach keep data. These 6 are pinned in `classification.py::EXPECTED_FK_EDGES` (as `(child_table, child_col, parent_table)` tuples) and asserted (a) constant-vs-spec by the CI guard and (b) **constant-vs-live** by §3.7.

### 3.6 Equity / PnL input enumeration (proves the capital-reset guarantee — MAJOR-3)

Every input the governor reads to compute equity/drawdown on restart, with read paths and disposition:

| Input | Read path | Reset disposition |
|---|---|---|
| Realized PnL (closed, non-quarantined) | `SUM(shadow_trades.pnl_dollars)` — governor.py:393-399 (`get_current_equity` DB path) and 336-352 (`compute_drawdown_pct`) | **In WIPE** (`shadow_trades`) → term → 0. |
| Starting capital | `config.risk.starting_capital` default 100000 — governor.py:387 | NOT in DB; confirmed via §4.4 emit + `--verify-config`. |
| **Broker-reported equity (live IB)** | `get_current_equity` → `acct.equity` when broker is IB — governor.py:374-382 | **NOT in DB; reflects OPEN POSITIONS** → covered by the broker-flat HARD GATE (§5.4). Paper book does not hit this path. |
| Unrealized PnL | NOT read (drawdown/equity are realized-only by design — governor.py:327, 364) | N/A (excluded by design). |
| `attribution_trades` | Attribution analytics only; not an equity input | In WIPE. |
| `traffic_light_state` | Regime posture singleton; not an equity input | In WIPE. |
| `system_metrics`, `metric_snapshots` | Telemetry/snapshots; not an equity input | In WIPE. |
| Last-audit value | `audit_reports` (governor trusts last verdict ~36h — memory) | In WIPE + runbook step 6 force-regenerates (two-layer staleness). |

Conclusion: on the **paper** path, equity resets to exactly `starting_capital` once `shadow_trades` is wiped, with no other prior-trading input. On the **live-IB** path, broker equity is independent of the DB and is neutralized only by flattening the broker → that is why open positions are a hard ABORT, not a warning.

### 3.7 Live-schema reconciliation (the authoritative gate — CRITICAL-2)

The registry guard's universe is the *registered* schema; the wipe runs against LIVE prod PG 5433, which this codebase repeatedly sees DRIFT out of registry sync (memory: notifications_* missing 2026-06-02; no PG schema auto-sync post-cutover; manual `create_all_tables`). An unregistered live table is invisible to the registry guard, the partition, AND the §3.5 FK proof → it could silently SURVIVE the clean slate, or a CASCADE could reach it via an unanalyzed live FK. `scripts/_clean_slate/live_schema.py` (run in Phase 0 against the prod DSN, read-only):

1. **`reconcile_live_schema(dsn)`** — `SELECT table_name FROM information_schema.tables WHERE table_schema='public' AND table_type='BASE TABLE'`. Compute `live_only = live - registered` and `registered_only = registered - live`. If either non-empty → **ABORT** `ABORT_LIVE_SCHEMA_DRIFT` naming both sets; a human must reconcile (register+classify the live-only table, or `create_all_tables` the registry-only one) before the wipe can run. (Filtered to exclude PG internals; the universe is `public` base tables.)
2. **`reconcile_live_fk_edges(dsn)`** — query `pg_constraint`/`information_schema.table_constraints`+`key_column_usage`+`constraint_column_usage` (contype='f') for every FK whose child OR parent is in `WIPE_TABLES`. Normalize to `(child_table, child_col, parent_table)` and assert the set equals `EXPECTED_FK_EDGES` (the 6 in §3.5). Any unexpected edge (incl. a live wipe→keep edge) → **ABORT** `ABORT_FK_DRIFT` naming the offending edges. This catches a live FK that the registry does not model and that a CASCADE would traverse.

**Stated explicitly:** the registry completeness guard (§3.4) is necessary but NOT sufficient. §3.7 is the authoritative gate — it validates the partition AND the FK-safety proof against the bytes actually in prod, immediately before anything irreversible.

## 4. Script Flow (phased)

### PHASE 0 — Preflight + reconcile + already-clean (read-only; abort on any RED)
1. **Watch-loop-stopped (GATING):** `_check_watch_loop_running()` (archive_bootcamp:120-168 — lockfile + psutil + `nssm status != SERVICE_STOPPED`). If non-None → **ABORT** `ABORT_WATCHLOOP`. (Re-checked again in Phase 3.0; see MAJOR-2.)
2. **DSN sanity:** confirm `dsn` resolves/reachable (`pg_connect(dsn)` SELECT 1, read-only). Capture `current_database()`, `inet_server_port()`.
3. **Registry partition integrity:** `assert_partition_complete()` — refuse on drift.
4. **LIVE-SCHEMA RECONCILIATION (authoritative):** `reconcile_live_schema(dsn)` + `reconcile_live_fk_edges(dsn)` (§3.7). Abort `ABORT_LIVE_SCHEMA_DRIFT` / `ABORT_FK_DRIFT` on any divergence.
5. **Broker-flat HARD GATE:** `_check_alpaca_positions()` (archive_bootcamp:243). If open positions AND NOT `--i-have-flattened-broker` → **ABORT** `ABORT_BROKER_NOT_FLAT` with the position list and the irrecoverability note (§5.4). With the override, downgrade to a prominent WARN recorded in the manifest. Never places orders.
6. **Open-shadow-trades advisory:** `_check_open_shadow_trades()` count into manifest (WARN).
7. **Already-clean short-circuit (MAJOR-4):** read per-table counts for every `WIPE_TABLES` table. If ALL == 0 → the platform is already a clean slate: **short-circuit to a no-op result `ALREADY_CLEAN` WITHOUT taking a new backup** (a fresh dump here would capture empty trade state and falsely PASS verify). Emit the banner's restart/config runbook, write the manifest, exit 0.

### PHASE 1 — Backup + verify into a FRESH EPHEMERAL scratch DB (REFUSE-on-failure)
`scripts/_clean_slate/backup.py`. Runs in dry-run too (read-only dump). Skipped only if Phase 0 short-circuited `ALREADY_CLEAN`.
1. `docker exec halcyon-pg pg_dump -U halcyon -d halcyon` → plain SQL (restore-compatible; container `halcyon-pg`, superuser `halcyon`, db `halcyon`).
2. `docker cp` the dump → `data/backups/clean_slate/<ISO8601>/prod.sql`.
3. **Verify structure** (the checks at restore_pg_from_snapshot.ps1:116-144): size > 1 MB (else `BackupVerifyError`/`REFUSE_BACKUP`); compute SHA256; count `^CREATE TABLE` statements and compare to **80**:
   - **count == 80** → PASS.
   - **count < 80 (SHORTFALL)** → **HARD REFUSE** `REFUSE_BACKUP` (`BackupVerifyError`): a dump missing tables is structurally unrestorable; never proceed to TRUNCATE (MAJOR-1).
   - **count > 80 (EXCESS)** → **REFUSE** `REFUSE_SCHEMA_DRIFT`: live drift the §3.7 reconciliation must resolve first (should already have aborted in Phase 0; this is defense-in-depth).
   - WARN is reserved for benign, explained equalities only (none expected); the only PASS threshold is exact == 80.
4. **Verify-restore into an EPHEMERAL DB (CRITICAL-3):**
   a. Connect to the **scratch SERVER** via `--scratch-server-dsn` (default `postgresql://test:test@127.0.0.1:5434/postgres` — the maintenance DB on the test PG server, NOT the shared `halcyon` test DB used by pytest).
   b. `CREATE DATABASE clean_slate_verify_<ISO8601>` (AUTOCOMMIT; name carries the run timestamp).
   c. Assert the new DB is **empty** (`information_schema.tables` public base-table count == 0) before restoring; abort `REFUSE_VERIFY` if not.
   d. `psql` restore the dump into the ephemeral DB.
   e. **Count-compare** per-table row counts ephemeral-vs-prod for the full WIPE+KEEP set (and total table count). Any restore error or count divergence beyond tolerance (exact for low-volume; ±0.5% only for `minute_bars`-class high-churn KEEP tables, which are read live so small drift is the live delta not a backup fault) → **REFUSE** `REFUSE_VERIFY` (`BackupVerifyError`).
   f. **`DROP DATABASE clean_slate_verify_<ISO8601>`** in a `finally` (force-disconnect first). The ephemeral DB never outlives the run and never touches the shared test DB.
5. **Backup manifest** records: size, SHA, create-count, restore-verdict, per-table compare, **per-WIPE-table prod row counts**, and `BACKUP_OF_EMPTY_STATE` if the dump was taken while all WIPE tables were empty (MAJOR-4 belt-and-suspenders; Phase 0 normally short-circuits before here).

**Refuse rule:** any backup or verify failure REFUSES the TRUNCATE phase even with `--confirm`. There is no prod bypass; a `--skip-backup`-style flag exists ONLY for tests against non-prod DSNs and is itself REFUSED on a prod-signature DSN.

### PHASE 2 — Dry-run preview (always printed)
Read-only connection; compute and print: the exact `WIPE_TABLES` list with **LIVE current row counts**; the `KEEP_TABLES` list with current counts (proof market data is preserved); the model L1 DB reset + the L2/L3/config instructions that will be EMITTED; the backup location + verify verdict; all WARN/ABORT flags (broker, open shadow trades, CREATE-count, schema/FK reconciliation result); projected post-wipe state (all WIPE → 0); and the explicit note that **this dry run already connected to and dumped prod** (read-path prod-touch, §2.2).

### [CONFIRM GATE]
`@safe_op(mutates=True)` returns a `DryRunResult` and logs `dry_run` UNLESS `confirm=True` (_safety.py:197). Without `--confirm`, execution STOPS here after the preview — zero mutation. `prod_guard` additionally requires `ARCIS_ALLOW_PROD_PG=1` AND `confirm=True` for a prod-signature DSN (_safety.py:375-390).

### PHASE 3 — TRUNCATE (single transaction, watch-loop re-checked at the boundary)
**3.0 (MAJOR-2a) Immediate re-check:** the watch loop is NSSM-managed and AUTO-RESTARTS; the backup+verify window is minutes. Immediately before opening the TRUNCATE transaction, re-call `_check_watch_loop_running()`. If non-None → **ABORT** `ABORT_WATCHLOOP_RECHECK` (nothing committed). Additionally require evidence the operator STOPPED the NSSM service (not merely idle): the check's signal-3 (`nssm status` contains `SERVICE_STOPPED`) must be satisfied; if `nssm` is unavailable on PATH the script treats the precondition as UNVERIFIED and ABORTs `ABORT_WATCHLOOP_UNVERIFIED` unless `--i-have-stopped-nssm` is passed (operator attestation, recorded). The runbook directs `nssm stop ArcisWatchLoop` (verified stopped/disabled), not just observed-idle.

**3.1 TRUNCATE:** via `pg_connect(dsn, isolation_level='SERIALIZABLE')`, in ONE transaction:
```sql
TRUNCATE TABLE <sorted WIPE_TABLES, comma-joined> RESTART IDENTITY CASCADE;
```
- Capture per-table BEFORE counts (Phase 0/2) and AFTER counts (all 0); print row delta per table + grand total.
- TRUNCATE (not DROP) deliberately: avoids the #92/#129 'must be owner' crash-loop and the ALTER OWNER/GRANT/ALTER DEFAULT PRIVILEGES dance. Preserves structure + ownership + grants.
- On any error → ROLLBACK (pg_connect rolls back on exception, _db.py:66-71); exit non-zero; nothing committed.

**3.2 Forensic 'wipe-committed' marker (minor (d)):** immediately AFTER the TRUNCATE transaction commits and BEFORE Phase 4, write `data/backups/clean_slate/<ISO8601>/WIPE_COMMITTED.marker` (timestamp + server identity + per-table deltas) and **fsync** it. This makes a committed-wipe-without-final-manifest detectable on a crash between commit and Phase 7, and supports safe re-entry diagnosis.

### PHASE 4 — Model reset + config instructions
- **L1 (DB, AUTO):** `model_versions` ∈ WIPE ⇒ already TRUNCATE-d ⇒ `get_active_model_version()` → None ⇒ `get_active_model_name()` falls to Ollama/'base' (versioning.py:344-362). Assert `model_versions` empty post-truncate; record.
- **L2 (config, EMIT):** instruct operator to set `llm.model` in `config/settings.local.yaml` to the base Ollama tag (else inference keeps serving the fine-tune — versioning.update_config_model:314). Script does NOT auto-edit (cp1252 corruption risk; DD-CFG).
- **L3 (Ollama, EMIT):** instruct operator to ensure the base tag is the loaded Ollama model (OS-level).
- **Config resets (EMIT):** confirm `live_trading.post_bootcamp=false` (auditor.py:722 default false) and `risk.starting_capital=100000` (PAPER). Banner warns: **DO NOT touch `live_trading.starting_capital`=100 (LIVE).** Capital resets emergently once `shadow_trades` wiped (§3.6).

### PHASE 5 — SQLite retire (archive-fsync-then-empty, never delete)
`scripts/_clean_slate/sqlite_retire.py`:
- Source: `C:/arcis/data/ai_research_desk.sqlite3` (+ `-wal`,`-shm`) from `.env ARCIS_DB_PATH` / `paths.db_canonical`.
- Archive: `VACUUM INTO 'data/archive/clean_slate/<ISO8601>/ai_research_desk.sqlite3'` (or file copy if VACUUM INTO unavailable), capturing WAL/SHM. **fsync the archive file (and its directory) BEFORE emptying** (minor (d)) so an interruption can never leave both the live file emptied and the archive unflushed.
- **Then empty, NOT delete:** re-create empty / truncate the trade-learning tables in place so a valid file persists (`connect_db` recreates an empty file at db.py:638; deleting outright changes the fallback for any non-gated tool/test). (DD-SQLITE.)
- Record archive path + SHA in manifest.

### PHASE 6 — Post-verify (DB) + optional config-verify (MAJOR-3)
**6.1 DB:** re-query each `WIPE_TABLES` count == 0; each `KEEP_TABLES` count unchanged vs Phase 2; assert `model_versions` empty; confirm SQLite archive exists + non-empty. Mismatch → loud FAILURE + `POST_VERIFY_FAILED` (wipe already committed).
**6.2 Config/Ollama (closes the L2/L3 loop):** because L2/L3/config are emitted-instructions-only, a DB-only post-verify can report `POST_VERIFY PASSED` while the system still serves the fine-tune / stale capital. `config_verify.verify_post_reset_config(config_path)`:
- READ `config/settings.local.yaml`: assert `llm.model` == the base tag, `live_trading.post_bootcamp` == false, `risk.starting_capital` == 100000.
- READ the Ollama loaded model (`ollama ps` / API tags) and assert the base tag is loaded.
- Behavior: if `--verify-config` is passed (intended to be run AFTER the operator completes the manual L2/L3 steps), failures are loud FAILUREs and the manifest is updated to `POST_VERIFY_CONFIG_PASSED`/`..._FAILED`. If `--verify-config` is NOT passed in the main run (the normal case, since the operator hasn't edited YAML yet), the manifest records **`POST_VERIFY_CONFIG_PENDING`** and the banner instructs re-running `clean_slate_wipe.py --verify-config` post-config to flip it. "Clean slate" is not certified until both `POST_VERIFY` (DB) and `POST_VERIFY_CONFIG` (config/Ollama) are PASSED.

### PHASE 7 — Audit + manifest + banner
- Atomic `manifest.json` (temp + `os.replace`, archive_bootcamp pattern): timestamp, server identity, partition hash, **live-schema reconciliation verdict**, **live-FK-edge verdict**, backup path+SHA+verdict, **per-WIPE-table before/after deltas + empty-state tag**, reset verdicts, SQLite archive path, all WARN/ABORT flags, broker-gate disposition, DB post-verify verdict, config post-verify verdict (`PENDING`/`PASSED`/`FAILED`), final verdict.
- `write_event(tool_name='clean_slate_wipe', params={...}, result=..., duration_ms, session_id)` — auto-sanitizes DSN passwords (_execution_log.py:141). Complements the decorator-emitted events with the rich operational delta.
- Print the **operator BANNER** (archive_bootcamp `_BANNER` pattern): restart sequence + L2/L3/config manual steps + two-layer-staleness note + the `--verify-config` re-run instruction + the `--emergency`-is-orthogonal note (§5.5).

## 5. Safety / ProdGuard Integration

### 5.1 Decorator stack (outer→inner)
```python
@safe_op(name='clean_slate_wipe', mutates=True, describe=_describe_clean_slate)
@prod_guard(dsn_param='dsn')
def clean_slate_wipe(*, dsn: str, scratch_server_dsn: str, confirm: bool = False,
                     i_have_flattened_broker: bool = False, i_have_stopped_nssm: bool = False,
                     verify_config: bool = False, skip_sqlite: bool = False,
                     emergency: bool = False) -> dict:
    return _run_clean_slate(dsn=dsn, scratch_server_dsn=scratch_server_dsn, confirm=confirm, ...)
```
Verified contract: `safe_op` short-circuits to `DryRunResult` without calling fn when `confirm` absent (_safety.py:197); `prod_guard` blocks prod DSN without env+confirm (_safety.py:375-390); `SafetyError` subclasses skip the duplicate 'error' event (_safety.py:146-147). **NO `@safety_window` — see §5.3.**

### 5.2 ProdGuard signatures
`prod_guard` matches `dsn` against `pg.prod_dsn_signatures` (`localhost:5433` / `127.0.0.1:5433` / `halcyon_app:`). The prod DSN MUST be threaded as `dsn=` (guard reads `kwargs.get('dsn')`). `ARCIS_ALLOW_PROD_PG=1` is the explicit operator opt-in at execution time.

### 5.3 No market-hours safety_window (RESOLVED — minor (c))
The central config declares ONLY `safety_windows.no_restart_overnight`; there is **no `market_hours` key** (arcis_config.yaml:118-128, verified). `safety_window('market_hours')` would raise `ValueError("window 'market_hours' not declared")` at call time (_safety.py:268-271). Therefore the script ships **without** `@safety_window`. The HARD preconditions that gate a destructive run are instead: watch-loop NSSM-stopped (re-checked, §Phase 3.0), live-schema+FK reconciliation (§3.7), and broker-flat (§5.4). A follow-up (filed as #138, see DD-WINDOW) may add a declared RTH window later; this design does not edit central config to invent one.

### 5.4 Broker-flat HARD GATE (MAJOR-2b)
Open broker positions wiped from `shadow_trades` become PERMANENT orphans: the reconciler's backfill source is the very `shadow_trades`/`ib_shadow_log` history this wipe destroys (exactly the orphan-at-scale class just fixed in #76/#82). Moreover live-IB equity reads broker `acct.equity` (§3.6), so open positions also defeat the capital-reset guarantee. Default: open positions → **ABORT `ABORT_BROKER_NOT_FLAT`** with the position list and a prominent irrecoverability note. Override: `--i-have-flattened-broker` (operator attestation that the broker is flat) downgrades to a recorded WARN. The script NEVER places flatten orders (out-of-scope).

### 5.5 `--emergency` is orthogonal (minor (a))
`--emergency` ONLY ever affected a `safety_window`'s audited bypass. With no `@safety_window` in the stack (§5.3), `--emergency` has **no effect** in this script: it does NOT bypass `--confirm`, does NOT bypass `ARCIS_ALLOW_PROD_PG=1`, and does NOT bypass any hard gate. It is retained as a reserved, currently-inert flag (so adding a window later doesn't change the CLI contract) and the banner states plainly: "`--emergency` does nothing here; the wipe still requires `--confirm` + `ARCIS_ALLOW_PROD_PG=1` and all hard gates."

## 6. Reuse vs New

**Reuse (import; do NOT re-implement):** `_check_watch_loop_running`, `_check_alpaca_positions`, `_check_open_shadow_trades` (archive_bootcamp:120-262 — PG/SQLite-agnostic; copy verbatim into `_clean_slate/preflight.py` with attribution if import coupling is undesired); atomic manifest writer + dry-run-default argparse shape + `_BANNER` pattern (archive_bootcamp); all safety primitives + `pg_connect` + `write_event` (src/tools/).

**New (budget for it):** backup + verify-restore-into-ephemeral path; the live-schema/FK reconciliation; classification constants + completeness guard; the config-verify reader; the decorated entry point + phase orchestration + forensic markers.

**Anti-pattern (do NOT emulate):** `scripts/fix_training_page.py` (raw DELETE, no guard/dry-run/backup).

## 7. Error Handling & Refuse/Abort Paths

| Condition | Behavior | Audit result |
|---|---|---|
| Watch loop running (Phase 0) | ABORT before any mutation | `ABORT_WATCHLOOP` |
| Watch loop running (Phase 3.0 re-check) | ABORT before TRUNCATE txn | `ABORT_WATCHLOOP_RECHECK` |
| NSSM stopped-state unverifiable, no attestation | ABORT before TRUNCATE | `ABORT_WATCHLOOP_UNVERIFIED` |
| Registry partition drift | ABORT (assert) | `ABORT_PARTITION_DRIFT` |
| Live public schema ≠ registry | ABORT | `ABORT_LIVE_SCHEMA_DRIFT` |
| Live FK edges ≠ the 6 expected | ABORT | `ABORT_FK_DRIFT` |
| Open broker positions, no override | ABORT before backup | `ABORT_BROKER_NOT_FLAT` |
| All WIPE tables already empty | no-op short-circuit, NO backup | `ALREADY_CLEAN` |
| Prod DSN w/o env+confirm | `ProdGuardError` (decorator) | `prod_guard_block` |
| No `--confirm` | DryRunResult, preview only, exit 0 | `dry_run` |
| pg_dump fails / dump <1MB / CREATE-count < 80 | `BackupVerifyError`, REFUSE wipe | `REFUSE_BACKUP` |
| CREATE-count > 80 (live drift) | REFUSE pending reconciliation | `REFUSE_SCHEMA_DRIFT` |
| Ephemeral DB not empty pre-restore / restore err / count divergence | `BackupVerifyError`, REFUSE wipe | `REFUSE_VERIFY` |
| TRUNCATE raises | ROLLBACK, exit non-zero, nothing committed | `error` |
| Crash after commit, before manifest | `WIPE_COMMITTED.marker` present, manifest absent → detectable on re-entry | (forensic) |
| SQLite source missing | WARN, skip retire, continue | `SQLITE_ABSENT` |
| DB post-verify mismatch | loud FAILURE, wipe already committed | `POST_VERIFY_FAILED` |
| Config/Ollama not yet reset (normal main run) | recorded pending; re-run `--verify-config` | `POST_VERIFY_CONFIG_PENDING` |
| `--verify-config` run, config/Ollama still stale | loud FAILURE | `POST_VERIFY_CONFIG_FAILED` |

**Idempotency & safe re-entry:** re-running after a completed wipe hits the Phase-0 `ALREADY_CLEAN` short-circuit (no new backup of empty state). A run interrupted AFTER the TRUNCATE commit is detectable via `WIPE_COMMITTED.marker` without a sibling `manifest.json`; re-entry is safe (TRUNCATE of empty tables is a no-op, SQLite already-empty is a no-op, model_versions already empty). A run interrupted after the SQLite archive but before emptying leaves a valid (fsync'd) archive and an untouched live file → re-run completes the empty step.

## 8. Testing Strategy

Test infra: pytest with **`TEST_DATABASE_URL=...@127.0.0.1:5434`** (halcyon-pg-test) — NEVER `ARCIS_ALLOW_PROD_PG_IN_TESTS=1` (disables the P0 guard; memory). Ephemeral verify DBs are created/dropped on the 5434 SERVER and are distinct from the shared test DB. Decorators accept `log_path=`/`config_path=` overrides for isolation.

1. **Completeness guard:** assert exhaustive+disjoint vs `registry.TABLES` AND `len==80`; assert `EXPECTED_FK_EDGES` matches §3.5. **Verify-by-mutation:** inject a fake table into a COPY of `registry.TABLES` → assert `assert_partition_complete()` RAISES (not theater — memory: feedback_vacuous_test_pattern).
2. **Live-schema reconciliation:** on a scratch DB create an extra unregistered table → assert `reconcile_live_schema` ABORTs `ABORT_LIVE_SCHEMA_DRIFT`; drop a registered table → assert it ABORTs the other direction; add an unexpected FK edge → assert `reconcile_live_fk_edges` ABORTs `ABORT_FK_DRIFT`. Verify-by-mutation: prove each abort fires only on the injected drift and PASSES on a faithful registry-built schema.
3. **Ephemeral-scratch lifecycle + backup verify-or-refuse:** mock docker pg_dump to emit (a) <1MB → `REFUSE_BACKUP`; (b) CREATE-count 79 (shortfall) → `REFUSE_BACKUP` (HARD, by-mutation: assert it RAISES, does not WARN); (c) CREATE-count 81 → `REFUSE_SCHEMA_DRIFT`; (d) count-divergent restore → `REFUSE_VERIFY`; (e) good dump → proceeds. Assert the ephemeral DB is CREATEd, asserted-empty, and DROPped (query the 5434 server for absence after) and that the shared `halcyon` test DB is never touched.
4. **Dry-run default:** no `confirm` → DryRunResult, NO mutation on a seeded scratch DB, `dry_run` event; preview prints live counts; assert the dry run still performed the read-path dump (prod-touch documented).
5. **ProdGuard:** prod-signature DSN without env/confirm → `ProdGuardError`+`prod_guard_block`. By-mutation: a separate test documents the guard requires the kwarg (positional DSN → guard silent).
6. **TRUNCATE-by-mutation:** seed WIPE+KEEP rows + an FK chain (recommendations→shadow_trades), run `confirm=True` against the scratch DSN, assert WIPE→0, KEEP unchanged, CASCADE leaves keep intact, delta report correct.
7. **Watch-loop re-check (MAJOR-2a):** mock `_check_watch_loop_running` to return None at Phase 0 but non-None at the Phase-3.0 re-check → assert `ABORT_WATCHLOOP_RECHECK`, nothing committed.
8. **Broker hard gate (MAJOR-2b):** mock `_check_alpaca_positions` non-empty → assert `ABORT_BROKER_NOT_FLAT` before backup; with `--i-have-flattened-broker` → assert proceeds with a recorded WARN.
9. **Already-clean (MAJOR-4):** seed scratch with all WIPE tables empty → assert `ALREADY_CLEAN`, NO backup taken (mock backup asserted not-called), exit 0.
10. **Config-verify (MAJOR-3):** point `verify_post_reset_config` at a temp config with llm.model=fine-tune → assert FAIL; with base tag + post_bootcamp=false + starting_capital=100000 (+ mocked Ollama base loaded) → assert PASS. Assert a normal main run records `POST_VERIFY_CONFIG_PENDING`.
11. **Idempotency:** run twice on scratch; second run short-circuits ALREADY_CLEAN, no error.
12. **SQLite retire:** tmp SQLite with seeded trade tables → archive created + non-empty + **source still exists** (emptied, not deleted); assert archive fsync ordering (archive present before empty).
13. **Interrupted-run / forensic marker (minor (d)):** drive the flow to abort right after the TRUNCATE commit (inject) → assert `WIPE_COMMITTED.marker` exists, `manifest.json` absent, and a committed-wipe-without-manifest is detectable; separately abort after the SQLite archive but before empty → assert the archive is intact and re-entry completes safely.
14. **E2E rehearsal (scratch only):** full `confirm=True` against a registry-provisioned scratch DB: backup+verify (ephemeral), TRUNCATE deltas, KEEP preserved, SQLite tmp archived+emptied, manifest with all verdicts incl. reconciliation + config-pending, idempotent re-run. NEVER prod 5433.

Every mutating test asserts the operation **could** have failed (verify-by-mutation) before trusting a green assertion.

## 9. Operator Runbook (steps the script does NOT do — emitted in the banner; full doc at docs/runbooks/clean_slate_wipe.md)
1. **Before:** `nssm stop ArcisWatchLoop` (verify SERVICE_STOPPED/disabled, not just idle); **flatten the broker** (the script ABORTS on open positions — pass `--i-have-flattened-broker` only after truly flat); confirm clean prod window; `set ARCIS_ALLOW_PROD_PG=1`.
2. **Run dry-run first** (no `--confirm`); review WIPE list + live deltas + reconciliation verdict + WARN flags. (Note: the dry run reads + dumps prod.)
3. **Run with `--confirm`** (operator GO).
4. **After (config — manual, utf-8):** set `config/settings.local.yaml` `llm.model`→base tag; confirm `risk.starting_capital=100000`; confirm `live_trading.post_bootcamp=false`; **DO NOT touch `live_trading.starting_capital`=100**.
5. **After (Ollama — OS):** ensure the base tag is the loaded model.
6. **Re-run `clean_slate_wipe.py --verify-config`** to flip `POST_VERIFY_CONFIG_PENDING`→`PASSED` (asserts config + Ollama reset).
7. **Restart + regenerate (two-layer staleness, memory):** restart the watch loop AND force-regenerate the stale `audit_reports` verdict so the governor does not act on pre-wipe state.
8. Verify clean restart against `manifest.json` (final verdict + both post-verifies PASSED).

## 10. Decisions surfaced for execution-time GO (sensible defaults set)
See Decisions Log. All have defaults; none block speccing. Surfaced for GO: (a) broker-flat override `--i-have-flattened-broker` (default: HARD ABORT on open positions); (b) SQLite empty-in-place vs file-recreate (default: archive-fsync-then-empty-in-place); (c) verify-restore tolerance (default: exact for low-volume tables, ±0.5% only for `minute_bars`-class KEEP tables); (d) whether to add a declared RTH safety_window later (default: not now; follow-up #138).

## Design Decisions

| # | Decision | Rationale |
|---|----------|-----------|
| 1 | Explicit hardcoded WIPE/KEEP constant pair (human-reviewed once over the **80** registered tables) + a CI completeness guard pinning count==80, NOT derive-from-registry. | TableDef (registry.py:73-93) has no domain/category field. The only authoritative registered universe is `set(registry.TABLES)` (exactly 80, verified 2026-06-03). Asserting `WIPE∪KEEP==set(TABLES)`, disjointness, and `len==80` (mirroring `_require_classified_replace`, db.py:820-836) makes the classification reviewed-once and drift-proof. Counts: WIPE=53, KEEP=27, sum=80. |
| 2 | `daily_ib_health` → WIPE (DD-IBHEALTH). | It was previously in NEITHER set, which would make `assert_partition_complete()` raise `missing={'daily_ib_health'}` and abort EVERY run. It is local-only IB-gateway infra-health telemetry (registry:390-393: not synced, infra not trading data); IB is dormant (SD#41) and the 30-day stability gate it feeds is meaningless post-clean-slate. Ruling it WIPE (machine-derived telemetry that regenerates) restores exhaustiveness (53/27/80). Alternatives: KEEP (rejected — it is not operator-authored config and a clean slate should not carry pre-wipe infra counters); leave unclassified (rejected — guaranteed abort). |
| 3 | Phase-0 **live-schema + live-FK reconciliation** against the prod DSN is the AUTHORITATIVE gate; the registry guard is necessary-but-not-sufficient (CRITICAL-2). | This codebase repeatedly sees live PG drift out of registry sync (notifications_* missing 2026-06-02; no PG auto-sync post-cutover; manual create_all_tables). An unregistered live table is invisible to the registry guard, the partition, and the §3.5 FK proof → could survive the wipe or be CASCADE-reached via an unmodeled FK. Querying `information_schema.tables` (assert live public set == registry) and `pg_constraint` (assert live wipe-touching FK edges == the 6 expected) validates the partition AND the FK-safety proof against the bytes actually in prod, immediately before anything irreversible. Aborts: `ABORT_LIVE_SCHEMA_DRIFT`, `ABORT_FK_DRIFT`. Alternatives: trust the registry only (rejected — the documented drift class defeats it). |
| 4 | Verify-restore into a FRESH EPHEMERAL DB (`clean_slate_verify_<ISO8601>` created+dropped on the 5434 server), asserted empty pre-restore, NOT the shared `halcyon` test DB (CRITICAL-3). | Restoring into the shared test DB (used by pytest) would (a) make the plain-SQL CREATE-TABLE restore error on residue → false REFUSE, or inflate counts → false PASS, and (b) clobber concurrent CI/tests. An ephemeral DB on the same server gives an isolated, known-empty target; DROP in `finally` (force-disconnect) guarantees no residue and no contention. `--scratch-server-dsn` defaults to the maintenance DB (`/postgres`) and explicitly NOT the test DB. Alternatives: TRUNCATE-then-restore the shared DB (rejected — still contends with CI, and a partial restore leaves it dirty); restore on prod (rejected — defeats the purpose). |
| 5 | TRUNCATE ... RESTART IDENTITY CASCADE in a single transaction, NOT DROP; with a watch-loop re-check at the transaction boundary and an open-broker HARD gate (MAJOR-2). | DROP triggers the #92/#129 'must be owner' crash-loop + the ALTER OWNER/GRANT/ALTER DEFAULT PRIVILEGES dance; TRUNCATE preserves structure/ownership/grants and the §3.5/§3.7 FK proofs make a single multi-table TRUNCATE FK-safe. The watch loop is NSSM-managed + auto-restarts and the backup window is minutes, so a Phase-0-only check is point-in-time stale → re-check immediately before commit and require NSSM SERVICE_STOPPED (or `--i-have-stopped-nssm` attestation). Open broker positions wiped from shadow_trades become permanent orphans (the reconciler's backfill source is the very history destroyed) AND defeat live-IB equity reset (governor.py:374-382), so open positions ABORT by default (`--i-have-flattened-broker` override). |
| 6 | Config/Ollama resets are EMITTED as instructions, and a `--verify-config` loop READS+ASSERTS them (`POST_VERIFY_CONFIG_PENDING` until confirmed) (MAJOR-3). | Auto-editing prod YAML risks cp1252 corruption (memory feedback_windows_utf8_encoding); the archive_bootcamp precedent emits instructions. But emitted-only L2/L3 means a DB-only post-verify can report PASSED while still serving the fine-tune / stale capital. `verify_post_reset_config` reads `config/settings.local.yaml` (assert llm.model==base, post_bootcamp==false, starting_capital==100000) and the Ollama loaded tag, flipping the manifest to PASSED only after the operator completes the manual steps. Equity itself resets emergently on the paper path (§3.6: shadow_trades is the only prior-trading equity input; broker-equity path is gated by broker-flat). |
| 7 | Backup CREATE-count SHORTFALL → HARD REFUSE; EXCESS → REFUSE pending reconciliation; only exact==80 PASSes (MAJOR-1). | A dump missing tables is a structurally broken / unrestorable backup; proceeding to an irreversible TRUNCATE on a checkbox WARN is unacceptable. Shortfall (count<80) raises `BackupVerifyError`/`REFUSE_BACKUP`. Excess (count>80) signals live drift the §3.7 reconciliation must resolve → `REFUSE_SCHEMA_DRIFT`. WARN is reserved for benign explained equalities (none expected). |
| 8 | No `@safety_window('market_hours')`; ship with watch-loop-stopped + live-schema + broker-flat as the hard preconditions; `--emergency` is a reserved no-op (minors a/c). | The config declares only `safety_windows.no_restart_overnight`; `market_hours` does not exist (arcis_config.yaml:118-128) and `safety_window('market_hours')` would `ValueError` at call time (_safety.py:268-271). Inventing a central-config key is out-of-scope for a script PR. The hard gates above are stronger than a clock window for a destructive op. `--emergency` only ever affected a window's bypass, so with no window it has zero effect — retained as inert (banner-stated) so a future window doesn't change the CLI contract. Follow-up #138 may add a declared RTH window. (DD-WINDOW.) Removed the prior "developer chooses" market_hours fork. |
| 9 | SQLite retire = archive (VACUUM INTO/copy) → **fsync** → empty-in-place, NEVER blind-delete; plus a fsync'd `WIPE_COMMITTED.marker` before Phase 4 (DD-SQLITE; minor d). | `connect_db` recreates an empty file at db.py:638; deleting the canonical file changes the fallback for any non-gated tool/test. Archiving first (with WAL/SHM) preserves forensics; emptying-in-place leaves a valid schema'd file. fsync-before-empty makes an interrupted run unable to lose both copies. The `WIPE_COMMITTED.marker` (written+fsync'd after the TRUNCATE commit, before Phase 4) makes a committed-wipe-without-final-manifest detectable for safe re-entry. |
| 10 | Connection via `_db.pg_connect(dsn=<literal .env DATABASE_URL>)`; DSN threaded as `dsn=`; CLI calls the DECORATED entry point; prod is intentionally TOUCHED on the read path (reconcile/dump/preview) without prod_guard firing (minor b). | `connect_db`'s cutover-gate (db.py:614-641) silently routes to SQLite without `ARCIS_PG_CUTOVER_ENABLED` → would wipe the wrong store. `prod_guard` reads `kwargs.get('dsn')` (_safety.py:372): a positional/mis-named DSN makes the guard silently never fire. `prod_guard` gates the *mutation* (the wrapped-fn call), not raw reads — so the Phase-0 reconciliation, Phase-1 dump, and Phase-2 preview connect to and dump prod before any short-circuit. This read-path prod-touch is reviewed, safe (read-only/off-box dump), and surfaced in the banner. |
| 11 | Already-clean Phase-0 short-circuit (all WIPE counts==0 → `ALREADY_CLEAN`, NO new backup) + per-WIPE-table counts in the manifest with `BACKUP_OF_EMPTY_STATE` tagging (MAJOR-4). | Each run dumps to a new ISO8601 dir; a re-run after a completed wipe would back up the now-EMPTY trade state, which passes all structural verify checks and is indistinguishable from a good backup. Detecting all-empty WIPE tables before backup short-circuits to a no-op; recording per-table prod counts (and tagging empty-state dumps) makes an accidental empty-state backup auditable. |
| 12 | Explicit Phase-7 `write_event` + atomic `manifest.json` in addition to decorator-emitted events. | The decorators emit dry_run/prod_guard_block/success/error carrying only kwargs; the capstone needs a rich forensic record (reconciliation verdicts, per-table deltas, backup SHA, restore verdict, SQLite archive path, broker disposition, both post-verifies). write_event auto-sanitizes DSN passwords (_execution_log.py:141). |

## Design Decisions

| # | Decision | Rationale |
|---|----------|-----------|
| 1 | Rule daily_ib_health into WIPE_TABLES, restoring an exhaustive 80-table partition (WIPE=53, KEEP=27). | len(registry.TABLES)==80 (verified live 2026-06-03), and daily_ib_health (registry.py:394) was previously in NEITHER set, which would make assert_partition_complete() raise missing={'daily_ib_health'} and abort EVERY run. It is local-only IB-gateway infra-health telemetry (registry comment 390-393: not synced to cloud, infra metrics not trading data); IB is dormant (SD#41) and its 30-day stability gate is meaningless after a clean slate. As machine-derived telemetry that regenerates, it belongs in WIPE. Re-asserted exhaustive+disjoint against the real 80-table registry (missing=[], extra=[], overlap=[]); corrected '~71' to 80 everywhere and pinned len==80 in the guard. |
| 2 | Add a Phase-0 live-schema + live-FK reconciliation against the actual prod DSN as the AUTHORITATIVE gate; state explicitly that the registry completeness guard is necessary but NOT sufficient. | The registry guard's universe is the registered schema, but the wipe runs against live prod PG 5433, which this codebase repeatedly sees drift out of registry sync (notifications_* missing 2026-06-02; no PG auto-sync post-cutover; manual create_all_tables). An unregistered live table is invisible to the registry guard, the WIPE/KEEP partition, AND the §3.5 FK-safety proof — so it could silently survive the 'clean slate', or a live FK could let a CASCADE reach an unanalyzed table. reconcile_live_schema (information_schema.tables: live public set == registry, else ABORT_LIVE_SCHEMA_DRIFT) and reconcile_live_fk_edges (pg_constraint: live wipe-touching FK edges == the 6 EXPECTED_FK_EDGES, else ABORT_FK_DRIFT) validate the partition and the FK proof against the bytes actually in prod, immediately before anything irreversible. |
| 3 | Verify-restore into a FRESH EPHEMERAL database (clean_slate_verify_<ISO8601>, CREATEd then DROPped on the 5434 server, asserted empty pre-restore) — never the shared halcyon test DB. | Restoring into the shared 5434 test DB (used by pytest) would either error the plain-SQL CREATE-TABLE restore on residue (false REFUSE) or inflate counts (false PASS), and would clobber concurrent CI/tests. A dedicated ephemeral DB on the same server is isolated and known-empty; DROP in a finally (after force-disconnect) guarantees no residue and no contention. --scratch-server-dsn defaults to the 5434 maintenance DB (/postgres) and explicitly NOT the shared test DB, so a wipe-verify can never collide with the test suite. |
| 4 | Make open broker positions a HARD GATE (ABORT_BROKER_NOT_FLAT) by default, with an explicit --i-have-flattened-broker override; re-check the NSSM-managed watch loop immediately before the TRUNCATE transaction. | Open positions wiped from shadow_trades/ib_shadow_log become PERMANENT orphans — the reconciler's backfill source is the very history this wipe destroys (the orphan-at-scale class just fixed in #76/#82) — and live-IB equity reads broker acct.equity (governor.py:374-382), which reflects open positions and is independent of the DB, defeating the capital-reset guarantee. A WARN is insufficient for an irreversible op, so open positions ABORT by default. Separately, the watch loop is NSSM-managed and auto-restarts and the backup+verify window is minutes, so a Phase-0-only check is point-in-time stale; the script re-calls _check_watch_loop_running() immediately before opening the TRUNCATE txn and requires NSSM SERVICE_STOPPED (or an explicit --i-have-stopped-nssm attestation when nssm is unavailable), aborting otherwise. |
| 5 | Close the config/Ollama reset loop with a --verify-config mode that READS config/settings.local.yaml + the Ollama loaded model and ASSERTS llm.model==base, post_bootcamp==false, starting_capital==100000; record POST_VERIFY_CONFIG_PENDING until confirmed. | L2 (config) and L3 (Ollama) resets are emitted instructions only (auto-editing prod YAML risks cp1252 corruption — feedback_windows_utf8_encoding), so a DB-only Phase-6 post-verify can report POST_VERIFY PASSED while the system still serves the fine-tune or holds stale capital. The full equity-input enumeration (§3.6) proves the paper path resets emergently once shadow_trades is wiped, but the config/Ollama layer needs its own assertion. verify_post_reset_config reads (never edits) the YAML + Ollama tag; in the normal main run (operator hasn't edited YAML yet) the manifest records POST_VERIFY_CONFIG_PENDING and the banner instructs re-running --verify-config post-edit to flip it to PASSED. 'Clean slate' is certified only when both the DB and config post-verifies PASS. |
| 6 | Promote backup CREATE-count SHORTFALL to a HARD REFUSE (REFUSE_BACKUP); treat EXCESS as REFUSE_SCHEMA_DRIFT; only an exact count==80 passes. | A dump with fewer than 80 CREATE TABLE statements is a structurally broken / unrestorable backup; proceeding to an irreversible TRUNCATE on a checkbox WARN is unacceptable (MAJOR-1). Shortfall raises BackupVerifyError/REFUSE_BACKUP. An excess (>80) indicates live drift the §3.7 reconciliation must resolve first (REFUSE_SCHEMA_DRIFT; should already have aborted in Phase 0, kept as defense-in-depth). WARN is reserved for benign explained equalities (none expected); the only PASS threshold is exact==80. |
| 7 | Add a Phase-0 already-clean short-circuit (all WIPE counts==0 → ALREADY_CLEAN, NO new backup) and record per-WIPE-table prod row counts in the manifest with a BACKUP_OF_EMPTY_STATE tag. | Each run dumps to a new ISO8601 dir, so a re-run after a completed wipe would back up the now-EMPTY trade state, which passes all structural verify checks and is indistinguishable from a good backup (MAJOR-4). Detecting all-empty WIPE tables before backup short-circuits to a safe no-op without producing a misleading empty-state backup; recording per-table prod counts (and tagging any dump taken while WIPE is empty) makes an accidental empty-state backup auditable rather than silently 'PASS'. |
| 8 | Ship WITHOUT @safety_window('market_hours'); make --emergency an inert reserved flag; do not add a market_hours key to central config. Remove the prior 'developer chooses' market_hours fork. | The central config declares only safety_windows.no_restart_overnight; there is no market_hours key (arcis_config.yaml:118-128, verified), and safety_window('market_hours') would raise ValueError at call time (_safety.py:268-271). Inventing a central-config key inside a script PR is out-of-scope and risky. The hard preconditions (watch-loop NSSM-stopped + re-checked, live-schema+FK reconciliation, broker-flat) are stronger guards than a clock window for a destructive op. --emergency only ever affected a window's audited bypass, so with no window it has zero effect — kept inert (banner-stated) so a future declared window doesn't change the CLI contract. A follow-up (#138) may add a real RTH window later. |
| 9 | Write an fsync'd WIPE_COMMITTED.marker after the TRUNCATE commit and before Phase 4, and fsync the SQLite archive before emptying; add an interrupted-run test asserting safe re-entry and that a committed-wipe-without-manifest is detectable. | Minor (d): the irreversible TRUNCATE commit and the final manifest are separated by Phases 4-7; a crash between them would leave no record that the wipe committed. A forensic marker (timestamp + server identity + per-table deltas), fsync'd immediately after commit, makes a committed-wipe-without-final-manifest detectable on re-entry, where ALREADY_CLEAN then handles convergence. fsyncing the SQLite archive (and its directory) before the empty step guarantees an interruption cannot lose both the live file and an unflushed archive. The test exercises both abort boundaries (post-commit, and post-archive/pre-empty) and asserts safe re-entry. |
| 10 | Document that prod is intentionally TOUCHED on the read path (reconciliation, pg_dump, dry-run preview) before any prod_guard/confirm short-circuit, and that this is safe and reviewed. | Minor (b): prod_guard gates the call to the wrapped function (the mutation), not raw reads (_safety.py:372 reads kwargs but the block only prevents the mutating call). The Phase-0 reconciliation, Phase-1 dump, and Phase-2 preview open read connections to and fully dump prod even in a dry run. This is intentional (read-only / off-box dump, no mutation) but non-obvious, so it is stated in the spec (§2.2) and surfaced in the operator banner ('dry-run still reads + dumps prod') to avoid surprise. The decorator execution order (safe_op outer → prod_guard inner; safe_op short-circuits to DryRunResult without calling the inner chain when confirm is absent) is documented alongside. |