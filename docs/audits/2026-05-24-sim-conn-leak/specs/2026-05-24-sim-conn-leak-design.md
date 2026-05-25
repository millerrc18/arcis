# #100 — Sim Test-Harness Connection-Lifecycle Leak Fix (REV-2)

## 1. Overview

### 1.1 Problem statement
Running `src/simulation/lifecycle/entrypoints/full_gate.py` (or `smoke.py`) back-to-back against the ephemeral 5434 test Postgres accumulates **idle-in-txn / idle-stale** backends. After enough iterations the test PG reaches `max_connections=100` (docker-compose.test.yml default) and wedges. This blocks the iterative simulator dev loop and — more importantly — makes the **STABLE verdict from #97's full gate untrustworthy across N back-to-back runs**.

### 1.2 Role in the roadmap
- Gates **#95 clean-slate wipe**. The wipe is gated on a trustworthy sim STABLE verdict; if the sim wedges mid-cycle, STABLE means nothing.
- Closes Phase-2 of the W21 completion roadmap (operator order 2026-05-22).
- Document-only PROD audit surfaces two latent leak risks (`bracket_attach.py:126`, `broker_exception_logger.py:51`) that will be filed as separate future tasks (NOT fixed in this PR — per requirements).

### 1.3 Root-cause summary (clarified for REV-2 per DA1)
The **primary** mechanism is **cross-check poisoning within ONE invocation of `Oracle.assert_all()`**:
- 7 cursor sites use the bare pattern `cur = conn.cursor()` without `with` and without `cur.close()`. When a check raises mid-execute, the cursor stays referenced and the txn stays in `idle in transaction (aborted)` state on `self.conn`.
- `Oracle.assert_all()` shares the same `self.conn` across 9 invariant checks **without rollback between them** — so a half-aborted state from check N raises `InFailedSqlTransaction` on the FIRST `cur.execute(...)` of check N+1.
- **The bug surfaces within a single assert_all() call.** Test N+1 sees the poisoning from test N's leftover state.

The **secondary** symptom is cross-run backend accumulation:
- Across back-to-back gate runs, Python-side cursor refs can keep the conn-wrapper object alive past the entrypoint `finally`'s `close()`, and PG's backend can linger as `idle (aborted)` until the GC chain releases the conn. Whether this happens deterministically depends on Python ref-counting and pytest fixture teardown order — it is **mechanism-fuzzy** and not a reliable witness for the bug itself.

The fix is two-part and **minimally invasive**:
1. Retrofit 7 cursor sites to `with conn.cursor() as cur:` — psycopg2 ≥ 2.5 closes the cursor on context exit even when the inner block raises.
2. Wrap each invariant call in `Oracle.assert_all()` in `try/finally` with `self.conn.rollback()` in the `finally` — guaranteeing the shared conn is in a clean transaction state before each subsequent check.

### 1.4 What this PR is NOT
- Not a refactor of `Oracle` (`assert_all` still takes a shared `self.conn`; signature unchanged).
- Not a connection-pool introduction (no `psycopg2.pool.SimpleConnectionPool`).
- Not a PROD code change (PROD audit findings filed as separate future tasks; PROD watch-loop conn-pool behavior is **identical** after this PR).
- Not a `prod_guard` rewrite (sentinel + monkeypatch untouched; new leak detector uses a dedicated short-lived conn so there is zero composition surface with `prod_guard`).

---

## 2. Architecture

### 2.1 Components
```
src/simulation/lifecycle/
├── oracle/
│   ├── _checks_db.py            [MODIFY] 5 cursor sites → `with` (L35, L64, L92, L120, L174)
│   ├── _checks_signal.py        [MODIFY] 1 cursor site → `with` (L32)
│   └── invariants.py            [MODIFY] Oracle.assert_all() rollback-between-checks
├── scenario.py                  [MODIFY] 1 cursor site → `with` (L489)
├── entrypoints/
│   ├── full_gate.py             [MODIFY] leak-detector snapshot hooks
│   └── smoke.py                 [MODIFY] leak-detector snapshot hooks
└── _leak_detector.py            [NEW] pure-query helper (pg_stat_activity)

tests/simulation/lifecycle/
└── test_no_conn_leak.py         [NEW] inner-mechanism witness + 3x-loop accumulator test

docs/audits/2026-05-24-sim-conn-lifecycle-leak/
└── audits/2026-05-24-prod-leak-audit.md   [NEW] document-only PROD audit
```

### 2.2 Leak detector design (pure-query helper, no monkeypatch)
The leak detector is a **pure-query helper**: it opens its own dedicated short-lived conn via `psycopg2.connect(dsn, application_name='sim_leak_observer')`, issues a single `SELECT … FROM pg_stat_activity`, returns a `BackendSnapshot` dataclass, and closes the conn on exit. **It does NOT monkeypatch `psycopg2.connect`.** It does NOT compose with `prod_guard.install_prod_guard()` — composition surface is zero because there is no wrapping. The detector's own conn is filtered out of the count via `pid <> pg_backend_pid()` AND by the application_name filter described in §2.5.

The canonical signal is **TOTAL client-backend count for `application_name='sim_leak_test'`** (not idle-in-txn count). Rationale: `smoke.py` runs with `autocommit=True` so idle-in-txn is structurally 0 there; total backend count covers both entrypoints uniformly. The `state` breakdown is surfaced in the diagnostic string for debugging only.

