# REPLACE Semantic-Divergence Audit (T0.12)

**Date:** 2026-05-11
**Sprint / Phase:** SP5 §J5/§J6 Phase 0
**Task:** T0.12 (precedes T0.4 `engine_aware_upsert` implementation)
**Authoritative dispatch table:** the per-table decisions in this audit are copied verbatim into the `_REPLACE_SEMANTICS` dict in `src/utils/db.py` by T0.4.

---

## 1. Purpose

Determine, per Phase 1 `action='replace'` target table, whether `engine_aware_upsert` on Postgres MUST emulate SQLite's `INSERT OR REPLACE` (DELETE-then-INSERT) or whether `INSERT … ON CONFLICT DO UPDATE` is semantically equivalent for our reader/writer call patterns.

Getting this wrong silently corrupts FK-related data over the 7-day observability window after the cutover — no test would catch it, because both branches succeed on the surface.

## 2. Why the two paths diverge

| | SQLite `INSERT OR REPLACE` | PG `INSERT … ON CONFLICT … DO UPDATE` |
|---|---|---|
| Operation | `DELETE WHERE pk=…` then `INSERT` (one atomic step) | In-place `UPDATE` of the existing row |
| `ON DELETE` triggers | Fire | Do not fire |
| `ON DELETE CASCADE` FKs | Cascade to child rows | Do not cascade |
| `AUTOINCREMENT` rowid | Reassigned to the next free value | Preserved |
| Constraint validation | Re-evaluated on INSERT | Evaluated as UPDATE (different ruleset for some defaults) |

For tables that have NONE of the above (no incoming FKs, no triggers, no rowid dependency), the two paths are functionally identical for any reader that keys off the table's declared PK / unique constraint.

## 3. Investigation methodology

For each candidate table I checked:

1. **Schema registry (`src/schema/registry.py`)** — TableDef entry: PK type/composition, columns, indexes, `foreign_keys` list, AUTOINCREMENT flag.
2. **Incoming FK references** — every other TableDef in the registry was scanned for `ForeignKeyDef(references_table=<this_table>)`. The result is exhaustive because the registry is the single source of truth for schema (per CLAUDE.md: "NEVER write `CREATE TABLE` in any file except `src/schema/registry.py`").
3. **Triggers** — `grep -ri "CREATE TRIGGER" src/` returned **zero** results. The codebase does not install any database triggers.
4. **rowid readers** — `grep -rn "rowid|ROWID" src/` returned only:
   - `src/schema/registry.py:47, 1483` — docstring comments
   - `src/schema/sqlite.py:99` — docstring comment
   - `src/sync/render_sync.py:22,573,602,682,694,713,717` — retiring file, deleted in Phase 4 (T4.1)
   No reader code depends on rowid stability for any of our target tables.
5. **Call-site context** — for each `INSERT OR REPLACE` site, I read 5–10 lines before/after to capture writer intent (idempotency model, PK supply pattern, dedup expectation).
6. **DELETE FROM queries** — checked whether any code path explicitly relies on cascade behavior via separate `DELETE FROM <table>` statements. Only `config_overrides` has explicit `DELETE FROM` queries (in `clear_overrides` endpoints) and they target the whole table, not specific rows.

## 4. Decision matrix

All 9 tables share three structural properties that drive the dispatch:

- **No incoming FK refs.** Registry scan returns zero references for every target.
- **No triggers.** `CREATE TRIGGER` does not appear anywhere in `src/`.
- **No INTEGER PK / AUTOINCREMENT.** Every target uses a TEXT PK (UUID, composite, or natural key). Rowid reassignment is invisible to readers because no reader keys off rowid.

