I have enough data to produce the comprehensive deep report. Let me synthesize.

<reasoning>
This is a massive Modified-A migration audit. Key findings across all 20 focus areas:

1. **Wrapper file (`src/utils/db.py`)** — post-rollback state confirmed. PostgresConnectionWrapper exists with execute/executemany passthrough but NO `?`→`%s` rewrite, NO compat Row class, NO engine_aware helpers. Lines 86-95 implement context-manager. The precedence rule is "explicit db_path wins" (sentinel pattern at line 98). Phase 0 wrapper changes integrate at: lines 64-75 (execute/executemany methods), new class additions, new module-level functions.

2. **PRAGMA inventory** — 21 occurrences across 11 files. Categories:
   - **Schema introspection** (PRAGMA table_info, index_list, index_info): edgar_collector.py:233, retention.py:116, event_risk_score.py:48, model_monitor.py:176, cosine_similarity.py:161, schema/sqlite.py:41+46+190, schema/validator.py:61. These need `engine_aware_column_info()` / `engine_aware_index_list()` helpers.
   - **Runtime tuning** (busy_timeout, journal_mode, synchronous, integrity_check): watch.py:1108-1130, sync/reconcile.py:101+195, sync/render_sync.py:84, evaluation/system_validator.py:165, schema/sqlite.py:34, utils/db.py:146. These are SQLite-only-by-design — wrap in `if isinstance(conn, sqlite3.Connection)`.

3. **sqlite_master** — 5 occurrences across 5 files: data_collection/retention.py:108, schema/validator.py:43, startup_checks.py:153+166, evaluation/system_validator.py:175. All need `engine_aware_table_list()` helper.

4. **INSERT OR REPLACE/IGNORE** — 17 occurrences across 14 files:
   - **`OR IGNORE` (10)**: short_interest_collector:111, research_collector:121, insider_collector via comment:18, fed_collector:128, edgar_collector:338, notifications/platform_events:96, analyst_collector:153, council/protocol:228, sync/render_sync:891
   - **`OR REPLACE` (8)**: data_enrichment/staleness:42, evaluation/build_score:460, api/routes/system:566, monitoring/system_metrics:148, council/value_tracker:120, simulation/engine:504, walkforward_runner:308+355, walkforward_universe:81
   - 8 of these target tables have `sync_conflict_col` already populated (edgar_filings, short_interest, fed_communications, analyst_estimates, system_metrics has none, etc.). Most need to fall back to PK.

5. **Dynamic placeholder generation** — 9 occurrences: journal/store:187+241, features/event_risk_score:95, council/value_tracker:306, api/routes/logs:63, monitoring/system_metrics:142, shadow_trading/_status_sql:46+54, platform/promotion:691. These produce `?, ?, ?` strings then pass via `conn.execute(f"...({placeholders})", values)`. Wrapper's `?`→`%s` rewrite catches these transparently.

6. **`row[0]`** integer-indexed access is PERVASIVE — found 60+ references across 50+ files including in hot paths (journal, system_validator, attribution/logger). The compat Row class is mandatory — without it the cutover guarantees silent breakage. Existing example at cli/promotion_cmd.py:81 has `row["event_id"] if hasattr(row, "keys") else row[0]` showing the operator has hit this pattern before.

7. **`conn.row_factory = sqlite3.Row`** AFTER connect_db — 45+ assignments in PG-relevant files. These become DEAD CODE on PG path (wrapper has no-op row_factory setter at line 59). Informational only — no fix needed since wrapper accepts the assignment.

8. **CI infrastructure: ZERO** — only `.github/ISSUE_TEMPLATE` and `.github/dependabot.yml` exist. No `workflows/` directory exists at all. New `pg-tests.yml` builds from scratch — no existing pattern to mirror.

9. **`conftest.py:postgres_session`** — implemented at lines 180-213. Reads `TEST_DATABASE_URL` (NOT DATABASE_URL — safety guard). Skips test if env unset. Uses `psycopg2.extras.RealDictCursor`. autocommit=False; rollback in teardown.

10. **Test prototype pattern** — `test_dashboard_reconciliation.py:272-303` shows `@pytest.mark.parametrize("db_backend", ["sqlite", "postgres"])` with `request.getfixturevalue("postgres_session")` for lazy postgres fixture loading.

11. **Watch loop's connect_db** — 11 call sites, ALL pass `DB_PATH` or `self.db_path` explicitly. By the current precedence (explicit path wins), these all route to SQLite. The PRAGMA cluster at watch.py:1108-1130 (configure SQLite for production) plus backup API at 1164-1165 are explicitly SQLite-only and need allowlist entry. **Critical implication**: if Phase 3 cutover changes precedence so DATABASE_URL routes the watch loop, these calls break — so EITHER the precedence stays (recommended) AND DATABASE_URL only routes truly arg-less connect_db() calls, OR these call sites need `if not isinstance(conn, sqlite3.Connection)` guards.

12. **`startup_checks.py`** — 2 sqlite_master refs at 153+166 (both COUNT queries). Uses `connect_db(db_path)` — explicit path, so always routes SQLite. **But** `_check_render_postgres` at line 272-337 ALREADY does PG-aware checks with `psycopg2.connect(db_url)` — engine-aware precedent.

13. **`journal/store.py`** — Pure SQLite-idiomatic. Every call passes `db_path`, so currently always SQLite. 18 connect_db calls. Patterns: dynamic placeholders (lines 187, 241), `f"UPDATE shadow_trades SET {set_clause} WHERE trade_id = ?"`, `LIKE ?`, multi-line SELECT with `?`. ALL use placeholder `?` — none have literal `?` in string contents. Cutover blocker: if `db_path=DB_PATH` becomes meaningless (PG cutover) — DB_PATH is the SQLite file path. Currently safe by precedence rule.

14. **`monitoring/system_metrics.py:131-152`** — `_store_snapshot` uses dynamic placeholders + INSERT OR REPLACE. `system_metrics` table has NO sync_conflict_col, PK is `snapshot_id` (UUID). For PG: `INSERT INTO system_metrics ... ON CONFLICT (snapshot_id) DO UPDATE SET ...` — but since snapshot_id is a fresh UUID per call, REPLACE never collides — could be simplified to plain INSERT for PG. The wrapper needs to decide: emit `OR REPLACE` removal for PG, or `ON CONFLICT (pk) DO UPDATE` translation.

15. **The 7 `cloud_routes/*.py` files** — All implement `if database_url:` branching. Best precedent: `platform.py:_read_rows` (lines 43-70) — does `sql.replace("?", "%s")` for PG path. `notifications.py:74` and `walkforward.py:51` follow same pattern. `broker_exceptions.py:50+118+162` uses `connect_db()` (no args) for SQLite, raw psycopg2 for PG. **These are proto-Option-A consumers** — wrapper centralization would replace these manual branches with `connect_db()` returning either engine.

16. **`scripts/sqlite_to_pg_migrate.py:97-119`** — `_build_insert_sql_template` uses `ON CONFLICT ({pk_cols}) DO NOTHING`. The migration tool resolves conflict via PK list, NOT sync_conflict_col. `engine_aware_upsert` should follow same pattern + extend to UPDATE for REPLACE semantics: `ON CONFLICT (target) DO UPDATE SET col1=EXCLUDED.col1, col2=EXCLUDED.col2, ...`. Note: this script is the production-validated UPSERT pattern — the upsert helper should reuse `_resolve_primary_key_columns` at line 50.

17. **`src/schema/registry.py`** — 72 tables, 940 columns, file too large to read whole. PK access: `table.primary_key` (str or list). `sync_conflict_col` attribute: present on 8 tables only (edgar_filings, short_interest, fed_communications, analyst_estimates, macro_snapshots, earnings_calendar, scan_metrics, live_prices). 64 tables fall back to PK for conflict target. Composite PK tables: correlation_matrices(5-col), factor_loadings(4-col), sp100_historical_constituents(2-col), data_freshness(2-col), minute_bars(2-col), operator_view_state(2-col).

18. **SQLite-only-by-design candidates beyond CLAUDE.md list**:
    - **`src/schema/sqlite.py`** — CONFIRMED (allowlist)
    - **`src/schema/registry.py`** — CONFIRMED (allowlist)
    - **`src/scheduler/watch.py`** — backup API at 1164-1165 + PRAGMA cluster at 1108-1130. **Recommendation**: backup API stays SQLite-only (allowlist line range). PRAGMA cluster needs `if isinstance(conn, sqlite3.Connection)` wrapping OR refactor to `_configure_sqlite_for_production()` helper.
    - **`src/training/trainer.py`** — line 1171, training writer (allowlist)
    - **`src/sync/reconcile.py`** — HYBRID confirmed. Designed for both engines: takes `pg_conn` parameter + opens SQLite directly. Will retire with render_sync per surface report. No migration needed; retire as bundle.
    - **`src/sync/render_sync.py`** — 7 raw sqlite3.connect calls (lines 83, 454, 479, 507, 525, 886, 935). All for reading SQLite source to push to PG. This is the SYNCER itself — retires when PG becomes source of truth. No migration needed.

19. **Cross-engine SQL syntax differences (beyond surface)**:
    - **`julianday('now')`** — SQLite-only. Found at council/agent_data.py:91 (`CAST(julianday('now') - julianday(actual_entry_time) AS INTEGER)`).
    - **`date('now')`** — SQLite-only. Found at api/routes/ib_status.py:55 and shadow_trading/executor.py:776. PG equivalent: `CURRENT_DATE` or `NOW()::date`.
    - **No `||` string concat used in SQL** — only Python expressions.
    - **No `LIMIT offset, count`** SQLite syntax found — all use `LIMIT N OFFSET M` form which works on both.
    - **No `INSERT INTO ... DEFAULT VALUES`** SQLite syntax found.
    - **No `WITH RECURSIVE`** found.
    - **No `REGEXP` / `json_extract` / `json_each` / `json1`** found.
    - **No bool literals TRUE/FALSE in SQL** — uses 1/0 throughout (SQLite-native, works on PG in most contexts).
    - **AUTOINCREMENT** — only emitted by schema/sqlite.py:87 (DDL). Not in runtime code. PG doesn't have AUTOINCREMENT but has SERIAL/IDENTITY — handled by schema/postgres.py separately.

