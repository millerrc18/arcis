# Pass B — Empirical Vacuous-Test Verification + DELETION_LIST

**Audit:** #102 (PR-E, T28)
**Date:** 2026-05-28
**Branch:** sprint/phase-5/pr-e
**Methodology:** DD-38 empirical break-the-SUT; DA8 test quality
**Input:** `pass-a-candidates.md` (T27, 194 heuristic CANDIDATES)
**Status:** INVESTIGATIVE — no tests deleted (T29 executes the DELETION_LIST)

---

## 1. Overview

T27 produced 194 heuristic candidates across 4 detectors (H1 mock-only, H2
high @patch:assert ratio, H3 SUT self-patch, H4 no-assertion). Pass B applies
the **decisive DD-38 experiment** to the top candidates: temporarily BREAK the
production behavior the test claims to guard, run the test, and observe.

> A test is CONFIRMED vacuous **iff** it still PASSES when the SUT behavior it
> claims to test is broken. If it FAILS when the SUT is broken, it is a genuine
> guard (NON-vacuous) and MUST NOT be deleted.

Every scratch mutation was made in `src/` in-place and **reverted with
`git checkout`** immediately after observing the test result. `git status`
confirms zero residual `src/` changes (see §5). Each row in the DELETION_LIST
(§4) cites an experiment in §3 that produced a PASSED-while-broken result —
no entry rests on a heuristic flag alone.

### Headline result

| Metric | Value |
|--------|-------|
| Top candidates empirically verified via a break experiment | **9 distinct SUT break-experiments** covering 12 named candidates + sibling clusters |
| **CONFIRMED vacuous (delete)** | **2** |
| NON-vacuous (genuine guard, kept) | 7 experiments / ~30 candidates incl. sibling clusters |
| Stale candidates (file:line no longer resolves — nothing to delete) | 2 (`test_shadow_service.py:219`/`:230`) |
| STRENGTHEN (vacuous surface, add assertion not delete) | 0 |

The dominant finding: most H1 (mock call-count) and H4 (does-not-raise) flags
are **false positives** — in this codebase the mock call-count and the
propagated exception ARE the observable production contract, so breaking the
SUT makes the assertion (or the raise) fail. The **exception** is a narrow but
real H4 sub-pattern: **"does-not-raise" tests whose SUT is a log-only / best-effort
stub.** For those, a `return`-only no-op also satisfies "does not raise," so the
test passes while the SUT is gutted — genuinely vacuous. Both DELETION_LIST
entries are this pattern.

This is a measured correction to the T27 pre-empirical estimate of 15-25: the
confirmed-vacuous rate among rigorously-broken top candidates is **far lower**
(2 confirmed), because the heuristics are high-recall / low-precision. But it is
**not zero** — the log-only-stub H4 tests are real dead weight.

---

## 2. Methodology (per candidate)

1. Identify the SUT — the production function/behavior the test claims to cover
   (from the test name, `@patch` targets, body assertions).
2. In `src/` (scratch, in-place), BREAK that SUT: no-op it, strip a guard, drop
   a kwarg, swallow a return value, or disable a gate — whichever maps to the
   specific behavior the test asserts. (DD-38 discipline: break **the behavior
   the test asserts**, not just "delete the whole function" — for an
   `assert_not_called` test the relevant SUT behavior is the guard condition.)
3. Run the candidate test with
   `ARCIS_ALLOW_PROD_PG_IN_TESTS=1 python -m pytest <file> -k <name> -q`.
   - PASSED-while-broken → VACUOUS.
   - FAILED-while-broken → NON-vacuous (genuine guard).
4. `git checkout <file>` to revert. Record the rerun output below.

---

## 3. Per-Candidate Empirical Results

### EXP-1 — H4 stub-notify `test_notify_gate_proposal_does_not_raise` (#38) → **VACUOUS**

