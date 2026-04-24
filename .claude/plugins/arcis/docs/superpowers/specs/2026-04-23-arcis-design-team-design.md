# ARCIS Design-Team Skill Specification

**Skill:** `design-team`
**Command:** `/arcis:design`
**Purpose:** Transform ideas or existing artifacts into codebase-grounded design specs and implementation plans through multi-agent analysis, structured interviewing, and adversarial review.

---

## 1. Overview

### 1.1 Problem Statement

Going from idea to implementation requires three things that are hard to do in a single context window:

1. **Deep codebase understanding** — knowing what exists, what patterns are used, where integration points are
2. **Structured requirement elicitation** — asking the right questions informed by what the code actually looks like
3. **Design validation** — catching infeasible assumptions and missing edge cases before code is written

The design-team skill decomposes this into specialized agents that each do one thing well, orchestrated by a Director that handles user interaction and workflow management.

### 1.2 Input Modes

| Mode | Trigger | Behavior |
|------|---------|----------|
| **Blank idea** | User provides a natural language description | Full interview: Director explores intent, constraints, success criteria |
| **Existing artifact** | User provides a file path, URL, or pastes structured requirements | Clarification interview: Director asks targeted questions about gaps and ambiguities |
| **Iteration** | User provides a previous spec + change requests | Delta interview: Director focuses on what's changing and why |

Detection is automatic based on input parsing at INTAKE.

### 1.3 Output

Two files, committed to the project:

1. **Design spec** at `docs/superpowers/specs/YYYY-MM-DD-<topic>-design.md`
2. **Implementation plan** at `docs/superpowers/plans/YYYY-MM-DD-<topic>.md`

The implementation plan produces a `task_graph` compatible with `/arcis:code`'s Planner output schema, enabling direct handoff:

```
/arcis:code --spec <spec-path> --plan <plan-path>
```

### 1.4 Pipeline

```
INTAKE → SCOUT → INTERVIEW → ANALYZE → CHECKPOINT → DESIGN → REVIEW → OUTPUT
```

8 phases, linear with conditional branching at REVIEW (fail-fast loop).

### 1.5 Agent Roster

| Agent | Model | maxTurns | Tools | Dispatched In |
|-------|-------|----------|-------|---------------|
| Codebase Analyst | opus | 10 | Read, Glob, Grep, LS, Bash | SCOUT + ANALYZE |
| Architect | opus | 10 | Read, Glob, Grep | DESIGN + REVIEW (revision) |
| Feasibility Reviewer | opus | 4 | Read, Glob, Grep | REVIEW |
| Devil's Advocate | opus | 4 | (none) | REVIEW |

All agents use opus. Design work is pure reasoning — no place for cost-optimized models.

The **Director** (the command itself) handles orchestration, user interviewing, checkpoint management, and output writing. It is not a separate agent file.

### 1.6 CLI Arguments

| Flag | Type | Default | Purpose |
|------|------|---------|---------|
| `<positional>` | string | (required) | Feature idea, artifact path, or URL |
| `--codebase <path>` | path | cwd | Target codebase root directory |
| `--spec-only` | flag | false | Produce design spec without implementation plan |
| `--skip-review` | flag | false | Skip REVIEW phase (trust the Architect) |
| `--out <path>` | path | `docs/superpowers/` | Custom output directory for spec + plan files |
| `--help` | flag | — | Show usage and argument descriptions |

---

## 2. Pipeline Phases

### 2.1 Phase 1: INTAKE

**Actor:** Director

**Steps:**

1. Parse CLI arguments.
2. Detect input mode:
   - If positional argument is a file path that exists → **artifact mode**. Read the file.
   - If positional argument is a URL → **artifact mode**. Fetch the content.
   - If positional argument looks like a previous spec path → **iteration mode**. Read the spec.
   - Otherwise → **blank idea mode**. Treat as natural language description.
3. Detect target codebase:
   - If `--codebase` provided, use that path.
   - Otherwise, use current working directory.
   - If target directory has no source files (no `.py`, `.js`, `.ts`, `.go`, `.rs`, `.java`, etc.) → **greenfield mode**.
4. Normalize input into a **brief**:
   ```
   MODE: blank_idea | artifact | iteration
   GREENFIELD: true | false
   CODEBASE_ROOT: <path>
   IDEA: <normalized description or artifact content>
   PREVIOUS_SPEC: <path, if iteration mode>
   ```
