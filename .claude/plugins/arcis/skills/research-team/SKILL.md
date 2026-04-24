---
name: research-team
description: Hierarchical multi-agent research with adaptive complexity scoring, domain-specialized agents, and dialectical synthesis
---

# Research Team

This skill provides the `/arcis:research` command for deep, multi-agent research.

## Approach: Research Director Model

1. **CLASSIFY** — Score query complexity via trial search; route simple queries directly, delegate complex ones
2. **CLARIFY** — Identify ambiguities and confirm scope, domain, and output format before dispatching
3. **DECOMPOSE** — Break complex queries into domain-specific sub-questions for parallel investigation
4. **CHECKPOINT** — Confirm decomposition plan with user before spawning agents (avoids wasted effort)
5. **DISPATCH** — Spawn Domain Leads in parallel; each Lead spawns Specialists only for complex sub-topics
6. **CROSS-CUT** — Cross-Domain Analyst identifies inter-domain patterns, conflicts, and emergent insights
7. **FILL GAPS** — Optional Gap-Filling Leads address critical inter-domain questions missed by primary agents
8. **SYNTHESIZE** — Bottom-up synthesis: Specialists → Leads → Cross-Domain Analyst → Director
9. **OUTPUT** — Director produces final report in the appropriate structure (dialectical, convergent, or landscape)

## Agent Hierarchy

```
Research Director (command orchestrator, opus)
├── Research Classifier (safety gate, opus)
├── Domain Leads (parallel, opus) — one per identified domain
│   └── Specialists (parallel, sonnet default) — for complex sub-topics only
├── Cross-Domain Analyst (opus) — inter-domain patterns
└── Gap-Filling Leads (optional, opus) — for critical inter-domain gaps
```

## Key Properties

- Adaptive complexity scoring via trial search
- Selective decomposition (handle simple directly, delegate complex)
- Domain specialization — 13 presets + dynamic generation
- Confidence propagation — sonnet Specialists capped at Moderate
- Bottom-up synthesis — each level synthesizes before passing up

## Quality Standards

### Confidence Calibration (ICD 203)

| Level | Label | When to Use |
|-------|-------|-------------|
| 1 | Very Low | Fragmentary evidence, single source, high uncertainty |
| 2 | Low | Limited corroboration, significant gaps remain |
| 3 | Moderate | Multiple sources agree, some gaps or caveats present |
| 4 | High | Strong corroboration across independent sources, minor caveats |
| 5 | Very High | Overwhelming evidence, authoritative sources, near-certainty |

### Source Quality Scoring (0.0-1.0)

Composite of domain tier (0.30), citation impact (0.25), recency (0.20), author credibility (0.15), venue tier (0.10). See `references/source-quality-rubric.md`.

## Domain Presets

| Preset | Focus | Web:Academic |
|--------|-------|--------------|
| technical-engineering | Materials, structures, thermal, FEA | 1:1 |
| regulatory-compliance | FAR/DFARS, ITAR, AS9100, NADCAP | 2:1 |
| market-intelligence | Competitive analysis, market sizing | 3:1 |
| academic-scientific | Systematic lit review, evidence synthesis | 1:2 |
| financial-economic | Cost, ROI, economic models | 2:1 |
| supply-chain | Procurement, supplier risk, sourcing | 2:1 |
| manufacturing | Processes, tooling, SPC, lean/six sigma | 2:1 |
| defense-aerospace | Military, DoD, aircraft, spacecraft | 1:1 |
| robotics | Automation, control, manipulation, SLAM | 1:1 |
| software-development | Architecture, APIs, frameworks, AI/ML | 3:1 |
| hardware | Electronics, PCB, FPGA, embedded | 1:1 |
| tooling | Fixtures, jigs, molds, metrology | 2:1 |
| cybersecurity | CMMC, NIST 800-171, threats, compliance | 2:1 |

## Report Structures

| Structure | When to Use |
|-----------|-------------|
| Dialectical | When genuine tensions or contradictions exist between domains or sources |
| Convergent | When domains corroborate each other and point toward a unified conclusion |
| Landscape | When the query is exploratory and the goal is to map the answer space |
