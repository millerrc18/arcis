# Sprint 5 — Modified-A Migration Implementation Plan

**Date:** 2026-05-11
**Status:** EXECUTION-READY (approved by feasibility + devil's advocate review)
**Source spec:** [spec.md](./spec.md)
**Total tasks:** 57
**Execution batches:** 21
**Consumed by:** `/arcis:code --spec docs/audits/2026-05-11-modified-a-migration/spec.md --plan docs/audits/2026-05-11-modified-a-migration/plan.md`

## Planner Notes

REVISION 2 (Devil's Advocate critical+major addressed): T0.0 + T0.12 audit tasks added to batch 1 (no-dep). T3.0 baseline env audit slotted into batch 1 of Phase 3 alongside T3.1 snapshots. Total: 57 tasks across 5 phases (was 54; +T0.0, +T0.12, +T3.0). 21-batch execution_order structure preserved exactly. Phase 0 grows from +33 to +61 tests (C1+C3+M3 coverage). T0.2 bumped low→standard (M1 quote+pct-aware rewrite is a real parser). T2.14 bumped to standard (M4 AST-based scanning). T3.2 precedence flip is kill-switched behind ARCIS_PG_CUTOVER_ENABLED=1 env var (M2) — merging T3.2 alone does NOT activate cutover on any developer machine. T0.11 retry exhaustion does sys.exit(1) so NSSM restarts (M3 zombie-watchdog fix) — SystemExit propagates past watch.py:1133 because Exception does not catch BaseException subclasses. T0.4 _REPLACE_SEMANTICS dict is populated from T0.12 audit, hard-coded per-table; ValueError raised if a new table is upserted with action='replace' without classification (M-safety: forces auditability). Target test delta: +134 (accept band +90 to +140 per M6); PM verifies actual vs band in T2.15 closeout. Worktree isolation MANDATORY for Phase 1, Phase 2 file migrations, and Phase 4 cleanup. Cutover window remains Saturday morning EDT. MINORs N1/N2/N3 listed in spec section 11 'Known Considerations' — NOT planner-tracked; deferred to post-cutover backlog.

## Phase Summary

| Phase | Description | Task Count |
|---|---|---|
| Phase 0 | Wrapper Foundation (no production behavior change; tests-only) | 13 |
| Phase 1 | UPSERT Migration (17 sites in 16 files via engine_aware_upsert) | 15 |
| Phase 2 | PRAGMA/Introspection Migration + CI workflow + static-analysis discipline | 15 |
| Phase 3 | Cutover Retry (operator-managed, kill-switch gated) | 6 |
| Phase 4 | Retirement (delete render_sync.py, reconcile.py, src/api/cloud_app.py, docs/ops cleanup) | 8 |
| **Total** | | **57** |

## Execution Order (parallel batches)

**Batch 1:** T0.0, T0.1, T0.3, T0.7, T0.8, T0.12

**Batch 2:** T0.2

**Batch 3:** T0.4, T0.5, T0.6

**Batch 4:** T0.9, T0.11

**Batch 5:** T0.10

**Batch 6:** T1.1, T1.2, T1.3, T1.4, T1.5, T1.6, T1.8, T1.9, T1.10, T1.12, T1.14

**Batch 7:** T1.7, T1.11, T1.13, T1.15

**Batch 8:** T2.1, T2.2, T2.3, T2.4, T2.5, T2.9, T2.10, T2.11

**Batch 9:** T2.6, T2.7, T2.12

**Batch 10:** T2.8, T2.13

**Batch 11:** T2.14

**Batch 12:** T2.15

**Batch 13:** T3.0, T3.1

**Batch 14:** T3.2

**Batch 15:** T3.3

**Batch 16:** T3.4

**Batch 17:** T3.5

**Batch 18:** T4.1, T4.3

**Batch 19:** T4.2, T4.4, T4.5, T4.6

**Batch 20:** T4.7

**Batch 21:** T4.8

## Tasks by Phase

### Phase 0 — Wrapper Foundation (no production behavior change; tests-only)

#### T0.0: Pre-flight audit: catalogue literal-% in SQL strings (C1)

- **Complexity:** low
- **Batch:** 1
- **Worktree required:** False
- **Dependencies:** none
- **Files in scope:** docs/audits/2026-05-11-modified-a-migration/literal-pct-audit.md
- **Files read-only:** src/scheduler/watch.py, src/notifications/platform_events.py, src/api/cloud_routes/platform.py
- **Scope fence:** Do NOT modify any production file. Audit doc only. Do NOT pre-decide rewriting strategy for category (c) sites — Phase 1+ tasks handle those.
- **Test strategy:** 0 new tests — audit doc. PM verifies doc enumerates ≥1 site per category and includes the activity_log LIKE site explicitly.

Grep all in-scope production files for SQL string literals containing literal `%` (LIKE wildcards, prefix patterns, embedded percent chars). For each site, categorise as: (a) already-safe (pure SQLite path, no rewrite needed), (b) requires `%%` escape (LIKE pattern that must survive psycopg2 format binding), (c) parameter-substitutable (move `'%X%'` to bound parameter `LIKE ?` with `'%X%'` as the param value). Output: docs/audits/2026-05-11-modified-a-migration/literal-pct-audit.md with per-site classification. Must enumerate at minimum: activity_log LIKE in Telegram poll path, any cloud_routes LIKE queries, council/value_tracker reporting queries, and walkforward universe filters. Include grep command used. Audit doc is the spec deliverable; no production code change.


#### T0.1: Add CompatRow + _RowFactoryCursor classes (C3-aware iteration)

- **Complexity:** low
- **Batch:** 1
- **Worktree required:** False
- **Dependencies:** none
- **Files in scope:** src/utils/db.py, tests/test_db_compatrow.py
- **Files read-only:** tests/conftest.py
- **Scope fence:** Do NOT modify connect_db() function yet. Do NOT add engine_aware_* helpers yet (T0.4-T0.8).
- **Test strategy:** 12 tests: (1-8 prior) int access, str access, __contains__, keys(), __len__, repr, _RowFactoryCursor.fetchone, _RowFactoryCursor.fetchall; (9-12 C3): tuple(CompatRow({'a':1,'b':2})) == (1,2); list(CompatRow(...)) == [1,2]; [v for v in row] == [1,2]; a,b = CompatRow({'a':1,'b':2}); assert (a,b) == (1,2). Also: dict(CompatRow({'a':1,'b':2})) raises TypeError or returns {'a':1,'b':2} per chosen contract (document the choice).

Add CompatRow class supporting BOTH row[int] AND row['col']. CRITICAL (C3): __iter__ yields iter(self._row.values()) so iteration yields VALUES, NOT keys — matching sqlite3.Row semantics. __len__ returns column count. keys() returns column-name iterator for explicit name access. Add _RowFactoryCursor wrapping psycopg2 cursor; overrides fetchone/fetchall/fetchmany to wrap returned dicts in CompatRow. Place class definitions BEFORE PostgresConnectionWrapper.


#### T0.2: Add quote+pct-aware rewrite to PostgresConnectionWrapper (C1 + M1)

- **Complexity:** standard
- **Batch:** 2
- **Worktree required:** False
- **Dependencies:** none
- **Files in scope:** src/utils/db.py, tests/test_db_wrapper_rewrite.py
- **Files read-only:** src/api/cloud_routes/platform.py, docs/audits/2026-05-11-modified-a-migration/literal-pct-audit.md
- **Scope fence:** Do NOT change connect_db() precedence rule. Do NOT touch CompatRow class.
- **Test strategy:** 10 tests: (1-6 prior) basic ? → %s; quote-preserve `?` inside string literal; perf <100us; no-op when no ?; cursor.execute() goes through rewrite; executemany() rewrites once. (7-10 C1) `_rewrite_question_to_pct("SELECT * FROM activity_log WHERE message LIKE '%position%' AND id=?")` produces SQL psycopg2 can execute without IndexError when params bound; `LIKE 'PCT%'` survives; `WHERE col = '50%'` survives; mixed `?`+`%` pattern in WHERE clause binds correctly against a real PG test fixture.

Modify PostgresConnectionWrapper.execute/executemany/cursor to use a real quote-and-percent-aware tokenizer for `?`→`%s` rewriting AND escape unpaired `%` to `%%`. Outside string literals: `?` → `%s`, unpaired `%` → `%%`. Inside single-quoted literals: leave both untouched. Inside double-quoted identifiers (PG): leave alone. The implementation tracks quote state through the string. Add _rewrite_question_to_pct(sql) module function. Bumped from low to standard complexity per M1 reconciliation: this is no longer a 1-line replace.


#### T0.3: Extract _resolve_conflict_target helper

- **Complexity:** low
- **Batch:** 1
- **Worktree required:** False
- **Dependencies:** none
- **Files in scope:** src/utils/db.py, tests/test_db_conflict_target.py
- **Files read-only:** scripts/sqlite_to_pg_migrate.py, src/schema/registry.py
- **Scope fence:** Do NOT modify scripts/sqlite_to_pg_migrate.py — the existing migrator keeps its inline helper.
- **Test strategy:** 5 tests: sync_conflict_col path, string PK path, list PK path, unknown table raises, sync_conflict_col stripping.

Extract conflict-target resolution from scripts/sqlite_to_pg_migrate.py:50-53 into src/utils/db.py as _resolve_conflict_target(table_name) returning list[str]. Precedence: TABLES[name].sync_conflict_col comma-split, else TABLES[name].primary_key. Raises ValueError on unknown table.


#### T0.12: Pre-flight audit: REPLACE semantic-divergence per table (C2)

- **Complexity:** standard
- **Batch:** 1
- **Worktree required:** False
- **Dependencies:** none
- **Files in scope:** docs/audits/2026-05-11-modified-a-migration/replace-semantics-audit.md
- **Files read-only:** src/schema/registry.py, src/data_enrichment/staleness.py, src/evaluation/build_score.py, src/api/routes/system.py, src/monitoring/system_metrics.py, src/council/value_tracker.py, src/simulation/engine.py, src/platform/rigor/walkforward_runner.py, src/platform/rigor/walkforward_universe.py
- **Scope fence:** Do NOT modify any production file. Audit doc only. T0.4 consumes the dispatch decisions into _REPLACE_SEMANTICS dict.
- **Test strategy:** 0 new tests — audit doc. PM verifies doc enumerates a decision for all 10 tables and includes the reasoning trail (FK refs, triggers, AUTOINCREMENT).

Audit the 10 `action='replace'` Phase 1 target tables for SQLite-INSERT-OR-REPLACE-vs-PG-DO-UPDATE semantic divergence. Tables: data_freshness, build_score_history, config_overrides, system_metrics, council_parameter_state, simulation_results, walkforward_results, walkforward_trades, sp100_historical_constituents, plus any others uncovered. For each table, document in docs/audits/2026-05-11-modified-a-migration/replace-semantics-audit.md: (1) incoming FK references (other tables pointing at this one with ON DELETE clauses — from schema registry), (2) outgoing FK refs with ON DELETE CASCADE (this table's deletion cascades), (3) AUTOINCREMENT / rowid dependencies (does any reader code rely on rowid stability?), (4) any triggers on DELETE or INSERT. Output the dispatch decision per table: 'in_place_update' (PG ON CONFLICT DO UPDATE OK, no semantic divergence) or 'delete_insert' (must emulate SQLite DELETE+INSERT atomically on PG). Audit doc deliverable; no production code change.


#### T0.4: Add engine_aware_upsert with per-table REPLACE-semantic dispatch (C2)

- **Complexity:** standard
- **Batch:** 3
- **Worktree required:** False
- **Dependencies:** none
- **Files in scope:** src/utils/db.py, tests/test_db_engine_aware_upsert.py
- **Files read-only:** scripts/sqlite_to_pg_migrate.py, src/schema/registry.py, docs/audits/2026-05-11-modified-a-migration/replace-semantics-audit.md
- **Scope fence:** Do NOT migrate any production INSERT OR REPLACE/IGNORE sites yet (Phase 1). Wrapper must not raise on tables with UUID PKs. _REPLACE_SEMANTICS values must match T0.12 audit doc verbatim.
- **Test strategy:** 12 tests parametrized engine=[sqlite, postgres]: (1-8 prior) action=replace inserts new + updates existing; action=ignore preserves + inserts; composite-PK target; sync_conflict_col target; unknown table raises; action=invalid raises. (9-12 C2) in_place_update path on a leaf table preserves FK refs; delete_insert path on a parent-with-cascade table fires cascade as expected; ValueError raised when table not in _REPLACE_SEMANTICS; transaction atomicity for delete_insert (rollback on INSERT failure restores DELETEd row).

Add engine_aware_upsert(conn, table_name, row_dict, action='replace'|'ignore') to src/utils/db.py. Branches on isinstance(conn, PostgresConnectionWrapper). SQLite path: INSERT OR REPLACE/IGNORE INTO {table} VALUES (?, ...). PG path action='ignore': INSERT INTO {table} VALUES (%s, ...) ON CONFLICT (target) DO NOTHING (mirrors migrator script). PG path action='replace': consult _REPLACE_SEMANTICS dict (populated from T0.12 audit, hard-coded per table). If 'in_place_update' → INSERT ... ON CONFLICT DO UPDATE SET non_target_col=EXCLUDED.non_target_col. If 'delete_insert' → wrap DELETE FROM {table} WHERE conflict_cols=... + INSERT in single transaction. Raises ValueError("engine_aware_upsert(action='replace') called on table {name} without semantic classification — add to _REPLACE_SEMANTICS dict") if table absent. Reuses _resolve_conflict_target from T0.3.


#### T0.5: Add engine_aware_table_list + engine_aware_column_info helpers

- **Complexity:** standard
- **Batch:** 3
- **Worktree required:** False
- **Dependencies:** none
- **Files in scope:** src/utils/db.py, tests/test_db_engine_aware_introspection.py
- **Files read-only:** src/startup_checks.py, src/schema/registry.py
- **Scope fence:** Do NOT migrate any production sqlite_master/PRAGMA call sites yet (Phase 2A).
- **Test strategy:** 6 tests parametrized engine=[sqlite, postgres].

Add engine_aware_table_list(conn) and engine_aware_column_info(conn, table) to src/utils/db.py. Shape-matched to PRAGMA table_info output.


#### T0.6: Add engine_aware_index_list + engine_aware_foreign_keys helpers

- **Complexity:** standard
- **Batch:** 3
- **Worktree required:** False
- **Dependencies:** none
- **Files in scope:** src/utils/db.py, tests/test_db_engine_aware_introspection.py
- **Files read-only:** src/schema/registry.py
- **Scope fence:** Do NOT migrate any production PRAGMA index_list / foreign_key_list call sites yet (Phase 2A).
- **Test strategy:** 4 tests parametrized engine=[sqlite, postgres].

Add engine_aware_index_list(conn, table) and engine_aware_foreign_keys(conn, table) to src/utils/db.py.


#### T0.7: Add sync_conflict_col to notifications_dedup TableDef

- **Complexity:** trivial
- **Batch:** 1
- **Worktree required:** False
- **Dependencies:** none
- **Files in scope:** src/schema/registry.py, CHANGELOG.md
- **Files read-only:** src/notifications/platform_events.py
- **Scope fence:** Do NOT migrate the INSERT OR IGNORE site at platform_events.py:96 yet (T1.7).
- **Test strategy:** 1 test in tests/test_schema.py.

Modify TABLES['notifications_dedup'] in src/schema/registry.py: add sync_conflict_col="event_type, dedup_key". Run validate-schema --fix. Update CHANGELOG.md.


#### T0.8: Add configure_sqlite_for_production helper + re-export _sqlite_only_connect

- **Complexity:** low
- **Batch:** 1
- **Worktree required:** False
- **Dependencies:** none
- **Files in scope:** src/utils/db.py, tests/test_db_configure_sqlite.py
- **Files read-only:** src/scheduler/watch.py, src/schema/sqlite.py
- **Scope fence:** Do NOT yet refactor src/scheduler/watch.py:1107-1132 (T2.12).
- **Test strategy:** 4 tests: SQLite applies all 4 PRAGMAs, PG no-ops with warning, re-export importable, _sqlite_only_connect returns proper Connection.

Add configure_sqlite_for_production(conn) to src/utils/db.py. No-op + warning log on PG. Add re-export of _sqlite_only_connect from src/schema/sqlite.py.


#### T0.9: Add pg_wrapper + parametrized_conn fixtures to conftest.py

- **Complexity:** low
- **Batch:** 4
- **Worktree required:** False
- **Dependencies:** none
- **Files in scope:** tests/conftest.py, tests/test_conftest_pg_wrapper.py
- **Files read-only:** src/utils/db.py, src/schema/postgres.py
- **Scope fence:** Do NOT modify existing postgres_session fixture or init_test_db.
- **Test strategy:** 2 sanity tests.

Add pg_wrapper fixture and parametrized_conn fixture. Schema bootstrap via src/schema/postgres.py.


#### T0.11: Add connect_db_with_pg_retry with fast-exit on exhaustion (M3)

- **Complexity:** low
- **Batch:** 4
- **Worktree required:** False
- **Dependencies:** none
- **Files in scope:** src/utils/db.py, tests/test_db_pg_retry.py
- **Files read-only:** src/scheduler/watch.py, src/config/__init__.py
- **Scope fence:** Do NOT modify _configure_database in watch.py (T2.12). Do NOT change connect_db() precedence rule (T3.2).
- **Test strategy:** 5 tests: (1) SQLite path returns sqlite3.Connection without retry; (2) PG path with mocked psycopg2.connect raising OperationalError twice then succeeding returns PostgresConnectionWrapper (asserts 2 retries via monkeypatched time.sleep counter); (3) PG path with mocked psycopg2.connect raising OperationalError 5x writes watchdog.txt (assert file content contains 'PG_CONNECT_FAIL'); (4 M3) Exhaustion calls sys.exit(1) — capture SystemExit, assert exit code == 1; (5 M3) Exhaustion writes watchdog.txt BEFORE sys.exit (assert file written even if SystemExit propagates).

Add connect_db_with_pg_retry(db_path=None, *, max_attempts=5, backoff_seconds=30) to src/utils/db.py. SQLite path: identity passthrough to connect_db() (no retry). PG path: try/except wrapping psycopg2.OperationalError with time.sleep(backoff_seconds) loop up to max_attempts. On exhaustion (M3 fix): (1) Write 'PG_CONNECT_FAIL: <exc>' to data/watchdog.txt (Path constructed from src.config.DB_PATH parent). (2) logger.critical('PG unreachable after %d attempts; exiting for NSSM restart', max_attempts). (3) sys.exit(1) — raises SystemExit which is NOT caught by Exception-only handlers; process exits cleanly; NSSM auto-restart kicks in. Module-level log emits info when retry succeeds with attempt count. Adds: `import sys`, `import time`, `from pathlib import Path` if not already imported.


#### T0.10: Create .github/workflows/pg-tests.yml CI workflow

- **Complexity:** standard
- **Batch:** 5
- **Worktree required:** False
- **Dependencies:** none
- **Files in scope:** .github/workflows/pg-tests.yml, scripts/bootstrap_pg_test_schema.py
- **Files read-only:** src/schema/postgres.py, requirements.txt
- **Scope fence:** Do NOT add other workflows.
- **Test strategy:** Workflow runs on the introducing PR; manual verification of first green run.

Create .github/workflows/pg-tests.yml. Trigger: on pull_request to main + push to main. Python 3.12. postgres:16-alpine sidecar. TEST_DATABASE_URL set. Bootstrap schema via scripts/bootstrap_pg_test_schema.py. Run pytest with --timeout=60. Assert test count >= 3682.


### Phase 1 — UPSERT Migration (17 sites in 16 files via engine_aware_upsert)

#### T1.1: Migrate short_interest_collector to engine_aware_upsert

- **Complexity:** low
- **Batch:** 1
- **Worktree required:** True
- **Dependencies:** none
- **Files in scope:** src/data_collection/short_interest_collector.py, tests/test_short_interest_collector_upsert.py
- **Files read-only:** src/utils/db.py, src/schema/registry.py
- **Scope fence:** Do NOT touch any other call site.
- **Test strategy:** 1 parametrized test.

Replace INSERT OR IGNORE at src/data_collection/short_interest_collector.py:111 with engine_aware_upsert(conn, 'short_interest', row_dict, action='ignore').


#### T1.2: Migrate research_collector to engine_aware_upsert

- **Complexity:** low
- **Batch:** 1
- **Worktree required:** True
- **Dependencies:** none
- **Files in scope:** src/data_collection/research_collector.py, tests/test_research_collector_upsert.py
- **Files read-only:** src/utils/db.py, src/schema/registry.py
- **Scope fence:** Do NOT touch other call sites.
- **Test strategy:** 1 parametrized test.

Replace INSERT OR IGNORE at src/data_collection/research_collector.py:121 with engine_aware_upsert.


#### T1.3: Migrate fed_collector to engine_aware_upsert

- **Complexity:** low
- **Batch:** 1
- **Worktree required:** True
- **Dependencies:** none
- **Files in scope:** src/data_collection/fed_collector.py, tests/test_fed_collector_upsert.py
- **Files read-only:** src/utils/db.py, src/schema/registry.py
- **Scope fence:** Do NOT touch other call sites.
- **Test strategy:** 1 parametrized test.

Replace INSERT OR IGNORE at src/data_collection/fed_collector.py:128 with engine_aware_upsert.


#### T1.4: Migrate edgar_collector INSERT OR IGNORE to engine_aware_upsert

- **Complexity:** low
- **Batch:** 1
- **Worktree required:** True
- **Dependencies:** none
- **Files in scope:** src/data_collection/edgar_collector.py, tests/test_edgar_collector_upsert.py
- **Files read-only:** src/utils/db.py, src/schema/registry.py
- **Scope fence:** Do NOT touch PRAGMA table_info (T2.1).
- **Test strategy:** 1 parametrized test.

Replace INSERT OR IGNORE at src/data_collection/edgar_collector.py:338 with engine_aware_upsert. Do NOT yet touch PRAGMA table_info at line 233 (T2.1).


#### T1.5: Migrate analyst_collector to engine_aware_upsert

- **Complexity:** low
- **Batch:** 1
- **Worktree required:** True
- **Dependencies:** none
- **Files in scope:** src/data_collection/analyst_collector.py, tests/test_analyst_collector_upsert.py
- **Files read-only:** src/utils/db.py, src/schema/registry.py
- **Scope fence:** Do NOT touch other call sites.
- **Test strategy:** 1 parametrized test.

Replace INSERT OR IGNORE at src/data_collection/analyst_collector.py:153 with engine_aware_upsert.


#### T1.6: Convert insider_collector plain INSERT to engine_aware_upsert

- **Complexity:** low
- **Batch:** 1
- **Worktree required:** True
- **Dependencies:** none
- **Files in scope:** src/data_collection/insider_collector.py, tests/test_insider_collector_upsert.py
- **Files read-only:** src/utils/db.py, src/schema/registry.py
- **Scope fence:** Do NOT touch other call sites. If sync_conflict_col addition is needed, include in PR with CHANGELOG entry.
- **Test strategy:** 1 parametrized test asserting dedup behaviour on both engines.

Wrap the plain INSERT at src/data_collection/insider_collector.py:118 in engine_aware_upsert(conn, 'insider_transactions', row_dict, action='ignore'). Verify the unique constraint is registered as sync_conflict_col in registry; if absent, add it and record in CHANGELOG.md.


#### T1.7: Migrate platform_events to engine_aware_upsert

- **Complexity:** low
- **Batch:** 2
- **Worktree required:** True
- **Dependencies:** none
- **Files in scope:** src/notifications/platform_events.py, tests/test_platform_events_upsert.py
- **Files read-only:** src/utils/db.py, src/schema/registry.py
- **Scope fence:** Do NOT touch notifications_dedup TableDef (T0.7).
- **Test strategy:** 1 parametrized test.

Replace INSERT OR IGNORE at src/notifications/platform_events.py:96 with engine_aware_upsert(conn, 'notifications_dedup', row_dict, action='ignore'). Depends on T0.7.


#### T1.8: Migrate council/protocol INSERT OR IGNORE to engine_aware_upsert

- **Complexity:** low
- **Batch:** 1
- **Worktree required:** True
- **Dependencies:** none
- **Files in scope:** src/council/protocol.py, tests/test_council_protocol_upsert.py
- **Files read-only:** src/utils/db.py, src/schema/registry.py
- **Scope fence:** Do NOT touch other call sites.
- **Test strategy:** 1 parametrized test.

Replace INSERT OR IGNORE at src/council/protocol.py:228 with engine_aware_upsert(conn, 'council_debug_log', row_dict, action='ignore').


#### T1.9: Migrate staleness to engine_aware_upsert (verify in_place vs delete_insert)

- **Complexity:** low
- **Batch:** 1
- **Worktree required:** True
- **Dependencies:** none
- **Files in scope:** src/data_enrichment/staleness.py, tests/test_staleness_upsert.py
- **Files read-only:** src/utils/db.py, src/schema/registry.py, docs/audits/2026-05-11-modified-a-migration/replace-semantics-audit.md
- **Scope fence:** Do NOT touch other call sites.
- **Test strategy:** 1 parametrized test asserting UPDATE/UPSERT semantics match T0.12 dispatch decision.

Replace INSERT OR REPLACE at src/data_enrichment/staleness.py:42 with engine_aware_upsert(conn, 'data_freshness', row_dict, action='replace'). Verify _REPLACE_SEMANTICS['data_freshness'] matches T0.12 audit. Test asserts the chosen semantic via FK-cascade fixture if applicable.


#### T1.10: Migrate build_score to engine_aware_upsert

- **Complexity:** low
- **Batch:** 1
- **Worktree required:** True
- **Dependencies:** none
- **Files in scope:** src/evaluation/build_score.py, tests/test_build_score_upsert.py
- **Files read-only:** src/utils/db.py, src/schema/registry.py, docs/audits/2026-05-11-modified-a-migration/replace-semantics-audit.md
- **Scope fence:** Do NOT touch other call sites.
- **Test strategy:** 1 parametrized test asserting semantic match.

Replace INSERT OR REPLACE at src/evaluation/build_score.py:460 with engine_aware_upsert(conn, 'build_score_history', row_dict, action='replace'). Verify semantic dispatch matches T0.12.


#### T1.11: Migrate api/routes/system to engine_aware_upsert

- **Complexity:** low
- **Batch:** 2
- **Worktree required:** True
- **Dependencies:** none
- **Files in scope:** src/api/routes/system.py, tests/test_api_routes_system_upsert.py
- **Files read-only:** src/utils/db.py, src/schema/registry.py
- **Scope fence:** Do NOT touch other call sites.
- **Test strategy:** 1 parametrized test asserting semantic match.

Replace INSERT OR REPLACE at src/api/routes/system.py:566 with engine_aware_upsert(conn, 'config_overrides', row_dict, action='replace').


#### T1.12: Migrate system_metrics to engine_aware_upsert

- **Complexity:** low
- **Batch:** 1
- **Worktree required:** True
- **Dependencies:** none
- **Files in scope:** src/monitoring/system_metrics.py, tests/test_system_metrics_upsert.py
- **Files read-only:** src/utils/db.py, src/schema/registry.py
- **Scope fence:** Do NOT touch other call sites.
- **Test strategy:** 1 parametrized test.

Replace INSERT OR REPLACE + dynamic placeholders at src/monitoring/system_metrics.py:131-152 with engine_aware_upsert. Remove unused import sqlite3 at line 14.


#### T1.13: Migrate council/value_tracker to engine_aware_upsert

- **Complexity:** low
- **Batch:** 2
- **Worktree required:** True
- **Dependencies:** none
- **Files in scope:** src/council/value_tracker.py, tests/test_council_value_tracker_upsert.py
- **Files read-only:** src/utils/db.py, src/schema/registry.py
- **Scope fence:** Do NOT touch IN list at line 306.
- **Test strategy:** 1 parametrized test asserting semantic match.

Replace INSERT OR REPLACE at src/council/value_tracker.py:120 with engine_aware_upsert(conn, 'council_parameter_state', row_dict, action='replace'). Do NOT touch dynamic IN-list at line 306.


#### T1.14: Migrate simulation/engine INSERT OR REPLACE to engine_aware_upsert

- **Complexity:** low
- **Batch:** 2
- **Worktree required:** True
- **Dependencies:** none
- **Files in scope:** src/simulation/engine.py, tests/test_simulation_engine_upsert.py
- **Files read-only:** src/utils/db.py, src/schema/registry.py
- **Scope fence:** Do NOT touch other call sites.
- **Test strategy:** 1 parametrized test.

Replace INSERT OR REPLACE at src/simulation/engine.py:504 with engine_aware_upsert(conn, 'simulation_results', row_dict, action='replace').


#### T1.15: Migrate walkforward_runner + walkforward_universe to engine_aware_upsert

- **Complexity:** low
- **Batch:** 2
- **Worktree required:** True
- **Dependencies:** none
- **Files in scope:** src/platform/rigor/walkforward_runner.py, src/platform/rigor/walkforward_universe.py, tests/test_walkforward_upsert.py
- **Files read-only:** src/utils/db.py, src/schema/registry.py
- **Scope fence:** Do NOT touch other call sites.
- **Test strategy:** 3 parametrized tests asserting semantic match per target table.

Replace INSERT OR REPLACE × 2 at walkforward_runner.py:308 (walkforward_results) + line 355 (walkforward_trades). Replace INSERT OR REPLACE at walkforward_universe.py:81 (sp100_historical_constituents). Each verifies T0.12 semantic dispatch.


### Phase 2 — PRAGMA/Introspection Migration + CI workflow + static-analysis discipline

#### T2.1: Migrate edgar_collector PRAGMA table_info to engine_aware_column_info

- **Complexity:** low
- **Batch:** 1
- **Worktree required:** True
- **Dependencies:** none
- **Files in scope:** src/data_collection/edgar_collector.py, tests/test_edgar_collector_introspection.py
- **Files read-only:** src/utils/db.py
- **Scope fence:** Do NOT re-touch INSERT OR IGNORE migration (T1.4).
- **Test strategy:** 1 parametrized test.

Replace PRAGMA table_info(edgar_filings) at src/data_collection/edgar_collector.py:233 with engine_aware_column_info.


#### T2.2: Migrate data_collection/retention sqlite_master + PRAGMA

- **Complexity:** low
- **Batch:** 1
- **Worktree required:** True
- **Dependencies:** none
- **Files in scope:** src/data_collection/retention.py, tests/test_retention_introspection.py
- **Files read-only:** src/utils/db.py
- **Scope fence:** Do NOT touch other call sites.
- **Test strategy:** 1 parametrized test.

Replace sqlite_master query at src/data_collection/retention.py:108 with engine_aware_table_list. PRAGMA table_info at line 116 with engine_aware_column_info.


#### T2.3: Migrate event_risk_score PRAGMA table_info

- **Complexity:** low
- **Batch:** 1
- **Worktree required:** True
- **Dependencies:** none
- **Files in scope:** src/features/event_risk_score.py, tests/test_event_risk_score_introspection.py
- **Files read-only:** src/utils/db.py
- **Scope fence:** Do NOT change feature logic.
- **Test strategy:** 1 parametrized test.

Replace PRAGMA table_info at src/features/event_risk_score.py:48 with engine_aware_column_info.


#### T2.4: Migrate model_monitor PRAGMA table_info

- **Complexity:** low
- **Batch:** 1
- **Worktree required:** True
- **Dependencies:** none
- **Files in scope:** src/evaluation/model_monitor.py, tests/test_model_monitor_introspection.py
- **Files read-only:** src/utils/db.py
- **Scope fence:** Do NOT touch monitoring logic.
- **Test strategy:** 1 parametrized test.

Replace PRAGMA table_info at src/evaluation/model_monitor.py:176 with engine_aware_column_info.


#### T2.5: Migrate cosine_similarity PRAGMA table_info

- **Complexity:** low
- **Batch:** 1
- **Worktree required:** True
- **Dependencies:** none
- **Files in scope:** src/platform/features/cosine_similarity.py, tests/test_cosine_similarity_introspection.py
- **Files read-only:** src/utils/db.py
- **Scope fence:** Do NOT touch feature logic.
- **Test strategy:** 1 parametrized test.

Replace PRAGMA table_info at src/platform/features/cosine_similarity.py:161 with engine_aware_column_info.


#### T2.6: Migrate system_validator PRAGMA + sqlite_master

- **Complexity:** standard
- **Batch:** 2
- **Worktree required:** True
- **Dependencies:** none
- **Files in scope:** src/evaluation/system_validator.py, tests/test_system_validator_introspection.py
- **Files read-only:** src/utils/db.py
- **Scope fence:** Do NOT migrate other PRAGMAs in this file.
- **Test strategy:** 1 parametrized test.

Replace PRAGMA journal_mode at src/evaluation/system_validator.py:165 (wrap in isinstance check). Replace sqlite_master at line 175 with engine_aware_table_list.


#### T2.7: Migrate schema/validator PRAGMA + sqlite_master (CRITICAL)

- **Complexity:** standard
- **Batch:** 2
- **Worktree required:** True
- **Dependencies:** none
- **Files in scope:** src/schema/validator.py, tests/test_schema_validator_engine_aware.py
- **Files read-only:** src/utils/db.py, src/schema/registry.py
- **Scope fence:** Do NOT touch src/schema/sqlite.py or src/schema/postgres.py.
- **Test strategy:** 2 parametrized tests.

Replace sqlite_master at src/schema/validator.py:43 with engine_aware_table_list. Replace PRAGMA table_info at line 61 with engine_aware_column_info. Was the 2026-05-10 cutover blocker.


#### T2.8: Migrate startup_checks sqlite_master COUNT × 2 (CRITICAL)

- **Complexity:** standard
- **Batch:** 3
- **Worktree required:** True
- **Dependencies:** none
- **Files in scope:** src/startup_checks.py, tests/test_startup_checks_engine_aware.py
- **Files read-only:** src/utils/db.py, src/schema/validator.py
- **Scope fence:** Do NOT touch _check_render_postgres.
- **Test strategy:** 1 parametrized test.

Replace sqlite_master COUNT(*) queries at src/startup_checks.py:151-154 and 164-167 with len(engine_aware_table_list(conn)). Remove unused import sqlite3 at line 16.


#### T2.9: Rewrite council/agent_data julianday SQL

- **Complexity:** low
- **Batch:** 1
- **Worktree required:** True
- **Dependencies:** none
- **Files in scope:** src/council/agent_data.py, tests/test_council_agent_data_julianday.py
- **Files read-only:** src/utils/db.py
- **Scope fence:** Do NOT change council debate logic.
- **Test strategy:** 1 parametrized test.

At src/council/agent_data.py:91, replace julianday('now') - julianday(actual_entry_time) with Python-side computation. Pass days_held as parameter.


#### T2.10: Rewrite api/routes/ib_status date('now')

- **Complexity:** low
- **Batch:** 1
- **Worktree required:** True
- **Dependencies:** none
- **Files in scope:** src/api/routes/ib_status.py, tests/test_ib_status_date_now.py
- **Files read-only:** src/utils/db.py
- **Scope fence:** Do NOT change route logic.
- **Test strategy:** 1 parametrized test.

At src/api/routes/ib_status.py:55, replace WHERE date(created_at) = date('now') with parameterized form passing date.today().isoformat().


#### T2.11: Rewrite shadow_trading/executor date('now')

- **Complexity:** low
- **Batch:** 1
- **Worktree required:** True
- **Dependencies:** none
- **Files in scope:** src/shadow_trading/executor.py, tests/test_shadow_trading_executor_date_now.py
- **Files read-only:** src/utils/db.py
- **Scope fence:** Do NOT touch other call sites.
- **Test strategy:** 1 parametrized test.

At src/shadow_trading/executor.py:776, replace date('now') with parameterized form.


#### T2.12: Refactor watch.py _configure_database: PRAGMA helper + PG retry wrapper (with fast-exit)

- **Complexity:** standard
- **Batch:** 2
- **Worktree required:** True
- **Dependencies:** none
- **Files in scope:** src/scheduler/watch.py, tests/test_watch_pragma_isolation.py
- **Files read-only:** src/utils/db.py
- **Scope fence:** Do NOT touch backup API at lines 1164-1165. Do NOT touch other connect_db sites. Do NOT refactor watch_loop control flow.
- **Test strategy:** 3 parametrized tests: (a) _configure_database runs cleanly on both engines; (b) calls connect_db_with_pg_retry with max_attempts=5 (monkeypatch assert); (c) M3 — simulate T0.11 retry exhaustion (mock connect_db_with_pg_retry to raise SystemExit(1)); assert SystemExit propagates past line 1133 and the watch process would exit (capture SystemExit at test boundary).

At src/scheduler/watch.py:1107-1132 (_configure_database): (1) Replace inline PRAGMA cluster with configure_sqlite_for_production(conn) helper from T0.8 (no-op on PG). (2) Replace bare connect_db(DB_PATH) with connect_db_with_pg_retry(DB_PATH, max_attempts=5, backoff_seconds=30) from T0.11. (3) M3 verification: confirm the surrounding `except Exception` at line 1133 does NOT catch SystemExit raised by sys.exit(1) in T0.11 retry exhaustion — SystemExit inherits BaseException not Exception. Add a comment at line 1133 stating: '# SystemExit from connect_db_with_pg_retry retry exhaustion is intentionally uncaught — NSSM restarts the service.' Backup API at lines 1164-1165 stays raw SQLite.


#### T2.13: Extend test_connect_db_discipline.py allowlist

- **Complexity:** standard
- **Batch:** 3
- **Worktree required:** True
- **Dependencies:** none
- **Files in scope:** tests/test_connect_db_discipline.py
- **Files read-only:** src/schema/sqlite.py, src/scheduler/watch.py, src/training/trainer.py
- **Scope fence:** Do NOT modify existing 4-file allowlist tests.
- **Test strategy:** 8 test pairs + 4 retiring-allowlist tests.

Extend tests/test_connect_db_discipline.py: permanent allowlist (sqlite/registry/watch:1164-1165/trainer:1171), retiring-allowlist (render_sync.py, reconcile.py with markers).


#### T2.14: Create test_no_sqlite_isms_in_pg_safe_files.py (AST-based, M4)

- **Complexity:** standard
- **Batch:** 4
- **Worktree required:** True
- **Dependencies:** none
- **Files in scope:** tests/test_no_sqlite_isms_in_pg_safe_files.py
- **Files read-only:** src/utils/db.py, tests/test_connect_db_discipline.py
- **Scope fence:** Do NOT add tests for raw sqlite3.connect (test_connect_db_discipline.py scope). Bumped to standard complexity per M4 — AST traversal + multi-pattern detection.
- **Test strategy:** 5 test functions; assert ZERO offenders in scanned files. Include positive test fixtures (a small fixture file containing each anti-pattern) to verify the AST detector catches them.

Create tests/test_no_sqlite_isms_in_pg_safe_files.py. M4 REVISION: use AST-based scanning, NOT substring scan. The visitor traverses ast.Str/ast.Constant/ast.JoinedStr/ast.FormattedValue/ast.BinOp(op=Add) nodes, reconstructing full strings where possible. Detects: (1) String literals containing INSERT OR REPLACE/IGNORE — even when split across f-string fragments or .format() calls. (2) SQL-keyword strings (INSERT/SELECT/UPDATE/DELETE/VALUES) containing literal `?` placeholders outside quoted literals (heuristic for unrewritten placeholders). (3) String-concatenation chains where any segment contains SQLite-ism fragments. (4) f-string fragments where the {expr} portion evaluates to constant REPLACE or IGNORE (e.g. `f'INSERT OR {action.upper()} INTO ...'` if action is a constant). Define ALLOWLIST including retiring-files src/sync/render_sync.py + src/sync/reconcile.py with `# RETIRING: delete in SP5 §J6 Phase 4` markers. Add 4-5 test functions: test_no_insert_or_replace_or_ignore_ast, test_no_pragma_in_pg_safe_files (line-range allowlist for watch.py:1164-1165), test_no_sqlite_master_references_ast, test_no_sqlite_date_functions_ast, test_no_unrewritten_question_placeholders_ast.


#### T2.15: Bump CI test floor + Phase 0 closeout reconciliation (M6)

- **Complexity:** trivial
- **Batch:** 5
- **Worktree required:** False
- **Dependencies:** none
- **Files in scope:** .github/workflows/pg-tests.yml, CLAUDE.md
- **Files read-only:** docs/audits/2026-05-11-modified-a-migration/_design_raw.json
- **Scope fence:** Do NOT modify any test file.
- **Test strategy:** Workflow run verifies pass; PM-side count vs accept-band check.

Update .github/workflows/pg-tests.yml minimum-test-count step to match actual Phase 2 end-state (per spec section 5.3 target +134; accept band +90 to +140). PM verifies actual delta is within band; if outside, document why in CHANGELOG. Update CLAUDE.md test-floor lineage paragraph with actual numbers.


### Phase 3 — Cutover Retry (operator-managed, kill-switch gated)

#### T3.0: Pre-cutover: verify NSSM baseline env preservation (M5)

- **Complexity:** trivial
- **Batch:** 1
- **Worktree required:** False
- **Dependencies:** none
- **Files in scope:** docs/operator-guide.md
- **Scope fence:** No code change. Documentation + operator verification only.
- **Test strategy:** PM verifies docs section exists and lists PYTHONUTF8 + ARCIS_DB_PATH explicitly.

Operator step before T3.1: run `nssm get ArcisWatchLoop AppEnvironmentExtra` and document the current env-var list in docs/operator-guide.md under a new 'NSSM Production Environment' section. Required baseline vars: PYTHONUTF8=1 (UTF-8 codec safety for TRL chat_template_utils on Windows — confirmed 2026-05-10), ARCIS_DB_PATH=C:/arcis/data/ai_research_desk.sqlite3, OLLAMA_BASE_URL (LLM endpoint), and any others currently set. Acceptance: env-var list documented + PM verifies T3.3 uses APPEND syntax (not overwrite) when adding DATABASE_URL and ARCIS_PG_CUTOVER_ENABLED. PM blocks T3.3 dispatch if env-var list is empty or missing PYTHONUTF8.


#### T3.1: Pre-cutover snapshots (SQLite + PG)

- **Complexity:** trivial
- **Batch:** 1
- **Worktree required:** False
- **Dependencies:** none
- **Files in scope:** 
- **Scope fence:** No code changes. Operator step only.
- **Test strategy:** PM agent verifies snapshot files exist and non-zero size.

Operator step: cp SQLite snapshot + pg_dump PG snapshot. PM verifies files exist before greenlighting T3.2.


#### T3.2: Land precedence-flip commit (M2 kill-switched)

- **Complexity:** low
- **Batch:** 2
- **Worktree required:** False
- **Dependencies:** none
- **Files in scope:** src/utils/db.py, tests/test_db_precedence_flip.py
- **Scope fence:** Do NOT modify any other production file. M2 strict: behaviour with ARCIS_PG_CUTOVER_ENABLED unset MUST be identical to pre-T3.2 behaviour.
- **Test strategy:** 5 tests covering the 4-way truth table above + a 'merging to main on developer machine with stale DATABASE_URL in shell does not route to PG' regression test.

Modify src/utils/db.py:connect_db() (lines 98-148): when ALL of (a) os.environ.get('ARCIS_PG_CUTOVER_ENABLED') == '1' AND (b) DATABASE_URL.startswith('postgres') are true, IGNORE db_path argument with one-time warning log; else preserve current SQLite precedence. M2 INVARIANT: merging T3.2 to main MUST NOT change watch loop behaviour on any developer machine — the env gate defaults off. Tests assert: (a) gate=off + DATABASE_URL set + db_path passed → sqlite3.Connection at db_path (NOT routed to PG); (b) gate=on + DATABASE_URL set + db_path passed → PostgresConnectionWrapper; (c) gate=off + DATABASE_URL unset + db_path passed → sqlite3.Connection at db_path; (d) gate=on + DATABASE_URL unset → still SQLite (gate is gate, not override).


#### T3.3: Operator: NSSM env set (append) + restart

- **Complexity:** trivial
- **Batch:** 3
- **Worktree required:** False
- **Dependencies:** none
- **Files in scope:** 
- **Files read-only:** docs/operator-guide.md
- **Scope fence:** No code changes. Operator-managed step.
- **Test strategy:** Operator verifies process alive + confirms PYTHONUTF8 still set via `nssm get` post-restart.

Saturday morning: nssm set ArcisWatchLoop AppEnvironmentExtra <ENTIRE EXISTING ENV STRING from T3.0> + DATABASE_URL=postgresql://halcyon:...@localhost:5432/halcyon + ARCIS_PG_CUTOVER_ENABLED=1. M5: use APPEND syntax — do NOT overwrite existing env (PYTHONUTF8/ARCIS_DB_PATH must remain). Run nssm restart ArcisWatchLoop.


#### T3.4: 30-min smoke + 7-day observability (including activity_log LIKE C1 coverage)

- **Complexity:** trivial
- **Batch:** 4
- **Worktree required:** False
- **Dependencies:** none
- **Files in scope:** 
- **Files read-only:** arcis.log (operator-side)
- **Scope fence:** No code changes.
- **Test strategy:** PM verifies via SQL query on Docker PG; specifically asserts an activity_log LIKE query succeeded.

PM/operator tails arcis.log for 30 min. Verify watch loop tick, position monitor, Telegram poll (activity_log LIKE '%position%' — explicit C1 regression coverage), dashboard render. After 30-min OK, 7-day observability window begins. Verify zero IndexError/TypeError from psycopg2 binding.


#### T3.5: Cutover rollback procedure (contingent)

- **Complexity:** trivial
- **Batch:** 5
- **Worktree required:** False
- **Dependencies:** none
- **Files in scope:** docs/audits/2026-05-MM-cutover-retry-rollback.md (contingent)
- **Scope fence:** Conditional task — only executes if T3.4 fails.
- **Test strategy:** Operator + PM verify SQLite path resumes.

If T3.4 fails: operator runs nssm set ArcisWatchLoop AppEnvironmentExtra <baseline without ARCIS_PG_CUTOVER_ENABLED, optionally also without DATABASE_URL>; nssm restart. SQLite path resumes. Single env unset (ARCIS_PG_CUTOVER_ENABLED) is sufficient to revert — DATABASE_URL alone no longer flips precedence.


### Phase 4 — Retirement (delete render_sync.py, reconcile.py, src/api/cloud_app.py, docs/ops cleanup)

#### T4.1: Delete src/sync/render_sync.py + watch.py call site

- **Complexity:** standard
- **Batch:** 1
- **Worktree required:** True
- **Dependencies:** none
- **Files in scope:** src/sync/render_sync.py, src/scheduler/watch.py, tests/test_render_sync.py, CHANGELOG.md
- **Scope fence:** Do NOT touch other watch.py paths. Do NOT touch reconcile.py (T4.2).
- **Test strategy:** 1 test in test_repo_structure.py.

Delete src/sync/render_sync.py (1364 LOC). Remove RenderSyncThread import + start_render_sync() call at src/scheduler/watch.py:1346-1347. Delete tests/test_render_sync.py if exists. Update CHANGELOG.md.


#### T4.2: Delete src/sync/reconcile.py + remove retiring-allowlist

- **Complexity:** low
- **Batch:** 2
- **Worktree required:** True
- **Dependencies:** none
- **Files in scope:** src/sync/reconcile.py, tests/test_connect_db_discipline.py, tests/test_no_sqlite_isms_in_pg_safe_files.py, CHANGELOG.md
- **Scope fence:** Do NOT touch render_sync.py (T4.1).
- **Test strategy:** 1 test in test_repo_structure.py.

Delete src/sync/reconcile.py. Remove retiring-allowlist entries from tests/test_connect_db_discipline.py and tests/test_no_sqlite_isms_in_pg_safe_files.py. Update CHANGELOG.md.


#### T4.3: Delete src/api/cloud_app.py

- **Complexity:** low
- **Batch:** 1
- **Worktree required:** True
- **Dependencies:** none
- **Files in scope:** src/api/cloud_app.py, tests/test_phase_d_auth_and_safety.py, tests/test_safety_oneliners.py, CHANGELOG.md
- **Files read-only:** src/api/app.py
- **Scope fence:** Do NOT touch src/api/app.py (the replacement).
- **Test strategy:** 1 test in test_repo_structure.py.

Delete src/api/cloud_app.py (341 LOC). Remove obsolete imports at tests/test_phase_d_auth_and_safety.py:100 and tests/test_safety_oneliners.py:89. Update CHANGELOG.md.


#### T4.4: Collapse cloud_routes/platform.py dual-mode branches + remove ARCIS_PG_CUTOVER_ENABLED env gate

- **Complexity:** low
- **Batch:** 3
- **Worktree required:** True
- **Dependencies:** none
- **Files in scope:** src/api/cloud_routes/platform.py, src/utils/db.py, tests/test_db_precedence_flip.py, tests/test_cloud_routes_platform_collapsed.py
- **Scope fence:** Do NOT touch other cloud_routes files.
- **Test strategy:** 1 parametrized test + updated precedence tests (env gate removed).

At src/api/cloud_routes/platform.py lines 43-70, remove if database_url: branching. Use connect_db() directly. ALSO: remove the ARCIS_PG_CUTOVER_ENABLED env-gate code from src/utils/db.py:connect_db() now that cutover is stable; DATABASE_URL alone is sufficient. Test floor: update tests/test_db_precedence_flip.py to match new behaviour.


#### T4.5: Collapse cloud_routes notifications + kpis_compute + walkforward

- **Complexity:** low
- **Batch:** 3
- **Worktree required:** True
- **Dependencies:** none
- **Files in scope:** src/api/cloud_routes/notifications.py, src/api/cloud_routes/kpis_compute.py, src/api/cloud_routes/walkforward.py
- **Files read-only:** src/utils/db.py
- **Scope fence:** Do NOT touch platform.py (T4.4) or broker_exceptions/preflight (T4.6).
- **Test strategy:** 3 parametrized tests.

Remove if database_url: branches in notifications.py, kpis_compute.py, walkforward.py.


#### T4.6: Collapse cloud_routes broker_exceptions + preflight

- **Complexity:** low
- **Batch:** 3
- **Worktree required:** True
- **Dependencies:** none
- **Files in scope:** src/api/cloud_routes/broker_exceptions.py, src/api/cloud_routes/preflight.py
- **Files read-only:** src/utils/db.py
- **Scope fence:** Do NOT touch other cloud_routes files.
- **Test strategy:** 2 parametrized tests.

Remove if database_url: branches at broker_exceptions.py + preflight.py.


#### T4.7: Update CHANGELOG + docs/operator-guide.md (full env-var list, M5)

- **Complexity:** trivial
- **Batch:** 4
- **Worktree required:** False
- **Dependencies:** none
- **Files in scope:** docs/operator-guide.md, CHANGELOG.md
- **Files read-only:** docs/audits/2026-05-11-modified-a-migration/_design_raw.json
- **Scope fence:** Do NOT touch code files.
- **Test strategy:** Manual PM review.

Update docs/operator-guide.md with: (1) canonical NSSM env-var list — PYTHONUTF8, ARCIS_DB_PATH, DATABASE_URL, OLLAMA_BASE_URL, and any others — per M5; (2) cutover rollback steps referencing ARCIS_PG_CUTOVER_ENABLED unset; (3) reference to _design_raw.json. CHANGELOG.md final SP5 §J5/§J6 entry.


#### T4.8: Sprint 5 closeout: version bump + git tag + gh release

- **Complexity:** trivial
- **Batch:** 5
- **Worktree required:** False
- **Dependencies:** none
- **Files in scope:** src/version.py, CLAUDE.md, CHANGELOG.md
- **Files read-only:** docs/versioning-policy.md
- **Scope fence:** Final task.
- **Test strategy:** Manual PM/operator confirmation.

Bump src/version.py per docs/versioning-policy.md. Tag SP5-final-2026-MM-DD. gh release. Update CLAUDE.md test-floor lineage with final number.