5. If greenfield mode, skip to Phase 3 (INTERVIEW). Set `surface_report = null`.

### 2.2 Phase 2: SCOUT

**Actor:** Codebase Analyst (first dispatch)

**Purpose:** Quick architecture-level scan to give the Director enough context to ask smart interview questions.

**DYNAMIC CONTEXT injected by Director:**

```
## DYNAMIC CONTEXT

**CODEBASE_ROOT:** <path>
**BRIEF:** <normalized idea>
**ANALYSIS_MODE:** surface
**FOCUS_HINT:** <Director's best guess at relevant areas based on the brief>
```

**Analyst workflow (surface mode):**

1. Scan file tree structure (Glob for common patterns: `src/`, `app/`, `lib/`, `tests/`, config files).
2. Identify tech stack (read package.json, requirements.txt, Cargo.toml, go.mod, etc.).
3. Map major modules and their apparent responsibilities.
4. Identify architectural patterns (MVC, layered, microservices, monolith).
5. Note entry points (main files, route definitions, CLI entry points).
6. Identify conventions (naming, file organization, test patterns).

**Output:** `<codebase_report>` JSON

```json
{
  "analysis_mode": "surface",
  "tech_stack": {
    "language": "Python 3.14",
    "framework": "FastAPI",
    "orm": "SQLAlchemy 2.0 async",
    "frontend": "Jinja2 + HTMX + Alpine.js + Tailwind",
    "testing": "pytest",
    "other": ["Alembic", "openpyxl", "Plotly.js"]
  },
  "modules": [
    {
      "name": "models",
      "path": "app/models/",
      "responsibility": "SQLAlchemy data models",
      "key_files": ["project.py", "cost_element.py", "forecast.py"],
      "relevance_to_brief": "high"
    }
  ],
  "architecture_pattern": "Layered monolith (routes → services → models)",
  "conventions": {
    "naming": "snake_case everywhere",
    "file_org": "Feature-grouped under app/",
    "test_pattern": "tests/ mirrors app/ structure, pytest fixtures in conftest.py"
  },
  "entry_points": ["app/main.py (FastAPI app factory)"],
  "integration_points": [
    "Database via async SQLAlchemy sessions",
    "File uploads via openpyxl parsers"
  ],
  "coverage_assessment": "Scanned 45 files across 8 directories. Surface-level coverage is comprehensive."
}
```

**Turn budget:** 2-4 turns (this is a quick scan, not a deep dive).

### 2.3 Phase 3: INTERVIEW / CLARIFY

**Actor:** Director (directly, not a subagent)

**Purpose:** Elicit structured requirements from the user, informed by the codebase surface report.

**Behavior varies by input mode:**

| Mode | Interview Style |
|------|----------------|
| Blank idea | Full discovery: purpose, constraints, success criteria, user-facing behavior, data model implications, testing expectations |
| Artifact | Targeted clarification: gaps in the artifact, ambiguities, unstated assumptions, priority ordering |
| Iteration | Delta-focused: what's changing, why, impact on existing spec sections |

**Interview protocol:**

1. Ask one question at a time via `AskUserQuestion` (multiple choice preferred).
2. Use surface_report to make questions codebase-aware:
   - "I see you're using SQLAlchemy 2.0 async — should the new feature follow that pattern or is there a reason to use sync?"
   - "The existing tests use pytest fixtures in conftest.py — should we follow that pattern?"
3. After each answer, decide: ask another question or move on.
4. Stop when: (a) requirements are clear enough to design against, or (b) maximum 6 questions asked (avoid interview fatigue).
5. Check for contradictions in the accumulated requirements. If found, present them to the user and force resolution before proceeding.

**Output:** Structured `requirements` document (internal to Director, passed to subsequent phases):

```
## Requirements

**Goal:** <one sentence>
**Success criteria:** <bulleted list>
**Constraints:**
- Must: <hard requirements>
- Should: <preferences>
- Must not: <anti-requirements>
**Data model changes:** <if any>
**API/UI changes:** <if any>
**Testing expectations:** <what should be tested>
**Out of scope:** <explicitly excluded>
```

### 2.4 Phase 4: ANALYZE

**Actor:** Codebase Analyst (second dispatch)

