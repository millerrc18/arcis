# Round 10 — 0-Failures Triage

> **Operator-stated standard:** zero failed tests on main, doesn't matter if pre-existing.
> **Sweep result:** 13 failed / 3,630 passed / 11 skipped (no errors after fresh isolation).
> **PM disposition:** every failure has a documented root cause. None are "isolation noise"; none are "gaming candidate."

---

## Group A — B3 LEGACY_COERCIONS over-coerced (8 tests, 4 sub-causes)

The B3 follow-up commit `1a5e4d6` added `LEGACY_COERCIONS` in `src/shadow_trading/exit_reason.py` that map several legacy values to canonical vocab. The vocabulary was kept tight on the principle "fewer canonical values = clearer analytics." On reflection, the coercion was **too aggressive**: three of the four mappings collapsed semantically-distinct categories into a generic `error` or `reconciled` bucket, which hid information the operator wants visible.

### A1 — `reconciled_stale` → `reconciled` (over-coerced) — 4 tests

```
src/shadow_trading/exit_reason.py: LEGACY_COERCIONS["reconciled_stale"] = "reconciled"
```

**Why this should NOT coerce:** `reconciled_stale` means "timeout-style stale; reconciler force-closed because the trade had been hanging too long." `reconciled` is a broader category. Collapsing them loses the timeout signal.

**Affected tests:**
- `tests/test_reconcile.py::test_reconcile_marks_stale`
- `tests/test_reconcile.py::test_paper_reconcile_stale_auto_closed`
- `tests/test_reconcile.py::test_reconcile_stale_without_yfinance`
- `tests/test_reconcile.py::test_paper_reconcile_cancels_orders_before_close`

**Proposed fix:** Add `reconciled_stale` to `EXIT_REASON_VOCAB` as a first-class value. Remove from `LEGACY_COERCIONS`. Update B3 design doc to reflect.

**Anti-gaming check:** ✅ NOT gaming. The tests captured a real semantic distinction the B3 follow-up agent erased.

### A2 — `exit_overshoot_detected` → `error` (over-coerced) — 2 tests

**Why this should NOT coerce:** Overshoot is a specific data-integrity warning ("Alpaca thinks we own a different qty than we do"). `error` is a catch-all. The operator needs to see overshoots distinct from generic errors.

**Affected tests:**
- `tests/test_reconcile.py::test_stuck_exit_with_short_position_needs_manual_review`
- `tests/shadow_trading/test_reconcile_partial_fill_mismatch.py::test_overshoot_guard_still_fires_at_negative_qty`

**Proposed fix:** Add `exit_overshoot_detected` to `EXIT_REASON_VOCAB`. Remove from `LEGACY_COERCIONS`.

**Anti-gaming check:** ✅ NOT gaming. Same pattern as A1.

### A3 — `qty_mismatch_partial_fill` → `error` (over-coerced) — 1 test

**Why this should NOT coerce:** This is the CVS-style scenario from B2.C (operator-flagged, severe). The whole point of B2.C was making this category visible; coercing it to `error` defeats the purpose.

**Affected test:**
- `tests/shadow_trading/test_reconcile_partial_fill_mismatch.py::test_reconcile_handles_0_lt_alpaca_qty_lt_planned`

**Proposed fix:** Add `qty_mismatch_partial_fill` to `EXIT_REASON_VOCAB`. Remove from `LEGACY_COERCIONS`.

**Anti-gaming check:** ✅ NOT gaming. The B3 follow-up should never have collapsed this — direct contradiction of B2.C's design.

### A4 — `take_profit` → `target_1` (correctly coerced) — 1 test

**Why this SHOULD coerce:** The Alpaca bracket-leg-fill path writes `take_profit`; the price-poll path writes `target_1_hit`. These are semantically the same exit (target hit). Coercion to `target_1` is correct canonicalization.

**Affected test:**
- `tests/test_bracket_safety.py::TestStopVsTakeProfitLeg::test_limit_leg_sets_take_profit_reason`

**Proposed fix:** Update the test's assertion from `take_profit` to `target_1`. Add comment explaining the coercion is intentional canonicalization.

**Anti-gaming check:** ✅ NOT gaming. The test was written before B3's canonicalization landed; updating the assertion to match canonical behavior is the right fix.

---

## Group B — Real bug: `log_and_persist` UnboundLocalError (1 test)

`tests/test_executor_import.py::TestExitExceptionMarksFailure::test_exception_marks_exit_failed_not_open`

