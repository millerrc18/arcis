# One-DB Cutover Correction — SP5 §J5/§J6 Phase 3-revised

**Date:** 2026-05-11
**Status:** EXECUTION-READY — supersedes Phase 3 T3.2 (PR #1054), which has been rolled back
**Read time:** ~15 min
**Predecessor spec:** `docs/audits/2026-05-11-modified-a-migration/spec.md` §3 Phase 3
**Failed precedent:** PR #1054 (merged 17:28:31Z, cut over at 17:58:45Z, rolled back at 18:13:57Z — 15 min in)

---

## Revision History

| Date | Revision | Author | Summary |
|---|---|---|---|
| 2026-05-11 | r0 | design-team | Initial — invert precedence in `connect_db()` so the gate covers ALL call sites, not just sentinel-default; flip 9 of 10 local-only tables to sync_to_postgres=True; delete sync_state/render_sync now (formerly Phase 4); re-cutover via existing path-1 migrator. |

---

## 1. Overview

Phase 3 T3.2 (PR #1054) added an `ARCIS_PG_CUTOVER_ENABLED=1` gate to `connect_db()`, intending that production-on-NSSM would route every database call to Postgres. The implementation gated only the **sentinel-default** branch (`db_path is _SENTINEL`). With 265 of 336 call sites passing an explicit `db_path`, the gate covered ~5 sites; the other ~331 stayed on SQLite even when the gate was on. The 15-minute cutover window confirmed this — `shadow_trades`, `activity_log`, `scan_metrics`, `attribution_trades`, and others kept landing in SQLite.

**This spec corrects the precedence rule** and resolves three secondary consequences:

1. **Precedence inversion.** When the gate is on AND `DATABASE_URL` is Postgres, `connect_db(...)` returns a `PostgresConnectionWrapper` regardless of `db_path`. Tests (gate off) keep the explicit-path-wins-SQLite behavior.
2. **9 currently-local-only tables flip to PG-resident.** `data_freshness`, `system_metrics`, `bracket_health`, `model_evaluations`, `preference_pairs`, `command_results`, `config_overrides`, `operator_view_state`, `daily_ib_health` all get `sync_to_postgres=True` so they exist in PG post-migrator-rerun. (`sync_state` is deleted instead — see SP-ONEDB-002.)
3. **Cross-engine writer audit** for those 9 tables — replace raw `INSERT`/`INSERT OR REPLACE` with `engine_aware_upsert` where missing, and surface any `?`-placeholder / `sqlite_master` / `julianday` offenders to the AST scanner.

The cutover is then re-executed via the existing path-1 prereq (`scripts/render_migrate.py` + `scripts/sqlite_to_pg_migrate.py`) followed by NSSM env-flip + T3.4 smoke. The 30-second-rollback safety net (single env unset) is preserved.

**Out of scope:** walk-forward implementation (per `feedback_sprint_5_is_final`); v2 training; new features. Anything not on the cutover-critical path stays in Sprint 5 backlog.

---

## 2. Architecture

### 2.1 The corrected precedence rule (truth table)

Inputs: `gate_on` (env `ARCIS_PG_CUTOVER_ENABLED == "1"`), `pg_url` (env `DATABASE_URL` starts with `"postgres"`), `db_path_explicit` (caller passed any non-sentinel value, including `None`).

| gate_on | pg_url | db_path_explicit | Returns | Notes |
|---|---|---|---|---|
| F | F | F | SQLite at DEFAULT_DB | dev box, no env config |
| F | F | T | SQLite at db_path | test fixture with `:memory:` or temp file |
| F | T | F | SQLite at DEFAULT_DB | dev box has unrelated `DATABASE_URL` exported; gate is the kill-switch |
| F | T | T | SQLite at db_path | same — gate is off, test fixture wins |
| T | F | F | SQLite at DEFAULT_DB | gate set but no PG URL — fall through to SQLite |
| T | F | T | SQLite at db_path | same — neither knob is enough |
| T | T | F | **PostgresConnectionWrapper** | production NSSM at steady-state |
| T | T | T | **PostgresConnectionWrapper** (db_path IGNORED, one-time WARN log) | **THE FIX** — was returning SQLite under PR #1054 |

The previous (PR #1054) rule returned PG only in row 7 (`T,T,F`). The corrected rule returns PG in rows 7 AND 8. Only one of 8 rows changes; all test paths keep their current behavior because tests never set the gate.

### 2.2 The corrected `connect_db()` body

```python
def connect_db(db_path=_SENTINEL):
    """Return a database connection.

    Precedence (Sprint 5 §J5/§J6 Phase 3-revised one-DB cutover):
    1. If gate_on AND pg_url → PostgresConnectionWrapper (db_path ignored;
       one-time WARN log if a non-sentinel db_path was passed in this process)
    2. Else if db_path is _SENTINEL → SQLite at DEFAULT_DB
    3. Else → SQLite at db_path (test-fixture compat path)

    Rule 1 covers every call site — the gate is the master switch and the
    explicit-path argument is overridden when production says "one DB".
    Rule 3 is the test-fixture escape hatch — production never sets the
    gate on a sentinel-defaulted process so test paths are unchanged.
    """
    database_url = os.environ.get("DATABASE_URL", "")
    gate_on = os.environ.get("ARCIS_PG_CUTOVER_ENABLED") == "1"
    pg_url = database_url.startswith("postgres")

    if gate_on and pg_url:
        if db_path is not _SENTINEL:
            _warn_db_path_ignored_once(db_path)
        raw = psycopg2.connect(database_url, cursor_factory=psycopg2.extras.RealDictCursor)
        return PostgresConnectionWrapper(raw)

    effective_path = DEFAULT_DB if db_path is _SENTINEL else db_path
    conn = sqlite3.connect(effective_path, timeout=BUSY_TIMEOUT_MS / 1000.0)
    conn.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
    conn.row_factory = sqlite3.Row
    return conn
```

The one-time WARN log (`_warn_db_path_ignored_once`) uses a module-level set keyed by `id(db_path)` to fire at most once per unique path argument — so the watch loop's 200+ sites passing `DB_PATH` only log once per process restart. Format:

```
[DB] ARCIS_PG_CUTOVER_ENABLED=1 with DATABASE_URL set — ignoring db_path={!r}
       and routing to Postgres. Set gate=0 to revert to SQLite path.
```

This is *not* an error — it documents the routing decision. Disabling the warning entirely is rejected because operators inspecting logs need a paper trail when something downstream behaves unexpectedly.

`connect_db_with_pg_retry()` updates analogously: rule 1 now wraps in the retry loop regardless of whether `db_path` was sentinel.

### 2.3 The 10 currently-local-only tables — disposition matrix

| Table | Line | Writer file:line | Cross-engine status | Disposition |
|---|---|---|---|---|
| `daily_ib_health` | 382 | (no writer) | n/a — dormant | flip to `sync_to_postgres=True`; document as dormant, no writer audit needed |
| `model_evaluations` | 521 | `src/training/ab_evaluation.py:94` | raw INSERT with `?` placeholders | flip to True; convert to `engine_aware_upsert(action='ignore')` (evaluation_id is UUID, no dedup) |
| `preference_pairs` | 612 | `src/training/dpo_pipeline.py:106` | raw INSERT with `?` placeholders | flip to True; convert to `engine_aware_upsert(action='ignore')` (pair_id is UUID) |
| `sync_state` | 1528 | `src/sync/render_sync.py:312/359/378/393/428` + `src/cli/commands.py:1450` | render_sync is being retired | **DELETE** — see SP-ONEDB-002 |
| `command_results` | 1544 | `src/commands/executor.py:69` | raw INSERT with `?` placeholders | already `sync_to_postgres=True` in registry (false alarm in audit table); writer needs `engine_aware_upsert(action='ignore')` |
| `config_overrides` | 1564 | `src/config/overrides.py:131` | manual `ON CONFLICT(setting_key) DO UPDATE` — PG-native syntax but `?` placeholders | flip to True; convert to `engine_aware_upsert(action='replace')`. Already in `_REPLACE_SEMANTICS` as `in_place_update` |
| `bracket_health` | 1718 | `src/shadow_trading/bracket_monitor.py:188` | raw INSERT with `?` placeholders | flip to True; convert to `engine_aware_upsert(action='ignore')` (check_id is UUID) |
| `data_freshness` | 1816 | `src/data_enrichment/staleness.py:41` | already `engine_aware_upsert(action='replace')` ✓ | flip to True; reader paths at lines 67/101/130 use `?` which the wrapper rewrites — no additional change |
| `system_metrics` | 1976 | `src/monitoring/system_metrics.py:155` | already `engine_aware_upsert(action='replace')` ✓ | flip to True (already in `_REPLACE_SEMANTICS`); no writer change |
| `operator_view_state` | 2219 | `src/api/cloud_routes/system_index.py:96-104` (two ON CONFLICT writes) | uses `if database_url:` cloud-routes pattern + `?` placeholders | flip to True; ON CONFLICT syntax is already PG-compatible AND SQLite-compatible (both engines support `ON CONFLICT(...) DO UPDATE`). With the precedence inversion, the `if database_url:` branch becomes redundant — see SP-ONEDB-006. Leave it for now (defensive); cleanup tracked as backlog. |

**Net behavioral changes:**
- 1 schema-registry diff (9 flag flips + 1 table removal)
- 5 writer-fix sites: ab_evaluation, dpo_pipeline, executor, overrides, bracket_monitor
- 0 reader changes needed (the `?`→`%s` rewrite in `PostgresConnectionWrapper` handles SELECT/INSERT both)

### 2.4 SQLite-mirror disposition post-cutover

The SQLite file at `C:\arcis\data\ai_research_desk.sqlite3` continues to exist post-cutover for three reasons (SP-ONEDB-001):

1. **30-second rollback safety net.** Operator unsets the gate → next `connect_db()` returns SQLite from the same file. The file must remain on disk and broadly current. Path-1 prereq (`sqlite_to_pg_migrate.py`) writes both engines from the same migrator pass, so post-cutover SQLite is a same-day snapshot — stale but recoverable.
2. **Test fixtures.** All 336 call sites with explicit `db_path` create temp SQLite files in tests. Test env never sets the gate.
3. **Local development.** Devs running `python -m src.main scan --dry-run` on their box without `DATABASE_URL` set continue to hit SQLite.

The SQLite file is **stale-snapshot-only** post-cutover. Watch-loop writes flow to PG once the gate is set. No code path syncs SQLite from PG (the previous render_sync path was PG→SQLite for cloud-pushed commands; with the unified DB it's gone). If the operator unsets the gate for rollback:
- All reads/writes route to SQLite from the same connection.
- SQLite contains data current as of the path-1 migrator pass (date of cutover).
- PG data written between cutover and rollback is NOT mirrored back. Operator must accept this drift OR run the migrator again in reverse (out of scope for SP5).

The `_sqlite_only_connect` helper in `src/schema/sqlite.py` is preserved (SP-ONEDB-003) — schema bootstrapping always needs to seed the SQLite file fresh on dev boxes, and it bypasses `connect_db()` by design.

### 2.5 Cloud-routes `if database_url:` manual branches — preserved, not removed

The 7 sites in `src/api/cloud_routes/{broker_exceptions,kpis_compute,notifications,platform,preflight,walkforward}.py` that check `if database_url:` were added before T3.2 as a manual-routing pattern. With the precedence inversion, they become functionally redundant — `connect_db()` already routes to PG when the gate is on. SP-ONEDB-006 keeps them in place for this PR (defensive double-check); cleanup is backlog (not cutover-blocking).

---

## 3. Data Model

### 3.1 Registry edits

`src/schema/registry.py` — exactly one logical edit per table:

```python
# Before:
_register(TableDef(
    name="daily_ib_health",
    ...
    sync_to_postgres=False,  # ← THIS LINE
))

# After:
_register(TableDef(
    name="daily_ib_health",
    ...
    sync_to_postgres=True,  # ← flipped
))
```

Apply to: `daily_ib_health` (L396), `model_evaluations` (L539), `preference_pairs` (L628), `config_overrides` (L1574), `bracket_health` (L1731), `data_freshness` (L1830), `system_metrics` (L1999), `operator_view_state` (L2242).

`command_results` (L1544-1561) is **already `sync_to_postgres=True`** — the original audit table miscounted. No registry edit needed; writer audit still applies.

`sync_state` (L1527-1541) — **REMOVE the entire `_register(TableDef(...))` block.** Per SP-ONEDB-002, the table goes away because every reader/writer dies with render_sync.py.

### 3.2 sync_pk + sync_mode + sync_time_column required on flipped tables

`sync_to_postgres=True` alone is insufficient for the migrator. Each flipped table needs:
- `sync_pk`: column name(s) used for ON CONFLICT during incremental sync
- `sync_mode`: `"incremental"` (preferred) or `"full"`
- `sync_time_column`: for incremental — the column the migrator filters by

Per-table choice (use existing PK unless a time column makes more sense):

| Table | sync_pk | sync_mode | sync_time_column |
|---|---|---|---|
| daily_ib_health | "date" | full | (n/a — full sync) |
| model_evaluations | "evaluation_id" | incremental | "created_at" |
| preference_pairs | "pair_id" | incremental | "created_at" |
| config_overrides | "setting_key" | full | (n/a — small table, ~50 rows) |
| bracket_health | "check_id" | incremental | "checked_at" |
| data_freshness | "source, ticker" | full | (n/a — small table, one row per source×ticker pair) |
| system_metrics | "snapshot_id" | incremental | "timestamp" |
| operator_view_state | "user_id, entry_name" | full | (n/a — single-row-per-key table) |

These fields are read by `scripts/render_migrate.py` and `scripts/sqlite_to_pg_migrate.py`; without them the bootstrap pass either skips the table or fails. See SP-ONEDB-004 for the bootstrap path.

### 3.3 `sync_state` removal — cascade

After the registry entry is removed:
- `src/sync/render_sync.py` deletion (SP-ONEDB-006) — file owns the entire table
- `src/cli/commands.py:cmd_reset_live_prices_watermark` (L1443-1456) — removed; references `live_prices.last_synced_at` which no longer means anything
- `tests/test_render_sync*.py` (multiple files) — removed
- `tests/test_repo_structure.py` known_violations referencing render_sync — entry removed

The dispatcher in `src/cli/main.py` that wires `cmd_reset_live_prices_watermark` also drops the subcommand registration. CHANGELOG note: "Removed `arcis reset-live-prices-watermark` CLI subcommand (deprecated with render_sync.py)."

---

## 4. API and Module Surface

### 4.1 `src/utils/db.py` — function diffs

`connect_db(db_path=_SENTINEL)`:
- Body restructured per §2.2
- Adds module-level `_DB_PATH_WARNED: set[int] = set()` and `_warn_db_path_ignored_once(db_path)` helper
- Docstring rewritten to reflect Phase 3-revised precedence

`connect_db_with_pg_retry(db_path=_SENTINEL, *, max_attempts=5, backoff_seconds=30)`:
- Same fix: drop the `if db_path is not _SENTINEL: return connect_db(db_path)` short-circuit. When the gate is on, retry loop runs regardless of how db_path was passed.
- After fix:
  ```python
  database_url = os.environ.get("DATABASE_URL", "")
  gate_on = os.environ.get("ARCIS_PG_CUTOVER_ENABLED") == "1"
  if not (gate_on and database_url.startswith("postgres")):
      return connect_db(db_path)  # SQLite passthrough, no retry
  # PG retry loop unchanged from current implementation
  ```

`_REPLACE_SEMANTICS` (line 627) — no edit. `system_metrics`, `data_freshness`, `config_overrides` are all already classified `in_place_update`.

### 4.2 Writer-conversion details

**`src/training/ab_evaluation.py:88-104`** — replace the raw INSERT block with:
```python
init_training_tables(db_path)
with connect_db(db_path) as conn:
    engine_aware_upsert(conn, "model_evaluations", {
        "evaluation_id": evaluation_id,
        "created_at": created_at,
        "recommendation_id": recommendation_id,
        "ticker": ticker,
        "input_text": input_text,
        "current_model": current_model,
        "current_output": current_output,
        "current_score": current_score,
        "new_model": new_model,
        "new_output": new_output,
        "new_score": new_score,
        "winner": winner,
        "score_delta": score_delta,
    }, action="ignore")
    conn.commit()
```

**`src/training/dpo_pipeline.py:103-117`** — analogous swap to `engine_aware_upsert(conn, "preference_pairs", {...}, action="ignore")`.

**`src/commands/executor.py:67-80`** — split into two `engine_aware_upsert` calls (one for `command_results` insert, one for the `pending_commands` UPDATE). The UPDATE stays as-is because `engine_aware_upsert` is INSERT-only; the `?` placeholders are handled by `PostgresConnectionWrapper.execute`'s rewrite:
```python
with connect_db(db_path) as conn:
    engine_aware_upsert(conn, "command_results", {
        "result_id": result_id, "command_id": command_id,
        "status": status, "result_json": result_json,
        "error_message": error, "execution_ms": execution_ms,
        "created_at": now,
    }, action="ignore")
    conn.execute(
        "UPDATE pending_commands SET status = ? WHERE command_id = ?",
        ("completed" if status == "success" else "failed", command_id),
    )
    conn.commit()
```

**`src/config/overrides.py:122-141`** — swap manual ON CONFLICT for `engine_aware_upsert(action='replace')`. The previous_value-from-SELECT pattern stays:
```python
with connect_db(db_path) as conn:
    row = conn.execute(
        "SELECT setting_value FROM config_overrides WHERE setting_key = ?",
        (key,),
    ).fetchone()
    previous = row[0] if row else None
    engine_aware_upsert(conn, "config_overrides", {
        "setting_key": key,
        "setting_value": json_value,
        "previous_value": previous,
        "updated_at": now,
        "updated_by": "dashboard",
    }, action="replace")
    conn.commit()
```
`config_overrides` is already in `_REPLACE_SEMANTICS` as `in_place_update`.

**`src/shadow_trading/bracket_monitor.py:186-204`** — swap to `engine_aware_upsert(conn, "bracket_health", {...}, action="ignore")`. The `1 if bracket_intact else 0` boolean cast stays in the dict construction.

**`src/api/cloud_routes/system_index.py:93-118`** — TWO writes: `_write_view_state` and `_write_reviewed_override`. Both currently use manual `ON CONFLICT(user_id, entry_name) DO UPDATE`. Convert to `engine_aware_upsert(conn, "operator_view_state", {...}, action="replace")`. Add `operator_view_state` to `_REPLACE_SEMANTICS` as `"in_place_update"` (no incoming FKs; row is a single-key state record).

### 4.3 No new public API

The wrapper, helpers, and cloud_routes manual branches all stay. The only behavioral change is `connect_db()` precedence.

---

## 5. Error Handling

| Scenario | Behavior |
|---|---|
| Gate on, PG unreachable on `connect_db()` direct call | `psycopg2.OperationalError` propagates to caller — same as today. Most callers use `connect_db_with_pg_retry` which absorbs transient failures (5×30s). |
| Gate on, PG unreachable on `connect_db_with_pg_retry()` after 5×30s | Writes `data/watchdog.txt`, logs critical, `sys.exit(1)`. NSSM restarts. Same as Phase 0 T0.11. |
| Gate on, caller passes db_path (test code accidentally runs in prod env) | One-time WARN log per process per unique `db_path` value; returns PG connection. Tests do not set the gate, so this only fires in misconfigured env. |
| Gate off, no DATABASE_URL, caller passes db_path | SQLite at db_path — test fixture path, unchanged. |
| Gate off, DATABASE_URL set, caller passes db_path | SQLite at db_path — dev box with unrelated DATABASE_URL exported. |
| `engine_aware_upsert` called on a table with raw cross-engine writer mismatch | Same ValueError on unknown-table or missing `_REPLACE_SEMANTICS` classification (Phase 0 T0.4). Caller fixes the registry. |
| New cross-engine writer fails AST scan | `tests/test_no_sqlite_isms_in_pg_safe_files.py` rejects the PR. Convert to `engine_aware_upsert` or add to allowlist. |

---

## 6. Testing Strategy

### 6.1 Test infrastructure — no new fixtures needed

The Phase 0 fixtures (`postgres_session`, `pg_wrapper`, `parametrized_conn` from `tests/conftest.py`) already cover both engines. No new fixture infrastructure.

### 6.2 Test additions per task

| Task | Tests added | What they assert |
|---|---|---|
| T1 (connect_db precedence) | 8 | One per truth-table row from §2.1. Each test sets/unsets env vars (monkeypatch), calls `connect_db(...)`, asserts the type (PostgresConnectionWrapper vs sqlite3.Connection) and target. |
| T1 (connect_db_with_pg_retry parity) | 2 | Gate on + explicit db_path → retry loop entered (not short-circuited). Gate off + explicit db_path → identity passthrough. |
| T1 (_warn_db_path_ignored_once) | 2 | First call WARN logs; second call same db_path silent; different db_path WARN again. |
| T2 (registry flag flips) | 1 | `test_sync_to_postgres_flipped_for_one_db_cutover` — asserts the 8 (note: not 9; sync_state was removed) flipped tables all have `sync_to_postgres=True` and the required sync_mode/sync_pk/sync_time_column fields are populated. |
| T2 (sync_state removal) | 1 | `test_sync_state_not_in_registry` — pinned-removal regression lock. Catches accidental re-add. |
| T3 (ab_evaluation writer) | 1 | parametrized_conn fixture: insert 2 rows, assert both present on both engines. |
| T4 (dpo_pipeline writer) | 1 | same pattern. |
| T5 (executor + overrides writers) | 2 | One per writer file, parametrized_conn. config_overrides additionally asserts UPDATE-on-conflict (it's `action='replace'`). |
| T6 (bracket_monitor writer) | 1 | parametrized_conn insert + count. |
| T7 (cloud_routes operator_view_state) | 2 | Existing test file probably covers `_write_view_state`/`_write_reviewed_override`; extend to parametrized_conn. |
| **Total new tests** | **20** | (target band 16-24 — well within accept band for a focused PR) |

### 6.3 AST scanner re-run

`tests/test_no_sqlite_isms_in_pg_safe_files.py` runs on every PR. Per SP-ONEDB-008, after flipping the 9 tables, the 5 modified writer files (`ab_evaluation.py`, `dpo_pipeline.py`, `executor.py`, `overrides.py`, `bracket_monitor.py`) get re-scanned. None should introduce new KNOWN_OFFENDERS because `engine_aware_upsert` is the canonical path. The scanner already passes for `staleness.py` and `system_metrics.py`. PM verifies the scanner shows 0 violations after each writer task lands.

### 6.4 Test floor delta

Current floor: 3682. After this PR:
- +20 from this spec
- -N from sync_state/render_sync deletion (estimate: -8 to -15 tests in `tests/test_render_sync*.py` plus removal of `cmd_reset_live_prices_watermark` test)
- Net: roughly +5 to +12; update CLAUDE.md test-floor lineage after closeout.

---

## 7. Operational Notes

### 7.1 Re-cutover execution path

The operator runbook for the re-cutover sequence:

1. **Land this PR.** All registry flips, writer conversions, precedence fix in one PR (or 2-3 worktree-isolated PRs if dispatched in parallel).
2. **Verify gate is OFF on operator's machine.** `nssm get ArcisWatchLoop AppEnvironmentExtra | grep ARCIS_PG_CUTOVER_ENABLED` — must not be set (or `=0`).
3. **Run path-1 prereq migrator with new registry:**
   ```powershell
   $env:DATABASE_URL = "<render-postgres-url>"
   python scripts/render_migrate.py    # idempotent — adds 9 newly-sync-eligible tables to PG
   python scripts/sqlite_to_pg_migrate.py    # incremental migration of those tables from SQLite
   ```
   Each table reports row counts; 9 new tables should appear with non-zero counts (except `daily_ib_health` which is dormant — 0 rows is expected).
4. **Re-snapshot SQLite.** `cp C:\arcis\data\ai_research_desk.sqlite3 C:\arcis\data\backups\one-db-cutover-{timestamp}.sqlite3`
5. **Verify schema parity:** `python -m src.main validate-schema` → no drift.
6. **Set gate ON via NSSM append-syntax** (per M5 / `feedback_strict_rigor_no_handwave`):
   ```powershell
   nssm set ArcisWatchLoop AppEnvironmentExtra `
     PYTHONUTF8=1 `
     ARCIS_DB_PATH=C:/arcis/data/ai_research_desk.sqlite3 `
     DATABASE_URL=<render-postgres-url> `
     ARCIS_PG_CUTOVER_ENABLED=1
   nssm restart ArcisWatchLoop
   ```
7. **T3.4 smoke (30 min).** Within the first 30 minutes after restart:
   - Watch loop heartbeat logs reference PG ("connected to PG", first INSERT acknowledged)
   - `psql $DATABASE_URL -c "SELECT COUNT(*) FROM shadow_trades WHERE updated_at >= NOW() - INTERVAL '5 minutes';"` returns non-zero
   - Dashboard `/api/kpis` returns data with PG-routed reads (manually verify via curl)
   - `psql $DATABASE_URL -c "SELECT COUNT(*) FROM bracket_health WHERE checked_at::timestamp >= NOW() - INTERVAL '10 minutes';"` returns non-zero (proves the new sync_to_postgres=True flag → PG write path is live)
   - Critically — `sqlite3 C:\arcis\data\ai_research_desk.sqlite3 "SELECT COUNT(*) FROM shadow_trades WHERE updated_at >= datetime('now', '-5 minutes');"` returns **ZERO** (proves no SQLite drift during gate-on window)
8. **If T3.4 smoke fails or any signal degrades:** rollback per §7.2.

### 7.2 Rollback (30-second path, preserved)

```powershell
nssm set ArcisWatchLoop AppEnvironmentExtra `
  PYTHONUTF8=1 `
  ARCIS_DB_PATH=C:/arcis/data/ai_research_desk.sqlite3 `
  DATABASE_URL=<render-postgres-url>
  # (ARCIS_PG_CUTOVER_ENABLED unset)
nssm restart ArcisWatchLoop
```

Next `connect_db()` returns SQLite. PG writes during the gate-on window remain in PG; SQLite has the snapshot from step 4. Drift is acceptable for rollback semantics — the trade-off the operator accepts when choosing path-1.

### 7.3 SQLite cold-storage post-stable-cutover

Once the operator declares the cutover stable (≥7 days), the SQLite file's role degrades to cold backup. No new sync runs into it. Operator may choose at SP5 closeout to:
- Keep it as-is (cheap; ~1 GB on disk)
- Rotate to `C:\arcis\data\archive\` and shrink `data/` to PG-only
- Delete (rejected — loses the test/dev path entirely)

This decision is outside the SP5 cutover scope; document the question in CHANGELOG closeout, defer the disposition.

---

## 8. File Inventory

### Modified

| File | Change |
|---|---|
| `src/utils/db.py` | `connect_db` precedence fix; `_warn_db_path_ignored_once` helper; `connect_db_with_pg_retry` parity fix |
| `src/schema/registry.py` | 8 `sync_to_postgres=False`→`True` flips; sync_pk/sync_mode/sync_time_column added on each; `sync_state` block REMOVED |
| `src/training/ab_evaluation.py` | `engine_aware_upsert(action='ignore')` |
| `src/training/dpo_pipeline.py` | `engine_aware_upsert(action='ignore')` |
| `src/commands/executor.py` | `engine_aware_upsert(action='ignore')` for command_results |
| `src/config/overrides.py` | `engine_aware_upsert(action='replace')` |
| `src/shadow_trading/bracket_monitor.py` | `engine_aware_upsert(action='ignore')` |
| `src/api/cloud_routes/system_index.py` | `engine_aware_upsert(action='replace')` for both writes |
| `src/cli/commands.py` | Remove `cmd_reset_live_prices_watermark` (L1443-1456) |
| `src/cli/main.py` | Remove `reset-live-prices-watermark` subcommand registration |
| `tests/test_db_util.py` | +12 tests (precedence truth table, retry parity, warn-once) |
| `tests/test_schema.py` | +2 tests (registry flag invariants, sync_state removal lock) |
| `tests/test_writers_one_db.py` | NEW — +8 cross-engine writer tests |
| `CHANGELOG.md` | `[Unreleased]` entry |
| `docs/operator-guide.md` | Re-cutover runbook section |

### Deleted

| File | Reason |
|---|---|
| `src/sync/render_sync.py` | Deprecated — sync_state gone, render_sync has no remaining purpose |
| `src/sync/reconcile.py` | Deprecated — same family, was scheduled for Phase 4 anyway |
| `tests/test_render_sync*.py` (multiple) | Tests for deleted module |

### Read-only (touched in scope_fence)

| File | Why read-only |
|---|---|
| `src/utils/db.py` lines 246-345 (CompatRow, _RowFactoryCursor) | Phase 0 helper layer — not in scope; modify only `connect_db` and `connect_db_with_pg_retry` |
| `scripts/render_migrate.py` | Idempotent — schema flips alone trigger the new tables to materialize. No script edit needed. |
| `scripts/sqlite_to_pg_migrate.py` | Reads the registry; picks up the flipped tables automatically. No script edit needed. |

---

## 9. Known Considerations

**K1 — `data_freshness` and `system_metrics` already use engine_aware_upsert.** Their writer code is correct today; they were skipped from PG sync historically because the registry flag was False. Flipping the flag is sufficient — no writer change. The audit table in dynamic context misrepresented this; verified by reading `src/data_enrichment/staleness.py:41` and `src/monitoring/system_metrics.py:155`.

**K2 — `command_results` is already `sync_to_postgres=True`** in the registry (L1556). The dynamic-context audit claim that it's in the 10 local-only tables is wrong — there were never 10, there are 9. The writer at `src/commands/executor.py:69` still needs conversion to `engine_aware_upsert` because of `?` placeholders + manual SQL.

**K3 — `operator_view_state` cloud_routes path.** This is the only flipped table whose writer is in `cloud_routes/` (PG-aware path). Both writes use `ON CONFLICT(user_id, entry_name) DO UPDATE` which SQLite supports natively (3.24+), so the SQL is dual-engine even before conversion. We still convert to `engine_aware_upsert` for consistency and `_REPLACE_SEMANTICS` audit gating.

**K4 — `daily_ib_health` is dormant.** No writer exists; the table is created in SQLite but never written. Flipping `sync_to_postgres=True` creates the empty table in PG. No behavioral risk — the table is documented as future-use.

**K5 — Cloud_routes manual `if database_url:` branches stay.** Per SP-ONEDB-006, the 7 sites in `cloud_routes/` that pre-T3.2 check `if database_url:` and manually use psycopg2 are functionally redundant after the precedence inversion. Removing them is mechanical (~50 lines), but each site has its own quirks (cursor management, transaction boundaries). Backlog item; out of cutover scope.

**K6 — KNOWN_OFFENDERS post-flip.** AST scanner currently shows 0 in the date-functions class (per Phase 2.5 cleanup). After this PR, all 5 writer-conversion targets must still pass the scanner. PM-side gate: each writer task includes `python -m pytest tests/test_no_sqlite_isms_in_pg_safe_files.py -v` in its receipt.

**K7 — `_warn_db_path_ignored_once` not for production hot path.** The set lookup is O(1) but the WARN log itself has stdlib logger overhead. The cap-by-id-set ensures at most ~10 emissions per process (one per distinct db_path argument). Production hot paths use sentinel default (no db_path) so they don't trigger this path at all.

---

## 10. Design Decisions

| ID | Decision | Choice A | Choice B | Selected | Rationale | Falsifiability trigger |
|---|---|---|---|---|---|---|
| SP-ONEDB-001 | SQLite file post-cutover | Delete the file; PG is the only DB | Keep file as stale snapshot for rollback + tests + dev | **B** | The 30-second rollback safety net REQUIRES SQLite to exist locally (gate unset → next connect_db returns sqlite3 against this file). Tests use it (336 sites use explicit db_path → SQLite). Dev boxes use it (no DATABASE_URL → SQLite). All three constituencies depend on it. Cost of keeping it: ~1 GB on disk and operator awareness of "this is a stale snapshot, not the source of truth post-cutover." | If we observe operator confusion about which DB is authoritative — e.g. a CHANGELOG entry references the SQLite file as a write target — re-evaluate and add a startup banner |
| SP-ONEDB-002 | sync_state table — delete or migrate? | Migrate to PG with the other 9 | **Delete entirely; render_sync.py is dead** | **B** | `sync_state` was render_sync's bookkeeping. With the unified DB, render_sync is gone (PG is no longer "the cloud" to sync TO — it IS the production DB). Migrating sync_state to PG would create a dead table on a dead concept. Two callers: render_sync.py (deleting whole file anyway) and `cmd_reset_live_prices_watermark` (which references `live_prices` table — also a render_sync artifact). Cleaner to delete now than carry forward. | If a future feature wants per-table cursor tracking, recreate the table at that time. The schema is simple (table_name, last_synced_at) — no loss to deletion. |
| SP-ONEDB-003 | `schema/sqlite.py` _sqlite_only_connect — keep or remove? | Remove; bypass-the-shim is no longer needed | **Keep** | **A in disguise** — keep for now, scope removal to Phase 4 cleanup if SQLite-only call paths drop to zero. Dev boxes still need it (initialize_database needs PRAGMA index_list for index reconciliation; PRAGMA isn't dual-engine). Tests need it (schema bootstrap before test runs). Production with gate-on doesn't call it at all (connect_db routes to PG; this function is only invoked from `create_all_tables`, which is called by `validate-schema` CLI on the operator's box, never by the watch loop in prod). | If a SQLite-only call path is added post-cutover that violates the one-DB invariant, the AST scanner catches `import _sqlite_only_connect` outside the allowlist and fails. |
| SP-ONEDB-004 | How do flipped tables get into PG before re-cutover? | Single new bootstrap script | **Re-run existing render_migrate.py + sqlite_to_pg_migrate.py** | **B** | The existing scripts are idempotent and registry-driven — they already pick up `sync_to_postgres=True` tables automatically. Adding a new bootstrap script means writing migration code that duplicates what the migrator already does. Re-running the path-1 prereq is the documented operator runbook for this exact scenario. | If the migrator fails on any of the 8 newly-eligible tables, the path-1 step in §7.1 reports it; operator pauses and adds the missing sync_mode/sync_pk fields to registry. |
| SP-ONEDB-005 | Rollback semantics — what's the SQLite state post-cutover? | Run a reverse-migrator on rollback | **Stale snapshot; accept drift** | **B** | A reverse-migrator (PG→SQLite) requires test coverage, edge cases for the FK-cascade tables, and 2× the runtime of the forward path. The operator-stated trade-off when choosing path-1 was "30-second rollback acceptable even if SQLite is stale for the gate-on window." Documented in §2.4; preserved by §7.2. | If rollback occurs and the SQLite drift causes a downstream data-quality issue, the operator escalates to a manual `pg_dump` → `sqlite_import` recovery (1-shot, ad-hoc). Out of scope for SP5. |
| SP-ONEDB-006 | render_sync.py + reconcile.py + cloud_routes manual branches — delete now or Phase 4? | Defer all to Phase 4 | **Delete render_sync + reconcile now (sync_state removal forces it); leave cloud_routes branches for backlog** | **B (split)** | render_sync.py's only purpose was to populate `sync_state` and ship rows PG→SQLite for pending_commands; with sync_state gone and the cutover making PG authoritative, render_sync has no callers. Same for reconcile.py (PG↔SQLite reconciliation — pointless when there's only one source of truth). They are dead code post-flip; deleting them now reduces audit surface for the cutover. The cloud_routes `if database_url:` branches are functionally redundant but each site has independent logic; cleanup is mechanical-but-numerous, scoped as backlog. | If render_sync.py or reconcile.py is imported anywhere else (a stale call site we missed), CI's import-time errors catch it; revert the deletion and re-evaluate. |
| SP-ONEDB-007 | Test environment behavior post-fix | Add `ARCIS_PG_CUTOVER_ENABLED=0` to conftest setUp | **Rely on env-var absence (gate off by default)** | **B** | Tests do not export `ARCIS_PG_CUTOVER_ENABLED`. The gate check uses `os.environ.get("ARCIS_PG_CUTOVER_ENABLED") == "1"` — unset → False → SQLite branch. No conftest edit needed. CI runs with no PG env vars at all (postgres:16-alpine sidecar uses `TEST_DATABASE_URL`, not `DATABASE_URL`). | If a CI environment leaks `ARCIS_PG_CUTOVER_ENABLED=1` into the test process by accident, all 336 explicit-db_path tests fail with PG connection errors — fast and loud. Conftest can add a `monkeypatch.delenv("ARCIS_PG_CUTOVER_ENABLED", raising=False)` defensively if this is observed. |
| SP-ONEDB-008 | AST scanner KNOWN_OFFENDERS for the 9 flipped tables | Allowlist the 5 writer files temporarily | **Re-audit each writer; convert raw INSERT to engine_aware_upsert; pass clean** | **B** | The Phase 2.5 cleanup got the date-functions class to 0 offenders. Adding allowlist entries for a clean-up PR is regression in the wrong direction. Each writer converts to `engine_aware_upsert` (the canonical safe path) which has no `?` outside the wrapper and no SQLite-specific syntax. The 5 writer tasks each include re-running the scanner in their receipt. | If a writer can't be converted to `engine_aware_upsert` cleanly (e.g., dynamic column lists), it gets its own task with a specific scope_fence + escape clause; we don't allowlist as the default response. |
| SP-ONEDB-009 | Should `_warn_db_path_ignored_once` exist at all? | Silent override (no log) | **One-time WARN log per distinct db_path argument** | **B** | The 2026-05-11 cutover failed because the operator and the implementation disagreed about routing. A silent override means the next time someone hits this in 6 months, they have no signal. A WARN log per distinct path provides forensic context (`grep "ignoring db_path"`) without spamming the hot path (cap-by-id-set bounds emissions). The log message names the env var operators control to flip the routing. | If the WARN log becomes noise (e.g., a hot path with many distinct paths), tighten the cap or move to `logger.debug`. Not a correctness concern — purely DX. |
| SP-ONEDB-010 | Order of operations: precedence fix + table flips in one PR, or sequence? | Sequence: precedence first, flips second | **One PR (or worktree-parallel batches in one wave)** | **B** | Sequencing has a risky middle state: precedence-fix merged means production routes all reads/writes to PG including the 9 not-yet-migrated tables → reads return empty / writes silently fail with "table does not exist." One PR ships precedence + flips + writer fixes together, and the operator runs the migrator BEFORE flipping the gate. The gate is the cutover-execution boundary; the PR is just code. | If a partial-state PR is unavoidable (worktree-split), the table flips MUST land before the precedence fix lands in main, OR the operator commits to not flipping the gate until both are merged. The runbook step 6 (gate flip) is the operator's check. |
| SP-ONEDB-011 | Disposition of operator_view_state writer (cloud_routes vs core) | Keep in cloud_routes (PG-aware now-redundant branch) | Move to core | **A** | The cloud_routes/ directory's pattern is "API endpoints that may need PG-aware behavior even pre-cutover." Post-cutover, the precedence inversion makes those branches redundant but the file's organizational logic — these are FastAPI endpoint helpers — remains. Moving writers out of cloud_routes for organizational tidiness is a separate concern (SP-ONEDB-006 K5). | If the cloud_routes manual branches become a maintenance burden post-cutover (multiple bugs traced to "did we use the cloud_routes branch or the wrapper?"), batch their removal in a future PR. |

---

## 11. Do-Not-Do

- **Do NOT** modify `_REPLACE_SEMANTICS` except to add `operator_view_state: 'in_place_update'`. No new tables; no semantic upgrades.
- **Do NOT** rewrite the `_rewrite_question_to_pct` state machine. Phase 0 T0.2 proved it correct; testing pinned it.
- **Do NOT** remove `_sqlite_only_connect` — see SP-ONEDB-003.
- **Do NOT** add new `connect_db()` overloads or kwargs. The contract is `(db_path=_SENTINEL)` and the precedence rule is the only routing dimension.
- **Do NOT** restructure the cloud_routes `if database_url:` branches in this PR (SP-ONEDB-006).
- **Do NOT** allowlist any writer in the AST scanner (SP-ONEDB-008).
- **Do NOT** automate the operator runbook in §7.1. NSSM env changes are operator-trust operations per memory `reference_watch_loop_management` and `feedback_strict_rigor_no_handwave`.
- **Do NOT** ship a reverse-migrator (SP-ONEDB-005). Rollback drift is documented and accepted.
- **Do NOT** delete the SQLite file post-cutover (SP-ONEDB-001).

---

## 12. Falsifiability Triggers

After the PR lands and the re-cutover executes, the following observations would falsify the spec's claims and require re-design:

1. **T3.4 smoke shows ANY write landing in SQLite during the gate-on window.** This is the exact failure mode PR #1054 had. The truth table in §2.1 row 8 must hold. Test: `sqlite3 ... "SELECT COUNT(*) FROM shadow_trades WHERE updated_at >= datetime('now', '-5 minutes');"` returns 0 within 10 min of restart.
2. **PG-reachable but a known table reports `relation does not exist`.** This means the registry flip didn't trigger the migrator to create the table. Operator pauses, runs render_migrate.py, re-tries.
3. **`_warn_db_path_ignored_once` fires more than 50 times per minute.** Indicates a hot-path call site is passing db_path. Investigate and refactor that call site to use sentinel default.
4. **A write fails with `psycopg2.errors.UndefinedColumn` for any of the 9 newly-flipped tables.** Means the table was created in PG but with stale columns (schema-registry drift between SQLite and PG). Operator runs `python -m src.main validate-schema --fix` and re-attempts.
5. **Rollback (gate unset) doesn't immediately route to SQLite.** Means a process is holding a cached PostgresConnectionWrapper. Restart the affected process (watch loop, FastAPI workers).
6. **The AST scanner reports new violations in any of the 5 modified writer files.** PR rejected by CI; convert the offending line to `engine_aware_upsert` or pin the exception in the scanner allowlist with rationale.
7. **`engine_aware_upsert` raises ValueError on `operator_view_state` action='replace'.** Means SP-ONEDB-011's addition to `_REPLACE_SEMANTICS` was forgotten. Add the line and re-run.
8. **CHANGELOG and operator-guide drift from the runbook.** Failure of SP-ONEDB-010 — re-issue the docs.

If any of (1)-(5) fires within 30 min of the re-cutover, **rollback via §7.2** and re-evaluate this spec. The 15-min rollback window from PR #1054 is the precedent — operator preference is fast revert + redesign over slow forward-fix.

---

End of spec.