### 2.3 Cursor-with semantics quirk (called out explicitly so no future reader misses)
- `with conn.cursor() as cur:` — closes the cursor on exit (whether success or exception). This is what we want.
- `with conn:` — commits or rolls back the **transaction** on exit (psycopg2's context-manager protocol on the Connection object). It does NOT close the conn.
These are different. The fix uses **cursor**-with, not conn-with.

### 2.4 Where the leak-detector snapshot hooks land
- `full_gate.py`: snapshot BEFORE `_provision_pg` (baseline), snapshot AFTER `conn.close()` in the `finally` (post-run). Log the delta at INFO level via `LOG`. **Do not raise on growth** — production entrypoints stay non-failing; the test asserts. Pass `application_name_filter=None` so production logging snapshots show ALL backends (broader signal for ops triage).
- `smoke.py`: same shape.
- Both entrypoints use `_bootstrap.SIM_DATABASE_URL` for the detector's dsn.

### 2.5 Single-tenant isolation via `application_name` (REV-2, per DA3)
Multiple developers and CI jobs share the 5434 test PG. Counting **all** client backends produces false positives (other psql sessions) and false negatives (other devs' disconnects masking a real leak). REV-2 introduces single-tenant filtering:

- **The regression test** sets `os.environ['PGAPPNAME'] = 'sim_leak_test'` BEFORE invoking `run_smoke()`. libpq honours `PGAPPNAME` on every `psycopg2.connect()` that does not explicitly override it — so EVERY conn opened by the smoke entrypoint (and by anything smoke calls) carries `application_name='sim_leak_test'`.
- **The detector** accepts an optional `application_name_filter: str | None` parameter. When passed, the `pg_stat_activity` query adds `AND application_name = %s`. The regression test passes `application_name_filter='sim_leak_test'`. Production entrypoints pass `None` (broader logging signal).
- **The detector's own conn** advertises `application_name='sim_leak_observer'` (different from the test's 'sim_leak_test'), so even without `pid <> pg_backend_pid()` filtering, the detector's measurement conn would not falsely inflate the test's leak count. The `pid <> pg_backend_pid()` filter remains as a belt-and-braces redundancy.

This makes the snapshot count single-tenant to backends spawned by THIS test, regardless of concurrent psql sessions or parallel CI jobs.

---

## 3. Per-Fix Detailed Specification

### 3.1 The 7 cursor-with retrofits (≤30 LOC each, minimal-invasive)

| # | File | Line | Pattern | Wrap range |
|---|---|---|---|---|
| 1 | `oracle/_checks_db.py` | L35 | single `cur.execute` + `fetchall` | L35–L42 inside `with` |
| 2 | `oracle/_checks_db.py` | L64 | single `cur.execute` + `fetchall` | L64–L70 inside `with` |
| 3 | `oracle/_checks_db.py` | L92 | single `cur.execute` (parameterized) + `fetchall` | L92–L100 inside `with` |
| 4 | `oracle/_checks_db.py` | L120 | **TWO executes on SAME cursor** (L121 + L126), each followed by `fetchone()` | wrap **spans BOTH** executes |
| 5 | `oracle/_checks_db.py` | L174 | cursor **REUSED across for-loop** (L175–L188) — execute + fetchall **per iteration** | wrap **spans entire for-loop body** |
| 6 | `oracle/_checks_signal.py` | L32 | single `cur.execute` + `fetchall` | L32–L38 inside `with`. Keep cursor scope tight — do **NOT** wrap the broker set-comprehension at L39–L41 (it does not touch `cur`). |
| 7 | `scenario.py` | L489 | conditional `cur.execute` (L505 vs L507 depending on `status` filter), then dict-building loop | wrap from L489 through the dict-building loop at L508–L510 inside `with`. Both the conditional execute and the loop must be inside one `with`. |

**Special cases:**
- **Site #4 (L120)**: Both `cur.execute(...)` calls must share the SAME cursor.
  ```python
  with conn.cursor() as cur:
      cur.execute("SELECT COUNT(*) FROM training_examples ... ")
      measured = cur.fetchone()[0]
      cur.execute("SELECT COUNT(*) FROM model_versions")
      models = cur.fetchone()[0]
  ```
- **Site #5 (L174)**: The `with` block must span the entire `for` body.
  ```python
  hasher = hashlib.sha256()
  with conn.cursor() as cur:
      for table, order_cols, value_cols in _SNAPSHOT_QUERIES:
          ...
          cur.execute(f"SELECT {cols} FROM {table} ORDER BY {order_by}")
          hasher.update(f"::{table}::".encode())
          for row in cur.fetchall():
              ...
  ```

### 3.2 Oracle.assert_all() rollback-between-checks

`src/simulation/lifecycle/oracle/invariants.py` L88–L109. Convert to explicit per-call try/finally with `self.conn.rollback()`:

```python
def assert_all(self) -> list[InvariantResult]:
    """Run every invariant and return its InvariantResult, in 1..9 order.

    Each check runs inside a try/finally that rolls back `self.conn` on exit,
    so a check failure (or an InFailedSqlTransaction state from the prior
    check) does not poison the next check. Rollback on a clean / unstarted
    transaction is a no-op in psycopg2, so signal-only checks are unaffected.
    """
    results: list[InvariantResult] = []
    invocations = (
        lambda: _checks_db.check_attribution(self.conn),
        lambda: _checks_db.check_zero_orphans(self.conn),
        lambda: _checks_db.check_zero_synthetic_closes(self.conn),
        lambda: _checks_signal.check_db_open_equals_broker(
            self.conn, self.fake_trading_client),
        lambda: _checks_signal.check_capital_conservation(
            self.capital_ledger, self.db_reported_pnl),
        lambda: _checks_signal.check_honest_metrics(
            self.capital_ledger, self.marks,
            self.governor_drawdown_pct, self.observer),
        lambda: _checks_db.check_corpus_integrity(self.conn),
        lambda: _checks_signal.check_no_wedged_processes(
            self.pidfile, self.pidfile_identity),
        lambda: _checks_db.check_deterministic_reproducibility(self.conn),
    )
    for invoke in invocations:
        try:
            results.append(invoke())
        finally:
            self.conn.rollback()
    return results
```

### 3.3 Leak detector helper Python API (REV-2)

**File:** `src/simulation/lifecycle/_leak_detector.py` (NEW).

**Six-line module header:**
```python
"""Pure-query helper that snapshots pg_stat_activity for leak detection.

Called by: src.simulation.lifecycle.entrypoints.{full_gate,smoke},
  tests/simulation/lifecycle/test_no_conn_leak.py
Calls: psycopg2.connect (pure read; does NOT monkeypatch and does NOT
  compose with prod_guard — uses its own short-lived dedicated conn).
Owns tables: none.
Config keys: none (dsn is passed in).
Tests: tests/simulation/lifecycle/test_no_conn_leak.py.
"""
```

**Public surface (≤120 LOC total with REV-2 additions):**
```python
from __future__ import annotations

import sys
from dataclasses import dataclass

import psycopg2

# Substrings PG uses for connection exhaustion (PG ≥ 9.6).
_TOO_MANY_CLIENTS_MARKERS = (
    "too many clients",
    "sorry, too many connections",
)

_RECOVERY_HINT = (
    "[leak_detector] Test PG appears to be at max_connections. "
    "This is the exact condition #100 fixes; the diagnostic conn cannot "
    "be opened. Recover via one of:\n"
    "  (a) docker exec halcyon-pg-test psql -U test -d halcyon -c \""
    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
    "WHERE datname='halcyon' AND pid <> pg_backend_pid()\"\n"
    "  (b) docker-compose -f docker-compose.test.yml down -v && "
    "docker-compose -f docker-compose.test.yml up -d\n"
)


@dataclass(frozen=True)
class BackendSnapshot:
    """Immutable point-in-time pg_stat_activity reading."""
    total: int
    by_state: dict[str, int]
    sample_pids: tuple[int, ...]


def snapshot_backends(
    dsn: str,
    datname: str = "halcyon",
    application_name_filter: str | None = None,
) -> BackendSnapshot:
    """Open a short-lived conn, query pg_stat_activity, close, return snapshot.

    Filters:
      - datname = the sim DB name
      - backend_type = 'client backend' (excludes WAL writer / autovacuum)
      - pid != pg_backend_pid() (excludes the measuring conn itself)
      - if `application_name_filter` is not None, AND application_name = it
        (single-tenant isolation for the regression test; see §2.5)

    Raises:
      psycopg2.OperationalError on any connect failure. If the failure is
      a connection-exhaustion (the exact condition #100 fixes), a recovery
      hint is printed to stderr BEFORE the exception propagates, so the
      operator sees an actionable message instead of a bare stack.
    """
    sql_parts = [
        "SELECT pid, state",
        "FROM pg_stat_activity",
        "WHERE datname = %s",
        "  AND backend_type = 'client backend'",
        "  AND pid <> pg_backend_pid()",
    ]
    params: list = [datname]
    if application_name_filter is not None:
        sql_parts.append("  AND application_name = %s")
        params.append(application_name_filter)
    sql = "\n".join(sql_parts)

    try:
        conn = psycopg2.connect(dsn, application_name="sim_leak_observer")
    except psycopg2.OperationalError as err:
        msg = str(err).lower()
        if any(marker in msg for marker in _TOO_MANY_CLIENTS_MARKERS):
            print(_RECOVERY_HINT, file=sys.stderr, flush=True)
        raise

    try:
        with conn.cursor() as cur:
            cur.execute(sql, tuple(params))
            rows = cur.fetchall()
    finally:
        conn.close()

    by_state: dict[str, int] = {}
    pids: list[int] = []
    for pid, state in rows:
        key = state or "unknown"
        by_state[key] = by_state.get(key, 0) + 1
        pids.append(pid)
    return BackendSnapshot(
        total=len(rows),
        by_state=by_state,
        sample_pids=tuple(pids[:8]),
    )


def format_delta(before: BackendSnapshot, after: BackendSnapshot) -> str:
    """Render a single-string human-readable diagnostic."""
    delta = after.total - before.total
    states = sorted({*before.by_state, *after.by_state})
    state_lines = [
        f"  {s}: {before.by_state.get(s, 0)} -> {after.by_state.get(s, 0)}"
        for s in states
    ]
    return (
        f"backends: {before.total} -> {after.total} (delta {delta:+d})\n"
        + "\n".join(state_lines)
        + f"\n  sample_pids_after: {list(after.sample_pids)}"
    )
```

**Notable REV-2 changes:**
- (DA3) Added `application_name_filter` parameter; detector's own conn advertises `application_name='sim_leak_observer'` (distinct from the test's `sim_leak_test`).
- (DA4) Wrapped `psycopg2.connect(...)` in try/except `OperationalError`. On too-many-clients markers, the recovery hint is printed to stderr before re-raising. Operators see actionable commands, not a bare stack.
- Switched from `with psycopg2.connect(dsn) as conn:` to explicit `connect` + try/finally `close()`, so the exception handler can fire BEFORE the context manager engages (context-manager exit on an unopened conn would itself raise).

