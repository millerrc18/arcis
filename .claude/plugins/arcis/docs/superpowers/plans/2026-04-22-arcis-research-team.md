# ARCIS Research Team — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the ARCIS Claude Code plugin's research-team skill — a hierarchical multi-agent research system with adaptive complexity scoring, domain-specialized agents, and dialectical synthesis.

**Architecture:** The plugin is composed entirely of markdown files (agent prompts, commands, skill definitions, reference documents) plus one Python MCP server copied from the existing deep-research plugin. The command orchestrator (`research.md`) acts as the Research Director, dispatching Domain Lead agents that autonomously assess complexity and selectively delegate to Specialists. Results flow bottom-up through a Cross-Domain Analyst before final synthesis.

**Tech Stack:** Claude Code plugin system (markdown agents/commands/skills), deep-research MCP server (Python/FastMCP), YAML frontmatter, JSON schemas in markdown.

---

## File Structure

Files created or modified by this plan:

```
arcis/
├── .claude-plugin/
│   └── plugin.json                              # Task 1
├── .mcp.json                                    # Task 1
├── server/
│   └── research_mcp_server.py                   # Task 12 (copied from deep-research)
│
├── docs/
│   ├── superpowers/                             # (specs + plans — already exists)
│   └── agent-conventions.md                     # Task 7
│
├── skills/
│   ├── research-team/
│   │   ├── SKILL.md                             # Task 11
│   │   ├── commands/
│   │   │   └── research.md                      # Task 16 (largest file — orchestrator)
│   │   ├── agents/
│   │   │   ├── research-classifier.md           # Task 13
│   │   │   ├── domain-lead.md                   # Task 14
│   │   │   ├── specialist.md                    # Task 15
│   │   │   └── cross-domain-analyst.md          # Task 15
│   │   └── references/
│   │       ├── domain-presets/
│   │       │   ├── technical-engineering.md      # Task 10
│   │       │   ├── regulatory-compliance.md      # Task 10
│   │       │   ├── market-intelligence.md        # Task 10
│   │       │   ├── academic-scientific.md        # Task 10
│   │       │   ├── financial-economic.md         # Task 10
│   │       │   ├── supply-chain.md               # Task 10
│   │       │   ├── manufacturing.md              # Task 10
│   │       │   ├── defense-aerospace.md          # Task 10
│   │       │   ├── robotics.md                   # Task 10
│   │       │   ├── software-development.md       # Task 10
│   │       │   ├── hardware.md                   # Task 10
│   │       │   ├── tooling.md                    # Task 10
│   │       │   └── cybersecurity.md              # Task 10
│   │       ├── classification-blocklist.md       # Task 8
│   │       └── complexity-calibration.md         # Task 9
│   │
│   ├── coding-team/                              # Task 17 (stub)
│   │   └── SKILL.md
│   └── roast-me/                                 # Task 17 (stub)
│       └── SKILL.md
│
└── shared/
    ├── schemas/
    │   ├── findings-schema.md                    # Task 2
    │   └── completeness-reporting.md             # Task 3
    ├── references/
    │   ├── icd203-confidence-calibration.md      # Task 4
    │   └── source-quality-rubric.md              # Task 5
    └── examples/
        └── sample-findings-output.md             # Task 6
```

---

## Task 1: Plugin Scaffold

**Files:**
- Create: `.claude-plugin/plugin.json`
- Create: `.mcp.json`
- Create: all directories in the tree above

- [ ] **Step 1: Create the full directory structure**

Run:
```bash
cd "C:\Users\ryan.c.miller\OneDrive - General Dynamics Mission Systems\04 - Computer\Desktop\arcis"

mkdir -p .claude-plugin
mkdir -p server
mkdir -p docs
mkdir -p skills/research-team/commands
mkdir -p skills/research-team/agents
mkdir -p skills/research-team/references/domain-presets
mkdir -p skills/coding-team
mkdir -p skills/roast-me
mkdir -p shared/schemas
mkdir -p shared/references
mkdir -p shared/examples
```

Expected: All directories created without errors.

- [ ] **Step 2: Write plugin.json**

Create `.claude-plugin/plugin.json`:

```json
{
  "name": "arcis",
  "description": "Hierarchical multi-agent orchestration for quality amplification — research-team, coding-team, roast-me.",
  "version": "1.0.0",
  "author": {
    "name": "Ryan C. Miller"
  }
}
```

- [ ] **Step 3: Write .mcp.json**

Create `.mcp.json`:

```json
{
  "mcpServers": {
    "deep-research": {
      "command": "py",
      "args": ["${CLAUDE_PLUGIN_ROOT}/server/research_mcp_server.py"],
      "env": {
        "TAVILY_API_KEY": "${TAVILY_API_KEY}",
        "EXA_API_KEY": "${EXA_API_KEY}",
        "FIRECRAWL_API_KEY": "${FIRECRAWL_API_KEY}",
        "SERPER_API_KEY": "${SERPER_API_KEY}",
        "BRAVE_API_KEY": "${BRAVE_API_KEY}",
        "SERPAPI_KEY": "${SERPAPI_KEY}",
        "WOLFRAM_APP_ID": "${WOLFRAM_APP_ID}",
        "NEWSAPI_KEY": "${NEWSAPI_KEY}"
      }
    }
  }
}
```

Note: Server name stays `deep-research` so all MCP tool references (`mcp__deep-research__search_web` etc.) work unchanged with the copied server.

- [ ] **Step 4: Verify plugin scaffold**

Run:
```bash
cat .claude-plugin/plugin.json
cat .mcp.json
find . -type d | sort
```

Expected: Both JSON files parse correctly. Directory tree matches the file structure map above.

- [ ] **Step 5: Initialize git repo and commit**

Run:
```bash
git init
git add .claude-plugin/plugin.json .mcp.json
git commit -m "feat: scaffold ARCIS plugin with plugin.json and MCP config"
```

Expected: Clean commit with 2 files.

---

## Task 2: Findings Schema (Shared)

**Files:**
- Create: `shared/schemas/findings-schema.md`

This is THE inter-skill API contract — the most important shared artifact.

- [ ] **Step 1: Write findings-schema.md**

Create `shared/schemas/findings-schema.md`:

````markdown
# Findings Schema

The canonical output format for all ARCIS agents that produce research findings. This schema is the inter-skill API contract — research-team produces it, coding-team and roast-me consume it.

## Agent Findings Output

Every Domain Lead and Specialist returns a `<findings>` JSON block conforming to this schema.

```json
{
  "domain": "string — domain label (e.g., 'Technical Engineering')",
  "mandate": "string — what was this agent asked to investigate",
  "depth_level": "integer — 0=Director, 1=Lead, 2=Specialist, 3+=Deep Specialist",
  "self_researched": "boolean — true if agent researched directly (not just delegated)",
  "completeness": "number 0.0-1.0 — self-assessed coverage (see completeness-reporting.md)",
  "issues": ["string — problems encountered during research"],

  "complexity_assessment": {
    "overall_score": "number 0.0-1.0",
    "signals": {
      "topical_breadth": "number 0.0-1.0 — distinct sub-topics that can't be covered in a single synthesis",
      "authoritative_disagreement": "number 0.0-1.0 — contradictions between comparably-authoritative sources",
      "source_type_diversity": "number 0.0-1.0 — need for academic + industry + regulatory + other source types",
      "query_residual": "number 0.0-1.0 — how much of the mandate remains unanswered after trial search",
      "temporal_spread": "number 0.0-1.0 — results spanning multiple eras requiring separate treatment"
    },
    "decision": "string — 'no_decomposition' | 'selective_decompose' | 'full_decompose'",
    "sub_topics_delegated": "integer",
    "sub_topics_handled_directly": "integer"
  },

  "key_findings": [
    {
      "claim": "string — the finding",
      "confidence": "string — ICD 203 level: Very Low | Low | Moderate | High | Very High",
      "self_researched": "boolean — true if this agent found the evidence directly",
      "evidence": [
        {
          "source_url": "string",
          "source_title": "string",
          "source_quality": "number 0.0-1.0 (see source-quality-rubric.md)",
          "source_read_success": "boolean — false if source was paywalled or unreachable",
          "relevant_excerpt": "string — key quote or data point"
        }
      ],
      "contradicting_evidence": [
        {
          "source_url": "string",
          "source_title": "string",
          "source_quality": "number 0.0-1.0",
          "relevant_excerpt": "string",
          "why_overridden": "string — why the primary claim is preferred over this contradiction"
        }
      ],
      "implications": "string — what this means for the parent question"
    }
  ],

  "evidence_digest": [
    {
      "claim": "string",
      "source": "string — URL",
      "confidence": "string — ICD 203 level",
      "specialist_depth": "integer — depth level of the agent that produced this"
    }
  ],

  "specialist_reports": ["object — nested findings from delegated Specialists (same schema, recursive)"],

  "synthesis": {
    "conclusion": "string — primary conclusion for this domain",
    "confidence": "string — ICD 203 level",
    "key_points": ["string"],
    "reasoning": "string — how conclusion was reached from evidence"
  },

  "summary": "string — 3-5 sentence triage summary for Cross-Domain Analyst",

  "gaps_remaining": ["string — what couldn't be adequately answered"],

  "cross_domain_hooks": [
    {
      "hook_id": "string — unique identifier (e.g., 'te-hook-1')",
      "topic": "string — the cross-cutting topic",
      "direction": "string — 'supports' | 'contradicts' | 'extends'",
      "target_domains": ["string — domains this likely connects to"],
      "description": "string — brief explanation of the connection"
    }
  ]
}
```

## Cross-Domain Analyst Output

The Cross-Domain Analyst returns a separate schema focused on inter-domain patterns.

```json
{
  "contradictions": [
    {
      "domain_a": "string",
      "domain_b": "string",
      "claim_a": "string",
      "claim_b": "string",
      "root_cause": "string — different assumptions? evidence? values?",
      "severity": "string — 'high' | 'medium' | 'low'"
    }
  ],
  "connections": [
    {
      "domains": ["string"],
      "pattern": "string",
      "evidence_from_each_domain": {},
      "strength": "string — 'strong' | 'moderate' | 'tentative'"
    }
  ],
  "emergent_patterns": [
    {
      "pattern": "string",
      "contributing_domains": ["string"],
      "confidence": "string — ICD 203 level",
      "implications": "string"
    }
  ],
  "inter_domain_gaps": [
    {
      "gap_description": "string",
      "relevant_domains": ["string"],
      "impact_on_conclusions": "string"
    }
  ],
  "overall_coherence_assessment": "string",
  "recommended_report_structure": "string — 'dialectical' | 'convergent' | 'landscape'"
}
```

## Failure Manifest

Attached to the Research Director's final synthesis input. Lists any agents that failed.

```json
{
  "failed_agents": [
    {
      "agent": "string — agent role (e.g., 'Domain Lead', 'Specialist')",
      "domain": "string — domain label",
      "mandate": "string — what it was asked to do",
      "failure_mode": "string — 'timeout' | 'token_limit' | 'tool_failure' | 'malformed_output'",
      "partial_output": "object | null — whatever was recoverable"
    }
  ]
}
```

## Usage Notes

- **Confidence cap:** Specialist findings produced by sonnet have a hard cap at `Moderate`. Domain Leads must add independent evidence to elevate to `High`.
- **Completeness:** Independent self-assessment relative to the agent's own mandate, NOT an aggregation of child scores.
- **evidence_digest[]:** Compact claim/source/confidence tuples giving the Cross-Domain Analyst raw-evidence visibility without full passthrough.
- **cross_domain_hooks[]:** Signals from Domain Leads flagging topics that likely connect to other domains. Read by the Cross-Domain Analyst before full reports.
- **specialist_reports[]:** Recursive — a Domain Lead's specialist_reports contain findings objects that follow this same schema.
````

- [ ] **Step 2: Verify the file**

Run:
```bash
head -5 shared/schemas/findings-schema.md
wc -l shared/schemas/findings-schema.md
```

Expected: File starts with `# Findings Schema`, approximately 120-140 lines.

- [ ] **Step 3: Commit**

Run:
```bash
git add shared/schemas/findings-schema.md
git commit -m "feat: add findings schema — inter-skill API contract"
```

---

## Task 3: Completeness Reporting (Shared)

**Files:**
- Create: `shared/schemas/completeness-reporting.md`

- [ ] **Step 1: Write completeness-reporting.md**

Create `shared/schemas/completeness-reporting.md`:

````markdown
# Completeness Reporting

Defines the `completeness` field and `issues[]` array used by all ARCIS agents in their findings output.

## Completeness Score (0.0-1.0)

An **independent self-assessment** relative to the agent's own mandate. It is NOT an aggregation of child agent scores. Each agent answers: "Given my mandate, how well did I cover it?"

### Calculation

```
completeness = (sub-questions answered / sub-questions generated)
```

Adjusted downward for:
- Low-confidence findings (HIGH or VERY HIGH = full credit, MODERATE = 0.8x, LOW = 0.5x, VERY LOW = 0.2x)
- Tool failures that prevented investigation (each failure reduces proportionally to its coverage impact)
- Paywalled or unreachable sources that were critical to the mandate

### Scale

| Score | Meaning | Report Rendering |
|-------|---------|-----------------|
| 0.0 | Catastrophic failure — nothing produced | Coverage Failure section |
| 0.1-0.3 | Significant gaps, partial coverage | Coverage Failure section |
| 0.4-0.6 | Meaningful coverage with known gaps | Gaps section |
| 0.7-0.8 | Solid coverage with minor gaps | Gaps section (if any) |
| 0.9-1.0 | Comprehensive coverage relative to mandate | No gap flag |

### Distinguishing "Found Nothing" vs "Could Not Investigate"

- `completeness: 0.8` + empty `key_findings[]` = "We looked hard and the evidence does not exist" — rendered as a finding (absence of evidence is meaningful)
- `completeness: 0.1` + empty `key_findings[]` = "We barely looked" — rendered as a gap/failure

## Issues Array

`issues[]` captures problems encountered during research. Each entry is a string describing what went wrong.

### Issue Categories

| Category | Example |
|----------|---------|
| Tool failure | `"search_web returned error: rate limit exceeded"` |
| Source access | `"Primary source paywalled: doi.org/10.xxxx — could not verify claim"` |
| Token pressure | `"Output truncated — 3 additional findings omitted"` |
| Quality concern | `"All sources on sub-topic X are from a single author — possible echo chamber"` |
| Scope limitation | `"Mandate included Y but no sources found in any language searched"` |

### Rules

- Every tool failure MUST be recorded in `issues[]` — silent omission is a plan violation
- Issues do NOT automatically reduce `completeness` — the agent judges impact on coverage
- Issues propagate upward: Domain Leads include notable Specialist issues in their own `issues[]`
````

- [ ] **Step 2: Commit**

Run:
```bash
git add shared/schemas/completeness-reporting.md
git commit -m "feat: add completeness reporting schema"
```

---

## Task 4: ICD 203 Confidence Calibration (Shared)

**Files:**
- Create: `shared/references/icd203-confidence-calibration.md`

- [ ] **Step 1: Write icd203-confidence-calibration.md**

Create `shared/references/icd203-confidence-calibration.md`:

````markdown
# ICD 203 Confidence Calibration

