---
name: audit-orchestrator
description: Orchestrate the 3-phase audit process — dispatch domain agents, run synthesis, file GitHub issues, write report. Also handles --schedule for recurring audits.
---

# Audit Orchestrator

This skill orchestrates the full audit pipeline. It is invoked by the `/audit` command.

## Arguments

The `/audit` command passes arguments as a string. Parse them:
- No arguments: run all 8 domains
- Comma-separated domain names (e.g., `trading,security`): run only those domains
- `--quick`: skip `code-quality` and `comment-doc` domains
- `--baseline-only`: only check regressions against baseline (skip new issue filing)
- `--schedule daily|weekly|off`: manage recurring audit schedule (see Scheduling section)

## Scheduling Mode

If `--schedule` is present, handle scheduling instead of running an audit:

### `--schedule daily`
Use the CronCreate tool to create a scheduled remote agent:
- **Name:** `halcyon-audit-daily`
- **Schedule:** `0 12 * * 1-5` (noon UTC = 8 AM ET, weekdays)
- **Prompt:** `Use the audit-orchestrator skill to run a quick audit. Arguments: --quick`

Tell the user: "Scheduled daily audit (weekdays 8 AM ET). Use `/audit --schedule off` to cancel."

### `--schedule weekly`
Use the CronCreate tool to create a scheduled remote agent:
- **Name:** `halcyon-audit-weekly`
- **Schedule:** `0 12 * * 1` (noon UTC = 8 AM ET, Mondays)
- **Prompt:** `Use the audit-orchestrator skill to run a full audit.`

Tell the user: "Scheduled weekly audit (Mondays 8 AM ET). Use `/audit --schedule off` to cancel."

### `--schedule off`
Use CronList to find any crons with "halcyon-audit" in the name, then CronDelete to remove them. Tell the user which schedules were removed.

After handling scheduling, STOP — do not run an audit.

## Domain Name Mapping

| Short Name | Agent Name | Prefix |
|---|---|---|
| trading | trading-safety-auditor | TS |
| quality | code-quality-auditor | CQ |
| schema | schema-integrity-auditor | SI |
| tests | test-coverage-auditor | TC |
| compliance | compliance-auditor | CM |
| docs | comment-doc-auditor | CD |
| security | security-auditor | SE |
| architecture | architecture-auditor | AR |

## Phase 0: Setup

### 0a. Verify Prerequisites
Run these checks before proceeding:

```bash
gh auth status
```

If `gh` is not authenticated, tell the user: "GitHub CLI not authenticated. Run `gh auth login` first, or the audit will skip issue filing."

### 0b. Ensure Labels Exist
Run the label creation commands from `references/quality-gate.md`. These are idempotent (`--force`). Run them all in one Bash call:

```bash
gh label create audit --color 0E8A16 --force && gh label create critical --color B60205 --force && gh label create high --color D93F0B --force && gh label create medium --color FBCA04 --force && gh label create low --color 0075CA --force && gh label create trading-safety --color 5319E7 --force && gh label create code-quality --color 5319E7 --force && gh label create schema-integrity --color 5319E7 --force && gh label create test-coverage --color 5319E7 --force && gh label create compliance --color 5319E7 --force && gh label create documentation --color 5319E7 --force && gh label create security --color 5319E7 --force && gh label create architecture --color 5319E7 --force && gh label create root-cause --color C2E0C6 --force && gh label create systemic --color C2E0C6 --force
```

### 0c. Gather Context
Read these files and store their contents for agent prompts:
1. `CLAUDE.md` — project rules
2. `MASTER.md` (Section 2 only — "Current State") — key metrics
3. `audit/audit_baseline.json` — known findings
4. `audit/audit_history.json` — previous audit data

Run and capture:
```bash
gh issue list --label audit --state all --json number,title,state,labels,body --limit 200
```

## Phase 1: SCATTER — Dispatch Domain Agents

Determine which domains to run based on arguments:
- No args: all 8
- `--quick`: skip code-quality and comment-doc (run 6)
- Comma-separated names: only those specified

Dispatch each selected domain agent using the Agent tool with these parameters:
- `subagent_type`: the agent name (e.g., `trading-safety-auditor`)
- `model`: `sonnet`
- `run_in_background`: `true`
- `prompt`: Include the full context gathered in Phase 0. Tell the agent: "You are running as part of an automated audit on YYYY-MM-DD. Return your findings in the `<audit-findings>` JSON format specified in your instructions. Be thorough but stay within your domain."

**IMPORTANT:** Dispatch ALL selected agents in a SINGLE message with multiple Agent tool calls. This ensures true parallel execution.

Wait for all background agents to complete. You will be notified as each finishes.