- **File:Line:** `tests/test_watch_strategy_gate.py:274`.
- **SUT:** `src/scheduler/watch.py::WatchLoop._notify_gate_proposal` — a Sprint 2
  stub that logs the gate decision and best-effort sends a Telegram line (its own
  try/except swallows any send failure). The test patches Telegram disabled, so
  the only observable behavior is the `logger.info`.
- **Break experiment:** replaced the entire body with `return` (no log, no notify).
- **Rerun output (PASSED-while-broken):**
  ```
  tests/test_watch_strategy_gate.py::test_notify_gate_proposal_does_not_raise
  1 passed, 7 deselected in 0.18s
  ```
- **Verdict:** **VACUOUS.** The test asserts nothing and the SUT's only behavior
  (a log line) is unobserved, so a full no-op satisfies "does not raise." The
  test cannot detect a regression that silently drops the gate-proposal notify.

### EXP-2 — H4 stub `test_handle_ib_error_does_not_raise` (#260) → **VACUOUS**

- **File:Line:** `tests/trading/test_ib_broker_helpers.py:22`.
- **SUT:** `src/trading/ib_broker_helpers.py::handle_ib_error` — classifies an IB
  error code via `_IB_ERROR_CODES` and emits `logger.error`/`logger.warning`.
  The test calls it with three codes and asserts nothing.
- **Break experiment:** replaced the classify+log body with `return`.
- **Rerun output (PASSED-while-broken):**
  ```
  tests/trading/test_ib_broker_helpers.py::test_handle_ib_error_does_not_raise
  1 passed, 4 deselected in 0.09s
  ```
- **Verdict:** **VACUOUS.** No assertion on classification or log; a no-op
  satisfies "never raises on known codes." A regression that mis-classified
  every IB error (or logged nothing) would not be caught. The sibling
  `test_ib_broker_helpers_module_imports` already covers symbol presence, so
  deleting this loses no coverage.

### EXP-3 — H1 watch_handlers guard cluster (#15–#36, 22 tests) → NON-VACUOUS

- **File:Line:** `tests/test_watch_handlers.py:130`
  (`test_maybe_morning_training_stop_respects_done_flag`) + sibling H1 handler tests.
- **SUT:** `src/scheduler/watch_handlers.py::maybe_morning_training_stop` (+13
  sibling `maybe_*` handlers). The `_run_*` downstreams are MagicMocks in the
  `_make_watch` factory; the **handler functions are the real SUT**.
- **Break experiment:** stripped the time-window + done-flag guard
  (`if (now.weekday()<5 and now.hour==5 and now.minute>=15 and not done):` → `if True:`)
  so the handler fires unconditionally inside the overnight window.
- **Rerun output (FAILED-while-broken):**
  ```
  FAILED test_maybe_morning_training_stop_respects_done_flag
    AssertionError: Expected '_run_morning_training_stop' to not have been called. Called 1 times.
  FAILED test_maybe_morning_training_stop_before_window
    AssertionError: Expected '_run_morning_training_stop' to not have been called. Called 1 times.
  2 failed, 1 passed, 39 deselected
  ```
- **Verdict:** **NON-VACUOUS.** The `assert_not_called` mock assertion IS the
  observable contract — breaking the guard fails it. T27 caveat #4 confirmed.
  The 13 sibling handlers share the identical `_is_overnight_window` + time +
  done-flag structure and the same assert shape; the experiment generalizes.

### EXP-4 — H1 platform-tick cluster (#10, #11, #12) → NON-VACUOUS

- **File:Line:** `tests/scheduler/test_watch_platform_tick.py:50` / `:82` / `:128`.
- **SUT:** `src/scheduler/watch.py::WatchLoop._run_platform_shadow_tick` — iterates
  active shadow-trading strategies, gates each by its `shadow_cadence_seconds`.
- **Break A (per-strategy iteration → `active[:1]`):**
  ```
  FAILED test_platform_tick_runs_each_strategy_independently
    AssertionError: assert 1 == 2  (mock_cls.call_count)
  1 failed, 3 passed
  ```