Confidence levels for all ARCIS findings. Based on Intelligence Community Directive 203 (Analytic Standards), adapted for open-source research.

## Five-Level Scale

| Level | Label | When to Use |
|-------|-------|-------------|
| 1 | **Very Low** | Fragmentary information. Single unverified source, or conflicting evidence with no resolution basis. Essentially conjecture supported by minimal data. |
| 2 | **Low** | Limited sources of questionable reliability. Minor analytical judgments possible but high uncertainty remains. Evidence exists but is thin or contradictory. |
| 3 | **Moderate** | Several credible sources with generally consistent findings, but key assumptions remain untested or could be wrong. This is the default for well-researched claims that lack independent verification. |
| 4 | **High** | Multiple authoritative, high-quality sources with strong logical consistency. Alternative explanations have been considered and are less well-supported. Minor gaps may exist but don't undermine the core finding. |
| 5 | **Very High** | Extensive evidence from diverse, high-quality sources. Findings independently replicated or corroborated across domains. Very rare — reserve for claims with overwhelming evidence. |

## Calibration Examples

### Very Low
> "One blog post from 2019 mentions that Company X considered this approach but abandoned it."
- Single source, unverified, no corroboration, outdated

### Low
> "Two industry reports suggest adoption rates between 15-40%, but neither cites primary data and the range is too wide to be actionable."
- Multiple sources but questionable reliability, wide uncertainty band

### Moderate
> "Three peer-reviewed papers and two industry reports agree that the process reduces defect rates by 20-30%. However, all studies used similar test conditions that may not reflect production environments."
- Credible sources, consistent findings, but key assumption (test vs production) untested

### High
> "DoD technical reports, peer-reviewed metallurgical studies, and industry case studies all confirm the material property change at this temperature range. One dissenting study used a different alloy composition, explaining the discrepancy."
- Multiple authoritative sources, alternative explanation investigated and resolved

### Very High
> "FAA certification data, multiple independent lab tests, and ten years of operational fleet data all corroborate the fatigue life prediction within ±5%."
- Diverse source types, independently replicated, extensive operational evidence

## Confidence Propagation Rules

1. Confidence can only be **elevated** by a higher-tier agent that adds independent evidence
2. Confidence can be **lowered** by any agent at any level
3. Confidence cannot be elevated without adding new evidence to the `evidence[]` array
4. Sonnet Specialist findings are capped at **Moderate** regardless of evidence quality — the model tier imposes a ceiling
5. Domain Lead elevating a Specialist claim to High must document the additional evidence that justifies the elevation

## Usage in Reports

- Every claim in the final report carries a confidence level
- The executive summary states overall confidence with a one-sentence justification
- The Confidence Key table is included in every report for reader reference
- Reduced overall confidence is applied proportionally when agents fail or coverage gaps exist
````

- [ ] **Step 2: Commit**

Run:
```bash
git add shared/references/icd203-confidence-calibration.md
git commit -m "feat: add ICD 203 confidence calibration reference"
```

---

## Task 5: Source Quality Rubric (Shared)

**Files:**
- Create: `shared/references/source-quality-rubric.md`

- [ ] **Step 1: Write source-quality-rubric.md**

Create `shared/references/source-quality-rubric.md`:

````markdown
# Source Quality Rubric

Composite quality scoring (0.0-1.0) for all sources encountered during ARCIS research. Used by agents when populating `source_quality` in findings and when registering sources via the MCP `register_source` tool.

## Composite Score

Five factors, weighted. If a factor cannot be assessed (e.g., citation count unavailable for a web source), exclude it and redistribute its weight proportionally among the remaining factors.

| Factor | Weight | Measures |
|--------|--------|----------|
| Domain tier | 0.30 | Source type authority level |
| Citation impact | 0.25 | Citation count relative to field norms |
| Recency | 0.20 | How current the source is |
| Author credibility | 0.15 | Author expertise and institutional affiliation |
| Venue tier | 0.10 | Publication venue quality |

## Domain Tiers

| Tier | Score | Examples |
|------|-------|---------|
| Authoritative | 1.0 | Peer-reviewed journals, government publications (FAA, DoD, NIST), official standards (AS9100, NADCAP), patent filings |
| Expert | 0.8 | Conference proceedings (AIAA, IEEE), working papers from recognized institutions, technical reports from national labs |
| Professional | 0.6 | Reputable news outlets, analyst reports (McKinsey, Gartner), established trade publications (Aviation Week, SAE) |
| Community | 0.4 | Stack Overflow (high-vote answers), established technical blogs (from known domain experts), white papers from vendors |
| General | 0.2 | Forums, personal blogs, unattributed web content, press releases, marketing materials |

## Citation Impact Scoring

| Percentile (within field) | Score |
|--------------------------|-------|
| Top 10% | 1.0 |
| Top 25% | 0.8 |
| Top 50% | 0.6 |
| Bottom 50% | 0.4 |
| No citations / not applicable | Exclude factor, redistribute weight |

## Recency Scoring

