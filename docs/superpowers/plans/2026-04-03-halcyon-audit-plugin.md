# Halcyon Audit Plugin Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create a project-local Claude Code plugin that provides a `/audit` command dispatching 8 parallel domain agents + 1 synthesis agent to produce baseline-aware, quality-gated repo audits with GitHub issue filing.

**Architecture:** Three-phase scatter-gather-report model. Phase 1 dispatches 8 domain-specific agents (sonnet, background, maxTurns 30) that return structured JSON findings. Phase 2 dispatches a synthesis agent (inherit model) that deduplicates, clusters root causes, correlates cross-domain, verifies evidence, computes health scores, and determines the quality gate. Phase 3 (orchestrator skill) files GitHub issues idempotently, writes the summary report, updates history, and prints the terminal summary.

**Tech Stack:** Claude Code plugin system (markdown agents, SKILL.md, commands), `gh` CLI for GitHub issues, Python for audit probes, JSON for state files.

**Spec:** `docs/superpowers/specs/2026-04-03-halcyon-audit-plugin-design.md`

---

## File Structure

```
Files to CREATE:
  .claude/plugins/halcyon-audit/.claude-plugin/plugin.json
  .claude/plugins/halcyon-audit/commands/audit.md
  .claude/plugins/halcyon-audit/agents/trading-safety-auditor.md
  .claude/plugins/halcyon-audit/agents/code-quality-auditor.md
  .claude/plugins/halcyon-audit/agents/schema-integrity-auditor.md
  .claude/plugins/halcyon-audit/agents/test-coverage-auditor.md
  .claude/plugins/halcyon-audit/agents/compliance-auditor.md
  .claude/plugins/halcyon-audit/agents/comment-doc-auditor.md
  .claude/plugins/halcyon-audit/agents/security-auditor.md
  .claude/plugins/halcyon-audit/agents/architecture-auditor.md
  .claude/plugins/halcyon-audit/agents/audit-synthesizer.md
  .claude/plugins/halcyon-audit/skills/audit-orchestrator/SKILL.md
  .claude/plugins/halcyon-audit/skills/audit-orchestrator/references/finding-schema.md
  .claude/plugins/halcyon-audit/skills/audit-orchestrator/references/issue-templates.md
  .claude/plugins/halcyon-audit/skills/audit-orchestrator/references/quality-gate.md
  audit/audit_baseline.json
  audit/audit_history.json
```

---

### Task 1: Plugin Manifest and Directory Scaffold

**Files:**
- Create: `.claude/plugins/halcyon-audit/.claude-plugin/plugin.json`
- Create: `audit/audit_baseline.json`
- Create: `audit/audit_history.json`

- [ ] **Step 1: Create directory structure**

```bash
mkdir -p ".claude/plugins/halcyon-audit/.claude-plugin"
mkdir -p ".claude/plugins/halcyon-audit/commands"
mkdir -p ".claude/plugins/halcyon-audit/agents"
mkdir -p ".claude/plugins/halcyon-audit/skills/audit-orchestrator/references"
```

- [ ] **Step 2: Write plugin manifest**

Write `.claude/plugins/halcyon-audit/.claude-plugin/plugin.json`:

```json
{
  "name": "halcyon-audit",
  "version": "1.0.0",
  "description": "Comprehensive repo audit with 8 parallel domain agents, synthesis, and GitHub issue filing",
  "author": {
    "name": "millerrc18"
  }
}
```

- [ ] **Step 3: Write initial baseline file**

Write `audit/audit_baseline.json`:

```json
{
  "version": "1.0.0",
  "last_updated": "2026-04-03",
  "known_findings": []
}
```

- [ ] **Step 4: Write initial history file**

Write `audit/audit_history.json`:

```json
{
  "runs": []
}
```

- [ ] **Step 5: Verify and commit**

```bash
find .claude/plugins/halcyon-audit -type f | sort
ls audit/audit_baseline.json audit/audit_history.json
git add .claude/plugins/halcyon-audit/.claude-plugin/plugin.json audit/audit_baseline.json audit/audit_history.json
git commit -m "feat(audit): scaffold halcyon-audit plugin with manifest and state files"
```

---

### Task 2: Reference Documents (Finding Schema, Issue Templates, Quality Gate)

