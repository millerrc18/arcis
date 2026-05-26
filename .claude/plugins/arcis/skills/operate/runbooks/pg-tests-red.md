---
name: pg-tests-red
verb: runbook
symptom-matchers:
  - "pg tests red"
  - "postgres tests failing"
  - "pytest pg failures"
  - "pg-tests.yml failing"
  - "Postgres CI red"
required-tools:
  - ciinvestigate
  - dbquery
  - logtail
  - prcomments
required-agents:
  - ci-investigator
  - db-investigator
expected-duration: 10-20 min
mutations: false  # diagnostic-only; resulting fixes are handed to operator
risk-level: low
references:
  - feedback_vacuous_test_pattern
  - feedback_review_sibling_search
---

# Runbook — pg-tests-red

## When to use

The `pg-tests.yml` CI workflow (or any PG-touching pytest job) is showing failures. The operator wants to know:
1. Which tests failed.
2. Whether each is flaky / vacuous / real regression.
3. Whether the failure is correlated with DB-side state (e.g., a table got dropped, a row diff between local and CI).
4. What the fix-now path is.

## Prerequisites

- A PR number OR a CI run ID. If neither is supplied, the runbook will prompt for one.
- gh CLI authenticated (the underlying tools assume this).

## Steps

### Step 1 — ask which-run

**Purpose:** Identify the CI run to investigate. Avoid scope creep (do not auto-scan all recent runs — that's git-historian's job for a different runbook).

**Invocation:** AskUserQuestion if `RUNBOOK_ARG[1]` (CI run id or PR number) was not provided.

> Which CI run should this runbook investigate?
> Provide one of:
> - PR number (e.g., "1234")
> - GitHub Actions run ID (e.g., "14123456789")
> - "latest" — use most recent pg-tests.yml run

Options:
- "PR number: <input>" — set TARGET_PR
- "Run ID: <input>" — set TARGET_RUN_ID
- "Latest" — fetch latest pg-tests run via `gh run list --workflow pg-tests.yml --limit 1`
- "Cancel"

### Step 2 — agent ci-investigator

**Purpose:** Classify each pytest failure. Distinguish real regression from flaky / vacuous / mock-drift.

**Invocation:**
```
Agent(
  subagent_type: "ci-investigator",
  prompt: <inject DYNAMIC CONTEXT>
)
```

**DYNAMIC CONTEXT:**
```
## DYNAMIC CONTEXT

**MANDATE:** Classify each pytest failure in {TARGET_RUN_ID or PR latest run} against the 4-way taxonomy (real regression / flaky / vacuous test / mock-target drift). Group by classification. For real regressions, identify the introducing commit if obvious.
**RUN_ID:** {TARGET_RUN_ID or null if PR mode}
**RUN_IDS:** null
**TARGET_PR:** {TARGET_PR or null}
**POST_SUMMARY:** false
**ALLOW_REPOST:** false
**WORKTREE_PATH:** {pwd}
```

**Expected output:** `<ci_report>` with `failures[]`, `classifications[]`, `coverage_assessment`.

**Decision point:**
- `failures[]` empty → STOP — no failures to investigate. Operator was wrong about the symptom, OR the run already passed on re-trigger.
- All failures classified `vacuous` or `mock-drift` → continue to Step 3 (likely no DB correlate; skip to operator handoff)
- ≥1 failure classified `real-regression` → continue to Step 3 (DB correlate likely)

### Step 3 — ask need-db-side

**Purpose:** Decide whether to dispatch db-investigator. Some failures are pure code regressions; some are caused by DB state drift between local and CI. Operator picks.

**Invocation:** AskUserQuestion.

> ci-investigator found $N failures: $CLASSIFICATION_SUMMARY.
> Some of these may be caused by DB-side state drift (e.g., a table got dropped, a row count diverges between local and CI). Should I dispatch db-investigator in parallel?

Options:
- "Yes — investigate DB-side" — continue to Step 4
- "No — code-only, skip DB" — skip to Step 5
- "Show me the failure list first" — print the failures, re-ask

### Step 4 — agent db-investigator

**Purpose:** Read-only DB forensics on tables the failed tests touch.

**Invocation:**
```
Agent(
  subagent_type: "db-investigator",
  prompt: <inject DYNAMIC CONTEXT>
)
```

**DYNAMIC CONTEXT:**
```
## DYNAMIC CONTEXT

**MANDATE:** Investigate whether the test failures correlate with DB-side state drift. Compare prod-PG vs test-PG (per arcis_config.yaml pg.prod_dsn_signatures vs pg.test_dsn). Look at: row counts, table ownership, recent schema changes via the capability registry.
**INVESTIGATION_MODE:** surface
**INITIAL_HYPOTHESIS:** Test fixtures may be missing tables, or test-PG snapshot is stale.
**FOCUS_TABLES:** {tables mentioned in the failed test file names — parsed from <ci_report>.failures[*].test_path}
**WORKTREE_PATH:** {pwd}
```

**Expected output:** `<db_report>` with `findings[]`.

**Decision point:**
- `findings[]` empty → continue to Step 5 (informational; no DB correlate)
- `findings[]` non-empty with severity ≥ anomaly → continue to Step 5 (compose into report)

### Step 5 — compose findings + report

**Purpose:** Merge `<ci_report>` + `<db_report>` (when present) into a unified operator-facing report. Per FA13 composition algorithm.

**Decision point:**
- Severity rollup per the algorithm in commands/operate.md.
- Each real-regression finding gets a recommendation: "open hotfix issue", "investigate commit SHA via /arcis:operate triage", or "rerun CI to confirm flaky."
- **No out-of-scope deferral:** if 5 failures classified and 3 are vacuous tests, surface ALL 3 vacuous tests with a recommendation to fix them. Do not silently defer.

### Step 6 — ask post-summary

**Purpose:** Offer to post the forensic summary as a PR comment if a TARGET_PR is set.

**Invocation:** AskUserQuestion. SKIP if TARGET_PR is null.

> ci-investigator's forensic summary can be posted as a comment on PR $TARGET_PR (repost-idempotent via SHA-256 fingerprint footer — safe to re-run).
> Post the summary now?

Options:
- "Yes — post summary" — invoke `/arcis:operate act post-pr-summary $TARGET_PR` (this is a mutation; goes through act's confirm gate, but the runbook's already-confirmed nature can pass through with single-confirm)
- "No — diagnostic only, don't post" — STOP

## Success criteria

Runbook produces:
1. A composed `<ci_report>` + `<db_report>` (when dispatched) summary to the operator
2. Each failure classified
3. Each real-regression has a recommendation
4. PR comment posted (if operator opted in) — verified via `prcomments --pr $TARGET_PR --tail 1`

## Rollback

This runbook is diagnostic-only. The only mutation is the optional PR comment post in Step 6, which is repost-idempotent (DA4 — ci-investigator's fingerprint footer prevents duplicates). Rollback = manually delete the PR comment if undesired.

## Abandonment recovery (DA9)

Predominantly read-only — see §3 Phase R3 abandonment recovery sub-section. The only mutation is Step 6's optional PR-comment post; abandonment between Step 6 mutation and its verify (`prcomments --tail 1`) triggers the standard abandonment-event write per §3.

## Escalation

- ci-investigator returns no classifications: try with `INVESTIGATION_MODE=deep` or fall back to `/arcis:operate triage "CI red — manual investigation"` with reduced scope.
- db-investigator finds schema drift: open a hotfix issue; do NOT auto-remediate (schema mutations are out of scope for this runbook).
- Multiple PRs touch the same failing test: run git-historian via `/arcis:operate triage` to identify the introducing commit.
