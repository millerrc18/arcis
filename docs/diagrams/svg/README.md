# Arcis Architecture Diagrams

13 SVG diagrams for MASTER.md, Research Framework, and investor materials.
All support light/dark mode via CSS media queries.

## Diagram Index

| # | File | MASTER.md Section | Description |
|---|---|---|---|
| 01 | system-architecture.svg | Section 3 | Full pipeline: data → features → ranker → LLM → risk → broker → training |
| 02 | broker-abstraction.svg | Section 3 | Multi-broker: paper (Alpaca) vs live (IB) via factory pattern |
| 03 | flywheel-moat.svg | Section 8 | Compounding loop: trades → data → model → better trades |
| 04 | multi-cadence-scanning.svg | Section 3 | 4-tier architecture: 15min / 30min / 60min / daily |
| 05 | risk-governor.svg | Section 7 | 8 hard checks before every trade |
| 06 | data-enrichment-stack.svg | Section 3 | 7 orthogonal signal dimensions |
| 07 | revenue-path.svg | Section 8 | Revenue sequencing: trading → C2 → signals → fund |
| 08 | ai-council.svg | Section 7 | 5-agent Modified Delphi protocol |
| 09 | watch-loop-24hr.svg | Section 3 | 24-hour daily cycle: pre-market through overnight |
| 10 | hardware-scaling.svg | Section 6 | RTX 3060 → 3090 → dedicated server |
| 11 | trade-lifecycle.svg | Section 3 | Signal to close: scan → rank → LLM → risk → execute → exit |
| 12 | training-pipeline.svg | Section 7 | Self-blinding architecture + outcome-conditioned templates |
| 13 | phase-gates.svg | Section 6 | Bootcamp → scale → multi-strategy → fund formation |

## Usage in Markdown

GitHub renders inline SVGs in markdown. Embed with:
```markdown
![System Architecture](docs/diagrams/svg/01-system-architecture.svg)
```

## CC Integration Task

When integrating into MASTER.md, add each diagram BELOW the relevant section heading
as a GitHub-rendered image reference. Don't embed raw SVG in markdown.
