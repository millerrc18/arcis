---
description: Deep multi-step research with parallel agents, cross-domain search, citation tracing, dialectical synthesis, and council debate
argument-hint: "<query>" [--depth shallow|moderate|deep|exhaustive] [--domain <domain>] [--output <path>]
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

# /research — Deep Research Pipeline

You are executing the deep-research pipeline. Follow each phase sequentially. Do not skip phases unless the depth config says to. Output progress text between phases so the user sees what's happening in real-time.

## Parse Arguments

Parse `$ARGUMENTS` to extract:
- `query`: The research question (required — everything not a flag)
- `--depth`: shallow, moderate (default), deep, or exhaustive
- `--domain`: Domain preset (default: auto-detect from query)
- `--output`: Output file path (default: `docs/research/YYYY-MM-DD-<slug>.md`)

If no query is provided, ask the user: "What would you like to research?"

Store start time for elapsed time tracking.

**Depth determines which phases run:**

| Depth | Phases | Agents |
|-------|--------|--------|
| shallow | 0→1→2→3→6 | 2 direct searchers |
| moderate | 0→1→2→2.5→3→4→6 | 2 direct + 1 lateral + 1 contrarian + tracer + 1 refine |
| deep | 0→1→2→2.5→3→4→5→6 | 3 direct + 2 lateral + 1 contrarian + tracer + 2 refine + council |
| exhaustive | 0→1→2→2.5→3→4→5→6 | 5 direct + 3 lateral + 1 contrarian + tracer + 3 refine + council |

Create a task list to track progress (one task per active phase).

---

## Phase 0: CLASSIFY

Output: `--- Phase 0: CLASSIFY ---`
Output: `Screening research topic for data classification...`

**Step 1: Keyword scan**

Read `skills/research-methodology/references/classification-blocklist.md` if it exists. Check the query against ITAR/CUI/EAR indicator patterns:
- USML categories, "defense article", "defense service"
- CUI/FOUO markings
- Export control terms (ITAR, EAR, ECCN)
- Weapons/systems terminology
- Classification indicators (secret, TS, SCI, SAP)

If no keyword match → classification = `PUBLIC`, proceed.

**Step 2: LLM classification (only if keyword hit)**

Evaluate whether the query involves ITAR/CUI/EAR data. Err on over-classification.

- `PUBLIC` → proceed
- `SENSITIVE` → warn user via AskUserQuestion. If declined, halt.
- `CONTROLLED` → halt with message about using internal resources

Write checkpoint: `.research-session/checkpoint-phase0.json`

---

## Phase 1: PLAN

Output: `--- Phase 1: PLAN ---`
Output: `Decomposing research query into sub-questions...`

**Step 1: Set domain**

If `--domain` was specified, call `set_domain`. Otherwise auto-detect from query keywords (CMMC → cybersecurity-compliance, SPC → manufacturing-quality, etc.). Default to "general".

**Step 2: Load domain preset**

Try to read `skills/research-methodology/references/domains/{domain}.md` for the domain's preferred sources, lateral strategy, and temporal emphasis. Pass this to the planner.

**Step 3: Spawn planner agent**

Launch one Agent:
- `subagent_type`: "research-planner"
- `model`: "opus"
- Prompt includes: query, domain, depth level, domain preset content, requested agent counts

**Step 4: Parse planner output**

Extract from `<findings>` JSON: `direct_questions`, `lateral_questions`, `contrarian_angle`. Assign to respective searcher agents.

Write checkpoint: `.research-session/checkpoint-phase1.json`

---

## Phase 2: GATHER

Output: `--- Phase 2: GATHER ---`

Count total agents based on depth. Output:
```
Searching [N] sub-questions in parallel...
Dispatching [TOTAL] agents ([D] direct, [L] lateral, [C] contrarian)...
```

**Launch ALL searcher agents in parallel in a SINGLE response:**

**Direct searchers** (one per direct sub-question):
- `subagent_type`: "research-searcher", `model`: "sonnet"
- Each prompt includes: sub-question, temporal assignment, search terms, domain

**Lateral searchers** (moderate+ only):
- `subagent_type`: "research-lateral", `model`: "sonnet"
- Each prompt includes: lateral question, source domain, primary domain, search terms, connection rationale

