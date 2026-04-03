# Halcyon Audit Plugin — User Guide

The halcyon-audit plugin provides a single `/audit` command that runs comprehensive, baseline-aware repo audits. It dispatches 8 specialized domain agents in parallel, synthesizes findings through a 9th agent, files GitHub issues with corrective actions, and produces a quality-gated summary report.

## Quick Reference

| Item | Details |
|---|---|
| Plugin location | `.claude/plugins/halcyon-audit/` |
| Command | `/audit` |
| Spec | `docs/superpowers/specs/2026-04-03-halcyon-audit-plugin-design.md` |
| Baseline file | `audit/audit_baseline.json` |
| History file | `audit/audit_history.json` |
| Reports | `docs/audits/audit-YYYY-MM-DD.md` |
| State file | `audit/state.json` (shared with daily CI audit) |

## Commands

```bash
/audit                           # Full audit — all 8 domains
/audit trading,security          # Audit only specified domains
/audit --quick                   # Skip code-quality and comment-doc (noisiest)
/audit --baseline-only           # Only check regressions against baseline
/audit --schedule daily          # Schedule recurring audit, weekdays 8 AM ET
/audit --schedule weekly         # Schedule recurring audit, Mondays 8 AM ET
/audit --schedule off            # Remove scheduled audit
```

### Domain Names

| Short Name | Full Agent | Prefix | What It Checks |
|---|---|---|---|
| `trading` | trading-safety-auditor | TS | Silent failures, risk governor bypass, broker/journal truth |
| `quality` | code-quality-auditor | CQ | Oversized functions/files, god objects, dead code, duplication |
| `schema` | schema-integrity-auditor | SI | Schema drift, DDL violations, FK integrity, orphaned records |
| `tests` | test-coverage-auditor | TC | Test count, coverage gaps, slow tests, mock quality |
| `compliance` | compliance-auditor | CM | CLAUDE.md rules, MASTER.md architecture, naming conventions |
| `docs` | comment-doc-auditor | CD | MASTER.md drift, stale comments, README accuracy |
| `security` | security-auditor | SE | Credentials, SQL injection, API auth, CORS, dependencies |
| `architecture` | architecture-auditor | AR | Layer violations, circular imports, module coupling |

## Prerequisites

1. **GitHub CLI** — `gh auth status` must show authenticated
2. **Virtual environment** — `.venv` must be activated (agents run pytest and schema validation)
3. **Auto-accept mode** — Press Shift+Tab before running to avoid permission prompts for Bash commands in subagents

## How It Works

### Three-Phase Execution Model

```
Phase 1: SCATTER
    Dispatch 8 domain agents in parallel (sonnet model, background)
    Each agent scans its domain and returns structured JSON findings
    ~3-5 minutes wall clock

Phase 2: GATHER
    Dispatch synthesis agent (inherit model, foreground)
    Deduplicates, clusters root causes, correlates cross-domain
    Verifies evidence for high/critical findings
    Computes health scores and quality gate
    ~2-3 minutes

Phase 3: REPORT
    Files GitHub issues (idempotent — won't create duplicates)
    Writes summary report to docs/audits/
    Updates audit history for trend tracking
    Prints quality gate + executive summary to terminal
    ~1-2 minutes
```

### Quality Gate

The audit produces a pass/fail signal based on these criteria:

| Gate | Criteria | Action |
|---|---|---|
| **PASS (GREEN)** | Zero critical, zero new high, health >= 7.0 | No immediate action |
| **WARN (YELLOW)** | Zero critical AND (<=2 new high OR health 5.0-6.9) | Plan remediation |
| **FAIL (RED)** | Any critical OR >2 new high OR health < 5.0 | Immediate remediation |

### Health Scores

Each domain is scored 1-10:

| Finding Severity | Score Deduction |
|---|---|
| Critical | -3.0 per finding |
| High | -1.5 per finding |
| Medium | -0.5 per finding |
| Low | -0.1 per finding |

Overall health = arithmetic mean of all 8 domain scores.

## Baseline Management