```
src/shadow_trading/executor.py:1979:
    log_and_persist(...)
UnboundLocalError: cannot access local variable 'log_and_persist' where it is not associated with a value
```

**Root cause:** Round 5b/B2.B's lazy-import pattern. The `from src.shadow_trading.broker_exception_logger import log_and_persist` is INSIDE one except block, making `log_and_persist` a function-local variable. When a different except block in the same function (line 1979) tries to use it before the lazy-import-bearing block has run, Python raises `UnboundLocalError`.

This is a **real production bug**. If a real exception fires at the line-1979 site BEFORE the line-829 lazy import has run in the same call, the error handler itself raises, and the trade stays in an undefined state.

**Proposed fix:** Move the import to module-top (line ~40 area, alongside other imports). The lazy-import was originally chosen to avoid a circular import; verify there's no actual cycle (B2.A already moved the helper to its own module, so the cycle should be broken).

**Anti-gaming check:** ✅ Real bug fix. This was caught by a test asserting a specific failure path.

---

## Group C — Archive script: hardcoded table count outdated (4 tests)

`tests/scripts/test_archive_bootcamp_2026_04_24.py` — all 4 tests fail with:

```
ERROR archive_bootcamp_2026_04_24.py:541 Registry table count drift: expected 67, got 68. Update CLAUDE.md + this script's invariant.
```

**Root cause:** The archive script `scripts/archive_bootcamp_2026_04_24.py` line ~541 has `EXPECTED_TABLE_COUNT = 67` (hardcoded). Track 1.5 / Round 5a / B2.A added the `broker_exceptions` table (commit `c3e5431`), bringing the count to 68.

**Proposed fix:** Bump constant from 67 to 68. Add an inline comment documenting the lineage:
```
EXPECTED_TABLE_COUNT = 68  # 67 pre-Track-1.5 + 1 broker_exceptions (B2.A, c3e5431)
```

The script's error message even says "Update CLAUDE.md + this script's invariant" — it's a self-documenting drift detector.

**Anti-gaming check:** ✅ Trivial constant bump matching reality. Not weakening anything.

**Side observation:** The same test runs surface a separate WARNING — `cannot import name 'AlpacaAdapter' from 'src.shadow_trading.alpaca_adapter'`. That's a separate bug unrelated to test failures. Worth filing as a follow-up but doesn't block the 4 archive tests.

---

## Summary

| Root cause | Tests | Fix | Files touched |
|---|---|---|---|
| A1: `reconciled_stale` over-coerced | 4 | Promote to vocab | `src/shadow_trading/exit_reason.py` |
| A2: `exit_overshoot_detected` over-coerced | 2 | Promote to vocab | `src/shadow_trading/exit_reason.py` |
| A3: `qty_mismatch_partial_fill` over-coerced | 1 | Promote to vocab | `src/shadow_trading/exit_reason.py` |
| A4: `take_profit` correctly coerced | 1 | Update test assertion | `tests/test_bracket_safety.py` |
| B: `log_and_persist` UnboundLocalError | 1 | Move import to module-top | `src/shadow_trading/executor.py` |
| C: archive script table count outdated | 4 | Bump constant 67 → 68 | `scripts/archive_bootcamp_2026_04_24.py` |
| **TOTAL** | **13** | | **4 files** |

## Proposed dispatch shape

Three parallel fix agents (disjoint files):

- **Fix-A** — `src/shadow_trading/exit_reason.py` + reconcile tests (Group A1+A2+A3 — promote 3 values to vocab; A4 test update bundled here too)
- **Fix-B** — `src/shadow_trading/executor.py` (Group B — module-top import)
- **Fix-C** — `scripts/archive_bootcamp_2026_04_24.py` (Group C — constant bump)

Each agent gets the anti-gaming rules (no skipping, no weakening, no autouse fixtures hiding the symptom). Each commits its own narrow tests passing. After all three commit: full integrator sweep → expect 0 failures.

## What I'm NOT proposing

- **Not skipping any test.** Every test gets fixed at the root.
- **Not weakening any assertion.** The A4 test gets its expectation updated to match canonical behavior, but the assertion is still strict.
- **Not adding `pytest.skip`, `xfail`, or `skipif`.**
- **Not introducing autouse fixtures that suppress the underlying bug.**
- **Not deferring any of these to "post-PR follow-up."**
- The 8 LEGACY_COERCIONS tests are NOT gaming — the coercions were genuinely wrong (loss of operator-relevant signal). The fix expands the canonical vocab, doesn't mute the tests.

---

**Awaiting operator sign-off.** When you respond, I dispatch Fix-A/B/C in parallel.
