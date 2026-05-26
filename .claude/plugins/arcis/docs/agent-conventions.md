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

---

## Naming Addendum — Investigator-Class Bare-Name Exception (DD-1)

The 19 existing agents all carry a skill prefix (`coding-*`, `design-*`, `research-*`, `roast-*`) per the Naming Convention above. The 4 investigator-class agents introduced in #108 are an intentional, documented exception to this rule.

**Investigator-class agents use bare names (no skill prefix):**

| Agent file | `name` field | Reason |
|---|---|---|
| `db-investigator.md` | `db-investigator` | Cross-skill; consumed by #109, #110, #111, and operator directly |
| `ci-investigator.md` | `ci-investigator` | Cross-skill; consumed by #109, #111, and operator directly |
| `git-historian.md` | `git-historian` | Cross-skill; consumed by #110, #111, and operator directly |
| `live-monitor.md` | `live-monitor` | Cross-skill; consumed by #109, #111, and operator directly |

**The rule:**

- **Prefixed name** (`skill-role`) = skill-scoped agent. Owned by and invocable from a single skill. Use the prefix.
- **Bare name** (`role`) = investigator-class agent. Cross-skill ownership — intended for invocation by multiple future skills AND directly by the operator. Use a bare name ONLY when all of the following are true: (a) the agent is a general-purpose investigator with no single owning skill; (b) the agent's name is descriptive enough to be collision-resistant on its own (e.g., `db-investigator` is unambiguous); (c) the agent is explicitly documented as investigator-class in the conventions doc.

Future investigator-class agents that add new bare names MUST add a row to the table above. Do not add bare names for agents that are skill-scoped — use the prefix.

---

## maxTurns Addendum — Investigator-Class = 60 with Turn-50 Budget-Stop (DD-2, DD-17)

The `maxTurns` default in frontmatter (shown as `10` in the Agent Frontmatter template above) is appropriate for most single-pass agents. The investigator-class agents established in #108 set a different precedent:

**Investigator-class `maxTurns`: 60**

Rationale:
- Investigators have bounded but branching workflows: surface (4-6 tool calls) or deep (15-30 tool calls) modes, plus sibling-search and drill-down steps.
- `coding-rigor-reviewer.md` (line 5 of its frontmatter) already uses `maxTurns: 60` as the closest analogue (structured-investigation agent with multi-pass rubric execution).
- 60 leaves headroom for branching investigations (anomaly triggers second DBQuery + SymbolFind) while bounding runaway loops in `--json` parsing failures.

**Turn-50 budget-stop (DA6):**

Every investigator-class agent MUST honor a hard stop at turn 50, leaving 10 turns headroom for composing OUTPUT FORMAT JSON and the final `<reasoning>` block without truncation. The 50/60 split is the graceful-exit guarantee: an agent that hits `maxTurns: 60` mid-tool-call produces truncated OUTPUT FORMAT JSON that callers cannot parse.

At turn 50, the agent MUST:
1. Stop issuing new tool invocations.
2. Finalize findings from data already collected.
3. Populate `coverage_assessment` honestly (see §5 OUTPUT FORMAT Addendum for schema).

The turn-50 constraint MUST appear in both the agent's TASK Workflow and its CONSTRAINTS section. Task 6 lint grep-asserts for `turn 50` or `turn-50` in every investigator-class agent file.

---

## Bash-Subprocess Tool Invocation Appendix