| # | Table | Incoming FKs (DEL) | Outgoing FK CASCADE | Triggers | Reader rowid dep | Decision | Rationale (one line) |
|---|---|---|---|---|---|---|---|
| 1 | `data_freshness` | none | none | none | none | `in_place_update` | Composite TEXT PK; leaf table; readers use `WHERE source=? AND ticker=?`. |
| 2 | `build_score_history` | none | none | none | none | `in_place_update` | TEXT UUID PK; readers query by `score_date`. UUID-per-call writer means REPLACE never actually fires (separate concern in §6). |
| 3 | `config_overrides` | none | none | none | none | `in_place_update` | TEXT natural PK `setting_key`; clear-all is a separate DELETE statement, not a per-row cascade. |
| 4 | `system_metrics` | none | none | none | none | `in_place_update` | TEXT UUID PK; readers query by `timestamp`; writer always supplies fresh UUID (so REPLACE never fires; identical to `INSERT`). |
| 5 | `council_parameter_state` | none | none | none | none | `in_place_update` | TEXT natural PK `parameter_name`; single-row-per-key semantics; readers fetch by name. |
| 6 | `simulation_results` | none | none | none | none | `in_place_update` | TEXT UUID PK; writer supplies fresh UUID per call; readers query by `run_id`/`scenario`/`created_at`. |
| 7 | `walkforward_results` | none | none | none | none | `in_place_update` | TEXT PK `run_id`; explicit re-persist-on-rerun semantics (`Idempotent via primary key — re-persist overwrites`); ON CONFLICT DO UPDATE matches the documented intent. |
| 8 | `walkforward_trades` | none | none | none | none | `in_place_update` | TEXT PK `trade_id`; nested under walkforward_results rerun; same idempotency model. |
| 9 | `sp100_historical_constituents` | none | none | none | none | `in_place_update` | Composite TEXT PK `(ticker, added_date)`; CSV-driven, idempotent reload; readers query by ticker / date range. |

**Tally:**
- `in_place_update`: 9
- `delete_insert`: 0
- `operator_decision_needed`: 0

## 5. Per-table detail

### 5.1 `data_freshness`

- **Registry:** `src/schema/registry.py` (TableDef in registry; PK=`['source', 'ticker']`).
- **Columns:** `source` TEXT, `ticker` TEXT, `last_fetched_at` TEXT, `status` TEXT, `created_at` TEXT.
- **Use site:** `src/data_enrichment/staleness.py:42` — `record_fetch(source, ticker)`. INSERT OR REPLACE keyed on the composite PK; intent: "remember the last fetch time per (source, ticker)".
- **Incoming FKs:** none.
- **Outgoing FKs:** none.
- **Triggers:** none.
- **Rowid dependencies:** none. Readers in `staleness.py` use `WHERE source=? AND ticker=?` only.
- **Reader code paths:** `check_staleness(source, ticker)` in the same module — pure key-based read.
- **Decision:** `in_place_update`.
- **Rationale:** Composite-TEXT PK; pure leaf table; no FK refs in either direction; no triggers; reader code is key-based. ON CONFLICT (`source`, `ticker`) DO UPDATE is semantically equivalent to DELETE-then-INSERT here.

### 5.2 `build_score_history`

- **Registry:** PK=`score_id` TEXT; columns include `score_date`, build-score components, `created_at`.
- **Use site:** `src/evaluation/build_score.py:460` — `persist_build_score()`. INSERT OR REPLACE; the docstring says **"keyed on `score_date` so re-runs on the same day overwrite rather than duplicate"** but the actual PK is `score_id`. Each call passes `str(uuid.uuid4())` as `score_id`, so REPLACE never fires — every call is functionally an INSERT (this is a separate latent bug; see §6).
- **Incoming FKs:** none.
- **Outgoing FKs:** none.
- **Triggers:** none.
- **Rowid dependencies:** none. Readers in `evaluation/build_score.py` query by `score_date` and aggregate over windows.
- **Decision:** `in_place_update`.
- **Rationale:** Even when the writer is fixed to actually use `score_date` as the conflict target, the per-row semantics remain identical between engines — no FKs, no triggers, no rowid readers.

### 5.3 `config_overrides`

- **Registry:** PK=`setting_key` TEXT.
- **Use site:** `src/api/routes/system.py:566` — settings endpoint. INSERT OR REPLACE keyed on `setting_key`; intent: "upsert one config value".
- **Incoming FKs:** none.
- **Outgoing FKs:** none.
- **Triggers:** none.
- **Rowid dependencies:** none.
- **Sibling code paths (sibling-search):** four sites contain `DELETE FROM config_overrides` (`src/api/routes/system.py:585`, `src/config/overrides.py:160`, `src/api/cloud_routes/core.py:401`, `src/sync/render_sync.py:937`). All are full-table truncation (`clear all overrides`), not row-level cascade triggers from REPLACE behavior. They are unaffected by the dispatch decision.
- **Decision:** `in_place_update`.
- **Rationale:** TEXT natural-key PK; readers fetch by key; clear-all paths are independent. ON CONFLICT (`setting_key`) DO UPDATE matches semantics.

