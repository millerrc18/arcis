---
name: audit
description: Run a comprehensive, baseline-aware repo audit with parallel domain agents and GitHub issue filing
arguments:
  - name: domains
    description: "Comma-separated domain names to audit (trading,quality,schema,tests,compliance,docs,security,architecture). Flags: --quick, --baseline-only, --schedule daily|weekly|off"
    required: false
---

# /audit — Comprehensive Repo Audit

Run a full audit of the Halcyon Lab (Arcis) repository using 8 specialized domain agents in parallel, synthesize findings, file GitHub issues, and produce a quality-gated report.

**Tip:** For uninterrupted execution, press Shift+Tab to enable auto-accept before running this command.

## Usage

- `/audit` — Full audit, all 8 domains
- `/audit trading,security` — Only specified domains
- `/audit --quick` — Skip code-quality and comment-doc (noisiest domains)
- `/audit --baseline-only` — Only check regressions against baseline
- `/audit --schedule daily` — Schedule recurring audit at 8 AM ET weekdays
- `/audit --schedule weekly` — Schedule recurring audit Monday 8 AM ET
- `/audit --schedule off` — Remove scheduled audit

## What This Does

1. **Dispatches 8 domain agents** in parallel (sonnet model, ~3-5 min each)
2. **Runs a synthesis agent** that deduplicates, clusters root causes, verifies evidence, and computes health scores
3. **Files GitHub issues** with severity labels, corrective actions, and evidence (idempotent — won't create duplicates)
4. **Writes a summary report** to `docs/audits/audit-YYYY-MM-DD.md`
5. **Prints a quality gate** (PASS/WARN/FAIL) with health scores and priority remediation list

## Scheduling

When `--schedule` is provided, this command sets up a recurring audit instead of running one immediately:
- `daily`: Creates a scheduled remote agent that runs `/audit --quick` at 8 AM ET on weekdays (Mon-Fri)
- `weekly`: Creates a scheduled remote agent that runs `/audit` (full) at 8 AM ET on Mondays
- `off`: Removes any existing scheduled audit

Scheduled audits run as remote agents and will file GitHub issues and write reports automatically.

## Invoke the Orchestrator

Use the `audit-orchestrator` skill to execute. Pass the arguments: `$ARGUMENTS`