20. **Wrapper integration points** (post-rollback state confirmed):
    - `PostgresConnectionWrapper.execute()` at lines 64-70: add `?`→`%s` rewrite (use precompiled regex skipping single-quoted segments to be defensive).
    - `executemany()` at lines 72-75: same rewrite.
    - Wrap `cur` returned from execute/executemany in a `_RowFactoryCursor` that wraps fetchone/fetchall results in CompatRow.
    - Add `class CompatRow:` near class definition.
    - Add `engine_aware_upsert(conn, table_name, row_dict, action='replace'|'ignore')`, `engine_aware_table_list(conn)`, `engine_aware_column_info(conn, table)`, `engine_aware_index_list(conn, table)`, `engine_aware_foreign_keys(conn, table)` as module-level functions after the wrapper class.

**Critical Cutover Implications**:
- The current precedence rule "explicit db_path wins" means migrating away from passing `db_path` is itself the cutover trigger. Phase 3 watch loop cutover requires either (a) the watch loop to call `connect_db()` without DB_PATH and let DATABASE_URL route, or (b) keep passing DB_PATH but use psycopg2 path when DATABASE_URL set anyway. The Spec needs explicit guidance.
- **The watch loop currently passes DB_PATH at ALL its connect_db sites**. If migration leaves the explicit-path rule intact, then PRAGMA/backup-API/SQLite-only-by-design files stay SAFE but **DATABASE_URL is never consulted** at the watch loop, sync, executor, journal, etc. So Phase 3 needs an architectural decision: invert precedence after Phase 0/1/2 migration is complete, OR migrate every call site to drop the explicit db_path arg. **The cutover retry is gated on this decision.**

Test discipline test currently allowlists 4 files: simulation/engine.py, startup.py, startup_checks.py, shadow_trading/executor.py. Extend to allowlist: schema/sqlite.py, schema/registry.py, scheduler/watch.py (lines 1164-1165 + 1108-1130), training/trainer.py:1171. Sync files (sync/render_sync.py, sync/reconcile.py) need separate "retiring" allowlist or stub-skip.

Reporting all findings in the codebase_report.
</reasoning>