**Purpose:** Targeted deep analysis of the specific areas the requirements touch. The Analyst now knows exactly what to focus on.

**Skipped if:** Greenfield mode (no codebase to analyze).

**DYNAMIC CONTEXT injected by Director:**

```
## DYNAMIC CONTEXT

**CODEBASE_ROOT:** <path>
**BRIEF:** <normalized idea>
**REQUIREMENTS:** <structured requirements from INTERVIEW>
**SURFACE_REPORT:** <full surface report from SCOUT>
**ANALYSIS_MODE:** deep
**FOCUS_AREAS:** <Director's list of specific areas to investigate, derived from requirements>
```

**Analyst workflow (deep mode):**

1. Read the surface report to avoid re-scanning already-covered ground.
2. For each focus area identified by the Director:
   a. Read the relevant source files.
   b. Trace data flow through the area (model → service → route → template).
   c. Identify integration points that the new feature must connect to.
   d. Note existing patterns that the new feature should follow.
   e. Flag potential conflicts (e.g., "this table already has a `status` column with different semantics").
3. Assess depth of analysis per area:
   - **Shallow:** File exists, purpose clear, no complex interactions. Report structure only.
   - **Moderate:** Read key functions, understand interfaces. Report signatures and contracts.
   - **Deep:** Trace full execution path, understand state management, map dependencies. Report complete analysis.
4. Self-assess coverage: what was analyzed thoroughly vs. what was only surface-scanned.

**Output:** `<codebase_report>` JSON (extended schema for deep mode)

```json
{
  "analysis_mode": "deep",
  "focus_areas": [
    {
      "area": "Cost element data model",
      "depth": "deep",
      "files_read": ["app/models/cost_element.py", "app/services/cost_service.py"],
      "patterns_found": [
        "All models use DeclarativeBase with async session",
        "Services use repository pattern with dependency injection"
      ],
      "integration_points": [
        {
          "description": "CostElement.project_id FK to Project.id",
          "file": "app/models/cost_element.py",
          "line": 23,
          "implication": "New feature must maintain this FK relationship"
        }
      ],
      "potential_conflicts": [],
      "relevant_code_snippets": [
        {
          "file": "app/services/cost_service.py",
          "lines": "45-67",
          "description": "Existing forecast calculation — new feature should extend, not replace"
        }
      ]
    }
  ],
  "cross_cutting_concerns": [
    "All routes require authentication middleware",
    "Database migrations managed by Alembic — new models need migration scripts"
  ],
  "coverage_gaps": [
    "Did not analyze frontend templates in detail — surface-level only"
  ]
}
```

**Turn budget:** 4-8 turns depending on codebase complexity and number of focus areas.

### 2.5 Phase 5: CHECKPOINT

**Actor:** Director

**Purpose:** Present the accumulated context to the user for approval before investing in design generation.

**Director presents:**

1. **Requirements summary** (from INTERVIEW)
2. **Codebase analysis summary** (key findings from SCOUT + ANALYZE, not the raw reports)
3. **Complexity assessment:** Is this a small feature (≤2 files), medium (3-8 files), or large (9+ files)?
4. **Estimated plan size:** Approximate number of implementation tasks.

**User options:**
- **Approve** → proceed to DESIGN
- **Modify** → Director adjusts requirements or analysis focus, may re-dispatch Analyst
- **Abort** → stop, no output

**Complexity flag:** Director records `complexity_level` (trivial/standard/complex) for use in REVIEW phase gating.

### 2.6 Phase 6: DESIGN

**Actor:** Architect

**Purpose:** Produce a design spec and implementation plan grounded in the real codebase analysis.

**DYNAMIC CONTEXT injected by Director:**

```
## DYNAMIC CONTEXT

**BRIEF:** <normalized idea>
**REQUIREMENTS:** <structured requirements from INTERVIEW>
**CODEBASE_REPORT:** <FULL raw deep report — not summarized>
**SURFACE_REPORT:** <FULL raw surface report>
**COMPLEXITY_LEVEL:** trivial | standard | complex
**SPEC_ONLY:** true | false
**GREENFIELD:** true | false
```

**Architect workflow:**

1. **Read inputs** (turns 1-2): Absorb the codebase reports and requirements. Identify the key design decisions.

