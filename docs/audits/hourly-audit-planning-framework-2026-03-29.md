# Hourly Audit Planning Framework (Pre-Execution)

_Date: 2026-03-29_
_Status: Planning only (no repository-wide audit executed yet)_

## 1) Objective
Design a recurring audit process that can run every hour with high accuracy, clear severity categorization, confidence scoring, and actionable remediation guidance, without pretending a full deep audit can be redone from scratch 24x/day.

## 2) Why a Tiered Hourly Scope Is Necessary
A true "entire repo" deep audit each hour is operationally expensive and risks lower signal quality due to reviewer fatigue and repeated low-value checks. A tiered cadence preserves accuracy:

- **Hourly:** fast delta/risk-surface audit (what changed + what can break now)
- **Daily:** broader systemic review
- **Weekly:** deep full-repo architectural and control audit
- **Monthly:** governance and methodology validation

This keeps "accuracy first" while still giving hourly coverage.

## 3) Recommended Recurring Event Scope (Every Hour)

### Event A — Triage & Change-Surface Audit (0-10 min)
**Goal:** Detect high-risk changes immediately.

- Pull latest changeset since last audit timestamp.
- Identify touched areas by critical domain:
  - trading execution (`src/shadow_trading`, live execution pathways)
  - risk controls (`src/risk`, kill switch, limits)
  - data integrity (collectors, feature generation, scoring inputs)
  - model/training quality controls (leakage, validation, promotion gates)
  - API/dashboard reliability for operator visibility
- Auto-classify changed files into risk buckets and assign review priority.

**Minimum commands (planning baseline):**
- `git fetch --all --prune`
- `git diff --name-status <last_audit_sha>...HEAD`
- `python -m src.main preflight` (or equivalent health entrypoint)

**Output:** Hourly delta inventory + preliminary risk map.

### Event B — Control Invariant Verification (10-25 min)
**Goal:** Verify safety-critical controls still hold.

Run targeted checks only for impacted surfaces, e.g.:
- kill switch behavior unchanged
- risk governor checks still enforced and fail-safe
- bracket order constraints still present
- no bypass of validation/promotion gates
- no logging/observability regressions in critical paths

**Evidence rules:**
- Every invariant check must include command, exit code, and log path.
- Any skipped check must include reason + explicit follow-up owner.

**Output:** Pass/fail matrix of invariants with direct evidence.

### Event C — Targeted Test + Static Audit Slice (25-40 min)
**Goal:** Maximize defect detection per minute.

- Run focused tests for changed modules + nearest integration tests.
- Run static scans for dangerous patterns in changed diff:
  - bare `except` in safety paths
  - silent error handling
  - insecure secret handling
  - nondeterministic time/data assumptions in training eval
- Re-run only failed tests once to remove flake noise.

**Minimum commands (planning baseline):**
- `pytest -q <changed_test_targets>`
- `ruff check <changed_python_paths>`
- `mypy <changed_python_paths>` (if type coverage exists)

**Output:** Deterministic evidence bundle (commands, status, logs).

### Event D — Findings Log + Recommendations (40-55 min)
**Goal:** Produce decision-ready output.

Every finding must include:
- **Criticality:** Critical / High / Medium / Low / Informational
- **Confidence:** High / Medium / Low + short rationale
- **Impact:** operational, financial, model quality, compliance, observability
- **Recommendation:** specific remediation
- **Trade-offs:** latency, engineering effort, false positive/negative risk, complexity
- **Owner + ETA suggestion**

**Output:** Hourly audit log entry, sorted by severity then confidence.

### Event E — Escalation Gate (55-60 min)
**Goal:** Ensure urgent issues trigger immediate action.

- If any **Critical** with medium+ confidence: trigger immediate incident/escalation path.
- If cumulative High findings exceed threshold: schedule same-day deep-dive.
- If low confidence but high impact: require manual reviewer confirmation in next cycle.

**Default thresholds (tunable):**
- `critical_count >= 1` => incident
- `high_count >= 3` in 4-hour rolling window => same-day deep dive
- unresolved `medium_count >= 5` for 24h => weekly audit priority bump

**Output:** Escalation disposition and next-action queue.

## 4) Criticality Taxonomy (Use Consistently)
- **Critical:** Can cause uncontrolled trading loss, disable risk controls, or corrupt decision pipeline with immediate material downside.
- **High:** Serious degradation to safety/performance integrity likely within normal operation.
- **Medium:** Important weakness; bounded impact or requires specific conditions.
- **Low:** Minor robustness/maintainability concern.
- **Info:** Observation or optimization note without immediate risk.

## 5) Confidence Rubric
- **High confidence:** Reproduced with deterministic test/log evidence.
- **Medium confidence:** Strong static/diff evidence but partial runtime proof.
- **Low confidence:** Plausible hypothesis needing additional data.

Rule: Never present low-confidence issues as confirmed defects.

## 6) Trade-off Template (Required per Recommendation)
For each proposed fix, record:
1. **Benefit:** risk reduced and expected impact.
2. **Cost:** implementation effort, run-time cost, team bandwidth.
3. **Risk of change:** potential regressions/new complexity.
4. **Alternative:** lower-cost or staged option.
5. **Decision:** recommend now / defer / monitor.

## 7) GitHub Issue Requirement for Every Error
Every confirmed error (Critical/High/Medium/Low) discovered during audits must have a corresponding GitHub issue opened during the same audit cycle.

### Required issue fields
- Title with severity prefix: `[CRITICAL]`, `[HIGH]`, `[MEDIUM]`, `[LOW]`
- Summary + affected components
- Reproduction steps
- Expected vs actual behavior
- Evidence (logs, stack traces, test output, screenshots where applicable)
- Risk statement (financial/safety/quality impact)
- Proposed remediation options + trade-off analysis
- Owner, target milestone, and SLA target

### Labeling and SLA defaults
- Critical: `severity:critical`, `area:*`, `audit-found`, response < 1 hour
- High: response < 4 hours
- Medium: response < 2 business days
- Low: response < 5 business days

## 8) Suggested Cadence Beyond Hourly
- **Daily (1x):** end-to-end pipeline walk + broader integration suite.
- **Weekly (1x):** full-repo deep audit (architecture, control design, tech debt, documentation accuracy).
- **Monthly (1x):** governance/meta-audit (are audits catching real issues? false positive rate? time-to-remediate trends?).

## 9) Deliverable Format for Each Hourly Cycle
1. Summary (risk posture: green/yellow/red)
2. Scope executed (what changed + what was checked)
3. Findings table (severity, confidence, impact, evidence)
4. Recommendations with trade-off analysis
5. GitHub issues created (links + owners)
6. Escalation decisions
7. Open items carried to next cycle

## 10) Non-Goals for Hourly Cycle
- Re-reading every doc and every file from scratch each hour.
- Full architectural reinterpretation each run.
- Large-scale refactor proposals without evidence from current deltas.

These belong to daily/weekly deep audits.