**Contrarian searcher** (moderate+ only, exactly 1):
- `subagent_type`: "research-contrarian", `model`: "sonnet"
- Prompt includes: counter-thesis, search terms, what would disprove consensus

**Collect results** — merge all findings into `gathered_findings`. Output source discovery summary:
```
Found [N] sources across [M] agents

  [Academic] "Title" (Year)
       Venue | Quality: 0.XX
       URL
```

Write to `.research-session/gathered_findings.json` if > 3000 tokens.
Write checkpoint: `.research-session/checkpoint-phase2.json`

---

## Phase 2.5: TRACE (moderate+ only)

Skip if depth = shallow.

Output: `--- Phase 2.5: TRACE ---`
Output: `Following citation chains from top [N] sources...`

**Step 1: Identify top sources**

From gathered findings, select the 3-5 highest-quality academic sources (by quality_score).

**Step 2: Spawn tracer agent**

Launch one Agent:
- `subagent_type`: "research-tracer", `model`: "sonnet"
- Prompt includes: top source URLs/titles/DOIs, domain

**Step 3: Merge traced sources**

Add tracer findings to gathered_findings. Output:
```
  Traced [N] citation chains → discovered [M] primary sources
```

Write checkpoint: `.research-session/checkpoint-phase2.5.json`

---

## Phase 3: SYNTHESIZE

Output: `--- Phase 3: SYNTHESIZE ---`
Output: `Synthesizing findings from [N] sources...`

**Spawn synthesizer agent:**
- `subagent_type`: "research-synthesizer", `model`: "opus"
- Prompt includes: original query, domain, depth, ALL gathered findings

**Extract output:** executive summary, thesis/antithesis/synthesis, gap list, confidence level.

Output:
```
  Synthesis complete: [N] sources analyzed | [G] gaps identified | Confidence: [level]
```

Write checkpoint: `.research-session/checkpoint-phase3.json`

---

## Phase 4: REFINE (moderate+ only, adaptive stopping)

Skip if depth = shallow.

Output: `--- Phase 4: REFINE ---`

**Max iterations by depth:** moderate=1, deep=2, exhaustive=3

**For each iteration:**

1. Output: `Refine iteration [I]: addressing [N] gaps...`
2. Spawn refiner agent:
   - `subagent_type`: "research-refiner", `model`: "sonnet"
   - Prompt: gap list (highest importance first), domain, existing source count
3. Collect results
4. Check stopping conditions:
   - `overall_novelty` < 0.10 → stop (new findings overlap with existing)
   - All critical gaps resolved → stop
   - Refiner recommends stop → stop
5. Output: `  Refine iteration [I]: novelty=[X], [N] new sources, [G] gaps closed`
6. If stopping early: `  Stopping refinement: [reason]`

Merge refiner findings into gathered_findings.
Write checkpoint: `.research-session/checkpoint-phase4.json`

---

## Phase 5: DELIBERATE (deep/exhaustive only)

Skip if depth = shallow or moderate.

Output: `--- Phase 5: DELIBERATE (Council Debate) ---`
Output: `Convening 5-agent council for deliberation...`

### Round 1: Independent Assessment

Launch ALL 5 council agents in parallel in a SINGLE response:

1. `subagent_type`: "council-synthesizer", `model`: "sonnet"
2. `subagent_type`: "council-skeptic", `model`: "sonnet"
3. `subagent_type`: "council-practitioner", `model`: "sonnet"
4. `subagent_type`: "council-contrarian", `model`: "sonnet"
5. `subagent_type`: "council-arbiter", `model`: "opus"

Each receives: the full synthesis (thesis/antithesis/synthesis), executive summary, source list. NO agent sees any other agent's output.

Output:
```
  Round 1 complete — 5 independent assessments received
  Analyzing divergences...
```

### Round 1.5: Divergence Detection (automated, not agent)

Compare all 5 assessments:
1. **Findings matrix** — flag findings in one agent's top 3 but missing from another's
2. **Recommendation conflicts** — flag contradictory recommendations
3. **Confidence divergence** — flag claims where confidence differs by ≥2
4. **Crux misalignment** — compare what each identified as key uncertainty

Set aside consensus items (unanimous agreement). Build debate agenda from divergences only.

Output:
```
  [N] consensus items identified
  [M] divergence points flagged for debate
```

