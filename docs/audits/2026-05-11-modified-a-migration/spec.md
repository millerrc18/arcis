# Modified-A Migration — SP5 §J5/§J6 Design Spec (REVISION 2)

**Date:** 2026-05-11
**Status:** EXECUTION-READY (revised per Devil's Advocate findings C1-C3, M1-M6)
**Read time:** ~18 min
**Source audit:** `docs/audits/2026-05-10-cloudflare-tunnel-cutover/sqlite-isms-prelim-audit.md`
**Failed precedent:** `commit 449dfc0` rollback (precedence-inversion crashed 2 min after NSSM env flip)

---

## 1. Overview

The Cloudflare-Tunnel cutover landed the Modified-A **infrastructure** (Docker PG, auth, tunnel) on 2026-05-10. The remaining work — SP5 §J5/§J6 — is the **SQLite→PG dialect-impedance migration of 339 `connect_db()` call sites + dual-engine regression-locks + Sat morning cutover retry**.

The 2026-05-10 attempt failed in 2 min by inverting `connect_db()` precedence before centralising the impedance handling. Three concurrent code paths broke. This spec centralises every such impedance in `src/utils/db.py`, migrates the 17 SQLite-ism-bearing sites across 16 files in two waves, adds CI-enforced dual-engine regression tests, then re-runs the cutover under a kill-switch env gate.

**Revision 2 fixes (Devil's Advocate findings):**
- **C1 — Literal-% in SQL** Rewrite must double unpaired `%` to `%%` for psycopg2 binding. Added T0.0 pre-flight audit + spec section 2.3 update.
- **C2 — REPLACE semantic divergence** Added T0.12 audit of FK/cascade/AUTOINCREMENT behaviour across the 10 `action='replace'` tables. Per-table mitigation in T0.4.
- **C3 — CompatRow iteration semantics** Spec section 2.2 + T0.1 tests explicitly state CompatRow iterates VALUES (not keys), matching `sqlite3.Row`.
- **M1 — Quote-aware + %-aware rewrite** T0.2 ships a real parser, not naive replace. Bumped to standard complexity.
- **M2 — Precedence-flip kill-switch** T3.2 precedence flip gated behind `ARCIS_PG_CUTOVER_ENABLED=1` env var; defaults off; flipped on at T3.3; removed in Phase 4.
- **M3 — Zombie-watchdog avoidance** T0.11 retry exhaustion calls `sys.exit(1)` after watchdog.txt write so NSSM restarts the service (no zombie watch loop without DB).
- **M4 — AST-based static analysis** T2.14 uses Python AST to catch dynamic-placeholder SQL fragments (the 2026-05-10 bug class).
- **M5 — Baseline NSSM env preservation** Added T3.0 pre-cutover gate to verify PYTHONUTF8/ARCIS_DB_PATH/etc are preserved when DATABASE_URL is appended.
- **M6 — Test count reconciliation** Section 5.3 reconciled per-task; target +100, accept +90 to +140 without re-issue.

**Out-of-scope retirement:** `src/sync/render_sync.py`, `src/sync/reconcile.py`, `src/api/cloud_app.py` are deleted in Phase 4.

---

## 2. Architecture

### 2.1 Cutover invariant (the precedence question — RESOLVED, kill-switched)

**Phase 3 precedence rule (lands in T3.2, behind env gate):**
```
if os.environ.get('ARCIS_PG_CUTOVER_ENABLED') == '1' and DATABASE_URL.startswith('postgres'):
    → PostgresConnectionWrapper (ignore db_path argument; log one-time warning if passed)
else:
    → sqlite3.Connection (use db_path if provided; else DEFAULT_DB)
```

**Why the env gate (M2 mitigation):** Without it, merging T3.2 to main flips precedence on every developer machine that happens to have `DATABASE_URL=postgresql://...` exported (e.g. from another project). The gate makes T3.2's merge a no-op on developer boxes; only the production NSSM service has `ARCIS_PG_CUTOVER_ENABLED=1` set (alongside `DATABASE_URL`) at T3.3. The gate is removed in Phase 4 cleanup once cutover is stable.

### 2.2 Wrapper layer (`src/utils/db.py`) — grown from 149 to ~470 LOC

Components added in Phase 0 (revised):

| Component | Purpose |
|---|---|
| `CompatRow` class | Wraps a RealDictRow to support BOTH `row[0]` (int index) AND `row['col']` (named). **CRITICAL (C3): iterates VALUES, not keys** — `__iter__` yields `iter(self._row.values())` so `for v in row:` and `tuple(row)` and `list(row)` and `a, b = row` all match `sqlite3.Row` semantics. `__len__` returns column count. `keys()` returns the column-name iterator for explicit name access. |
| `_RowFactoryCursor` class | Wraps psycopg2 cursor; overrides `fetchone/fetchall/fetchmany` to wrap returned dicts in CompatRow; overrides `execute/executemany` to rewrite `?`→`%s` AND escape un-paired `%`→`%%` |
| `PostgresConnectionWrapper.execute()` | Adds the `?`→`%s` + `%`→`%%` rewrite; returns `_RowFactoryCursor` |
| `PostgresConnectionWrapper.executemany()` | Same rewrite, returns `_RowFactoryCursor` |
| `PostgresConnectionWrapper.cursor()` | Returns `_RowFactoryCursor(self._conn.cursor())` |
| `engine_aware_upsert(conn, table, row_dict, action)` | Per-engine UPSERT. SQLite: `INSERT OR REPLACE/IGNORE`. PG `action='ignore'`: `INSERT … ON CONFLICT DO NOTHING` (mirrors migrator). PG `action='replace'`: **per-table dispatch driven by T0.12 audit** — for tables where SQLite DELETE-then-INSERT semantics matter (FK cascade, AUTOINCREMENT rowid), uses explicit `DELETE WHERE conflict_cols=… ; INSERT INTO …`. For tables where in-place UPDATE is acceptable, uses `INSERT … ON CONFLICT … DO UPDATE SET non-target=EXCLUDED.non-target`. The per-table choice is hard-coded in a `_REPLACE_SEMANTICS` dict in `src/utils/db.py`. |
| `engine_aware_table_list(conn)` | SQLite: `sqlite_master`; PG: `information_schema.tables` |
| `engine_aware_column_info(conn, table)` | SQLite: `PRAGMA table_info(table)`; PG: `information_schema.columns`. Returns shape-matched tuple list |
| `engine_aware_index_list(conn, table)` | SQLite: `PRAGMA index_list(table)`; PG: `pg_index/pg_class` join |
| `engine_aware_foreign_keys(conn, table)` | SQLite: `PRAGMA foreign_key_list(table)`; PG: `information_schema.referential_constraints + key_column_usage` |
| `configure_sqlite_for_production(conn)` | Extracted from `watch.py:1107-1132`. Applies SQLite PRAGMA cluster. No-op on PG. |
| `connect_db_with_pg_retry(...)` | PG-only OperationalError retry. 5×30s. **On exhaustion: writes `data/watchdog.txt` AND `sys.exit(1)` so NSSM restarts** (M3 fix). |
| `_sqlite_only_connect(db_path)` | Re-exported from `src/schema/sqlite.py:18` |

### 2.3 `?`→`%s` rewrite — safety (REVISED per C1)

**The problem:** psycopg2 uses `%` as both the parameter sigil (`%s`, `%(name)s`) AND the format-specifier prefix. After replacing `?` with `%s`, any literal `%` in the SQL string causes psycopg2's parameter binding to crash with `IndexError: tuple index out of range` or `TypeError: not enough arguments for format string`. This is the exact failure shape as the 2026-05-10 crash, different root cause.

**Common offenders in production code:**
```sql
SELECT * FROM activity_log WHERE message LIKE '%position%'   -- LIKE wildcards
WHERE col LIKE 'PCT%'                                        -- prefix LIKE
SELECT '100%' || x AS label                                  -- literal % in string
```

**Pre-flight audit (T0.0):** Grep all in-scope production files for SQL strings containing literal `%`. Catalogue each site as (a) already-safe (no rewrite involved — pure SQLite path), (b) requires `%%` escape after rewrite, or (c) parameter-substitutable (move `'%X%'` to `LIKE ?` with `'%X%'` passed as a bound parameter). Output: `docs/audits/2026-05-11-modified-a-migration/literal-pct-audit.md`. Smoke-test deliverable in T3.4 includes the activity_log LIKE path because it was explicitly mentioned in the original failure transcript.

**Rewrite implementation (T0.2):** A quote-AND-percent-aware tokenizer (~50 LOC), NOT naive replace:
```python
def _rewrite_question_to_pct(sql: str) -> str:
    """Rewrite `?` placeholders to `%s` for psycopg2. Escape unpaired `%` to `%%`.

    Rules:
      1. Inside single-quoted string literals: leave `?` and `%` untouched.
      2. Outside string literals:
         a. `?` → `%s` (parameter placeholder)
         b. unpaired `%` (not followed by `s`, `d`, `(`, `%`, etc.) → `%%`
      3. Inside double-quoted identifiers (PG): leave alone.
    """
```

**Regression test (T0.2):** Asserts:
```python
# Quote-aware: preserve ? inside string literals
assert _rewrite_question_to_pct("SELECT * FROM t WHERE name LIKE '?%' AND id=?") \
    == "SELECT * FROM t WHERE name LIKE '?%%' AND id=%s"  # ? inside lit stays; outside →%s; literal % outside →%%

# %-escape: LIKE wildcards survive after binding
rewritten = _rewrite_question_to_pct("SELECT * FROM activity_log WHERE message LIKE '%position%' AND id=?")
# Critical assertion: psycopg2 must be able to bind a parameter without IndexError
import psycopg2
conn = pg_test_conn()
with conn.cursor() as cur:
    cur.execute(rewritten, (1,))   # must NOT raise IndexError/TypeError
```

Performance budget: <100μs per call (Render PG RTT is 30-80ms — rewrite still 300× cheaper).

### 2.4 `engine_aware_upsert` API — REPLACE semantics resolved per T0.12 audit (C2)

**The problem:** SQLite's `INSERT OR REPLACE` is DELETE-then-INSERT (fires `ON DELETE` triggers, cascades FK refs, reassigns rowid for AUTOINCREMENT tables). PG's `INSERT … ON CONFLICT DO UPDATE` is in-place UPDATE (preserves FKs, no DELETE trigger, no rowid change). 10 of 17 Phase 1 sites use REPLACE. Silent data divergence post-cutover for FK-dependent tables.

**Mitigation: T0.12 audit + per-table dispatch table in `src/utils/db.py`.**

T0.12 audits each of the 10 `action='replace'` target tables for:
1. Incoming FK references (other tables pointing at this one with `ON DELETE` clauses)
2. Outgoing FK references with `ON DELETE CASCADE` (this table's deletion cascades to others)
3. AUTOINCREMENT / rowid dependencies
4. Triggers on DELETE or INSERT (per schema registry)

**Tables to audit (per T0.12):** `data_freshness`, `build_score_history`, `config_overrides`, `system_metrics`, `council_parameter_state`, `simulation_results`, `walkforward_results`, `walkforward_trades`, `sp100_historical_constituents`, plus any others surfaced.

Output: `docs/audits/2026-05-11-modified-a-migration/replace-semantics-audit.md` with a finding per table: `DELETE_INSERT_REQUIRED` or `IN_PLACE_UPDATE_OK`.

**Dispatch table in `src/utils/db.py`** (populated from T0.12 findings, hard-coded for auditability):
```python
_REPLACE_SEMANTICS = {
    # table_name: 'delete_insert' | 'in_place_update'
    'data_freshness': 'in_place_update',         # leaf table; no FK depends on rowid
    'build_score_history': '<from T0.12 audit>',
    'config_overrides': '<from T0.12 audit>',
    # ... etc
}
```

PG `action='replace'` branch:
- **`in_place_update`:** `INSERT INTO {table} (cols) VALUES (%s,…) ON CONFLICT ({target}) DO UPDATE SET non_target=EXCLUDED.non_target …`
- **`delete_insert`:** Two-statement: `DELETE FROM {table} WHERE {target_col_eq_values} ; INSERT INTO {table} (cols) VALUES (%s,…)` — executed in a single transaction so semantics match SQLite's atomicity.

If a table is NOT in `_REPLACE_SEMANTICS`, the helper raises `ValueError("engine_aware_upsert(action='replace') called on table {name} without semantic classification — add to _REPLACE_SEMANTICS dict")`. This forces auditability: every new `replace` target is a conscious decision.

**Per-task acceptance (Phase 1):** Each `action='replace'` migration task (T1.9, T1.10, T1.11, T1.12, T1.13, T1.14, T1.15a/b/c) gets a parametrize-both-engines test that asserts the chosen semantic actually matches between engines:
- For `in_place_update` tables: after upsert-then-modify, FK references to the (now-updated) row are intact.
- For `delete_insert` tables: after upsert-then-modify, FK cascade behaviour matches SQLite.

### 2.5 Phase 0 registry change (one column-level edit)

`src/schema/registry.py:TABLES['notifications_dedup'].sync_conflict_col` — T0.7 adds `sync_conflict_col="event_type, dedup_key"`.

### 2.6 SQLite-isms in scope — 17 sites across 16 in-scope files

(Unchanged from prior revision — table preserved verbatim.)

| File | Site | Action |
|---|---|---|
| `src/data_collection/short_interest_collector.py:111` | INSERT OR IGNORE | T1.1 → engine_aware_upsert(ignore) |
| `src/data_collection/research_collector.py:121` | INSERT OR IGNORE | T1.2 → engine_aware_upsert(ignore) |
| `src/data_collection/fed_collector.py:128` | INSERT OR IGNORE | T1.3 → engine_aware_upsert(ignore) |
| `src/data_collection/edgar_collector.py:338` | INSERT OR IGNORE | T1.4 → engine_aware_upsert(ignore) |
| `src/data_collection/analyst_collector.py:153` | INSERT OR IGNORE | T1.5 → engine_aware_upsert(ignore) |
| `src/data_collection/insider_collector.py:118` | plain INSERT (constraint dedup) | T1.6 → engine_aware_upsert(ignore) |
| `src/notifications/platform_events.py:96` | INSERT OR IGNORE | T1.7 |
| `src/council/protocol.py:228` | INSERT OR IGNORE | T1.8 |
| `src/data_enrichment/staleness.py:42` | INSERT OR REPLACE | T1.9 |
| `src/evaluation/build_score.py:460` | INSERT OR REPLACE | T1.10 |
| `src/api/routes/system.py:566` | INSERT OR REPLACE | T1.11 |
| `src/monitoring/system_metrics.py:148` | INSERT OR REPLACE | T1.12 |
| `src/council/value_tracker.py:120` | INSERT OR REPLACE | T1.13 |
| `src/simulation/engine.py:504` | INSERT OR REPLACE | T1.14 |
| `src/platform/rigor/walkforward_runner.py:308` | INSERT OR REPLACE | T1.15a |
| `src/platform/rigor/walkforward_runner.py:355` | INSERT OR REPLACE | T1.15b |
| `src/platform/rigor/walkforward_universe.py:81` | INSERT OR REPLACE | T1.15c |

Retiring-file SQLite-isms NOT in scope (footnoted): `src/sync/render_sync.py:891` (deleted in T4.1), `src/sync/reconcile.py` (deleted in T4.2).

### 2.7 SQLite-only-by-design allowlist (final state)

| File | Lines | Reason |
|---|---|---|
| `src/schema/sqlite.py` | all | Engine-specific schema generator |
| `src/schema/registry.py` | all | Declarative schema definition |
| `src/scheduler/watch.py` | 1164-1165 | SQLite Online Backup API |
| `src/training/trainer.py` | 1171 | Training corpus stays local SQLite |

### 2.8 CI infrastructure

`.github/workflows/pg-tests.yml` — created in T0.10. postgres:16-alpine sidecar, Python 3.12, `TEST_DATABASE_URL` set, schema bootstrap via `scripts/bootstrap_pg_test_schema.py`, asserts test count ≥ floor.

---

## 3. Phase plan (5 phases — 21 batches, 57 tasks total)

### Phase 0 — Wrapper Foundation + Pre-flight Audits (~3.5 days)

**Goal:** Centralise every dialect-impedance + complete pre-flight audits (T0.0 literal-%, T0.12 REPLACE semantics). SQLite path unchanged. PG path supports quote-AND-percent-aware rewrite, CompatRow with VALUES iteration, per-semantic UPSERT, introspection helpers, fast-exit retry. CI workflow active.

**Acceptance:**
- `src/utils/db.py` grows from 149→~470 LOC
- T0.0 + T0.12 audit docs land in `docs/audits/2026-05-11-modified-a-migration/`
- `pg-tests.yml` workflow runs on every PR
- Production behaviour unchanged: T3.2 NOT YET MERGED, no env gate set → SQLite path everywhere
- ~+47 net tests (was +33; +12 for revised C1/C3 tests, M3 fast-exit test, T0.12-derived semantic-divergence tests)

**Scope-fence:** Phase 0 makes NO production code change OUTSIDE `src/utils/db.py` and the one registry edit (notifications_dedup sync_conflict_col).

### Phase 1 — UPSERT Migrations (~2 days, parallelisable)

**Goal:** Convert all 17 sites across 16 in-scope files to `engine_aware_upsert(conn, table, row_dict, action)`. Per-table semantic dispatch (from T0.12 audit) is now hard-coded in `_REPLACE_SEMANTICS`.

**Acceptance:**
- Each migrated file has a parametrize-both-engines test asserting INSERT, UPDATE-on-conflict (or DELETE-INSERT depending on semantic), and FK behaviour where relevant
- `INSERT OR REPLACE/IGNORE` strings appear ZERO times in migrated files (enforced by Phase 2D AST-based test T2.14)
- ~+17 net tests (was +14; +3 for FK-semantic asserts on action='replace' tables)

### Phase 2 — Introspection / SQL-function migrations + Discipline tests (~2.5 days)

Sub-phases 2A (schema introspection — 8 files), 2B (SQL function rewrites — 3 files), 2C (watch loop PRAGMA isolation + PG retry adoption — 1 file), 2D (static-analysis discipline — 2 test files).

**Phase 2D revision (M4):** T2.14 now uses AST-based scanning, NOT substring scan. AST detects:
1. String literals (anywhere in the source) containing `INSERT OR REPLACE`, `INSERT OR IGNORE`, `OR REPLACE`, `OR IGNORE` (even when split across f-string fragments or `.format()` calls)
2. SQL-keyword strings (`INSERT`, `SELECT`, `UPDATE`, `DELETE`, `VALUES`) containing literal `?` placeholders
3. String-concatenation chains where any segment contains SQLite-ism fragments
4. f-string fragments where the `{expr}` portion evaluates to `REPLACE` or `IGNORE` at compile time (heuristic: if `expr` is a constant Name with uppercase value)

The AST visitor traverses every `ast.Str`/`ast.Constant`/`ast.JoinedStr`/`ast.FormattedValue`/`ast.BinOp(op=Add)` node, reconstructing the full string where possible. Tests assert ZERO violations in migrated files.

**Acceptance:**
- Test floor grows to ~3805 (~+85 from Phase 2: +12 sub-phases 2A-C, +50 from T2.14 AST test cases, ~+23 from T2.13 expanded allowlist tests)
- `pg-tests.yml` workflow runs green

### Phase 3 — Cutover Retry (~1.5 days)

**Pre-cutover sequence:**
- **T3.0 (NEW, M5 mitigation):** Operator verifies baseline NSSM env vars are preserved before the cutover. Required env: `PYTHONUTF8=1` (UTF-8 codec safety for TRL chat_template_utils), `ARCIS_DB_PATH=C:/arcis/data/ai_research_desk.sqlite3` (DB path), `OLLAMA_BASE_URL` (LLM endpoint), plus any others currently set. Operator runs `nssm get ArcisWatchLoop AppEnvironmentExtra` and pastes output into a PM verification checklist. The T3.3 NSSM update command must use APPEND syntax (not overwrite) for env vars. Acceptance: documented env baseline in operator-guide.md.
- **T3.1:** SQLite + PG snapshots
- **T3.2 (M2 revision):** Land precedence-flip commit. Precedence now gated behind `ARCIS_PG_CUTOVER_ENABLED=1` env var (defaults off, no-op on developer machines).
- **T3.3:** Operator sets BOTH `DATABASE_URL=postgresql://…` AND `ARCIS_PG_CUTOVER_ENABLED=1` on NSSM service env. Verifies via T3.0 that PYTHONUTF8 + ARCIS_DB_PATH are still present (append syntax). Restarts service.
- **T3.4:** 30-min smoke including activity_log LIKE path (C1 regression coverage)
- **T3.5:** Conditional rollback. Operator unsets `ARCIS_PG_CUTOVER_ENABLED` (single flip) → watch loop reverts to SQLite path.

### Phase 4 — Retirement (~2 days)

T4.1-T4.6 deletions as before. **T4.7 revision:** docs/operator-guide.md update now includes the complete NSSM env-var list (PYTHONUTF8, ARCIS_DB_PATH, DATABASE_URL, ARCIS_PG_CUTOVER_ENABLED, etc.) per M5. **T4.4 revision:** Remove `ARCIS_PG_CUTOVER_ENABLED` env-gate code from `src/utils/db.py:connect_db` (cleanup once stable). T4.8 closeout.

---

## 4. Wrapper API — full signatures (REVISED)

See `src/utils/db.py` post-Phase-0 layout. New highlights:

```python
class CompatRow:
    """Row wrapper supporting BOTH `row[int]` AND `row['col']` access.

    Mirrors sqlite3.Row semantics for psycopg2 RealDictCursor results.

    CRITICAL INVARIANT (C3): Iteration yields VALUES, not keys.
        for v in row → values
        tuple(row)   → (v1, v2, ...)
        list(row)    → [v1, v2, ...]
        a, b = row   → values destructured

    For column-name iteration, callers must use row.keys() explicitly.
    """
    def __init__(self, row_dict): self._row = row_dict
    def __getitem__(self, k):
        if isinstance(k, int):
            return list(self._row.values())[k]
        return self._row[k]
    def __iter__(self): return iter(self._row.values())   # VALUES, not keys (C3)
    def __len__(self): return len(self._row)
    def __contains__(self, k): return k in self._row
    def keys(self): return self._row.keys()
    def __repr__(self): return f"CompatRow({self._row})"


def _rewrite_question_to_pct(sql: str) -> str:
    """Quote-AND-percent-aware rewrite (C1 + M1).

    1. Inside single-quoted literals: ? and % untouched
    2. Outside literals:
       a. ? → %s
       b. Unpaired % → %% (so psycopg2 binding doesn't crash on LIKE wildcards)
    """


def engine_aware_upsert(conn, table_name, row_dict, action='replace'):
    """Engine-aware UPSERT.

    action='ignore':
      SQLite: INSERT OR IGNORE INTO ...
      PG:     INSERT ... ON CONFLICT DO NOTHING

    action='replace':
      SQLite: INSERT OR REPLACE INTO ...  (always DELETE-then-INSERT)
      PG:     dispatch on _REPLACE_SEMANTICS[table_name]:
        'in_place_update' → INSERT ... ON CONFLICT DO UPDATE SET ...
        'delete_insert'   → DELETE WHERE conflict_cols=...; INSERT ...
      Raises ValueError if table_name not in _REPLACE_SEMANTICS.
    """


def connect_db_with_pg_retry(db_path=None, *, max_attempts=5, backoff_seconds=30):
    """connect_db() with psycopg2.OperationalError retry.

    SQLite path: passthrough.
    PG path: 5×30s retry on OperationalError.

    Retry exhaustion (M3 fix):
      1. Write 'PG_CONNECT_FAIL: <exc>' to data/watchdog.txt
      2. logger.critical(...)
      3. sys.exit(1)  # NSSM restarts the service; no zombie watch loop
    """
```

---

## 5. Test strategy

### 5.1 Existing fixtures we build on

- `tests/conftest.py:postgres_session` — function-scoped psycopg2.connect with RealDictCursor + rollback teardown
- `tests/conftest.py:init_test_db` — SQLite temp-path fixture
- `tests/test_dashboard_reconciliation.py:272-303` — prototype parametrize-both-engines pattern

### 5.2 New fixtures Phase 0 adds

- `pg_wrapper` — wraps psycopg2 conn in `PostgresConnectionWrapper`
- `parametrized_conn` — yields both SQLite + PG wrapper for dual-engine tests
- `pg_retry_mocked_clock` — monkeypatches `time.sleep` to count retry attempts
- `pg_with_pre_inserted_fk_row` — fixture for FK-cascade behaviour assertions

### 5.3 Per-phase test additions (RECONCILED per M6)

Per-task test budgets ground-truth (Phase 0):

| Task | Tests added | Rationale |
|---|---|---|
| T0.0 (literal-% audit) | 0 | Audit doc — no code |
| T0.1 (CompatRow + _RowFactoryCursor) | 12 | 8 prior + 4 new C3 iteration tests (tuple(row), list(row), for v in row, a,b=row destructuring) |
| T0.2 (rewrite — quote+pct aware) | 10 | 6 prior + 4 new C1 tests (LIKE '%foo%', LIKE 'PCT%', literal % outside lit, mixed ?+% binding) |
| T0.3 (_resolve_conflict_target) | 5 | unchanged |
| T0.4 (engine_aware_upsert) | 12 | 8 prior + 4 new C2 tests (delete_insert vs in_place_update semantic dispatch, ValueError on unknown table) |
| T0.5 (table_list + column_info) | 6 | unchanged |
| T0.6 (index_list + foreign_keys) | 4 | unchanged |
| T0.7 (notifications_dedup sync_conflict_col) | 1 | unchanged |
| T0.8 (configure_sqlite_for_production) | 4 | unchanged |
| T0.9 (pg_wrapper + parametrized_conn fixtures) | 2 | unchanged |
| T0.10 (CI workflow) | 0 | Workflow runs on PR |
| T0.11 (connect_db_with_pg_retry — fast-exit) | 5 | 3 prior + 2 new M3 tests (sys.exit called on exhaustion; watchdog.txt written before exit) |
| T0.12 (REPLACE semantics audit) | 0 | Audit doc — no code |
| **Phase 0 total** | **61** | Reconciled from prior "+33" |

Net by phase (target+accept band per M6):

| Phase | Target | Accept (band) |
|---|---|---|
| 0 | +61 | +50 to +75 |
| 1 | +17 | +14 to +22 |
| 2A | +8 | +6 to +12 |
| 2B | +3 | +2 to +5 |
| 2C | +2 | +2 to +4 |
| 2D | +50 | +40 to +70 (AST tests are bulkier than substring) |
| 3 | +3 | +2 to +6 |
| 4 | -10 | -15 to -5 |
| **Net** | **+134** | **+90 to +140** |

**Reconciliation rule (M6):** Phase 0 closeout task includes a PM verification step: count actual new tests, confirm within accept band. Update CLAUDE.md test-floor lineage with the actual number. If outside the accept band, re-issue with explanation.

### 5.4 Discipline test patterns (Phase 2D)

**T2.13 (`test_connect_db_discipline.py`):** Permanent allowlist (sqlite.py, registry.py, watch.py:1164-1165, trainer.py:1171), retiring allowlist (render_sync.py, reconcile.py).

**T2.14 (`test_no_sqlite_isms_in_pg_safe_files.py`) — REVISED M4:** AST-based scanning. Test functions:
- `test_no_insert_or_replace_or_ignore` — visits all string nodes; reconstructs f-strings/concats; matches against SQLite-ism patterns including dynamic ones
- `test_no_pragma_in_pg_safe_files` — line-range allowlist for watch.py:1164-1165
- `test_no_sqlite_master_references`
- `test_no_sqlite_date_functions` (julianday, date('now'), datetime('now'))
- `test_no_unrewritten_question_placeholders` — string contains SQL-keyword + `?` outside quoted literals

---

## 6. Error handling strategy

### 6.1 Wrapper-level errors

| Error | When | Response |
|---|---|---|
| `psycopg2.ProgrammingError` | Invalid SQL after rewrite | Propagate with rewritten SQL in error |
| `psycopg2.IntegrityError` | UPSERT against unique constraint not in registry | Propagate with table context |
| `psycopg2.OperationalError` | PG down/restarting | `connect_db_with_pg_retry` 5×30s; on exhaustion: watchdog.txt + sys.exit(1) (M3) |
| Format/IndexError from binding | Literal `%` in SQL after naive rewrite | **Prevented by C1 fix** — quote+pct-aware rewrite ensures psycopg2 binding succeeds |
| `KeyError` on CompatRow | row['nonexistent'] | Propagate — matches sqlite3.Row |
| `IndexError` on CompatRow | row[N] where N≥len | Propagate |
| `ValueError` from engine_aware_upsert | Unknown table; missing _REPLACE_SEMANTICS entry; unknown action | Raise at call site so registry drift / semantic-classification gaps surface in CI |

### 6.2 Cutover-time errors (M3 fix)

**Phase 0+2C state (after T0.11 + T2.12):**
- `_configure_database` calls `connect_db_with_pg_retry(DB_PATH, max_attempts=5, backoff_seconds=30)`
- SQLite path: no retry, identical to today
- PG path: 5×30s absorbs Docker-PG-restart race
- **On retry exhaustion (M3 invariant):** Wrapper writes `data/watchdog.txt` → `logger.critical(...)` → `sys.exit(1)`. The existing `except Exception` at watch.py:1133 catches SystemExit propagated through (actually, `sys.exit(1)` raises `SystemExit` which is NOT caught by `except Exception` since SystemExit inherits BaseException not Exception). Process exits cleanly. NSSM auto-restart kicks in. Cycle continues until operator intervenes.
- **Invariant statement:** "PG-unreachable at startup → fast process exit, NSSM restart, eventually operator unsets ARCIS_PG_CUTOVER_ENABLED + DATABASE_URL."

### 6.3 Rollback decision tree (Phase 3)

```
If watch loop exits-and-restarts repeatedly (PG retry exhaustion loop):
   → Telegram alert via watchdog.txt poll
   → Operator: nssm set ArcisWatchLoop AppEnvironmentExtra ARCIS_PG_CUTOVER_ENABLED=  (unset)
   → nssm restart → SQLite path

If watch loop runs but Hot-path CRITICAL error within 30 min:
   → Operator: unset ARCIS_PG_CUTOVER_ENABLED → restart → SQLite path
   → Phase 4 retirement deferred

If 30-min smoke passes but 7-day observability surfaces ≥1 CRITICAL/HIGH dialect-error:
   → Investigate; if surface fix, hotfix + redeploy
   → If structural, unset env gate + revert precedence flip commit
```

---

## 7-10. Cutover plan / Rollback / Worktree discipline / Out-of-scope

See prior revision sections 7-10 (preserved verbatim except for the env-gate variable name in section 7 procedure text — `ARCIS_PG_CUTOVER_ENABLED` instead of bare `DATABASE_URL`-based detection).

---

## 11. Known Considerations (Devil's Advocate MINORs — not blocking)

**N1 — `engine_aware_upsert` row_dict validation.** Helper should pre-validate `row_dict` keys against `TABLES[table].columns` (raise on unknown columns, raise on missing NOT NULL). Currently the helper trusts the caller; mistakes surface as PG IntegrityError or SQLite OperationalError at runtime. Not a correctness blocker but improves DX. Tracked as Sprint 5 backlog: post-cutover hardening.

**N2 — T1.6 try/except splitting.** `insider_collector.py:118` surrounding control flow may benefit from splitting T1.6 into T1.6a (registry-check / sync_conflict_col validation) + T1.6b (INSERT wrap). Current scope keeps both in one task because the function is small (~30 LOC); if the implementing agent finds the diff too tangled, they may split during execution and note in their PR. Not a planner-level mandate.

**N3 — spec.md extraction.** `_design_raw.json` is consumed by the Reviewer + Developer agents but is awkward for human discoverability. Recommended a future T0.A0 to extract `docs/audits/2026-05-11-modified-a-migration/spec.md` from the JSON's `spec` field for human readers. Not required for execution.


---

## Design Decisions Log

| # | Decision | Rationale | Alternatives Considered |
|---|---|---|---|
| 1 | Precedence rule for the cutover gated behind ARCIS_PG_CUTOVER_ENABLED=1 env var (M2) | Without the env gate, T3.2's precedence flip activates on EVERY machine where DATABASE_URL is set in the shell — including developer boxes where DATABASE_URL points at another project's PG. The gate makes T3.2 a no-op on merge: only the production NSSM service (which has both DATABASE_URL=postgresql://… AND ARCIS_PG_CUTOVER_ENABLED=1) routes to PG. Rollback becomes a single env unset (ARCIS_PG_CUTOVER_ENABLED=). Gate removed in T4.4 cleanup once cutover is stable. Documented incident analog: not yet observed, but the failure shape (stale DATABASE_URL in developer shell silently routing to PG) is high-likelihood after T3.2 merge given the watch loop runs on the operator's box where multiple projects coexist. | DATABASE_URL alone flips precedence (rejected: too coupled to ambient env; M2 incident shape); Build-time flag baked into the binary (rejected: requires re-deploy to roll back); Operator manually edits db.py at cutover time (rejected: hard to revert; not idempotent) |
| 2 | Quote-AND-percent-aware rewrite (C1) — escapes unpaired `%` to `%%`, not just naive `?` replace | psycopg2 uses `%` as both parameter sigil and format-specifier prefix. After replacing `?` with `%s`, any literal `%` in SQL (LIKE wildcards, prefix patterns, embedded percent chars) causes psycopg2's binding to crash with IndexError/TypeError — exact same failure shape as 2026-05-10. The codebase contains real literal-% sites (activity_log LIKE '%position%' in Telegram poll path, called out as smoke test). The rewrite MUST handle this. T0.0 audits all such sites; T0.2 ships a quote+pct-aware tokenizer that doubles unpaired `%` to `%%` outside string literals. C1 regression test executes the rewritten SQL against a real PG fixture and asserts no binding error. | Naive replace (REJECTED — original revision; would crash on activity_log LIKE in T3.4 smoke); Force every literal % to be a bound parameter (rejected: 158+ sites; many are static SQL strings); Use psycopg2.sql.SQL composition (rejected: requires every call site to opt in; defeats centralisation) |
| 3 | engine_aware_upsert action='replace' dispatches per-table on _REPLACE_SEMANTICS — explicit DELETE+INSERT emulation for FK-sensitive tables (C2) | SQLite INSERT OR REPLACE is DELETE-then-INSERT (fires ON DELETE triggers, cascades FK refs, reassigns rowid). PG INSERT ... ON CONFLICT DO UPDATE is in-place UPDATE (preserves FKs, no DELETE trigger). Silent data divergence for any FK-dependent table. T0.12 audits all 10 action='replace' target tables for FK refs, cascades, AUTOINCREMENT, triggers. Findings encoded into a hard-coded _REPLACE_SEMANTICS dict in src/utils/db.py. PG path dispatches: 'in_place_update' → ON CONFLICT DO UPDATE; 'delete_insert' → wrap DELETE+INSERT in single transaction. Unknown tables raise ValueError to force auditability. | ON CONFLICT DO UPDATE for all replace tables (REJECTED — C2 silent data divergence); DELETE+INSERT for all replace tables (rejected: needlessly destroys rowid stability where it's safe); Migrate FK-sensitive tables to action='ignore' instead (rejected: changes semantics; replaces upsert with insert-or-noop) |
| 4 | CompatRow iterates VALUES, not keys — explicit __iter__ contract matching sqlite3.Row (C3) | sqlite3.Row.__iter__ yields VALUES (cell contents). psycopg2.extras.RealDictRow.__iter__ yields KEYS (column names). 60+ row[N] integer-indexed sites in the codebase. If any site does `for v in row:` or `tuple(row)` or `a, b = row`, with naive RealDictRow we'd silently yield column names instead of values. CompatRow MUST override __iter__ to yield self._row.values(). Tests assert tuple(row) == (v1, v2), list(row) == [v1, v2], destructuring works, [v for v in row] yields values. dict(row) is explicitly an undefined case — document the chosen behaviour in the class docstring. | Default RealDictRow iteration (REJECTED — C3 silent corruption on any for-loop); Wrap and yield keys to match dict default (rejected: contradicts sqlite3.Row semantics; the whole point is dropping into existing code); Document the trap and grep all `for v in row:` sites (rejected: too much detection surface) |
| 5 | T0.11 retry exhaustion calls sys.exit(1) after watchdog.txt write — NSSM restarts the service (M3) | Original revision: T0.11 wrote watchdog.txt and re-raised psycopg2.OperationalError. Watch.py:1133 has `except Exception` which CATCHES the re-raised exception, logs warning, and continues — leaving a zombie watch loop running without a working DB. Telegram alert never fires, NSSM never restarts (process didn't exit), every subsequent task fails silently. Fix: on retry exhaustion, write watchdog.txt then sys.exit(1). SystemExit inherits BaseException not Exception, so the wrapping `except Exception` at line 1133 does NOT catch it. Process exits cleanly, NSSM auto-restarts. T2.12 adds a comment at line 1133 explicitly documenting this invariant. Operator-facing rollback (NSSM unset ARCIS_PG_CUTOVER_ENABLED) still works because the next retry cycle will route to SQLite path. | Re-raise OperationalError and let watch.py handle it (REJECTED — M3 zombie-watchdog mode); Refactor watch.py:1133 to remove `except Exception` for OperationalError specifically (rejected: leaks DB concern into scheduler; centralisation argues for fast-exit in the wrapper); Watchdog.txt + os._exit(1) instead of sys.exit(1) (rejected: bypasses Python cleanup; sys.exit is the standard exit path) |
| 6 | T2.14 uses AST-based scanning, not substring scan (M4) | The 2026-05-10 crash was triggered by system_validator.py:1039's `f'INSERT INTO ... VALUES ({placeholders})'` where placeholders was built dynamically. Substring scan for 'INSERT OR REPLACE' or '?' would miss `f'INSERT OR {action.upper()} INTO ...'` or `'INSERT' + ' OR ' + 'IGNORE' + ' INTO ...'`. AST-based scan visits ast.Constant/ast.JoinedStr/ast.FormattedValue/ast.BinOp(op=Add) nodes, reconstructs strings where possible, and catches dynamic patterns. Detection rules: (1) any string containing 'INSERT OR REPLACE/IGNORE' even split; (2) SQL-keyword strings with unrewritten `?` placeholders; (3) string concat chains with SQLite-ism fragments; (4) f-string fragments where the expr evaluates to constant REPLACE/IGNORE. Bumps T2.14 to standard complexity. Includes positive-test fixtures (anti-pattern files) to verify the detector works. | Substring scan (REJECTED — M4: misses dynamic patterns; this was the exact 2026-05-10 bug class); Ban all `?` placeholders in migrated files entirely (rejected: too aggressive; legitimate parameterized queries still use ?); Lint with ruff/flake8 custom rule (rejected: extra tooling; AST scan in pytest is more discoverable and self-contained) |
| 7 | Pre-cutover baseline NSSM env audit (T3.0) + APPEND syntax at T3.3 (M5) | Tonight (2026-05-10) we discovered TRL's chat_template_utils.py on Windows requires PYTHONUTF8=1 for UTF-8 codec safety. If operator follows the original spec literally and only adds DATABASE_URL to NSSM env at T3.3 (potentially overwriting via `nssm set`), PYTHONUTF8 disappears → training pipeline silently breaks. T3.0 documents the baseline env-var list (PYTHONUTF8, ARCIS_DB_PATH, OLLAMA_BASE_URL, and any others surfaced via `nssm get`) in operator-guide.md. T3.3 explicitly uses APPEND syntax — concatenates new vars onto the existing string rather than overwriting. PM blocks T3.3 if T3.0 audit doc is missing or empty. T4.7 finalises the canonical env-var list in operator-guide.md. | Operator remembers to use append (REJECTED — M5: not enforceable; relies on human discipline); Move all env config to .env file loaded by watch.py startup (rejected: NSSM env is the canonical operator interface; .env wouldn't apply to non-Python subprocesses); Add an integration test that asserts PYTHONUTF8 is set (rejected: tests don't run under NSSM; can't simulate the service env) |
| 8 | Use a CompatRow wrapper class to support BOTH row[int] AND row['col'] access on PG | The codebase report enumerated 60+ row[N] integer-indexed sites across 50+ files including hot paths. RealDictCursor returns dicts that raise KeyError on int access — silent data corruption without CompatRow. (Iteration semantics — C3 — addressed in design_decisions[3].) | Audit + fix all 60 row[N] sites manually (rejected: enormous touch surface); Use psycopg2 default tuple cursor (rejected: row['col'] then breaks); Use NamedTupleCursor (rejected: row[0] still doesn't work syntactically the same way) |
| 9 | engine_aware_upsert: action='ignore' (DO NOTHING) mirrors the migrator; action='replace' is per-table dispatched (NEW code) | scripts/sqlite_to_pg_migrate.py:_build_insert_sql_template emits ONLY DO NOTHING — that covers the action='ignore' branch (7 of 17 Phase 1 sites). The action='replace' branch is new code, now further refined by C2's per-table semantic dispatch. | Pretend the whole helper is extracted (rejected: false reuse); Author both branches from scratch (rejected: ignore-branch IS verbatim the migrator's output); Use SQLAlchemy Core (rejected: no ORM in this codebase) |
| 10 | Add sync_conflict_col='event_type, dedup_key' to notifications_dedup TableDef (T0.7) | notifications_dedup has a unique idx on (event_type, dedup_key) but no sync_conflict_col → engine_aware_upsert would fall back to PK=id (UUID) → would silently allow duplicates on PG. | Auto-introspect unique indexes (rejected: too implicit); Pass conflict_target explicitly at call site (rejected: defeats centralisation); Add sync_conflict_col to ALL 64 PK-only tables (rejected: no behavioural change) |
| 11 | Retiring allowlist for sync/render_sync.py + sync/reconcile.py (not permanent) | Both files deleted in Phase 4. Permanent allowlist would hide a future audit issue. `# RETIRING: delete in SP5 §J6 Phase 4` markers + separate test surface. | Permanent allowlist (rejected: hides retirement intent); Skip entirely (rejected: loses regression-lock coverage during transition); Comment-out discipline test (rejected: harder to find when removing) |
| 12 | Extract configure_sqlite_for_production helper to src/utils/db.py | Named helper makes intent explicit, lets future SQLite-only callers reuse, isolates engine-check to one place. | Inline isinstance check at watch.py (rejected: re-uses guards if future modules need same setup); Put in src/scheduler/ (rejected: belongs with the wrapper); Move to PostgresConnectionWrapper.__init__ no-op (rejected: too magical) |
| 13 | Phase 3 (cutover) is operator-managed at NSSM-env level — not auto-dispatched by PM agent | NSSM env edits + service restart on production are operator-trust operations per memory `reference_watch_loop_management`. Auto-dispatching agents violates autopilot discipline. | Auto-dispatch a PM-controlled NSSM update (rejected: bypass); Watch loop polls config file (rejected: adds complexity); Manual code flip (rejected: that's what the env var IS for) |
| 14 | 5-phase plan with phases landing as separate PRs | Each phase has a distinct concern + acceptance gate. Granular rollback + reviewability + clear cutover gate. | Bundle Phase 0+1 (rejected: Should constraint says separate PRs); Bundle Phase 1+2 (rejected: 28 files in one PR is unreviewable); Single mega-PR (rejected: was the implicit 2026-05-10 attempt) |
| 15 | Test count target +134 with accept band +90 to +140 (M6) | Per-task budgets sum to +134 (Phase 0: +61, Phase 1: +17, Phase 2: +63, Phase 3: +3, Phase 4: -10). Accept band allows ±slack without re-issue. T2.15 closeout includes PM verification of actual delta vs band. CLAUDE.md test-floor lineage updated with the actual number. | Exact target +100 (rejected: brittle — small variations cause unnecessary re-issue); No target at all (rejected: violates Success criteria of ≥+100); Strict band ±5 (rejected: too tight given AST-test count is hard to predict precisely) |
| 16 | CI workflow uses postgres:16-alpine sidecar with ephemeral creds — no GitHub secrets | No existing GitHub secret infrastructure. postgres:16-alpine matches Render PG + Docker compose. Sidecar uses postgres:postgres ephemeral creds. | External test PG via secret (rejected: introduces secret management); Run SQLite-only in CI (rejected: defeats dual-engine regression-locks); testcontainers-python (rejected: extra dep) |
| 17 | Worktree isolation MANDATORY for parallel Phase 1, Phase 2, Phase 4 dispatches | Per CLAUDE.md 'Parallel Agent Dispatch — Worktree Discipline' and memory feedback_strict_rigor_no_handwave. Phase 1 (15 parallel agents), Phase 2 (8-11 per batch), Phase 4 cleanup all need worktrees. | Worktrees for everything (rejected: friction on serial tasks); No worktrees anywhere (rejected: violates CLAUDE.md); Worktrees only for cross-package boundaries (rejected: too clever) |
| 18 | PM-side verification step before EVERY parallel batch: git fetch origin && gh pr list | Per memory feedback_autopilot_origin_check. Sprint 0 Wave 1b PR #701 duplicate-work incident. Phase 1 has up to 11 parallel agents — without origin check, agents could race the operator. | Skip the check (rejected: documented incident); After-batches-complete check (rejected: too late); Agents themselves do git fetch (rejected: only PM has the full repo view) |
| 19 | Add connect_db_with_pg_retry (T0.11) — 5×30s retry, fast-exit on exhaustion | Per feasibility-review finding 4 + M3 fix: the prior spec described a retry loop that doesn't exist. The actual _configure_database at watch.py:1107-1132 has no OperationalError handler. T0.11 adds the retry loop; T2.12 swaps the call site; M3 makes exhaustion call sys.exit(1) so NSSM restarts (no zombie watch loop). | Rewrite spec section 6.2 to honestly describe current crash-and-restart (rejected: per feedback_fix_before_trade, fix-now); Inline retry in watch.py (rejected: duplicates if another module needs it); Automatic retry on PostgresConnectionWrapper.__init__ (rejected: too magical) |
| 20 | Spec section 2.6 footnotes retiring-file SQLite-isms as out-of-scope | Per feasibility-review finding 7: render_sync.py:891 NOT in Phase 1 (deleted in Phase 4). Footnote makes the deliberate scoping decision auditable. | Migrate render_sync.py:891 in Phase 1 (rejected: file deleted in Phase 4; wasted churn); Don't footnote (rejected: reviewer flagged; explicit > implicit); Move to permanent allowlist (rejected: conflates SQLite-only-by-design with soon-to-be-deleted) |
