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
- **Anti-fallacy playbook** — PM monitors for 24 known sub-agent failure patterns with prescribed responses
- **Selective review** — QA always runs; Security and Performance dispatched based on what the task touches
- **Progress dashboard** — Live HTML dashboard with task graph, PM notes, scorecard, and agent activity

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