The baseline system prevents audit fatigue by tracking known findings. Located at `audit/audit_baseline.json`.

### Classification

When the audit runs, each finding is classified as:

| Classification | Meaning | Action |
|---|---|---|
| `regression` | New finding not in baseline | Create GitHub issue |
| `baseline_fail` | Known finding still present | Skip (already tracked) |
| `improvement` | Previously failing, now passing | Close linked issue |

### Adding to Baseline

After an audit, the orchestrator asks if you want to add new findings to the baseline. This is appropriate when:
- A finding is acknowledged but deferred (e.g., watch.py god object — planned for a future sprint)
- A finding is a false positive
- A finding is low-risk and not worth tracking per-audit

### Baseline File Format

```json
{
  "version": "1.0.0",
  "last_updated": "2026-04-03",
  "known_findings": [
    {
      "fingerprint": "sha256_hash",
      "domain": "code-quality",
      "title": "watch.py exceeds 400-line limit",
      "severity": "high",
      "issue_number": 210,
      "first_detected": "2026-04-03",
      "reason": "Planned refactor in Sprint 9"
    }
  ]
}
```

## GitHub Issue Management

### Issue Types

The audit creates three types of GitHub issues:

1. **Finding** — standalone issue for a single finding
   - Title: `[Audit] High: Silent failure in executor error path`
   - Labels: `audit`, `high`, `trading-safety`

2. **Root Cause** — explains multiple symptom findings
   - Title: `[Audit] High: watch.py god object causes cascading failures [Root Cause]`
   - Labels: `audit`, `high`, `root-cause`, `architecture`, `code-quality`

3. **Systemic** — recurring pattern across the codebase
   - Title: `[Audit] Medium: Redundant inner imports across 12 files [Systemic]`
   - Labels: `audit`, `medium`, `systemic`, `code-quality`

### Idempotency

Each finding has a deterministic fingerprint: `sha256(domain + file + line_range + title)`.

- Running `/audit` twice will NOT create duplicate issues
- If a finding's severity changes, the existing issue is updated
- If a previously-closed finding recurs, the issue is reopened
- If a finding is resolved, the issue is closed with a comment

### Labels

The first audit run creates these labels automatically (idempotent):

| Label | Color | Purpose |
|---|---|---|
| `audit` | Green | All audit-created issues |
| `critical` | Red | Critical severity |
| `high` | Orange | High severity |
| `medium` | Yellow | Medium severity |
| `low` | Blue | Low severity |
| `trading-safety` | Purple | Trading domain |
| `code-quality` | Purple | Code quality domain |
| `schema-integrity` | Purple | Schema domain |
| `test-coverage` | Purple | Test domain |
| `compliance` | Purple | Compliance domain |
| `documentation` | Purple | Documentation domain |
| `security` | Purple | Security domain |
| `architecture` | Purple | Architecture domain |
| `root-cause` | Light green | Root cause issues |
| `systemic` | Light green | Systemic pattern issues |

## Scheduling

The `--schedule` flag sets up recurring audits via Claude Code's remote agent system (CronCreate).

```bash
/audit --schedule daily     # Noon UTC (8 AM ET), Mon-Fri, runs --quick
/audit --schedule weekly    # Noon UTC (8 AM ET), Mondays, runs full audit
/audit --schedule off       # Remove all scheduled audits
```

Scheduled audits:
- Run as remote agents on Anthropic's infrastructure
- File GitHub issues and write reports automatically
- Work even when your machine is off
- Both daily and weekly run full audits (all 8 domains)

**DST caveat:** Schedule times use a fixed EDT (UTC-4) offset. During EST (Nov-Mar), audits run 1 hour earlier than specified. For example, `/audit --schedule daily 8pm` runs at 8 PM ET in summer but 7 PM ET in winter. This is a cron limitation — cron doesn't support timezone-aware scheduling.

## Trend Tracking

The audit history at `audit/audit_history.json` tracks health scores over time. Each audit appends a run entry:

```json
{
  "date": "2026-04-03",
  "quality_gate": "WARN",
  "overall_health": 6.5,
  "scores": {
    "trading_safety": 7,
    "code_quality": 5,
    "schema_integrity": 9,
    "test_coverage": 7,
    "compliance": 8,
    "documentation": 6,
    "security": 8,
    "architecture": 5
  },
  "finding_counts": {"critical": 0, "high": 3, "medium": 12, "low": 8},
  "issues_created": 6,
  "issues_closed": 2,
  "report_path": "docs/audits/audit-2026-04-03.md"
}
```

The summary report includes trend arrows comparing to the previous run:
- Score up >= 0.5: up arrow
- Score down >= 0.5: down arrow
- Otherwise: sideways arrow

## Relationship to Daily CI Audit

| Aspect | `/audit` Plugin | Daily CI Audit |
|---|---|---|
| Where it runs | Local (Claude Code) or scheduled remote | GitHub Actions |
| Scope | 8 domains, full codebase analysis | Targeted pytest suites + probes |
| Baseline | `audit/audit_baseline.json` | `config/daily_repo_audit_baseline.json` |
| Output | Report + GitHub issues + history | Artifact + step summary + managed issues |
| When to use | Deep periodic audit, sprint boundaries | Daily regression detection |
| State file | `audit/audit_history.json` | `audit/state.json` |

The two systems are complementary:
- Daily CI catches regressions fast (runs every day in CI)
- `/audit` provides deep cross-domain analysis (run periodically or on-demand)
- Both file GitHub issues but use separate baselines and separate tracking

## Extending the Plugin

### Adding a New Domain Agent

1. Create `.claude/plugins/halcyon-audit/agents/new-domain-auditor.md` with frontmatter:
   ```yaml
   ---
   name: new-domain-auditor
   description: What this agent audits
   model: sonnet
   maxTurns: 30
   tools: Read, Grep, Glob, Bash
   ---
   ```
2. Add the domain to the mapping table in the orchestrator skill (`SKILL.md`)
3. Add the domain short name to the command description in `commands/audit.md`
4. Add a domain prefix entry in `references/finding-schema.md`

### Modifying the Quality Gate

Edit `.claude/plugins/halcyon-audit/skills/audit-orchestrator/references/quality-gate.md` to change thresholds.

### Adding Runtime Probes

Each agent can include bash commands in its prompt. To add a new probe:
1. Write the probe as a bash command in the relevant agent's `.md` file
2. Add it under a "Runtime Probes" section
3. The agent will execute it and include the output as evidence

### Enabling Persistent Memory

The synthesis agent can learn across audits if given persistent memory. To enable:
1. Copy `.claude/plugins/halcyon-audit/agents/audit-synthesizer.md` to `.claude/agents/audit-synthesizer.md`
2. Add `memory: local` to the frontmatter
3. The agent will accumulate audit intelligence over time

Note: Plugin agents cannot use the `memory` frontmatter field — this is a Claude Code limitation. Copying to `.claude/agents/` (project scope) bypasses this restriction.

## Cost Estimate

| Component | Model | Est. Tokens |
|---|---|---|
| 8 domain agents | sonnet | ~200K each = ~1.6M |
| 1 synthesis agent | opus (inherit) | ~500K |
| Orchestrator | parent session | ~100K |
| **Total per audit** | | **~2.2M tokens** |

`--quick` mode skips 2 domains, reducing to ~1.6M tokens.

## Troubleshooting

**"GitHub CLI not authenticated"**
Run `gh auth login` before using `/audit`.

**Subagents blocked by permissions**
Press Shift+Tab to enable auto-accept mode before running `/audit`.

**Duplicate issues created**
Check that the `Fingerprint:` field is present in issue bodies. The deduplication relies on this field.

**"No audit baseline found"**
The file `audit/audit_baseline.json` should exist with `{"version":"1.0.0","last_updated":"...","known_findings":[]}`. If missing, create it.

**Audit takes too long**
Use `/audit --quick` to skip code-quality and comment-doc domains. These are the noisiest and most token-intensive.

**Scheduled audit not running**
Check `CronList` to verify the cron exists. Scheduled audits require an active Claude Code subscription with remote agent access.