### 5.4 `system_metrics`

- **Registry:** PK=`snapshot_id` TEXT; columns are GPU/CPU/RAM/disk/Ollama metrics + `timestamp`.
- **Use site:** `src/monitoring/system_metrics.py:148` — `_store_snapshot(snapshot)`. Writer generates fresh `snapshot_id = str(uuid.uuid4())` at line 170 every call. So REPLACE never fires — every call is functionally an INSERT.
- **Incoming FKs:** none.
- **Outgoing FKs:** none.
- **Triggers:** none.
- **Rowid dependencies:** none. Readers in `health.py`/`analytics.py` query by `timestamp` ordering, not rowid.
- **Decision:** `in_place_update`.
- **Rationale:** Functional INSERT; per-row semantics identical between engines.

### 5.5 `council_parameter_state`

- **Registry:** PK=`parameter_name` TEXT.
- **Use site:** `src/council/value_tracker.py:120` — `log_parameter_change(...)`. INSERT OR REPLACE keyed on `parameter_name`; intent: "remember the current value for each tracked parameter" (single-row-per-parameter table).
- **Incoming FKs:** none.
- **Outgoing FKs:** none.
- **Triggers:** none.
- **Rowid dependencies:** none.
- **Adjacent table note:** `council_parameter_log` (separate table) gets an explicit `INSERT` at line 109 + an `UPDATE` at line 102 in the same transaction — `_state` is the projection of the latest entry, with no cross-table cascade.
- **Decision:** `in_place_update`.
- **Rationale:** Natural-key PK; readers fetch by name. ON CONFLICT (`parameter_name`) DO UPDATE matches.

### 5.6 `simulation_results`

- **Registry:** PK=`result_id` TEXT; ~40 columns of Monte Carlo / regime / outcome metrics.
- **Use site:** `src/simulation/engine.py:504` — `store_result(result, run_id, ...)`. Writer generates fresh `str(uuid.uuid4())` at line 516 every call. Functional INSERT.
- **Incoming FKs:** none.
- **Outgoing FKs:** none.
- **Triggers:** none.
- **Rowid dependencies:** none. Readers in `analytics.py`/`cloud_routes/core.py` query by `run_id`/`scenario`/`created_at`.
- **Decision:** `in_place_update`.
- **Rationale:** Functional INSERT; semantics identical between engines.

### 5.7 `walkforward_results`

- **Registry:** PK=`run_id` TEXT; columns include strategy/spec hash, pooled metrics, outcome state, window counts.
- **Use site:** `src/platform/rigor/walkforward_runner.py:308` — `persist_run(...)`. The function-level docstring states: **"Idempotent via primary key — re-persist overwrites."** So `run_id` IS expected to repeat on reruns, and the REPLACE branch genuinely fires (unlike the UUID-per-call sites).
- **Incoming FKs:** none (verified via registry scan).
- **Outgoing FKs:** none (the FK from `walkforward_trades.run_id → walkforward_results.run_id` is NOT declared in the registry — see §6.2).
- **Triggers:** none.
- **Rowid dependencies:** none. Readers in `cloud_routes/walkforward.py` and `platform/promotion.py` query by `run_id` / `strategy_id` / `created_at`.
- **Decision:** `in_place_update`.
- **Rationale:** ON CONFLICT (`run_id`) DO UPDATE SET all-non-pk-cols=EXCLUDED matches the documented "re-persist overwrites" intent exactly. No FK-cascade concern because the parent→child FK is not declared at the registry level; rerun cleanup of stale `walkforward_trades` rows is bounded by `run_id` semantics on the child table (§5.8), not by cascade.

### 5.8 `walkforward_trades`

