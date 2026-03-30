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

## 2026-03-30 — Hourly Audit Cycle 001 Findings
- **Issue:** First executed hourly cycle found 1 high + 4 medium + 1 low confirmed issues (training leakage crash path, notification idempotency/time-gating behavior, undefined API logger, pytest import-path fragility, invalid doc command).
- **Why it mattered:** These impact audit reliability, quality-gate robustness, and operator alert trust.
- **Action taken:** Logged full cycle report in `docs/audits/hourly-audit-log-2026-03-30T01-00Z.md` and drafted GitHub issues for each finding in `docs/quality/github_issues/2026-03-30-hourly-audit-cycle-001.md`.
- **Evidence:** Command outputs from preflight, pytest (`PYTHONPATH=. pytest -q`), and ruff checks captured in audit log.
- **PR reference:** (pending in current branch)
