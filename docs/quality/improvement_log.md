# Improvement Log

## 2026-03-29 — Introduced Hourly Audit Planning Framework
- **Improvement:** Established a repeatable, evidence-first hourly audit scope with explicit time-boxed events and escalation logic.
- **Why it mattered:** Enables thorough, high-accuracy recurring reviews while preventing redundant full-repo rescans every hour.
- **Trade-off:** Hourly cycle focuses on deltas/invariants; full deep-repo coverage shifts to daily/weekly cadence.
- **Evidence:** `docs/audits/hourly-audit-planning-framework-2026-03-29.md` added.
- **PR reference:** f8cf075

## 2026-03-29 — Hardened Framework with Governance & Reproducibility Controls
- **Improvement:** Added concrete command baselines, mandated GitHub issue creation for each confirmed error, and defined default escalation thresholds.
- **Why it mattered:** Improves repeatability between auditors and ensures findings are tracked to closure.
- **Trade-off:** Additional process overhead and issue volume, offset by stronger control traceability.
- **Evidence:**
  - `docs/audits/hourly-audit-planning-framework-2026-03-29.md` (expanded sections)
  - `docs/quality/github_issues/2026-03-29-hourly-audit-planning-gaps.md` (issue drafts)
- **PR reference:** (pending in current branch)
