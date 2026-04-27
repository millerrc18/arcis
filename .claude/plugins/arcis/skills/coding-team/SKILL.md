---
name: coding-team
description: Autonomous multi-agent implementation with PM orchestrator, parallel developers, specialized reviewers (QA/Security/Performance), regression prevention, and scope control
---

# Coding Team

This skill provides the `/arcis:code` command for autonomous, large-scope implementation with hierarchical agent coordination.

## Approach: Project Manager Model

1. **INTAKE** — Parse arguments, read spec/plan, assess scope
2. **PLAN** — Dispatch Planner to generate dependency-aware task graph with scope fences (skip if `--plan` provided)
3. **EXECUTE** — Dispatch Developers in dependency order (parallel where independent)
4. **REVIEW** — Per-task: dispatch relevant specialized Reviewers, loop until clean
5. **DOCUMENT** — Dispatch Documentarian to update docs/README/CHANGELOG
6. **INTEGRATE** — Dispatch Integrator for final regression sweep
7. **REPORT** — PM produces summary with scorecard

## Agent Hierarchy

```
Coding PM (command orchestrator, opus)
├── Coding Planner (opus, maxTurns:6)
│   — Generates task graph with dependencies, scope fences, test strategy
├── Coding Developers (parallel, sonnet, maxTurns:12 each)
│   — TDD: failing test → implement → full suite → commit
├── Coding Reviewers (parallel, opus, maxTurns:4 each)
│   ├── QA Reviewer — spec compliance, scope violations, test coverage
│   ├── Security Reviewer — OWASP top 10, injection, auth, secrets
│   └── Performance Reviewer — complexity, N+1, concurrency, blocking I/O
├── Coding Documentarian (sonnet, maxTurns:6)
│   — Updates docs based on change manifest
└── Coding Integrator (opus, maxTurns:6)
    — Final regression sweep, cross-file consistency
```

## Key Properties

- **Regression prevention** — 3 layers: cumulative test gates, context propagation via change manifest, Integrator sweep
- **Scope control** — 3 checkpoints: Planner scope fences, QA Reviewer scope check, Integrator diff audit
- **Anti-fallacy playbook** — PM monitors for 29 known sub-agent failure patterns with prescribed responses
- **Selective review** — QA always runs; Security and Performance dispatched based on what the task touches
- **Progress dashboard** — Live HTML dashboard with task graph, PM notes, scorecard, and agent activity
- **Worktree isolation** — Developers run in `git worktree add`-isolated branches by default; first tool use must verify cwd (see Delivery Discipline below)
- **Delivery checkpoints** — commit-and-push after each sub-deliverable; PR body regenerated from final git log post-commits

## Delivery Discipline

Lessons learned from Sprint 0 / 0.B / 0.C dispatches (2026-04-26 to 2026-04-27). PM bakes these into every Developer brief; Developers verify on first tool use.

### 1. Worktree isolation verification (mandatory first tool use)

Every Developer's first action must be:

```bash
pwd                                # expected: under .claude/worktrees/agent-X/
git rev-parse --show-toplevel      # expected: same worktree path, NOT main repo
git branch --show-current          # expected: assigned themed branch OR auto-named worktree branch
```

If any of those don't match the assignment, refuse to proceed and report. **Evidence:** Sprint 0.C C.4 + C.5 ran without isolation; both wrote to the main repo working tree, leaving it on a feature branch with mixed-agent uncommitted changes (race incident 2026-04-27 06:05 UTC). PM had to stash and recover.

### 2. Commit-and-push per sub-deliverable

When task scope contains ≥3 sub-deliverables (multiple trackers, multiple themed files, multiple domains), commit AND push after each sub-deliverable lands — do not batch the final "verify + push + PR open" at the end. **Evidence:** B2.4 (6 refactors), B2.6 (8 trackers), C.1 first agent (200 sites), C.1 cont, C.5 cont — 5 budget exhaustions in 2 days, all stranded at the verify→push→PR stage. Per-deliverable push converts "complete-but-stranded" failure into "partial-but-shipped".

For very large mechanical scopes (50+ sites), commit per N=10-15 sites or per logical domain.

### 3. PR body regenerated from final git log

Developer writes the PR body LAST, after all commits land, by reading `git log main..HEAD` and `git diff main..HEAD --stat`. Optimistic-pre-written PR bodies (drafted during planning, never updated) cause scope-drift between claims and code. **Evidence:** PR #739 claimed "NO known_violations.json mutation" but the diff showed entries removed; PR #747 claimed "all ~200 sites migrated" but only 156 actually shipped.

### 4. Pre-existing failure canon

Reference `docs/audits/known-pre-existing-failures.md` rather than independently rediscovering the same documented failures. PR body says "no NEW failures introduced; documented list unchanged" if that's true. **Evidence:** Same 4 pre-existing failures (`test_full_pipeline_when_broker_exception_during_exit`, `test_site6_emergency_close_sdk_missing_persists`, `test_no_file_over_400_lines`, `test_no_function_over_60_lines`) re-flagged in 8+ separate PR review bodies during Sprint 0.

### 5. Sibling-search rule

When a fix targets `file:line`, GREP `file` for the same anti-pattern at other lines BEFORE submitting. **Evidence:** Sprint 0 Cluster 8 review caught Win Rate at line 443 but missed Training Examples at line 445 (same anti-pattern, 2 lines apart). Sibling search would have caught it.

### 6. test_repo_structure.py disclosure

Developer runs `python -m pytest tests/test_repo_structure.py -v` as part of verification and discloses any new violations in strict-rigor receipts. **Evidence:** PR #717 shipped `promotion_gate.py` at 573 lines without disclosure; surfaced post-merge by PR #729 review. Sprint 0.B PR #735 split via real refactor (not grandfather entry).

### 7. Line-ending preservation (Windows)

On Windows with `core.autocrlf=true` and 71+ legacy CRLF-indexed files, the Edit/Write tools may normalize CRLF→LF on write, producing massive line-ending diffs that obscure substantive changes. Two mitigations:
- Prefer `sed -i 's/X/Y/g' file.py` via Bash for mechanical text replacements
- For repository-wide normalization, propose `.gitattributes` with `*.py text eol=lf`

**Evidence:** PR #747 has +9549/-9403 diff, of which only ~1500 lines is substantive (~156 connect_db swaps); the rest is line-ending churn from 71 legacy CRLF-indexed files.

## Reviewer Dispatch Logic

| Task touches... | QA | Security | Performance |
|----------------|-----|----------|-------------|
| API endpoints, auth, user input | Yes | Yes | Yes |
| Data models, database queries | Yes | No | Yes |
| Business logic, algorithms | Yes | No | Yes |
| Frontend/UI components | Yes | No | No |
| Config, env, infrastructure | Yes | Yes | No |
| Documentation only | No | No | No |

## Arguments

| Flag | Purpose |
|------|---------|
| `--plan <path>` | Execute an existing plan file (skip internal planning) |
| `--spec <path>` | Generate plan from a design spec |
| `--files <paths...>` | Hard scope fence to specific files/directories |
| `--model opus` | Upgrade Developers from sonnet to opus |
| `--no-docs` | Skip Documentarian |
| `--dry-run` | Generate plan only, don't execute |
| `--sequential` | Force sequential Developer dispatch |