**Composition with prod_guard:** zero (unchanged).

### 3.4 Entrypoint hooks

**`full_gate.py`**:
```python
def run_full_gate() -> FullGateResult:
    install_prod_guard()
    dsn = _bootstrap.SIM_DATABASE_URL
    baseline = _leak_detector.snapshot_backends(dsn)  # no filter — broad ops signal
    conn = _provision_pg(dsn)
    try:
        runner = ScenarioRunner(conn=conn, start=_FULL_GATE_START, sim_dsn=dsn)
        scenario = runner.run(days=_FULL_GATE_DAYS)
    finally:
        conn.rollback()
        conn.close()
        after = _leak_detector.snapshot_backends(dsn)
        LOG.info(
            "[full_gate] conn-leak diagnostic:\n%s",
            _leak_detector.format_delta(baseline, after),
        )
    ...
```
Note: detector does NOT raise on growth — it logs only.

**`smoke.py`** — analogous shape; baseline before `_truncate_smoke_tables()`, after taken in `finally` after `conn.close()`. Same log call, prefixed `[smoke]`.

### 3.5 Regression test — outer 3x-loop accumulator (REV-2 positioning)

`tests/simulation/lifecycle/test_no_conn_leak.py` contains TWO tests. This subsection describes the **outer accumulator backstop**. §3.6 describes the **inner-mechanism witness** (the primary verify-by-mutation surface per DA1).