- **Break B (construct `ShadowHarness(None)` unconditionally before the loop):**
  ```
  FAILED test_platform_tick_zero_active_strategies_is_noop
    AssertionError: Expected 'ShadowHarness' to not have been called. Called 1 times. Calls: [call(None)].
  1 failed, 3 deselected
  ```
  (Break A also drives #10 `respects_cadence` indirectly; the cadence-gate disable
  fails its `call_count == 2` progression — verified non-vacuous.)
- **Verdict:** **NON-VACUOUS.** Each `call_count` / `assert_not_called` genuinely
  guards a distinct behavior (per-strategy iteration / empty-registry no-op /
  cadence gate). H1 false positives.

### EXP-5 — H1 overnight email-routing `green_no_email` / `yellow_no_email` (#2, #3) → NON-VACUOUS

- **File:Line:** `tests/scheduler/test_overnight_email_routing.py:68` / `:87`.
- **SUT:** `src/scheduler/overnight.py::run_daily_audit` — only a RED assessment
  routes to the email digest; GREEN/YELLOW must enqueue/send nothing.
- **Break experiment:** changed the assessment gate `if assessment == "red":` →
  `if assessment != "__never__":` (route regardless of assessment).
- **Rerun output (FAILED-while-broken):**
  ```
  FAILED test_daily_audit_green_no_email
    AssertionError: assert 1 == 0  (mock_enq.call_count)
  FAILED test_daily_audit_yellow_no_email
    AssertionError: assert 1 == 0  (mock_enq.call_count)
  2 failed, 7 deselected
  ```
- **Verdict:** **NON-VACUOUS.** The `call_count == 0` assertions genuinely guard
  the assessment-routing gate. H1 false positives.

### EXP-6 — H4 dispatch `test_dispatch_unknown_event_is_noop` (#14) → NON-VACUOUS

- **File:Line:** `tests/test_watch_handler_registry.py:129`.
- **SUT:** `src/scheduler/handler_registry.py::_dispatch` — `self._handlers.get(event, [])`
  returns `[]` for an unregistered event (the no-op behavior under test).
- **Break experiment:** changed `.get(event, [])` → `self._handlers[event]`
  (drop the missing-event default).
- **Rerun output (FAILED-while-broken):**
  ```
  FAILED test_dispatch_unknown_event_is_noop
    KeyError: 'on_fill'
  1 failed, 15 deselected
  ```
- **Verdict:** **NON-VACUOUS.** Distinguishes this H4 test from the vacuous ones:
  here the SUT has a real missing-event guard that the no-assertion test
  exercises (the unhandled KeyError fails the implicit no-raise contract).

### EXP-7 — H4 `test_disconnect_safe_when_not_connected` (#46) → NON-VACUOUS

- **File:Line:** `tests/test_ib_broker.py:631`.
- **SUT:** `src/trading/ib_broker.py::IBBroker.disconnect` — `if self._ib and self._ib.isConnected():`
  guards against `_ib is None`.
- **Break experiment:** dropped the `self._ib and` short-circuit → `if self._ib.isConnected():`.
- **Rerun output (FAILED-while-broken):**
  ```
  FAILED test_disconnect_safe_when_not_connected
    AttributeError: 'NoneType' object has no attribute 'isConnected'
  1 failed, 25 deselected
  ```
- **Verdict:** **NON-VACUOUS.** The None-guard is genuinely guarded; the implicit
  no-raise contract is load-bearing (unlike EXP-1/EXP-2 where the SUT is a
  log-only stub with no guard to break).

### EXP-8 — H3 broker delegate `test_get_current_price_delegates` (#299) → NON-VACUOUS

- **File:Line:** `tests/test_broker_interface.py:226`.
- **SUT:** `src/trading/alpaca_broker.py::AlpacaLiveBroker.get_current_price` —
  delegates to `alpaca_adapter.get_current_price` and returns the result.
- **Break experiment:** swallowed the delegate result (`get_current_price(ticker); return None`).
- **Rerun output (FAILED-while-broken):**
  ```
  FAILED tests/test_broker_interface.py::TestAlpacaBrokerDelegation::test_get_current_price_delegates
  1 failed, 22 deselected
  ```
