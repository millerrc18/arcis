# Arcis #100 Sim Conn-Lifecycle Leak — Implementation Plan

**Spec:** [`docs/audits/2026-05-24-sim-conn-leak/specs/2026-05-24-sim-conn-leak-design.md`](../specs/2026-05-24-sim-conn-leak-design.md)
**Target release:** v0.36.6X (re-baseline at implementation time per #105 lesson; current main is v0.36.63)
**Estimated effort:** ~½ day agent work, dual-Opus QA
**Tasks:** 7 across 3 execution batches
**Sim-side fix only — PROD watch-loop conn pool behavior unchanged.**

---

## Implementation Discipline (read first)

PREAMBLE — Out-of-scope deferral: NONE. If you encounter broken tests / hardcoded values / drifted references / repairable defects WHILE executing the effort, fix INSIDE the effort. Do not write 'Out of scope (pre-existing failures)' in PR body. If a surfaced issue is GENUINELY larger than the effort, STOP + surface via AskUserQuestion.

Dual-Opus QA gate per #98 standard: two independent Opus reviewers verify root-cause / hardening / ripple / noise dimensions at 100% confidence before merge. PRIMARY verify-by-mutation evidence (TEST 1 RED with InFailedSqlTransaction + GREEN with 9 InvariantResults) MUST appear in PR body — DUAL QA verifies this evidence is the inner-mechanism witness, not just the outer 3x-loop. The 3x-loop accumulator backstop's RED evidence is best-effort and does NOT block merge if not reproducible.

Per-PR versioning: v0.36.6X is a placeholder — at impl time check `git tag --sort=-v:refname | head -3` for the latest baseline and bump accordingly.

Batch 1 (Task 1): Scaffold the leak detector and run the ASSERTIVE bare-pattern sibling-search BEFORE any cursor edits. Sibling-search is REPORTING + AskUserQuestion only on UNEXPECTED sites — do NOT abort on count mismatch alone. The 7-known-site list is: oracle/_checks_db.py {L35, L64, L92, L120, L174}, oracle/_checks_signal.py L32, scenario.py L489. Detector MUST include application_name='sim_leak_observer' on its own conn AND a try/except OperationalError that prints the recovery hint to stderr on too-many-clients markers before re-raising.

Batch 2 (Tasks 2, 3, 4, 5, 7): Parallel-safe. Task 2 owns _checks_db.py. Task 3 owns _checks_signal.py + scenario.py. Task 4 owns invariants.py. Task 5 owns full_gate.py + smoke.py. Task 7 owns the audit doc + CHANGELOG. Zero file overlap.

Batch 3 (Task 6): The regression test exercises all preceding work and owns the verify-by-mutation evidence. MUST contain TWO tests: PRIMARY inner-mechanism witness (mechanically deterministic; stash invariants.py rewrite → InFailedSqlTransaction); BACKSTOP 3x-loop accumulator (best-effort; GC-fuzzy). PRIMARY's RED+GREEN evidence is load-bearing for merge; BACKSTOP's evidence is informational. Both tests use application_name='sim_leak_test' isolation (PGAPPNAME env var for smoke conns, direct kwarg for the inner-test's own conn) and filter the detector via application_name_filter='sim_leak_test'.

PROD AUDIT IS DOCUMENT-ONLY in this PR. bracket_attach.py:126 and broker_exception_logger.py:51 are filed as #100-followup-A and #100-followup-B respectively.

Windows UTF-8 gotcha: any open() call MUST pass encoding='utf-8'. Use Edit/Write tools for markdown writes.

127.0.0.1 not localhost: the sim DSN at _bootstrap.SIM_DATABASE_URL is already 127.0.0.1:5434.

prod_guard sentinel preservation: post-PR `git diff src/simulation/lifecycle/prod_guard.py` MUST be empty.

---

## Execution Order

**Batch 1:** Task 1

**Batch 2:** Task 2, Task 3, Task 4, Task 5, Task 7

**Batch 3:** Task 6

---

## Tasks

### Task 1 — Scaffold _leak_detector.py with application_name filter + too-many-clients fallback

**Estimated complexity:** low

**Files in scope:**
- `src/simulation/lifecycle/_leak_detector.py`

**Files (read-only context):**
- `src/simulation/lifecycle/entrypoints/full_gate.py`
- `src/simulation/lifecycle/entrypoints/smoke.py`
- `src/simulation/lifecycle/prod_guard.py`

**Description:**

Create src/simulation/lifecycle/_leak_detector.py per spec §3.3. Public surface: BackendSnapshot dataclass; snapshot_backends(dsn, datname='halcyon', application_name_filter: str | None = None); format_delta(before, after). REV-2 requirements: (a) detector's own psycopg2.connect MUST advertise application_name='sim_leak_observer'; (b) when application_name_filter is not None, the pg_stat_activity WHERE clause MUST include AND application_name = %s; (c) wrap the psycopg2.connect call in try/except psycopg2.OperationalError — if str(err).lower() contains 'too many clients' OR 'sorry, too many connections', print the recovery hint (verbatim per spec §3.3 _RECOVERY_HINT constant) to sys.stderr BEFORE re-raising; (d) use explicit connect+try/finally close() rather than `with psycopg2.connect(...)` so the except branch fires before any context-manager exit. NO monkeypatch of psycopg2.connect. NO composition with prod_guard. Six-line module header per project convention.

SIBLING-SEARCH (REV-2 per DA2 — ASSERTIVE not ABORTIVE): Before implementing the module, run a sibling-search Grep across src/simulation/lifecycle/ for the BARE-PATTERN regex `cur\s*=\s*[a-zA-Z_]+\.cursor\(\)` (assignment to bare cursor, NOT `with ... as cur:`). Print the full list of matches with file:line. Cross-reference against the 7 known sites from spec §3.1 (oracle/_checks_db.py L35, L64, L92, L120, L174; oracle/_checks_signal.py L32; scenario.py L489). If matches == exactly the 7 known sites: proceed silently. If matches include UNEXPECTED bare-pattern sites beyond the 7 known: STOP and surface via AskUserQuestion with the list of unexpected sites. If matches include FEWER than the 7 known sites: STOP — the line numbers may have drifted, surface via AskUserQuestion. Default behavior on the expected set: log the match list to the implementer's verification log + proceed.

**Test strategy:**

No standalone test in this task — leak detector exercised by Task 6. Terminal states: (a) module imports cleanly via `python -c 'from src.simulation.lifecycle._leak_detector import snapshot_backends, BackendSnapshot, format_delta'`; (b) `snapshot_backends(dsn, application_name_filter='nonexistent_app')` returns BackendSnapshot(total=0, ...) against a running test PG; (c) sibling-search bare-pattern Grep matches exactly the 7 known sites from spec §3.1, or surfaces unexpected sites via AskUserQuestion. Manual recovery-hint smoke: temporarily set max_connections=1 in the test PG (or saturate it), call snapshot_backends, verify the recovery hint appears on stderr and OperationalError is re-raised.

**Scope fence:** Do NOT monkeypatch psycopg2.connect. Do NOT compose with prod_guard. Do NOT add SimpleConnectionPool. Do NOT modify any other file. Do NOT add tests in this task — the regression test is Task 6. Sibling-search is ASSERTIVE (log + AskUserQuestion only on UNEXPECTED bare-pattern sites), NOT ABORTIVE on a count-mismatch alone. Do NOT regress to abortive count-check.

---

### Task 2 — Cursor-with retrofit: oracle/_checks_db.py (5 sites)

**Depends on:** Task 1

**Estimated complexity:** medium

**Files in scope:**
- `src/simulation/lifecycle/oracle/_checks_db.py`

**Files (read-only context):**
- `src/simulation/lifecycle/_leak_detector.py`
- `src/simulation/lifecycle/oracle/_result.py`

**Description:**

Convert 5 cursor sites in src/simulation/lifecycle/oracle/_checks_db.py to `with conn.cursor() as cur:` per spec §3.1. Site #1 L35 (check_attribution: single execute, wrap L35-L42). Site #2 L64 (check_zero_orphans: single execute, wrap L64-L70). Site #3 L92 (check_zero_synthetic_closes: parameterized execute, wrap L92-L100). Site #4 L120 (check_corpus_integrity: TWO executes on SAME cur — wrap MUST span both executes + both fetchone calls, see spec §3.1 special case). Site #5 L174 (canonical_snapshot_hash: cursor REUSED across 3-iteration for-loop — wrap MUST span the entire for-loop body so every cur.execute is inside the `with`, see spec §3.1 special case). Each retrofit ≤ 8 LOC delta. Module docstring, imports, and InvariantResult construction are UNTOUCHED.

**Test strategy:**

Existing tests/simulation/lifecycle/test_oracle.py must remain green. Terminal states: (a) every check still returns InvariantResult with same name/detail format; (b) sites #4 and #5 produce IDENTICAL output to pre-fix (the snapshot hash is determinism-critical — any drift here breaks invariant 9). Verify-by-mutation contract owned by Task 6.

**Scope fence:** Do NOT change InvariantResult field values or names. Do NOT change SQL query text. Do NOT change ORDER BY clauses (invariant 9 determinism is bit-sensitive). Do NOT touch _SNAPSHOT_QUERIES tuple. Do NOT modify _checks_signal.py — that is Task 3. Do NOT modify Oracle.assert_all — that is Task 4. Each individual file change ≤ 30 LOC.

---

### Task 3 — Cursor-with retrofit: _checks_signal.py + scenario.py (2 sites)

**Depends on:** Task 1

**Estimated complexity:** low

**Files in scope:**
- `src/simulation/lifecycle/oracle/_checks_signal.py`
- `src/simulation/lifecycle/scenario.py`

**Files (read-only context):**
- `src/simulation/lifecycle/_leak_detector.py`

**Description:**

Two retrofits in two files. (1) src/simulation/lifecycle/oracle/_checks_signal.py L32 (check_db_open_equals_broker): wrap `cur.execute` + `fetchall` at L32-L38 inside `with conn.cursor() as cur:`. Keep cursor scope tight — do NOT wrap the broker set-comprehension at L39-L41. (2) src/simulation/lifecycle/scenario.py L489 (_fetch_shadow_trade_rows): wrap from L489 through the dict-building loop at L508-L510. Both the conditional execute (L505 vs L507) and the dict-building for-loop must be inside one `with` block.

**Test strategy:**

Existing test_oracle.py and test_scenario.py must remain green. Terminal states: (a) check_db_open_equals_broker still emits identical detail string; (b) _fetch_shadow_trade_rows still returns identical list-of-dicts in identical order.

**Scope fence:** Do NOT wrap the broker set-comprehension (L39-L41 in _checks_signal.py) inside the `with`. Do NOT change SQL text. Do NOT change column tuple `cols` in scenario.py. Do NOT modify _checks_db.py — that is Task 2. Do NOT modify Oracle.assert_all — that is Task 4. Each individual file change ≤ 30 LOC.

---

### Task 4 — Oracle.assert_all() rollback-between-checks

**Depends on:** Task 1

**Estimated complexity:** medium

**Files in scope:**
- `src/simulation/lifecycle/oracle/invariants.py`

**Files (read-only context):**
- `src/simulation/lifecycle/oracle/_checks_db.py`
- `src/simulation/lifecycle/oracle/_checks_signal.py`
- `src/simulation/lifecycle/oracle/_result.py`

**Description:**

Modify src/simulation/lifecycle/oracle/invariants.py L88-L109. Convert the list-of-9 `return [...]` expression into explicit per-check invocations, each wrapped in try/finally with self.conn.rollback() in the finally. Preserves 1..9 order (use the lambda-tuple structure per spec §3.2). Updates the docstring to document the new contract. Oracle.__init__ signature UNTOUCHED. Oracle.assert_all signature UNTOUCHED. Total LOC delta ≤ 25.

**Test strategy:**

Existing test_oracle.py must remain green. Terminal states: (a) assert_all() still returns 9 InvariantResults in 1..9 order; (b) signal-only checks (4, 5, 6, 8) still produce correct results despite no-op rollback after each; (c) if a check itself raises, the `finally` still rolls back and the exception propagates. Add at least one unit test that verifies rollback-is-called-between-checks (instrument self.conn with a counting wrapper — expect count == 9 after assert_all). NOTE: Task 6's PRIMARY inner-mechanism witness directly exercises the cross-check poisoning fix at the integration level — this Task 4 test is the unit-level companion.

**Scope fence:** Do NOT change Oracle.__init__ signature. Do NOT change Oracle.assert_all signature or return type. Do NOT change the 1..9 ORDER. Do NOT change arguments passed to each _checks_db.* / _checks_signal.* call. Do NOT modify _checks_db.py or _checks_signal.py. Do NOT remove the docstring; update it to document rollback-between-checks. LOC delta ≤ 30.

---

### Task 5 — Entrypoint leak-detector hooks (full_gate.py + smoke.py)

**Depends on:** Task 1

**Estimated complexity:** low

**Files in scope:**
- `src/simulation/lifecycle/entrypoints/full_gate.py`
- `src/simulation/lifecycle/entrypoints/smoke.py`

**Files (read-only context):**
- `src/simulation/lifecycle/_leak_detector.py`
- `src/simulation/lifecycle/_bootstrap.py`

**Description:**

Add INFO-level leak-detector diagnostic logging to both entrypoints per spec §3.4. (1) full_gate.py: import _leak_detector; take baseline snapshot AFTER install_prod_guard() but BEFORE _provision_pg; take after snapshot in `finally` AFTER conn.close(); log via existing LOG at INFO level with prefix `[full_gate] conn-leak diagnostic:`. Do NOT raise on growth. Pass `application_name_filter=None` (production logging gets broader signal). (2) smoke.py: same shape; baseline before _truncate_smoke_tables(); after in finally after conn.close(); prefix `[smoke] conn-leak diagnostic:`. Each entrypoint LOC delta ≤ 8.

**Test strategy:**

Verify entrypoints still produce identical FullGateResult/SmokeResult shape. Terminal states: (a) running run_smoke()/run_full_gate() produces an additional log line with the diagnostic; (b) no exception raised by detector on a leaky run; (c) prod_guard sentinel intact. Tested transitively by Task 6.

**Scope fence:** Do NOT change install_prod_guard() call ordering. Do NOT change conn lifecycle. Do NOT raise on detector findings. Do NOT change LOG instance. Do NOT change FullGateResult/SmokeResult shape. Do NOT pass application_name_filter='sim_leak_test' here — that filter belongs to the test, not to production logging.

---

### Task 6 — Regression test: inner-mechanism witness + 3x-loop accumulator (REV-2)

**Depends on:** Task 1, Task 2, Task 3, Task 4, Task 5

**Estimated complexity:** medium

**Files in scope:**
- `tests/simulation/lifecycle/test_no_conn_leak.py`
- `tests/simulation/lifecycle/_oracle_fixtures.py`

**Files (read-only context):**
- `src/simulation/lifecycle/_leak_detector.py`
- `src/simulation/lifecycle/entrypoints/smoke.py`
- `src/simulation/lifecycle/_bootstrap.py`
- `src/simulation/lifecycle/oracle/invariants.py`
- `tests/simulation/lifecycle/test_oracle.py`

**Description:**

Create tests/simulation/lifecycle/test_no_conn_leak.py with TWO tests per spec §3.5 + §3.6.

TEST 1 (PRIMARY) — `test_assert_all_does_not_poison_subsequent_checks`:
  - Constructs an Oracle with a real psycopg2.connect(dsn, application_name='sim_leak_test'), autocommit=False, plus stubbed signal-only collaborators reused from existing test_oracle.py builders (hoist into tests/simulation/lifecycle/_oracle_fixtures.py if the builders are too tightly scoped to the test file — STRICTLY ADDITIVE).
  - Induces aborted-txn state via `cur.execute('SELECT 1 FROM table_that_does_not_exist')` wrapped in `with pytest.raises(psycopg2.errors.UndefinedTable)`.
  - Calls `oracle.assert_all()`.
  - Asserts: len(results) == 9, results[0] and results[1] are not None (proving rollback cleared the aborted state).
  - This is the PRIMARY verify-by-mutation surface per DA1. Mechanism: WITH the fix in invariants.py, assert_all rolls back between checks and clears the induced poisoning. WITHOUT the fix, the first DB-touching check raises InFailedSqlTransaction.

TEST 2 (BACKSTOP) — `test_no_conn_leak_smoke_accumulator`:
  - Sets `os.environ['PGAPPNAME'] = 'sim_leak_test'` BEFORE invoking run_smoke().
  - Takes baseline snapshot via `_leak_detector.snapshot_backends(dsn, application_name_filter='sim_leak_test')`.
  - Runs run_smoke() N times (N = int(os.environ.get('SIM_LEAK_LOOP_ITERATIONS', '3'))).
  - Takes after snapshot via same call.
  - Asserts `delta <= 0` with full diagnostic via format_delta in the message.
  - Docstring documents this is DEFENSIVE BACKSTOP, not the primary witness.

Verify-by-mutation procedure for PRIMARY (MUST be executed by the implementer and pasted into PR body):
  1. git stash the assert_all rewrite from invariants.py (Task 4's work).
  2. Run TEST 1 → expect FAILED with psycopg2.errors.InFailedSqlTransaction on the FIRST DB check.
  3. Capture the failure traceback.
  4. git stash pop.
  5. Re-run TEST 1 → expect PASSED, 9 InvariantResults.
  6. Paste both outputs into PR body.

Verify-by-mutation for BACKSTOP (best-effort, NOT load-bearing):
  1. git stash the 7 cursor retrofits (Tasks 2+3's work).
  2. Run TEST 2. Outcome may be RED (delta > 0) OR GREEN due to GC timing fuzz — log whichever occurs.
  3. git stash pop.
  4. Re-run → expect GREEN.
  5. Paste the GREEN run into PR body. If RED was reproduced in step 2, paste that too.

**Test strategy:**

Boundary-touch tests against real 5434 PG (no mocks). PRIMARY test mutation is mechanically deterministic (stash invariants.py rewrite → InFailedSqlTransaction; restore → 9 results). BACKSTOP test mutation is best-effort. Per feedback_vacuous_test_pattern: NEITHER test uses mock-and-assert-not-called patterns; both exercise real PG semantics. DUAL Opus QA verifies PRIMARY RED+GREEN evidence in PR body. The _oracle_fixtures.py file is created ONLY if reusing test_oracle.py builders requires hoisting; if test_oracle.py exposes them via module-level names already, import directly and skip the hoist.

**Scope fence:** Do NOT mock psycopg2.connect, cursor, or pg_stat_activity. Do NOT use side_effect/assert_not_called patterns. Do NOT skip the PRIMARY verify-by-mutation procedure — PR body MUST contain its RED + GREEN evidence. Do NOT skip setting PGAPPNAME='sim_leak_test' in BACKSTOP test. Do NOT use autocommit=True in PRIMARY test (would mask the bug). Do NOT raise the BACKSTOP threshold above 0. Do NOT modify test_oracle.py — if hoisting fixture builders, create _oracle_fixtures.py and import from BOTH new test AND test_oracle.py (test_oracle.py edit MUST be import-only).

---

### Task 7 — PROD audit document + CHANGELOG + follow-up task filings

**Estimated complexity:** low

**Files in scope:**
- `docs/audits/2026-05-24-sim-conn-lifecycle-leak/audits/2026-05-24-prod-leak-audit.md`
- `CHANGELOG.md`

**Files (read-only context):**
- `src/shadow_trading/bracket_attach.py`
- `src/shadow_trading/broker_exception_logger.py`
- `src/utils/db.py`

**Description:**

(1) Create docs/audits/2026-05-24-sim-conn-lifecycle-leak/audits/2026-05-24-prod-leak-audit.md containing the full PROD audit per spec §6 (PRIMARY findings table with bracket_attach.py:126 + broker_exception_logger.py:51; SECONDARY findings with watch.py:1495; CLEAN findings buckets with sampling-vs-enumeration disclosure; coverage-gap disclosure). Use encoding='utf-8'. (2) Append CHANGELOG.md entry at v0.36.6X per spec §8 sketch — re-baseline at impl time (`git tag --sort=-v:refname | head -3`). (3) File two follow-up tasks: #100-followup-A (bracket_attach.py:126 conn-leak fix) and #100-followup-B (broker_exception_logger.py:51 explicit close). Both at P2 priority.

**Test strategy:**

No automated test — documentation-only deliverable. Terminal states: (a) markdown renders cleanly; (b) two follow-up tasks visible in TaskList; (c) CHANGELOG entry matches re-baselined v0.36.6X version. Reviewer verifies bracket_attach.py:126 and broker_exception_logger.py:51 line refs against live files.

**Scope fence:** Do NOT modify bracket_attach.py or broker_exception_logger.py — DOCUMENT-ONLY per requirements. Do NOT modify utils/db.py — read-only. Do NOT bundle the bracket_attach fix — file as #100-followup-A. Use encoding='utf-8' explicitly (Windows UTF-8 gotcha per operator memory).

---

