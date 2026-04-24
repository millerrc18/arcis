---
name: design-team
description: Idea-to-spec pipeline with codebase-grounded analysis, structured interviewing, feasibility validation, and adversarial stress-testing — produces specs and plans consumable by /arcis:code
---

# Design Team

This skill provides the `/arcis:design` command for transforming ideas or existing artifacts into codebase-grounded design specs and implementation plans.

## Approach: Adaptive Analysis Pipeline

1. **INTAKE** — Parse input, detect mode (blank idea / artifact / iteration), detect greenfield
2. **SCOUT** — Quick architecture-level codebase scan (skip if greenfield)
3. **INTERVIEW** — Director elicits requirements using codebase-aware questions
4. **ANALYZE** — Targeted deep codebase analysis on areas requirements touch (skip if greenfield)
5. **CHECKPOINT** — User approves requirements + analysis summary before design
6. **DESIGN** — Architect produces spec + implementation plan grounded in codebase reality
7. **REVIEW** — Sequential fail-fast: Feasibility Reviewer → Devil's Advocate
8. **OUTPUT** — Write spec + plan files, commit, present handoff command

## Agent Hierarchy

```
Design Director (command orchestrator + interviewer, opus)
├── Codebase Analyst (opus, maxTurns:10)
│   — Surface scan (SCOUT) + targeted deep analysis (ANALYZE)
│   — Adaptive depth: architecture-level → component-level → execution-path tracing
├── Architect (opus, maxTurns:10)
│   — Produces design spec + task_graph implementation plan
│   — Receives RAW codebase reports (not summaries)
├── Feasibility Reviewer (opus, maxTurns:4)
│   — Verifies design against real codebase (files, interfaces, dependencies)
│   — REJECT / REQUEST_CHANGES / PASS
└── Devil's Advocate (opus, maxTurns:4, no tools)
    — Pure reasoning stress-test: ambiguities, edge cases, missing requirements
    — Tests spec self-containment (if reviewer can't understand without code, spec is incomplete)
```

## Key Properties

- **All opus** — design work is pure reasoning; no cost-optimized models
- **Adaptive analysis** — surface scan informs interview, interview targets deep analysis
- **Sequential fail-fast review** — Feasibility first; Devil's Advocate only if feasible
- **No-tool Devil's Advocate** — tests whether the spec is self-contained
- **Direct handoff** — plan uses `/arcis:code` task_graph schema for seamless execution
- **Three input modes** — blank idea, existing artifact, spec iteration

## Input Modes

| Mode | Trigger | Behavior |
|------|---------|----------|
| Blank idea | Natural language description | Full discovery interview |
| Existing artifact | File path, URL, or structured requirements | Targeted clarification |
| Iteration | Previous spec path + change requests | Delta-focused interview |

## Conditional Logic

| Condition | Effect |
|-----------|--------|
| Greenfield (no source files) | Skip SCOUT + ANALYZE + Feasibility Reviewer |
| Trivial complexity (≤2 files) | Skip Devil's Advocate |
| `--spec-only` | Skip implementation plan generation |
| `--skip-review` | Skip REVIEW phase entirely |

## Arguments

| Flag | Purpose |
|------|---------|
| `<positional>` | Feature idea, artifact path, or URL |
| `--codebase <path>` | Target codebase root (default: cwd) |
| `--spec-only` | Produce spec without implementation plan |
| `--skip-review` | Skip REVIEW phase |
| `--out <path>` | Custom output directory for spec + plan |