**Files:**
- Create: `.claude/plugins/halcyon-audit/skills/audit-orchestrator/references/finding-schema.md`
- Create: `.claude/plugins/halcyon-audit/skills/audit-orchestrator/references/issue-templates.md`
- Create: `.claude/plugins/halcyon-audit/skills/audit-orchestrator/references/quality-gate.md`

- [ ] **Step 1: Write finding-schema.md**

Copy the finding schema from spec Section 6.1. Include field rules, domain prefixes, and the complete JSON structure. See the full content in the plan body above (Task 2, Step 1).

- [ ] **Step 2: Write issue-templates.md**

Copy the 3 issue templates (Finding, Root Cause, Systemic) from spec Section 6.2. Include deduplication and close instructions. See the full content in the plan body above (Task 2, Step 2).

- [ ] **Step 3: Write quality-gate.md**

Copy the gate definitions from spec Section 7. Include health score computation, trend arrows, and label setup commands. See the full content in the plan body above (Task 2, Step 3).

- [ ] **Step 4: Commit**

```bash
git add .claude/plugins/halcyon-audit/skills/audit-orchestrator/references/
git commit -m "feat(audit): add finding schema, issue templates, and quality gate references"
```

---

### Task 3: Trading Safety Auditor Agent

**Files:** Create `.claude/plugins/halcyon-audit/agents/trading-safety-auditor.md`

Agent checks: silent failures in execution paths, risk governor bypass vectors, broker/journal truth divergence, fail-open safety checks, kill switch integrity. Includes runtime probes (AST scan for bare excepts in trading code). Extends existing `security-reviewer` agent. Uses domain prefix `TS-`. Full content in plan body above.

- [ ] **Step 1: Write agent file**
- [ ] **Step 2: Commit** — `git commit -m "feat(audit): add trading-safety-auditor agent"`

---

### Task 4: Code Quality Auditor Agent

**Files:** Create `.claude/plugins/halcyon-audit/agents/code-quality-auditor.md`

Agent checks: oversized files (>400 lines), oversized functions (>50 lines), god objects, dead code/unused imports, duplicated logic, redundant inner imports. Includes Python AST probes for all checks. Uses domain prefix `CQ-`. Full content in plan body above.

- [ ] **Step 1: Write agent file**
- [ ] **Step 2: Commit** — `git commit -m "feat(audit): add code-quality-auditor agent"`

---

### Task 5: Schema Integrity Auditor Agent

**Files:** Create `.claude/plugins/halcyon-audit/agents/schema-integrity-auditor.md`

Agent checks: schema drift (runs validate-schema), DDL outside registry, FK enforcement, table row counts, column drift, orphaned records. Extends existing `drift-detector` + `data-integrity-checker` agents. Uses domain prefix `SI-`. Full content in plan body above.

- [ ] **Step 1: Write agent file**
- [ ] **Step 2: Commit** — `git commit -m "feat(audit): add schema-integrity-auditor agent"`

---

### Task 6: Test Coverage Auditor Agent

**Files:** Create `.claude/plugins/halcyon-audit/agents/test-coverage-auditor.md`

Agent checks: full pytest run, test count vs CI minimum, critical path coverage gaps, slow tests, network leak detection, mock quality review. Extends existing `test-runner` agent. Uses domain prefix `TC-`. Full content in plan body above.

- [ ] **Step 1: Write agent file**
- [ ] **Step 2: Commit** — `git commit -m "feat(audit): add test-coverage-auditor agent"`

---

### Task 7: Compliance Auditor Agent

**Files:** Create `.claude/plugins/halcyon-audit/agents/compliance-auditor.md`

Agent checks: every CLAUDE.md rule (secrets, risk governor, test count, mocking, schema registry), every MASTER.md rule (layer imports, config separation, naming conventions). Includes layer violation scanner. Uses domain prefix `CM-`. Full content in plan body above.

- [ ] **Step 1: Write agent file**
- [ ] **Step 2: Commit** — `git commit -m "feat(audit): add compliance-auditor agent"`

---

### Task 8: Comment & Documentation Auditor Agent

**Files:** Create `.claude/plugins/halcyon-audit/agents/comment-doc-auditor.md`

Agent checks: doc drift (runs verify_docs.py), MASTER.md Section 2 accuracy, stale TODOs/FIXMEs, stale comments, architecture doc accuracy, README accuracy. Uses domain prefix `CD-`. Full content in plan body above.

