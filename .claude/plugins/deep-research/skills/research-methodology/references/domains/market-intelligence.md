# Domain Preset: Market Intelligence

## Description

Competitive analysis, market sizing and segmentation, mergers and acquisitions (M&A) trends, industry analysis, and business intelligence. Covers both defense/government market intelligence and commercial market research, with emphasis on actionable insights for strategic decision-making.

## Preferred Sources

1. **SEC EDGAR filings** — 10-K, 10-Q, proxy statements, 8-K material events for public companies
2. **Defense News** — Defense industry news, top 100 rankings, contract awards
3. **FPDS (Federal Procurement Data System)** — Federal contract award data, spending trends, market share analysis
4. **Bloomberg / Bloomberg Government** — Financial data, defense market analysis, BGOV contract trackers
5. **PitchBook** — M&A transactions, private company valuations, industry deal flow
6. **Industry association reports** — AIA (Aerospace Industries Association), NDIA, SIA
7. **USAspending.gov** — Federal spending data, prime and sub-award tracking
8. **Janes** — Defense and security intelligence, equipment databases, country assessments
9. **Deloitte / McKinsey / BCG** — Publicly available industry reports and trend analyses
10. **GovWin (Deltek)** — Government contract opportunity tracking, competitive intelligence

## Lateral Search Strategy

| Adjacent Field | Why Cross-Pollinate |
|---------------|-------------------|
| **Military intelligence (OSINT)** | Open-source intelligence collection methods, structured analysis of incomplete information, deception detection |
| **Sports scouting / Talent evaluation** | Systematic evaluation of competitors under uncertainty, draft/trade analytics, performance prediction models |
| **Ecology / Competitive dynamics** | Competitive exclusion principle, niche theory, predator-prey dynamics as market competition models |
| **Venture capital / Startup analysis** | Market timing, technology adoption curves, disruption theory, TAM/SAM/SOM frameworks |
| **Political science** — Policy analysis, geopolitical risk assessment, government decision-making models |

## Temporal Emphasis

Strongly current. Market conditions, competitive landscapes, and deal activity change rapidly. Historical data provides trend context but should not be over-weighted.

- **Half-life**: 2 years
- **Foundational corpus** (contextually relevant):
  - Porter, *Competitive Strategy* (Five Forces)
  - Christensen, *The Innovator's Dilemma*
  - Ries, *The Lean Startup* (market validation)
  - SIC/NAICS code frameworks
  - TAM/SAM/SOM sizing methodology
- **Current emphasis**: Latest quarterly earnings, recent contract awards, M&A announcements, defense budget markups, geopolitical events affecting markets, technology disruption signals. Data older than 2 years should be flagged as potentially stale.

## Output Template Tweaks

Add the following sections to the standard report template:

### Competitive Landscape Matrix

[Map key competitors across relevant dimensions: market share, capabilities, recent wins/losses, strategic direction, financial health, and technology investment. Use a structured comparison table. Identify whitespace opportunities.]

### Market Size Estimates

[Provide TAM (Total Addressable Market), SAM (Serviceable Addressable Market), and SOM (Serviceable Obtainable Market) estimates where applicable. Document methodology (top-down vs bottom-up), data sources, key assumptions, and confidence intervals. Show the math.]

### Key Assumptions & Sensitivities

[Explicitly list the assumptions underlying market estimates and competitive assessments. Perform sensitivity analysis: which assumptions, if wrong, would most change the conclusions? Identify leading indicators that would signal assumption failure.]

## Example Queries

1. "Defense electronics M&A trends 2024-2025 and implications for mid-tier contractors"
2. "Market size for commercial drone inspection services in aerospace MRO"
3. "Competitive landscape for tactical communications systems — who is winning recent awards?"