<codebase_report>
{
  "analysis_mode": "deep",
  "focus_areas": [
    {
      "area": "1. Complete dialect-sensitive call-site enumeration",
      "depth": "deep",
      "files_read": [
        "src/utils/db.py", "src/scheduler/watch.py:1080-1180", "src/journal/store.py",
        "src/monitoring/system_metrics.py", "src/startup_checks.py", "src/sync/reconcile.py",
        "src/schema/sqlite.py", "scripts/sqlite_to_pg_migrate.py", "tests/conftest.py",
        "tests/test_connect_db_discipline.py", "tests/test_dashboard_reconciliation.py:260-304",
        "src/data_collection/retention.py:100-120", "src/api/cloud_routes/platform.py"
      ],
      "patterns_found": [
        "120 unique files call connect_db (482 references total)",
        "Top files by connect_db count: journal/store.py(18), training/versioning.py(16), api/routes/system.py(15), evaluation/system_validator.py(15), shadow_trading/reconcile.py(15), platform/promotion.py(13), scheduler/watch.py(12), shadow_trading/executor.py(12)",
        "Only 4 connect_db() (no-args) call sites: cli/commands.py:1448, broker_exceptions.py:61+140+192. ALL others pass explicit db_path"
      ],
      "integration_points": [
        {"description": "PRAGMA — schema introspection (rewriteable via engine_aware helpers)", "file": "src/data_collection/edgar_collector.py", "line": 233, "implication": "PRAGMA table_info(edgar_filings)"},
        {"description": "PRAGMA table_info dynamic", "file": "src/data_collection/retention.py", "line": 116, "implication": "f\"PRAGMA table_info({table})\""},
        {"description": "PRAGMA table_info dynamic", "file": "src/features/event_risk_score.py", "line": 48, "implication": "f\"PRAGMA table_info({table_name})\""},
        {"description": "PRAGMA table_info recommendations", "file": "src/evaluation/model_monitor.py", "line": 176, "implication": "Hardcoded table"},
        {"description": "PRAGMA table_info edgar_filings", "file": "src/platform/features/cosine_similarity.py", "line": 161, "implication": "Hardcoded table"},
        {"description": "PRAGMA — runtime tuning (SQLite-only, needs isinstance guard)", "file": "src/scheduler/watch.py", "line": "1108-1130", "implication": "PRAGMA integrity_check + journal_mode=WAL + synchronous=NORMAL + busy_timeout=5000 — all SQLite-only"},
        {"description": "PRAGMA busy_timeout", "file": "src/sync/reconcile.py", "line": "101+195", "implication": "SQLite-only-by-design (retires with render_sync)"},
        {"description": "PRAGMA busy_timeout", "file": "src/sync/render_sync.py", "line": 84, "implication": "SQLite-only-by-design (retires with render_sync)"},
        {"description": "PRAGMA journal_mode read", "file": "src/evaluation/system_validator.py", "line": 165, "implication": "Diagnostic only; wrap in isinstance check"},
        {"description": "PRAGMA index_list/info", "file": "src/schema/sqlite.py", "line": "41+46+190", "implication": "Already allowlisted in CLAUDE.md (uses _sqlite_only_connect)"},
        {"description": "PRAGMA table_info validator", "file": "src/schema/validator.py", "line": 61, "implication": "Needs engine_aware_column_info or split into validate_sqlite + validate_postgres"},
        {"description": "sqlite_master — table list (rewriteable)", "file": "src/data_collection/retention.py", "line": 108, "implication": "SELECT name FROM sqlite_master WHERE type='table' — use engine_aware_table_list()"},
        {"description": "sqlite_master — schema validator", "file": "src/schema/validator.py", "line": 43, "implication": "Same query"},
        {"description": "sqlite_master — table count startup", "file": "src/startup_checks.py", "line": "153+166", "implication": "SELECT COUNT(*) FROM sqlite_master WHERE type='table' — runs on EVERY watch-loop startup; PG-blocker on cutover"},
        {"description": "sqlite_master — system validator", "file": "src/evaluation/system_validator.py", "line": 175, "implication": "Same query"},
        {"description": "INSERT OR IGNORE", "file": "src/data_collection/short_interest_collector.py", "line": 111, "implication": "Target=short_interest, sync_conflict_col=(ticker, settlement_date)"},
        {"description": "INSERT OR IGNORE", "file": "src/data_collection/research_collector.py", "line": 121, "implication": "Target=research_papers, sync_conflict_col=None → fallback PK=id (UUID, never collides — REPLACE/IGNORE semantically equivalent to plain INSERT)"},
        {"description": "INSERT OR IGNORE", "file": "src/data_collection/fed_collector.py", "line": 128, "implication": "Target=fed_communications, sync_conflict_col=(comm_type, date, title)"},
        {"description": "INSERT OR IGNORE", "file": "src/data_collection/edgar_collector.py", "line": 338, "implication": "Target=edgar_filings, sync_conflict_col=accession_number"},
        {"description": "INSERT OR IGNORE", "file": "src/notifications/platform_events.py", "line": 96, "implication": "Target=notifications_dedup, sync_conflict_col=None → unique idx on (event_type, dedup_key); needs explicit conflict target"},
        {"description": "INSERT OR IGNORE", "file": "src/data_collection/analyst_collector.py", "line": 153, "implication": "Target=analyst_estimates, sync_conflict_col=(ticker, date, source)"},
        {"description": "INSERT OR IGNORE", "file": "src/council/protocol.py", "line": 228, "implication": "Target=council_debug_log, sync_conflict_col=None → PK=debug_id (UUID)"},
        {"description": "INSERT OR IGNORE", "file": "src/sync/render_sync.py", "line": 891, "implication": "Target=pending_commands, RETIRES with render_sync"},
        {"description": "INSERT OR REPLACE", "file": "src/data_enrichment/staleness.py", "line": 42, "implication": "Target=data_freshness, sync_conflict_col=None → PK=(source, ticker) composite — UPDATE semantics"},
        {"description": "INSERT OR REPLACE", "file": "src/evaluation/build_score.py", "line": 460, "implication": "Target=build_score_history, sync_conflict_col=None → PK=score_id (UUID)"},
        {"description": "INSERT OR REPLACE", "file": "src/api/routes/system.py", "line": 566, "implication": "Target=config_overrides, sync_conflict_col=None → PK=setting_key"},
        {"description": "INSERT OR REPLACE + dynamic placeholders", "file": "src/monitoring/system_metrics.py", "line": 148, "implication": "Target=system_metrics, sync_conflict_col=None → PK=snapshot_id (UUID, never collides)"},
        {"description": "INSERT OR REPLACE", "file": "src/council/value_tracker.py", "line": 120, "implication": "Target=council_parameter_state, sync_conflict_col=None → PK=parameter_name"},
        {"description": "INSERT OR REPLACE", "file": "src/simulation/engine.py", "line": 504, "implication": "Target=simulation_results, sync_conflict_col=None → PK=result_id"},
        {"description": "INSERT OR REPLACE", "file": "src/platform/rigor/walkforward_runner.py", "line": "308+355", "implication": "Targets=walkforward_results+walkforward_trades, sync_conflict_col=None → PK=run_id, trade_id"},
        {"description": "INSERT OR REPLACE", "file": "src/platform/rigor/walkforward_universe.py", "line": 81, "implication": "Target=sp100_historical_constituents, sync_conflict_col=None → PK=(ticker, added_date)"},
        {"description": "Dynamic placeholders (engine-agnostic via wrapper rewrite)", "file": "src/journal/store.py", "line": "187 (recommendations) + 241 (shadow_trades)", "implication": "', '.join('?' for _ in row)"},
        {"description": "Dynamic placeholders", "file": "src/features/event_risk_score.py", "line": 95, "implication": "Macro event types IN list"},
        {"description": "Dynamic placeholders", "file": "src/council/value_tracker.py", "line": 306, "implication": "Attributable parameters IN list"},
        {"description": "Dynamic placeholders", "file": "src/api/routes/logs.py", "line": 63, "implication": "Allowed event types IN list"},
        {"description": "Dynamic placeholders", "file": "src/monitoring/system_metrics.py", "line": 142, "implication": "Co-located with INSERT OR REPLACE"},
        {"description": "Dynamic placeholders", "file": "src/shadow_trading/_status_sql.py", "line": "46+54", "implication": "Status filter expansion (TERMINAL_STATUSES, ACTIVE_STATUSES)"},
        {"description": "Dynamic placeholders", "file": "src/platform/promotion.py", "line": 691, "implication": "Status IN list"},
        {"description": "Multi-line SQL with embedded ? placeholders", "file": "src/data_collection/options_collector.py", "line": "138-145", "implication": "executemany with 17-? VALUES tuple; wrapper.executemany also needs ? rewrite"},
        {"description": "SQLite-only date('now') function", "file": "src/api/routes/ib_status.py", "line": 55, "implication": "WHERE date(created_at) = date('now') — PG needs CURRENT_DATE"},
        {"description": "SQLite-only date('now') function", "file": "src/shadow_trading/executor.py", "line": 776, "implication": "Same — PG-incompatible"},
        {"description": "SQLite-only julianday() function", "file": "src/council/agent_data.py", "line": 91, "implication": "CAST(julianday('now') - julianday(actual_entry_time) AS INTEGER) — PG needs EXTRACT(EPOCH FROM NOW() - actual_entry_time) / 86400"}
      ],
      "potential_conflicts": [
        "row[N] integer-indexed access pervasive (60+ references confirmed across 50+ files including hot paths: journal, system_validator, attribution/logger, watch, training, council). RealDictCursor returns dicts that raise KeyError on int access → silent data corruption unless CompatRow class wraps results",
        "45+ assignments of `conn.row_factory = sqlite3.Row` AFTER connect_db. On PG path these become no-ops (PostgresConnectionWrapper.row_factory is a settable attribute with no effect). Informational only — no fix needed, but worth noting in spec that the wrapper accepts the assignment defensively"
      ],
      "relevant_code_snippets": []
    },
    {
      "area": "2. `?`-rewrite edge cases — literal `?` inside string contents",
      "depth": "deep",
      "files_read": ["all src/ files — grep enumeration"],
      "patterns_found": [
        "Searched: `LIKE '?%'`, `SELECT '?'`, `WHERE col REGEXP '\\?'`, string literals containing `?` adjacent to placeholder `?` — ZERO matches",
        "All LIKE queries use form `column LIKE ?` with parameterized binding — never `LIKE '?%'` with literal `?`",
        "VALUES tuples like `\"VALUES ('live_prices', ?)\"`, `\"VALUES (?, ?, ?, ?, 'pending', ?, ?, ?, 'dashboard')\"` are SAFE — `?` characters are placeholders, single-quoted strings contain no `?` chars"
      ],
      "integration_points": [
        {"description": "Naive sql.replace('?', '%s') is SAFE in this codebase", "file": "src/api/cloud_routes/platform.py", "line": 59, "implication": "Existing precedent does this exact replace and works in production"}
      ],
      "potential_conflicts": [
        "Spec must still include the regression test for `?`-in-string-literal as a defensive guarantee — future code additions could introduce such a pattern and silently break. Recommended test: assert that sql with `LIKE '?%'` is NOT rewritten to `LIKE '%s%'`. Implementation: split-on-quotes regex or use sqlparse for full safety, OR document the constraint and lint via test_no_question_in_sql_literals"
      ],
      "relevant_code_snippets": [
        {"file": "src/api/cloud_routes/platform.py", "lines": "55-63", "description": "Production-validated precedent: `pg_sql = sql.replace('?', '%s')` — naive replace, no escape handling, has not caused issues. Wrapper-level rewrite should match this behavior to avoid surprise migrations."}
      ]
    },
    {
      "area": "3. INSERT OR REPLACE/IGNORE → ON CONFLICT mapping per file",
      "depth": "deep",
      "files_read": ["all 17 INSERT OR REPLACE/IGNORE files; src/schema/registry.py for sync_conflict_col"],
      "patterns_found": [
        "8 tables have explicit sync_conflict_col: edgar_filings(accession_number), short_interest(ticker,settlement_date), fed_communications(comm_type,date,title), analyst_estimates(ticker,date,source), macro_snapshots(series_id,collected_date), earnings_calendar(ticker,earnings_date), scan_metrics(created_at), live_prices(ticker)",
        "64 tables have NO sync_conflict_col → engine_aware_upsert must fall back to table.primary_key",
        "12 tables in the INSERT OR list have UUID-style PKs (snapshot_id, debug_id, score_id, etc.) where REPLACE/IGNORE is effectively plain INSERT (no collisions possible by design)",
        "Composite PKs requiring multi-col ON CONFLICT: data_freshness(source,ticker), sp100_historical_constituents(ticker,added_date), minute_bars(ticker,timestamp), operator_view_state(user_id,entry_name), correlation_matrices(5-col), factor_loadings(4-col)"
      ],
      "integration_points": [
        {"description": "Production-validated UPSERT template", "file": "scripts/sqlite_to_pg_migrate.py", "line": "97-119", "implication": "_build_insert_sql_template uses ON CONFLICT (pk_cols) DO NOTHING — wraps composite PKs correctly. engine_aware_upsert(action='ignore') should reuse this pattern; action='replace' extends with DO UPDATE SET col=EXCLUDED.col, ..."},
        {"description": "PK column resolver", "file": "scripts/sqlite_to_pg_migrate.py", "line": "50-53", "implication": "_resolve_primary_key_columns helper handles string-or-list PK forms — reuse in engine_aware_upsert"}
      ],
      "potential_conflicts": [
        "notifications_dedup table has sync_conflict_col=None but has unique idx on (event_type, dedup_key). engine_aware_upsert(table='notifications_dedup', action='ignore') falling back to PK=id will FAIL — id is UUID, never collides, and PG won't dedupe. Spec must check unique indexes when sync_conflict_col is absent OR site must explicitly pass conflict columns. RECOMMENDATION: add sync_conflict_col=(event_type, dedup_key) to notifications_dedup in schema/registry.py as Phase 0 work"
      ],
      "relevant_code_snippets": [
        {"file": "scripts/sqlite_to_pg_migrate.py", "lines": "97-119", "description": "Existing UPSERT template — engine_aware_upsert should reuse the `_resolve_primary_key_columns` helper at line 50 and extend the template builder with DO UPDATE branch for action='replace'"}
      ]
    },
    {
      "area": "4. `tests/test_connect_db_discipline.py` extension scope",
      "depth": "deep",
      "files_read": ["tests/test_connect_db_discipline.py"],
      "patterns_found": [
        "Current allowlist (4 files via affirmative test functions): simulation/engine.py, startup.py, startup_checks.py, shadow_trading/executor.py",
        "Test pattern: paired (no_raw_sqlite3_connect + imports_connect_db) per file. Uses regex `r\"(?:_?sqlite3)\\.connect\\(\"`",
        "EXCLUSIONS from regex: comment lines (starts with #). Does NOT exclude lines inside _sqlite_only_connect helper (relies on file-level allowlist instead)"
      ],
      "integration_points": [
        {"description": "Test file size — currently 120 lines, can easily extend to 240+ for SP5", "file": "tests/test_connect_db_discipline.py", "line": "1-120", "implication": "No test_repo_structure.py size violation projected"}
      ],
      "potential_conflicts": [
        "Test enforces both 'no raw sqlite3.connect' AND 'imports connect_db'. For SQLite-only-by-design files (schema/sqlite.py uses sqlite3.connect inside _sqlite_only_connect), the test must INVERT — assert they DO have raw sqlite3.connect AND DO NOT import connect_db (or do, but for unrelated purposes)",
        "Extending the allowlist requires positive-and-negative test pairs per file. For SP5, NEW allowlist entries: schema/sqlite.py, schema/registry.py, training/trainer.py:1171 (single-line allowlist via inline noqa? OR move to separate sqlite-helper), scheduler/watch.py:1164-1165 (backup API) + 1108-1130 (PRAGMA cluster) — line-range allowlist needed",
        "RETIRING files: sync/render_sync.py + sync/reconcile.py — surface report says both retire with render decommission. Spec must decide whether to ADD them to allowlist (preserved at retirement) or SKIP them in the test (with TODO marker)"
      ],
      "relevant_code_snippets": [
        {"file": "tests/test_connect_db_discipline.py", "lines": "23-39", "description": "_raw_connect_lines helper — extend to support line-range allowlists for partial-file exclusions (e.g. watch.py:1108-1130 + 1164-1165)"}
      ]
    },
    {
      "area": "5. CI infrastructure for pg-tests.yml",
      "depth": "deep",
      "files_read": [".github/ directory listing"],
      "patterns_found": [
        "ZERO existing GitHub Actions workflows. Only `.github/ISSUE_TEMPLATE/` directory and `.github/dependabot.yml` file exist",
        "No `.github/workflows/` directory exists at all"
      ],
      "integration_points": [
        {"description": "No CI workflow precedent — pg-tests.yml builds from scratch", "file": ".github/", "line": 0, "implication": "Spec must specify FULL workflow including: workflow trigger (on: pull_request to main + push to main?), checkout action, Python setup version (3.12 per CLAUDE.md), pip install, postgres:16-alpine sidecar service definition, env TEST_DATABASE_URL, pytest invocation. NO existing pattern to mirror — Architect designs it freely. Recommend matching the operator's local test cmd: `python -m pytest tests/ -q --timeout=60`"}
      ],
      "potential_conflicts": [
        "No existing secret management pattern. TEST_DATABASE_URL for postgres:16-alpine sidecar uses ephemeral container creds (no GitHub secret needed) — `postgres://postgres:postgres@localhost:5432/test_arcis`. Spec should NOT reach for repo secrets",
        "No existing CI workflow means no precedent for: test count enforcement (CLAUDE.md says 3682 floor — gate CI on this), python version pinning, dependency caching. These will need first-time decisions in Architect's plan"
      ],
      "relevant_code_snippets": []
    },
    {
      "area": "6. `conftest.py:postgres_session` fixture implementation",
      "depth": "deep",
      "files_read": ["tests/conftest.py:180-213"],
      "patterns_found": [
        "Fixture is at conftest.py:180-213, scope='function'",
        "Reads TEST_DATABASE_URL (NOT DATABASE_URL — safety guard documented in docstring lines 188-200)",
        "Uses psycopg2.connect(test_database_url, cursor_factory=psycopg2.extras.RealDictCursor)",
        "autocommit=False; rollback in teardown (line 211); close (line 213)",
        "Skips test (pytest.skip) when TEST_DATABASE_URL absent — does NOT fail"
      ],
      "integration_points": [
        {"description": "Lazy fixture-loading pattern via request.getfixturevalue", "file": "tests/test_dashboard_reconciliation.py", "line": "285-288", "implication": "Lets SQLite parametrize variant run unconditionally; postgres variant skips cleanly when TEST_DATABASE_URL absent. This is the prototype for all SP5 dual-engine tests"}
      ],
      "potential_conflicts": [
        "Fixture yields raw psycopg2 connection, NOT a PostgresConnectionWrapper. For SP5 tests of the wrapper itself, tests may want to wrap it: `wrapper = PostgresConnectionWrapper(postgres_session)`. Spec needs to specify whether wrapper is added inside the fixture or per-test"
      ],
      "relevant_code_snippets": [
        {"file": "tests/test_dashboard_reconciliation.py", "lines": "272-303", "description": "Existing prototype @pytest.mark.parametrize('db_backend', ['sqlite', 'postgres']) — every SP5 migrated file test follows this pattern with lazy `request.getfixturevalue('postgres_session')`. Note the asymmetry: SQLite uses mock-runtime fixture, postgres uses real connection. Architect must specify how parametrize handles cases where the migrated function takes a `conn` argument vs uses connect_db() internally"}
      ]
    },
    {
      "area": "7. Watch loop's connect_db touchpoints",
      "depth": "deep",
      "files_read": ["src/scheduler/watch.py:1080-1180 + grep all connect_db sites"],
      "patterns_found": [
        "11 connect_db sites total. ALL pass an explicit path (DB_PATH or self.db_path):",
        "  Line 84: connect_db(self.db_path) — instance path",
        "  Line 147: connect_db(db_path) — function arg",
        "  Lines 546, 934, 995, 1019, 1110, 1142, 1523, 1557, 2219: connect_db(DB_PATH) — module constant",
        "Backup API at lines 1164-1165: raw sqlite3.connect (intentional, SQLite-only Online Backup API — PG has pg_dump)"
      ],
      "integration_points": [
        {"description": "PRAGMA configuration cluster (SQLite-only)", "file": "src/scheduler/watch.py", "line": "1108-1130", "implication": "_configure_database() runs at startup. Calls PRAGMA integrity_check, journal_mode=WAL, synchronous=NORMAL, busy_timeout=5000. On PG path these all raise. MUST be guarded by isinstance(conn, sqlite3.Connection) OR refactored to _configure_sqlite_for_production(conn) helper called only when engine=SQLite"},
        {"description": "Cross-cutting: ALL watch sites pass DB_PATH explicitly", "file": "src/scheduler/watch.py", "line": "various", "implication": "Under current precedence rule, watch loop is forever SQLite-bound. **Architectural decision required**: either (a) Phase 3 cutover removes explicit db_path from watch.py call sites and routes via DATABASE_URL, or (b) precedence is inverted post-migration. Without one of these, DATABASE_URL never reaches the watch loop"}
      ],
      "potential_conflicts": [
        "_check_row_counts at 1142: `conn.execute('SELECT COUNT(*) FROM shadow_trades')` — engine-agnostic SQL, but the diagnostic runs at startup. PG-compatible.",
        "_backup_database at 1156-1177: uses sqlite3.Connection.backup() API (Online Backup) — there is NO PG equivalent. Must remain SQLite-only or be no-op'd on PG."
      ],
      "relevant_code_snippets": [
        {"file": "src/scheduler/watch.py", "lines": "1108-1130", "description": "_configure_database — SQLite-only PRAGMA cluster. Recommend extracting to src/utils/db.py:configure_sqlite_for_production(conn) and calling it only on SQLite path. Alternative: wrap in `if isinstance(conn, sqlite3.Connection)` block."},
        {"file": "src/scheduler/watch.py", "lines": "1156-1177", "description": "_backup_database — uses sqlite3 Online Backup API at lines 1164-1166. Needs allowlist entry in test_connect_db_discipline.py (line-range allowlist OR module-level docstring marker)."}
      ]
    },
    {
      "area": "8. `startup_checks.py` full scan",
      "depth": "deep",
      "files_read": ["src/startup_checks.py (all 483 lines)"],
      "patterns_found": [
        "Imports `sqlite3` at line 16 — UNUSED in the file post-discipline migration (was for raw connect, now uses connect_db)",
        "Two sqlite_master COUNT queries at lines 153 + 166 — both inside check_schema() at lines 143-189",
        "_check_render_postgres at 272-337 ALREADY engine-aware: uses psycopg2.connect(db_url) + information_schema.columns lookups. Existing precedent for PG-side schema introspection",
        "All other connect_db calls in this file pass db_path explicitly (routed SQLite by precedence)"
      ],
      "integration_points": [
        {"description": "sqlite_master COUNT query #1", "file": "src/startup_checks.py", "line": "151-154", "implication": "Runs in success path of check_schema after validate_sqlite returns clean. Replace with engine_aware_table_list(conn) helper"},
        {"description": "sqlite_master COUNT query #2", "file": "src/startup_checks.py", "line": "164-167", "implication": "Runs in error path of check_schema (after fix_issues runs). Same pattern, same fix"},
        {"description": "PG-aware reference for information_schema lookup", "file": "src/startup_checks.py", "line": "321-324", "implication": "`SELECT column_name FROM information_schema.columns WHERE table_name = %s` — model for engine_aware_column_info(table) PG branch"}
      ],
      "potential_conflicts": [
        "validate_sqlite at line 145 — called from check_schema. Reads schema/validator.py which itself contains `SELECT name FROM sqlite_master` at line 43 + `PRAGMA table_info` at line 61. So fixing startup_checks.py alone is insufficient; schema/validator.py either needs engine_aware split or its own _sqlite_only_connect bypass",
        "fix_issues at line 162 — also from schema/validator. Inherits the same issues",
        "The unused `import sqlite3` at line 16 should be removed in Phase 0 cleanup"
      ],
      "relevant_code_snippets": [
        {"file": "src/startup_checks.py", "lines": "143-189", "description": "check_schema function — 2 sqlite_master refs. ALSO calls validate_sqlite + fix_issues from schema/validator which adds 2 more SQLite-isms. Phase migration order matters: schema/validator.py must migrate (or be split) BEFORE startup_checks.py is declared PG-safe"}
      ]
    },
    {
      "area": "9. `journal/store.py` deep dive",
      "depth": "deep",
      "files_read": ["src/journal/store.py (full)"],
      "patterns_found": [
        "Pure SQLite-idiomatic file. Imports sqlite3 at line 12 (used for sqlite3.Row at 6+ assignments).",
        "ALL 18 connect_db calls pass `db_path: str = DB_PATH` — explicitly path-routed → SQLite under current precedence",
        "Dynamic placeholders at: line 187 (recommendations INSERT), 241 (shadow_trades INSERT)",
        "Multi-statement migration UPDATE at line 100: `UPDATE shadow_trades SET actual_exit_time = COALESCE(...) WHERE...` — engine-agnostic syntax",
        "Multi-line SELECT/INSERT patterns with `?` placeholders pervasive (line 191, 214, 246, 269, 295, 319, 343, 348, 467, 489-495, 511, 525, 539, 562-564, 586-588, 604)",
        "executemany NOT used in this file — single execute() everywhere",
        "Uses date()/datetime() Python-side then passes ISO strings via `?` — NO SQL-side date() calls"
      ],
      "integration_points": [
        {"description": "Hot-path INSERT", "file": "src/journal/store.py", "line": "187-191", "implication": "Dynamic placeholders + recommendations INSERT. Wrapper's ?-rewrite handles transparently"},
        {"description": "Hot-path INSERT", "file": "src/journal/store.py", "line": "241-246", "implication": "Same pattern for shadow_trades INSERT — fires on every shadow trade open"},
        {"description": "Hot-path UPDATE", "file": "src/journal/store.py", "line": "264-269", "implication": "update_shadow_trade — fires on every trade update during reconciliation"},
        {"description": "Hot-path SELECT", "file": "src/journal/store.py", "line": "274-284", "implication": "get_open_shadow_trades — fires every position-monitor tick (Tier 1, every 15m)"}
      ],
      "potential_conflicts": [
        "EVERY call site here passes db_path=DB_PATH. By precedence rule, journal/store.py never sees PG even after migration. To exercise PG path: either (1) drop db_path arg at the cutover (huge surface change), (2) invert precedence so DATABASE_URL wins (Sprint 0.5 already tried — the very failure this migration responds to), or (3) accept that journal/store.py remains SQLite-bound while OTHER call paths get PG. The Spec MUST make this explicit"
      ],
      "relevant_code_snippets": [
        {"file": "src/journal/store.py", "lines": "186-192", "description": "Canonical 'dynamic placeholder' pattern: `columns = ', '.join(row.keys()); placeholders = ', '.join('?' for _ in row); conn.execute(f'INSERT INTO {table} ({columns}) VALUES ({placeholders})', values)`. Wrapper-level `?`→`%s` rewrite handles this transparently. Test coverage: must include this exact pattern as a regression-lock unit test"}
      ]
    },
    {
      "area": "10. `monitoring/system_metrics.py` deep dive",
      "depth": "deep",
      "files_read": ["src/monitoring/system_metrics.py (full)"],
      "patterns_found": [
        "Single connect_db call at line 146 (inside _store_snapshot). Passes db_path explicitly (default DB_PATH)",
        "Dynamic placeholder generation at line 142 followed by INSERT OR REPLACE at line 148",
        "Target table: system_metrics, PK=snapshot_id (UUID generated at line 170). sync_conflict_col=None",
        "Since snapshot_id is fresh UUID per snapshot, REPLACE never collides — could be plain INSERT on PG path",
        "Imports sqlite3 at line 14 — UNUSED in code body. Remove in Phase 0"
      ],
      "integration_points": [
        {"description": "INSERT OR REPLACE + dynamic placeholders combined", "file": "src/monitoring/system_metrics.py", "line": "142-150", "implication": "engine_aware_upsert(conn, 'system_metrics', dict(zip(cols, values)), action='replace') — wraps both concerns. Alternative: since snapshot_id is UUID-fresh, use plain INSERT and accept that the 'OR REPLACE' is dead code"}
      ],
      "potential_conflicts": [
        "Frequency: surface report indicates this fires every 5 scans during market hours + on overnight tasks. ~30 writes/hour during active periods. Per-write overhead of ?-rewrite + CompatRow is negligible at this rate."
      ],
      "relevant_code_snippets": [
        {"file": "src/monitoring/system_metrics.py", "lines": "131-152", "description": "Complete _store_snapshot — model for the OR REPLACE → engine_aware_upsert migration. Recommend dropping the OR REPLACE (snapshot_id is UUID, never collides) and using plain INSERT — simpler than full UPSERT translation"}
      ]
    },
    {
      "area": "11. The 7 cloud_routes/*.py files — Option-A precedents",
      "depth": "deep",
      "files_read": ["src/api/cloud_routes/platform.py (full); grep for if database_url patterns across all cloud_routes"],
      "patterns_found": [
        "10 cloud_routes files total: __init__.py, _command_ttl.py, analytics.py, broker_exceptions.py, commands.py, core.py, council.py, diagnostics.py, ib_shadow.py, kpis.py, kpis_compute.py, notes.py, notifications.py, platform.py, preflight.py, system_index.py, trades.py, training.py, walkforward.py",
        "Files with `if database_url:` runtime branching pattern (engine_aware): platform.py(line 56), notifications.py(74, 114), kpis_compute.py(75), walkforward.py(51), preflight.py(220), broker_exceptions.py(50, 118, 162)",
        "All use the same recipe: `database_url = os.environ.get('DATABASE_URL', '')` → if set, raw psycopg2.connect with cursor_factory=RealDictCursor + sql.replace('?', '%s') → else fallback to connect_db(DB_PATH) with sqlite3.Row factory",
        "broker_exceptions.py is the closest to Option-A model: uses `with closing(connect_db()) as conn` (no-args connect_db) on SQLite path at lines 61, 140, 192 + raw psycopg2 on PG path. After SP5 wrapper centralization, this BECOMES Option-A by definition"
      ],
      "integration_points": [
        {"description": "Reference precedent for sql.replace('?', '%s')", "file": "src/api/cloud_routes/platform.py", "line": "55-63", "implication": "Production-validated dual-mode read pattern. Wrapper-level rewrite displaces this manual code in all 7 files"},
        {"description": "RealDictCursor usage", "file": "src/api/cloud_routes/platform.py", "line": 61, "implication": "Confirms operator's existing choice of RealDictCursor for PG — matches the interview decision for the wrapper"}
      ],
      "potential_conflicts": [
        "These files are write-light READ endpoints. They don't currently use engine_aware_upsert because they don't INSERT. So they validate the READ-PATH wrapper logic but NOT the UPSERT helper",
        "After SP5 centralization, _read_rows/_read_one in platform.py become single-line `connect_db()` calls. This is a DELETION not migration — 7 files lose ~25 lines each of manual branching"
      ],
      "relevant_code_snippets": [
        {"file": "src/api/cloud_routes/platform.py", "lines": "43-70", "description": "_read_rows — current dual-mode pattern. Post-SP5: collapses to `conn = connect_db(); rows = conn.execute(sql, params).fetchall(); return [dict(r) for r in rows]`. The `?`→`%s` rewrite is internalized to PostgresConnectionWrapper.execute()"}
      ]
    },
    {
      "area": "12. `scripts/sqlite_to_pg_migrate.py:_build_insert_sql_template`",
      "depth": "deep",
      "files_read": ["scripts/sqlite_to_pg_migrate.py:1-200"],
      "patterns_found": [
        "_build_insert_sql_template at lines 97-119: emits `INSERT INTO {table} ({cols}) VALUES %s ON CONFLICT ({pk_cols}) DO NOTHING`",
        "Designed for psycopg2.extras.execute_values bulk insert (note `VALUES %s` not `VALUES (%s,...)` — execute_values expands the tuples)",
        "Always uses DO NOTHING semantics (no UPDATE branch). Conflict target = PK columns only (does NOT consult sync_conflict_col)",
        "Composite-PK aware: pk_cols is a list, joined into a comma-separated conflict target",
        "_resolve_primary_key_columns at line 50-53: handles string-or-list PK forms"
      ],
      "integration_points": [
        {"description": "Production-validated UPSERT-IGNORE pattern", "file": "scripts/sqlite_to_pg_migrate.py", "line": "97-119", "implication": "engine_aware_upsert(action='ignore') reuses verbatim. action='replace' extends template with `DO UPDATE SET col1=EXCLUDED.col1, col2=EXCLUDED.col2, ...` over non-PK columns"},
        {"description": "PK resolver reuse", "file": "scripts/sqlite_to_pg_migrate.py", "line": "50-53", "implication": "engine_aware_upsert should reuse this helper. Recommend extracting to src/utils/db.py for shared use"}
      ],
      "potential_conflicts": [
        "Migrator uses DO NOTHING for all tables — works for IGNORE semantics. But INSERT OR REPLACE in source files (8 sites) requires DO UPDATE. The migrator was never used for REPLACE semantics. Spec must add the DO UPDATE branch to engine_aware_upsert",
        "Migrator does NOT consult sync_conflict_col — only PK. For tables where INSERT OR IGNORE relies on a unique INDEX (not PK), e.g. notifications_dedup, the migrator would silently allow duplicates. Already-validated against 1.32M rows on Render, so apparently NO live table relies on this pattern at scale, but engine_aware_upsert MUST handle sync_conflict_col when set"
      ],
      "relevant_code_snippets": [
        {"file": "scripts/sqlite_to_pg_migrate.py", "lines": "97-119", "description": "_build_insert_sql_template — extract pattern into src/utils/db.py:_build_pg_upsert_template(table, cols, action, conflict_target). conflict_target = sync_conflict_col if set else PK columns. action='ignore' → DO NOTHING; action='replace' → DO UPDATE SET non-conflict-cols = EXCLUDED.non-conflict-cols"}
      ]
    },
    {
      "area": "13. `src/schema/registry.py` semantics",
      "depth": "moderate",
      "files_read": ["src/schema/registry.py (file too large for full read — used python introspection)"],
      "patterns_found": [
        "72 tables, 940 columns total",
        "table.primary_key: str | list[str]. ALL 72 tables have a non-empty PK (no PK-less tables)",
        "table.sync_conflict_col: str (comma-joined column list) — present on 8 tables only",
        "Composite PKs: correlation_matrices(5-col), factor_loadings(4-col), data_freshness(2-col), sp100_historical_constituents(2-col), minute_bars(2-col), operator_view_state(2-col)",
        "sync_conflict_col uses comma-string format (e.g. 'ticker, settlement_date') — must be split on parsing"
      ],
      "integration_points": [
        {"description": "PK introspection", "file": "src/schema/registry.py", "line": "table.primary_key attribute", "implication": "engine_aware_upsert reads table.primary_key when sync_conflict_col is absent"},
        {"description": "sync_conflict_col is a comma-joined STRING not a list", "file": "src/schema/registry.py", "line": "(varies per table)", "implication": "engine_aware_upsert must `[c.strip() for c in sync_conflict_col.split(',')]` to get column list"}
      ],
      "potential_conflicts": [
        "table.sync_conflict_col format inconsistency: e.g. analyst_estimates has 'ticker, date, source' (with spaces) — parsing must strip. Already handled in render_sync — re-use that parser",
        "For tables without sync_conflict_col AND with UUID PKs (e.g. system_metrics, council_debug_log), engine_aware_upsert(action='ignore') is technically a no-op (UUID never collides). Could short-circuit, but not required for correctness",
        "For tables with NO sync_conflict_col AND a unique index that's the de-facto conflict target (notifications_dedup), Phase 0 should ADD sync_conflict_col to those table definitions in registry.py. Affected: notifications_dedup (unique idx on event_type, dedup_key)"
      ],
      "relevant_code_snippets": []
    },
    {
      "area": "14. SQLite-only-by-design candidates beyond CLAUDE.md",
      "depth": "deep",
      "files_read": ["src/schema/sqlite.py", "src/sync/reconcile.py", "src/sync/render_sync.py (partial)", "src/scheduler/watch.py:1100-1180"],
      "patterns_found": [
        "CLAUDE.md baseline allowlist: schema/sqlite.py, schema/registry.py, scheduler/watch.py(backup API only 1164-1165), training/trainer.py(line 1171)",
        "Surface report flagged WATCH.PY PRAGMA CLUSTER 1108-1130 as candidate — CONFIRMED SQLite-only. Recommend wrap in isinstance OR refactor to dedicated helper",
        "Sync layer (sync/render_sync.py + sync/reconcile.py): HYBRID by design. render_sync.py opens SQLite (raw sqlite3.connect at 7 sites) to read source-of-truth, then writes to PG via psycopg2. reconcile.py mirrors this. BOTH retire when PG becomes source-of-truth (Wave 3 cutover scope per surface report)",
        "_sqlite_only_connect helper exists ONLY in src/schema/sqlite.py:18. No other module has a similar bypass helper"
      ],
      "integration_points": [
        {"description": "watch.py:1108-1130 PRAGMA cluster", "file": "src/scheduler/watch.py", "line": "1108-1130", "implication": "Either: (1) Add `if isinstance(conn, sqlite3.Connection):` guard around lines 1112-1131; or (2) Extract to src/utils/db.py:configure_sqlite_for_production(conn) and call only when engine=SQLite. Option 2 is cleaner — moves SQLite-specific tuning out of watch.py"},
        {"description": "watch.py:1164-1165 backup API", "file": "src/scheduler/watch.py", "line": "1164-1165", "implication": "Raw sqlite3.connect for Online Backup API (`src.backup(dst)`). PG has no equivalent — _backup_database must check engine and no-op or skip on PG. Test discipline allowlist: line-range exception OR module-level marker"},
        {"description": "sync/reconcile.py", "file": "src/sync/reconcile.py", "line": "full file", "implication": "HYBRID confirmed — designed for both engines. RETIRES with render decommission. Test discipline: add to retiring-allowlist with TODO marker"}
      ],
      "potential_conflicts": [
        "sync/render_sync.py and sync/reconcile.py both use raw sqlite3.connect — adding them to the SQLite-only-by-design allowlist will hide a real future audit issue (they retire, not stay). Better: tag them with `# RETIRING: render_sync sunset` marker and split the test_connect_db_discipline.py into 'permanent allowlist' (schema/sqlite.py, schema/registry.py, etc.) and 'retiring allowlist' (sync/*, with explicit removal TODO when render decommissions)"
      ],
      "relevant_code_snippets": [
        {"file": "src/scheduler/watch.py", "lines": "1106-1136", "description": "_configure_database — refactor target. Extract PRAGMA cluster (lines 1112-1131) into src/utils/db.py:configure_sqlite_for_production(conn). watch.py becomes engine-agnostic — calls the helper only when engine=SQLite"}
      ]
    },
    {
      "area": "15. Migration sequencing dependencies",
      "depth": "deep",
      "files_read": ["module-import-graph analysis from connect_db usage + import statements"],
      "patterns_found": [
        "Foundational dependency: src/utils/db.py (no internal deps, only psycopg2 + sqlite3 + src.config)",
        "Phase 0 must land first: utils/db.py wrapper + engine_aware helpers + CompatRow",
        "Phase 1 ordering by dependency (downstream → upstream):",
        "  Layer 1 (leaf): journal/store.py, monitoring/system_metrics.py, evaluation/build_score.py, data_collection/* (collectors)",
        "  Layer 2: notifications/platform_events.py, council/*, evaluation/system_validator.py",
        "  Layer 3: api/routes/* (depends on layer 1+2)",
        "  Layer 4: scheduler/watch.py (depends on everything below + journal)",
        "  Layer 5: startup_checks.py + startup.py (depends on schema/validator which depends on schema/registry)",
        "schema/validator.py has SQLite-isms (line 43 sqlite_master, line 61 PRAGMA). It's called by startup_checks.py. Migrating schema/validator BEFORE startup_checks is critical — OR split it into validate_sqlite + validate_postgres",
        "data_collection/retention.py has SQLite-isms (line 108 sqlite_master, line 116 PRAGMA). It depends on schema/registry (TABLES). Migrate after Phase 0",
        "evaluation/system_validator.py is HEAVILY called (system_validator → many run-time check paths). Has SQLite-isms at line 165 (PRAGMA journal_mode), 175 (sqlite_master), and 15+ row[N] integer accesses. HIGH-RISK migration",
        "shadow_trading/executor.py is in the current discipline allowlist BUT has date('now') at line 776 — SQLite-only. Migration needs runtime SQL rewrite to CURRENT_DATE"
      ],
      "integration_points": [
        {"description": "Cross-cutting dependency", "file": "src/schema/validator.py", "line": "43+61", "implication": "Both startup_checks.py AND data_collection/retention.py AND data_enrichment/staleness.py read schema/validator. Schema validator migrates first OR splits"},
        {"description": "ALL hot-path files depend on src/utils/db.py", "file": "src/utils/db.py", "line": "wrapper", "implication": "Phase 0 must absorb all wrapper risk before any file-level migration. No parallelization possible across Phase 0/Phase 1 boundary"}
      ],
      "potential_conflicts": [
        "training/trainer.py line 1171 uses `_sqlite3.connect(db_path)` (aliased import) — this is training data writer, SQLite-only-by-design per CLAUDE.md. Test discipline must whitelist line 1171 specifically",
        "scheduler/watch.py has connect_db at 11 sites — migrating watch.py is the cutover gate itself. CANNOT be parallel with Phase 0 wrapper work"
      ],
      "relevant_code_snippets": []
    },
    {
      "area": "16. Performance hotspots",
      "depth": "moderate",
      "files_read": ["src/scheduler/watch.py (skim), src/journal/store.py, src/monitoring/system_metrics.py"],
      "patterns_found": [
        "Watch loop tick frequency: every 60s (line 1247-1276) — sleep-loop with hour/minute dispatching",
        "Per-tick DB queries (hot path):",
        "  Position monitor (every 15m): journal/store.get_open_shadow_trades — 1x SELECT, returns N rows where N is active position count (typically <20)",
        "  Market scans (every 30m): journal/store INSERT to recommendations — N inserts where N=scan output (~5-50)",
        "  System metrics (every 5 scans): monitoring/system_metrics single INSERT OR REPLACE",
        "  Telegram polling (high freq): notifications/telegram_commands SELECT activity_log LIKE",
        "Background sync thread: render_sync (every ~60s) — N SELECT + INSERT per table per sync window",
        "Journal write rate during market hours: ~5-20 inserts/min combined (recommendations + shadow_trades updates)",
        "Total DB operations/min during peak: ~30-100",
        "Per-call overhead of ?-rewrite: O(len(sql)) string scan — ~1μs for typical SQL. CompatRow wrap: O(N cols) per row, ~5μs. Negligible at observed rates"
      ],
      "integration_points": [
        {"description": "Highest-frequency hot path", "file": "src/notifications/telegram_commands.py", "line": "141", "implication": "Telegram poll queries — checked every few seconds during long-poll intervals. Verify wrapper overhead stays <1ms per call"},
        {"description": "Bulk insert path", "file": "src/data_collection/options_collector.py", "line": "138-145", "implication": "executemany with up to 1000-row chunks (options chain pulls). Wrapper's executemany must rewrite ? once not per-row"}
      ],
      "potential_conflicts": [
        "No SQLite full-scan queries observed — all hot paths are indexed lookups. Migration won't accidentally regress to seq scans",
        "Render Postgres latency from local (~30-80ms round-trip) is the dominant cost — wrapper overhead is dwarfed by network. So even 100μs of overhead per call is irrelevant. Spec doesn't need benchmarks beyond a sanity-check 'no >5x regression' assertion"
      ],
      "relevant_code_snippets": []
    },
    {
      "area": "17. test_dashboard_reconciliation.py parametrization prototype",
      "depth": "deep",
      "files_read": ["tests/test_dashboard_reconciliation.py:260-304"],
      "patterns_found": [
        "Uses @pytest.mark.parametrize('db_backend', ['sqlite', 'postgres'])",
        "postgres fixture is LAZY-LOADED via `request.getfixturevalue('postgres_session')` — only resolves when db_backend=='postgres', allowing sqlite variant to run unconditionally",
        "Asserts postgres_session is not None before proceeding",
        "Reuses the same `_make_runtime()` + `_make_client()` test helpers — does NOT exercise the connection directly; only validates that the endpoint emits _meta envelope under both backends. This is a SHALLOW test — proves the route works but NOT that the underlying SQL is engine-portable",
        "Skip semantics: pytest.skip inside fixture when TEST_DATABASE_URL absent → reported as SKIPPED not FAILED → test count stable across environments"
      ],
      "integration_points": [
        {"description": "Lazy fixture pattern", "file": "tests/test_dashboard_reconciliation.py", "line": "286-288", "implication": "Required pattern for SP5 tests so SQLite variant runs in CI without TEST_DATABASE_URL"}
      ],
      "potential_conflicts": [
        "Existing prototype tests _meta envelope (route-level), NOT the migrated function (SQL-level). For SP5, tests must exercise the actual `connect_db()` -> execute() -> fetchone()/fetchall() path. Recommended: test inserts a row, reads it back, asserts equality across engines. This requires WRITE access in tests — which the prototype doesn't exercise (it only does reads via the route)",
        "TEST_DATABASE_URL pointing at a clean ephemeral postgres:16-alpine sidecar in CI: schema must be created fresh per CI run. Spec needs schema bootstrap step (Phase 0 wrapper has no schema-create logic for PG — schema/postgres.py exists for that)"
      ],
      "relevant_code_snippets": [
        {"file": "tests/test_dashboard_reconciliation.py", "lines": "272-303", "description": "Prototype @pytest.mark.parametrize dual-engine test. For SP5 file-level migration tests, the pattern extends: test fixture must bootstrap schema in the postgres branch (create_all_tables from schema/postgres.py), then exercise the migrated function with real INSERT+SELECT, then assert result-equivalence across both engines"}
      ]
    },
    {
      "area": "18. _sqlite_only_connect-style bypass helpers",
      "depth": "deep",
      "files_read": ["grep for sqlite3.connect across all src/"],
      "patterns_found": [
        "Only ONE _sqlite_only_connect helper exists: src/schema/sqlite.py:18-36",
        "Raw sqlite3.connect call sites in src/ (excluding wrapper at utils/db.py:145):",
        "  scheduler/watch.py:1164, 1165 (backup API — SQLite-only-by-design)",
        "  training/trainer.py:1171 (training data writer — SQLite-only-by-design, uses `_sqlite3.connect` alias)",
        "  schema/sqlite.py:33, 226 (already wrapped by _sqlite_only_connect at the function level)",
        "  sync/reconcile.py:100, 194 (HYBRID — retires)",
        "  sync/render_sync.py:83, 454, 479, 507, 525, 886, 935 (HYBRID — retires)",
        "Total: 14 raw sqlite3.connect sites outside utils/db.py. 9 will retire with render_sync; 5 stay (3 schema/sqlite internal, 2 backup, 1 training)"
      ],
      "integration_points": [],
      "potential_conflicts": [
        "No other bypass helper exists — spec doesn't need to handle multiple _sqlite_only_connect variants. The single existing helper in schema/sqlite.py is the canonical pattern. If SP5 adds new SQLite-only-by-design files, they should call schema/sqlite._sqlite_only_connect (export it) OR define their own inline 3-line raw sqlite3.connect + busy_timeout + Row factory"
      ],
      "relevant_code_snippets": [
        {"file": "src/schema/sqlite.py", "lines": "18-36", "description": "Canonical _sqlite_only_connect — documents WHY (the rollback hazard), applies busy_timeout=30000 + row_factory=sqlite3.Row. Spec: consider re-exporting via src/utils/db.py:_sqlite_only_connect so any SQLite-only-by-design file uses the same helper. Currently only schema/sqlite.py knows about it"}
      ]
    },
    {
      "area": "19. Cross-engine SQL syntax differences inventory",
      "depth": "deep",
      "files_read": ["grep across all src/ for known SQLite-PG dialect divergences"],
      "patterns_found": [
        "JULIANDAY: 1 site — src/council/agent_data.py:91 `CAST(julianday('now') - julianday(actual_entry_time) AS INTEGER)`. PG equivalent: `EXTRACT(EPOCH FROM (NOW() - actual_entry_time)) / 86400`",
        "DATE('now'): 2 sites — src/api/routes/ib_status.py:55 `WHERE date(created_at) = date('now')`, src/shadow_trading/executor.py:776 `... AND created_at > date('now')`. PG: `CURRENT_DATE`. Note that since created_at is stored as ISO strings/timestamps, both engines work with this query IF rewritten",
        "String concat `||`: ZERO matches in SQL contexts (only Python expressions). PG-compatible",
        "REGEXP / json_extract / json_each / json_array: ZERO matches. JSON columns stored as TEXT and parsed Python-side",
        "LIMIT offset,count (SQLite/MySQL): ZERO matches. All queries use `LIMIT N OFFSET M` form (engine-agnostic)",
        "INSERT INTO ... DEFAULT VALUES: ZERO matches",
        "WITH RECURSIVE: ZERO matches",
        "Boolean literals: SQL uses 1/0 throughout (not TRUE/FALSE). PG accepts integer 1/0 in WHERE col=1 contexts — works",
        "AUTOINCREMENT: Only at DDL layer (schema/sqlite.py:87). Runtime never references it",
        "ROWID: 2 informational refs in render_sync.py:694+717 (auto-repair of NULL ids from SQLite ROWID before pushing to PG). Used during sync ETL, NOT runtime queries"
      ],
      "integration_points": [
        {"description": "julianday rewrite required", "file": "src/council/agent_data.py", "line": 91, "implication": "Spec must specify exact PG equivalent. Recommendation: extract days-between-timestamps logic to a Python helper that returns int, avoid SQL-side date math entirely"},
        {"description": "date('now') rewrite required", "file": "src/api/routes/ib_status.py", "line": 55, "implication": "Replace with `CURRENT_DATE` or compute date in Python and pass as parameter"},
        {"description": "date('now') rewrite required", "file": "src/shadow_trading/executor.py", "line": 776, "implication": "Same. NOTE: executor.py is in the existing test_connect_db_discipline.py allowlist already (no raw sqlite3.connect) — but this is a separate SQLite-only-SQL issue not raw connection issue"}
      ],
      "potential_conflicts": [
        "Spec recommendation: add a 4th test in test_no_sqlite_isms_in_pg_safe_files.py specifically for SQL dialect functions: `\\bjulianday\\(`, `\\bdate\\('now'\\)`, `\\bdatetime\\('now'\\)`. Catches future regressions"
      ],
      "relevant_code_snippets": []
    },
    {
      "area": "20. Phase 0 wrapper integration points (post-rollback state)",
      "depth": "deep",
      "files_read": ["src/utils/db.py (149 lines, full)"],
      "patterns_found": [
        "File is 149 lines post-rollback. PostgresConnectionWrapper class at lines 48-95.",
        "Existing PostgresConnectionWrapper methods: cursor(line 61), execute(64-70), executemany(72-75), commit(77), rollback(80), close(83), __enter__(86), __exit__(89-95)",
        "row_factory attribute is a no-op accept (line 59) — setter works but value is ignored",
        "connect_db function at lines 98-148. Precedence: explicit db_path > DATABASE_URL > DEFAULT_DB (SQLite)",
        "Sentinel default pattern: `db_path=_SENTINEL` at line 98. None means open `:memory:` (test compat). _SENTINEL means consult DATABASE_URL"
      ],
      "integration_points": [
        {"description": "execute method — add ?-rewrite", "file": "src/utils/db.py", "line": "64-70", "implication": "Insert `sql = sql.replace('?', '%s')` as first statement after method body opens, OR more defensive: regex-skip-quoted-segments. Wrap returned cur in compat-row cursor"},
        {"description": "executemany method — add ?-rewrite", "file": "src/utils/db.py", "line": "72-75", "implication": "Same rewrite. params iterable need not be rewritten — only SQL string"},
        {"description": "cursor method — wrap for compat-row factory", "file": "src/utils/db.py", "line": "61-62", "implication": "Return _RowFactoryCursor(self._conn.cursor()) so callers that use `cur = conn.cursor()` directly still get CompatRow"},
        {"description": "New: CompatRow class", "file": "src/utils/db.py", "line": "(insert after line 47)", "implication": "Class supporting BOTH `row[0]` int index AND `row['col']` named access. Wraps a dict (from RealDictCursor) and provides __getitem__ that branches on isinstance(key, int) → keys()[key] else self._dict[key]. Also keys(), __iter__, __contains__"},
        {"description": "New: engine_aware_upsert function", "file": "src/utils/db.py", "line": "(insert after connect_db)", "implication": "Signature: engine_aware_upsert(conn, table_name, row_dict, action='replace'|'ignore'). Branches on isinstance(conn, PostgresConnectionWrapper). Reads src.schema.registry.TABLES[table_name] for sync_conflict_col + primary_key. Builds INSERT INTO ... ON CONFLICT (target) DO NOTHING|UPDATE SET col=EXCLUDED.col. Uses table.sync_conflict_col if set else table.primary_key (comma-string-split)"},
        {"description": "New: engine_aware_table_list helper", "file": "src/utils/db.py", "line": "(after engine_aware_upsert)", "implication": "Branches on engine. SQLite: SELECT name FROM sqlite_master WHERE type='table'. PG: SELECT table_name FROM information_schema.tables WHERE table_schema='public'"},
        {"description": "New: engine_aware_column_info helper", "file": "src/utils/db.py", "line": "(after engine_aware_table_list)", "implication": "SQLite: PRAGMA table_info(table). PG: SELECT column_name, data_type, is_nullable, column_default FROM information_schema.columns WHERE table_name=%s. Return shape: list of (cid, name, type, notnull, default, pk) tuples to match SQLite output"},
        {"description": "New: engine_aware_index_list helper", "file": "src/utils/db.py", "line": "(after engine_aware_column_info)", "implication": "SQLite: PRAGMA index_list(table). PG: SELECT i.relname, ix.indisunique FROM pg_index ix JOIN pg_class i ON i.oid=ix.indexrelid JOIN pg_class t ON t.oid=ix.indrelid WHERE t.relname=%s"},
        {"description": "New: engine_aware_foreign_keys helper", "file": "src/utils/db.py", "line": "(after engine_aware_index_list)", "implication": "SQLite: PRAGMA foreign_key_list(table). PG: information_schema.referential_constraints + key_column_usage joins"},
        {"description": "Optional: re-export _sqlite_only_connect", "file": "src/utils/db.py", "line": "(import + re-export)", "implication": "from src.schema.sqlite import _sqlite_only_connect — makes it accessible via src.utils.db._sqlite_only_connect for SQLite-only-by-design callers without forcing schema/sqlite import"}
      ],
      "potential_conflicts": [
        "Current cursor() at line 61 returns the raw psycopg2 cursor — direct callers that do `cur = conn.cursor()` then `cur.execute(sql, params)` will BYPASS the wrapper's `?`-rewrite. Spec MUST wrap the returned cursor with a custom class _RowFactoryCursor whose execute/executemany also rewrite",
        "PostgresConnectionWrapper.cursor() currently returns the underlying psycopg2 cursor (line 62). For consistency the wrapper class must be a deep facade — every entry point that produces a cursor or returns rows needs CompatRow integration",
        "fetchone() / fetchall() are called on the cursor — those are psycopg2 cursor methods. Wrapping in _RowFactoryCursor means overriding fetchone/fetchall/fetchmany to wrap returned dicts in CompatRow",
        "The `with connect_db(db_path) as conn` context-manager use at 70+ call sites: when conn is a PostgresConnectionWrapper, __exit__ commits on success / rolls back on exception. Current implementation looks correct (lines 89-95). Confirm test coverage"
      ],
      "relevant_code_snippets": [
        {"file": "src/utils/db.py", "lines": "48-95", "description": "PostgresConnectionWrapper — current state. Phase 0 INSERTION POINTS: (1) before line 64, add _PLACEHOLDER_REGEX = re.compile(r'(?<![?])\\?(?!\\?)'); (2) lines 64-70, insert sql rewrite + wrap returned cur; (3) lines 72-75, same; (4) line 61-62, replace return with `return _RowFactoryCursor(self._conn.cursor())`; (5) add _RowFactoryCursor + CompatRow classes BEFORE PostgresConnectionWrapper; (6) add engine_aware_* helper functions AFTER connect_db"},
        {"file": "src/utils/db.py", "lines": "98-148", "description": "connect_db — current precedence rule unchanged. Phase 0 modifications NONE here — wrapper bug fixes only. The precedence-inversion question (whether Phase 3 cutover changes this) is a Phase 3 spec decision, NOT a Phase 0 wrapper change"}
      ]
    }
  ],
  "cross_cutting_concerns": [
    "**Test count floor at 3682** — every wrapper-test + per-file-migration test ADDS, never replaces. Spec must explicitly track new test count per phase. Requirement says +100 minimum.",
    "**Worktree isolation mandatory** per CLAUDE.md — every parallel agent dispatch needs `isolation: worktree`. Worktrees do NOT carry .env, so TEST_DATABASE_URL won't be set in worktree CI runs by default. Spec must specify how worktrees source TEST_DATABASE_URL (likely: pass-through via agent dispatch env config, OR rely on postgres:16-alpine sidecar in CI which doesn't need .env)",
    "**No CREATE/ALTER TABLE outside src/schema/** — engine_aware_upsert MUST NOT issue DDL. PostgresConnectionWrapper.execute() raises if it sees CREATE/ALTER (defensive). Schema/registry remains the single authority",
    "**Render Postgres latency** — ~30-80ms round-trip from local. Wrapper overhead is dwarfed by network. Performance benchmarks should focus on round-trip count regressions, not per-call microseconds",
    "**The cutover question is unresolved**: current precedence is 'explicit db_path wins'. ALL 11 watch.py + 18 journal/store.py call sites pass DB_PATH. Under this rule, DATABASE_URL never routes the hot path. **Phase 3 spec MUST DECIDE**: invert precedence post-Phase 1/2, OR rewrite call sites to drop db_path arg, OR add an opt-in `prefer_database_url=True` flag. The 2026-05-10 attempt failed by inverting precedence prematurely (before Phase 0 wrapper landed). The Architect must spec this explicitly",
    "**Render decommission is OUT OF SCOPE** per requirements — but the sync/render_sync.py + sync/reconcile.py files exist in the codebase NOW with raw sqlite3.connect everywhere. Test discipline must accept them as 'retiring allowlist' with explicit TODO markers, NOT treat them as permanent SQLite-only-by-design",
    "**`.env` env var inheritance in tests**: conftest.py:_isolate_local_api_token_env clears ARCIS_LOCAL_API_TOKEN per-test. Similar pattern needed: postgres_session reads TEST_DATABASE_URL but tests should NOT see operator's DATABASE_URL leak in (worktree .env carry-through concern documented in CLAUDE.md). conftest fixture should monkeypatch.delenv('DATABASE_URL') in autouse to prevent the wrapper accidentally routing to operator's prod Render"
  ],
  "coverage_gaps": [
    "Did NOT read full src/schema/registry.py (46k tokens) — used Python introspection for table/column/PK/sync_conflict_col metadata instead. If the Architect needs e.g. per-table FK relationships or column type details, registry.py needs targeted re-read",
    "Did NOT enumerate the COMPLETE row[N] integer-indexed access list — sampled 60+ occurrences across 50+ files but did not produce a per-file inventory. For the spec's CompatRow test plan, the Architect can either (a) add the test to test_no_sqlite_isms_in_pg_safe_files.py as a regression-lock, or (b) accept that CompatRow's job is exactly to support row[0]; integer access is FINE post-Phase-0 and doesn't need per-file enumeration",
    "Did NOT read src/sync/render_sync.py in full (1364 lines) — only confirmed structure via grep + spot checks. Since this file retires with render decommission, full migration mapping is unnecessary",
    "Did NOT verify whether test_dashboard_reconciliation.py's prototype actually runs the SQL path or only the route-level path. Spec needs the actual SQL exercise pattern for migrated-function tests — the Architect should write a NEW prototype test (not extend the existing one) that exercises connect_db() → INSERT → SELECT → assert across both engines",
    "Did NOT inventory every multi-line SQL string with embedded `?` — too many to enumerate exhaustively. Coverage gap: a future SQL with `\"LIKE '?%'\"` string-literal-containing-? could trip the wrapper's naive rewrite. Spec MUST include the regression-lock test as a defensive guarantee even though no current site triggers it",
    "Did NOT enumerate ALL 339 connect_db call sites — surface report claim is 339, my count is 482 references in 120 unique files (counting comments + imports + actual calls). The 339 figure is plausible as 'actual function call sites' vs 'string occurrences'. For the spec's scope-fencing, file count (120) is more useful than call-site count"
  ]
}
</codebase_report>

