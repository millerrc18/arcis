# Halcyon Audit Plugin — Design Spec

**Date:** 2026-04-03
**Status:** Approved
**Author:** Claude + millerrc18

## 1. Purpose

A project-local Claude Code plugin that provides a single `/audit` command to run comprehensive, baseline-aware repo audits on the Halcyon Lab (Arcis) autonomous trading system. The audit dispatches 8 specialized domain agents in parallel, synthesizes findings through a 9th agent, files GitHub issues with corrective actions, and produces a quality-gated summary report.

## 2. Problem Statement

Extensive repo audits currently require manual orchestration: a human must dispatch multiple analysis passes, stitch findings together, classify severity, file GitHub issues individually, and write a summary report. This process took a full session for the March 29 audit and produced 11 issues (#40-#50). The process is not repeatable, not baseline-aware, and produces no trend data.

The daily CI audit (`daily_repo_audit.py`) is automated but narrow — it runs targeted pytest suites and a handful of runtime probes. It doesn't cover code quality, architecture, documentation drift, or cross-domain risk chains.

## 3. Architecture

### 3.1 Three-Phase Execution Model

```
Phase 1: SCATTER — Parallel Domain Agents (8 agents)
    Each agent scans its domain, returns structured JSON findings
    Runs on model: sonnet (cost-efficient, fast)
    maxTurns: 30 per agent
    ↓
Phase 2: GATHER — Synthesis Agent (1 agent)
    Receives all findings + existing GitHub issues + previous audit history
    Performs: deduplication, root cause clustering, cross-domain correlation,
             risk chain analysis, severity recalculation, verification, baseline classification
    Runs on model: inherit (full reasoning capability)
    ↓
Phase 3: REPORT — Orchestrator (skill)
    Files GitHub issues (idempotent)
    Writes summary report to docs/audits/
    Updates audit/state.json and audit/audit_history.json
    Prints quality gate + executive summary to terminal
```

### 3.2 Plugin Structure

```
.claude/plugins/halcyon-audit/
├── .claude-plugin/
│   └── plugin.json                     # Plugin manifest
├── commands/
│   └── audit.md                        # /audit entry point
├── agents/
│   ├── trading-safety-auditor.md       # Domain agent 1
│   ├── code-quality-auditor.md         # Domain agent 2
│   ├── schema-integrity-auditor.md     # Domain agent 3
│   ├── test-coverage-auditor.md        # Domain agent 4
│   ├── compliance-auditor.md           # Domain agent 5
│   ├── comment-doc-auditor.md          # Domain agent 6
│   ├── security-auditor.md             # Domain agent 7
│   ├── architecture-auditor.md         # Domain agent 8
│   └── audit-synthesizer.md            # Synthesis agent
└── skills/
    └── audit-orchestrator/
        ├── SKILL.md                    # Orchestration logic
        └── references/
            ├── finding-schema.md       # JSON output contract
            ├── issue-templates.md      # GitHub issue templates
            └── quality-gate.md         # Pass/warn/fail criteria
```

### 3.3 Data Flow

```
/audit [domains] [--quick] [--baseline-only]
  │
  ├─ Read CLAUDE.md + MASTER.md (project rules)
  ├─ Read audit/audit_baseline.json (known findings)
  ├─ Read audit/audit_history.json (trend data)
  ├─ Run: gh issue list --label audit --state all (existing issues)
  ├─ Run: gh label create --force (ensure labels exist)
  │
  ├─ DISPATCH 8 domain agents in parallel (background)
  │   Each receives: project rules, baseline, file inventory
  │   Each returns: <audit-findings>{...JSON...}</audit-findings>
  │
  ├─ DISPATCH synthesis agent (foreground, after all 8 complete)
  │   Receives: all 8 finding sets + baseline + issue inventory + history
  │   Returns: synthesized findings + report data
  │
  ├─ FILE GitHub issues (idempotent)
  │   New findings → create issue
  │   Known findings → skip (or update if severity changed)
  │   Resolved findings → close issue with comment
  │
  ├─ WRITE report to docs/audits/audit-YYYY-MM-DD.md
  ├─ UPDATE audit/state.json + audit/audit_history.json
  └─ PRINT quality gate + executive summary to terminal
```

## 4. The 8 Audit Domains

### 4.1 Trading Safety

**Agent:** `trading-safety-auditor`
**Extends:** Existing `security-reviewer` agent patterns
**Focus:**
- Silent failures in execution paths (executor.py, watch.py trade management)
- Risk governor bypass vectors (can any code path skip checks?)
- Broker/journal truth divergence (Alpaca state vs local DB)
- Fail-open safety checks (what happens when a safety query errors?)
- Kill switch integrity (atomic? stale? testable?)
**Runtime probes:** Executes `scripts/audit_probes.py` trading safety probes
**Critical context:** This is a live trading system. A silent failure here means real money at risk.

### 4.2 Code Quality

**Agent:** `code-quality-auditor`
**New agent** (no existing equivalent)
**Focus:**
- Functions exceeding 50 lines (project convention from past audits)
- Files exceeding 400 lines (project convention)
- God objects (classes with >20 methods or >10 state variables)
- Dead code (unused imports, unreachable branches, unused parameters)
- Duplicated logic (>70% similar blocks across files)
- Redundant inner imports shadowing module-level imports
**Files to prioritize:** `src/scheduler/watch.py` (3031 lines), `src/notifications/telegram.py` (1461 lines), `src/evaluation/system_validator.py` (949 lines)

### 4.3 Schema Integrity

**Agent:** `schema-integrity-auditor`
**Extends:** Existing `drift-detector` + `data-integrity-checker` agents
**Focus:**
- Run `python -m src.main validate-schema` and report drift
- DDL outside `src/schema/registry.py` (CI guardrail check)
- FK enforcement (PRAGMA foreign_keys status)
- Column drift between registry definitions and live DB
- Orphaned records (child rows referencing non-existent parents)
- Table row counts (empty tables that should have data)
**Runtime probes:** Executes schema validation commands, PRAGMA checks

### 4.4 Test Coverage

**Agent:** `test-coverage-auditor`
**Extends:** Existing `test-runner` agent
**Focus:**
- Run `python -m pytest tests/ -v --tb=short` and report results
- Test count vs CI minimum (1105 as of CLAUDE.md, 1301 as of MASTER.md)
- Identify critical paths with ZERO test coverage (risk governor, executor, reconciliation)
- Flag slow tests (>5 seconds, potential network leak or missing mock)
- Mock quality (are mocks realistic? do they test the right behavior?)
- Date-sensitive tests (known issue #49)
**Runtime probes:** Actually runs the test suite

### 4.5 Compliance

**Agent:** `compliance-auditor`
**New agent** (no existing equivalent)
**Focus:**
- CLAUDE.md rule violations:
  - Never commit secrets
  - Training data quality is #1
  - Risk governor is sacred
  - Test count must not drop
  - Mock all external APIs in tests
  - Schema registry is the single source of truth
- MASTER.md architectural rules:
  - Layer imports only go DOWN (Layer 4 → 3 → 2 → 1)
  - Config separation (YAML for non-secrets, .env for secrets)
  - Naming conventions (snake_case tables/columns, ISO 8601 timestamps)
- Checks each rule against the actual codebase with evidence

### 4.6 Comment & Documentation Accuracy

**Agent:** `comment-doc-auditor`
**New agent** (no existing equivalent)
**Focus:**
- Run `python scripts/verify_docs.py` for doc drift metrics
- MASTER.md Section 2 counts vs reality (Python files, tests, tables, pages, issues)
- Stale comments referencing removed code, renamed functions, or old schemas
- Misleading docstrings that describe different behavior than the code
- Architecture docs vs actual architecture (`docs/architecture.md` accuracy)
- README.md accuracy (commands, setup instructions, feature claims)
- Outdated TODOs and FIXMEs older than 30 days

### 4.7 Security

**Agent:** `security-auditor`
**Extends:** Existing `security-reviewer` agent
**Focus:**
- Credentials in tracked files (API keys, tokens, passwords in source)
- `.env` and `config/settings.local.yaml` gitignored correctly
- SQL injection in raw sqlite3 queries (f-string/format SQL construction)
- API authentication gaps (unprotected state-modifying routes)
- CORS configuration (appropriate origins)
- Dependency vulnerabilities (check `requirements.txt` for known CVEs)
- Input validation on API routes receiving user/external data
**Runtime probes:** Scans tracked files for secret patterns

### 4.8 Architecture

**Agent:** `architecture-auditor`
**New agent** (no existing equivalent)
**Focus:**
- Layer violations: imports going UP in the layer hierarchy
  - Layer 4 (Orchestration): watch.py, main.py
  - Layer 3 (Services): *_service.py, council/engine.py
  - Layer 2 (Domain): executor.py, governor.py, traffic_light.py, features/*, ranker.py
  - Layer 1 (Infrastructure): alpaca_adapter.py, telegram.py, render_sync.py, llm/client.py
- Circular imports (A imports B imports A)
- God objects and separation-of-concerns violations
- Module coupling (how many other modules does each module import?)
- Dependency direction (domain should not depend on infrastructure details)

## 5. Synthesis Agent

### 5.1 Purpose

The synthesis agent is the "brain" that transforms 8 independent finding sets into one cohesive audit. It runs AFTER all 8 domain agents complete.

### 5.2 Inputs

- All 8 domain agents' structured JSON findings
- `audit/audit_baseline.json` (known findings with issue numbers)
- `audit/audit_history.json` (previous audit scores and trends)
- GitHub issue inventory (`gh issue list --label audit --state all`)
- CLAUDE.md + MASTER.md (project rules for context)

### 5.3 Processing Steps

1. **Baseline classification**: For each finding, classify as:
   - `regression` — new finding not in baseline (will be filed)
   - `baseline_fail` — known finding already tracked (skip filing)
   - `improvement` — previously failing, now passing (close issue)
   - `pass` — no issue found (skip)

2. **Deduplication**: Group findings by `(file, line_range)`. Same location from multiple agents = merge into one finding, take highest severity, combine corrective actions, tag with all relevant domains.

3. **Root cause clustering**: Identify findings that share an underlying cause. Example: 5 findings in watch.py → one root cause issue about the god object.

4. **Cross-domain correlation**: Connect findings that span agents. Example: risk governor bypass (trading-safety) + no test for that path (test-coverage) + stale comment saying "tested" (comment-doc) = compound risk.

5. **Risk chain analysis**: Map cascading failure paths. Example: schema drift → stale query → empty result → wrong trading decision.

6. **Severity recalculation**: Adjust severity based on compound risk:
   - A medium finding becomes high when it intersects with a trading safety gap
   - A low finding stays low even if multiple agents flag it
   - Confidence level (high/medium/low) affects severity weighting

7. **Verification pass**: For each high/critical finding:
   - Read the actual file at the reported location
   - Confirm the issue exists as described
   - If unverifiable, downgrade to `unverified` status
   - Record verification evidence

8. **Health score computation**: Score each dimension 1-10 based on finding count and severity, compare to previous audit.

9. **Remediation prioritization**: Select top 5-7 items for "Fix This Week" based on `severity x impact x effort`. Include effort estimates (S/M/L) and dependency ordering.

### 5.4 Output

The synthesis agent returns:
- Classified, deduplicated, clustered finding list
- Issue creation/update/close instructions
- Health scores per dimension
- Executive summary (3 sentences)
- Quality gate determination (PASS/WARN/FAIL)
- Remediation priority list
- Delta from previous audit

## 6. Output Formats

### 6.1 Agent Finding Schema

Every domain agent wraps its output in:

```xml
<audit-findings>
{
  "domain": "trading-safety",
  "agent_version": "1.0.0",
  "timestamp": "2026-04-03T12:00:00Z",
  "findings": [
    {
      "id": "TS-001",
      "severity": "critical|high|medium|low",
      "confidence": "high|medium|low",
      "title": "Short descriptive title",
      "file": "src/path/to/file.py",
      "lines": "42-78",
      "description": "What is wrong and why it matters",
      "evidence": "Exact code snippet, command output, or test result proving the finding",
      "impact": "What breaks, what risk this creates, what degrades",
      "corrective_action": [
        "Step 1: specific action",
        "Step 2: specific action",
        "Step 3: how to verify the fix"
      ],
      "related_issues": [40, 42],
      "cwe": "CWE-XXX (if applicable)"
    }
  ],
  "files_scanned": ["src/path1.py", "src/path2.py"],
  "probes_executed": ["probe_name_1", "probe_name_2"],
  "summary": "One-paragraph domain summary"
}
</audit-findings>
```

### 6.2 GitHub Issue Types

**Finding Issue** (standalone):
```markdown
## [Audit] {Severity}: {Title}

**Domain:** {domain}
**File(s):** `{file}:{lines}`
**Confidence:** {high|medium|low}
**Detected:** {YYYY-MM-DD}
**Fingerprint:** `{sha256_hash}`

### Description
{description}

### Evidence
{evidence — code snippet, command output, or test result}

### Impact
{impact}

### Corrective Action
1. {step 1}
2. {step 2}
3. {verification step}

### Related
- Existing issues: #{numbers}
- Audit run: {audit date}
```

**Root Cause Issue** (explains multiple symptoms):
```markdown
## [Audit] {Severity}: {Title} [Root Cause]

**Domains:** {domain1}, {domain2}, ...
**Root cause for findings:** {finding IDs}
**Detected:** {YYYY-MM-DD}

### Pattern
{Description of the root cause and how it manifests across domains}

### Affected Findings
| ID | Domain | Severity | Title |
|---|---|---|---|

### Corrective Action
1. {step 1 — addresses root cause}
2. {step 2}
3. {verification — confirms all symptoms resolved}
```

**Systemic Issue** (recurring pattern):
```markdown
## [Audit] {Severity}: {Title} [Systemic]

**Domain:** {domain}
**Pattern:** {description of recurring pattern}
**Instances:** {count}
**Detected:** {YYYY-MM-DD}

### Affected Files
| File | Lines | Instance Description |
|---|---|---|

### Corrective Action
1. {bulk fix approach}
2. {prevention — how to stop this from recurring}
```

### 6.3 Summary Report

Written to `docs/audits/audit-YYYY-MM-DD.md`:

```markdown
# Repo Audit — {YYYY-MM-DD}

## Quality Gate: {PASS|WARN|FAIL}

## Executive Summary
{3 sentences: overall health, most important finding, trend direction}

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
1. {root cause + affected finding count}

### Risk Chains
1. {A -> B -> C -> consequence}

### Recurring Patterns
1. {pattern + instance count}

## Fix This Week (Top Priority)
| # | Severity | Effort | Title | Depends On |
|---|---|---|---|---|
| 1 | Critical | M | {title} | - |
| 2 | High | S | {title} | #1 |
...max 7 items...

## All Issues Filed
| # | Type | Severity | Domain(s) | Title | Status |
|---|---|---|---|---|---|
| {gh#} | Finding | High | trading | {title} | Created |
| {gh#} | Root Cause | High | arch, quality | {title} | Created |
| {gh#} | - | Medium | schema | {title} | Closed (resolved) |

## Delta from Previous Audit ({previous_date})
- Resolved: {count} findings
- New: {count} findings
- Recurring: {count} findings ({count} with changed severity)
- Health score change: {previous} -> {current} ({delta})

## Agent Coverage
| Agent | Files Scanned | Findings | Probes Run |
|---|---|---|---|
| trading-safety | {count} | {count} | {count} |
...

## Methodology
- Audit tool: halcyon-audit plugin v1.0.0
- Domain agents: 8 (model: sonnet, maxTurns: 30)
- Synthesis agent: 1 (model: opus/inherit)
- Baseline: audit/audit_baseline.json ({count} known findings)
- Previous audit: {date} ({path})
```

## 7. Quality Gate Definition

| Gate | Criteria | Action |
|---|---|---|
| **PASS (GREEN)** | Zero critical, zero new high, overall health >= 7.0 | No immediate action required |
| **WARN (YELLOW)** | Zero critical AND (<=2 new high OR health 5.0-6.9) | Review findings, plan remediation |
| **FAIL (RED)** | Any critical finding OR >2 new high OR health < 5.0 | Immediate remediation required |

## 8. Baseline Management

### 8.1 Baseline File: `audit/audit_baseline.json`

```json
{
  "version": "1.0.0",
  "last_updated": "2026-04-03",
  "known_findings": [
    {
      "fingerprint": "sha256_hash",
      "domain": "trading-safety",
      "title": "Short title",
      "severity": "high",
      "issue_number": 42,
      "first_detected": "2026-03-29",
      "reason": "Why this is a known/accepted finding"
    }
  ]
}
```

### 8.2 Classification Logic

For each finding from domain agents:
1. Compute fingerprint: `sha256(domain + file + line_range + title_normalized)`
2. Look up fingerprint in baseline:
   - **Found + still failing** → `baseline_fail` (skip issue creation, note in report)
   - **Found + now passing** → `improvement` (close linked issue, note in report)
   - **Not found** → `regression` (create new issue)
3. After audit, offer to add new findings to baseline if they're accepted/deferred

### 8.3 History File: `audit/audit_history.json`

```json
{
  "runs": [
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
      "finding_counts": {
        "critical": 0,
        "high": 3,
        "medium": 12,
        "low": 8
      },
      "issues_created": 6,
      "issues_closed": 2,
      "report_path": "docs/audits/audit-2026-04-03.md"
    }
  ]
}
```

## 9. Idempotent Issue Management

### 9.1 Fingerprinting

Each finding gets a deterministic fingerprint:
```
fingerprint = sha256(domain + file + normalized_line_range + normalized_title)
```

`normalized_title` = lowercase, strip whitespace, remove articles.
`normalized_line_range` = round to nearest 10-line block (tolerates minor code shifts).

### 9.2 Issue Lifecycle

Before creating issues, the orchestrator fetches:
```bash
gh issue list --label audit --state all --json number,title,state,labels,body --limit 200
```

For each finding:
1. Extract fingerprint from finding
2. Search existing issues for matching `Fingerprint:` in body
3. **Match found + issue open** → Update issue body if severity/description changed
4. **Match found + issue closed** → Reopen if finding recurred
5. **No match** → Create new issue with labels: `audit`, `{severity}`, `{domain}`

For resolved findings (in baseline but no longer detected):
1. Find the linked issue by number
2. Add comment: "Resolved in audit {date}. Verified by {agent}."
3. Close issue

### 9.3 Label Setup

On first run, ensure labels exist:
```bash
gh label create audit --color 0E8A16 --force
gh label create critical --color B60205 --force
gh label create high --color D93F0B --force
gh label create medium --color FBCA04 --force
gh label create low --color 0075CA --force
gh label create trading-safety --color 5319E7 --force
gh label create code-quality --color 5319E7 --force
gh label create schema-integrity --color 5319E7 --force
gh label create test-coverage --color 5319E7 --force
gh label create compliance --color 5319E7 --force
gh label create documentation --color 5319E7 --force
gh label create security --color 5319E7 --force
gh label create architecture --color 5319E7 --force
gh label create root-cause --color C2E0C6 --force
gh label create systemic --color C2E0C6 --force
```

## 10. Command Interface

### 10.1 Usage

```
/audit                           # Full audit, all 8 domains
/audit trading,security          # Only specified domains
/audit --quick                   # Skip code-quality and comment-doc (noisiest)
/audit --baseline-only           # Only check regressions against baseline
```

### 10.2 Domain Names (for filtering)

`trading`, `quality`, `schema`, `tests`, `compliance`, `docs`, `security`, `architecture`

### 10.3 Prerequisites

- `gh` CLI authenticated (`gh auth status`)
- Git repository with remote configured
- For uninterrupted execution: Shift+Tab to enable auto-accept before running

### 10.4 Terminal Output

```
======================================
  AUDIT QUALITY GATE: WARN (YELLOW)
======================================

Executive Summary:
Overall health 6.5/10, down from 7.2. Two new high-severity findings in
trading safety (silent failure in executor, risk governor state query).
Schema integrity improved to 9/10 after registry adoption.

Health Scores:
  Trading Safety:    7/10  (-->)
  Code Quality:      5/10  (-->)
  Schema Integrity:  9/10  (^)
  Test Coverage:     7/10  (-->)
  Compliance:        8/10  (^)
  Documentation:     6/10  (v)
  Security:          8/10  (-->)
  Architecture:      5/10  (-->)

Issues: 6 created, 2 closed, 8 baseline
Report: docs/audits/audit-2026-04-03.md

Fix This Week:
  1. [High]  Fix silent failure in executor error path (S)
  2. [High]  Add risk governor state query timeout (S)
  3. [High]  Extract scan_runner from watch.py (L) -- root cause for 5 findings
```

## 11. Integration Points

### 11.1 Existing Project Agents

The audit agents reference and extend the 6 existing agents:

| Audit Agent | Extends | Extension |
|---|---|---|
| trading-safety-auditor | security-reviewer | Adds execution path probes, broker truth checks |
| schema-integrity-auditor | drift-detector, data-integrity-checker | Adds cross-domain correlation, registry compliance |
| test-coverage-auditor | test-runner | Adds coverage gap analysis, mock quality review |
| security-auditor | security-reviewer | Adds dependency scanning, CORS review |
| code-quality-auditor | (new) | - |
| compliance-auditor | (new) | - |
| comment-doc-auditor | (new) | - |
| architecture-auditor | (new) | - |

Each extending agent's prompt begins with: "You perform the same checks as the existing {agent_name} agent (read its definition at .claude/agents/{agent_name}.md for reference), PLUS the following audit-specific checks..."

### 11.2 Daily CI Audit

- Both systems write to `audit/state.json` in compatible format
- The daily audit's `config/daily_repo_audit_baseline.json` is separate from the `/audit` baseline (`audit/audit_baseline.json`) — they serve different scopes
- The `/audit` report references recent daily audit results for trend context

### 11.3 Existing Scripts

| Script | How /audit uses it |
|---|---|
| `scripts/daily_repo_audit.py` | Read probe patterns for trading-safety probes |
| `scripts/verify_docs.py` | Run by comment-doc-auditor for doc drift |
| `scripts/check_config.py` | Run by compliance-auditor for config drift |

## 12. Plugin Agent Constraints

Per Claude Code docs, plugin subagents do NOT support:
- `hooks` frontmatter field (ignored)
- `mcpServers` frontmatter field (ignored)
- `permissionMode` frontmatter field (ignored)
- `memory` frontmatter field (ignored)

**Mitigations:**
- Use explicit `tools:` field to specify allowed tools (Read, Grep, Glob, Bash)
- Document that users should enable auto-accept (Shift+Tab) before running
- For persistent memory: document how to copy the synthesis agent to `.claude/agents/` after first use and add `memory: local`
- MCP tools (Alpaca) are inherited from the parent session, so audit agents CAN use Alpaca for position checks

## 13. Cost & Performance

| Component | Model | Est. Turns | Est. Tokens |
|---|---|---|---|
| 8 domain agents | sonnet | ~20 each | ~200K each |
| 1 synthesis agent | inherit (opus) | ~30 | ~500K |
| Orchestrator | parent session | ~10 | ~100K |
| **Total** | | | **~2.2M tokens** |

Estimated wall-clock time: 5-10 minutes (parallel domain agents + sequential synthesis).

Domain agents run as background tasks. The orchestrator waits for all 8 to complete before dispatching the synthesis agent.

## 14. File Inventory

Files created/modified by this plugin:

| File | Action | Purpose |
|---|---|---|
| `.claude/plugins/halcyon-audit/.claude-plugin/plugin.json` | Create | Plugin manifest |
| `.claude/plugins/halcyon-audit/commands/audit.md` | Create | /audit command |
| `.claude/plugins/halcyon-audit/agents/*.md` | Create (9) | Domain + synthesis agents |
| `.claude/plugins/halcyon-audit/skills/audit-orchestrator/SKILL.md` | Create | Orchestration logic |
| `.claude/plugins/halcyon-audit/skills/audit-orchestrator/references/*.md` | Create (3) | Supporting docs |
| `audit/audit_baseline.json` | Create | Baseline findings |
| `audit/audit_history.json` | Create | Audit trend data |
| `docs/audits/audit-YYYY-MM-DD.md` | Create (per run) | Audit reports |

## 15. Success Criteria

The plugin is complete when:

1. `/audit` dispatches all 8 agents and produces a synthesized report
2. Findings are filed as GitHub issues with correct labels and templates
3. Running `/audit` twice does NOT create duplicate issues
4. Known findings from baseline are correctly classified
5. The quality gate produces a clear PASS/WARN/FAIL signal
6. The report includes a "Fix This Week" prioritized list
7. Health scores are tracked across runs in audit_history.json
8. Domain filtering works (`/audit trading,security`)
9. The `--quick` flag skips code-quality and comment-doc
10. All 8 agents return structured JSON in the specified schema