2. **Design the solution** (turns 3-6):
   a. Define the architecture: what components, how they interact, where they fit in the existing codebase.
   b. Specify data model changes (new tables, modified columns, migrations).
   c. Specify API/route changes (new endpoints, modified handlers).
   d. Specify frontend changes (new templates, modified components).
   e. Define error handling strategy.
   f. Define testing strategy.

3. **Produce the design spec** (turns 5-7): Write a complete design document in markdown format following the project's established spec format. The spec must be self-contained — a reader should understand the full design without needing to read the codebase reports.

4. **Produce the implementation plan** (turns 7-10, skip if `--spec-only`): Decompose the design into a task graph compatible with `/arcis:code`'s Planner output:

```json
{
  "tasks": [
    {
      "id": "T1",
      "description": "Add ForecastRun model and Alembic migration",
      "files_in_scope": ["app/models/forecast.py", "alembic/versions/"],
      "files_read_only": ["app/models/project.py"],
      "scope_fence": "Do NOT modify existing model classes. Only add new model and migration.",
      "test_strategy": "Unit test model creation, relationship traversal, and migration up/down",
      "depends_on": []
    }
  ],
  "execution_order": [["T1", "T2"], ["T3"], ["T4", "T5"]],
  "notes": "Tasks T1 and T2 are independent and can run in parallel..."
}
```

Each task: max 4 files in scope, explicit scope fence, explicit test strategy, dependency list.

**Output:** `<design>` block containing:
```json
{
  "spec": "<full markdown design spec>",
  "plan": {
    "tasks": [...],
    "execution_order": [...],
    "notes": "..."
  },
  "design_decisions": [
    {
      "decision": "Use async SQLAlchemy sessions for new queries",
      "rationale": "Matches existing codebase pattern, avoids mixing sync/async",
      "alternatives_considered": ["Sync sessions", "Raw SQL"]
    }
  ]
}
```

### 2.7 Phase 7: REVIEW

**Actor:** Director orchestrates Feasibility Reviewer → Devil's Advocate (sequential, fail-fast)

**Purpose:** Validate the design against the real codebase and stress-test for holes.

**Step 1: Feasibility Review**

Dispatched first. Has tools to read the codebase.

**DYNAMIC CONTEXT for Feasibility Reviewer:**

```
## DYNAMIC CONTEXT

**CODEBASE_ROOT:** <path>
**DESIGN_SPEC:** <Architect's full spec>
**IMPLEMENTATION_PLAN:** <Architect's full plan>
**CODEBASE_REPORT:** <deep report for reference>
```

**Feasibility Reviewer workflow:**

1. For each file referenced in the plan's `files_in_scope`:
   a. Verify the file exists (or will be created).
   b. Verify the interfaces the design assumes actually exist.
   c. Check for conflicts with existing code.
2. Verify data model assumptions (table names, column types, relationships).
3. Check dependency assumptions (libraries available, versions compatible).
4. Verify the plan's task dependencies make sense (no circular deps, no missing prereqs).
5. Check that scope fences are realistic (changes can actually be contained to the listed files).

**Output:** `<review>` JSON

```json
{
  "verdict": "PASS | REJECT | REQUEST_CHANGES",
  "findings": [
    {
      "severity": "critical | major | minor",
      "category": "missing_file | wrong_interface | conflict | dependency | scope",
      "description": "The design assumes UserService.get_by_email() exists, but the actual method is UserService.find_by_email()",
      "location": "spec section 3.2",
      "codebase_evidence": "app/services/user_service.py:45",
      "suggested_fix": "Update spec to use find_by_email() or rename the existing method"
    }
  ],
  "summary": "Design is feasible with 2 minor corrections."
}
```

**Verdict rules:**
- REJECT if any critical finding (design assumes something fundamentally wrong)
- REQUEST_CHANGES if major findings only
- PASS if minor findings only or no findings

**If REJECT:** Director re-dispatches Architect with the Feasibility Reviewer's findings. Max 2 revision cycles. After 2 rejections, escalate to user.

**If REQUEST_CHANGES:** Director passes findings to Architect for a single revision pass, then proceeds to Devil's Advocate.

**If PASS:** Proceed directly to Devil's Advocate.

**Step 2: Devil's Advocate**

Dispatched only after Feasibility PASS or REQUEST_CHANGES (resolved).

**Has NO tools.** Reasons purely from the design document. This tests whether the spec is self-contained and complete.