All investigator-class agents (#108) invoke Tier 1+2 tools exclusively via Bash subprocess. This appendix documents the complete contract that every such invocation must follow.

### Canonical Invocation Pattern (DA1)

```bash
cd "$(git rev-parse --show-toplevel)" && python -m src.tools.<name> --json [args]
```

The `cd "$(git rev-parse --show-toplevel)"` prefix is mandatory. The operator regularly dispatches agents from `.claude/worktrees/<branch>/` sub-directories. Hardcoding `cd C:/arcis/halcyon-lab` breaks every worktree invocation with a silent `ModuleNotFoundError: No module named src` that is indistinguishable from a tool-missing failure.

**WORKTREE_PATH override:** An agent MAY receive `WORKTREE_PATH: <abs path>` in DYNAMIC CONTEXT. When present, prefer `cd "$WORKTREE_PATH"` over `git rev-parse` (the latter requires a `.git` directory absent from some sparse-checkout or detached worktree shapes). `WORKTREE_PATH` is optional; absence falls back to `git rev-parse`.

Task 6 lint grep-asserts NO occurrence of the literal string `cd C:/arcis/halcyon-lab` in any investigator-class agent file.

### Mandatory Explicit Per-Call Timeout (DA2)

Every Bash subprocess invocation MUST include an explicit `timeout` parameter (milliseconds). Implicit reliance on the Bash tool's 120-second default is FORBIDDEN.

**Tiered defaults:**

| Timeout | Tools |
|---|---|
| 60000 ms (60s) | `dbquery` SELECTs, `symbolfind`, `capabilityregistry`, `prcomments read/post`, `processmanager status`, `tradingstate`, `healthprobe`, git read-only ops (`log`/`blame`/`show`/`diff`) |
| 90000 ms (90s) | `logtail` against multi-MB logs |
| 120000 ms (120s) | `ciinvestigate` against an uncached `run_id` (network fetch + cache-warm) |

An agent MAY override the tier (e.g., a `dbquery` against a long-running JOIN may need 120s). The override MUST be inline in the agent's TASK Workflow step and justified in `<reasoning>`. Task 6 lint grep-asserts every Bash invocation in agent files carries an explicit `timeout` argument.

Rationale: a single subprocess hitting the implicit 120s ceiling consumes 1/60 of the per-agent turn budget; unbounded waits inside investigators cascade into operator session lockup.

### `--json` Mandatory

`--json` is mandatory for every Tier 1+2 tool invocation. Agents always parse the JSON envelope; markdown-mode output is human-only and not for agent consumption.

### JSON Envelope Parsing Contract

The shared envelope contract is implemented in `src/tools/_cli_envelope.py` via `cli_envelope()` (and the `run_cli()` wrapper consumed by every tool's `__main__.py`):

- **Success:** tool emits its primary payload (JSON array or object) to stdout, exits 0.
- **Failure:** tool emits the error envelope to stdout, exits 1:
  ```json
  {"error": {"type": "<ExceptionClassName>", "message": "<sanitize_error(e)>", "tool": "<tool_name>"}}
  ```
  The `message` is routed through `src.utils.secret_redact.sanitize_error` to redact credential patterns before surfacing.

### Exit-Code Handling Discipline

| Exit code | Action |
|---|---|
| 0 | Parse stdout as the tool's payload schema. |
| 1 | Parse stdout as the error envelope; extract `error.type` + `error.message`; surface in the agent's report. NEVER suppress or retry silently. |
| non-0 non-1 | Report `"<tool> subprocess crashed: <exit_code> + <stderr_excerpt>"` verbatim. |
| JSON parse failure | Report the raw stdout verbatim — do not discard it. |
| Bash `timeout` exceeded | Surface with the `timeout_exceeded` marker so callers distinguish from tool-internal errors. |

### Shell-Quoting Convention for Embedded SQL / Regex / Payload Strings

The Bash tool executes command strings. When embedding SQL, regex, or other payloads as positional arguments, use **single-quotes** to preserve literal `$`, `<`, `>`, `*`, `?`, `&`, `|`, parentheses, and backticks:

```bash
cd "$(git rev-parse --show-toplevel)" && python -m src.tools.dbquery 'SELECT count(*) FROM shadow_trades WHERE alpaca_order_id IS NOT NULL' --json
```

For payloads that contain literal single quotes, use the bash `'\''` escape OR switch to the stdin-pipe pattern (see below). Double-quoting payloads invites bash variable expansion — avoid unless specifically needed (e.g., `cd "$WORKTREE_PATH"` deliberately expands the variable).

### Stdin-Pipe Pattern for Body-Content Delivery

Investigator-class agents have no `Write`/`Edit` in their `allowed-tools` and cannot create temp files on disk. For any subprocess that needs to receive multi-line text content (notably `prcomments post`'s body argument), use the stdin-pipe pattern:

```bash
cat <<'EOF' | python -m src.tools.prcomments post <PR_NUMBER> --body-file - --confirm --json
# Forensic Summary — Run <run_id>

## Classification
... markdown body here ...

<!-- [fingerprint:<sha256_hex_8_chars>] -->
EOF
```

Rules:
- The prcomments CLI accepts `--body-file -` to read body content from stdin (per `_build_parser()` in `src/tools/prcomments/__main__.py`: `body_text = sys.stdin.read() if body_file == "-" else ...`).
- Use **single-quoted heredoc delimiter** `'EOF'` to prevent bash expansion of `$`, backticks, etc. inside the body payload.
- The heredoc closing `EOF` MUST be at column 0 (no leading whitespace) — indenting it is a bash parse error.
- This pattern applies anywhere an agent needs to pipe multi-line content into a Tier 1+2 tool without temp-file creation.
- The fingerprint footer (`<!-- [fingerprint:...] -->`) is appended only by ci-investigator for repost-idempotency (see §Cross-cutting-conventions appendix, DA4).

---

## §5 OUTPUT FORMAT Addendum — Investigator-Class Custom-Tag Enum (DD-11)

The §5 OUTPUT FORMAT section above mandates `<reasoning>` + `<findings>` as the default output envelope for all agents. Two classes of agent are documented exceptions to this default:

### PR-Comment-Class Exception (pre-existing)

`coding-rigor-reviewer` emits a markdown PR-comment body followed by a final JSON verdict block. This is a documented exception distinct from the investigator-class.

### Investigator-Class Custom Tags (NEW — #108)

The 4 investigator-class agents emit a single custom-tagged JSON block per agent. The permitted tags form a **registered enum**:

| Tag | Agent | Domain semantics |
|---|---|---|
| `<db_report>` | `db-investigator` | DB anomaly / schema archaeology output |
| `<ci_report>` | `ci-investigator` | CI failure triage output |
| `<git_report>` | `git-historian` | Temporal git archaeology output |
| `<live_report>` | `live-monitor` | Live-system snapshot output |

**Rules for investigator-class output tags:**
1. Tag names MUST be unique across the entire agent corpus — no two agents share an OUTPUT FORMAT tag.
2. Each agent's 5-section body MUST explicitly declare its OUTPUT FORMAT tag in the OUTPUT FORMAT section (not implicit).
3. Future investigator-class agents adding new tags MUST add a row to the registered-enum table above. Adding a new tag without updating this table is a conventions violation.
4. The `<reasoning>` block (per §5 default) is still produced BEFORE the custom tag — the investigator-class does not eliminate reasoning, it replaces `<findings>` with the domain-tagged JSON block.

### `coverage_assessment` Required Field (DA6)

Every investigator-class JSON payload MUST include a `coverage_assessment` field. This field is required on ALL FOUR investigator-class agents. Schema:

| Field | Type | Description |
|---|---|---|
| `mode_used` | string | `surface` or `deep` for db-investigator; `n/a` for ci-investigator and git-historian (which have no modes) |
| `tool_invocations_used` | integer | Count of Bash/tool invocations issued |
| `tool_invocations_budget_remaining` | integer | `60 - tool_invocations_used`; agents MUST NOT misreport this |
| `coverage_judgment` | string enum | `complete` (mandate fully answered) or `partial` (partially answered; gaps documented) or `incomplete` (budget exhausted before reaching mandate's core question) |
| `gaps_unresolved[]` | array of strings | Each string describes a sub-question the agent did NOT answer and why (budget / tool failure / out of scope) |

---

## Cross-Cutting-Conventions Appendix

The following 6 conventions apply to ALL investigator-class agents (#108 and future). Each is named with an anchor so agent prompts can cite them.

### DA1 — Worktree-Portable cwd

Every Bash subprocess invocation MUST resolve the repo root via `cd "$(git rev-parse --show-toplevel)"` — NEVER hardcode an absolute path like `cd C:/arcis/halcyon-lab`.

An agent MAY receive `WORKTREE_PATH: <abs path>` in DYNAMIC CONTEXT. When present, prefer `cd "$WORKTREE_PATH"` over `git rev-parse` (the `$WORKTREE_PATH` path is guaranteed by the dispatch envelope to be the correct worktree root, whereas `git rev-parse` requires a `.git` directory that may be absent in sparse-checkout or detached worktree shapes). `WORKTREE_PATH` is optional; absence falls back to `git rev-parse`.

**Rationale (DD-12):** The operator regularly dispatches agents from `.claude/worktrees/<branch>/` sub-directories. Hardcoding the path breaks every worktree invocation with a silent `ModuleNotFoundError`.

### DA2 — Mandatory Per-Call Bash `timeout` Parameter

Every Bash subprocess invocation MUST include an explicit `timeout` parameter (milliseconds). The Bash tool's implicit 120-second default is FORBIDDEN for investigator-class agents. See the tiered defaults in the §Bash-subprocess Tool Invocation appendix above.

**Rationale (DD-13):** A single subprocess hitting the 120s ceiling consumes 1/60 of the per-agent budget. Tiered explicit timeouts also let callers distinguish timeout failures (`timeout_exceeded` marker) from tool-internal errors.

### DA3 — Empty-Result-as-`informational` Classification

When a tool returns an EMPTY primary collection (zero rows from `dbquery`, zero files from `symbolfind`, zero lines from `logtail --grep`, zero failed jobs from `ciinvestigate`, zero services from `healthprobe`, etc.), the agent MUST classify this as an `informational` finding in OUTPUT FORMAT. An empty result MUST NOT be silently dropped.

**Required content of the `informational` finding:**
- `evidence` — the exact subprocess invocation (argv) and the empty-payload envelope.
- `recommendation` — typically "no action needed" for truly empty results; "investigate why expected non-empty result is empty" when the empty result IS the anomaly.

**Severity escalation:** `informational` < `anomaly` < `must_fix`. An empty result is always `informational` UNLESS the empty result is itself the anomaly (e.g., a table expected to have rows returning zero → classify as `anomaly`).

**Rationale (DD-14):** A silent absence is indistinguishable from a tool subprocess that bypassed parsing. Surfacing the absence honestly is the anti-handwave discipline applied at the empty-result boundary.

### DA4 — Fingerprint-Footer Convention for Repost-Idempotent Posters

This convention applies specifically to **ci-investigator** (the only investigator-class agent that posts to GitHub PRs).

**Fingerprint computation:** SHA-256 over the concatenation of `head_sha + classification_concatenated + first_200_chars_of_summary`. Take the first 8 hex characters as the fingerprint value.

**Footer format:** A single-line HTML comment appended to every posted PR comment body:
```
<!-- [fingerprint:<8-hex-char-sha256-prefix>] -->
```

**Repost-idempotency protocol:**
1. Before posting, call `prcomments read <TARGET_PR> --json` and scan all existing comment bodies for the regex `<!-- \[fingerprint:[0-9a-f]{8}\] -->`.
2. Extract each existing fingerprint.
3. If the computed fingerprint MATCHES an existing fingerprint AND `ALLOW_REPOST=false` (default): SKIP the post; set `post_status=skipped_duplicate` and `existing_fingerprint=<matched fingerprint>` in OUTPUT FORMAT.
4. If `ALLOW_REPOST=true` (operator-authorized override): proceed with the post and log the override decision in `tool_invocations[]` for audit.

**`post_status` enum:** `posted` | `skipped_duplicate` | `refused_no_target_pr` | `refused_envelope_error` | `not_attempted`

The fingerprint intentionally includes `head_sha` so a re-run on a new commit SHA produces a new fingerprint and posts normally — idempotency locks per `(head_sha, classification, summary_prefix)` triple, not per-PR.

**Rationale (DD-15):** Multi-agent dispatch patterns produce a real risk of ci-investigator being re-dispatched against the same `RUN_ID` and posting a duplicate forensic summary. The fingerprint pre-check prevents duplicate spam while still allowing fresh posts when the underlying evidence has changed (new SHA → new fingerprint).

### DA5 — JSONB / TEXT 200-Char Truncation Rule

Tier 1+2 tools faithfully return whatever JSONB / TEXT payload the DB or process emits. Agents MUST NOT echo full JSONB / TEXT column values into `<reasoning>` or OUTPUT FORMAT bodies without truncation.

**Truncation rule:** Every column whose name matches the patterns `*_jsonb`, `*_detail`, `*_payload`, `*_body`, OR whose serialized representation exceeds 200 characters, MUST be truncated to the first 200 characters with the literal suffix ` [truncated]` appended.

The full value MAY be retained in the agent's transient working memory for analysis. Only the SURFACED rendering (in reports, in cited evidence, in PRComments bodies) is truncated.

**Rationale (DD-16):** (a) Prevents bloating turn budgets with multi-KB payloads. (b) Reduces secret-bleed surface area — `audit_reports.findings_jsonb` regularly contains transient secrets; agent-layer truncation is defense-in-depth alongside PRComments' own `_secrets.detect_secret_in_text` pre-flight. (c) Keeps PRComments-posted bodies legible.

### DA6 — Turn-50 Budget-Stop with `coverage_assessment`

Every investigator-class agent MUST gracefully exit at turn 50, leaving 10 turns headroom for composing OUTPUT FORMAT JSON and the final `<reasoning>` block without truncation.

**At turn 50, the agent MUST:**
1. Stop issuing new tool invocations.
2. Finalize findings from data already collected.
3. Populate `coverage_assessment` honestly (see §5 OUTPUT FORMAT Addendum for the required schema).

`coverage_assessment` is a REQUIRED field on ALL FOUR investigator-class OUTPUT FORMATs. The `coverage_judgment` field MUST reflect reality: `complete` only when the mandate was fully answered; `partial` or `incomplete` when budget constrained the investigation.

**Rationale (DD-17):** An agent that hits `maxTurns: 60` mid-tool-call produces truncated OUTPUT FORMAT JSON that callers (#109, #111) cannot parse. The 50/60 budget-stop guarantees parseable output even on the most expensive investigations. The `coverage_assessment` field provides cross-agent comparability for the #111 skill-audit's regression tracking.
