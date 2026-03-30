# Issue Log

## 2026-03-29 — Audit Process Scope Gap
- **Issue:** No formal recurring hourly audit scope definition existed for how to balance accuracy with cadence.
- **Why it mattered:** Without a scoped framework, "audit every hour" can become inconsistent, low-signal, or operationally unsustainable.
- **Action taken:** Added planning framework in `docs/audits/hourly-audit-planning-framework-2026-03-29.md` defining tiered cadence, hourly event structure, severity/confidence rubric, escalation gates, and trade-off requirements.
- **Evidence:** Document created and versioned in repo.
- **PR reference:** f8cf075

## 2026-03-29 — Planning Framework Gaps (Addressed)
- **Issue:** Initial framework lacked concrete command baselines, explicit per-error GitHub issue policy, and numeric escalation thresholds.
- **Why it mattered:** Missing operational specifics can reduce audit reproducibility and closure accountability.
- **Action taken:** Expanded framework with minimum command baselines, mandatory GitHub issue policy + required fields/SLAs, and default escalation thresholds.
- **Evidence:** Updated planning document + issue drafts in `docs/quality/github_issues/2026-03-29-hourly-audit-planning-gaps.md`.
- **PR reference:** (pending in current branch)