- [ ] **Step 1: Write agent file**
- [ ] **Step 2: Commit** — `git commit -m "feat(audit): add comment-doc-auditor agent"`

---

### Task 9: Security Auditor Agent

**Files:** Create `.claude/plugins/halcyon-audit/agents/security-auditor.md`

Agent checks: credential exposure, gitignore verification, SQL injection (f-string SQL), API auth gaps, CORS config, dependency vulnerabilities, input validation. Extends existing `security-reviewer` agent. Uses domain prefix `SE-`. Full content in plan body above.

- [ ] **Step 1: Write agent file**
- [ ] **Step 2: Commit** — `git commit -m "feat(audit): add security-auditor agent"`

---

### Task 10: Architecture Auditor Agent

**Files:** Create `.claude/plugins/halcyon-audit/agents/architecture-auditor.md`

Agent checks: layer violations (imports going UP), circular imports (DFS cycle detection), module coupling (import count), separation of concerns. Uses MASTER.md layer hierarchy. Uses domain prefix `AR-`. Full content in plan body above.

- [ ] **Step 1: Write agent file**
- [ ] **Step 2: Commit** — `git commit -m "feat(audit): add architecture-auditor agent"`

---

### Task 11: Audit Synthesizer Agent

**Files:** Create `.claude/plugins/halcyon-audit/agents/audit-synthesizer.md`

The synthesis brain. 11-step processing pipeline: parse findings, baseline classification, deduplication, root cause clustering, cross-domain correlation, risk chain analysis, severity recalculation, verification pass, health score computation, quality gate determination, remediation prioritization. Uses `model: inherit`, `effort: max`, `maxTurns: 40`. Returns `<audit-synthesis>` JSON. Full content in plan body above.

- [ ] **Step 1: Write agent file**
- [ ] **Step 2: Commit** — `git commit -m "feat(audit): add audit-synthesizer agent"`

---

### Task 12: Audit Orchestrator Skill

**Files:** Create `.claude/plugins/halcyon-audit/skills/audit-orchestrator/SKILL.md`

The orchestration logic: Phase 0 (prerequisites, labels, context gathering), Phase 1 (parallel agent dispatch), Phase 2 (synthesis dispatch), Phase 3 (issue filing, report writing, state updates, terminal output, baseline offer). Handles argument parsing for domain filtering, --quick, --baseline-only. Full content in plan body above.

- [ ] **Step 1: Write skill file**
- [ ] **Step 2: Commit** — `git commit -m "feat(audit): add audit-orchestrator skill"`

---

### Task 13: /audit Command

**Files:** Create `.claude/plugins/halcyon-audit/commands/audit.md`

Entry point that describes usage and invokes the audit-orchestrator skill. Accepts optional domain arguments. Full content in plan body above.

- [ ] **Step 1: Write command file**
- [ ] **Step 2: Commit** — `git commit -m "feat(audit): add /audit command entry point"`

---

### Task 14: Verify and Final Commit

- [ ] **Step 1: Verify file structure**

```bash
find .claude/plugins/halcyon-audit -type f | sort
```

Expected: 15 files (1 manifest, 9 agents, 1 command, 1 skill, 3 references).

- [ ] **Step 2: Verify JSON validity**

```bash
python -c "import json; json.load(open('.claude/plugins/halcyon-audit/.claude-plugin/plugin.json')); print('manifest OK')"
python -c "import json; json.load(open('audit/audit_baseline.json')); print('baseline OK')"
python -c "import json; json.load(open('audit/audit_history.json')); print('history OK')"
```

- [ ] **Step 3: Verify frontmatter on all agents**

```bash
for f in .claude/plugins/halcyon-audit/agents/*.md; do
  echo -n "$f: "
  head -1 "$f" | grep -q "^---" && echo "OK" || echo "MISSING FRONTMATTER"
done
```

- [ ] **Step 4: Final commit**

```bash
git add -A .claude/plugins/halcyon-audit/ audit/
git commit -m "feat(audit): complete halcyon-audit plugin v1.0.0

Implements docs/superpowers/specs/2026-04-03-halcyon-audit-plugin-design.md.
8 domain agents, 1 synthesis agent, orchestrator skill, /audit command.
Baseline-aware, quality-gated, with idempotent GitHub issue filing."
```

- [ ] **Step 5: Notify user about activation**

Tell user: restart Claude Code session, then run `/audit --quick` for first test.