| Age | Score |
|-----|-------|
| < 1 year | 1.0 |
| 1-3 years | 0.8 |
| 3-5 years | 0.6 |
| 5-10 years | 0.4 |
| 10+ years | 0.2 |
| Foundational/seminal (any age) | 0.8 (override — seminal works don't decay) |

## Author Credibility

| Indicator | Score |
|-----------|-------|
| Recognized domain expert with institutional affiliation | 1.0 |
| Published researcher in the field | 0.8 |
| Industry practitioner with verifiable credentials | 0.6 |
| Journalist or analyst covering the field | 0.4 |
| Anonymous or unverifiable author | 0.2 |

## Venue Tier

| Venue Type | Score |
|------------|-------|
| Top-tier journal (Nature, Science, field-leading journals) | 1.0 |
| Respected journal or major conference | 0.8 |
| Workshop, symposium, or regional conference | 0.6 |
| Preprint server (arXiv, SSRN) | 0.4 |
| Self-published, blog, or no formal venue | 0.2 |

## MCP register_source Quality Rating

When calling `register_source`, map the composite score to the 1-5 integer rating:

| Composite Score | register_source Rating |
|----------------|----------------------|
| 0.8-1.0 | 5 |
| 0.6-0.79 | 4 |
| 0.4-0.59 | 3 |
| 0.2-0.39 | 2 |
| 0.0-0.19 | 1 |

## Grouping in Reports

Sources in the final report are grouped by quality tier:

| Tier | Label | Composite Score |
|------|-------|----------------|
| Authoritative | `≥0.8` | Top-tier sources |
| Expert | `0.6-0.79` | Strong secondary sources |
| Professional | `0.4-0.59` | Credible but less rigorous |
| Other | `<0.4` | Low-confidence sources |
````

- [ ] **Step 2: Commit**

Run:
```bash
git add shared/references/source-quality-rubric.md
git commit -m "feat: add source quality rubric reference"
```

---

## Task 6: Sample Findings Output (Shared)

**Files:**
- Create: `shared/examples/sample-findings-output.md`

- [ ] **Step 1: Write sample-findings-output.md**

Create `shared/examples/sample-findings-output.md`:

````markdown
# Sample Findings Output

A concrete, valid example of findings output conforming to the findings schema. Use this as a reference when authoring or debugging agent prompts.

## Example: Domain Lead Report — Technical Engineering

This example shows a Domain Lead that handled one sub-topic directly and delegated two to Specialists.

```json
{
  "domain": "Technical Engineering",
  "mandate": "Investigate friction stir welding (FSW) applicability to Al-Li aerospace structures",
  "depth_level": 1,
  "self_researched": true,
  "completeness": 0.85,
  "issues": [
    "One key NASA technical report was paywalled — could not verify specific tensile strength data"
  ],

  "complexity_assessment": {
    "overall_score": 0.65,
    "signals": {
      "topical_breadth": 0.8,
      "authoritative_disagreement": 0.5,
      "source_type_diversity": 0.4,
      "query_residual": 0.7,
      "temporal_spread": 0.3
    },
    "decision": "selective_decompose",
    "sub_topics_delegated": 2,
    "sub_topics_handled_directly": 2
  },

  "key_findings": [
    {
      "claim": "FSW produces joints with 80-95% of parent material tensile strength in 2xxx-series Al-Li alloys, compared to 60-70% for conventional fusion welding",
      "confidence": "High",
      "self_researched": true,
      "evidence": [
        {
          "source_url": "https://doi.org/10.1016/j.msea.2023.xxxxx",
          "source_title": "Mechanical Properties of FSW Al-Li 2195 Joints for Aerospace Applications",
          "source_quality": 0.88,
          "source_read_success": true,
          "relevant_excerpt": "Tensile tests of FSW joints in 2195-T8 showed ultimate tensile strength of 420 MPa (92% of base material) with elongation of 8.2%"
        },
        {
          "source_url": "https://ntrs.nasa.gov/citations/20230xxxxx",
          "source_title": "NASA Marshall FSW Parameter Optimization for SLS Structures",
          "source_quality": 0.92,
          "source_read_success": true,
          "relevant_excerpt": "Production FSW parameters for 2195 achieve consistent joint efficiency above 85% across 12mm thick sections"
        }
      ],
      "contradicting_evidence": [
        {
          "source_url": "https://doi.org/10.1007/s00170-2022-xxxxx",
          "source_title": "Challenges in FSW of Third-Generation Al-Li Alloys",
          "source_quality": 0.75,
          "relevant_excerpt": "Joint efficiency dropped to 72% when welding speed exceeded 400mm/min in 2060-T8",
          "why_overridden": "Study used 2060 alloy (different composition) and non-optimized parameters — not directly comparable to 2195 production data"
        }
      ],
      "implications": "FSW is viable for primary aerospace structures in Al-Li, provided parameters are optimized per alloy composition"
    }
  ],

  "evidence_digest": [
    {
      "claim": "FSW joints in 2195 achieve 80-95% parent material strength",
      "source": "https://doi.org/10.1016/j.msea.2023.xxxxx",
      "confidence": "High",
      "specialist_depth": 1
    },
    {
      "claim": "FAA certification requires minimum 300 coupon tests for new joining process qualification",
      "source": "https://www.faa.gov/regulations/advisory_circulars/xxx",
      "confidence": "Moderate",
      "specialist_depth": 2
    }
  ],

  "specialist_reports": [
    {
      "domain": "Al-Li Metallurgy under FSW",
      "mandate": "Investigate microstructural evolution in Al-Li alloys during FSW and impact on mechanical properties",
      "depth_level": 2,
      "self_researched": true,
      "completeness": 0.78,
      "issues": [],
      "complexity_assessment": {
        "overall_score": 0.45,
        "signals": {
          "topical_breadth": 0.3,
          "authoritative_disagreement": 0.6,
          "source_type_diversity": 0.3,
          "query_residual": 0.5,
          "temporal_spread": 0.4
        },
        "decision": "no_decomposition",
        "sub_topics_delegated": 0,
        "sub_topics_handled_directly": 3
      },
      "key_findings": [
        {
          "claim": "T1 precipitate dissolution in the weld nugget is the primary mechanism for property loss — post-weld aging at 150°C for 24h recovers 90% of T1 density",
          "confidence": "Moderate",
          "self_researched": true,
          "evidence": [
            {
              "source_url": "https://doi.org/10.1016/j.actamat.2023.xxxxx",
              "source_title": "T1 Precipitate Evolution During FSW of Al-Cu-Li Alloys",
              "source_quality": 0.85,
              "source_read_success": true,
              "relevant_excerpt": "TEM analysis revealed complete T1 dissolution in the nugget zone with partial recovery after PWHT at 150°C/24h"
            }
          ],
          "contradicting_evidence": [],
          "implications": "Post-weld heat treatment is essential for structural applications — design must accommodate PWHT constraints"
        }
      ],
      "evidence_digest": [],
      "specialist_reports": [],
      "synthesis": {
        "conclusion": "FSW of Al-Li alloys requires careful parameter-microstructure-property optimization, with PWHT as a mandatory step for structural applications",
        "confidence": "Moderate",
        "key_points": [
          "T1 precipitate dissolution is the dominant degradation mechanism",
          "PWHT at 150°C/24h provides significant property recovery",
          "Welding speed is the most sensitive parameter for nugget zone microstructure"
        ],
        "reasoning": "Multiple TEM studies consistently show T1 dissolution; PWHT recovery is well-documented but optimal parameters are alloy-specific"
      },
      "summary": "FSW disrupts T1 precipitates in Al-Li weld nuggets, reducing strength. Post-weld aging at 150°C/24h recovers ~90% of precipitate density. Parameter optimization is alloy-specific.",
      "gaps_remaining": [
        "Long-term fatigue behavior of PWHT-recovered FSW joints (no data beyond 10^6 cycles)"
      ],
      "cross_domain_hooks": []
    }
  ],

  "synthesis": {
    "conclusion": "FSW is technically viable for primary Al-Li aerospace structures with proper parameter optimization and mandatory PWHT, offering significant strength advantages over fusion welding",
    "confidence": "High",
    "key_points": [
      "Joint efficiency of 80-95% demonstrated in production conditions",
      "T1 precipitate dissolution is manageable with PWHT",
      "Parameter sensitivity requires per-alloy qualification programs"
    ],
    "reasoning": "NASA production data, peer-reviewed mechanical testing, and microstructural analysis converge on viability. Contradicting evidence uses non-optimized parameters. The confidence gap is in long-term fatigue data."
  },

  "summary": "FSW achieves 80-95% joint efficiency in Al-Li 2xxx alloys for aerospace structures, significantly outperforming fusion welding. Requires parameter optimization per alloy and mandatory post-weld heat treatment. Primary uncertainty is long-term fatigue behavior beyond 10^6 cycles.",

  "gaps_remaining": [
    "Long-term fatigue data for FSW Al-Li joints beyond 10^6 cycles",
    "Cost comparison of FSW vs. traditional riveted construction for large aerospace panels"
  ],

  "cross_domain_hooks": [
    {
      "hook_id": "te-hook-1",
      "topic": "FAA certification requirements for FSW in primary structure",
      "direction": "extends",
      "target_domains": ["Regulatory Compliance"],
      "description": "Certification test matrix requirements will significantly impact program cost and schedule"
    },
    {
      "hook_id": "te-hook-2",
      "topic": "FSW tooling and fixturing requirements for large panels",
      "direction": "extends",
      "target_domains": ["Manufacturing", "Supply Chain"],
      "description": "FSW machines for aerospace panels are capital-intensive — limited global supplier base"
    }
  ]
}
```

## Notes

- The Domain Lead's confidence is `High` because it added NASA production data on top of Specialist `Moderate` findings — confidence elevation with new evidence
- The Specialist's confidence is capped at `Moderate` (sonnet model ceiling)
- `cross_domain_hooks` flag topics for the Cross-Domain Analyst to investigate across domain boundaries
- `evidence_digest` provides a flat list for the Cross-Domain Analyst's initial scan before diving into full reports
- `specialist_reports` is recursive — contains the same schema nested
````

- [ ] **Step 2: Commit**

Run:
```bash
git add shared/examples/sample-findings-output.md
git commit -m "feat: add sample findings output example"
```

---

## Task 7: Agent Conventions Doc

**Files:**
- Create: `docs/agent-conventions.md`

- [ ] **Step 1: Write agent-conventions.md**

Create `docs/agent-conventions.md`:

````markdown
# ARCIS Agent Authoring Conventions

Development guide for writing agent prompts in the ARCIS plugin. This is a convention document for agent authors, NOT a runtime contract.

## 5-Section Prompt Structure

Every ARCIS agent MUST use exactly these five sections in this order:

### 1. EPISTEMIC LENS

The agent's identity and optimization objective. Establishes HOW the agent thinks, not WHAT it does.

- Role identity (e.g., "You are a domain researcher specializing in...")
- Optimization objective (what the agent prioritizes)
- Anti-sycophancy directive where applicable (adversarial agents must pre-commit to a position)

### 2. TASK

What the agent does. Defines inputs, workflow, and outputs.

- **Inputs you will receive:** — enumerate exactly what the orchestrator injects
- **Your workflow:** — numbered steps the agent follows
- **Outputs you must produce:** — what the agent returns

### 3. CONSTRAINTS

Hard rules expressed as MUST/MUST NOT. These are not guidelines — violation is a bug.

- Source quality minimums
- maxTurns budget
- Confidence caps
- Output token limits
- Tool restrictions

### 4. DYNAMIC CONTEXT

A placeholder section that the orchestrator fills at dispatch time. The agent template contains only:

```markdown
## DYNAMIC CONTEXT

<!-- Injected by orchestrator at dispatch time -->
```

The orchestrator injects:
- Domain specialization (from presets or generated on-the-fly)
- Specific mandate for this dispatch
- Parent findings (if applicable)
- Budget allocation
- Depth level and max depth
- Complexity threshold for this depth level

### 5. OUTPUT FORMAT

Exact output structure the agent must follow:

```xml
<reasoning>
Chain-of-thought analysis. Logged for provenance but NOT parsed by the orchestrator.
This is where the agent shows its work.
</reasoning>

<findings>
{
  "structured JSON conforming to findings-schema.md"
}
</findings>
```

**Rules:**
- `<reasoning>` is always first — it grounds the agent's thinking before producing structured output
- `<findings>` JSON MUST conform to the findings schema in `shared/schemas/findings-schema.md`
- The orchestrator parses `<findings>` via regex extraction — do not nest additional XML tags inside it
- Keep `<reasoning>` descriptive but concise — it's logged for audit, not consumed by downstream agents

## Agent Frontmatter

YAML frontmatter at the top of every agent `.md` file:

```yaml
---
name: agent-name          # kebab-case, prefixed by skill (e.g., research-domain-lead)
description: One-line description of what this agent does
model: opus               # opus or sonnet
maxTurns: 10              # tool-use turns budget
allowed-tools:            # list of tools the agent may use (empty [] for pure reasoning)
  - mcp__deep-research__search_web
  - mcp__deep-research__search_academic
  - Write
---
```

## Naming Convention

Agent filenames are prefixed per-skill to prevent namespace collisions:

| Pattern | Example |
|---------|---------|
| `research-<role>.md` | `research-classifier.md`, `research-domain-lead.md` |
| `coding-<role>.md` | `coding-developer.md` (future) |
| `roast-<role>.md` | `roast-analyst.md` (future) |
````

- [ ] **Step 2: Commit**

Run:
```bash
git add docs/agent-conventions.md
git commit -m "feat: add agent authoring conventions doc"
```

---

## Task 8: Classification Blocklist

**Files:**
- Create: `skills/research-team/references/classification-blocklist.md`

- [ ] **Step 1: Write classification-blocklist.md**

Create `skills/research-team/references/classification-blocklist.md`:

````markdown
# Classification Blocklist

Keyword patterns for the Phase 0 classification gate. Used by the Research Classifier agent and the Research Director to screen queries before any external API calls.

## How This Is Used

1. The Research Director scans the user query against these patterns
2. If ANY pattern matches, the query is forwarded to the Research Classifier agent for LLM evaluation
3. If NO pattern matches, classification = `PROCEED` and no agent is dispatched

## ITAR / USML Indicators

- "defense article"
- "defense service"
- "USML" or "United States Munitions List"
- "USML Category" followed by Roman numerals (I through XXI)
- "technical data" (in context of defense/export)
- "ITAR" or "International Traffic in Arms"
- "DDTC" or "Directorate of Defense Trade Controls"
- "TAA" or "Technical Assistance Agreement"
- "MLA" or "Manufacturing License Agreement"

## EAR / Export Control Indicators

- "EAR" or "Export Administration Regulations"
- "ECCN" followed by alphanumeric pattern (e.g., "ECCN 9A004")
- "Commerce Control List"
- "BIS" or "Bureau of Industry and Security"
- "export controlled"
- "deemed export"
- "dual-use" (in export control context)

## CUI / FOUO Indicators

- "CUI" or "Controlled Unclassified Information"
- "FOUO" or "For Official Use Only"
- "SBU" or "Sensitive But Unclassified"
- "NOFORN"
- "distribution statement" followed by B, C, D, E, or F
- "limited distribution"
- "official use only"

## Classification Level Indicators

- "classified" (when referring to information handling, not taxonomic classification)
- "SECRET" or "TOP SECRET" (as classification markings)
- "TS/SCI"
- "SAP" or "Special Access Program"
- "SCI" or "Sensitive Compartmented Information"
- "security clearance" (in context of access requirements)

## Weapons / Systems Terminology

- Specific weapon system designations (e.g., "MK-", "AGM-", "AIM-")
- "munitions"
- "warhead"
- "guidance system" (in weapons context)
- "countermeasures" (in electronic warfare context)
- "stealth" or "low observable" (in platform design context)

## Nuclear Indicators

- "nuclear weapon"
- "enrichment" (uranium/plutonium context)
- "critical mass"
- "weapons grade"

## Notes

- Pattern matching is case-insensitive
- Context matters — "classified" in "classified by species" is not a hit. The LLM evaluation in step 2 resolves false positives.
- This list is intentionally over-inclusive. False positives are cheap (LLM evaluation). False negatives are dangerous (sensitive query sent to external APIs).
- Update this list when new controlled terminology is encountered.
````

- [ ] **Step 2: Commit**

Run:
```bash
git add skills/research-team/references/classification-blocklist.md
git commit -m "feat: add classification blocklist for ITAR/CUI/EAR screening"
```

---

## Task 9: Complexity Calibration Reference

**Files:**
- Create: `skills/research-team/references/complexity-calibration.md`

- [ ] **Step 1: Write complexity-calibration.md**

Create `skills/research-team/references/complexity-calibration.md`:

````markdown
# Complexity Calibration

Worked examples for consistent complexity scoring. Used by the Research Director (domain-level assessment) and Domain Leads (sub-topic-level assessment).

## Scoring Recap

Five weighted signals, each 0.0-1.0:

| Signal | Weight | Measures |
|--------|--------|----------|
| Topical breadth | 0.30 | Distinct sub-topics that can't be covered in a single synthesis |
| Authoritative disagreement | 0.25 | Contradictions between comparably-authoritative sources |
| Source type diversity | 0.15 | Need for academic + industry + regulatory + other source types |
| Query residual | 0.15 | How much of the mandate remains unanswered after trial search |
| Temporal spread | 0.15 | Results spanning multiple eras requiring separate treatment |

Composite = weighted sum. Compare against depth-adjusted threshold.

## Depth-Adjusted Thresholds

| Depth Level | Role | Base Threshold |
|-------------|------|---------------|
| 0 | Research Director | 0.3 |
| 1 | Domain Lead | 0.5 |
| 2 | Specialist | 0.7 |
| 3+ | Deep Specialist | 0.9 |

Rigor modifier: `shallow` +0.2, `moderate` 0, `deep` -0.1, `exhaustive` -0.2.

---

## Research Director Examples (Domain Identification)

### LOW Complexity (0.2) — "What is the current price of titanium Ti-6Al-4V bar stock?"

**Trial search results:** Consistent pricing data from 3+ suppliers and market reports. Single domain (market/supply chain). No disagreement. Current data readily available.

```json
{
  "overall_score": 0.2,
  "signals": {
    "topical_breadth": 0.1,
    "authoritative_disagreement": 0.1,
    "source_type_diversity": 0.2,
    "query_residual": 0.1,
    "temporal_spread": 0.1
  },
  "decision": "no_decomposition"
}
```

**Assessment:** Single-domain, single-Lead mode. The Director handles this directly or dispatches one Market Intelligence Lead.

### MODERATE Complexity (0.5) — "How does additive manufacturing compare to traditional machining for aerospace titanium components?"

**Trial search results:** Multiple sub-topics visible (cost, mechanical properties, certification, design freedom). Some disagreement on cost-effectiveness. Mix of academic papers and industry reports. Active field — recent developments differ from 5-year-old data.

```json
{
  "overall_score": 0.52,
  "signals": {
    "topical_breadth": 0.7,
    "authoritative_disagreement": 0.4,
    "source_type_diversity": 0.5,
    "query_residual": 0.4,
    "temporal_spread": 0.5
  },
  "decision": "selective_decompose"
}
```

**Assessment:** Two domains — Technical Engineering (process comparison) and Regulatory Compliance (certification). Director decomposes into 2 Domain Leads.

### HIGH Complexity (0.8) — "Analyze the feasibility and implications of replacing aluminum-lithium with carbon fiber composites in next-generation narrow-body aircraft primary structure"

**Trial search results:** Touches materials science, structural engineering, manufacturing processes, certification, supply chain, cost modeling, environmental impact. Active expert disagreement on composite fatigue in fuselage pressurization cycles. Requires academic papers, OEM case studies, regulatory guidance, supplier data. Multi-decade evolution from A320 to 787 to future concepts.

```json
{
  "overall_score": 0.82,
  "signals": {
    "topical_breadth": 0.9,
    "authoritative_disagreement": 0.8,
    "source_type_diversity": 0.8,
    "query_residual": 0.7,
    "temporal_spread": 0.8
  },
  "decision": "full_decompose"
}
```

**Assessment:** 4-5 domains — Technical Engineering, Manufacturing, Regulatory, Supply Chain, Financial. Full decomposition with per-branch specialist budgets.

---

## Domain Lead Examples (Sub-Topic Complexity)

### LOW Sub-Topic Complexity (0.25) — "FSW process parameters for 2195-T8"

**Trial search results:** Well-documented in NASA technical reports and peer-reviewed papers. Parameters (rotation speed, travel speed, forge force) are well-established for this specific alloy. No significant disagreement.

```json
{
  "overall_score": 0.25,
  "signals": {
    "topical_breadth": 0.2,
    "authoritative_disagreement": 0.1,
    "source_type_diversity": 0.2,
    "query_residual": 0.2,
    "temporal_spread": 0.3
  },
  "decision": "no_decomposition"
}
```

**Assessment:** Handle directly — no Specialist needed. Domain Lead researches this sub-topic itself.

### HIGH Sub-Topic Complexity (0.75) — "Al-Li metallurgy under FSW"

**Trial search results:** Multiple competing theories on T1 precipitate behavior. Alloy-specific results that don't generalize. Mix of TEM studies, mechanical testing papers, and simulation work. Active research front with evolving understanding.

```json
{
  "overall_score": 0.72,
  "signals": {
    "topical_breadth": 0.6,
    "authoritative_disagreement": 0.8,
    "source_type_diversity": 0.6,
    "query_residual": 0.8,
    "temporal_spread": 0.7
  },
  "decision": "selective_decompose"
}
```

**Assessment:** Delegate to a Specialist. The disagreement level and query residual justify dedicated investigation.

---

## Decision Guide

After computing the composite score, compare against the threshold for your depth level:

- **Score < threshold:** Handle directly. You are the researcher.
- **Score ≥ threshold (marginally):** Use selective decomposition — delegate the complex sub-topics, handle the rest yourself.
- **Score >> threshold:** Full decomposition — delegate all sub-topics.

When in doubt between "handle directly" and "delegate," prefer handling directly. Delegation has overhead (agent dispatch, context switching, result collection). Only delegate when the complexity genuinely exceeds what you can cover with the trial search results you already have.
````

- [ ] **Step 2: Commit**

Run:
```bash
git add skills/research-team/references/complexity-calibration.md
git commit -m "feat: add complexity calibration reference with worked examples"
```

---

## Task 10: Domain Presets (13 files)

**Files:**
- Create: `skills/research-team/references/domain-presets/technical-engineering.md`
- Create: `skills/research-team/references/domain-presets/regulatory-compliance.md`
- Create: `skills/research-team/references/domain-presets/market-intelligence.md`
- Create: `skills/research-team/references/domain-presets/academic-scientific.md`
- Create: `skills/research-team/references/domain-presets/financial-economic.md`
- Create: `skills/research-team/references/domain-presets/supply-chain.md`
- Create: `skills/research-team/references/domain-presets/manufacturing.md`
- Create: `skills/research-team/references/domain-presets/defense-aerospace.md`
- Create: `skills/research-team/references/domain-presets/robotics.md`
- Create: `skills/research-team/references/domain-presets/software-development.md`
- Create: `skills/research-team/references/domain-presets/hardware.md`
- Create: `skills/research-team/references/domain-presets/tooling.md`
- Create: `skills/research-team/references/domain-presets/cybersecurity.md`

All 13 files follow the same template. Each preset defines 6 fields per the spec: `domain_name`, `expertise_framing`, `source_preferences`, `evaluation_lens`, `trial_search_strategy`, `keywords`. The orchestrator reads these and injects them into Domain Lead DYNAMIC CONTEXT.

- [ ] **Step 1: Write technical-engineering.md**

Create `skills/research-team/references/domain-presets/technical-engineering.md`:

```markdown
# Technical Engineering

## domain_name
Technical Engineering

## expertise_framing
You think like a systems engineer with deep materials and structural analysis expertise. You prioritize quantitative data — material properties, test results, performance metrics, failure modes — over qualitative assessments. You evaluate claims by checking whether the underlying physics and test methodology are sound. You are skeptical of vendor claims without independent verification.

## source_preferences
- **Preferred source types:** peer-reviewed journals (AIAA, ASME, Elsevier materials science), NASA/ESA technical reports, MIL-HDBK, MMPDS/CMH-17, conference proceedings (SAMPE, AIAA SciTech)
- **Authoritative domains:** ntrs.nasa.gov, doi.org, apps.dtic.mil, sae.org
- **Web:Academic ratio:** 1:1

## evaluation_lens
Strong evidence in this domain means: independently measured material properties, statistically significant test data (not single-specimen results), validated simulation models (with experimental correlation), and traceable standards compliance. Be wary of simulation-only claims without experimental validation.

## trial_search_strategy
- 1 `search_web` query focusing on industry applications and recent developments
- 1 `search_academic` query targeting peer-reviewed experimental data
- Weight academic sources slightly higher for core technical claims

## keywords
engineering, design, materials, thermal, structural, mechanical, fatigue, fracture, FEA, simulation, testing, alloy, composite, stress, strain, load, specification
```

- [ ] **Step 2: Write regulatory-compliance.md**

Create `skills/research-team/references/domain-presets/regulatory-compliance.md`:

```markdown
# Regulatory Compliance

## domain_name
Regulatory Compliance

## expertise_framing
You think like a regulatory affairs specialist. You trace requirements to their authoritative source (CFR, FAR, DFARS, MIL-STD) and verify currency. You distinguish between mandatory requirements (shall), recommendations (should), and guidance (may). You flag when regulations have pending amendments or recent revisions that could change the compliance landscape.

## source_preferences
- **Preferred source types:** Federal Register, CFR, FAR/DFARS, MIL-STDs, Advisory Circulars, NIST publications, AS9100/NADCAP standards, GAO reports
- **Authoritative domains:** ecfr.gov, acquisition.gov, federalregister.gov, nist.gov, faa.gov, sae.org
- **Web:Academic ratio:** 2:1

## evaluation_lens
Strong evidence in this domain means: direct citation of regulatory text with section numbers, official interpretive guidance (advisory circulars, DCMA guidebooks), or documented enforcement actions/audit findings. Industry blog interpretations of regulations are weak evidence without official corroboration.

## trial_search_strategy
- 1 `search_web` query targeting official regulatory sources and recent amendments
- 1 `search_academic` query for regulatory analysis and compliance frameworks
- Prioritize recency — regulations change frequently

## keywords
regulation, FAR, DFARS, ITAR, AS9100, compliance, requirement, certification, audit, standard, specification, advisory circular, CFR, MIL-STD, NADCAP, qualification
```

- [ ] **Step 3: Write market-intelligence.md**

Create `skills/research-team/references/domain-presets/market-intelligence.md`:

```markdown
# Market Intelligence

## domain_name
Market Intelligence

## expertise_framing
You think like a market analyst. You look for market size, growth rates, competitive landscape, pricing trends, and demand drivers. You triangulate data from multiple market reports and cross-check against company financials and industry data where available. You are skeptical of single-source market size estimates and look for methodology transparency.

## source_preferences
- **Preferred source types:** industry analyst reports (McKinsey, Deloitte, Roland Berger), trade publications (Aviation Week, FlightGlobal), company 10-K filings, government market data (BLS, Census Bureau, ITC)
- **Authoritative domains:** sec.gov, bls.gov, trade.gov, aviationweek.com
- **Web:Academic ratio:** 3:1

## evaluation_lens
Strong evidence in this domain means: multiple independent market estimates that converge, transparent methodology (sample size, data collection method), traceable to primary data sources (government statistics, company filings). Single analyst estimates without methodology disclosure are weak.

## trial_search_strategy
- 2 `search_web` queries targeting industry reports and market data
- 1 `search_academic` query for market analysis papers (if applicable)
- Weight web sources — market data is rarely in academic papers

## keywords
market, competition, pricing, demand, forecast, market share, revenue, growth, competitive landscape, industry analysis, TAM, SAM, M&A, valuation
```

- [ ] **Step 4: Write academic-scientific.md**

Create `skills/research-team/references/domain-presets/academic-scientific.md`:

```markdown
# Academic-Scientific

## domain_name
Academic-Scientific

## expertise_framing
You think like a systematic reviewer. You evaluate methodology rigor, statistical significance, reproducibility, and citation impact. You weight meta-analyses and systematic reviews above individual studies. You identify publication bias and look for pre-registered studies. You trace citation chains to find seminal works.

## source_preferences
- **Preferred source types:** peer-reviewed journals, systematic reviews, meta-analyses, preprints with independent replication, Cochrane-style evidence syntheses
- **Authoritative domains:** doi.org, pubmed.ncbi.nlm.nih.gov, arxiv.org, scholar.google.com, semanticscholar.org
- **Web:Academic ratio:** 1:2

## evaluation_lens
Strong evidence in this domain means: pre-registered study with adequate sample size, statistically significant results (with effect size, not just p-value), independent replication, published in peer-reviewed venue with adequate review process. Conference papers are weaker than journal papers. Preprints are weaker still unless subsequently published.

## trial_search_strategy
- 1 `search_web` query for review articles and summaries
- 2 `search_academic` queries targeting primary research and systematic reviews
- Weight academic sources heavily

## keywords
research, study, theory, hypothesis, peer-reviewed, systematic review, meta-analysis, methodology, statistical significance, replication, citation, experiment, empirical
```

- [ ] **Step 5: Write financial-economic.md**

Create `skills/research-team/references/domain-presets/financial-economic.md`:

```markdown
# Financial-Economic

## domain_name
Financial-Economic

## expertise_framing
You think like a financial analyst. You focus on cost structures, ROI calculations, economic models, and financial risk. You validate assumptions behind projections and look for sensitivity analysis. You distinguish between accounting costs and economic costs, and between nominal and real values.

## source_preferences
- **Preferred source types:** SEC filings, central bank publications (Fed, ECB), CBO/GAO reports, NBER working papers, financial databases (Bloomberg, S&P Capital IQ — via web summaries), Big 4 industry reports
- **Authoritative domains:** sec.gov, bea.gov, federalreserve.gov, nber.org, cbo.gov
- **Web:Academic ratio:** 2:1

## evaluation_lens
Strong evidence in this domain means: audited financial data, government economic statistics, peer-reviewed economic models with disclosed assumptions, and sensitivity analysis showing robustness. Projections without assumption disclosure or sensitivity analysis are weak.

## trial_search_strategy
- 1 `search_web` query targeting financial data and industry reports
- 1 `search_academic` query for economic analysis and cost models
- Prioritize traceable data sources over commentary

## keywords
cost, budget, ROI, economic, financial model, NPV, IRR, depreciation, amortization, COGS, margin, break-even, cash flow, capex, opex
```

- [ ] **Step 6: Write supply-chain.md**

Create `skills/research-team/references/domain-presets/supply-chain.md`:

```markdown
# Supply Chain

## domain_name
Supply Chain

## expertise_framing
You think like a supply chain manager. You focus on supplier capabilities, lead times, single-source risks, logistics constraints, and make-vs-buy decisions. You evaluate supplier maturity (TRL/MRL equivalents) and identify concentration risks. You look for geopolitical and trade policy impacts on sourcing.

## source_preferences
- **Preferred source types:** industry databases (ThomasNet, SAM.gov), trade publications, government trade data (ITC, Commerce Dept), logistics industry reports, CSCMP publications
- **Authoritative domains:** sam.gov, trade.gov, thomasnet.com, supplychainbrain.com
- **Web:Academic ratio:** 2:1

## evaluation_lens
Strong evidence in this domain means: verifiable supplier data, government trade statistics, documented lead times from procurement records, and industry benchmarking studies with disclosed methodology. Anecdotal supplier claims without independent verification are weak.

## trial_search_strategy
- 1 `search_web` query targeting supplier data and industry analysis
- 1 `search_academic` query for supply chain risk and optimization research
- Weight web sources — supply chain data is operational, not academic

## keywords
supplier, procurement, logistics, lead time, sourcing, make-vs-buy, second source, qualified supplier list, supply risk, inventory, JIT, BOM, vendor
```

- [ ] **Step 7: Write manufacturing.md**

Create `skills/research-team/references/domain-presets/manufacturing.md`:

```markdown
# Manufacturing

## domain_name
Manufacturing

## expertise_framing
You think like a manufacturing engineer. You focus on process capabilities (Cpk), tolerances, cycle times, yield rates, and quality control methods. You evaluate manufacturing readiness (MRL) and scalability. You look for process-property relationships and understand that lab results don't always transfer to production.

## source_preferences
- **Preferred source types:** SME (Society of Manufacturing Engineers) publications, NIST Manufacturing Extension Partnership reports, ASM International handbooks, industry case studies, OEM technical papers
- **Authoritative domains:** sme.org, nist.gov, asminternational.org, sae.org
- **Web:Academic ratio:** 2:1

## evaluation_lens
Strong evidence in this domain means: production-validated data (not lab-scale only), documented process parameters with statistical process control data, demonstrated repeatability across multiple production runs, and independent quality verification.

## trial_search_strategy
- 1 `search_web` query targeting industry applications and process data
- 1 `search_academic` query for manufacturing research and process optimization
- Weight production-validated data over lab results

## keywords
production, process, tooling, machining, assembly, additive manufacturing, CNC, welding, casting, forging, injection molding, tolerance, Cpk, yield, SPC, lean, six sigma
```

- [ ] **Step 8: Write defense-aerospace.md**

Create `skills/research-team/references/domain-presets/defense-aerospace.md`:

```markdown
# Defense-Aerospace

## domain_name
Defense-Aerospace

## expertise_framing
You think like a defense/aerospace program analyst. You understand acquisition lifecycle (Milestone A/B/C), PPBE process, and platform development. You evaluate program health through cost/schedule/performance metrics. You understand classification boundaries and stay within open-source limits.

## source_preferences
- **Preferred source types:** CRS reports, GAO audits, DoD budget documents (FYDP, SAR), DTIC open publications, Jane's (summaries), Aviation Week, congressional testimony
- **Authoritative domains:** gao.gov, crs.gov, apps.dtic.mil, defense.gov, congress.gov
- **Web:Academic ratio:** 1:1

## evaluation_lens
Strong evidence in this domain means: official DoD documents (SAR, budget justifications), GAO audit findings, CRS analysis, and open-source intelligence from recognized defense publications. Avoid speculative capability assessments and stay within unclassified sources.

## trial_search_strategy
- 1 `search_web` query targeting defense news and government reports
- 1 `search_academic` query for defense policy and technology analysis
- Be cautious with classification boundaries — see classification-blocklist.md

## keywords
military, DoD, aircraft, spacecraft, defense, acquisition, milestone, LRIP, FRP, SAR, FYDP, PPBE, platform, weapon system, prime contractor
```

- [ ] **Step 9: Write robotics.md**

Create `skills/research-team/references/domain-presets/robotics.md`:

```markdown
# Robotics

## domain_name
Robotics

## expertise_framing
You think like a robotics systems engineer. You evaluate across the full stack: mechanical design, actuation, sensing, control algorithms, autonomy, and human-robot interaction. You focus on real-world performance data over simulated results. You understand the gap between research demonstrations and deployable systems.

## source_preferences
- **Preferred source types:** IEEE Robotics & Automation journals, conference proceedings (ICRA, IROS, RSS, CoRL), ROS documentation, industry case studies (Boston Dynamics, FANUC, ABB), NIST robotics standards
- **Authoritative domains:** ieee.org, doi.org, ros.org, nist.gov
- **Web:Academic ratio:** 1:1

## evaluation_lens
Strong evidence in this domain means: demonstrated performance on physical hardware (not simulation-only), statistical reliability data, documented failure modes, and comparison against baselines. Simulation-only results are suggestive but not conclusive.

## trial_search_strategy
- 1 `search_web` query targeting industry applications and product data
- 1 `search_academic` query for robotics research with experimental results
- Prefer sources with real-world validation

## keywords
robot, automation, actuator, control system, kinematics, dynamics, SLAM, manipulation, locomotion, end effector, ROS, sensor fusion, path planning, reinforcement learning
```

- [ ] **Step 10: Write software-development.md**

Create `skills/research-team/references/domain-presets/software-development.md`:

```markdown
# Software Development

## domain_name
Software Development

## expertise_framing
You think like a senior software architect. You evaluate technology choices by maturity, community support, performance characteristics, and maintenance burden. You distinguish between hype and proven production use. You look for architecture patterns that have survived real-world scale.

## source_preferences
- **Preferred source types:** official documentation, GitHub repos (stars, activity, issues), tech blog posts from engineering teams (Netflix, Google, Stripe engineering blogs), conference talks (Strange Loop, QCon), language/framework RFCs
- **Authoritative domains:** github.com, docs.python.org, developer.mozilla.org, cloud.google.com, aws.amazon.com
- **Web:Academic ratio:** 3:1

## evaluation_lens
Strong evidence in this domain means: production deployment at scale with documented outcomes, well-maintained open source with active community, official documentation, and benchmarks with disclosed methodology. Microbenchmarks and synthetic tests are weak without production context.

## trial_search_strategy
- 2 `search_web` queries targeting documentation and engineering blog posts
- 1 `search_academic` query for CS research papers (if applicable)
- Weight practical production evidence over theoretical analysis

## keywords
code, API, architecture, framework, algorithm, microservice, database, deployment, CI/CD, testing, performance, scalability, open source, library, SDK
```

- [ ] **Step 11: Write hardware.md**

Create `skills/research-team/references/domain-presets/hardware.md`:

```markdown
# Hardware

## domain_name
Hardware

## expertise_framing
You think like an electronics/hardware engineer. You evaluate designs by power consumption, signal integrity, thermal management, reliability (MTBF), and manufacturability. You understand the gap between prototype and production hardware. You focus on datasheet specifications and independently verified performance data.

## source_preferences
- **Preferred source types:** IEEE publications, component datasheets, application notes (TI, Analog Devices, Intel), conference proceedings (DAC, ISSCC), industry standards (IPC, JEDEC)
- **Authoritative domains:** ieee.org, ti.com, analog.com, ipc.org, jedec.org
- **Web:Academic ratio:** 1:1

## evaluation_lens
Strong evidence in this domain means: datasheet specifications (from component manufacturers), independently measured performance data, reliability testing per JEDEC/MIL-STD standards, and thermal/signal integrity analysis with validated models.

## trial_search_strategy
- 1 `search_web` query targeting datasheets, application notes, and design guides
- 1 `search_academic` query for hardware research and novel architectures
- Weight manufacturer specifications and independent test data

## keywords
circuit, PCB, FPGA, embedded, sensor, electronics, power supply, signal integrity, EMI, thermal management, ASIC, SoC, microcontroller, ADC, DAC, bus protocol
```

- [ ] **Step 12: Write tooling.md**

Create `skills/research-team/references/domain-presets/tooling.md`:

```markdown
# Tooling

## domain_name
Tooling

## expertise_framing
You think like a tooling engineer. You focus on fixture design, tool life, dimensional accuracy, repeatability, and total cost of ownership. You evaluate tooling solutions by their production-readiness and maintenance requirements. You understand the relationship between tooling quality and part quality.

## source_preferences
- **Preferred source types:** SME publications, tooling supplier technical data, metrology standards (ASME Y14.5, ISO GPS), industry case studies, NIST measurement standards
- **Authoritative domains:** sme.org, nist.gov, asme.org, mitutoyo.com, zeiss.com
- **Web:Academic ratio:** 2:1

## evaluation_lens
Strong evidence in this domain means: documented tool life data under production conditions, GR&R studies for measurement tooling, demonstrated dimensional capability (Cpk data), and cost-per-part analysis with tooling amortization.

## trial_search_strategy
- 1 `search_web` query targeting tooling applications and supplier data
- 1 `search_academic` query for tooling research and optimization
- Weight production-validated performance data

## keywords
fixture, jig, mold, die, gauge, metrology, GD&T, CMM, tool life, wear, calibration, gage R&R, check fixture, inspection, tolerance stack
```

- [ ] **Step 13: Write cybersecurity.md**

Create `skills/research-team/references/domain-presets/cybersecurity.md`:

```markdown
# Cybersecurity

## domain_name
Cybersecurity

## expertise_framing
You think like a cybersecurity analyst. You evaluate threats by likelihood and impact, not just theoretical possibility. You focus on practical attack vectors, proven mitigations, and compliance frameworks. You distinguish between vulnerability disclosures (CVEs) and demonstrated exploits. You understand the defense-in-depth principle.

## source_preferences
- **Preferred source types:** NIST publications (SP 800 series), CISA advisories, CVE databases, CMMC/FedRAMP documentation, security vendor research (Mandiant, CrowdStrike, Recorded Future), RFC documents
- **Authoritative domains:** nist.gov, cisa.gov, cve.org, nvd.nist.gov, mitre.org
- **Web:Academic ratio:** 2:1

## evaluation_lens
Strong evidence in this domain means: CVE-tracked vulnerabilities with CVSS scores, NIST guidance with SP/FIPS numbers, documented incidents with forensic analysis, and compliance frameworks with specific control requirements. Theoretical attacks without proof of concept are weaker evidence.

## trial_search_strategy
- 1 `search_web` query targeting security advisories and compliance guidance
- 1 `search_academic` query for security research and novel attack/defense techniques
- Prioritize recency — threat landscape changes rapidly

## keywords
security, vulnerability, encryption, threat, compliance, CMMC, NIST 800-171, FedRAMP, STIG, CVE, penetration test, zero trust, SOC, incident response, malware
```

- [ ] **Step 14: Verify all 13 preset files exist**

Run:
```bash
ls skills/research-team/references/domain-presets/
wc -l skills/research-team/references/domain-presets/*.md
```

Expected: 13 `.md` files listed. Each approximately 40-55 lines.

- [ ] **Step 15: Commit all presets**

Run:
```bash
git add skills/research-team/references/domain-presets/
git commit -m "feat: add 13 domain preset references for research-team"
```

---

## Task 11: SKILL.md (Research Team)

**Files:**
- Create: `skills/research-team/SKILL.md`

The SKILL.md is always-on context (autoTrigger: true) that loads whenever the plugin is active. It provides methodology context, not orchestration logic (that's in the command).

- [ ] **Step 1: Write SKILL.md**

Create `skills/research-team/SKILL.md`:

````markdown
---
name: research-team
description: Hierarchical multi-agent research with adaptive complexity scoring, domain-specialized agents, and dialectical synthesis
autoTrigger: true
---

# Research Team

This skill provides the `/arcis:research` command for deep, multi-agent research.

## Approach: Research Director Model

The Research Director (the `/arcis:research` command) orchestrates hierarchical agent delegation:

1. **CLASSIFY** — Screen query for ITAR/CUI/EAR sensitivity (always-on safety gate)
2. **CLARIFY** — Ask one clarifying question if the query is too vague to decompose well (conditional)
3. **DECOMPOSE** — Trial searches to ground decomposition, identify domains, assess complexity
4. **CHECKPOINT** — Present decomposition tree to user for approval/modification
5. **DISPATCH** — Launch Domain Leads in parallel, each autonomously researching and selectively delegating to Specialists
6. **CROSS-CUT** — Cross-Domain Analyst finds inter-domain patterns, contradictions, and emergent insights
7. **FILL GAPS** — Optional gap-filling for critical inter-domain gaps (requires `--fill-gaps`)
8. **SYNTHESIZE** — Research Director merges domain reports + cross-cutting analysis into final report
9. **OUTPUT** — Dual output: markdown report + JSON sidecar

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

- **Adaptive complexity scoring** — agents assess complexity via trial search, only delegate when genuinely needed
- **Selective decomposition** — agents handle simple sub-topics directly, delegate complex ones
- **Domain specialization** — 13 domain presets + dynamic specialist generation for novel domains
- **Confidence propagation** — sonnet Specialists capped at Moderate; elevation requires new evidence from higher-tier agent
- **Bottom-up synthesis** — each level synthesizes before passing up, reducing volume while preserving findings

## Quality Standards

### Confidence Calibration (ICD 203)

| Level | Label | When to Use |
|-------|-------|-------------|
| 1 | Very Low | Fragmentary information, mostly conjecture |
| 2 | Low | Limited sources, significant uncertainty |
| 3 | Moderate | Several credible sources, some gaps |
| 4 | High | Multiple authoritative sources, strong agreement |
| 5 | Very High | Extensive evidence, expert consensus |

### Source Quality Scoring (0.0-1.0)

Composite of: domain tier (0.30), citation impact (0.25), recency (0.20), author credibility (0.15), venue tier (0.10). See `shared/references/source-quality-rubric.md` for full rubric.

## Domain Presets

13 domain presets in `references/domain-presets/`:

| Preset | Focus | Web:Academic |
|--------|-------|-------------|
| `technical-engineering` | Materials, structures, thermal, FEA | 1:1 |
| `regulatory-compliance` | FAR/DFARS, ITAR, AS9100, NADCAP | 2:1 |
| `market-intelligence` | Competitive analysis, market sizing | 3:1 |
| `academic-scientific` | Systematic lit review, evidence synthesis | 1:2 |
| `financial-economic` | Cost, ROI, economic models | 2:1 |
| `supply-chain` | Procurement, supplier risk, sourcing | 2:1 |
| `manufacturing` | Processes, tooling, SPC, lean/six sigma | 2:1 |
| `defense-aerospace` | Military, DoD, aircraft, spacecraft | 1:1 |
| `robotics` | Automation, control, manipulation, SLAM | 1:1 |
| `software-development` | Architecture, APIs, frameworks, AI/ML | 3:1 |
| `hardware` | Electronics, PCB, FPGA, embedded | 1:1 |
| `tooling` | Fixtures, jigs, molds, metrology | 2:1 |
| `cybersecurity` | CMMC, NIST 800-171, threats, compliance | 2:1 |

## Report Structures

Reports adapt structure to content:

| Structure | When | Example |
|-----------|------|---------|
| **Dialectical** | Genuine tensions between domains | "Should we adopt Rust for embedded?" |
| **Convergent** | Domains independently corroborate | "What are best practices for DB indexing?" |
| **Landscape** | Exploratory, answer is a map | "What is the state of additive mfg in aerospace?" |
````

- [ ] **Step 2: Commit**

Run:
```bash
git add skills/research-team/SKILL.md
git commit -m "feat: add research-team SKILL.md with methodology context"
```

---

## Task 12: Copy MCP Server

**Files:**
- Create: `server/research_mcp_server.py` (copied from deep-research plugin)

- [ ] **Step 1: Copy the MCP server file**

Run:
```bash
cp "$HOME/.claude/plugins/cache/local/deep-research/1.0.0/server/research_mcp_server.py" server/research_mcp_server.py
```

Note: If the local plugin path doesn't exist, try:
```bash
cp "$HOME/.claude/plugins/cache/claude-plugins-official/deep-research/5.0.6/server/research_mcp_server.py" server/research_mcp_server.py
```

Or find the correct path:
```bash
find "$HOME/.claude/plugins" -name "research_mcp_server.py" -type f 2>/dev/null
```

- [ ] **Step 2: Verify the copy**

Run:
```bash
head -20 server/research_mcp_server.py
wc -l server/research_mcp_server.py
```

Expected: Python file with FastMCP setup. Should be several hundred lines.

- [ ] **Step 3: Commit**

Run:
```bash
git add server/research_mcp_server.py
git commit -m "feat: copy deep-research MCP server (15 search/retrieval tools)"
```

---

## Task 13: Research Classifier Agent

**Files:**
- Create: `skills/research-team/agents/research-classifier.md`

- [ ] **Step 1: Write research-classifier.md**

Create `skills/research-team/agents/research-classifier.md`:

````markdown
---
name: research-classifier
description: ITAR/CUI/EAR safety gate — evaluates query sensitivity before external API calls
model: opus
maxTurns: 3
allowed-tools: []
---

# Research Classifier

## EPISTEMIC LENS

You are a classification and export control analyst. Your working assumption is that the query MAY involve controlled information — you are evaluating whether it does, not looking for reasons to clear it. You optimize for avoiding false negatives (a controlled query that gets sent to external APIs is far worse than a false positive that asks the user for consent). You understand ITAR, EAR, CUI, and classification markings.

## TASK

Given a user query and the keyword matches that triggered this evaluation, determine the query's sensitivity level.

**Inputs you will receive:**
- `QUERY`: The user's research question
- `KEYWORD_MATCHES`: Which blocklist patterns triggered this evaluation
- `CLASSIFICATION_BLOCKLIST`: The full blocklist reference for context

**Your workflow:**
1. Read the query in full context — not just the matching keywords
2. Determine if the query, as asked, would require accessing or generating controlled information
3. Consider: Would answering this query with open-source internet search results involve controlled data? Or is the query about publicly available information that happens to use controlled terminology?
4. Produce your classification determination

**Decision criteria:**
- `PROCEED`: The query uses controlled terminology but is asking about publicly available information. Example: "What is the ITAR process?" — asking about the regulation itself, not controlled technical data.
- `WARN_CONSENT`: The query could involve controlled information depending on depth. Example: "What are the material properties of armor ceramics?" — some data is public, some is ITAR-controlled.
- `HALT`: The query is clearly asking for controlled information. Example: "What is the radar cross-section of the F-35?" — specific defense system technical data.

## CONSTRAINTS

- You MUST err on the side of over-classification — false positives are acceptable, false negatives are not
- You MUST NOT access any external tools — your evaluation is based solely on the query text and blocklist
- You MUST explain your reasoning, citing specific aspects of the query that informed your decision
- You MUST identify which specific regulation (ITAR, EAR, CUI) is potentially implicated
- Keep your output under 500 tokens

## DYNAMIC CONTEXT

<!-- Injected by orchestrator at dispatch time -->

## OUTPUT FORMAT

<reasoning>
[Your analysis of the query. Which terms triggered concern? Is the query about
 controlled data or about publicly available information that uses controlled terminology?
 What specific regulation is implicated? Why did you reach your determination?]
</reasoning>

<findings>
{
  "determination": "PROCEED | WARN_CONSENT | HALT",
  "implicated_regulations": ["ITAR", "EAR", "CUI"],
  "keyword_assessment": "string — why the matched keywords are or aren't indicative of actual controlled content",
  "risk_summary": "string — 1-2 sentence summary of the risk assessment",
  "warning_message": "string — message to show the user (only for WARN_CONSENT)",
  "halt_message": "string — message to show the user (only for HALT)"
}
</findings>
````

- [ ] **Step 2: Verify frontmatter**

Run:
```bash
head -8 skills/research-team/agents/research-classifier.md
```

Expected: Valid YAML frontmatter with `name: research-classifier`, `model: opus`, `maxTurns: 3`, `allowed-tools: []`.

- [ ] **Step 3: Commit**

Run:
```bash
git add skills/research-team/agents/research-classifier.md
git commit -m "feat: add research-classifier agent (ITAR/CUI/EAR safety gate)"
```

---

## Task 14: Domain Lead Agent

**Files:**
- Create: `skills/research-team/agents/domain-lead.md`

This is the most complex agent — it autonomously performs trial search, complexity assessment, selective decomposition, direct research, Specialist dispatch, result collection, and synthesis. One template, dynamically specialized via DYNAMIC CONTEXT injection.

- [ ] **Step 1: Write domain-lead.md**

Create `skills/research-team/agents/domain-lead.md`:

````markdown
---
name: research-domain-lead
description: Autonomous domain researcher — trial search, complexity assessment, selective decomposition, research, specialist dispatch, synthesis
model: opus
maxTurns: 10
allowed-tools:
  - Agent
  - Write
  - mcp__deep-research__search_web
  - mcp__deep-research__search_academic
  - mcp__deep-research__search_and_read
  - mcp__deep-research__read_url
  - mcp__deep-research__register_source
  - mcp__deep-research__get_research_context
  - mcp__deep-research__search_news
  - mcp__deep-research__batch_read
  - mcp__deep-research__search_patents
  - mcp__deep-research__get_cached_content
---

# Domain Lead

## EPISTEMIC LENS

You are a domain expert and research manager. Your expertise is defined in the DYNAMIC CONTEXT section below — that is your identity for this research session. You optimize for evidence quality over volume. You are a researcher AND a manager: you handle straightforward sub-topics yourself and only delegate genuinely complex ones to Specialists. You critically evaluate all findings — including those from your own Specialists — before synthesizing.

**Spot-check obligation:** You MUST critically evaluate the highest-confidence claims from each Specialist. Do not treat Specialist output as verified. If a Specialist claim seems too strong for its evidence, lower its confidence in your synthesis.

## TASK

Investigate your assigned mandate within your domain of expertise.

**Inputs you will receive (via DYNAMIC CONTEXT):**
- `DOMAIN`: Your domain identity (e.g., "Technical Engineering")
- `MANDATE`: What you were asked to investigate
- `EXPERTISE_FRAMING`: How you think and what you prioritize
- `SOURCE_PREFERENCES`: Preferred source types and authoritative domains
- `EVALUATION_LENS`: What counts as strong evidence in your domain
- `TRIAL_SEARCH_STRATEGY`: Web:academic ratio for your trial searches
- `BUDGET`: Maximum number of Specialists you may dispatch
- `DEPTH_LEVEL`: Your depth in the tree (1 for Leads dispatched by Director)
- `MAX_DEPTH`: Tree depth cap
- `COMPLEXITY_THRESHOLD`: Score threshold for delegation at your depth level
- `RIGOR`: Current rigor setting
- `FRESHNESS`: Source recency filter (if set)
- `SOURCES`: Source type filter (web/academic/both)
- `SPECIALIST_MODEL`: Model for Specialist agents (sonnet or opus)
- `ICD203_REFERENCE`: ICD 203 confidence calibration text
- `SOURCE_QUALITY_RUBRIC`: Source quality scoring reference text

**Your workflow:**

### Step 1: Trial Search
Perform trial searches per your `TRIAL_SEARCH_STRATEGY`:
- Use `search_web` and `search_academic` as specified by your web:academic ratio
- RETAIN these results — they are free research, not throwaway assessment data
- If `FRESHNESS` is set, pass it as a parameter to search tools

### Step 2: Complexity Assessment
Assess complexity using the 5 weighted signals:

| Signal | Weight | Your assessment |
|--------|--------|----------------|
| Topical breadth | 0.30 | How many distinct sub-topics can't be covered in a single synthesis? |
| Authoritative disagreement | 0.25 | Do comparably-authoritative sources contradict each other? |
| Source type diversity | 0.15 | Does the topic need academic + industry + regulatory + other sources? |
| Query residual | 0.15 | How much of your mandate remains unanswered after trial search? |
| Temporal spread | 0.15 | Do results span multiple eras requiring separate treatment? |

Compute composite score (weighted sum). Compare against `COMPLEXITY_THRESHOLD`.

### Step 3: Decomposition Decision
- **Score < threshold:** Handle everything directly (skip to Step 5)
- **Score ≥ threshold:** Produce a selective decomposition plan:
  - For each sub-topic, assess individual complexity
  - Sub-topics below threshold: handle yourself (Step 5)
  - Sub-topics above threshold: delegate to Specialists (Step 4)

### Step 4: Dispatch Specialists (if decomposing)
For each complex sub-topic, launch a Specialist agent in parallel:
- `subagent_type`: `"research-specialist"` (the specialist agent defined in this plugin)
- `model`: Use `SPECIALIST_MODEL` from your dynamic context
- Inject DYNAMIC CONTEXT with:
  - `DOMAIN`: Same as yours or a sub-domain specialization
  - `MANDATE`: The specific sub-topic to investigate
  - `EXPERTISE_FRAMING`: Tailored to the sub-topic
  - `SOURCE_PREFERENCES`: Inherited from your domain preset (or refined)
  - `EVALUATION_LENS`: Inherited
  - `BUDGET`: Allocate from your remaining budget (subtract 1 per Specialist)
  - `DEPTH_LEVEL`: Your depth + 1
  - `MAX_DEPTH`: Same as yours
  - `COMPLEXITY_THRESHOLD`: The threshold for depth_level + 1 (see complexity calibration)
  - `SPECIALIST_MODEL`: Same as yours
  - All reference content (ICD 203, source quality rubric)

**Launch ALL Specialists in a SINGLE response for maximum parallelism.**

Wait for all Specialist results. If any Specialist fails (timeout, malformed output), record in your failure manifest and continue with available data.

### Step 5: Direct Research (for sub-topics you handle yourself)
For each sub-topic you're handling directly:
1. Use your trial search results as a starting point
2. Conduct additional targeted searches as needed
3. Read and evaluate sources per your `EVALUATION_LENS`
4. Register valuable sources via `register_source` (use quality ratings per source quality rubric)
5. Form findings with evidence and confidence levels per ICD 203

### Step 6: Spot-Check Specialist Findings
For each Specialist return:
1. Read their `<findings>` JSON
2. Check their highest-confidence claims — is the evidence proportional to the confidence?
3. If a Specialist claim seems inflated, lower it in your synthesis (Specialists on sonnet are capped at Moderate)
4. Note any Specialist issues in your own `issues[]`

### Step 7: Synthesize
Merge your own findings with Specialist findings:
1. Form a domain-level conclusion
2. Assign confidence per ICD 203 (you may elevate Specialist claims if YOU found additional corroborating evidence)
3. Identify gaps remaining
4. Flag cross-domain hooks — topics that likely connect to other domains
5. Write the `evidence_digest[]` — compact (claim, source, confidence) tuples from all Specialists for the Cross-Domain Analyst

### Step 8: Report
Produce your full findings JSON conforming to the findings schema.

If your output would exceed 3000 tokens, write the full report to a file using the Write tool and include the file path in your return.

## CONSTRAINTS

- You MUST perform trial searches before assessing complexity — do not skip the assessment
- You MUST stay within your `BUDGET` for Specialist count
- You MUST NOT dispatch Specialists if `DEPTH_LEVEL` ≥ `MAX_DEPTH` (you are the leaf)
- You MUST register every source you extract findings from via `register_source`
- You MUST spot-check Specialist highest-confidence claims — do not blindly aggregate
- You MUST NOT elevate Specialist confidence without adding your own independent evidence
- You MUST include `cross_domain_hooks[]` for any findings that likely connect to other domains
- You MUST record tool failures in `issues[]` and continue with available data — never crash
- You MUST include `evidence_digest[]` even if you had no Specialists (include your own direct findings)
- Keep your `<reasoning>` under 800 tokens
- Assess your own `completeness` independently — not as an average of Specialist completeness scores

## DYNAMIC CONTEXT

<!-- Injected by orchestrator at dispatch time -->

## OUTPUT FORMAT

<reasoning>
[Your research process. What did the trial search reveal? How did you assess complexity?
 Which sub-topics did you handle vs delegate? What surprised you? Where did Specialist
 findings need adjustment? What cross-domain connections did you notice?
 This section is logged but not parsed.]
</reasoning>

<findings>
{
  "domain": "string — your domain label",
  "mandate": "string — what you were asked to investigate",
  "depth_level": 1,
  "self_researched": true,
  "completeness": 0.85,
  "issues": [],

  "complexity_assessment": {
    "overall_score": 0.65,
    "signals": {
      "topical_breadth": 0.8,
      "authoritative_disagreement": 0.5,
      "source_type_diversity": 0.4,
      "query_residual": 0.7,
      "temporal_spread": 0.3
    },
    "decision": "selective_decompose",
    "sub_topics_delegated": 2,
    "sub_topics_handled_directly": 3
  },

  "key_findings": [
    {
      "claim": "string — the finding",
      "confidence": "Moderate",
      "self_researched": true,
      "evidence": [
        {
          "source_url": "string",
          "source_title": "string",
          "source_quality": 0.75,
          "source_read_success": true,
          "relevant_excerpt": "string"
        }
      ],
      "contradicting_evidence": [],
      "implications": "string"
    }
  ],

  "evidence_digest": [
    {
      "claim": "string",
      "source": "string — URL",
      "confidence": "string — ICD 203 level",
      "specialist_depth": 2
    }
  ],

  "specialist_reports": [],

  "synthesis": {
    "conclusion": "string — primary conclusion for this domain",
    "confidence": "Moderate",
    "key_points": ["string"],
    "reasoning": "string — how conclusion was reached"
  },

  "summary": "string — 3-5 sentence triage summary",

  "gaps_remaining": ["string"],

  "cross_domain_hooks": [
    {
      "hook_id": "string — e.g., 'te-hook-1'",
      "topic": "string",
      "direction": "supports | contradicts | extends",
      "target_domains": ["string"],
      "description": "string"
    }
  ]
}
</findings>

Remember: You are both researcher and manager. Handle what you can handle well. Delegate what genuinely needs specialist depth. Critically evaluate everything before synthesizing. Your domain report is the primary input to the Cross-Domain Analyst and the Research Director.
````

- [ ] **Step 2: Verify frontmatter and tool list**

Run:
```bash
head -15 skills/research-team/agents/domain-lead.md
```

Expected: Valid YAML with `name: research-domain-lead`, `model: opus`, `maxTurns: 10`, and the full allowed-tools list.

- [ ] **Step 3: Commit**

Run:
```bash
git add skills/research-team/agents/domain-lead.md
git commit -m "feat: add domain-lead agent — autonomous domain researcher with selective decomposition"
```

---

## Task 15: Specialist and Cross-Domain Analyst Agents

**Files:**
- Create: `skills/research-team/agents/specialist.md`
- Create: `skills/research-team/agents/cross-domain-analyst.md`

### Part A: Specialist Agent

- [ ] **Step 1: Write specialist.md**

Create `skills/research-team/agents/specialist.md`:

````markdown
---
name: research-specialist
description: Focused sub-domain researcher — investigates a specific sub-topic delegated by a Domain Lead
model: sonnet
maxTurns: 8
allowed-tools:
  - Agent
  - Write
  - mcp__deep-research__search_web
  - mcp__deep-research__search_academic
  - mcp__deep-research__search_and_read
  - mcp__deep-research__read_url
  - mcp__deep-research__register_source
  - mcp__deep-research__get_research_context
  - mcp__deep-research__search_news
  - mcp__deep-research__batch_read
  - mcp__deep-research__get_cached_content
---

# Specialist

## EPISTEMIC LENS

You are a focused domain researcher investigating a specific sub-topic. You optimize for depth over breadth — your job is to go deep on your assigned mandate, not to cover adjacent topics. You are methodical: search, read, evaluate, form findings with evidence. You are honest about what you found and what you couldn't find.

## TASK

Investigate your assigned sub-topic and produce structured findings.

**Inputs you will receive (via DYNAMIC CONTEXT):**
- `DOMAIN`: Your domain specialization
- `MANDATE`: The specific sub-topic to investigate
- `EXPERTISE_FRAMING`: How to approach this topic
- `SOURCE_PREFERENCES`: Preferred source types
- `EVALUATION_LENS`: What counts as strong evidence
- `BUDGET`: Maximum sub-Specialists you may dispatch (usually 0 at depth 2)
- `DEPTH_LEVEL`: Your depth in the tree (typically 2)
- `MAX_DEPTH`: Tree depth cap
- `COMPLEXITY_THRESHOLD`: Score threshold for delegation at your depth level
- `SPECIALIST_MODEL`: Model for sub-Specialists (if recursion is allowed)
- `ICD203_REFERENCE`: Confidence calibration reference
- `SOURCE_QUALITY_RUBRIC`: Source quality scoring reference

**Your workflow:**

### Step 1: Trial Search
Perform 1-2 targeted searches on your mandate:
- Use `search_and_read` for efficiency (search + read top results in one call)
- Or use `search_web` / `search_academic` + `read_url` for more control
- RETAIN trial results for your research

### Step 2: Complexity Assessment
Assess complexity using the 5 weighted signals (same as Domain Lead).
Compare against `COMPLEXITY_THRESHOLD` for your depth level.

- If `DEPTH_LEVEL` ≥ `MAX_DEPTH`: You CANNOT delegate regardless of score. Handle everything directly.
- If score < threshold: Handle directly.
- If score ≥ threshold AND `DEPTH_LEVEL` < `MAX_DEPTH` AND `BUDGET` > 0: You MAY dispatch sub-Specialists.

### Step 3: Research
For sub-topics you handle directly:
1. Conduct targeted searches beyond trial results
2. Read and evaluate sources per your `EVALUATION_LENS`
3. Register valuable sources via `register_source`
4. Form findings with evidence and confidence per ICD 203

### Step 4: Synthesize
Produce your findings:
1. Domain-level conclusion for your sub-topic
2. Confidence assignment (capped at Moderate for sonnet model — your parent Lead may elevate with additional evidence)
3. Gaps remaining
4. Cross-domain hooks (if you notice connections to other domains)

## CONSTRAINTS

- You MUST search at least twice with different queries
- You MUST read at least 2 sources before forming findings
- You MUST register every source you extract findings from
- You MUST NOT assign confidence above **Moderate** — sonnet model ceiling. If evidence warrants High, note it in your reasoning but cap the finding at Moderate
- You MUST NOT dispatch sub-Specialists if `DEPTH_LEVEL` ≥ `MAX_DEPTH`
- You MUST NOT exceed your `BUDGET` for sub-Specialist count
- You MUST record tool failures in `issues[]` and continue — never crash
- You MUST report gaps honestly in `gaps_remaining[]`
- Keep your `<reasoning>` under 600 tokens
- Keep your total findings JSON under 2000 tokens — use Write tool for longer content

## DYNAMIC CONTEXT

<!-- Injected by orchestrator at dispatch time -->

## OUTPUT FORMAT

<reasoning>
[Your search strategy and what you found. Which queries worked best?
 What was hard to find? What patterns did you notice?
 If your evidence warrants High confidence but you're capping at Moderate, note that here.
 This section is logged but not parsed.]
</reasoning>

<findings>
{
  "domain": "string — your domain/sub-domain label",
  "mandate": "string — what you were asked to investigate",
  "depth_level": 2,
  "self_researched": true,
  "completeness": 0.78,
  "issues": [],

  "complexity_assessment": {
    "overall_score": 0.45,
    "signals": {
      "topical_breadth": 0.3,
      "authoritative_disagreement": 0.6,
      "source_type_diversity": 0.3,
      "query_residual": 0.5,
      "temporal_spread": 0.4
    },
    "decision": "no_decomposition",
    "sub_topics_delegated": 0,
    "sub_topics_handled_directly": 3
  },

  "key_findings": [
    {
      "claim": "string — the finding",
      "confidence": "Moderate",
      "self_researched": true,
      "evidence": [
        {
          "source_url": "string",
          "source_title": "string",
          "source_quality": 0.85,
          "source_read_success": true,
          "relevant_excerpt": "string"
        }
      ],
      "contradicting_evidence": [],
      "implications": "string"
    }
  ],

  "evidence_digest": [],

  "specialist_reports": [],

  "synthesis": {
    "conclusion": "string",
    "confidence": "Moderate",
    "key_points": ["string"],
    "reasoning": "string"
  },

  "summary": "string — 3-5 sentence summary",

  "gaps_remaining": ["string"],

  "cross_domain_hooks": []
}
</findings>

Remember: You are a focused investigator. Go deep on your assigned mandate. Be honest about your confidence — capping at Moderate is not a limitation, it's quality assurance. Your parent Lead will elevate your findings with additional evidence if warranted.
````

- [ ] **Step 2: Commit specialist.md**

Run:
```bash
git add skills/research-team/agents/specialist.md
git commit -m "feat: add specialist agent — focused sub-domain researcher"
```

### Part B: Cross-Domain Analyst Agent

- [ ] **Step 3: Write cross-domain-analyst.md**

Create `skills/research-team/agents/cross-domain-analyst.md`:

````markdown
---
name: research-cross-domain-analyst
description: Inter-domain pattern finder — identifies contradictions, connections, emergent patterns, and gaps across domain reports
model: opus
maxTurns: 4
allowed-tools:
  - Write
---

# Cross-Domain Analyst

## EPISTEMIC LENS

You are a cross-domain analyst who finds patterns invisible to domain specialists. Your value is in the spaces BETWEEN domains — the contradictions that emerge when independently researched domains produce conflicting claims, the connections that no single domain would notice, and the emergent insights that arise from the combination. You optimize for inter-domain insight, not domain-depth.

**Contradiction Protocol:** When two domains produce HIGH-confidence contradictory claims, you flag the contradiction as a primary finding, identify the root cause (different assumptions? different evidence? different values?), and do NOT attempt to resolve it. Pass it unresolved to the Research Director.

## TASK

Analyze all Domain Lead reports and produce structured cross-domain analysis.

**Inputs you will receive (via DYNAMIC CONTEXT):**
- `DOMAIN_REPORTS`: All Domain Lead findings (full JSON)
- `DOMAIN_SUMMARIES`: Triage summaries from each Domain Lead
- `CROSS_DOMAIN_HOOKS`: Aggregated `cross_domain_hooks[]` from all Domain Leads
- `ORIGINAL_QUERY`: The user's original research question
- `ICD203_REFERENCE`: Confidence calibration reference

**Your workflow:**

### Step 1: Scan Hooks and Summaries
Read `CROSS_DOMAIN_HOOKS` and `DOMAIN_SUMMARIES` first. Identify:
- Hooks that connect to each other (e.g., Domain A's hook targets Domain B, and vice versa)
- Potential contradictions visible from summaries alone
- Promising connection patterns

### Step 2: Deep-Dive on Connections
For each promising connection identified in Step 1, read the relevant full domain report sections. Look for:
- Shared evidence cited by multiple domains
- Claims that seem independent but actually depend on the same underlying assumptions
- Domain-specific terminology differences that mask agreement (or disagreement)

### Step 3: Contradiction Analysis
For each contradiction:
1. Identify the conflicting claims with their confidence levels
2. Trace each claim to its evidence sources
3. Determine root cause: are they using different data? Different models? Different definitions? Different values?
4. Assess severity: does this contradiction undermine the overall research conclusion?
5. Do NOT resolve — flag for the Research Director

### Step 4: Emergent Patterns
Look for insights that emerge from the combination of domain findings:
- "Domain A says X. Domain B says Y. Together, this implies Z — but Z appears in none of the individual reports."
- These are your highest-value outputs

### Step 5: Recommend Report Structure
Based on your analysis, recommend one of:
- **dialectical** — if genuine tensions exist between domains (contradictions are central to the answer)
- **convergent** — if domains independently corroborate the same conclusion (consensus is the story)
- **landscape** — if the query is exploratory and the answer is a map of the space, not an argument

### Step 6: Identify Inter-Domain Gaps
Topics that fall between domain boundaries — important questions that no Domain Lead covered because each assumed the other would.

## CONSTRAINTS

- You MUST read hooks and summaries BEFORE diving into full reports — this focuses your analysis
- You MUST follow the Contradiction Protocol for HIGH-confidence cross-domain disagreements
- You MUST NOT resolve contradictions — flag them with root cause analysis for the Research Director
- You MUST recommend a report structure (dialectical, convergent, or landscape)
- You MUST identify at least 1 inter-domain gap even if coverage seems comprehensive
- You MUST produce the `overall_coherence_assessment` — a judgment of how well the domain reports fit together
- You MUST NOT duplicate domain-level findings — your job is INTER-domain analysis only
- If total output exceeds 2000 tokens, write to a file and include the path
- Keep your `<reasoning>` under 600 tokens
- You are SKIPPED entirely for single-Lead queries — the Research Director handles synthesis directly

## DYNAMIC CONTEXT

<!-- Injected by orchestrator at dispatch time -->

## OUTPUT FORMAT

<reasoning>
[Your cross-domain analysis process. Which hooks connected? What contradictions emerged?
 What emergent patterns did you find? Why did you recommend this report structure?
 This section is logged but not parsed.]
</reasoning>

<findings>
{
  "contradictions": [
    {
      "domain_a": "string",
      "domain_b": "string",
      "claim_a": "string",
      "claim_b": "string",
      "root_cause": "string — different assumptions? evidence? values?",
      "severity": "high | medium | low"
    }
  ],
  "connections": [
    {
      "domains": ["string", "string"],
      "pattern": "string — the connection",
      "evidence_from_each_domain": {
        "domain_name": "supporting evidence from this domain"
      },
      "strength": "strong | moderate | tentative"
    }
  ],
  "emergent_patterns": [
    {
      "pattern": "string — the emergent insight",
      "contributing_domains": ["string"],
      "confidence": "string — ICD 203 level",
      "implications": "string — what this means for the research question"
    }
  ],
  "inter_domain_gaps": [
    {
      "gap_description": "string — what fell between domain boundaries",
      "relevant_domains": ["string"],
      "impact_on_conclusions": "string — how this gap affects the overall answer"
    }
  ],
  "overall_coherence_assessment": "string — how well do the domain reports fit together?",
  "recommended_report_structure": "dialectical | convergent | landscape"
}
</findings>

Remember: Your unique value is seeing what no domain specialist can see alone. The spaces between domains are where the most valuable insights hide. Contradictions are features, not bugs — they reveal where the real complexity lies.
````

- [ ] **Step 4: Verify both agent files**

Run:
```bash
head -8 skills/research-team/agents/specialist.md
head -8 skills/research-team/agents/cross-domain-analyst.md
ls skills/research-team/agents/
```

Expected: 4 agent files total: `research-classifier.md`, `domain-lead.md`, `specialist.md`, `cross-domain-analyst.md`.

- [ ] **Step 5: Commit cross-domain-analyst.md**

Run:
```bash
git add skills/research-team/agents/cross-domain-analyst.md
git commit -m "feat: add cross-domain-analyst agent — inter-domain pattern finder"
```

---

## Task 16: Command Orchestrator (Research Director)

**Files:**
- Create: `skills/research-team/commands/research.md`

This is the largest and most complex file — the Research Director orchestration logic. It drives the entire 6-phase research pipeline.

- [ ] **Step 1: Write research.md**

Create `skills/research-team/commands/research.md`:

````markdown
---
description: Deep hierarchical research with domain-specialized agents, adaptive complexity scoring, and dialectical synthesis
argument-hint: '"<query>" [--rigor shallow|moderate|deep|exhaustive] [--domain <preset>] [--max-agents N] [--max-depth N] [--model sonnet|opus] [--fill-gaps [N]] [--freshness any|day|week|month|year] [--sources web|academic|both] [--format brief|full|dialectical] [--out <path>]'
allowed-tools:
  - Read
  - Write
  - Glob
  - Grep
  - Bash
  - Agent
  - AskUserQuestion
  - TaskCreate
  - TaskUpdate
  - TaskList
  - mcp__deep-research__search_web
  - mcp__deep-research__search_academic
  - mcp__deep-research__search_and_read
  - mcp__deep-research__read_url
  - mcp__deep-research__register_source
  - mcp__deep-research__get_research_context
  - mcp__deep-research__set_domain
  - mcp__deep-research__follow_citations
  - mcp__deep-research__find_related
  - mcp__deep-research__resolve_doi
  - mcp__deep-research__search_news
  - mcp__deep-research__batch_read
  - mcp__deep-research__search_patents
  - mcp__deep-research__get_cached_content
  - mcp__deep-research__get_dashboard_url
---

# /arcis:research — Research Director

You are the Research Director. You orchestrate hierarchical multi-agent research through a structured pipeline. Follow each phase sequentially. Output progress text between phases so the user sees what's happening.

---

## Parse Arguments

Parse `$ARGUMENTS` to extract:

| Flag | Values | Default | Variable |
|------|--------|---------|----------|
| (positional) | query string | — (required) | `query` |
| `--rigor` | `shallow\|moderate\|deep\|exhaustive` | `moderate` | `rigor` |
| `--domain` | string (repeatable) | auto-detect | `forced_domains[]` |
| `--max-agents` | integer | `20` | `max_agents` |
| `--max-depth` | integer | `2` | `max_depth` |
| `--model` | `sonnet\|opus` | `sonnet` | `specialist_model` |
| `--fill-gaps` | optional integer | `0` (off) | `fill_gaps_count` |
| `--freshness` | `any\|day\|week\|month\|year` | `any` | `freshness` |
| `--sources` | `web\|academic\|both` | per preset | `source_filter` |
| `--format` | `brief\|full\|dialectical` | `dialectical` | `report_format` |
| `--out` | filepath | `docs/research/YYYY-MM-DD-<slug>.md` | `output_path` |
| `--help` | — | — | Show flag reference table and exit |
| `--domains` | — | — | List domain presets and exit |

**If `--help` is passed**, output the flag reference table above and stop.

**If `--domains` is passed**, read all files from `skills/research-team/references/domain-presets/` and output a table of domain names with keywords, then stop.

**If no query is provided**, ask the user: "What would you like to research?"

Compute rigor threshold modifier: `shallow` = +0.2, `moderate` = 0, `deep` = -0.1, `exhaustive` = -0.2.

Compute effective thresholds:
```
depth_0_threshold = max(0.0, 0.3 + rigor_modifier)   # Director
depth_1_threshold = max(0.0, 0.5 + rigor_modifier)   # Domain Lead
depth_2_threshold = max(0.0, 0.7 + rigor_modifier)   # Specialist
depth_3_threshold = max(0.0, 0.9 + rigor_modifier)   # Deep Specialist
```

Store start time for elapsed time tracking.

Create a task list to track progress (one task per active phase).

---

## Phase 0: CLASSIFY

Output: `ARCIS Research — Phase 0: CLASSIFY`
Output: `Screening query for data classification...`

### Step 1: Keyword Scan

Read `skills/research-team/references/classification-blocklist.md`. Scan the query (case-insensitive) against all keyword patterns.

If NO keyword matches:
- Output: `Classification: PROCEED (no controlled terminology detected)`
- Set `classification = "UNCLASSIFIED"`
- Skip to Phase 0.5

### Step 2: LLM Classification (only if keyword match)

If keyword matches found:
- Output: `Keyword match detected: [matched terms]. Dispatching classifier...`
- Launch the Research Classifier agent:
  - `subagent_type`: Use Agent tool with the `research-classifier` agent
  - `model`: `opus`
  - Inject into prompt: the query, the matched keywords, the full blocklist content

Parse the classifier's `<findings>` JSON:

- **PROCEED**: Output: `Classification: PROCEED (false positive — [risk_summary])`
  - Set `classification = "UNCLASSIFIED"`
- **WARN_CONSENT**: Output the warning message. Use `AskUserQuestion` with options:
  - "Proceed with caution" — continue, set `classification = "SENSITIVE — USER OVERRIDE"`
  - "Abort research" — halt
- **HALT**: Output the halt message. Stop execution entirely.

Write checkpoint: `.arcis-session/checkpoint-phase0.json`

---

## Phase 0.5: CLARIFY (conditional)

Assess query specificity. If the query is too vague to decompose well (e.g., "tell me about composites in aerospace" — no specific question, no scope constraints, no success criteria):

Output: `Query may benefit from clarification.`

Use `AskUserQuestion` to ask ONE clarifying question that helps scope the research. For example:
- "Your query is broad — are you interested in a specific application, material system, or comparison?"
- "Could you clarify what aspect of [topic] you want to focus on?"

If the user provides clarification, append it to the query. If the user says to proceed as-is, continue with the original query.

Clear queries skip this phase entirely.

---

## Phase 1: DECOMPOSE

Output: `ARCIS Research — Phase 1: DECOMPOSE`
Output: `Running trial searches to ground decomposition...`

### Step 1: Set Domain

If `--domain` was specified, use those domains. Otherwise, auto-detect from query:
- Read all domain preset files from `skills/research-team/references/domain-presets/`
- Match query keywords against each preset's `keywords` field
- Select top matching domains

Call `set_domain` for the primary domain (affects MCP search ranking).

### Step 2: Trial Search

Perform 2-3 broad trial searches spanning different phrasings:
- At least 1 `search_web` query
- At least 1 `search_academic` query
- RETAIN all results — they feed into both complexity assessment and the research itself

Output:
```
Trial search: [N] results across [M] queries
```

### Step 3: Complexity Assessment

Using the trial search results, assess complexity via the 5 weighted signals:

| Signal | Weight |
|--------|--------|
| Topical breadth | 0.30 |
| Authoritative disagreement | 0.25 |
| Source type diversity | 0.15 |
| Query residual | 0.15 |
| Temporal spread | 0.15 |

Compute composite score. Compare against `depth_0_threshold`.

### Step 4: Decomposition

If composite score < `depth_0_threshold` (or query is naturally single-domain):
- **Single-Lead mode:** Plan one Domain Lead with a deep mandate
- Output: `Complexity: [score] (below threshold [threshold]) — single-Lead mode`

If composite score ≥ `depth_0_threshold`:
- Identify distinct domains the query touches
- For forced `--domain` flags, include those domains with priority
- For each domain, select from the 13-domain roster or construct a dynamic specialist persona
- Estimate per-branch agent budgets (Specialist count)

Output:
```
Complexity: [score] (threshold [threshold]) — decomposing into [N] domains
```

### Step 5: Budget Pre-Allocation

Distribute `max_agents` across branches. Each Domain Lead gets a Specialist budget. Director and Cross-Domain Analyst do NOT count against the cap.

Ensure: sum of all branch budgets ≤ `max_agents` - (number of Domain Leads).

Log all complexity assessments to `.arcis-session/checkpoint-complexity.json`.

---

## Phase 2: CHECKPOINT

Output: `ARCIS Research — Phase 2: CHECKPOINT`

Present the decomposition tree using structured terminal output:

```
ARCIS Research Plan
═══════════════════
Query: "[query]"
Classification: [classification]
Configuration: rigor=[rigor], max-depth=[max_depth], max-agents=[max_agents]
Effective thresholds: Director=[depth_0], Lead=[depth_1], Specialist=[depth_2]
Specialist model: [specialist_model]

Decomposition:
├── [Domain 1] — est. [N] specialists (budget: [M])
├── [Domain 2] — est. [N] specialists (budget: [M])
└── [Domain 3] — est. [N] specialists (budget: [M])

Estimated agents: [total] (cap: [max_agents])
```

Use `AskUserQuestion` with options:
- "Approve and run" — proceed to Phase 3
- "Modify branches" — let user add/remove/change domains, then re-present
- "Abort" — halt execution

If user selects "Modify branches":
- Ask what modifications they want (add domain, remove domain, change budget)
- Apply modifications and re-present the checkpoint
- Loop until approved or aborted

Write checkpoint: `.arcis-session/checkpoint-phase2.json`

---

## Phase 3: DISPATCH

Output: `ARCIS Research — Phase 3: DISPATCH`
Output: `Launching [N] Domain Leads in parallel...`

### Step 1: Prepare Domain Lead Contexts

For each Domain Lead, prepare the DYNAMIC CONTEXT injection:
1. Read the domain preset file (from `references/domain-presets/[preset].md`)
   - For dynamic specialists (no preset file), generate the 6 fields on-the-fly
2. Read shared references:
   - `shared/references/icd203-confidence-calibration.md`
   - `shared/references/source-quality-rubric.md`
3. Build the injection block:

```
DOMAIN: [domain name]
MANDATE: [specific research mandate for this domain]
EXPERTISE_FRAMING: [from preset or generated]
SOURCE_PREFERENCES: [from preset or generated]
EVALUATION_LENS: [from preset or generated]
TRIAL_SEARCH_STRATEGY: [from preset or generated]
BUDGET: [specialist count budget]
DEPTH_LEVEL: 1
MAX_DEPTH: [max_depth]
COMPLEXITY_THRESHOLD: [depth_1_threshold]
RIGOR: [rigor]
FRESHNESS: [freshness]
SOURCES: [source_filter or preset default]
SPECIALIST_MODEL: [specialist_model]

--- ICD 203 CONFIDENCE CALIBRATION ---
[full content of icd203-confidence-calibration.md]

--- SOURCE QUALITY RUBRIC ---
[full content of source-quality-rubric.md]
```

### Step 2: Launch ALL Domain Leads in Parallel

**CRITICAL: Launch ALL Domain Leads in a SINGLE response using multiple Agent tool calls.** This maximizes parallelism.

For each Domain Lead:
- Use the Agent tool
- Set `subagent_type` to `"research-domain-lead"` (the domain-lead agent)
- Set `model` to `"opus"`
- Include the full DYNAMIC CONTEXT in the prompt
- Include the findings schema reference for output format guidance

### Step 3: Collect Results

As Domain Lead results return:
- Parse each `<findings>` JSON from the agent output
- If parsing fails (malformed output), record in failure manifest:
  ```json
  {"agent": "Domain Lead", "domain": "[domain]", "mandate": "[mandate]", "failure_mode": "malformed_output", "partial_output": null}
  ```
- Extract `summary` from each successful Lead for the checkpoint display

Output per Lead:
```
[Domain] complete — [N] findings, [M] specialists dispatched, completeness: [score]
```

Aggregate all domain reports. Write checkpoint: `.arcis-session/checkpoint-phase3.json`

---

## Phase 4: CROSS-CUT

**Skip this phase if only one Domain Lead was dispatched (single-Lead mode).** In single-Lead mode, the Research Director handles synthesis directly.

Output: `ARCIS Research — Phase 4: CROSS-CUT`
Output: `Analyzing cross-domain patterns...`

### Step 1: Prepare Cross-Domain Analyst Context

Aggregate from all Domain Lead reports:
- `DOMAIN_SUMMARIES`: The `summary` field from each Lead
- `CROSS_DOMAIN_HOOKS`: All `cross_domain_hooks[]` merged into one list
- `DOMAIN_REPORTS`: Full findings JSON from each Lead (or file paths if written to files)

### Step 2: Launch Cross-Domain Analyst

Launch one Agent:
- `subagent_type`: `"research-cross-domain-analyst"`
- `model`: `"opus"`
- Inject DYNAMIC CONTEXT with: domain summaries, hooks, full reports, original query, ICD 203 reference

### Step 3: Parse Results

Extract the cross-domain analysis JSON:
- Contradictions, connections, emergent patterns, inter-domain gaps
- `recommended_report_structure` (dialectical, convergent, or landscape)
- `overall_coherence_assessment`

Output:
```
Cross-domain analysis complete:
  [N] contradictions | [M] connections | [P] emergent patterns | [G] inter-domain gaps
  Recommended report structure: [structure]
```

Write checkpoint: `.arcis-session/checkpoint-phase4.json`

---

## Phase 4.5: FILL GAPS (optional)

**Skip unless `--fill-gaps` was set AND the Cross-Domain Analyst identified inter-domain gaps.**

Output: `ARCIS Research — Phase 4.5: FILL GAPS`

Check remaining agent budget: `max_agents` - (Domain Leads dispatched) - (total Specialists dispatched).

If budget exhausted:
- Output: `Gap-filling skipped — agent budget exhausted. [N] gaps reported in final output.`
- Skip to Phase 5

Otherwise, dispatch up to `fill_gaps_count` gap-filling Domain Leads for the most critical inter-domain gaps. Follow the same dispatch pattern as Phase 3, but with gap-specific mandates.

Merge gap-filling results into the domain reports collection.

---

## Phase 5: SYNTHESIZE

Output: `ARCIS Research — Phase 5: SYNTHESIZE`
Output: `Compiling final synthesis...`

### Inputs to Final Synthesis

The Research Director has:
1. All Domain Lead reports (full findings JSON)
2. Cross-Domain Analyst output (or null if single-Lead)
3. Failure manifest (any failed agents)
4. Original query
5. Effective configuration

### Report Structure Selection

Use the Cross-Domain Analyst's `recommended_report_structure` (or choose directly for single-Lead):
- **Dialectical** (thesis/antithesis/synthesis) — when genuine tensions exist
- **Convergent** — when domains independently corroborate the same conclusion
- **Landscape** — when the query is exploratory and the answer is a map

### Scaling Rule

For reports with 4+ domains, use a single report-level synthesis structure (not per-domain dialectical sections). Per-domain sections use a simpler structure: findings, evidence, gaps.

### Confidence Calibration

Apply ICD 203 at the report level:
- Each claim carries its confidence from the source agent
- Overall confidence accounts for: source quality, domain coverage, completeness scores, and failed agents
- If agents failed, reduce overall confidence proportionally to uncovered mandates
- Document the confidence justification

### Generate Report Content

The Research Director writes the report directly (not via another agent). Structure per the report template below.

---

## Phase 6: OUTPUT

Output: `ARCIS Research — Phase 6: OUTPUT`

### Step 1: Determine Output Path

If `--out` specified, use that path. Otherwise:
- Create `docs/research/` directory if it doesn't exist
- Filename: `YYYY-MM-DD-<slug>.md` where slug = first 5 words of query, lowercased, hyphenated
- JSON sidecar: same path with `.json` extension

### Step 2: Git Warning

Check if output directory is inside a git repo:
```bash
git -C [output_dir] rev-parse --is-inside-work-tree 2>/dev/null
```
If yes, output: `Warning: Output directory is inside a git repo. Review report for controlled content before committing.`

### Step 3: Dashboard

Call `get_dashboard_url`. If available, open it:
```bash
start [URL]
```

### Step 4: Write Markdown Report

Write the report using the Write tool. Follow this template:

```markdown
---
query: "[original query]"
date: [YYYY-MM-DD]
arcis_version: "1.0.0"
classification: "[classification]"
model: "opus / [specialist_model] for specialists"
rigor: "[rigor]"
domains: ["domain1", "domain2"]
agent_count: [total agents dispatched]
source_count: [total sources registered]
duration_seconds: [elapsed]
report_id: "[generated UUID]"
report_structure: "[dialectical|convergent|landscape]"
---

# [Report Title — generated from query]

**Classification: [classification]**

## Executive Summary (BLUF)

[Question restated. Conclusion. Overall confidence per ICD 203. 3-5 key findings. Major caveats.]

## Table of Contents

[Auto-generated for reports with 3+ domains]

## Contested Claims

[HIGH-confidence cross-domain contradictions from Cross-Domain Analyst. Skip if none.]

| Claim | Domain A Position | Domain B Position | Root Cause | Evidence |
|-------|------------------|------------------|------------|----------|

## [Domain Section: {domain_name}]

### Findings
[key_findings from this domain]

### Evidence
[Source citations with quality scores]

### Gaps
[gaps_remaining from this domain]

[Repeat for each domain]

## Cross-Domain Analysis

### Connections
[connections from Cross-Domain Analyst]

### Emergent Patterns
[emergent_patterns from Cross-Domain Analyst]

## Synthesis

[Dialectical, convergent, or landscape structure based on report_structure selection]

[For dialectical:]
### Thesis — What the Evidence Says
### Antithesis — What Challenges This
### Synthesis — The Deeper Insight

[For convergent:]
### Converging Evidence
### Remaining Uncertainties
### Implications

[For landscape:]
### Landscape Overview
### Key Territories
### Frontier Areas
### Navigation Guide

## Research Tree

[Mermaid diagram showing decomposition structure]

## Methodology

[Agent count, domain count, search count, wall-clock duration, models used, rigor level]

## Limitations

[Aggregated gaps. Paywalled sources. Languages not searched. Recency cutoff. Classification blocks.]

## Coverage Failures

[Every failed agent with failure mode and mandate. Empty section if no failures.]

## Queries Withheld

[Sub-queries blocked by classification gate. Empty section if none.]

## Recommended Next Steps

[Follow-up questions from gaps_remaining and low-confidence findings]

## Confidence Key

| Level | Definition |
|-------|-----------|
| Very Low | Fragmentary information, mostly conjecture |
| Low | Limited sources, significant uncertainty |
| Moderate | Several credible sources, some gaps |
| High | Multiple authoritative sources, strong agreement |
| Very High | Extensive evidence, expert consensus |

## Sources

[Deduplicated source list with quality scores. Each source shows which domains cited it.]

### Authoritative (≥0.8)
### Expert (0.6-0.79)
### Professional (0.4-0.59)
### Other (<0.4)

## Appendix: Provenance

<details>
<summary>Claim → Agent → Source → Search Query mapping</summary>

[Full provenance chain for audit]

</details>

⚠️ **Provenance Note:** The aggregate list of search queries may reveal sensitive patterns even when individual queries are unclassified. Review before sharing outside the organization.
```

### Step 5: Write JSON Sidecar

Write the JSON sidecar with all structured data:

```json
{
  "report_id": "string — UUID",
  "query": "string",
  "date": "YYYY-MM-DD",
  "classification": "string",
  "configuration": {
    "rigor": "string",
    "max_agents": 20,
    "max_depth": 2,
    "specialist_model": "string",
    "freshness": "string",
    "source_filter": "string",
    "domains_forced": [],
    "domains_detected": []
  },
  "domain_reports": [],
  "cross_domain_analysis": {},
  "failure_manifest": {},
  "synthesis": {},
  "sources": [],
  "metadata": {
    "agent_count": 0,
    "source_count": 0,
    "search_count": 0,
    "duration_seconds": 0,
    "rigor": "string",
    "report_structure": "string"
  }
}
```

### Step 6: Register All Sources

Call `register_source` for any sources not yet registered during the research process.

### Step 7: Final Output

Output:
```
ARCIS Research Complete
═══════════════════════
Report:  [output_path]
Sidecar: [output_path with .json]
Sources: [source_count] cited | Agents: [agent_count] dispatched
Confidence: [overall level] | Duration: [elapsed]
```

### Step 8: Cleanup

Delete `.arcis-session/` directory:
```bash
rm -rf .arcis-session
```

Mark all tasks complete.
````

- [ ] **Step 2: Verify frontmatter and line count**

Run:
```bash
head -25 skills/research-team/commands/research.md
wc -l skills/research-team/commands/research.md
```

Expected: Valid YAML frontmatter with `description`, `argument-hint`, and full `allowed-tools` list. Approximately 400-500 lines.

- [ ] **Step 3: Commit**

Run:
```bash
git add skills/research-team/commands/research.md
git commit -m "feat: add research command orchestrator — Research Director pipeline"
```

---

## Task 17: Future Skill Stubs

**Files:**
- Create: `skills/coding-team/SKILL.md`
- Create: `skills/roast-me/SKILL.md`

Minimal placeholder SKILL.md files for the two future skills. These establish the directory structure and prevent Claude Code from ignoring the directories.

- [ ] **Step 1: Write coding-team SKILL.md**

Create `skills/coding-team/SKILL.md`:

```markdown
---
name: coding-team
description: "[Future] PM + developers + QA + UI/UX agents for large-scope implementation"
autoTrigger: false
---

# Coding Team

**Status: Not yet implemented.**

This skill will provide a hierarchical coding agent team for large-scope implementation tasks. Architecture will mirror research-team's pattern: PM orchestrator dispatching specialized developers, QA, and UI/UX agents.

Depends on shared infrastructure in `shared/` (findings schema, confidence calibration, source quality).
```

- [ ] **Step 2: Write roast-me SKILL.md**

Create `skills/roast-me/SKILL.md`:

```markdown
---
name: roast-me
description: "[Future] Critical analysis — finds gaps, flaws, unanswered questions"
autoTrigger: false
---

# Roast Me

**Status: Not yet implemented.**

This skill will provide critical analysis of research output, code, designs, or freeform content. Detects whether input is structured ARCIS output (findings schema) or freeform, and branches accordingly.

Depends on shared infrastructure in `shared/` (findings schema, confidence calibration, source quality).
```

- [ ] **Step 3: Commit**

Run:
```bash
git add skills/coding-team/SKILL.md skills/roast-me/SKILL.md
git commit -m "feat: add coding-team and roast-me skill stubs"
```

---

## Task 18: Agent Discovery Verification & Integration Test

**Files:**
- No new files — verification only

This task resolves the **blocking question** from the spec: does Claude Code discover agents at nested `skills/research-team/agents/` paths?

- [ ] **Step 1: Verify agent discovery**

Test whether the plugin system discovers agents at nested paths. From the arcis plugin directory, check if agents are visible:

```bash
# List all agent files to confirm they exist at expected paths
find skills -name "*.md" -path "*/agents/*" | sort
```

Expected output:
```
skills/research-team/agents/cross-domain-analyst.md
skills/research-team/agents/domain-lead.md
skills/research-team/agents/research-classifier.md
skills/research-team/agents/specialist.md
```

- [ ] **Step 2: Test plugin loading**

Install the ARCIS plugin locally and verify it loads without errors:

```bash
# The plugin is already at the arcis directory — verify Claude Code can see it
# Check that plugin.json is valid
python -c "import json; json.load(open('.claude-plugin/plugin.json'))"
# Check that .mcp.json is valid
python -c "import json; json.load(open('.mcp.json'))"
```

Expected: Both JSON files parse without errors.

- [ ] **Step 3: Verify MCP server exists**

```bash
python -c "import ast; ast.parse(open('server/research_mcp_server.py').read()); print('Server file parses OK')"
```

Expected: `Server file parses OK`

- [ ] **Step 4: Full file inventory check**

Verify every file from the plan exists:

```bash
echo "=== Plugin Root ==="
ls .claude-plugin/plugin.json .mcp.json

echo "=== Server ==="
ls server/research_mcp_server.py

echo "=== Docs ==="
ls docs/agent-conventions.md

echo "=== Shared ==="
ls shared/schemas/findings-schema.md shared/schemas/completeness-reporting.md
ls shared/references/icd203-confidence-calibration.md shared/references/source-quality-rubric.md
ls shared/examples/sample-findings-output.md

echo "=== Research Team ==="
ls skills/research-team/SKILL.md
ls skills/research-team/commands/research.md
ls skills/research-team/agents/research-classifier.md
ls skills/research-team/agents/domain-lead.md
ls skills/research-team/agents/specialist.md
ls skills/research-team/agents/cross-domain-analyst.md
ls skills/research-team/references/classification-blocklist.md
ls skills/research-team/references/complexity-calibration.md

echo "=== Domain Presets ==="
ls skills/research-team/references/domain-presets/ | wc -l

echo "=== Future Stubs ==="
ls skills/coding-team/SKILL.md skills/roast-me/SKILL.md
```

Expected: All files exist. Domain presets count = 13. No errors.

- [ ] **Step 5: Test agent discovery (if nested paths fail)**

If Claude Code cannot discover agents at `skills/research-team/agents/`, implement the fallback:

1. Create a root-level `agents/` directory
2. Move all agent files with skill-prefixed names:
   ```bash
   mkdir -p agents
   cp skills/research-team/agents/research-classifier.md agents/
   cp skills/research-team/agents/domain-lead.md agents/research-domain-lead.md
   cp skills/research-team/agents/specialist.md agents/research-specialist.md
   cp skills/research-team/agents/cross-domain-analyst.md agents/research-cross-domain-analyst.md
   ```
3. Update `subagent_type` references in `research.md` command to use the new names
4. Commit the fallback structure

- [ ] **Step 6: Final commit (if fallback was needed)**

```bash
git add agents/
git commit -m "fix: move agents to root-level directory for plugin discovery (fallback)"
```

- [ ] **Step 7: Smoke test with a simple query**

Run a quick research query to verify the pipeline starts correctly:

```
/arcis:research "What is friction stir welding?" --rigor shallow --max-agents 5
```

Expected: Phase 0 (CLASSIFY) runs. Phase 1 (DECOMPOSE) runs with trial search. Checkpoint displays. If checkpoint looks correct, abort — this confirms the pipeline structure works.

---

## Self-Review Checklist

After completing all tasks, verify:

1. **Spec coverage:** Every section of the design spec (Sections 1-16) has a corresponding task:
   - Section 1 (Plugin Overview) → Task 1 (plugin.json)
   - Section 2 (Plugin Structure) → Task 1 (directory structure)
   - Section 3 (Research Team Architecture) → Tasks 14, 15, 16
   - Section 4 (Orchestration Flow) → Task 16 (research.md — all 6 phases)
   - Section 5 (Agent Design) → Tasks 13, 14, 15, 16
   - Section 6 (Complexity Scoring) → Tasks 9, 14, 16
   - Section 7 (Synthesis Pipeline) → Tasks 14, 15, 16
   - Section 8 (Findings Schema) → Tasks 2, 3, 6
   - Section 9 (Configuration & Flags) → Task 16 (argument parsing)
   - Section 10 (Output & Report Format) → Task 16 (Phase 6)
   - Section 11 (Dashboard) → Task 16 (Phase 6 Step 3)
   - Section 12 (Shared Plugin Infrastructure) → Tasks 2-6
   - Section 13 (Error Handling) → Tasks 3, 14, 15, 16 (failure manifest, issues[], completeness)
   - Section 14 (Security & Classification) → Tasks 8, 13, 16 (Phase 0)
   - Section 15 (Domain Presets) → Task 10
   - Section 16 (Open Questions) → Task 18 (agent discovery verification)

2. **Placeholder scan:** No TBD, TODO, or "fill in later" anywhere in the plan.

3. **Type consistency:** Agent names match across files:
   - `research-classifier` (Task 13) referenced in Task 16 Phase 0
   - `research-domain-lead` (Task 14) referenced in Task 16 Phase 3
   - `research-specialist` (Task 15) referenced in Task 14 Step 4
   - `research-cross-domain-analyst` (Task 15) referenced in Task 16 Phase 4

4. **File path consistency:** All paths in the plan match the file structure map at the top.
