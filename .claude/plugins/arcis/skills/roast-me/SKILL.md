---
name: roast-me
description: Adversarial critique of any artifact — research, code, designs, plans, proposals — using Prosecutor vs. Defense vs. Judge debate model
autoTrigger: true
---

# Roast Me

This skill provides the `/arcis:roast` command for adversarial critical analysis of any artifact.

## Approach: Adversarial Debate Model

1. **INTAKE** — Receive artifact, detect type, normalize into brief
2. **DISPATCH** — Prosecutor and Defense agents run in parallel (independent, no shared context)
3. **JUDGE** — Judge receives both briefs, weighs each charge, produces severity-ranked verdict
4. **REPORT** — Director formats the final roast report

## Agent Hierarchy

```
Roast Director (command orchestrator, opus)
├── Roast Prosecutor (opus, maxTurns:8)
│   — Finds every flaw, gap, weakness, logical fallacy
│   — Produces structured indictment with severity-ranked charges
├── Roast Defense (opus, maxTurns:8)
│   — Steelmans the artifact, finds genuine strengths
│   — Anticipates weaknesses and pre-builds defenses
└── Roast Judge (opus, maxTurns:4, no tools)
    — Weighs Prosecutor charges against Defense briefs
    — Rules: sustained, partially sustained, dismissed, insufficient evidence
```

## Key Properties

- **All opus** — critique requires maximum analytical depth, no cost-saving tier
- **Independent briefs** — Prosecutor and Defense don't see each other's work
- **Polymorphic** — auto-detects artifact type and calibrates critique lens
- **Structured verdict** — every charge has evidence, defense, ruling, and recommendation
- **`--compare` mode** — roast artifact A against reference artifact B

## Artifact Type Detection

| Artifact Type | Detection Signal | Critique Lens |
|---------------|-----------------|---------------|
| ARCIS research output | `<findings>` tags or findings JSON schema | Evidence quality, confidence calibration, source gaps |
| Code | File extensions or fenced code blocks | Bugs, security, performance, maintainability |
| Design spec | Architecture/Components/Data flow sections | Feasibility, missing requirements, assumptions |
| Implementation plan | Task checkboxes, file paths, steps | Missing steps, wrong ordering, untestable tasks |
| Proposal / strategy | Goals, stakeholders, timelines, risks | Logical fallacies, unsupported claims, missing alternatives |
| Freeform | None of the above | General: logic, evidence, completeness, assumptions |

## Severity Calibration

| Level | Definition |
|-------|-----------|
| Critical | Would cause failure, data loss, security breach, or fundamental misalignment |
| Major | Significant gap requiring rework if not addressed before implementation |
| Minor | Real issue but bounded impact; addressable during implementation |
| Nit | Style, preference, or theoretical concern; not immediately actionable |

## Arguments

| Flag | Purpose |
|------|---------|
| `--file <path>` | Roast a specific file or directory |
| `--url <url>` | Fetch and roast web content |
| `--severity <level>` | Filter output to show only findings at or above this level |
| `--focus <category>` | Bias Prosecutor toward: logic, evidence, security, feasibility, completeness, consistency |
| `--compare <path>` | Roast primary artifact against a reference artifact |