### Round 2: Structured Debate (on divergences only)

If divergences exist, re-spawn the 4 non-Arbiter council agents (NOT the Arbiter):
- Each receives: all Round 1 outputs + divergence summary
- Each MUST steel-man the opposing position before responding
- Hard cap: 2 rounds per disagreement

Output:
```
  Round 2 complete — structured debate on [M] points
```

### Round 3: Final Synthesis

Spawn ONLY the Arbiter:
- `subagent_type`: "council-arbiter", `model`: "opus"
- Receives: ALL outputs from Rounds 1, 1.5, and 2
- Produces: BLUF, consensus findings, residual disagreements (with minority reports), critical uncertainties, assumptions

Output:
```
  Council deliberation complete
  BLUF: [1-2 sentence recommendation]
  Confidence: [level]
```

Write checkpoint: `.research-session/checkpoint-phase5.json`

---

## Phase 6: OUTPUT

Output: `--- Phase 6: OUTPUT ---`
Output: `Compiling final report...`

**Step 1: Determine output path**

If `--output` specified, use that. Otherwise:
- Create `docs/research/` if needed
- Filename: `YYYY-MM-DD-<slug>.md` (first 5 words of query, lowercased, hyphenated)

**Step 2: Open dashboard**

Call `get_dashboard_url`. If available, open it: `Bash: start [URL]` (Windows).

**Step 3: Get final context**

Call `get_research_context` with section="all".

**Step 4: Compile and write report**

Use the dialectical report template. Include all sections:

```markdown
# [Topic] — Deep Research Report

**Date:** [today] | **Depth:** [depth] | **Domain:** [domain]
**Query:** [original query]
**Classification:** [PUBLIC or SENSITIVE (user-overridden)]

---

## Executive Summary
[3-5 sentences: the non-obvious takeaway]
**Overall Confidence:** [level] — [justification per ICD 203]

## Key Findings

### What the Evidence Says (Thesis)
[From synthesizer]

### What Challenges This (Antithesis)
[From synthesizer + contrarian findings]

### The Deeper Insight (Synthesis)
[From synthesizer]

## How Thinking Has Evolved
[Timeline: foundational origins → key shifts → current state]

## Cross-Domain Connections
[From lateral searcher findings]

## Counter-Evidence & Risks
[From contrarian searcher + council skeptic]

## Source Chain
[Primary sources traced through citations, ranked by importance]

## Decision Implications
[Concrete actions based on synthesis]

---

## Council Debate
[ONLY if depth = deep or exhaustive — otherwise omit this entire section]

### BLUF (Bottom Line Up Front)
[From arbiter]
**Confidence:** [level] — [justification]

### Consensus Findings
[Bulleted list]

### Key Debate Points
[For each disagreement: issue, majority position, minority position, resolution]

### Actionable Recommendations
[Numbered list with confidence and evidence]

### Critical Uncertainties
[Things research could not determine]

### Assumptions
[Explicit assumptions]

### Debate Transcript
<details>
<summary>Full council debate transcript</summary>

[Round 1 assessments]
[Divergence analysis]
[Round 2 debate]
[Round 3 synthesis]

</details>

---

## Research Notes & Next Steps

### Process Notes
[What was hard to find, surprising gaps, API performance]

### Recommended Next Steps
[Follow-up questions, deeper dives, experts to consult]

## Sources
[All sources from registry, grouped by quality tier]

### Authoritative (≥0.8)
[Sources]

### Expert (0.6-0.79)
[Sources]

### Professional (0.4-0.59)
[Sources]

### Other (<0.4)
[Sources]

## Research Metadata
- Query: [query]
- Depth: [depth]
- Domain: [domain]
- Duration: [elapsed time]
- Sub-questions: [count]
- Agents dispatched: [count by type]
- Search queries executed: [count]
- Sources registered: [count]
- Unique domains: [count]
- API usage: [per-API counts]
- Refinement iterations: [count] (stop reason: [reason])
- Council: [yes/no]
- Gaps remaining: [count]
```

Write the report using the Write tool.

**Step 5: Final output**

Output:
```
Report written to [output_path]
[source_count] sources cited | [search_count] searches | Confidence: [level] | [elapsed time]
```

**Step 6: Cleanup**

Delete `.research-session/` directory. Mark all tasks complete.
