---
name: research-methodology
description: Research methodology, quality standards, and domain knowledge for the deep-research plugin
autoTrigger: true
---

# Research Methodology

This skill provides context for the deep-research plugin's approach to research.

## Approach: Dialectical Research

The `/research` command uses a multi-phase pipeline:

1. **CLASSIFY** — Screen query for ITAR/CUI/EAR sensitivity before any external API calls
2. **PLAN** — Decompose query into direct + lateral + contrarian sub-questions with temporal assignments
3. **GATHER** — Parallel agents search web, academic, and cross-domain sources
4. **TRACE** — Follow citation chains from top sources to find primary/seminal works (deep/exhaustive)
5. **SYNTHESIZE** — Dialectical analysis: thesis (consensus) → antithesis (challenges) → synthesis (deeper insight)
6. **REFINE** — Adaptive gap-filling with novelty-gated stopping (moderate+)
7. **DELIBERATE** — 5-agent council debate using Modified Delphi protocol (deep/exhaustive)
8. **OUTPUT** — Structured report with citations, provenance, and confidence levels

## Quality Standards

### Confidence Calibration (ICD 203)

| Level | Label | When to Use |
|-------|-------|-------------|
| 1 | Very Low | Single source, conflicting evidence, no resolution |
| 2 | Low | Few sources, questionable reliability |
| 3 | Moderate | Credible sources but key assumptions could be wrong |
| 4 | High | High-quality sources, strong logic, alternatives considered |
| 5 | Very High | Diverse high-quality sources, independently replicated |

### Source Quality Scoring (0.0-1.0)

Composite of: domain tier (0.30), citation impact (0.25), recency (0.20), author credibility (0.15), venue tier (0.10). Missing factors excluded, weights redistributed.

**Domain tiers:** Authoritative (1.0) = peer-reviewed journals, government publications. Expert (0.8) = conference proceedings, working papers. Professional (0.6) = reputable news, analyst reports. Community (0.4) = Stack Overflow, established blogs. General (0.2) = forums, personal blogs.

## Domain Presets

12 domain presets control source preferences, lateral search strategies, and temporal emphasis:

| Domain | Focus |
|--------|-------|
| `general` | Catch-all default |
| `trading` | Quant finance, algo strategies, risk management |
| `aerospace-engineering` | Materials, structures, propulsion, avionics |
| `defense-regulatory` | FAR/DFARS, ITAR/EAR, AS9100, NADCAP |
| `supply-chain` | Procurement, supplier risk, make-vs-buy |
| `manufacturing-quality` | Processes, NDT, metrology, SPC, lean/six sigma |
| `cybersecurity-compliance` | CMMC, NIST 800-171, FedRAMP, OT security |
| `software-ai` | Architecture, AI/ML, LLM apps, data pipelines |
| `project-management` | EVM, scheduling, risk, program execution |
| `academic-scientific` | Systematic lit review, evidence synthesis |
| `market-intelligence` | Competitive analysis, market sizing, M&A |
| `medical-health` | Evidence-based medicine, health optimization |

## Report Structure

Reports follow the dialectical template:
- Executive Summary (with ICD 203 confidence)
- Thesis / Antithesis / Synthesis
- How Thinking Has Evolved (temporal arc)
- Cross-Domain Connections
- Counter-Evidence & Risks
- Source Chain (primary sources traced through citations)
- Decision Implications (concrete actions)
- Council Debate (deep/exhaustive only): BLUF, consensus, debate points, recommendations
- Sources (grouped by quality tier)
- Research Metadata (agents, APIs, costs, timing)
