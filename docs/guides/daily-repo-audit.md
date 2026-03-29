# Daily Repo Audit

Halcyon now includes a hosted daily repo-audit workflow:

- Workflow: `.github/workflows/daily-repo-audit.yml`
- Audit runner: `scripts/daily_repo_audit.py`
- Issue sync: `scripts/sync_daily_repo_audit_issues.py`
- Baseline file: `config/daily_repo_audit_baseline.json`

## Schedule

The workflow runs every hour at `:15` UTC.

It can also be launched manually with `workflow_dispatch`.

## What It Checks

The daily repo audit is deliberately code-focused rather than machine-specific.
It avoids local-only runtime assumptions such as a developer's Ollama process,
paper-trading credentials, or workstation database state.

Current checks include:

- Custom probes for the highest-risk execution issues
- Targeted pytest suites around live trading, council, risk, features, API routes, and CLI guardrails
- A tracked-file secret-prefix scan

## Baseline Behavior

The audit is baseline-aware.

Known failures from the 2026-03-29 manual audit are listed in
`config/daily_repo_audit_baseline.json` and linked to the GitHub issues opened in that audit.

Each task is classified as one of:

- `pass`
- `baseline_fail`
- `improvement`
- `unexpected_fail`

Overall audit status:

- `green`: no baseline failures and no unexpected failures
- `yellow`: baseline failures still exist, or a baseline failure was improved
- `red`: a new unexpected failure appeared

## GitHub Issue Policy

The workflow does not reopen all known issues every day.

Instead:

- Known baseline failures stay linked to their existing audit issues
- Unexpected regressions create or reopen managed issues titled:
  - `[Daily Repo Audit] Unexpected regression in ...`
- If a managed unexpected-regression issue stops reproducing, the workflow closes it automatically
- The workflow uses the repository `GITHUB_TOKEN` with `issues: write`, so it does not need a pasted PAT

This keeps the tracker useful without daily issue spam.

## Artifacts

Every run uploads an `audit-output/` artifact containing:

- `summary.json`
- `latest-summary.md`
- `daily-repo-audit-YYYY-MM-DD.md`

The step summary is also appended to the GitHub Actions run summary.