**Outer test contract:**
```python
def test_no_conn_leak_smoke_accumulator():
    """Run smoke 3x back-to-back; assert zero net backend growth.

    Positioning (REV-2 per DA1): DEFENSIVE BACKSTOP. The PRIMARY witness
    for the bug is test_assert_all_does_not_poison_subsequent_checks below,
    which directly exercises the cross-check poisoning mechanism within ONE
    assert_all() call. This 3x outer-loop test catches the SECONDARY symptom
    — cross-run backend accumulation — IF Python-side ref-keeping prevents
    full conn GC between iterations. Since that mechanism is fuzzy, this
    test's RED-when-mutated property is best-effort, not load-bearing.
    Treat as a regression smoke test for the broader leak surface.
    """
    os.environ["PGAPPNAME"] = "sim_leak_test"  # libpq picks this up
    dsn = _bootstrap.SIM_DATABASE_URL
    iterations = int(os.environ.get("SIM_LEAK_LOOP_ITERATIONS", "3"))

    baseline = _leak_detector.snapshot_backends(
        dsn, application_name_filter="sim_leak_test"
    )
    for _ in range(iterations):
        run_smoke()
    after = _leak_detector.snapshot_backends(
        dsn, application_name_filter="sim_leak_test"
    )

    delta = after.total - baseline.total
    assert delta <= 0, (
        f"PG backend leak detected across {iterations} runs:\n"
        + _leak_detector.format_delta(baseline, after)
    )
```

**Threshold rationale:** `delta <= 0` (STRICT). Filtered by `application_name='sim_leak_test'` so concurrent psql sessions and parallel CI jobs do NOT confound the count.

**Why smoke and not full_gate:** smoke ~15s, full_gate ~90s. 3 iterations of smoke fits the lifecycle-smoke CI 600s budget; full_gate would not. The leak surfaces in both paths.

**Stress-mode opt-in:** `SIM_LEAK_LOOP_ITERATIONS=10` for manual/nightly stress runs.

### 3.6 Inner-mechanism witness test (NEW, primary verify-by-mutation per DA1)

The inner test directly exercises the bug's actual mechanism — cross-check poisoning of `self.conn` within ONE `Oracle.assert_all()` invocation — without relying on cross-iteration backend persistence or Python GC timing.

**Test contract:**
```python
def test_assert_all_does_not_poison_subsequent_checks(tmp_path):
    """WITNESS for the bug's actual mechanism per spec §1.3.

    Bug: `Oracle.assert_all()` shares `self.conn` across 9 invariants WITHOUT
    rollback between them. If check N raises mid-cur.execute, `self.conn` is
    left in `idle in transaction (aborted)` state. Check N+1's first execute
    then raises `InFailedSqlTransaction`.

    Fix: try/finally with `self.conn.rollback()` after each check (§3.2).

    Verify-by-mutation procedure:
      1. Stash the assert_all() try/finally rewrite from invariants.py.
      2. Run this test → expect FAILED with InFailedSqlTransaction
         on the second check.
      3. Restore the fix.
      4. Re-run → expect PASSED, both checks complete.
    """
    import psycopg2
    from psycopg2 import errors as pg_errors

    from src.simulation.lifecycle import _bootstrap
    from src.simulation.lifecycle.oracle import invariants as inv_mod

    dsn = _bootstrap.SIM_DATABASE_URL
    conn = psycopg2.connect(dsn, application_name="sim_leak_test")
    conn.autocommit = False  # MUST be False so aborted-txn state is visible

    try:
        # Construct a minimal Oracle with the real conn but stub the 5
        # signal-only collaborators we don't exercise here. The two DB
        # checks we will invoke (check_attribution, check_zero_orphans)
        # do their own SELECT against `self.conn`.
        oracle = _build_oracle_with_real_conn_and_stub_signals(
            conn=conn,
            fake_trading_client=_FakeTradingClient(),
            tmp_path=tmp_path,
        )

        # Force an aborted-txn state by issuing a deliberately-failing
        # SELECT against `oracle.conn`. This simulates what happens when
        # an invariant check's cur.execute(...) raises mid-flight without
        # `with` cleanup.
        with pytest.raises(psycopg2.errors.UndefinedTable):
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM table_that_does_not_exist")
        # `conn` is now in `idle in transaction (aborted)` state.

        # WITHOUT the fix (assert_all without per-check rollback): the
        # next check raises InFailedSqlTransaction.
        # WITH the fix: assert_all rolls back self.conn between checks,
        # so the deliberate poisoning is cleared and both checks complete.
        results = oracle.assert_all()

        assert len(results) == 9
        # Specifically: check 1 (attribution) is the first one that
        # actually executes SQL against self.conn. If the fix is absent
        # AND the rollback isn't happening, it would have raised
        # InFailedSqlTransaction here.
        assert results[0] is not None
        assert results[1] is not None
    finally:
        conn.close()


def _build_oracle_with_real_conn_and_stub_signals(*, conn, fake_trading_client, tmp_path):
    """Construct Oracle with the real conn + stubbed non-DB collaborators.

    The non-DB args (capital_ledger, marks, governor_drawdown_pct,
    observer, pidfile, pidfile_identity, db_reported_pnl) are filled with
    minimal valid stubs whose only job is to let the signal-only checks
    return InvariantResult objects without raising. The DB-touching checks
    (1, 2, 3, 7, 9) operate against the real conn.
    """
    # Implementation detail: minimal stubs constructed from the existing
    # test fixtures in test_oracle.py. Reuse those builders rather than
    # re-defining shapes inline.
    ...
```

