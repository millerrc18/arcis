# Cutover Rectification Sprint — Post-Failure Hardening

**Date:** 2026-05-11
**Sprint:** SP5 §J5/§J6 follow-up (post-Phase-3-revised cutover attempt)
**Status:** Open — required before next cutover attempt
**Lineage:** Phase 0 (#1048) → Phase 1 (#1049) → Phase 2 (#1050) → Phase 2.5 (#1052) → Phase 3-revised (#1055) → THIS PR

## Context

The Phase 3-revised one-database cutover was attempted on 2026-05-11T20:37:06Z and **rolled back at 20:44:48Z** (~8 min in) after two distinct P0 failure modes surfaced:

- **P0 #89** — PG tables disappearing: 72 tables present immediately after migration, 13 tables remaining 5 minutes later. 59 sync-eligible tables vanished. No `DROP TABLE` statements in PG logs (because `log_statement=none`).
- **P0 #90** — SQLite write leak: One `shadow_trades` row (NVDA, `status='rejected'`) landed in SQLite at 20:38:59Z despite the gate being on. Some write path bypassed the precedence inversion.

The 30-second rollback gate worked correctly. Watch loop is healthy on SQLite. But neither P0 has a confirmed root cause and both are blockers for the next cutover attempt.

This sprint executes **9 rectification items** (filed during the post-mortem) plus any additional issues that surface during implementation. Goal: the next cutover attempt has comprehensive instrumentation + hardened guardrails so the failure modes either (a) can't recur or (b) leave a precise forensic trail.

## Architecture

This is a **hardening sprint** — no new features. Three change classes:

1. **PG configuration** — runtime settings + role hardening so DDL is captured and superuser footprint is reduced
2. **Migration script hygiene** — fix the bulk-INSERT-without-sequence-advance pkey-conflict cascade + drift-detection gaps
3. **Watch-loop runtime instrumentation** — every routing decision leaves a forensic trail; discipline tests detect indirect bypasses

## Tasks (9 items + scope-creep allowance)

### T1 — Enable PG `log_statement=all` via docker-compose

**Goal:** PG logs every DDL/DML so the next "59 tables disappeared" mystery has a paper trail.

**Files in scope:**
- `docker-compose.yml`

**Change:**
```yaml
# Add to halcyon-pg service:
command:
  - "postgres"
  - "-c"
  - "log_statement=all"
  - "-c"
  - "log_line_prefix=%t [%p] %u@%d "
```

**Test strategy:** Manual verification post-implementation — `docker exec halcyon-pg psql -U halcyon -d halcyon -c "SHOW log_statement;"` must return `all`. Add a regression-lock test that reads `docker-compose.yml` and asserts the `-c log_statement=all` flag is present. No automated PG test — operator restarts container post-merge.

**Scope fence:**
- ONLY edit `docker-compose.yml`
- Do NOT add a new PG service
- Do NOT modify volumes, ports, or networks
- Do NOT change POSTGRES_USER/POSTGRES_PASSWORD/POSTGRES_DB
- New test file: `tests/test_docker_compose_logging.py` (regression lock)

**Acceptance:** docker-compose.yml diff is exactly the `command:` block addition; regression test passes.

---

### T2 — Create non-superuser PG application role + read-only role for pgAdmin

**Goal:** Defense-in-depth — the watch loop's PG connection shouldn't have superuser privileges. Also create a read-only role for pgAdmin so GUI users can't accidentally DROP tables.

**Files in scope:**
- `scripts/setup_pg_roles.py` (NEW) — idempotent role creation script
- `docs/operator-guide.md` — runbook addition for role setup
- `tests/test_pg_roles_script.py` (NEW) — verifies the script's SQL is well-formed

**Roles to create:**
1. `halcyon_app` — INSERT/SELECT/UPDATE/DELETE on all sync-eligible tables. NO SUPERUSER. NO CREATE/DROP TABLE. This becomes the role the watch loop authenticates as (post-cutover).
2. `halcyon_readonly` — SELECT only on all tables. For pgAdmin / dashboard / analytical access.

**Script logic (`scripts/setup_pg_roles.py`):**
```python
# Connect as halcyon (superuser). Run:
#   CREATE ROLE halcyon_app WITH LOGIN PASSWORD '<from env DOCKER_PG_APP_PASSWORD>';
#   CREATE ROLE halcyon_readonly WITH LOGIN PASSWORD '<from env DOCKER_PG_RO_PASSWORD>';
#   GRANT CONNECT ON DATABASE halcyon TO halcyon_app, halcyon_readonly;
#   GRANT USAGE ON SCHEMA public TO halcyon_app, halcyon_readonly;
#   GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO halcyon_app;
#   GRANT SELECT ON ALL TABLES IN SCHEMA public TO halcyon_readonly;
#   GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO halcyon_app;
#   ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO halcyon_app;
#   ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO halcyon_readonly;
# All statements wrapped in DO $$ ... EXCEPTION WHEN duplicate_object THEN NULL; $$
# so the script is idempotent.
```

**Test strategy:** Mock psycopg2 connection; assert the script issues the expected sequence of GRANT/CREATE ROLE statements. Verify idempotence (running twice = same end state). No live PG required.

**Scope fence:**
- ONLY add the 2 new files + edit operator-guide.md (runbook section)
- Do NOT modify the watch loop or NSSM env in this PR — role rotation is a follow-up step the operator does after merge
- Do NOT modify docker-compose.yml's POSTGRES_USER (still `halcyon` as superuser; new roles are additional)
- New env vars `DOCKER_PG_APP_PASSWORD` + `DOCKER_PG_RO_PASSWORD` referenced but not committed (operator adds to .env post-merge)

**Acceptance:** Script syntax-parses; test verifies idempotent SQL; operator-guide has a clear runbook step for running it post-merge.

---

### T3 — Fix `setup_signals` NOT NULL drift between SQLite + PG (and any other column-level drifts)

**Goal:** The PG cutover crashed at 20:37:44 with `null value in column "setup_type"` because SQLite allowed NULL setup_type but PG enforced NOT NULL. The drift is in the registry's NULL semantics — needs reconciliation.

**Investigation first:** Run a drift-detection script that compares per-table per-column NULL constraints between live SQLite + registry + a fresh PG schema. Surface ALL drift cases, not just `setup_signals.setup_type`.

**Files in scope:**
- `scripts/audit_schema_drift.py` (NEW) — drift detector
- `src/schema/registry.py` — fix any per-column NULL drift surfaced
- `tests/test_schema_drift_audit.py` (NEW) — regression lock for `setup_signals.setup_type` + any other drifts found
- `docs/audits/2026-05-11-cutover-rectification/drift-audit-results.md` (NEW) — operator-readable summary of drifts found

**Drift detection logic:**
- For each table in `TABLES.items()` where `sync_to_postgres=True`:
  - For each column: compare `column.nullable` (registry) vs SQLite `pragma_table_info(...)` `notnull` field vs PG `information_schema.columns.is_nullable`
  - Report mismatches: `table.col: registry={X} sqlite={Y} pg={Z}`
- Output: markdown report + JSON

**Test strategy:** Add `test_setup_signals_setup_type_nullable_in_registry` (regression-lock for the specific drift) + `test_schema_registry_consistency` (ensures every NOT-NULL column has a default OR is in a documented-required-input set).

**Scope fence:**
- ONLY edit `src/schema/registry.py` for column-attribute fixes
- Do NOT add new tables or columns
- Do NOT change primary_key, foreign_keys, or indexes
- Other drift cases (CHECK constraints, defaults, etc.) are out of scope — file as follow-up tasks

**Acceptance:** Drift report committed; `setup_signals.setup_type` either reconciled to NULLABLE in registry+PG OR reconciled to NOT NULL in registry+SQLite (with default value); test verifies the resolution holds.

---

### T4 — Sequence-advance after bulk INSERT in `sqlite_to_pg_migrate.py`

**Goal:** Post-migration, PG sequences (e.g., `activity_log_id_seq`) are still at 1 even though tables have rows up to id=N. First watch-loop INSERT auto-assigns id=1 and conflicts. Fix: after bulk INSERT, advance the sequence to `MAX(id) + 1`.

**Files in scope:**
- `scripts/sqlite_to_pg_migrate.py`
- `tests/test_sqlite_to_pg_migrate.py` — add 1 test for the seq-advance behavior

**Change:**
```python
# After _migrate_table() succeeds, for each table with an INTEGER PRIMARY KEY 
# that's auto-incremented (i.e., has a sequence in PG):
def _advance_sequence_after_bulk(pg_conn, table_name: str, pk_col: str) -> None:
    """Advance the PG sequence for an integer PK to MAX(id) + 1 post-bulk-load.
    
    Postgres SERIAL/IDENTITY columns have an associated sequence (e.g.,
    activity_log_id_seq). Bulk INSERTs that specify explicit id values do NOT
    advance the sequence. Subsequent INSERTs that omit id rely on the sequence
    and will collide with existing rows.
    """
    with pg_conn.cursor() as cur:
        cur.execute(f"SELECT pg_get_serial_sequence(%s, %s)", (table_name, pk_col))
        seq_row = cur.fetchone()
        if not seq_row or not seq_row[0]:
            return  # not a serial column
        seq_name = seq_row[0]
        cur.execute(
            f"SELECT setval(%s, COALESCE(MAX({pk_col}), 0) + 1, false) FROM {table_name}",
            (seq_name,),
        )
    pg_conn.commit()
```

Call this after every successful `_migrate_table()`. Skip for tables where PK is not integer (UUID, composite, etc.).

**Test strategy:** Mock pg_conn, verify the `setval` call is issued with correct args. Live verification: after migration, `SELECT last_value FROM activity_log_id_seq;` returns > 0.

**Scope fence:**
- ONLY edit `scripts/sqlite_to_pg_migrate.py` + the test
- Do NOT modify the registry
- Do NOT change which tables are migrated
- Do NOT modify connection handling outside the per-table loop

**Acceptance:** Test passes; manual verification: post-migration, no pkey conflict on subsequent INSERTs.

---

### T5 — Add WARN-once instrumentation on `connect_db()` SQLite-routing path under gate-on

**Goal:** When the gate is on, any SQLite routing should be visible. Currently the inverse exists (WARN-once when explicit-path is overridden to PG, SP-ONEDB-009). Add the symmetric WARN: if the gate is on AND we still return SQLite (because pg_url is missing or another reason), emit a WARN.

**Files in scope:**
- `src/utils/db.py`
- `tests/test_db_util.py`

**Change to `connect_db()`:**
```python
# After the current gate-on-and-pg-url branch (existing PG path):
if gate_on and pg_url:
    ...existing PG routing...

# NEW: WARN if gate is on but we're falling through to SQLite
if gate_on and not pg_url:
    _warn_gate_on_no_pg_url_once()

# Existing SQLite fallback path
effective_path = DEFAULT_DB if db_path is _SENTINEL else db_path
conn = sqlite3.connect(effective_path, ...)
...
```

**Helper:**
```python
_GATE_ON_NO_PG_URL_WARNED: bool = False

def _warn_gate_on_no_pg_url_once() -> None:
    """Single WARN when gate is on but DATABASE_URL doesn't start with postgres.
    
    This is the symmetric forensic signal to _warn_db_path_ignored_once: if the
    operator sets ARCIS_PG_CUTOVER_ENABLED=1 but DATABASE_URL is empty or
    non-postgres, we silently fall through to SQLite. This WARN ensures the
    misconfig leaves a forensic trail.
    """
    global _GATE_ON_NO_PG_URL_WARNED
    if _GATE_ON_NO_PG_URL_WARNED:
        return
    _GATE_ON_NO_PG_URL_WARNED = True
    logger.warning(
        "[DB] ARCIS_PG_CUTOVER_ENABLED=1 but DATABASE_URL does not start with "
        "'postgres' — falling through to SQLite. Verify NSSM env via "
        "`nssm get <service> AppEnvironmentExtra`."
    )
```

**Test strategy:** 2 new tests:
- `test_warn_gate_on_no_pg_url_emits_once`: gate=on, url=empty, call connect_db twice; assert exactly 1 WARN
- `test_warn_gate_on_no_pg_url_silent_when_pg_url_set`: gate=on, url=pg, call connect_db; assert NO warn (only the existing SP-ONEDB-009 warn if explicit path)

**Scope fence:**
- ONLY edit `src/utils/db.py` (add helper + 1 call site) + test_db_util.py
- Do NOT modify the truth-table logic — only add a WARN at one specific cell
- Do NOT modify `_REPLACE_SEMANTICS` or any engine_aware helper
- Do NOT change `_warn_db_path_ignored_once`

**Acceptance:** 2 new tests pass; existing 22 truth-table tests still pass; AST scanner stays 15/15.

---

### T6 — Extend `test_connect_db_discipline.py` to trace through wrapper functions

**Goal:** The current discipline test scans `src/` for raw `sqlite3.connect` patterns. It does NOT verify that indirect callers (e.g., `journal.store:insert_shadow_trade()`) properly use `connect_db()`. Extend the test to trace through known wrapper functions.

**Files in scope:**
- `tests/test_connect_db_discipline.py`
- (Optionally `src/journal/store.py` if a small refactor makes tracing easier — but try to keep src/ unchanged)

**Change:**
Add a new test `test_wrapper_functions_use_connect_db`:
- Define a list of known DB wrapper functions: `[("src/journal/store.py", "insert_shadow_trade"), ("src/utils/activity_logger.py", "log_activity"), ...]`
- For each, AST-parse the function and assert it uses `connect_db(...)` (not raw `sqlite3.connect`)
- This is structural — it doesn't run the function, just validates the import + call chain

**Test strategy:** Self-test — the test itself verifies its scanner catches a synthetic violation.

**Scope fence:**
- ONLY edit `tests/test_connect_db_discipline.py`
- Do NOT modify the AST scanner module itself (it's in `tests/test_no_sqlite_isms_in_pg_safe_files.py`)
- Do NOT add new wrapper functions — only audit existing ones
- Wrapper-function list should be discovered, not hardcoded: scan src/ for functions named `insert_*`, `log_*`, `record_*`, `save_*` and audit each

**Acceptance:** New test passes; if any wrapper function uses raw `sqlite3.connect` instead of `connect_db()`, the test fails with a clear message naming the file:line.

---

### T7 — Process-startup env-state fail-fast assertion

**Goal:** At watch-loop process startup, before any DB writes, assert env state is consistent. If `ARCIS_PG_CUTOVER_ENABLED=1` but `DATABASE_URL` is empty/non-postgres, fail-fast with a clear message rather than silently routing to SQLite.

**Files in scope:**
- `src/startup_checks.py` — add a new check function
- `src/startup.py` — register the new check in STARTUP_CATEGORIES
- `tests/test_startup_checks.py` (or appropriate existing test file)

**New check function:**
```python
def check_cutover_gate_consistency(config: dict, db_path: str) -> list[CheckResult]:
    """Verify ARCIS_PG_CUTOVER_ENABLED + DATABASE_URL are consistent at process start.
    
    The Phase 3-revised cutover requires BOTH env vars to be set together for
    PG routing. If gate is on but DATABASE_URL is missing, every connect_db()
    call silently falls through to SQLite — a partial cutover state with no
    forensic signal until the new T5 WARN fires.
    
    This check makes the misconfig fail-fast at process start instead.
    """
    gate_on = os.environ.get("ARCIS_PG_CUTOVER_ENABLED") == "1"
    database_url = os.environ.get("DATABASE_URL", "")
    pg_url = database_url.startswith("postgres")
    
    if gate_on and not pg_url:
        return [CheckResult(
            name="cutover_gate_consistency", category="config", status="critical",
            detail="ARCIS_PG_CUTOVER_ENABLED=1 but DATABASE_URL does not start with 'postgres'",
            fix_hint="Either unset ARCIS_PG_CUTOVER_ENABLED (revert to SQLite) or set DATABASE_URL=postgresql://...",
        )]
    if not gate_on and pg_url:
        return [CheckResult(
            name="cutover_gate_consistency", category="config", status="warn",
            detail="DATABASE_URL is postgres but ARCIS_PG_CUTOVER_ENABLED is not set — gate is OFF, writes route to SQLite",
            fix_hint="If cutover desired: nssm set <svc> AppEnvironmentExtra <existing> ARCIS_PG_CUTOVER_ENABLED=1",
        )]
    return [CheckResult(
        name="cutover_gate_consistency", category="config", status="ok",
        detail=f"Gate={gate_on} pg_url={pg_url} (consistent)",
        fix_hint="",
    )]
```

Register in `STARTUP_CATEGORIES` (Config category).

**Test strategy:** 4 tests covering the 4 truth-table corners (gate_on × pg_url). Critical case (gate_on=True, pg_url=False) returns `critical` status which causes startup to fail per existing exit-code conventions.

**Scope fence:**
- ONLY edit `src/startup_checks.py` (add function) + `src/startup.py` (register) + test file
- Do NOT modify the existing check functions
- Do NOT change the CRITICAL→exit-1 behavior in cmd_startup

**Acceptance:** 4 new tests pass; gate-on + no-pg-url misconfig now fails startup with clear error.

---

### T8 — Operator-guide cutover-runbook update for pgAdmin discipline + pg_stat_activity capture

**Goal:** Add operator guidance to (a) disconnect pgAdmin from PG during cutover or use the new readonly role, and (b) capture `pg_stat_activity` snapshots every 30s during cutover for connection forensics.

**Files in scope:**
- `docs/operator-guide.md`
- `scripts/capture_pg_activity.ps1` (NEW) — PowerShell snippet that captures pg_stat_activity to a log file

**operator-guide additions:**
1. **Step 0.5 (new pre-flight check)**: Verify pgAdmin is disconnected OR using `halcyon_readonly` role. Command: `docker exec halcyon-pg psql -U halcyon -d halcyon -c "SELECT application_name FROM pg_stat_activity WHERE usename != 'halcyon_app' AND application_name LIKE '%pgAdmin%';"` should return zero rows.
2. **Step 7.5 (new mid-smoke capture)**: Run `scripts/capture_pg_activity.ps1` in a separate PowerShell terminal during the 30-min smoke. Captures pg_stat_activity every 30s to `C:/arcis/logs/pg-activity-<timestamp>.log`. Stops when smoke completes.

**Capture script:**
```powershell
# capture_pg_activity.ps1
$logPath = "C:/arcis/logs/pg-activity-$(Get-Date -Format 'yyyy-MM-dd-HHmmss').log"
Write-Host "Capturing pg_stat_activity every 30s to $logPath. Ctrl+C to stop."
while ($true) {
    $ts = Get-Date -Format "yyyy-MM-ddTHH:mm:ssZ"
    "=== $ts ===" | Out-File -Append $logPath
    docker exec halcyon-pg psql -U halcyon -d halcyon -c `
        "SELECT pid, usename, client_addr, application_name, state, query_start, LEFT(query, 200) AS query_preview FROM pg_stat_activity WHERE datname='halcyon' ORDER BY query_start DESC;" `
        | Out-File -Append $logPath
    Start-Sleep -Seconds 30
}
```

**Test strategy:** Docs-only + script. Lint the PowerShell script syntactically via `Test-PSScriptAnalyzer` if available, otherwise PR-time visual review.

**Scope fence:**
- ONLY edit `docs/operator-guide.md` + add the PS1 script
- Do NOT modify any other docs or scripts
- Do NOT add Python tests for the PS1 script (it's a shell utility)

**Acceptance:** Operator-guide has both new steps integrated into the Phase 3-revised cutover runbook section; PS1 script is executable and well-formed.

---

### T9 — CHANGELOG entry

**Goal:** Document the rectification PR under `[Unreleased]`.

**Files in scope:**
- `CHANGELOG.md`

**Entry:**
```markdown
### SP5 §J5/§J6 Cutover Rectification — 9 hardening items

Post-mortem follow-up after the Phase 3-revised cutover attempt rolled back at 2026-05-11T20:44:48Z. Two P0 failure modes surfaced (#89 PG tables disappearing, #90 SQLite write leak) — neither had a definitive root cause due to PG log_statement=none + missing forensic instrumentation. This PR closes the instrumentation + guardrail gaps so the next attempt either can't fail the same way or leaves a precise forensic trail.

- **docker-compose.yml** — PG now runs with `log_statement=all` + `log_line_prefix=%t [%p] %u@%d` (T1)
- **scripts/setup_pg_roles.py** (NEW) — idempotent creation of `halcyon_app` (non-superuser, INSERT/SELECT/UPDATE/DELETE) + `halcyon_readonly` (SELECT only) roles (T2)
- **src/schema/registry.py** — `setup_signals.setup_type` NULL drift reconciled; other drifts surfaced in `docs/audits/2026-05-11-cutover-rectification/drift-audit-results.md` (T3)
- **scripts/sqlite_to_pg_migrate.py** — bulk INSERT now followed by `setval('<table>_id_seq', MAX(id) + 1)` for integer PK columns; closes the pkey-conflict crash class (T4)
- **src/utils/db.py** — `connect_db()` now emits WARN-once when gate is on but DATABASE_URL is non-postgres (symmetric forensic signal to SP-ONEDB-009) (T5)
- **tests/test_connect_db_discipline.py** — extended to trace through wrapper functions (`insert_shadow_trade`, `log_activity`, etc.) verifying they use `connect_db()` not raw sqlite3 (T6)
- **src/startup_checks.py + src/startup.py** — new `check_cutover_gate_consistency` fail-fast assertion catches gate/url mismatch at process startup (T7)
- **docs/operator-guide.md + scripts/capture_pg_activity.ps1** — runbook now includes pgAdmin disconnect step + pg_stat_activity snapshot capture during smoke (T8)
- **docs/audits/2026-05-11-cutover-rectification/spec.md** + drift-audit-results.md — sprint provenance (T3, T9)
```

**Scope fence:**
- ONLY edit `CHANGELOG.md`
- Insert above the existing top `[Unreleased]` entry (Phase 3-revised)
- No code changes

**Acceptance:** CHANGELOG has the new section at the top of [Unreleased]; renders cleanly.

---

## Sprint discipline

Every task must:
1. Use worktree isolation (`isolation: "worktree"` for every Developer dispatch)
2. Commit + push per sub-deliverable (per Delivery Discipline §2)
3. Run `tests/test_repo_structure.py` and disclose any new violations
4. Re-run AST scanner (`test_no_sqlite_isms_in_pg_safe_files.py`) + discipline (`test_connect_db_discipline.py`) — both must stay 15/15
5. Sibling-search per memory `feedback_review_sibling_search` — use the three-form regex `(from src\.X|import src\.X|src\.X\.)` for any deletion/rename
6. Strict-rigor receipt in each status report

## Out of scope (do NOT do in this sprint)

- Actually flipping watch-loop NSSM env to use `halcyon_app` role — that's an operator decision post-merge (next cutover attempt)
- Walk-forward implementation — deferred per memory `feedback_sprint_5_is_final`
- New CHECK constraint reconciliation (only NULL drift in scope)
- Frontend changes — none of the 9 items affect frontend
- Live cutover retry — only fixing the instrumentation; operator decides when to retry

## Acceptance criteria — sprint-level

This sprint is COMPLETE when:
1. All 9 task PRs merged into one integration branch
2. Drift audit report exists, identifies all NOT-NULL drifts, and `setup_signals.setup_type` is reconciled
3. Test floor: net +15 to +30 tests added; AST scanner + discipline tests stay green
4. PR opened against main with exhaustive review body
5. After merge, operator can re-execute cutover with confidence that:
   - Any future table-disappearance has DDL captured in PG log
   - Any future SQLite leak under gate-on emits WARN-once
   - Gate/URL misconfig fails at process startup (not silently mid-flight)
   - pgAdmin can't accidentally destroy data (use halcyon_readonly)
   - Bulk-INSERT sequence-advance prevents pkey-conflict cascade