- **Registry:** PK=`trade_id` TEXT; indexed on `run_id`, `(run_id, window_index)`, `quarantined`.
- **Use site:** `src/platform/rigor/walkforward_runner.py:355` — nested inside `persist_run()`. INSERT OR REPLACE keyed on `trade_id` per trade. `trade_id` is either supplied by the trade dict or generated as a fresh UUID.
- **Incoming FKs:** none.
- **Outgoing FKs:** none (no `ForeignKeyDef` declared; the logical parent is `walkforward_results.run_id` but it's not enforced).
- **Triggers:** none.
- **Rowid dependencies:** none.
- **Decision:** `in_place_update`.
- **Rationale:** Identical semantics on both engines. Note: re-persisting a `run_id` does NOT delete previously-written trades whose `trade_id` doesn't recur in the new run — this is true on both SQLite and PG (the SQLite path only "REPLACEs" rows with matching trade_id PKs). Cleanup-on-rerun is therefore caller-managed, not engine-managed, and the dispatch choice doesn't affect it. (See §6.3 for the latent stale-trade concern that exists on **both** engines today.)

### 5.9 `sp100_historical_constituents`

- **Registry:** PK=`['ticker', 'added_date']` (composite TEXT); columns include `removed_date`, `company_name`, `reason`.
- **Use site:** `src/platform/rigor/walkforward_universe.py:81` — `populate_constituents_table(db_path, csv_path)`. Loads a CSV row-by-row with INSERT OR REPLACE. Docstring: "Idempotent via INSERT OR REPLACE on composite (ticker, added_date)."
- **Incoming FKs:** none.
- **Outgoing FKs:** none.
- **Triggers:** none.
- **Rowid dependencies:** none. Readers (`resolve_universe_as_of(...)`) query by `added_date <= as_of_date AND (removed_date IS NULL OR removed_date > as_of_date)`.
- **Decision:** `in_place_update`.
- **Rationale:** Composite TEXT PK; readers are date-range based. ON CONFLICT (`ticker`, `added_date`) DO UPDATE matches the CSV-reload intent.

## 6. Concerns & latent bugs found during audit (NOT blocking T0.4 dispatch)

These are observations surfaced by the audit but do **NOT** change the dispatch decisions. They are flagged for follow-up tracking and are unrelated to the SQLite→PG cutover correctness.

### 6.1 UUID-per-call writers degrade "REPLACE" to "INSERT"

`build_score_history`, `simulation_results`, and `system_metrics` all generate a fresh `str(uuid.uuid4())` as the PK on every call. Because the PK is fresh each time, `INSERT OR REPLACE` never actually triggers REPLACE — every call is functionally an `INSERT`. This means:

- `build_score.persist_build_score()` will accumulate multiple rows per `score_date` on same-day reruns, contradicting its docstring "keyed on `score_date` so re-runs on the same day overwrite". The intended conflict target should be `score_date` (which needs a UNIQUE index added to the table).
- `system_metrics._store_snapshot()` and `simulation_engine.store_result()` are presumably meant to be append-only by `timestamp`/`run_id` — if so the `OR REPLACE` is dead code, but it doesn't cause divergence.

**Impact on dispatch decision:** none. Both engines behave identically on a fresh-UUID INSERT; the bug exists on SQLite today and is unchanged by the migration.

**Follow-up:** Sprint 5 backlog item — audit each UUID-per-call site, decide whether the table needs a unique index on the dedup column (e.g., `score_date`, `run_id, scenario`), and either fix the writer to pass the dedup key as the PK or replace `INSERT OR REPLACE` with plain `INSERT`.

### 6.2 walkforward_results → walkforward_trades FK not declared in registry

The walkforward_trades table has a logical parent–child relationship with walkforward_results via `run_id`, but the registry's `foreign_keys` list is empty for walkforward_trades. This means the cutover doesn't accidentally introduce a cascade behavior — but it also means there's no engine-enforced referential integrity. If a future T2.4-class refactor adds the FK declaration, the dispatch decision for walkforward_trades may need re-review (the registry's `ForeignKeyDef` does not currently carry an `on_delete` field — adding one would also be part of that hardening).

**Impact on dispatch decision:** none today. If the FK is added later, re-audit walkforward_trades.

### 6.3 Stale-trade cleanup on walkforward re-runs

When `persist_run(run_id=X)` re-runs with a different set of trades, any prior `walkforward_trades` rows with `run_id=X` and `trade_id` not present in the new run remain in the table. This is true on **both** SQLite (with OR REPLACE on trade_id PK) and PG (with ON CONFLICT DO UPDATE on trade_id) — neither engine cleans up orphans. The persistent-orphans issue is not a SQLite-vs-PG divergence, so the dispatch choice doesn't affect it.