**Notes for the implementer:**
- The exact stub construction MUST be derived from the existing `tests/simulation/lifecycle/test_oracle.py` fixtures. Reuse the existing `_capital_ledger`, `_marks`, `_observer`, etc. builders rather than re-inventing them. If those builders are tightly scoped to that test file, hoist them into a shared `tests/simulation/lifecycle/_oracle_fixtures.py` helper (additive only).
- `autocommit=False` is REQUIRED so the aborted-txn state is observable. With `autocommit=True`, every statement is its own txn and the bug cannot manifest.
- The `psycopg2.errors.UndefinedTable` poisoning is a deliberate harness mechanism; it is NOT the actual bug. The actual bug is invariant cleanup; we induce the same poisoned-state precondition deterministically.

**Why this is the primary witness (per DA1):**
- It exercises the EXACT mechanism described in §1.3 — cross-check poisoning of `self.conn`.
- It does NOT depend on cross-process backend persistence, Python GC timing, or pytest fixture teardown order.
- The mutation-revert test (stash invariants.py rewrite → test fails) is mechanically deterministic, not probabilistic.

---

## 4. Cross-Cutting Standards (per requirements)

| Standard | Application |
|---|---|
| `encoding='utf-8'` on every file open | All new files: no `open()` calls in detector or tests. The PROD-audit doc is markdown only. Enforce defensively in any future helper. |
| `127.0.0.1` not `localhost` | `_leak_detector.snapshot_backends` takes a DSN; the sim DSN is already `127.0.0.1:5434`. No new literal hostnames. |
| Six-line module-header convention | Applied to `_leak_detector.py` and `test_no_conn_leak.py`. |
| psycopg2 ≥ 2.5 for cursor-with | requirements.txt L33 `psycopg2-binary>=2.9,<3.0` — satisfied. |
| ≤30 LOC per file change | Each cursor retrofit 3–8 LOC; `assert_all()` rewrite ~25 LOC delta; entrypoint hooks ~8 LOC each. |
| `prod_guard` sentinel untouched | Detector does NOT monkeypatch; `prod_guard.py` is bit-for-bit identical post-PR. |
| Oracle signature preserved | `Oracle.__init__` and `Oracle.assert_all` keep the shared-conn contract. |
| No `psycopg2.pool.SimpleConnectionPool` | Single short-lived conns only. |
| No PROD code changes | All modifications inside `src/simulation/lifecycle/**`. PROD findings document-only. |
| Single-tenant isolation (REV-2) | `application_name='sim_leak_test'` set via `PGAPPNAME` env in the test; detector filters by it; isolates from concurrent psql / CI jobs. |
| Detector graceful fail under max_connections (REV-2) | Detector prints actionable recovery hint to stderr on `OperationalError` matching too-many-clients markers, then re-raises. |

---

## 5. Testing Strategy

### 5.1 Real PG (boundary-touch per `feedback_vacuous_test_pattern`)
Both tests connect to **real 5434 PG** (no mocks). They exercise the full smoke entrypoint and the real `pg_stat_activity`/`InFailedSqlTransaction` semantics. No mock of `psycopg2.connect`, no `_not_called` assertions.

### 5.2 Verify-by-mutation contract (REV-2 per DA1, DA4)

| Test | Mutation procedure | Expected RED | Expected GREEN |
|---|---|---|---|
| **PRIMARY — `test_assert_all_does_not_poison_subsequent_checks` (§3.6)** | Stash the try/finally rewrite in `invariants.py`. The cursor retrofits in `_checks_db.py` are irrelevant to this test (it induces poisoning directly via UndefinedTable). | `psycopg2.errors.InFailedSqlTransaction` raised inside `oracle.assert_all()` on the FIRST DB check after the induced poisoning. | All 9 InvariantResults returned, no exception. |
| **BACKSTOP — `test_no_conn_leak_smoke_accumulator` (§3.5)** | Stash the 7 cursor retrofits in `_checks_db.py`, `_checks_signal.py`, `scenario.py`. | `delta > 0` after 3 iterations (best-effort — may not always reproduce due to GC timing; if test passes when fix is reverted, log it but do NOT treat as test failure). | `delta <= 0` after 3 iterations. |
| **TERMINAL — ERROR-conn-exhausted (§5.5)** | Trigger by saturating the test PG to max_connections (e.g., open 100 idle psql sessions) before running. | `OperationalError` re-raised AFTER recovery-hint stderr line printed. | N/A — this is a degraded-state diagnostic; not a CI-gated state. |

The PR description and the implementer's verification log MUST include the PRIMARY test's RED-then-GREEN evidence as the load-bearing witness. The BACKSTOP test's RED evidence is captured if reproducible, but its absence does NOT block merge — the primary witness is sufficient.