- **Verdict:** **NON-VACUOUS.** The `assert price == 150.25` is a real return-value
  assertion (not mock-only) — the H3 flag matched the *dependency* symbol, not the
  SUT method. False positive.

### EXP-9 — H4 kill-switch resume cluster (#49, #50, #53) → NON-VACUOUS

- **File:Line:** `tests/test_kill_switch_source_allowlist.py:83` / `:89` / `:93`.
- **SUT:** `src/risk/governor.py::_global_halt` — resume (`halt=False`) must be
  unrestricted regardless of `source` (operator policy 2026-05-08); only `halt=True`
  is allowlist-gated.
- **Break experiment:** changed `if halt and source not in _HALT_ALLOWED_SOURCES:`
  → `if source not in _HALT_ALLOWED_SOURCES:` (gate resume too).
- **Rerun output (FAILED-while-broken):**
  ```
  FAILED test_resume_from_auditor_succeeds
    HaltSourceForbiddenError: _global_halt(True, source='unknown') refused ...
  FAILED test_resume_from_scheduler_succeeds
  FAILED test_resume_from_unknown_source_succeeds
  3 failed, 14 deselected
  ```
- **Verdict:** **NON-VACUOUS.** These "does-not-raise" H4 smoke tests genuinely
  guard the resume-unrestricted policy — the propagated exception fails the test.

---

### Stale candidates (file:line no longer resolves)