**Impact on dispatch decision:** none. If true idempotency is wanted, `persist_run` should `DELETE FROM walkforward_trades WHERE run_id=?` before the loop — orthogonal to T0.4.

### 6.4 Spec said "10 tables", audit found 9 unique tables / 12 call sites

The spec section 2.4 references "10 `action='replace'` target tables" and the explicit list contains 9 names. The discrepancy resolves cleanly: section 2.6's call-site count (11 of the 17 sites) maps to **9 unique tables** because `walkforward_runner.py` has two REPLACE sites (308 + 355) hitting two tables (walkforward_results + walkforward_trades), and the table list deduplicates. The "10" in the prose is an off-by-one count; the table list is canonical. No 11th surprise table surfaced via the sibling grep.

**Impact on dispatch decision:** none. All 9 tables are classified.

## 7. Summary for `_REPLACE_SEMANTICS` dict (consumed by T0.4)

```python
# src/utils/db.py — populated from T0.12 audit
# Source: docs/audits/2026-05-11-modified-a-migration/replace-semantics-audit.md
_REPLACE_SEMANTICS = {
    "data_freshness":               "in_place_update",
    "build_score_history":          "in_place_update",
    "config_overrides":             "in_place_update",
    "system_metrics":               "in_place_update",
    "council_parameter_state":      "in_place_update",
    "simulation_results":           "in_place_update",
    "walkforward_results":          "in_place_update",
    "walkforward_trades":           "in_place_update",
    "sp100_historical_constituents":"in_place_update",
}
```

**Acceptance reminder for T0.4 (per spec):** if `engine_aware_upsert(action='replace')` is called on a table not present in this dict, the helper MUST raise `ValueError("engine_aware_upsert(action='replace') called on table <name> without semantic classification — add to _REPLACE_SEMANTICS dict")` to force every future `replace` target through this audit.

## 7.1. Post-audit hotfix additions

Tables added to `_REPLACE_SEMANTICS` after the original 9-table Phase-1 audit. Each entry confirms the table satisfies the same leaf-table criteria (no incoming FKs, no triggers, no rowid-dependent readers) so `in_place_update` is semantically identical to native SQLite `INSERT OR REPLACE`.

| Table | Added | Source | Audit notes |
|---|---|---|---|
| `operator_view_state` | Phase-3 revised T6 | (PR n/a — added with operator_view_state introduction) | TEXT PK; no incoming FKs; readers query by key. |
| `stress_test_results` | v0.36.11 watch-loop hardening (PR #1122) | `scripts/stress_test.py` migration off `INSERT OR REPLACE` | TEXT UUID PK (deterministic UUID5 keyed by scenario/start/end/model); leaf table. |
| `minute_bars` | v0.36.12 residual hotfix (collect_1min_bars sibling fix) | `scripts/collect_1min_bars.py` migration off `INSERT OR REPLACE` | Composite TEXT PK `(ticker, timestamp)`; no incoming FKs; no triggers; readers query by ticker + time window. yfinance bars are immutable for stable historical timestamps so in-place update preserves the documented "idempotent re-collection" intent. |

If you add a new entry here you MUST also update `tests/test_db_engine_aware_upsert.py::test_replace_semantics_dict_matches_audit_verbatim`'s `expected` dict.

## 8. Audit reproducibility

The findings are reproducible from a clean clone:

```bash
# Registry scan (1)
python -c "
from src.schema.registry import TABLES
targets = ['data_freshness','build_score_history','config_overrides','system_metrics',
           'council_parameter_state','simulation_results','walkforward_results',
           'walkforward_trades','sp100_historical_constituents']
for t in targets:
    td = TABLES[t]
    print(t, td.primary_key, [fk.references_table for fk in td.foreign_keys])

# Incoming-FK scan (2)
for name, td in TABLES.items():
    for fk in td.foreign_keys:
        if fk.references_table in targets:
            print('incoming:', name, '->', fk.references_table)
"

# Trigger scan (3)
grep -ri 'CREATE TRIGGER' src/

# rowid reader scan (4)
grep -rn 'rowid\|ROWID' src/

# Call-site sweep (5/sibling)
grep -rn 'INSERT OR REPLACE' src/
```

All 5 commands produce results consistent with §4's matrix.
