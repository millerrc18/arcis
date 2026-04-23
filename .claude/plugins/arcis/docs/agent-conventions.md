# ARCIS Agent Authoring Conventions

Development guide for writing agent prompts in the ARCIS plugin. This is a convention document for agent authors, NOT a runtime contract.

---

## 5-Section Prompt Structure

Every ARCIS agent prompt is organized into exactly five sections, in this order. Section headers are `##` level markdown headings. The sections serve distinct purposes and should not be merged or reordered.

---

### 1. EPISTEMIC LENS

**Purpose:** Establishes who the agent is, what it is optimizing for, and (where applicable) an explicit anti-sycophancy directive.

This section defines the agent's identity and cognitive frame — not as a constraint list, but as a role description that shapes how the agent approaches ambiguity. A Domain Lead's epistemic lens tells it to think like a domain expert who evaluates evidence critically, not like a research assistant who summarizes whatever it finds. The optimization objective makes explicit what "good output" means for this agent role.

Anti-sycophancy directives are included for agents that receive parent findings as input (Domain Leads, Specialists). These agents must be instructed to evaluate parent context critically — accepting useful framing while remaining willing to produce findings that contradict or complicate what the parent found.

---

### 2. TASK

**Purpose:** Describes what inputs the agent receives, the sequence of workflow steps it must execute, and the decision criteria it uses at each branch point.

Use this structure inside the TASK section:

**Inputs you will receive:**
List the specific inputs injected via DYNAMIC CONTEXT — mandate, domain specialization, budget, depth level, parent findings (if any), etc.

**Your workflow:**
Numbered steps describing the agent's execution sequence. For agents that conditionally delegate (Domain Leads, Specialists below max depth), this section must include the complexity assessment step and the branching logic (handle directly vs. delegate). Decision thresholds come from DYNAMIC CONTEXT, not hardcoded here.

**Outputs you must produce:**
Explicit list of what the agent is required to produce. References OUTPUT FORMAT for structure.

---

### 3. CONSTRAINTS

**Purpose:** Hard rules expressed as MUST or MUST NOT. These are non-negotiable requirements that bound agent behavior regardless of what the research produces.

This section covers:

- **Source quality minimums.** Minimum `source_quality` score (per `shared/references/source-quality-rubric.md`) for evidence included in key findings. Example: "MUST NOT include evidence with source_quality below 0.5 in key_findings."
- **maxTurns budget.** The agent must complete its work within the tool-use turn budget specified in its frontmatter. Example: "MUST complete trial search and complexity assessment within the first 3 turns."
- **Confidence caps.** Sonnet Specialist agents MUST NOT assign confidence above Moderate. Domain Leads MUST NOT elevate a Specialist claim to High without adding new evidence to the `evidence[]` array.
- **Output token limits.** Where applicable, limits on reasoning block length or findings JSON size. Example: "Reasoning MUST NOT exceed 500 tokens — record key decision points only."
- **Tool restrictions.** If the agent has a restricted allowed-tools list (frontmatter), note any behavioral implications here. Example: "MUST NOT attempt web browsing — use only mcp__deep-research tools."
- **Recursion rules.** Specialists MUST NOT spawn sub-Specialists if `depth_level >= max_depth`. Domain Leads MUST NOT dispatch more Specialists than `budget` allows.

---

### 4. DYNAMIC CONTEXT

**Purpose:** Placeholder section that the orchestrator replaces at dispatch time with agent-specific configuration and runtime values.

In the agent source file, this section contains only a comment and a brief list of what gets injected:

```markdown
## DYNAMIC CONTEXT

<!-- Injected by orchestrator at dispatch time -->
```

What the orchestrator injects here at runtime:

- **Domain specialization** — the domain label, expertise framing, source preferences, and evaluation lens (from domain presets or generated on-the-fly for dynamic specialists)
- **Mandate** — the specific research question or sub-topic this agent is responsible for
- **Parent findings** — summarized findings from the parent agent, used for context and continuity (not treated as ground truth)
- **Budget** — maximum number of sub-agents this agent may dispatch
- **Depth level** — the agent's position in the tree (1 for Domain Leads dispatched by Director, 2 for their Specialists, etc.)
- **Max depth** — the tree depth cap for this run
- **Complexity threshold** — the score above which the agent should decompose (adjusted for depth level and rigor flag)

Do not put static content in the DYNAMIC CONTEXT section. It exists solely as an injection point.

---

### 5. OUTPUT FORMAT

**Purpose:** Specifies the exact output structure the agent must produce, which the orchestrator parses.

Every agent produces output in this form:

```
<reasoning>
Chain-of-thought notes on research decisions, source evaluation, complexity assessment rationale, and confidence calibration. Logged for auditability, not parsed by the orchestrator.
</reasoning>

<findings>
{ ... JSON conforming to findings-schema.md ... }
</findings>
```

Rules:

- `<reasoning>` comes first, `<findings>` second. Do not reverse the order.
- `<findings>` JSON must conform to `shared/schemas/findings-schema.md`. The orchestrator parses it via regex extraction of the `<findings>` block.
- The orchestrator does not parse `<reasoning>`. Keep it concise — record key decision points, source evaluation rationale, and confidence calibration notes. Do not narrate every tool call.
- JSON inside `<findings>` must be valid. Invalid JSON causes the orchestrator to treat the agent run as a failure and trigger the error recovery path.

---

## Agent Frontmatter

Every agent file begins with YAML frontmatter that configures how Claude Code invokes the agent. Use this template:

```yaml
---
name: agent-name          # kebab-case, prefixed by skill
description: One-line description of when to use this agent
model: opus               # opus or sonnet
maxTurns: 10              # tool-use turns budget
allowed-tools:            # list specific tools, or empty [] for no tool access
  - mcp__deep-research__search_web
  - mcp__deep-research__search_academic
  - mcp__deep-research__read_url
  - Write
---
```

Notes on frontmatter fields:

- `name` must be kebab-case and prefixed by skill (`research-`, `coding-`, `roast-`). See Naming Convention below.
- `model` is either `opus` or `sonnet`. Domain Leads and the Cross-Domain Analyst always use `opus`. Specialists default to `sonnet` but can be upgraded to `opus` via the `--model opus` run flag.
- `maxTurns` is the tool-use turn budget. Agents must plan their workflow to complete within this budget. The budget is enforced by Claude Code — the agent does not need to count turns itself, but the CONSTRAINTS section should specify how turns are allocated across the workflow phases.
- `allowed-tools` restricts which tools the agent can call. Specify only the tools the agent actually needs. The Research Classifier, for example, needs no tools — it receives the query as input and produces a classification decision without searching.

---

## Naming Convention

Agent filenames follow the pattern `<skill>-<role>.md`. This is enforced to prevent namespace collisions if the plugin system uses globally-scoped agent names.

| Skill | Pattern | Examples |
|---|---|---|
| research-team | `research-<role>.md` | `research-domain-lead.md`, `research-specialist.md`, `research-classifier.md`, `research-cross-domain-analyst.md` |
| coding-team | `coding-<role>.md` | `coding-pm.md`, `coding-developer.md`, `coding-qa.md` |
| roast-me | `roast-<role>.md` | `roast-critic.md`, `roast-devil-advocate.md` |

Use the skill prefix even when there is no immediate naming conflict. A future coding-team classifier would otherwise collide with `research-classifier.md` if both were named `classifier.md`.
