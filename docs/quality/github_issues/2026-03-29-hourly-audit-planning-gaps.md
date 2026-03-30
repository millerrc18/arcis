# GitHub Issue Drafts — 2026-03-29 (Planning Gaps)

These issue drafts capture errors/gaps identified in the prior planning revision and should be opened in GitHub during audit rollout.

---

## Issue 1
**Title:** [MEDIUM] Hourly audit framework lacked explicit command-level validation baseline

**Labels:** `severity:medium`, `area:audit-ops`, `audit-found`

**Summary**
The prior hourly audit planning document defined process stages but did not specify concrete baseline commands for each stage, reducing reproducibility and comparability across audit cycles.

**Affected Components**
- `docs/audits/hourly-audit-planning-framework-2026-03-29.md` (initial revision)
- Hourly audit operational execution process

**Reproduction Steps**
1. Read prior planning document.
2. Attempt to run an hourly cycle with two different auditors.
3. Observe command selection variance and inconsistent evidence quality.

**Expected Behavior**
The framework provides minimum command baselines so different auditors produce consistent, deterministic evidence sets.

**Actual Behavior**
Process guidance existed, but command-level baselines were missing.

**Evidence**
- Prior revision lacked concrete command examples in Event A/B/C sections.

**Risk Statement**
Inconsistent command execution can mask regressions and lower confidence in audit conclusions.

**Proposed Remediation Options**
1. Add minimum baseline command set per event (recommended).
2. Keep document generic and rely on individual auditor discretion.

**Trade-off Analysis**
- Option 1 improves consistency and evidence quality; modest maintenance burden when tooling changes.
- Option 2 is lower maintenance but increases drift and false confidence risk.

**Owner / Milestone / SLA**
- Owner: Audit tooling lead
- Milestone: Audit automation v1
- SLA: 2 business days

---

## Issue 2
**Title:** [MEDIUM] No explicit GitHub issue creation policy for confirmed audit errors

**Labels:** `severity:medium`, `area:governance`, `audit-found`

**Summary**
Prior planning did not codify a mandatory policy to open GitHub issues for each confirmed audit error, which can result in findings not being tracked to closure.

**Affected Components**
- Audit governance process
- Findings-to-remediation lifecycle

**Reproduction Steps**
1. Generate findings from an hourly cycle.
2. Attempt to track remediation status over multiple cycles.
3. Observe missing persistent issue linkage for some findings.

**Expected Behavior**
All confirmed errors map to GitHub issues with severity labels, owners, and due dates.

**Actual Behavior**
Issue creation policy was not explicitly required.

**Evidence**
- Prior planning revision omitted an explicit issue requirement section.

**Risk Statement**
Untracked findings create unresolved risk debt and weaken accountability.

**Proposed Remediation Options**
1. Require issue creation for all confirmed Low+ severity findings (recommended).
2. Require only Critical/High issue creation.

**Trade-off Analysis**
- Option 1 maximizes traceability; may increase issue volume.
- Option 2 reduces overhead but permits medium/low risk accumulation.

**Owner / Milestone / SLA**
- Owner: Engineering manager + audit lead
- Milestone: Audit governance hardening
- SLA: 2 business days

---

## Issue 3
**Title:** [LOW] Escalation thresholds were implied but not quantitatively defined

**Labels:** `severity:low`, `area:incident-process`, `audit-found`

**Summary**
The prior framework referenced escalation but lacked default numerical thresholds for triggering incident actions, making escalation decisions potentially subjective.

**Affected Components**
- Escalation gate logic
- Incident response consistency

**Reproduction Steps**
1. Produce a mix of high and medium findings.
2. Ask two reviewers whether to escalate.
3. Compare differing decisions due to missing thresholds.

**Expected Behavior**
Framework specifies default threshold triggers with tunable parameters.

**Actual Behavior**
Escalation intent described, but thresholds not quantified.

**Evidence**
- Prior Event E section had policy language but no numerical defaults.

**Risk Statement**
Delayed escalation for severe issues or over-escalation for low-risk clusters.

**Proposed Remediation Options**
1. Add default thresholds and tuning guidance (recommended).
2. Keep policy qualitative only.

**Trade-off Analysis**
- Option 1 improves consistency and speed; requires periodic threshold calibration.
- Option 2 is simpler initially but risks inconsistency under load.

**Owner / Milestone / SLA**
- Owner: Incident commander + audit lead
- Milestone: Audit automation v1
- SLA: 5 business days
