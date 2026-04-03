# halcyon-audit

Project-local Claude Code plugin for comprehensive, baseline-aware repo audits.

## Usage

```
/audit                    # Full audit, all 8 domains
/audit trading,security   # Specific domains only
/audit --quick            # Skip noisy domains (quality, docs)
/audit --baseline-only    # Only check regressions
/audit --schedule daily   # Recurring weekday audits
```

## Architecture

Three-phase scatter-gather-report:

1. **SCATTER** — 8 domain agents run in parallel (sonnet, background)
2. **GATHER** — 1 synthesis agent deduplicates, clusters, verifies, scores
3. **REPORT** — File GitHub issues, write report, update history

## Components

```
.claude-plugin/plugin.json          Plugin manifest
commands/audit.md                   /audit command entry point
agents/
  trading-safety-auditor.md         Silent failures, risk governor, broker truth
  code-quality-auditor.md           Functions >50 lines, files >400, god objects
  schema-integrity-auditor.md       Registry drift, DDL violations, FK integrity
  test-coverage-auditor.md          Pytest suite, coverage gaps, mock quality
  compliance-auditor.md             CLAUDE.md + MASTER.md rule violations
  comment-doc-auditor.md            Doc drift, stale comments, README accuracy
  security-auditor.md               Credentials, SQL injection, API auth, CORS
  architecture-auditor.md           Layer violations, circular imports, coupling
  audit-synthesizer.md              Dedup, root cause, verification, quality gate
skills/audit-orchestrator/
  SKILL.md                          Orchestration logic + scheduling
  references/
    finding-schema.md               JSON output contract for agents
    issue-templates.md              GitHub issue templates (3 types)
    quality-gate.md                 PASS/WARN/FAIL criteria + health scoring
```

## State Files (project root)

- `audit/audit_baseline.json` — Known/accepted findings
- `audit/audit_history.json` — Health score time series

## Documentation

- User guide: `docs/guides/audit-plugin.md`
- Design spec: `docs/superpowers/specs/2026-04-03-halcyon-audit-plugin-design.md`
- Implementation plan: `docs/superpowers/plans/2026-04-03-halcyon-audit-plugin.md`