DUAL-Opus QA must verify the PRIMARY evidence exists and the inner mechanism is correctly exercised.

### 5.3 Determinism preserved
The canonical snapshot hash (invariant 9) is sensitive to row order. The cursor-with retrofit at site #5 (L174) preserves the SAME cursor across the for-loop, so the hash output is bit-identical before/after. Reviewer verifies via existing `test_determinism.py`.

### 5.4 Test infrastructure decisions
- **No new conftest hoist required for `pg_conn` fixture.** Both new tests manage their own conn lifecycle.
- **Optional**: hoist `_oracle_fixtures.py` if the inner-mechanism test needs builders from `test_oracle.py`. Strictly additive; no existing-test changes.
- The test file lives at `tests/simulation/lifecycle/test_no_conn_leak.py`. No `conftest.py` modification.

### 5.5 Terminal states (REV-2 per DA4)

| Outcome | Cause | Diagnostic |
|---|---|---|
| PASS, primary test green | Rollback-between-checks correctly inserted | Test green; inner mechanism witnessed |
| PASS, accumulator test green | All 7 cursor sites + rollback correct | Backstop confirms broader leak surface clean |
| FAIL, InFailedSqlTransaction | `assert_all` rollback dropped | Primary test surfaces the exact mechanism in the failing line |
| FAIL, delta > 0 in accumulator | Cursor site reverted (possibly) | Diagnostic prints `before -> after` + per-state breakdown + sample pids |
| ERROR, OperationalError (general) | 5434 PG unreachable | Standard pytest error |
| **ERROR-conn-exhausted (NEW)** | Test PG at max_connections when detector tries to connect | Recovery hint printed to stderr BEFORE the exception propagates: (a) `pg_terminate_backend(pid) ...` SQL command; (b) `docker-compose -f docker-compose.test.yml down -v && up -d` container recreate. Then `OperationalError` re-raised. Operator sees actionable commands, not a bare stack. |

---

## 6. PROD AUDIT TABLE (Document-Only — Filed as Separate Future Tasks)

Per requirements: **no PROD code changes in this PR.** Each PRIMARY finding becomes a separate future task.

### 6.1 PRIMARY findings (real leak risk)

| File:Line | Pattern | Risk class | Future-task action |
|---|---|---|---|
| `src/shadow_trading/bracket_attach.py:126` | `conn = connect_db(db_path)` at L126; `try:` at L128 with empty `finally: pass`; `conn.close()` at L244 OUTSIDE the try/finally | LEAK on exception path | File as **#100-followup-A**: convert to `with closing(connect_db(db_path)) as conn:` |
| `src/shadow_trading/broker_exception_logger.py:51` | `conn = connect_db(**kwargs)` at L51; `with conn:` at L52 | AMBIGUOUS / readable as leak | File as **#100-followup-B**: make close discipline explicit |

### 6.2 SECONDARY findings (partial coverage)

| File:Line | Pattern | Status |
|---|---|---|
| `src/scheduler/watch.py:1495` (`_check_row_counts`) | Bare conn + manual `close()` on success, NO close on except branch | PARTIAL. Add to **#100-followup-C** (P3, batch with watch.py audit) |

### 6.3 CLEAN findings (already leak-proof — sampled or enumerated)

**With-pattern bucket (sampling):** relied on `PostgresConnectionWrapper.__exit__` contract at utils/db.py L549–L555.
- `src/shadow_trading/reconcile.py` — 14 sites, all `with connect_db(...)`.
- `src/shadow_trading/executor.py` — 10 sites, all `with connect_db(...)`.
- `src/journal/store.py` — 17 sites, all `with connect_db(...)`.
- `src/council/*` — all sites use `with`.
- `src/scheduler/watch.py` _run_scan sites — all `with` pattern.

**Bare-conn-with-try/finally bucket (enumerated):**
- `src/capability_registration.py:40`, `src/state.py:46`, `src/reconcile_state.py:34`, `src/exit_reconciliation.py:307`, `src/scheduler/watch.py` walkforward helpers (L2663, L2701, L2743) — all CLEAN.

### 6.4 Coverage gap (disclosed)
The with-pattern bucket is **sampled**, not exhaustively traced. Sampling relies on `PostgresConnectionWrapper.__exit__` (utils/db.py L549–L555). If a future change weakens that wrapper's contract, the sampling assumption no longer holds.

---

## 7. Design-Decision Summary (preview — full table in `design_decisions`)

| ID | Decision | Chosen | Rationale |
|---|---|---|---|
| DD-1 | Leak detector composition | Pure-query helper, no monkeypatch | Zero composition surface with `prod_guard` |
| DD-2 | Fix strategy at the 7 sites | `with conn.cursor() as cur:` retrofit | Minimal-invasive; preserves Oracle signature |
| DD-3 | Rollback-between-checks | try/finally per call in `assert_all` | Preserves 1..9 order; no-op on signal-only checks |
| DD-4 | Loop default + stress mode | 3 default, env-override for ≥10 | Fits CI budget |
| DD-5 | Canonical leak signal | TOTAL client backends + `application_name` filter | Smoke is autocommit=True → idle-in-txn structurally 0; app-name filter isolates from concurrent users |
| DD-6 | conftest pg_conn hoist | NOT hoisted | New tests manage their own conn lifecycle |
| DD-7 | PROD audit treatment | Document-only, separate future tasks | Per operator requirements |
| DD-8 | bracket_attach.py fix timing | Future task #100-followup-A | Per operator requirements |
| **DD-9 (NEW)** | **Inner-mechanism witness test** | **Direct cross-check-poisoning test as primary; 3x loop as backstop** | **DA1: cross-iter mechanism is GC-fuzzy; cross-check mechanism is the actual bug** |
| **DD-10 (NEW)** | **Single-tenant isolation via application_name** | **`PGAPPNAME=sim_leak_test` + detector filter** | **DA3: prevents concurrent psql / CI from confounding the snapshot** |
| **DD-11 (NEW)** | **Detector graceful-fail under max_connections** | **Wrap connect in try/except, print recovery hint to stderr, re-raise** | **DA4: diagnostic must be usable in the exact failure mode it diagnoses** |