**Skipped if:** `complexity_level == trivial` (≤2 files, no new data models, no new APIs).

**DYNAMIC CONTEXT for Devil's Advocate:**

```
## DYNAMIC CONTEXT

**DESIGN_SPEC:** <Architect's spec (revised if applicable)>
**IMPLEMENTATION_PLAN:** <Architect's plan>
**REQUIREMENTS:** <structured requirements for comparison>
```

**Devil's Advocate workflow:**

1. **Ambiguity scan:** Can any requirement be interpreted two different ways? Flag each with both interpretations.
2. **Edge case analysis:** What inputs, states, or sequences will break this design? Focus on boundaries, error paths, concurrent access, and data corruption scenarios.
3. **Missing requirements:** What did the user probably assume but didn't state? What will they ask about in the first code review?
4. **Scope creep risk:** Which parts of the design are likely to expand beyond the scope fence during implementation?
5. **Testing gaps:** Are there behaviors specified but not testable with the stated test strategy?

**Output:** `<review>` JSON

```json
{
  "verdict": "APPROVED | CONCERNS",
  "issues": [
    {
      "severity": "critical | major | minor | nit",
      "category": "ambiguity | edge_case | missing_requirement | scope_risk | test_gap",
      "description": "The spec says 'handle errors gracefully' but doesn't define what graceful means for each error type",
      "impact": "Developers will each handle errors differently, creating inconsistent UX",
      "recommendation": "Add an error handling table: error type → user message → HTTP status → log level"
    }
  ],
  "strengths": [
    "Data model is well-normalized and follows existing patterns",
    "Task decomposition has clean boundaries with no shared mutable state"
  ],
  "overall_assessment": "Solid design with 2 major gaps that should be addressed before implementation."
}
```

**After Devil's Advocate:** Director passes issues to Architect for a single revision pass. Only critical and major issues require changes — minor and nit are included in the spec as "known considerations" but don't block.

### 2.8 Phase 8: OUTPUT

**Actor:** Director

**Steps:**

1. Write the final design spec to `docs/superpowers/specs/YYYY-MM-DD-<topic>-design.md` (or `--out` path).
2. Write the implementation plan to `docs/superpowers/plans/YYYY-MM-DD-<topic>.md` (or `--out` path). Skip if `--spec-only`.
3. Commit both files with message: `docs: add <topic> design spec and implementation plan`
4. Present completion summary to user:
   ```
   Design complete.

   Spec: docs/superpowers/specs/2026-04-23-feature-x-design.md
   Plan: docs/superpowers/plans/2026-04-23-feature-x.md

   To implement:
   /arcis:code --spec <spec-path> --plan <plan-path>

   Review summary:
   - Feasibility: PASS (0 critical, 1 minor)
   - Devil's Advocate: 2 major issues addressed, 1 minor noted in spec
   - Design decisions: 4 recorded
   - Implementation tasks: 7 across 3 parallel batches
   ```

---

## 3. Agent Specifications

### 3.1 design-codebase-analyst

**File:** `skills/design-team/agents/design-codebase-analyst.md`

```yaml
name: design-codebase-analyst
description: Adaptive-depth codebase explorer — surface scans for architecture, deep dives for integration points and patterns
model: opus
maxTurns: 10
allowed-tools:
  - Read
  - Glob
  - Grep
  - LS
  - Bash
```

**Epistemic lens:** You are a codebase archaeologist. You read code to understand intent, not just structure. You distinguish between "how it works" and "why it works this way." When you find a pattern, you assess whether it's intentional convention or accidental legacy.