**Findings summary for Architect:**

**Critical architectural decision required (cutover gate):** The current `connect_db()` precedence rule ("explicit db_path wins") means EVERY hot-path call site (watch.py, journal/store.py, monitoring, etc.) passes DB_PATH and is permanently SQLite-routed. DATABASE_URL only reaches the 4 no-args `connect_db()` call sites (all in cloud_routes). Phase 3 cutover REQUIRES one of: (a) invert precedence so DATABASE_URL wins (what the failed 2026-05-10 attempt did — now safe AFTER Phase 0 wrapper + Phase 1 file migrations), (b) systematically remove db_path arg at call sites, or (c) add explicit opt-in flag. Spec must declare this in Phase 3.

**Phase 0 wrapper integration points** are fully mapped — see focus area 20. The wrapper currently lacks `?`→`%s` rewrite, CompatRow, and all 4 engine_aware_* helpers. Production precedent at `src/api/cloud_routes/platform.py:_read_rows` (lines 43-70) validates the naive `sql.replace('?', '%s')` works at scale.

**21 PRAGMA + 5 sqlite_master + 17 INSERT OR REPLACE/IGNORE + 9 dynamic-placeholder sites enumerated** with file:line + target table + sync_conflict_col mapping. The migration scope-fence is 28 files total (excluding sync/* and schema/* which are SQLite-only-by-design or retiring). 8 of 72 schema tables carry `sync_conflict_col`; the other 64 must fall back to PK for ON CONFLICT.

**Hidden SQL function dependencies beyond the surface-report list:** `julianday('now')` at council/agent_data.py:91, and `date('now')` at api/routes/ib_status.py:55 + shadow_trading/executor.py:776. None show up in PRAGMA/sqlite_master/OR-REPLACE inventories but are PG-incompatible. Spec must include them in `test_no_sqlite_isms_in_pg_safe_files.py` patterns.

**CI infrastructure starts from zero** — no `.github/workflows/` exists; `pg-tests.yml` builds fresh.

**Test count gate:** 3682 floor. Spec requires ≥+100 — implementation plan should target ~+30 Phase 0 (wrapper unit tests), then ≥+1 per migrated file in Phase 1-3 (~+75-100).

**Files referenced (absolute paths):**
- `C:/arcis/halcyon-lab/src/utils/db.py` — Phase 0 foundation
- `C:/arcis/halcyon-lab/src/schema/registry.py` — schema authority
- `C:/arcis/halcyon-lab/src/schema/sqlite.py` — canonical `_sqlite_only_connect` precedent
- `C:/arcis/halcyon-lab/scripts/sqlite_to_pg_migrate.py` — `_build_insert_sql_template` pattern (lines 97-119)
- `C:/arcis/halcyon-lab/src/api/cloud_routes/platform.py` — `?`→`%s` rewrite production precedent (lines 43-70)
- `C:/arcis/halcyon-lab/tests/conftest.py` — `postgres_session` fixture (lines 180-213)
- `C:/arcis/halcyon-lab/tests/test_dashboard_reconciliation.py` — dual-engine parametrize prototype (lines 272-303)
- `C:/arcis/halcyon-lab/tests/test_connect_db_discipline.py` — current allowlist (4 files)
- `C:/arcis/halcyon-lab/src/scheduler/watch.py` — PRAGMA cluster at 1108-1130, backup API at 1164-1165
- `C:/arcis/halcyon-lab/src/journal/store.py` — hot-path dynamic-placeholder pattern (lines 186-192, 240-246)
- `C:/arcis/halcyon-lab/src/monitoring/system_metrics.py` — combined OR REPLACE + dynamic placeholder (lines 131-152)
- `C:/arcis/halcyon-lab/src/startup_checks.py` — `_check_render_postgres` engine-aware precedent (lines 272-337) + sqlite_master at 151-167