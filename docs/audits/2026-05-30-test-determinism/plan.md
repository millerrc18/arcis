# Test-Determinism + Isolation Cleanup — Implementation Plan (#128)

**Goal:** make the test suite pass **deterministically** — independent of wall-clock time-of-day **and** test ordering. Today the suite is *green-by-daytime*: PR-G's authoritative run was `6 failed / 6996 passed / 35 justified-skip` at night, vs PR-E2's `0 failed` daytime baseline. This is the gate to trusting CI (when quota returns) and to the #95 capstone's "the fresh start is clean" validation.

**Class of change:** test-only + (at most) a minimal clock-injection seam in `src/notifications/policy.py`. NON-mutating to trading behavior.

**Discipline (operator anti-hand-wave standard — non-negotiable):**
- **No re-skipping, no assertion-weakening, no making a test not reach its assertion.** Every un-skip is **verify-by-mutation**: prove the test FAILS without the fix before claiming it green.
- **Validate at the FAILING condition**, not the passing one (a daytime run passes the night-flakes vacuously).
- The **T43 sentinel** (`tests/test_suite_integrity.py` + `xfail_strict`) must stay green. Net skip count must **drop by 9** (the #1192 set un-skipped); no NEW unjustified skips.
- **Dual-Opus QA at 100%.** CI is quota-dark → validate via full-LOCAL authoritative run, merge on CI-disambiguation (`feedback_ci_red_disambiguation`).

---

## The 15 victims (3 root-cause classes)

### Class A — Night-flakes (6 tests; currently FAIL at night, not skipped)
Hidden wall-clock dependency: `safe_send`'s quiet-hours policy gate (`src/notifications/policy.py:_in_quiet_window`, `now_et` computed ~`policy.py:107`) routes a `system_event`→digest at quiet hours, hitting `notifications_digest_queue` (registry.py:2625) which the SQLite test fixtures don't provision; plus date-boundary relative seeds.
- 4× governor/auditor alert tests (discover precisely — see Wave 2 T4), 1× ingestion quiet-hours, 1× `tests/attribution/test_resolver.py` (midnight date-boundary).

### Class B — env-scrub isolation (3 tests; #1192-skipped)
`tests/simulation/lifecycle/test_entrypoints.py:47,54,61` — `run_smoke` fails in-suite because the lifecycle bootstrap's import-time `_scrub_environment` leaves `connect_db` with a `None` db_path → `connect_db(None) TypeError`.

### Class C — order-dependent isolation (6 tests; #1192-skipped) — pass in isolation, fail in full-suite ordering
- `tests/test_conftest_pg_guard.py:142` — spawned subprocess inherits parent `os.environ` polluted by an earlier test → **scrub the subprocess env in `_run_collect`**.
- `tests/test_dashboard_gate_kpi_route.py:162` — `'1d'` promote-count depends on shared-state timestamps (also kin #12) → **now-relative seed timestamps**.
- `tests/test_dashboard_reconciliation.py:173` — process-global leaked by earlier test.
- `tests/test_self_blinding.py:173` — process-global leaked.
- `tests/test_trainer.py:66` and `:92` — process-global leaked.

---

## Wave plan

### Wave 1 — Systemic foundations (parallel-safe)
- **T1 Deterministic policy clock fixture.** Add a clock-injection seam at the `now_et` source in `policy.py` (minimal: accept an optional `now` param / read an injectable clock) and an autouse test fixture pinning it to a fixed **daytime** time by default, plus an explicit `freeze_quiet_hours` fixture for tests that DO exercise quiet-hours digest routing. Scope-fence: do NOT change production quiet-hours logic — only add the injection seam.
- **T2 Provision `notifications_digest_queue`** (+ sibling digest tables) in the notifications test fixtures / shared SQLite bootstrap so the digest path works where it's genuinely under test.

### Wave 2 — Per-victim fixes (parallel within wave; depends on Wave 1)
- **T4 Class A (6 night-flakes).** First **discover precisely**: run the governor/auditor/ingestion + `test_resolver` suites with the clock **frozen to 03:00 ET** — the failures are the targets. Fix each via the T1 clock fixture (+ T2 table where the digest path is asserted) + now-relative seeds. Verify-by-mutation: each FAILS at quiet-hours without the fix, PASSES with it.
- **T5 Class B (3 env-scrub).** Fix the import-time env-scrub so the smoke tier gets a valid db_path; un-skip the 3 `test_entrypoints` tests; confirm `run_smoke` works in-suite.
- **T6 Class C (6 order-dependent).** Use `pytest-forked` (per-test subprocess) to cheaply confirm each passes in isolation, then identify the leaked global by inspecting the suite-order failure. Fix at the SOURCE — extend the conftest autouse snapshot/restore pattern (precedent: `_reset_enricher_rate_limit_state:428`, the freezegun autouse hook) to reset the leaked globals; subprocess-env-scrub for `_run_collect`; now-relative seeds for `dashboard_gate_kpi`. Un-skip all 6. Verify under **randomized order** (`pytest-randomly`, ≥3 seeds).

### Wave 3 — Integration & determinism proof (depends on Wave 2)
- **T7 Authoritative proof.** In the CI-matching config (`DATABASE_URL="" ARCIS_DB_PATH=/tmp/<fresh>.sqlite3 TEST_DATABASE_URL=postgresql://test:test@127.0.0.1:5434/halcyon`, bootstrap 5434 first, `pytest tests/`, check `PYTEST_EXIT`, **never** the escape hatch):
  1. Run with clock **frozen to quiet-hours (03:00 ET)** → 0 failures (proves Class A fixed at the failing condition).
  2. Run with **randomized order** (≥3 seeds) → 0 failures (proves Class C isolation).
  3. Normal daytime run → 0 failures, no regression.
  4. T43 sentinel green; skip count dropped by exactly 9; 4 xfail unchanged or reduced.
  - CHANGELOG entry. Patch bump (v0.36.79) **only if** any `src/` touched (the policy clock seam); else test-only, no bump.

---

## Out of scope
- The capstone (#95), Phase-4 Cleanup-2 (#51/#77) — separate steps.
- Re-architecting the notifications policy — only the clock-injection seam.
- The 15 DD-42 lifecycle `authoritative-coverage` skips (legit — covered by nightly `lifecycle-full-gate`).

## Validation recipe (reference)
```bash
export TEST_DATABASE_URL="postgresql://test:test@127.0.0.1:5434/halcyon"
export DATABASE_URL=""            # connect_db → SQLite; prod 5433 untouched
export ARCIS_DB_PATH="/tmp/arcis_determinism.sqlite3"; rm -f "$ARCIS_DB_PATH"
python scripts/bootstrap_pg_test_schema.py
python -m pytest tests/ -p no:cacheprovider -q -rfEsxX --timeout=120 --timeout-method=thread > tmp/run.txt 2>&1
echo "PYTEST_EXIT=$?" >> tmp/run.txt   # PYTEST_EXIT is the real result
```
Freeze-to-quiet-hours: use `freezegun` to `2026-06-01 03:00 ET` (or the project's existing time-freeze helper) for the Class-A proof run.