## Phase 2: GATHER — Run Synthesis

Once ALL domain agents have completed:

1. Collect all agent results
2. Dispatch the `audit-synthesizer` agent in the FOREGROUND with:
   - All domain agent outputs (paste the full text of each agent's response)
   - The baseline JSON
   - The history JSON
   - The GitHub issue list
   - Instruction: "Synthesize these findings following your processing steps. Return the `<audit-synthesis>` JSON."

## Phase 3: REPORT — File Issues and Write Report

Parse the synthesis agent's `<audit-synthesis>` JSON output.

### 3a. File GitHub Issues
For each entry in `issues_to_create`:
1. Look up the finding details from the synthesized findings list
2. Check if a matching issue already exists (search the issue list from Phase 0 for matching title or fingerprint in body)
3. If no match, create the issue using the templates from `references/issue-templates.md`
4. Record the created issue number

For each entry in `issues_to_close`:
1. Close the issue with a comment noting the audit date

**If `--baseline-only` was specified:** Skip issue creation. Only close resolved issues and report the baseline status.

### 3b. Write Summary Report
Write the report to `docs/audits/audit-YYYY-MM-DD.md` with this structure:

```markdown
# Repo Audit — YYYY-MM-DD

## Quality Gate: {PASS|WARN|FAIL}

## Executive Summary
{3 sentences from synthesis}

## Health Scores
| Dimension | Score | Trend | Notes |
|---|---|---|---|
| Trading Safety | X/10 | {arrow} | {brief} |
| Code Quality | X/10 | {arrow} | {brief} |
| Schema Integrity | X/10 | {arrow} | {brief} |
| Test Coverage | X/10 | {arrow} | {brief} |
| Compliance | X/10 | {arrow} | {brief} |
| Documentation | X/10 | {arrow} | {brief} |
| Security | X/10 | {arrow} | {brief} |
| Architecture | X/10 | {arrow} | {brief} |
| **Overall** | **X/10** | **{arrow}** | |

## Quality Gate Criteria
- Critical findings: {count} (threshold: 0)
- New high findings: {count} (threshold: <=2)
- Overall health: {score} (threshold: >=7.0 for PASS)

## Systemic Analysis

### Root Causes Identified
{numbered list from synthesis}

### Risk Chains
{numbered list from synthesis}

### Recurring Patterns
{numbered list from synthesis}

## Fix This Week (Top Priority)
| # | Severity | Effort | Title | Depends On |
|---|---|---|---|---|
{from synthesis fix_this_week}

## All Issues Filed
| # | Type | Severity | Domain(s) | Title | Status |
|---|---|---|---|---|---|
{from synthesis}

## Delta from Previous Audit
{from synthesis delta}

## Agent Coverage
| Agent | Files Scanned | Findings | Probes Run |
|---|---|---|---|
{from domain agent outputs}

## Methodology
- Audit tool: halcyon-audit plugin v1.0.0
- Domain agents: {count} (model: sonnet, maxTurns: 30)
- Synthesis agent: 1 (model: inherit)
- Baseline: audit/audit_baseline.json ({count} known findings)
```

### 3c. Update State Files

Update `audit/audit_history.json` — read the current file, then append a new run entry to the `runs` array:
```json
{
  "date": "YYYY-MM-DD",
  "quality_gate": "...",
  "overall_health": 0.0,
  "scores": {...},
  "finding_counts": {"critical": 0, "high": 0, "medium": 0, "low": 0},
  "issues_created": 0,
  "issues_closed": 0,
  "report_path": "docs/audits/audit-YYYY-MM-DD.md"
}
```

### 3d. Terminal Output
Print the summary to the terminal:

```
======================================
  AUDIT QUALITY GATE: {GATE} ({COLOR})
======================================

Executive Summary:
{3 sentences from synthesis}

Health Scores:
  Trading Safety:    X/10  ({trend})
  Code Quality:      X/10  ({trend})
  Schema Integrity:  X/10  ({trend})
  Test Coverage:     X/10  ({trend})
  Compliance:        X/10  ({trend})
  Documentation:     X/10  ({trend})
  Security:          X/10  ({trend})
  Architecture:      X/10  ({trend})

Issues: {created} created, {closed} closed, {baseline} baseline
Report: docs/audits/audit-YYYY-MM-DD.md

Fix This Week:
  1. [{severity}] {title} ({effort})
  2. [{severity}] {title} ({effort})
  ...
```

### 3e. Offer Baseline Update
After presenting results, ask: "Would you like to add any new findings to the baseline (mark as known/accepted)?"

If yes, update `audit/audit_baseline.json` with the selected findings — add their fingerprints to the `known_findings` array.