---

## 8. CHANGELOG Sketch (v0.36.6X — version re-baselined at impl time)

```
## v0.36.6X — 2026-05-XX

### Fixed
- sim test-harness: connection-lifecycle leak (#100). Back-to-back smoke /
  full_gate runs no longer accumulate idle-in-txn / idle-stale PG backends.
  Primary fix: Oracle.assert_all() now rolls back self.conn in a try/finally
  per invariant, so a half-aborted transaction from check N cannot poison
  check N+1. Secondary fix: 7 cursor sites in oracle/_checks_db.py,
  oracle/_checks_signal.py, and scenario.py converted to
  `with conn.cursor() as cur:`.

### Added
- src/simulation/lifecycle/_leak_detector.py — pure-query helper that
  snapshots pg_stat_activity. Supports `application_name_filter` for
  single-tenant isolation. Prints operator-readable recovery hint to
  stderr when the test PG is at max_connections (the exact failure mode
  the helper is designed to diagnose).
- tests/simulation/lifecycle/test_no_conn_leak.py — inner-mechanism
  witness test (PRIMARY) + 3x-loop accumulator backstop. Env var
  SIM_LEAK_LOOP_ITERATIONS opts the backstop into stress mode.
- docs/audits/2026-05-24-sim-conn-lifecycle-leak/ — PROD code-path audit
  (document-only). Two follow-up tasks filed: #100-followup-A, -B.

### Unchanged (explicit)
- PROD watch-loop conn pool behavior is bit-for-bit identical.
- `prod_guard.install_prod_guard()` sentinel and monkeypatch untouched.
- `Oracle` signature is unchanged.
```

---

## 9. Acceptance Criteria