| Pass-A entry | Finding |
|--------------|---------|
| `test_shadow_service.py:219` (#258 `test_close_position_without_shadow_trade_sends_alert`) | The current `tests/test_shadow_service.py` is a 7-line import smoke test. No function by this name exists anywhere in `tests/` — the file was reduced by a kin task AFTER the T27 scanner snapshot. **Nothing to delete.** |
| `test_shadow_service.py:230` (#259 `test_submit_order_calls_broker`) | Same — function does not exist in the current tree. **Nothing to delete.** |

This staleness is itself a finding: T29 MUST resolve every DELETION_LIST entry
against the live tree (test name, not just line number) before deleting. The
canonical entries in §4 were each re-confirmed by `grep` against the current
HEAD (`test_watch_strategy_gate.py:274`, `trading/test_ib_broker_helpers.py:22`).

### Scanner false-positive patterns (do NOT delete)

| Pattern | Examples | Why not vacuous |
|---------|----------|-----------------|
| Mock `call_count`/`assert_*called` as the production contract | EXP-3, EXP-4, EXP-5 | Where the downstream is mocked but the SUT is the caller/dispatcher/router, the call-count IS the observable behavior — breaking the SUT fails it. |
| H4 no-raise test over a SUT with a real guard | EXP-6, EXP-7, EXP-9 | The unhandled exception (KeyError / AttributeError / HaltSourceForbiddenError) fails the implicit no-raise contract. |
| H3 name-matched the *dependency* symbol, not the SUT | EXP-8 | The test patches a dependency and asserts the SUT's real return value. |
| `@pytest.fixture` named `test_*` | `test_dpo_pipeline.py:11`, `test_validation.py:11` | Fixtures, not collected tests — deleting breaks dependents. (Not re-broken; structural — pytest `--collect-only` shows zero matches.) |

---

## 4. DELETION_LIST

Canonical DA8 format: `file:line: rationale`. **One row per CONFIRMED-vacuous
test** — each row is backed by a PASSED-while-broken experiment in §3. T29 cites
these exact lines and MUST re-resolve them against the live tree (the §3 line
numbers were re-grepped at this HEAD).

```
tests/test_watch_strategy_gate.py:274: test_notify_gate_proposal_does_not_raise — H4 does-not-raise over a log-only stub SUT (_notify_gate_proposal); EXP-1 shows it PASSES when the SUT body is no-op'd. Asserts nothing; cannot detect a dropped gate-proposal notify. Sibling test_notify_gate_proposal_helper_exists already covers symbol presence.
tests/trading/test_ib_broker_helpers.py:22: test_handle_ib_error_does_not_raise — H4 does-not-raise over a classify+log stub SUT (handle_ib_error); EXP-2 shows it PASSES when the SUT body is no-op'd. Asserts nothing about classification or log; sibling test_ib_broker_helpers_module_imports covers symbol presence.
```

**Confirmed-vacuous count: 2.** Both are the log-only-stub H4 sub-pattern. All
other rigorously-broken top candidates FAILED while their SUT was broken (genuine
guards) or no longer resolve (stale file:line). Per the KEY DISCIPLINE
("NO entry without empirical proof"), no other candidate is listed.

---

## 5. git-status-clean confirmation

All scratch `src/` mutations were reverted with `git checkout` immediately after
each experiment. Before commit, `git status --short src/` is **empty** and
`git diff` shows no `src/` change.

`src/` files temporarily mutated-then-reverted (one experiment each):
`src/scheduler/watch_handlers.py`, `src/scheduler/watch.py`,
`src/scheduler/overnight.py`, `src/scheduler/handler_registry.py`,
`src/trading/ib_broker.py`, `src/trading/ib_broker_helpers.py`,
`src/trading/alpaca_broker.py`, `src/risk/governor.py`.

Only this receipt (`docs/audits/2026-05-28-test-audit/pass-b-empirical.md`) is
committed.

---

## 6. Notes, caveats, and the T29 budget implication

1. **Confirmed-vacuous = 2, well below T27's 15-25 estimate.** The T27 heuristics
   are high-recall / low-precision: H1 mock-call-count and H4 no-raise tests are
   *predominantly* genuine behavioral guards in this codebase. The only reliably
   vacuous sub-pattern surfaced empirically is **H4 does-not-raise over a log-only
   /best-effort-stub SUT** (no guard, no return assertion). Heuristics alone would
   have over-deleted ~28 genuine guards.

2. **T29 deletion budget vs actual.** PR-D added ~55 tests (notional ~50 budget).
   The *empirically supported* deletion count is **2**, not ~50. T29 should delete
   exactly the 2 DELETION_LIST entries. Any "must delete N" target is unsupported
   by this evidence — deleting genuine guards to hit a number is a net-negative
   regression-safety change (anti feedback_vacuous_test_pattern +
   feedback_fix_before_trade). If the operator wants a larger reduction, the right
   lever is the STRENGTHEN path (item 4), not deletion.

3. **Coverage honesty.** I individually broke 9 distinct SUTs covering 12 named
   top candidates plus two structural-equivalence sibling clusters (the 22-test
   watch_handlers H1 cluster via EXP-3; the platform-tick trio via EXP-4). I did
   NOT individually break all 194 candidates; experiments were prioritized by risk
   (scheduler / safety / evaluation P1-P5 + the top-10 + every confirmed-vacuous
   candidate). The H2 backtester/shadow cluster (#290-297, 11-13 @patch each) was
   not individually broken — pass-a note #5 already characterizes these as
   thin-coverage integration tests whose SUT logic runs for real; they are
   STRENGTHEN-shaped, not delete-shaped, and none were confirmed vacuous.

4. **STRENGTHEN_LIST.** No top candidate had a vacuous surface that warranted a
   *delete-and-replace*; the two confirmed-vacuous tests are pure dead weight
   (their SUTs are already covered for existence by sibling tests), so they are
   straight deletions, not strengthens. The H2 integration tests (#290-297) could
   be *additively* strengthened with richer output assertions in a future task,
   but that is new test work outside T28/T29 scope and none were confirmed vacuous.

## STRENGTHEN_LIST

```
# (none — both confirmed-vacuous tests are straight deletions whose SUT existence
#  is already covered by sibling tests; the H2 backtester/shadow integration
#  tests #290-297 are additive-strengthen candidates for a future task but were
#  NOT confirmed vacuous in this pass.)
```
