---
name: data-anomaly
verb: runbook
symptom-matchers:
  - "data anomaly"
  - "row count drift"
  - "orphan FK"
  - "missing table"
  - "shadow trades missing"
  - "recommendations missing"
  - "macro_snapshots gap"
  - "duplicate rows"
required-tools:
  - dbquery
  - capabilityregistry
  - logtail
required-agents:
  - db-investigator
expected-duration: 10-20 min
mutations: false  # diagnostic; remediation = operator-issued hotfix
risk-level: low
references:
  - project_orphan_source_investigation
  - feedback_complete_efforts_no_deferral
---

# Runbook — data-anomaly

## When to use

A table-level anomaly observed: row count drift between prod-PG and registry expectation, orphan FK rows (shadow_trades referencing non-existent recommendations), missing collector tables (Finnhub dead-weight per #71), duplicate rows (the macro_snapshots dedupe issue #52), date gaps.

## Prerequisites

- Operator can name the affected table(s) OR the anomaly type. If neither, the runbook starts by listing all tables and asking.

## Steps

### Step 1 — ask which-anomaly

**Purpose:** Scope the investigation to specific tables. Avoid scanning all 80+ tables for every invocation.

**Invocation:** AskUserQuestion if `RUNBOOK_ARG[1]` not provided.

> Which data anomaly should this runbook investigate?

Options:
- "Specific table(s) — name them" — sub-prompt for table names
- "Orphan FK forensics" — set INVESTIGATION_HYPOTHESIS = orphan_fk
- "Row count drift vs registry" — set INVESTIGATION_HYPOTHESIS = registry_drift
- "Missing collector tables" — set INVESTIGATION_HYPOTHESIS = collector_missing
- "Duplicate rows" — set INVESTIGATION_HYPOTHESIS = duplicates
- "I'm not sure — surface a summary first" — set INVESTIGATION_HYPOTHESIS = broad_surface

### Step 2 — agent db-investigator

**Purpose:** Read-only forensics on the scoped tables.

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

**MANDATE:** Investigate the data anomaly. Type: {INVESTIGATION_HYPOTHESIS}. Tables: {FOCUS_TABLES if provided else null}. Read-only — no DML, no schema changes.
**INVESTIGATION_MODE:** {deep if INVESTIGATION_HYPOTHESIS != broad_surface else surface}
**INITIAL_HYPOTHESIS:** {derived from operator selection}
**FOCUS_TABLES:** {list or null for broad}
**WORKTREE_PATH:** {pwd}
```

**Expected output:** `<db_report>` with `findings[]`.

**Decision point:**
- `findings[]` empty → STOP. No anomaly found at this depth. Suggest deepening: rerun with `INVESTIGATION_MODE=deep` if surface yielded nothing, OR investigate manually.
- `findings[]` populated → continue to Step 3

### Step 3 — compose + categorize findings

**Purpose:** Group findings by remediation class.

**Decision point:** For each finding, categorize:

- **A. Schema-fixable** (missing index, wrong column type, missing FK) → recommendation: open hotfix issue
- **B. Backfill-fixable** (orphan rows, date-gap rows missing from collector) → recommendation: write backfill script (operator's pattern: mark-attempted + batch commits ≥50 per `feedback_backfill_patterns`)
- **C. Upstream-source bug** (e.g., orphan-source investigation #82) → recommendation: investigate upstream
- **D. Informational only** (row count is low but expected — markets closed, low volume) → no action

**No out-of-scope deferral** — if 5 findings, surface all 5 categorized. Even if only 2 are "real" issues by operator's standard, list the 3 informational ones.

### Step 4 — ask backfill-now

**Purpose:** Offer to draft a backfill script for B-class findings. Drafting is out of scope; we surface the pattern only.

**Invocation:** AskUserQuestion if any B-class finding.

> $N findings are backfill-class. Backfill scripts are written by the operator (see `feedback_backfill_patterns`: mark-attempted '{}' not NULL + batch commits ≥50 rows).
> Should I print the backfill skeleton for the most-affected table?

Options:
- "Yes — print skeleton" — print a Python skeleton matching the operator's backfill pattern
- "No — I'll write it manually" — continue to Step 5
- "Skip — no backfill needed" — continue to Step 5

### Step 5 — operator-facing report

```
DATA-ANOMALY $INCIDENT_ID — INVESTIGATION COMPLETE
Hypothesis: $HYPOTHESIS
Tables investigated: $FOCUS_TABLES
Findings ($N total):

[A-class: schema] $N
  1. ...

[B-class: backfill] $N
  1. ...

[C-class: upstream] $N
  1. ...

[D-class: informational] $N
  1. ...

Recommendations:
  A-class → open hotfix issue (use issue template above)
  B-class → write backfill script (skeleton printed above if requested)
  C-class → /arcis:operate triage "<upstream symptom>"
  D-class → no action
```

## Success criteria

1. db-investigator returned a `<db_report>` with `findings[]` populated OR empty + `coverage_assessment` informative
2. All findings categorized
3. All findings surfaced — no deferral

## Rollback

Diagnostic-only. No mutations.

## Abandonment recovery (DA9)

Diagnostic-only — no mutations in this runbook. Abandonment recovery is a no-op (see §3 Phase R3).

## Escalation

- db-investigator returns no findings but operator believes there is an issue: rerun with `INVESTIGATION_MODE=deep`.
- Operator wants to remediate via schema mutation: open a hotfix issue + use `/arcis:code` with a spec.
- Cross-table anomaly (multiple tables affected, complex correlation): fall back to /arcis:operate triage with broader scope.
