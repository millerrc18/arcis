# GitHub Issue Drafts — Hourly Audit Cycle 001 (2026-03-30 01:00 UTC)

## 1) [HIGH] Leakage detector crashes when TF-IDF pruning removes all terms

- **Issue ID:** AUD-2026-03-30-001
- **Labels:** `severity:high`, `area:training`, `audit-found`
- **Affected file(s):** `src/training/leakage_detector.py`

### Summary
`check_outcome_leakage()` can raise a `ValueError` when `TfidfVectorizer(min_df=3, max_df=0.8)` prunes all terms. This aborts the leakage check instead of returning a safe, explainable outcome.

### Reproduction
1. Run `PYTHONPATH=. pytest -q`.
2. Observe failure in `tests/test_leakage_detector.py::TestLeakageDetectorWithBiasedData::test_unbiased_data_passes`.
3. Traceback shows `ValueError: After pruning, no terms remain...` from sklearn vectorizer.

### Expected
Leakage detector should never crash on sparse/uniform text; it should return a non-fatal result (e.g., insufficient signal).

### Actual
Function raises an uncaught `ValueError` and fails the check path.

### Impact/Risk
- Reliability risk in a safety-relevant quality gate.
- Possible pipeline interruption during validation/audits.

### Recommendation
Wrap vectorization/classification in guarded handling for empty-feature scenarios and return structured fallback result.

### Trade-offs
- **Pros:** robust pipeline behavior; fewer false hard-failures.
- **Cons:** adds branching and "inconclusive" outcomes that require interpretation.

### Owner / SLA
- Owner: Training pipeline maintainer
- SLA: same day

---

## 2) [MEDIUM] Phase-gate reminder is not idempotent (`gate_50` duplicate)

- **Issue ID:** AUD-2026-03-30-002
- **Labels:** `severity:medium`, `area:notifications`, `audit-found`
- **Affected file(s):** `src/notifications/telegram.py`

### Summary
`check_action_reminders()` re-sends milestone reminders for already-notified gates.

### Reproduction
1. Run `PYTHONPATH=. pytest -q`.
2. Observe failure in `tests/test_action_reminders.py::test_gate_milestone_not_duplicated`.

### Expected
Second invocation should not resend the same milestone alert.

### Actual
Second call still includes `gate_50`.

### Impact/Risk
- Alert fatigue, reduced trust in operator notifications.
- Noise can hide higher-priority alerts.

### Recommendation
Use explicit idempotency keying and transactional insert/check around `activity_log` writes.

### Trade-offs
- **Pros:** clean operator signal.
- **Cons:** slightly more complex DB logic.

### Owner / SLA
- Owner: Notifications maintainer
- SLA: 2 business days

---

## 3) [MEDIUM] Retrain-overdue reminder check is non-deterministic around Sunday/time boundaries

- **Issue ID:** AUD-2026-03-30-003
- **Labels:** `severity:medium`, `area:notifications`, `area:scheduling`, `audit-found`
- **Affected file(s):** `src/notifications/telegram.py`

### Summary
`retrain_overdue` reminder behavior fails test expectation in time-gated path, indicating fragile time handling or branching logic.

### Reproduction
1. Run `PYTHONPATH=. pytest -q`.
2. Observe failure in `tests/test_action_reminders.py::test_retrain_overdue_check`.

### Expected
When Sunday/time and age conditions are satisfied, `retrain_overdue` should be emitted deterministically.

### Actual
Returned reminder list is empty.

### Impact/Risk
Missed retrain reminders can degrade model freshness and decision quality over time.

### Recommendation
Inject clock dependency, normalize timezone handling, and test with deterministic fixed datetime fixtures.

### Trade-offs
- **Pros:** deterministic behavior and stronger test reliability.
- **Cons:** moderate refactor effort in reminder logic.

### Owner / SLA
- Owner: Scheduler/notification maintainer
- SLA: 2 business days

---

## 4) [MEDIUM] Undefined logger in `/api/data-collection-stats` error path

- **Issue ID:** AUD-2026-03-30-004
- **Labels:** `severity:medium`, `area:api`, `audit-found`
- **Affected file(s):** `src/api/routes/system.py`

### Summary
`logger` is referenced in exception handling without being defined in the module.

### Reproduction
1. Run `ruff check src tests`.
2. Observe `F821 Undefined name 'logger'` at `src/api/routes/system.py`.

### Expected
Module defines logger before use.

### Actual
Potential `NameError` in error-handling path.

### Impact/Risk
Can turn recoverable API error into unhandled server exception.

### Recommendation
Add `import logging` and module logger initialization; add test for error path.

### Trade-offs
- **Pros:** low effort, better API resilience.
- **Cons:** none material.

### Owner / SLA
- Owner: API maintainer
- SLA: 2 business days

---

## 5) [MEDIUM] Default `pytest -q` invocation fails import resolution (`src` module)

- **Issue ID:** AUD-2026-03-30-005
- **Labels:** `severity:medium`, `area:developer-experience`, `audit-found`
- **Affected area:** test invocation/packaging config

### Summary
Running `pytest -q` from repo root fails test collection because module imports require `PYTHONPATH=.`.

### Reproduction
1. Run `pytest -q`.
2. Observe multiple `ModuleNotFoundError: No module named 'src'` collection errors.

### Expected
Standard test invocation should work without environment-specific hacks.

### Actual
Requires explicit `PYTHONPATH=.` prefix.

### Impact/Risk
CI drift and contributor friction; false-negative build status.

### Recommendation
Define project package/install path for tests (e.g., editable install) or configure pytest `pythonpath` in project config.

### Trade-offs
- **Pros:** consistent local/CI behavior.
- **Cons:** minor setup/config changes.

### Owner / SLA
- Owner: Build/test infrastructure maintainer
- SLA: 2 business days

---

## 6) [LOW] Hourly audit planning doc used unsupported CLI flag

- **Issue ID:** AUD-2026-03-30-006
- **Labels:** `severity:low`, `area:docs`, `audit-found`
- **Affected file(s):** `docs/audits/hourly-audit-planning-framework-2026-03-29.md`

### Summary
Planning baseline included `python -m src.main preflight --mode audit`, but CLI does not support `--mode` for `preflight`.

### Reproduction
1. Run `python -m src.main preflight --mode audit`.
2. Observe argparse unrecognized argument error.

### Expected
Documented baseline command should run as-is.

### Actual
Documented command fails.

### Impact/Risk
Audit automation runbook breaks at execution time.

### Recommendation
Use supported command: `python -m src.main preflight`.

### Trade-offs
None.

### Owner / SLA
- Owner: Audit docs maintainer
- SLA: same day