**Key constraints:**
- MUST self-assess coverage for each area (shallow/moderate/deep)
- MUST flag coverage gaps explicitly — what you didn't analyze and why
- MUST distinguish conventions (follow them) from legacy patterns (note but don't enforce)
- In surface mode: max 4 turns. Do not read individual source files. Focus on structure and metadata.
- In deep mode: 4-8 turns. Read source files in focus areas. Trace data flows. Map integration points.
- When dispatched for deep mode, MUST read the surface report first to avoid redundant work

**Anti-sycophancy directive:** Report what you find, including problems. If the codebase has concerning patterns (no tests, inconsistent conventions, security issues), report them. The Architect needs accurate data, not a flattering portrait.

### 3.2 design-architect

**File:** `skills/design-team/agents/design-architect.md`

```yaml
name: design-architect
description: Produces grounded design specs and implementation plans from codebase analysis and structured requirements
model: opus
maxTurns: 10
allowed-tools:
  - Read
  - Glob
  - Grep
```

**Epistemic lens:** You are a software architect who designs with the codebase, not against it. Your designs extend existing patterns rather than introducing new ones. You think in terms of minimal necessary change — what's the smallest set of additions and modifications that satisfies the requirements?

**Key constraints:**
- MUST follow existing codebase conventions identified in the codebase report
- MUST produce a self-contained spec — a reader should understand the full design without reading the codebase
- MUST produce task_graph in the exact schema that `/arcis:code`'s Planner uses (tasks[], execution_order[], notes)
- Each task: max 4 files_in_scope, explicit scope_fence, explicit test_strategy
- MUST record design decisions with rationale and alternatives considered
- If `SPEC_ONLY` is true, skip the implementation plan
- If `GREENFIELD` is true, focus on technology selection, project structure, and architecture rather than integration

**Anti-sycophancy directive:** Design for what the requirements actually say, not what sounds impressive. If the requirements call for a simple CRUD endpoint, design a simple CRUD endpoint. Don't add caching, event sourcing, or microservice extraction unless the requirements demand it.

### 3.3 design-feasibility-reviewer

**File:** `skills/design-team/agents/design-feasibility-reviewer.md`

```yaml
name: design-feasibility-reviewer
description: Validates design specs against the real codebase — checks that assumed interfaces, files, and patterns actually exist
model: opus
maxTurns: 4
allowed-tools:
  - Read
  - Glob
  - Grep
```

**Epistemic lens:** You are a build engineer who has to make this design work in the real codebase. You don't care if the design is elegant — you care if it's buildable. Every file reference, every function call, every data model assumption must be verified against what actually exists.

**Key constraints:**
- MUST verify every file referenced in files_in_scope actually exists (or is marked as "create new")
- MUST verify every interface/function the design assumes is available and has the expected signature
- MUST check for naming conflicts (new tables, new routes, new classes that collide with existing ones)
- Verdict is based on findings severity, not opinion
- REJECT only for critical findings (fundamental impossibility)
- REQUEST_CHANGES for major findings (wrong but fixable)
- PASS for minor or no findings

### 3.4 design-devils-advocate

**File:** `skills/design-team/agents/design-devils-advocate.md`

```yaml
name: design-devils-advocate
description: Adversarial stress-test of design specs — finds ambiguities, missing edge cases, unstated assumptions, and scope risks
model: opus
maxTurns: 4
allowed-tools: []
```

**Epistemic lens:** You are the person who will maintain this code in six months and is reading the spec for the first time. Every ambiguity you find now is a bug that won't be found until production. Every missing edge case is a support ticket. Every unstated assumption is a miscommunication between the spec author and the implementer.

**Key constraints:**
- NO tools. You reason from the design document alone. If you can't understand the design without checking the code, the design is incomplete — that's a finding.
- MUST find at least 2 issues (if you find 0, you aren't looking hard enough)
- Each issue MUST have a concrete recommendation, not just a complaint
- Focus on what will go wrong during implementation or in production, not on theoretical purity
- Severity calibration: critical = will cause data loss or security vulnerability. major = will cause user-visible bugs or block implementation. minor = will cause developer confusion. nit = style preference.

---

## 4. Conditional Logic

### 4.1 Greenfield Detection

At INTAKE, if the target codebase has no recognizable source files:

- Skip SCOUT (Phase 2)
- Skip ANALYZE (Phase 4)
- INTERVIEW focuses on technology choices, architecture patterns, project structure
- Architect works from requirements only, no codebase context
- Feasibility Reviewer is skipped (nothing to check against)
- Devil's Advocate still runs (design quality matters regardless of codebase)

### 4.2 Complexity Gating

At CHECKPOINT, Director assesses complexity:

| Level | Criteria | REVIEW behavior |
|-------|----------|-----------------|
| Trivial | ≤2 files modified, no new data models, no new APIs | Feasibility only, skip Devil's Advocate |
| Standard | 3-8 files, some new components | Full review (Feasibility → Devil's Advocate) |
| Complex | 9+ files, new subsystems, architectural changes | Full review with stricter thresholds |

### 4.3 Revision Loops

| Phase | Max Cycles | Escalation |
|-------|------------|------------|
| Feasibility REJECT → Architect | 2 | Present issues to user, ask how to proceed |
| Feasibility REQUEST_CHANGES → Architect | 1 | Proceed to Devil's Advocate |
| Devil's Advocate CONCERNS → Architect | 1 | Incorporate fixes, proceed to OUTPUT |

---

## 5. Context Flow Diagram

```
INTAKE
  │ brief
  ▼
SCOUT ──────────────────────────────────────┐
  │ surface_report                          │
  ▼                                         │
INTERVIEW (Director uses surface_report)    │
  │ requirements                            │
  ▼                                         │
ANALYZE (Analyst gets brief +               │
         surface_report + requirements)     │
  │ deep_report                             │
  ▼                                         │
CHECKPOINT (user sees summary of all)       │
  │ complexity_level                        │
  ▼                                         │
DESIGN (Architect gets brief +              │
        deep_report [raw] +                 │
        surface_report [raw] +              │
        requirements)                       │
  │ spec + plan                             │
  ▼                                         │
REVIEW/Feasibility (gets spec + plan +      │
                    deep_report)            │
  │ PASS ──────────────────┐                │
  │ REJECT ──► Architect   │                │
  │ (max 2x)    revises    │                │
  ▼                        │                │
REVIEW/Devil's Advocate    │                │
  (gets spec + plan ONLY)  │                │
  │ issues ──► Architect   │                │
  │            revises     │                │
  ▼                        │                │
OUTPUT (write files, commit)                │
```

**Key principle:** The Architect always receives RAW reports, not Director-curated summaries. Summarization is lossy — let the Opus model process full-fidelity data.

---

## 6. File Structure

```
skills/design-team/
├── SKILL.md                              # Skill metadata and methodology overview
├── commands/
│   └── design.md                         # Director orchestrator (8-phase pipeline)
└── agents/
    ├── design-codebase-analyst.md         # Surface + deep codebase analysis
    ├── design-architect.md                # Spec + plan generation
    ├── design-feasibility-reviewer.md     # Buildability check against real code
    └── design-devils-advocate.md          # Pure reasoning stress-test
```

Total: 6 files (SKILL.md + command + 4 agents).

---

## 7. Handoff to /arcis:code

The implementation plan's task_graph uses the exact schema defined in `skills/coding-team/agents/coding-planner.md`. This means `/arcis:code` can either:

1. **Use the plan directly:** `--plan <plan-path>` flag tells the PM to skip its Planner phase and use the pre-built plan.
2. **Re-plan:** If the user wants, the PM can run its own Planner for a fresh decomposition informed by the spec.

**Cross-skill dependency:** The `--plan` flag must be added to the coding-team's `code.md` to support this handoff. This is a single-line addition to `code.md`'s argument table and a conditional skip in Phase 2 (PLAN). This change is out of scope for the design-team implementation and should be tracked separately.

---

## 8. Design Decisions Log

| Decision | Rationale | Alternatives Considered |
|----------|-----------|------------------------|
| Director handles interviewing | Subagents cannot call AskUserQuestion — platform constraint | Separate Interviewer agent (impossible) |
| All opus, no sonnet | Design work is pure reasoning; cost savings not worth quality risk | Sonnet for Analyst (rejected: needs high reasoning for pattern recognition) |
| Sequential fail-fast review | Avoids wasted Devil's Advocate work on infeasible designs | Parallel review (rejected: conflicting feedback problem) |
| Devil's Advocate has no tools | Tests spec self-containment; if reviewer needs code to understand the design, the design is incomplete | Give DA Read access (rejected: undermines self-containment test) |
| Analyst dispatched twice (surface + deep) | Surface informs interview questions; deep is targeted by requirements | Single deep pass (rejected: Analyst works blind without requirements) |
| Raw reports to Architect, not summaries | Summarization is lossy; Opus can handle full context | Director-curated summaries (rejected: loses critical details) |
| Greenfield skips analysis | No codebase to analyze; interview focuses on tech choices instead | Analyze anyway for "best practices" (rejected: YAGNI) |
| task_graph matches coding-team schema | Enables direct handoff to /arcis:code without format conversion | Custom plan format (rejected: creates unnecessary translation layer) |