- [ ] All 7 cursor sites use `with conn.cursor() as cur:` — exact line ranges per §3.1.
- [ ] `Oracle.assert_all()` wraps each invariant call in try/finally with `self.conn.rollback()`.
- [ ] `_leak_detector.py` exists with `BackendSnapshot`, `snapshot_backends(dsn, datname, application_name_filter=None)`, `format_delta`.
- [ ] Detector's `snapshot_backends` opens its conn with `application_name='sim_leak_observer'`.
- [ ] Detector wraps `psycopg2.connect` in try/except `OperationalError`; on too-many-clients markers prints recovery hint to stderr then re-raises.
- [ ] `full_gate.py` and `smoke.py` invoke `snapshot_backends` before run + after `conn.close()`; log delta at INFO. Production calls pass `application_name_filter=None`.
- [ ] `tests/simulation/lifecycle/test_no_conn_leak.py` contains BOTH `test_assert_all_does_not_poison_subsequent_checks` (PRIMARY) AND `test_no_conn_leak_smoke_accumulator` (BACKSTOP).
- [ ] Primary test sets `PGAPPNAME=sim_leak_test`; both tests pass `application_name_filter='sim_leak_test'` when calling the detector.
- [ ] Verify-by-mutation evidence in PR body: PRIMARY test RED (stash invariants.py rewrite → InFailedSqlTransaction) + PRIMARY test GREEN (restore → 9 InvariantResults).
- [ ] PROD audit document committed at `docs/audits/2026-05-24-sim-conn-lifecycle-leak/audits/2026-05-24-prod-leak-audit.md`.
- [ ] Two follow-up tasks filed (#100-followup-A, #100-followup-B).
- [ ] `prod_guard.py` diff is empty (bit-for-bit).
- [ ] `Oracle.__init__` signature unchanged; `assert_all` signature unchanged.
- [ ] Determinism witness: `test_determinism.py` / `test_recid_determinism.py` still green.
- [ ] Task 1's sibling-search produced an assertive report (not abortive); any unexpected bare-cursor sites surfaced via AskUserQuestion BEFORE Tasks 2/3 ran.
- [ ] DUAL Opus QA approvals on impl (per #98 standard).
- [ ] CHANGELOG.md entry at v0.36.6X.

---

## Design Decisions Log

(All 11 decisions are also recorded as full entries in `design_decisions.json` alongside this spec.)

| # | Decision | Rationale (short) | Reversibility |
|---|----------|-------------------|---------------|
| DD-1 | DD-1: Leak detector is a pure-query helper with no monkeypatch and zero composition with pro... | Avoids any interaction with the prod_guard `_lifecycle_guarded` sentinel and the install_prod_guard monkeypatch at L48-L67. The detector opens a dedicated short-lived ... | Trivially reversible — delete the file. |
| DD-2 | DD-2: Fix the 7 cursor sites in-place via `with conn.cursor() as cur:` rather than refactori... | Minimal-invasive (≤30 LOC per file). Preserves the Oracle signature contract. Each retrofit is mechanical and reviewable. Aligns with existing codebase patterns (60+ P... | Per-site reversible. The PRIMARY verify-by-mutation procedure (Task 6 TEST 1)... |
| DD-3 | DD-3: Rollback-between-checks via try/finally per check call in Oracle.assert_all | Preserves the 1..9 invariant order required by VerdictReporter. Each check call is in its own try/finally so a check raising mid-execute still triggers self.conn.rollb... | Reversible via direct revert of the assert_all body. Oracle signature unchang... |
| DD-4 | DD-4: 3x loop is the BACKSTOP default; SIM_LEAK_LOOP_ITERATIONS allows opt-in stress mode (≥10) | 3 iterations is enough to demonstrate strict no-growth without inflating CI time. Smoke runs ~15s so 3 iterations is ~45s — fits inside the lifecycle-smoke 600s timeou... | Configurable via env var. |
| DD-5 | DD-5: Canonical leak signal is TOTAL client-backend count filtered by application_name (REV-2) | smoke.py runs autocommit=True (L96) so idle-in-txn is structurally 0 — idle-in-txn as the signal would be vacuous. TOTAL client-backend count covers both autocommit an... | The application_name_filter parameter defaults to None so production calls re... |
| DD-6 | DD-6: Do NOT hoist the existing pg_conn fixture from test_scenario.py into a shared conftest.py | Neither new test needs the existing pg_conn fixture. The PRIMARY (§3.6) test opens its own psycopg2.connect with application_name kwarg + autocommit=False. The BACKSTO... | Strictly additive change if future need arises. |
| DD-7 | DD-7: PROD audit is document-only in this PR; fixes are filed as separate future tasks. Sibl... | Per operator requirement: PROD audit DOCUMENT-ONLY (no PROD code changes). Bundling PROD fixes with sim fixes mixes blast radius. REV-2: Task 1's bare-cursor sibling-s... | Follow-up tasks are the reversibility mechanism for PROD findings. Sibling-se... |
| DD-8 | DD-8: bracket_attach.py:126 is filed as #100-followup-A, NOT fixed in this PR | Per requirements: PROD audit DOCUMENT-ONLY. The bracket_attach path is NOT exercised by ScenarioRunner so the sim regression test cannot witness it. Bundling expands P... | Follow-up task is the reversibility mechanism. |
| DD-9 (NEW, REV-2 per DA1) | DD-9 (NEW, REV-2 per DA1): Inner-mechanism witness test is PRIMARY verify-by-mutation surfac... | The bug per spec §1.3 is cross-check poisoning WITHIN a single Oracle.assert_all() invocation: check N's leaked cursor leaves self.conn in `idle in transaction (aborte... | Either test can be removed independently. The PRIMARY test is the must-keep w... |
| DD-10 (NEW, REV-2 per DA3) | DD-10 (NEW, REV-2 per DA3): Single-tenant test isolation via application_name='sim_leak_test' | The 5434 test PG is shared infrastructure — multiple developers, concurrent pytest runs, parallel CI jobs all hit the same backend pool. Counting ALL client backends i... | application_name_filter defaults to None so production entrypoint calls remai... |
| DD-11 (NEW, REV-2 per DA4) | DD-11 (NEW, REV-2 per DA4): Detector graceful-fail under max_connections exhaustion | The detector exists to diagnose connection-exhaustion leaks. In the exact failure mode it diagnoses — test PG at max_connections=100 — the detector's own psycopg2.conn... | The try/except is a thin wrapper around the existing connect call. Removable ... |


---

## Known Considerations (devils-advocate minor + nit findings, not blocking)

Surfaced during adversarial review; deemed below the threshold for spec revision. Documented for the implementing PM + post-merge consideration.

| # | Concern | Note |
|---|---------|------|
| KC1 | `Oracle.assert_all()` rollback in `finally` can mask the original check exception | If the check raised, `finally` runs `self.conn.rollback()`. If that rollback ALSO raises (rare — transport failure, server-forced backend termination), Python's exception-chaining surfaces the rollback exception as primary and the original check exception as `__context__`. Operator sees rollback failure first. Mitigation: wrap the rollback in `try: self.conn.rollback() except Exception: pass` — best-effort cleanup, not a contract. Document why the rollback is allowed to fail silently. |
| KC2 | 3x outer loop has no per-iteration progress output (interactive pytest sees a stalled test for ~45s) | Add `print(f'leak-test iteration {i+1}/{iterations}')` inside the for-loop. Trivial change, large UX win for interactive runs. CI is unaffected. |
| KC3 | `SIM_LEAK_LOOP_ITERATIONS` env var has no validation | `int(os.environ.get('SIM_LEAK_LOOP_ITERATIONS', '3'))` crashes with `ValueError` on non-int inputs (e.g., `'10s'`). Mitigation: bounded parse with default-on-error: `try: iterations = max(2, int(os.environ.get(...).strip())) except (ValueError, AttributeError): iterations = 3`. Log a warning if iterations < 2 (verify-by-mutation needs ≥2). |
| KC4 | Task 7 follow-up task filing mechanism (`TaskCreate`) is named but the implementer may not know if this is an arcis CLI invocation, a GitHub issue, or operator-manual | Per operator's complete-efforts-no-deferral discipline, every audit finding MUST become an actual tracked task. If unclear, surface via `AskUserQuestion` so operator files. Add acceptance criterion: `TaskList` output shows `#100-followup-A` (bracket_attach.py:126) and `#100-followup-B` (broker_exception_logger.py:51) as tracked items. |
| KC5 (nit) | Spec's file:line citations (L35, L64, L92, L120, L174, etc.) will drift after the with-wrap retrofit is applied | Primary anchor in the spec is by FUNCTION name (`check_attribution`, `check_corpus_integrity`, etc.) — line numbers are belt-and-suspenders. Implementer can refer to function names without line drift. |

(Per devils-advocate review pass — see `arcis:design-devils-advocate` invocation 2026-05-24.)
