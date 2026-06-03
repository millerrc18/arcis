# Clean-Slate Wipe — Implementation Plan

**Spec:** docs/superpowers/specs/2026-06-03-clean-slate-wipe-design.md
**Target:** `scripts/clean_slate_wipe.py` (W21 capstone #95)

**Execution order:** [[1, 7, 8], [2, 3, 4], [5, 6, 9], [10], [11, 15], [12, 13, 14]]

**Notes:** Batch 1: the dependency-free foundations — classification constants (1, the spine; daily_ib_health is in WIPE so the partition is exhaustive over 80), SQLite-retire (7), config-verify reader (8). Batch 2: classification guard test (2), live-schema reconciliation module (3, needs classification + EXPECTED_FK_EDGES), backup-with-ephemeral-scratch (4, needs classification). Batch 3: backup tests (5, needs 4), live-schema tests (6, needs 3), TRUNCATE core (9, needs 1). Batch 4: the decorated entry point (10) — single serialization point, depends on backup+live_schema+sqlite+config_verify+truncate-core. Batch 5: CLI (11) + runbook doc (15). Batch 6: the three test suites that drive the assembled entry point — main-flow/gating/already-clean/config-pending (12), interrupted-run/forensic-marker (13), full E2E rehearsal (14). All DB tests target the 5434 scratch DB / ephemeral verify DBs via TEST_DATABASE_URL — prod 5433 is NEVER touched by any task (execution stays operator-gated). Cross-cutting invariants every developer MUST honor: (a) pg_connect(dsn=...) only, never connect_db; (b) DSN threaded as dsn= kwarg so prod_guard fires; (c) TRUNCATE not DROP; (d) NO @safety_window (market_hours config key does not exist → ValueError); (e) the live-schema+FK reconciliation is the authoritative gate, registry guard is necessary-not-sufficient; (f) verify-restore into a FRESH EPHEMERAL DB, never the shared halcyon test DB; (g) broker open-positions ABORT by default; (h) re-check watch-loop inside the TRUNCATE boundary; (i) emit config instructions + a --verify-config loop, never auto-edit YAML; (j) archive SQLite (fsync) never blind-delete; (k) verify-by-mutation on every guard/mutation test; (l) WIPE=53, KEEP=27, sum=80 — do not re-balance.

---

## Tasks (15)

### 1. Classification constants + completeness guard (80-table, FK edges)
- **Description:** Create scripts/_clean_slate/__init__.py and scripts/_clean_slate/classification.py with the reviewed WIPE_TABLES (53) and KEEP_TABLES (27) frozensets exactly per spec §3.1/§3.2 (daily_ib_health is in WIPE), EXPECTED_FK_EDGES (the 6 tuples from §3.5 as (child_table, child_col, parent_table)), UNREGISTERED_NOTES (sync_state note), and assert_partition_complete() mirroring src/utils/db.py:820-836. The function computes missing/extra/overlap vs set(src.schema.registry.TABLES) and raises AssertionError naming all three sets; it MUST also assert len(set(registry.TABLES))==80 (count-pin).
- **Scope fence:** Do NOT add any DB-connection, TRUNCATE, pg_dump, or information_schema logic (live reconciliation is Task 3). Do NOT import psycopg2 or src.tools._db here — pure data + set algebra. Do NOT modify registry.py or db.py. WIPE must contain exactly 53 names, KEEP exactly 27, summing to 80.
- **Test strategy:** Covered by Task 2. Ship constants + assert function only; no tests here.

### 2. Completeness CI guard test (verify-by-mutation)
- **Description:** Create tests/scripts/test_clean_slate_classification.py asserting set(WIPE)|set(KEEP)==set(registry.TABLES), set(WIPE)&set(KEEP)==empty, len(registry.TABLES)==80, and EXPECTED_FK_EDGES equals the 6 spec edges. Add verify-by-mutation: inject a fake table into a COPY of registry.TABLES (monkeypatch) and assert assert_partition_complete() RAISES; also assert it RAISES if a name is moved out of both sets — proving the guard is not theater.
- **Depends on:** 1
- **Scope fence:** Do NOT test backup, live-schema, TRUNCATE, or CLI here — only the classification partition + FK-edge constant. Do NOT use a real PG connection.
- **Test strategy:** Self. Run pytest; confirm partition-exhaustive + count-pin + FK-edge assertions AND the by-mutation-raises assertions pass; confirm the by-mutation test fails if assert_partition_complete is stubbed to pass.

### 3. Live-schema + live-FK reconciliation module
- **Description:** Create scripts/_clean_slate/live_schema.py with reconcile_live_schema(dsn) and reconcile_live_fk_edges(dsn) per spec §3.7. reconcile_live_schema queries information_schema.tables (public, BASE TABLE) via pg_connect(dsn=...) read-only, computes live_only/registered_only vs set(registry.TABLES), and raises CleanSlateAbort('ABORT_LIVE_SCHEMA_DRIFT', ...) naming both sets on any divergence. reconcile_live_fk_edges queries pg_constraint/key_column_usage/constraint_column_usage (contype='f') for FKs whose child OR parent is in WIPE_TABLES, normalizes to (child_table, child_col, parent_table), and raises CleanSlateAbort('ABORT_FK_DRIFT', ...) if the set != classification.EXPECTED_FK_EDGES. Define the CleanSlateAbort exception here (or in a shared _errors module).
- **Depends on:** 1
- **Scope fence:** Do NOT TRUNCATE, dump, or write anything — read-only reconciliation only. Do NOT add the decorator stack or backup/sqlite logic. Do NOT hardcode prod DSN; accept dsn as a parameter.
- **Test strategy:** Covered by Task 6. Read-only against the DSN; use pg_connect(dsn=...), NEVER connect_db.

### 4. Backup + verify-restore into a FRESH EPHEMERAL scratch DB
- **Description:** Create scripts/_clean_slate/backup.py: run_backup_and_verify(dsn, scratch_server_dsn, out_dir) that (1) docker exec halcyon-pg pg_dump -U halcyon -d halcyon → plain SQL, (2) docker cp to out_dir/prod.sql, (3) verify size>1MB + SHA256 + CREATE-TABLE count: ==80 PASS, <80 raise BackupVerifyError REFUSE_BACKUP (HARD shortfall), >80 raise BackupVerifyError REFUSE_SCHEMA_DRIFT (per spec §Phase1.3 / MAJOR-1), (4) connect to scratch_server_dsn (maintenance DB, NOT the shared halcyon test DB), CREATE DATABASE clean_slate_verify_<ISO8601> in AUTOCOMMIT, assert it is empty pre-restore (else REFUSE_VERIFY), psql-restore the dump into it, count-compare per-table ephemeral-vs-prod (exact for low-volume, ±0.5% only for minute_bars-class KEEP), then DROP DATABASE in a finally (force-disconnect). Record per-WIPE-table prod row counts + BACKUP_OF_EMPTY_STATE tag in the returned verdict dict. Raise BackupVerifyError on any failure.
- **Depends on:** 1
- **Scope fence:** Do NOT TRUNCATE prod or touch the SQLite store. Do NOT restore into the shared halcyon test DB — only into the ephemeral clean_slate_verify_<ISO8601> DB. Do NOT add the decorator stack (Task 7). NEVER connect_db.
- **Test strategy:** Covered by Task 5. Use pg_connect(dsn=...) for count queries; subprocess for docker/psql. The ephemeral DB lives on the 5434 SERVER and is always dropped.

### 5. Backup verify-or-refuse + ephemeral-lifecycle tests
- **Description:** Create tests/scripts/test_clean_slate_backup.py: mock the docker pg_dump subprocess to emit (a) <1MB → assert BackupVerifyError/REFUSE_BACKUP, (b) CREATE-count 79 (shortfall) → assert HARD REFUSE_BACKUP (verify-by-mutation: assert it RAISES, not WARN), (c) CREATE-count 81 → assert REFUSE_SCHEMA_DRIFT, (d) a count-divergent restore → assert REFUSE_VERIFY, (e) a valid dump+matching restore → assert proceeds + returns verdict. Assert the ephemeral DB is CREATEd, asserted-empty, and DROPped (query the 5434 server for its absence afterward) and that the shared halcyon test DB is never created/dropped/written.
- **Depends on:** 4
- **Scope fence:** Do NOT exercise prod 5433. Do NOT test TRUNCATE, live-schema, or CLI here. Do NOT use the shared halcyon test DB as the restore target.
- **Test strategy:** Self. Verify-by-mutation on the shortfall + divergence cases. Use TEST_DATABASE_URL=...:5434 maintenance DSN for the ephemeral lifecycle; mock subprocess for dump/restore. NEVER ARCIS_ALLOW_PROD_PG_IN_TESTS=1; never the prod 5433 DSN.

### 6. Live-schema reconciliation tests (drift → abort, by-mutation)
- **Description:** Create tests/scripts/test_clean_slate_live_schema.py against a 5434 scratch DB provisioned from the registry: (a) faithful schema → both reconcilers PASS; (b) CREATE an extra unregistered table → reconcile_live_schema raises ABORT_LIVE_SCHEMA_DRIFT; (c) DROP a registered table → raises (registered_only) ABORT_LIVE_SCHEMA_DRIFT; (d) add an unexpected FK edge touching a WIPE table → reconcile_live_fk_edges raises ABORT_FK_DRIFT. Verify-by-mutation: assert each abort fires ONLY on the injected drift and the faithful case passes.
- **Depends on:** 3
- **Scope fence:** Do NOT test backup/TRUNCATE/CLI. Do NOT point at prod 5433. Build the scratch schema from the registry, not by importing live prod.
- **Test strategy:** Self. Provision an ephemeral scratch schema on 5434 (TEST_DATABASE_URL), mutate it, assert aborts. NEVER prod 5433; NEVER ARCIS_ALLOW_PROD_PG_IN_TESTS=1.

### 7. SQLite retire module (archive-fsync-then-empty)
- **Description:** Create scripts/_clean_slate/sqlite_retire.py: archive_and_empty_sqlite(src_path, archive_dir) resolving the canonical SQLite (+ -wal/-shm) from ARCIS_DB_PATH, archiving via VACUUM INTO (fallback file copy) into archive_dir, FSYNCING the archive file and its directory BEFORE emptying (per spec §Phase5 / minor d), then EMPTYING the trade/learning residue in place (re-create empty / truncate) so a valid non-empty file persists (connect_db recreates at db.py:638 — do NOT delete). If source absent, return SQLITE_ABSENT verdict (warn, no raise). Capture archive path + SHA.
- **Scope fence:** Do NOT blind-delete the SQLite file. Do NOT touch PG. Do NOT auto-edit any YAML. Archive-fsync-then-empty only.
- **Test strategy:** Covered by Task 14. Module-level: archive created + non-empty + source still exists (not deleted); archive fsync'd before empty.

### 8. Config/Ollama post-reset verify module
- **Description:** Create scripts/_clean_slate/config_verify.py: verify_post_reset_config(config_path, *, base_tag=None) per spec §Phase6.2 / MAJOR-3. READ config/settings.local.yaml (utf-8) and assert llm.model==base tag, live_trading.post_bootcamp==false, risk.starting_capital==100000; READ the Ollama loaded model (ollama ps / API tags, best-effort) and assert the base tag is loaded. Return a verdict dict (PASSED/FAILED with the specific failing assertion). Read-only; never edits config.
- **Scope fence:** Do NOT edit settings.local.yaml or any YAML. Do NOT place Ollama pull/load commands — READ only. Do NOT touch PG or SQLite. Use encoding='utf-8' for the YAML read (cp1252 risk).
- **Test strategy:** Covered by Task 12 (within main-flow tests). Module reads config + Ollama and asserts; never mutates.

### 9. TRUNCATE core + counts + DB post-verify
- **Description:** In scripts/clean_slate_wipe.py implement internal helpers (no decorators yet): _capture_counts(dsn, tables) (read-only per-table COUNT(*)), _truncate_wipe(dsn, wipe_tables) running a single-transaction TRUNCATE TABLE <sorted wipe> RESTART IDENTITY CASCADE via pg_connect(dsn, isolation_level='SERIALIZABLE'), and _post_verify_db(dsn) asserting WIPE==0, KEEP unchanged vs a passed-in baseline, and model_versions empty. Compute + return the per-table row delta. Rely on pg_connect rollback-on-exception.
- **Depends on:** 1
- **Scope fence:** Do NOT use DROP or connect_db. Do NOT add backup/sqlite/live-schema/CLI/decorator logic here — only count+truncate+db-post-verify core. Single transaction.
- **Test strategy:** Covered by Task 12. TRUNCATE-by-mutation against the 5434 scratch DB: seed WIPE+KEEP + an FK chain, assert WIPE→0, KEEP unchanged, CASCADE safe.

### 10. Decorated entry point + phase orchestration + forensic markers + banner
- **Description:** In scripts/clean_slate_wipe.py add the decorated public entry point clean_slate_wipe(*, dsn, scratch_server_dsn, confirm=False, i_have_flattened_broker=False, i_have_stopped_nssm=False, verify_config=False, skip_sqlite=False, emergency=False) with stack @safe_op(name='clean_slate_wipe', mutates=True, describe=_describe) → @prod_guard(dsn_param='dsn') (NO @safety_window — §5.3), delegating to _run_clean_slate sequencing Phase 0→7 per spec: Phase 0 (watch-loop gate, registry assert, live_schema.reconcile_*, broker HARD gate, open-shadow advisory, already-clean short-circuit→ALREADY_CLEAN no-backup); Phase 1 backup module; Phase 2 dry-run preview; Phase 3.0 watch-loop RE-CHECK (+NSSM-stopped/attestation) then TRUNCATE core, then write+fsync WIPE_COMMITTED.marker; Phase 4 model L1 assert + emit L2/L3/config instructions; Phase 5 sqlite_retire; Phase 6 db-post-verify + (if verify_config) config_verify else POST_VERIFY_CONFIG_PENDING; Phase 7 write_event + atomic manifest + BANNER. Wire all refuse/abort verdicts from §7. emergency is an inert reserved flag (banner-stated).
- **Depends on:** 3, 4, 7, 8, 9
- **Scope fence:** DSN MUST be passed as dsn= kwarg (prod_guard footgun). CLI __main__ (Task 11) calls this decorated fn, never _run_clean_slate. Do NOT add @safety_window('market_hours') (config key absent → ValueError). Do NOT auto-edit YAML — emit only. Do NOT place broker orders. Do NOT modify imported safety/_db/registry/config_verify modules.
- **Test strategy:** Covered by Tasks 12-14. Assert decorator ordering yields dry_run/prod_guard_block; backup-refuse + reconciliation-abort + broker-abort block TRUNCATE; manifest written atomically; WIPE_COMMITTED.marker fsync'd after commit.

### 11. CLI surface + dotenv DSN sourcing
- **Description:** In scripts/clean_slate_wipe.py add the argparse CLI (mirror archive_bootcamp dry-run-default shape: is_dry = not args.confirm): flags --confirm, --dsn (default from .env DATABASE_URL via dotenv), --scratch-server-dsn (default postgresql://test:test@127.0.0.1:5434/postgres — the 5434 maintenance DB, NOT the shared test DB), --out-dir, --skip-sqlite, --i-have-flattened-broker, --i-have-stopped-nssm, --verify-config, --emergency (reserved/inert). __main__ loads dotenv, reads the literal prod DSN, and calls the decorated clean_slate_wipe(dsn=..., ...). Do NOT add @safety_window and do NOT add a market_hours config key (§5.3); the absence is documented in the module docstring.
- **Depends on:** 10
- **Scope fence:** Do NOT add new keys to central YAML. Do NOT read DATABASE_URL anywhere except the CLI layer; thread dsn= downward. --scratch-server-dsn default MUST NOT be the shared halcyon test DB. Remove any 'developer chooses market_hours' branch.
- **Test strategy:** Subprocess CLI smoke test (in Task 12's file): invoke with no --confirm against a non-prod DSN, assert dry-run preview prints + exits 0 with no mutation.

### 12. Main-flow tests: gating, dry-run, truncate, re-check, broker, already-clean, config-pending
- **Description:** Create tests/scripts/test_clean_slate_wipe.py covering: dry-run default (no confirm → DryRunResult, no mutation, dry_run event, but read-path dump still occurred); ProdGuard block (prod-signature DSN w/o env+confirm → ProdGuardError/prod_guard_block); TRUNCATE-by-mutation on 5434 scratch (WIPE→0, KEEP unchanged, FK CASCADE safe, delta report); watch-loop Phase-0 abort; watch-loop Phase-3.0 RE-CHECK abort (None at Phase 0, non-None at re-check → ABORT_WATCHLOOP_RECHECK, nothing committed); broker HARD gate (open positions → ABORT_BROKER_NOT_FLAT before backup; with --i-have-flattened-broker → proceeds+WARN); already-clean short-circuit (all WIPE empty → ALREADY_CLEAN, backup NOT called); config-verify (temp config stale → FAIL; reset → PASS; normal main run records POST_VERIFY_CONFIG_PENDING); backup-refuse blocks TRUNCATE; CLI subprocess smoke (Task 11).
- **Depends on:** 11
- **Scope fence:** Do NOT run against prod 5433. Do NOT re-test the classification partition (Task 2), backup internals (Task 5), or live-schema (Task 6) — focus on orchestration + gating + truncate + re-check + broker + already-clean + config-pending.
- **Test strategy:** Self. Verify-by-mutation throughout. Use TEST_DATABASE_URL=...:5434; NEVER ARCIS_ALLOW_PROD_PG_IN_TESTS=1. Inject log_path/config_path overrides for decorator isolation; mock _check_watch_loop_running / _check_alpaca_positions / backup module as needed.

### 13. Interrupted-run / forensic-marker safe-re-entry test
- **Description:** Create tests/scripts/test_clean_slate_interrupted.py: (a) drive the flow against a 5434 scratch DB to abort immediately AFTER the TRUNCATE commit (inject failure before Phase 7) → assert WIPE_COMMITTED.marker exists + is fsync'd + manifest.json absent, and assert a committed-wipe-without-manifest is detectable (re-running hits ALREADY_CLEAN safely); (b) abort after the SQLite archive but before the empty step → assert the archive file is intact + non-empty and a re-run completes the empty step. Prove safe re-entry in both cases.
- **Depends on:** 11
- **Scope fence:** Do NOT point at prod 5433. Do NOT test the happy E2E path (Task 14). Focus only on interrupted-state detectability + safe re-entry.
- **Test strategy:** Self. Inject aborts via monkeypatch at the two boundaries; assert markers + safe re-entry. Use TEST_DATABASE_URL=...:5434 + a tmp SQLite; NEVER prod 5433.

### 14. End-to-end dry-run+confirm rehearsal against 5434 scratch (no prod)
- **Description:** Create tests/scripts/test_clean_slate_e2e.py: provision a 5434 scratch DB from the registry, seed representative WIPE + KEEP rows + an FK chain + a tmp SQLite, and drive the full clean_slate_wipe(confirm=True) against the SCRATCH DSN (non-prod) end-to-end: assert live-schema+FK reconciliation PASS, backup+verify ran (ephemeral verify DB created+dropped), TRUNCATE deltas correct, KEEP preserved, SQLite tmp archived+emptied, manifest written with ALL verdicts (reconciliation, backup, post-verify-db, POST_VERIFY_CONFIG_PENDING), and a clean re-run short-circuits ALREADY_CLEAN. Rehearses the full flow without ever touching prod 5433.
- **Depends on:** 11
- **Scope fence:** Do NOT point at prod 5433. Do NOT skip backup/verify (must exercise the ephemeral path against the 5434 server). Do NOT assert on real broker/Ollama (out-of-scope external steps; mock the broker check + config_verify Ollama read).
- **Test strategy:** Self (integration). Drives the decorated entry point against the 5434 scratch DSN with TEST_DATABASE_URL. Asserts every phase verdict in the manifest. NEVER prod 5433; NEVER ARCIS_ALLOW_PROD_PG_IN_TESTS=1.

### 15. Operator runbook doc + manifest schema
- **Description:** Create docs/runbooks/clean_slate_wipe.md documenting the §9 runbook (pre-stop watch loop via nssm stop + VERIFY SERVICE_STOPPED; flatten broker — script ABORTS on open positions, --i-have-flattened-broker only when truly flat; ARCIS_ALLOW_PROD_PG=1; dry-run-first incl. the note it dumps prod; --confirm; post-wipe manual config L2/L3 + post_bootcamp + risk.starting_capital with the explicit DO-NOT-TOUCH live_trading.starting_capital warning; re-run --verify-config to flip POST_VERIFY_CONFIG_PENDING; two-layer-staleness restart+regenerate) and the full manifest.json schema (all verdict fields incl. reconciliation, broker disposition, both post-verifies, BACKUP_OF_EMPTY_STATE, WIPE_COMMITTED.marker). State that --emergency is inert. Cross-link from the script banner.
- **Depends on:** 10
- **Scope fence:** Documentation only. Do NOT change script behavior. Do NOT instruct auto-editing YAML — manual steps only. Do NOT document a market_hours window (it does not exist).
- **Test strategy:** Doc only — no automated test. Reviewer checks the runbook matches the emitted banner + §9 + the manifest schema exactly.
