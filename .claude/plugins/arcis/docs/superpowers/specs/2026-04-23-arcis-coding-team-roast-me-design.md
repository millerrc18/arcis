# ARCIS Coding-Team & Roast-Me Design Spec

**Date:** 2026-04-23
**Plugin:** ARCIS (Autonomous Research & Coding Intelligence System)
**Skills covered:** coding-team, roast-me
**Depends on:** shared/ infrastructure (findings schema, ICD 203, source quality rubric, completeness reporting)
**Complements:** research-team (already implemented), superpowers:subagent-driven-development (different scope class)

---

## Relationship to Existing Skills

**coding-team vs. subagent-driven-development:** These complement each other. subagent-driven-development handles plan-based task-by-task execution — it requires a pre-written plan and dispatches implementer + generic reviewer subagents. coding-team handles a different class of work:

- **Scale:** 10+ file changes, multiple subsystems, needs architectural coordination
- **Autonomy:** Generates its own internal plan from a spec or high-level request
- **Quality amplification:** Dispatches domain-specific reviewers (QA, Security, Performance) instead of generic code-quality review

The trigger is: if the work is large enough to need its own planning phase, parallel developer dispatch, and specialized review lanes, use coding-team. If you have a well-specified plan and need linear task execution, use subagent-driven-development.

**roast-me vs. code-review skills:** roast-me is not a code review tool. It's a polymorphic critical analysis system that uses adversarial debate (Prosecutor vs. Defense vs. Judge) to find gaps, flaws, and unanswered questions in any artifact — research output, code, designs, plans, proposals, or freeform text. Code review skills focus on code quality. roast-me focuses on whether the thing is fundamentally sound.

---

# Part 1: Coding-Team

## 1.1 Overview

The coding-team skill provides autonomous, large-scope implementation with hierarchical agent coordination, regression prevention, scope discipline, and specialized review. A Project Manager (PM) agent orchestrates the full lifecycle: planning, parallel developer dispatch, domain-specific review, documentation, and integration verification.

**Command:** `/arcis:code`
**Auto-trigger:** Yes — triggers on multi-file implementation requests ("build", "implement", "create", "add [feature] with [multiple components]")

## 1.2 Agent Hierarchy

```
Coding PM (command orchestrator, opus)
├── Coding Planner (opus, maxTurns:6)
│   — Generates internal implementation plan from spec/request
│   — Produces task graph with dependencies, file assignments, scope fences, test strategy
│
├── Coding Developers (parallel, sonnet, maxTurns:12 each)
│   — One per task or task-group from the plan
│   — TDD: write failing test → implement → pass → commit
│   — Runs FULL test suite (not just new tests) before reporting done
│   — Reports: files changed, tests passing, concerns/blockers
│
├── Coding Reviewers (parallel after each dev completes, opus, maxTurns:4 each)
│   ├── QA Reviewer — spec compliance, test coverage, edge cases, scope violations
│   ├── Security Reviewer — OWASP top 10, injection, auth, secrets, error exposure
│   └── Performance Reviewer — complexity, allocations, N+1 queries, concurrency issues
│
├── Coding Documentarian (sonnet, maxTurns:6)
│   — Runs after all tasks pass review, before Integrator
│   — Receives: change_manifest, original spec, git diff
│   — Updates: README, API docs, inline doc comments, CHANGELOG
│   — ONLY documents what changed — does not document unchanged code
│
└── Coding Integrator (opus, maxTurns:6)
    — Runs after Documentarian
    — Full test suite, cross-file consistency check, regression sweep
    — Diffs every file against pre-implementation state
    — If regressions found → dispatches targeted fix Developer
    — Produces final status report
```

### Agent Details

**Coding PM** — The orchestrator. Does not write code. Coordinates all agents, maintains the change manifest, enforces scope, detects anti-patterns, and makes routing decisions (which reviewers to dispatch, whether to upgrade a Developer to opus, whether to force sequential execution for a risky task). Uses opus. No maxTurns limit (it's the command orchestrator).

**Coding Planner** — Receives the spec or high-level request and produces a structured task graph. Each task includes: description, files in scope, files read-only, dependencies on other tasks, test strategy, and a scope fence (explicit "do NOT" instructions). Uses opus because planning requires broad codebase understanding and architectural judgment. maxTurns: 6.

**Coding Developer** — Implements a single task from the plan. Follows TDD: write failing test, implement minimal code to pass, run full test suite, commit. Receives the task description, scope fence, change manifest (what prior Developers modified), and any relevant file content. Uses sonnet (upgradeable to opus via `--model opus`). maxTurns: 12.

**Coding QA Reviewer** — Checks spec compliance, test coverage, edge case handling, and scope violations. Has a dedicated scope check: "Did the Developer modify anything outside `files_in_scope`? Did they add functionality beyond the task description?" Uses opus. maxTurns: 4.

**Coding Security Reviewer** — Checks OWASP top 10, injection vectors, auth/authz issues, secrets in code, error message exposure, input validation at system boundaries. Uses opus. maxTurns: 4.

**Coding Performance Reviewer** — Checks algorithmic complexity, unnecessary allocations, N+1 query patterns, blocking I/O on async paths, shared mutable state without synchronization. Uses opus. maxTurns: 4.

**Coding Documentarian** — Updates existing documentation to reflect changes. Reads the change manifest and git diff, identifies stale or missing docs, and updates them. Does NOT: add docstrings to functions it didn't write, create new doc files unless warranted, rewrite existing docs for style. Uses sonnet. maxTurns: 6.

**Coding Integrator** — Final verification. Runs the full test suite, reviews the total diff against the original spec, checks for unintended side effects (deleted functions still referenced elsewhere, changed signatures, import breakage). If regressions are found, dispatches a targeted fix Developer with specific instructions. Optional for small jobs (PM skips it if only 1-2 tasks were dispatched). Uses opus. maxTurns: 6.

### Reviewer Dispatch Logic

Not every reviewer runs for every task. The PM selects relevant reviewers based on what the task touches:

| Task touches... | QA | Security | Performance |
|----------------|-----|----------|-------------|
| API endpoints, auth, user input | Yes | Yes | Yes |
| Data models, database queries | Yes | No | Yes |
| Business logic, algorithms | Yes | No | Yes |
| Frontend/UI components | Yes | No | No |
| Config, env, infrastructure | Yes | Yes | No |
| Documentation only | No | No | No |

QA always runs (it checks scope compliance). Security and Performance are dispatched selectively.

## 1.3 Execution Phases

The PM executes 7 phases in order:

### Phase 1: INTAKE

Parse arguments. Read spec/plan file if provided via `--spec` or `--plan`. If freeform request, capture it as the spec. Assess initial scope. If `--files` is provided, set the hard scope fence.

### Phase 2: PLAN

Skip if `--plan` was provided (plan already exists).

Dispatch the Coding Planner with the spec/request. The Planner returns a task graph:

```json
{
  "tasks": [
    {
      "id": 1,
      "name": "Add User model with email validation",
      "description": "Create User SQLAlchemy model with fields: id, email, name, created_at. Add email validation via regex. Add unique constraint on email.",
      "files_in_scope": ["src/models/user.py", "tests/test_user.py"],
      "files_read_only": ["src/models/base.py"],
      "depends_on": [],
      "test_strategy": "Unit test email validation (valid, invalid, edge cases). Unit test model creation. Test unique constraint violation.",
      "scope_fence": "Do NOT modify base.py. Do NOT add password hashing — that is a separate task. Do NOT add API endpoints.",
      "estimated_complexity": "low"
    }
  ],
  "execution_order": [[1, 2], [3], [4, 5], [6], [7]],
  "notes": "Tasks 1 and 2 are independent and can run in parallel. Task 3 depends on both. Tasks 4 and 5 are independent but both depend on 3."
}
```

The PM presents the task graph to the user and waits for approval before proceeding. If `--dry-run` was specified, the PM stops here after presenting the plan.

### Phase 3: EXECUTE

Dispatch Developers per the task graph's `execution_order`. Independent tasks run in parallel. Dependent tasks wait for their prerequisites.

The PM maintains a **change manifest** that accumulates across all tasks:

```json
{
  "completed_tasks": [
    {
      "task_id": 1,
      "task_name": "Add User model",
      "files_modified": ["src/models/user.py", "tests/test_user.py"],
      "functions_added": ["User.validate_email", "User.hash_password"],
      "functions_modified": [],
      "tests_added": ["test_validate_email", "test_hash_password"],
      "commit_sha": "abc1234"
    }
  ]
}
```

Each subsequent Developer receives the current change manifest so it knows what prior Developers changed and can avoid blind overwrites.

### Phase 4: REVIEW

After each Developer reports DONE or DONE_WITH_CONCERNS:

1. PM checks output against the anti-fallacy playbook (Section 1.5)
2. PM dispatches relevant Reviewers in parallel
3. If any Reviewer flags issues → Developer fixes → Reviewers re-review
4. Loop until all dispatched Reviewers approve
5. PM updates change manifest and marks task complete

### Phase 5: DOCUMENT

Dispatch the Coding Documentarian with the change manifest, original spec, and git diff. The Documentarian updates existing docs and adds CHANGELOG entries. Skipped if `--no-docs` flag was provided.

### Phase 6: INTEGRATE

Dispatch the Coding Integrator for final regression sweep. The Integrator:
1. Runs the full test suite
2. Diffs every changed file against the pre-implementation state
3. Checks for cross-file consistency (imports, type signatures, API contracts)
4. If regressions found → dispatches a targeted fix Developer → re-runs verification
5. Produces final status report

Skipped for small jobs (1-2 tasks) unless the PM detects risk signals.

### Phase 7: REPORT

PM produces a summary report:
- Tasks completed (count, names)
- Files changed (list with line counts)
- Tests: total passing, total failing, new tests added
- Issues found and resolved during review
- Concerns flagged by Developers (with PM's disposition)
- Regressions caught and fixed during integration
- Fallacy patterns detected and handled
- Overall assessment

## 1.4 Regression Prevention

Three-layer defense against "fix A, break B."

### Layer 1: Cumulative Test Gates

Every Developer runs the full test suite after implementation, not just their new tests. If any pre-existing test fails, the Developer must fix the regression before reporting DONE. The PM treats a Developer result with failing pre-existing tests as BLOCKED, not DONE.

### Layer 2: Context Propagation

Each Developer receives the change manifest showing what prior Developers modified — file paths, functions changed, tests added. Developers MUST check their changes against the manifest. If they need to modify a file another Developer already touched, they MUST read the current state of that file first, not work from their initial context.

### Layer 3: Integrator Regression Sweep

The Integrator's primary job is regression detection, not feature verification. It:
1. Runs the full test suite
2. Diffs every file against the pre-implementation state
3. Checks for unintended side effects: deleted functions still referenced elsewhere, changed signatures without updated callers, import breakage
4. If regressions found → dispatches a targeted fix Developer with specific instructions about what broke and why

### Atomic Rollback Awareness

Each Developer commits after their task passes review. If the Integrator finds a regression introduced by Task N, the commit history makes it possible to identify exactly which task caused it. No debugging in the dark.

## 1.5 Scope Control

Three-checkpoint defense against scope creep.

### Checkpoint 1: Planner Produces Scoped Tasks

Each task includes a `scope_fence` — explicit "do NOT" instructions that bound what the Developer is allowed to change. The `files_in_scope` list is exhaustive; any file not listed is off-limits.

### Checkpoint 2: QA Reviewer Checks Scope

The QA Reviewer's checklist includes a dedicated scope check:
- Did the Developer modify any files outside `files_in_scope`?
- Did they add functionality beyond the task description?
- Did they add docstrings, comments, or type annotations to code they didn't change?
- Is the diff size proportional to the task scope?

Scope violations are flagged as issues with the same severity as bugs. The Developer must revert them.

### Checkpoint 3: Integrator Diff Audit

The Integrator reviews the total diff against the original spec. Changes that can't be traced back to a specific task in the plan are flagged. This catches cumulative drift where each task adds "just one small thing" and the total diverges from intent.

### Developer Prompt Constraints

In the Developer agent prompt itself:
- MUST NOT modify files outside your `files_in_scope` list
- MUST NOT add features, refactor code, or make "improvements" beyond the task description
- MUST NOT add docstrings, comments, or type annotations to code you didn't change
- MUST NOT create helpers, utilities, or abstractions for patterns that occur only once
- If you notice something that should be fixed but isn't in your task, report it in your output as a `suggestion` — do not fix it

## 1.6 PM Anti-Fallacy Playbook

The PM agent prompt includes a catalog of 24 known sub-agent failure patterns, organized into four categories. The PM consults this reference when evaluating Developer output and makes prescribed responses (BLOCK, REJECT, SUSPECT, FLAG) rather than rationalizing issues away.

### Cascading Failure Patterns

| Fallacy | What Happens | Detection Signal | PM Response |
|---------|-------------|-----------------|-------------|
| **Cascade fix** | Agent fixes bug A by introducing a workaround that breaks feature B | Full test suite has new failures after Developer reports DONE | BLOCK: Developer must identify root cause and fix without side effects. If they can't, escalate to opus-tier Developer |
| **Signature drift** | Agent changes a function's parameters or return type but only updates the immediate caller, not all callers | QA Reviewer finds type errors or runtime failures in files the Developer didn't touch | BLOCK: Developer must grep for all usages of the changed function and update every call site. PM verifies count matches |
| **Import chain break** | Agent renames, moves, or restructures a module's exports; downstream importers silently break | Integrator's full test run reveals failures in modules the Developer didn't list as modified | BLOCK: Developer must update all import sites. PM cross-references change manifest to verify no file was missed |
| **State mutation ripple** | Agent modifies shared state (global config, singleton, database schema, shared context) without tracing all consumers | Tests pass in isolation but fail when run together; or Integrator finds behavioral changes in unrelated features | BLOCK: Developer must map every consumer of the shared state before modifying it. PM requires the consumer list in the Developer's output |
| **Migration cascade** | Schema change breaks ORM models, which break API layer, which break frontend/templates | Any test failure that spans more than 2 layers of the stack after a model change | BLOCK: PM must ensure schema changes are planned as multi-task sequences (schema, models, API, consumers), not single tasks |
| **Error type cascade** | Agent changes an error class, error code, or exception type; upstream handlers no longer catch it | QA Reviewer finds bare `except Exception` replacements or unhandled error paths | BLOCK: Developer must trace every try/catch/except that references the old error type and update them |
| **Partial revert** | Agent attempts to undo a broken change but only reverts some files, leaving the codebase in a hybrid state | Change manifest shows the Developer modified fewer files in the revert than in the original change | BLOCK: PM compares revert scope against original change scope. Every file touched in the forward change must be addressed in the revert |
| **Test fixture contamination** | Agent's new test mutates shared fixtures, database state, or module-level variables; other tests start failing nondeterministically | Tests pass individually but fail when run as a suite, or fail in different orders | BLOCK: Developer must isolate test state. Each test sets up and tears down its own fixtures. No shared mutable state between tests |
| **Dependency version cascade** | Agent upgrades a dependency to fix one issue; transitive dependencies break or conflict | Build/install failures, or runtime errors in unrelated modules after a dependency change | BLOCK: Developer must run full dependency resolution and test suite before reporting. PM flags any task that touches dependency files for extra scrutiny |
| **Config drift** | Agent hardcodes a value that was previously configurable, or changes a config default without updating all environments | Integrator finds hardcoded values that duplicate or contradict config entries | FLAG: Developer must extract to config or justify the hardcode in their output |

### Dishonest Reporting Patterns

| Fallacy | What Happens | Detection Signal | PM Response |
|---------|-------------|-----------------|-------------|
| **Phantom green** | Agent claims tests pass but didn't run them, or ran a subset | Developer output lacks the exact test command and full stdout/stderr transcript | BLOCK: re-dispatch with explicit instruction to run full test suite and paste complete output including pass/fail counts |
| **Confidence theater** | Agent says "done, all good" with an empty concerns field on a complex multi-file task | DONE status + no concerns + task complexity > 3 files | SUSPECT: dispatch QA Reviewer with deep-scrutiny flag; Reviewer must independently run tests and verify behavior |
| **Test-only fix** | Agent makes a failing test pass by modifying the test assertions to match broken behavior, rather than fixing the code | QA Reviewer finds test expectations were changed; diff shows test assertions modified but implementation unchanged | REJECT: Developer must fix the implementation, restore original test assertions. If the test was genuinely wrong, Developer must explain why in output |
| **False positive test** | Agent writes tests that pass regardless of implementation — testing mocks, tautologies, or asserting nothing | QA Reviewer finds tests with no meaningful assertions, or tests that pass even when the function under test is deleted | REJECT: Developer must write tests that actually fail when implementation is removed or broken |

### Scope Discipline Violations

| Fallacy | What Happens | Detection Signal | PM Response |
|---------|-------------|-----------------|-------------|
| **Scope drift** | Agent "improves" adjacent code, adds type hints to unchanged lines, cleans up imports it didn't break | QA Reviewer flags files modified outside `files_in_scope`, or diff lines that don't trace to the task | REJECT: Developer reverts non-task changes, re-submits scoped diff only |
| **Gold plating** | Agent adds error handling, logging, abstractions, or configurability nobody requested | Diff is significantly larger than expected; new functions/classes appear that aren't in the task spec | REJECT: Developer strips additions, re-submits minimal implementation |
| **Premature abstraction** | Agent creates a helper, utility, or base class for a pattern that only occurs once | New files or classes appear that serve a single caller | REJECT: Developer inlines the logic. Abstractions are only justified when 3+ consumers exist |
| **Zombie code** | Agent comments out code instead of deleting it, or leaves `# TODO: remove` markers | QA Reviewer finds commented-out blocks or TODO markers referencing removed features | REJECT: Developer deletes dead code completely. Git history is the backup, not comments |
| **Under-implementation** | Agent implements the happy path but skips error paths, edge cases, or validation that the task spec explicitly requires | QA Reviewer finds spec requirements without corresponding code or tests | BLOCK: Developer must implement all spec requirements. PM cross-references spec checklist against implementation |

### Code Quality Failures

| Fallacy | What Happens | Detection Signal | PM Response |
|---------|-------------|-----------------|-------------|
| **Copy-paste amnesia** | Agent duplicates existing logic instead of calling the existing function | QA Reviewer or Integrator finds near-identical code blocks | FLAG: Developer refactors to use existing function. PM updates change manifest |
| **Silent failure** | Agent catches and swallows errors with bare `except:`, empty `catch {}`, or `_ = err` | QA or Security Reviewer finds error-suppression patterns | REJECT: Developer must surface, log, or handle each error specifically |
| **Magic values** | Agent uses string literals, numeric constants, or inline URLs instead of named constants or config | QA Reviewer finds repeated literals or un-labeled magic numbers | FLAG: Developer extracts to named constants |
| **Race condition introduction** | Agent adds async/concurrent code without proper synchronization | Performance Reviewer finds shared mutable state accessed across threads/tasks without locks or atomic operations | BLOCK: Developer must add synchronization or redesign to avoid shared state |
| **Stale context** | Agent works against an old file state, overwriting another Developer's changes | Change manifest shows file was modified by a prior task but Developer's diff doesn't include those prior changes | BLOCK: Developer must re-read current file state and re-implement against it |

## 1.7 Progress Dashboard

The PM writes status updates to `.arcis/coding-dashboard.json` at every state transition. A lightweight HTML dashboard (shipped with the plugin) auto-refreshes from that file and is opened by the PM at execution start.

### Dashboard Layout

```
┌─────────────────────────────────────────────────────────┐
│  ARCIS Coding Team — "Add pagination to list endpoints" │
│  Phase: EXECUTE (3/7 tasks)          Elapsed: 4m 12s    │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  PLAN → EXECUTE → REVIEW → DOCS → INTEGRATE → REPORT   │
│           ▲                                             │
│           ┃ (active)                                    │
│                                                         │
├──────────────────────┬──────────────────────────────────┤
│  Task Graph          │  PM Notes                        │
│                      │                                  │
│  ✅ 1. User model    │  "Task 3 is the riskiest —      │
│  ✅ 2. Base paginator│   touches 4 shared files.        │
│  🔄 3. API endpoints │   Dispatched with --sequential   │
│  ⏳ 4. Query builder │   and extra context about the    │
│     └─ blocked by 3  │   base paginator from Task 2."   │
│  ⏳ 5. Frontend hooks│                                  │
│     └─ blocked by 4  │  "Developer 3 came back with     │
│  ⏳ 6. Tests         │   DONE_WITH_CONCERNS — says the  │
│  ⏳ 7. Error handling│   offset approach may not scale.  │
│                      │   Noted but proceeding — spec     │
│                      │   says offset, not cursor."       │
│                      │                                  │
├──────────────────────┴──────────────────────────────────┤
│  Active Agents                                          │
│                                                         │
│  🔨 Developer 3    (sonnet)  API endpoints   turn 7/12  │
│  ────────────────────▓▓▓▓▓▓▓▓▓▓▓▓░░░░░── 58%          │
│                                                         │
├─────────────────────────────────────────────────────────┤
│  Issues & Alerts                              0 🔴 1 🟡 │
│                                                         │
│  🟡 Task 3: DONE_WITH_CONCERNS — offset scalability    │
│                                                         │
├─────────────────────────────────────────────────────────┤
│  Scorecard                                              │
│  Tests: 14 pass / 0 fail    Scope violations: 0         │
│  Regressions caught: 0      Fallacies detected: 0       │
│  Files changed: 6           Lines added: 234            │
└─────────────────────────────────────────────────────────┘
```

### Dashboard Status File Schema

The PM writes to `.arcis/coding-dashboard.json`:

```json
{
  "project_name": "Add pagination to list endpoints",
  "phase": "EXECUTE",
  "elapsed_seconds": 252,
  "tasks": [
    {
      "id": 1,
      "name": "User model",
      "status": "completed",
      "blocked_by": [],
      "developer_model": "sonnet",
      "review_status": "passed"
    }
  ],
  "active_agents": [
    {
      "role": "developer",
      "task_id": 3,
      "model": "sonnet",
      "turn": 7,
      "max_turns": 12
    }
  ],
  "pm_notes": [
    {
      "timestamp": "2026-04-23T14:03:22",
      "note": "Task 3 is the riskiest — touches 4 shared files. Dispatched with extra context.",
      "sentiment": "cautious"
    }
  ],
  "scorecard": {
    "tests_pass": 14,
    "tests_fail": 0,
    "scope_violations": 0,
    "regressions_caught": 0,
    "fallacies_detected": 0,
    "files_changed": 6,
    "lines_added": 234
  },
  "issues": [
    {
      "severity": "warning",
      "task_id": 3,
      "message": "DONE_WITH_CONCERNS — offset scalability"
    }
  ]
}
```

### PM Notes

The PM writes a short natural-language note at every significant decision point. These capture the PM's reasoning, not just status:
- Why it chose to dispatch a task sequentially vs. parallel
- What it's worried about
- How it interpreted a Developer's concerns
- Whether it upgraded a Developer to opus and why
- When it detects a fallacy pattern and what it did about it

The `sentiment` field (`confident`, `cautious`, `concerned`, `recovering`) gives the dashboard a color-coded mood indicator for at-a-glance assessment.

### Dashboard Implementation

The dashboard is a single static HTML file at `skills/coding-team/dashboard/index.html`. It reads `.arcis/coding-dashboard.json` via `fetch()` and re-renders every 2 seconds. No server required. The PM opens it via Playwright at execution start if the Playwright MCP tool is available. If Playwright is not available, the PM logs dashboard file path to the console so the user can open it manually.

## 1.8 Command Interface

**Command:** `/arcis:code`

**Usage:**
```
/arcis:code <request or spec description>
/arcis:code --plan path/to/plan.md
/arcis:code --spec path/to/spec.md
/arcis:code --files src/models/ src/api/ -- "Add pagination to all list endpoints"
```

**Arguments:**

| Flag | Purpose | Default |
|------|---------|---------|
| `--plan <path>` | Skip internal planning — execute an existing plan file directly | None |
| `--spec <path>` | Read a design spec and generate the internal plan from it | None |
| `--files <paths...>` | Constrain scope to specific files/directories (hard scope fence) | Unrestricted |
| `--model opus` | Upgrade Developer agents from sonnet to opus for complex tasks | sonnet |
| `--no-docs` | Skip the Documentarian agent | Docs enabled |
| `--dry-run` | Planner generates the task graph but no Developers are dispatched. User reviews the plan first | Full execution |
| `--sequential` | Force sequential Developer dispatch (no parallelism). Safer for tightly coupled changes | Parallel where possible |

**Auto-trigger heuristic:** Triggers when the user's request implies multi-file implementation work — "build", "implement", "create", "add [feature] with [multiple components]". Does NOT trigger for single-file edits, bug fixes, or refactors.

## 1.9 Developer Status Handling

Developer agents report one of four statuses. The PM handles each:

**DONE:** Proceed to review phase. Dispatch relevant Reviewers.

**DONE_WITH_CONCERNS:** Developer completed the work but flagged doubts. PM reads concerns before proceeding. If concerns are about correctness or scope, address before review. If observational ("this file is getting large"), note in PM notes and proceed.

**NEEDS_CONTEXT:** Developer needs information that wasn't provided. PM provides the missing context and re-dispatches the same Developer.

**BLOCKED:** Developer cannot complete the task. PM assesses:
1. If context problem → provide more context, re-dispatch same model
2. If task requires more reasoning → re-dispatch with opus
3. If task is too large → break into smaller pieces, update task graph
4. If plan is wrong → flag to user, do not proceed

The PM never ignores an escalation or forces the same model to retry without changes.

## 1.10 Model Tiering

| Role | Default Model | Rationale |
|------|--------------|-----------|
| Coding PM | opus | Coordination, judgment, anti-fallacy detection |
| Coding Planner | opus | Architectural understanding, dependency analysis |
| Coding Developer | sonnet | Well-scoped implementation tasks |
| QA Reviewer | opus | Judgment-heavy: spec compliance, scope violations |
| Security Reviewer | opus | Security analysis requires deep reasoning |
| Performance Reviewer | opus | Performance analysis requires architectural context |
| Coding Documentarian | sonnet | Well-scoped doc updates from change manifest |
| Coding Integrator | opus | Cross-file regression analysis |

The `--model opus` flag upgrades Developers from sonnet to opus. All other roles are fixed.

## 1.11 File Structure

```
skills/coding-team/
├── SKILL.md                          # Skill metadata, auto-trigger config
├── commands/
│   └── code.md                       # PM orchestrator (command file)
├── agents/
│   ├── coding-planner.md             # Task graph generator
│   ├── coding-developer.md           # TDD implementer
│   ├── coding-qa-reviewer.md         # Spec compliance + scope check
│   ├── coding-security-reviewer.md   # OWASP + secrets + auth
│   ├── coding-performance-reviewer.md # Complexity + concurrency
│   ├── coding-documentarian.md       # Doc updater
│   └── coding-integrator.md          # Final regression sweep
├── references/
│   └── anti-fallacy-playbook.md      # 24-pattern reference table
└── dashboard/
    └── index.html                    # Live progress dashboard
```

## 1.12 Shared Infrastructure Usage

The coding-team skill uses shared infrastructure from `shared/`:

- **findings-schema.md** — Not directly used for output (coding-team produces code, not research findings). However, if coding-team is invoked to implement something based on research-team output, the Planner reads findings schema to understand the input.
- **completeness-reporting.md** — The Integrator borrows the completeness methodology to report how thoroughly the spec was implemented (confidence-weighted task completion).
- **agent-conventions.md** — All coding-team agents follow the 5-section prompt structure and naming conventions defined in `docs/agent-conventions.md`.

---

# Part 2: Roast-Me

## 2.1 Overview

The roast-me skill provides adversarial critical analysis of any artifact — research output, code, designs, plans, proposals, or freeform text. It uses an adversarial debate model: a Prosecutor finds every flaw, a Defense steelmans the artifact, and a Judge weighs both sides to produce a severity-ranked verdict.

The goal is not to be mean — it's to find the things you missed, the assumptions you didn't examine, and the failure modes you haven't considered. The adversarial structure ensures both sides are represented: genuine weaknesses are surfaced, but genuine strengths aren't lost in the process.

**Command:** `/arcis:roast`
**Auto-trigger:** Yes — triggers on "roast", "critique", "tear apart", "find problems with", "what's wrong with", "poke holes in", "devil's advocate"

## 2.2 Agent Hierarchy

```
Roast Director (command orchestrator, opus)
├── Roast Prosecutor (opus, maxTurns:8)
│   — Finds every flaw, gap, weakness, logical fallacy,
│     unsupported claim, missing consideration
│   — Adversarial by design — assumes the artifact is wrong
│     until proven otherwise
│   — Produces a structured indictment
│
├── Roast Defense (opus, maxTurns:8)
│   — Steelmans the artifact — finds the best interpretation
│   — Identifies strengths the Prosecutor would ignore
│   — Anticipates weaknesses and pre-builds defenses
│   — Concedes genuine weaknesses but contextualizes them
│   — Produces a structured defense brief
│
└── Roast Judge (opus, maxTurns:4, no tools)
    — Reads both Prosecutor and Defense output
    — Weighs each charge: sustained, partially sustained,
      dismissed, or insufficient evidence
    — Produces the final verdict with severity-ranked findings
    — Pure synthesis — no tools, no independent research
```

### Agent Details

**Roast Director** — The orchestrator. Receives the artifact, detects its type, normalizes it into a clean brief, dispatches Prosecutor and Defense in parallel, then dispatches the Judge with both outputs. Formats the final report. Uses opus. No maxTurns limit (command orchestrator).

**Roast Prosecutor** — The adversary. Its job is to find every flaw, gap, and weakness in the artifact. It assumes the artifact is wrong until proven otherwise. It categorizes charges by type (logic, evidence, completeness, assumption, security, feasibility, consistency) and severity (critical, major, minor, nit). It must provide evidence for each charge — "this is bad" without specifics is not a valid charge. Uses opus. maxTurns: 8. Has access to search/read tools so it can verify claims, check sources, and find counterexamples.

**Roast Defense** — The steelman. Its job is to find the best interpretation of the artifact, identify genuine strengths, and anticipate/pre-rebut weaknesses. It does not see the Prosecutor's output (they run in parallel). Instead, it independently identifies what a critic would attack and prepares defenses. Where weaknesses are genuine, it concedes but contextualizes ("this is a real gap, but here's why it's bounded"). Uses opus. maxTurns: 8. Has access to search/read tools for evidence gathering.

**Roast Judge** — The arbiter. Receives both the Prosecutor's indictment and the Defense's brief. For each Prosecutor charge, it checks whether the Defense anticipated it, weighs the arguments, and rules: sustained, partially sustained, dismissed, or insufficient evidence. It also surfaces Defense strengths that the Prosecutor didn't challenge. Has NO tools — it's a pure reasoning agent that works only from the two briefs presented to it. Uses opus. maxTurns: 4.

### Why All Opus

Every roast-me agent uses opus. Critique requires strong reasoning — a sonnet-tier agent would miss subtle logical fallacies, accept surface-level evidence, and produce less rigorous analysis. The entire value proposition of roast-me is depth of analysis. There is no cost-saving tier here.

## 2.3 Artifact Detection

The Director auto-detects artifact type and includes it in the brief so the Prosecutor and Defense calibrate their lenses accordingly.

| Artifact Type | Detection Signal | Critique Lens |
|---------------|-----------------|---------------|
| **ARCIS research output** | Contains `<findings>` tags or findings JSON schema fields (`key_findings`, `evidence_digest`, `cross_domain_hooks`) | Evidence quality, confidence calibration, source gaps, logical leaps in synthesis, missing domains, ICD 203 compliance |
| **Code** | File extensions (.py, .js, .ts, .go, .rs, etc.) or fenced code blocks with language tags | Bugs, security vulnerabilities, performance issues, maintainability, missing edge cases, architectural smell, test coverage gaps |
| **Design spec / architecture doc** | Markdown with sections like "Architecture", "Components", "Data flow", "API" | Feasibility, missing requirements, unstated assumptions, scalability gaps, integration risks, missing error handling strategy |
| **Implementation plan** | Markdown with task checkboxes, file paths, step-by-step instructions, commit messages | Missing steps, wrong ordering, dependency gaps, untestable tasks, scope ambiguity, missing rollback strategy |
| **Proposal / strategy** | Prose-heavy document mentioning goals, stakeholders, timelines, risks, budget, ROI | Logical fallacies, unsupported claims, missing alternatives, hidden assumptions, political blind spots, unrealistic timelines |
| **Freeform / unknown** | None of the above patterns match | General critical analysis: logic, evidence, completeness, assumptions, counterarguments, internal consistency |

The detected type biases the critique lens but does not restrict it. A Prosecutor roasting a design spec might flag security concerns (typically a "code" lens) if the design doesn't address them. Cross-lane critique is encouraged.

## 2.4 Input Normalization

The Director normalizes all input types into a standard brief before dispatching:

```
ARTIFACT TYPE: design-spec
ARTIFACT SOURCE: docs/superpowers/specs/2026-04-22-feature-design.md
ARTIFACT LENGTH: 847 lines

--- BEGIN ARTIFACT ---
[full content]
--- END ARTIFACT ---
```

No framing, no hints, no "pay attention to section X." Both agents receive the raw artifact and form their own judgments independently.

For `--compare` mode, the brief includes both artifacts:

```
ARTIFACT TYPE: implementation-vs-spec
PRIMARY ARTIFACT: src/api/users.py (implementation)
REFERENCE ARTIFACT: docs/specs/user-api-design.md (spec)

--- BEGIN PRIMARY ARTIFACT ---
[implementation content]
--- END PRIMARY ARTIFACT ---

--- BEGIN REFERENCE ARTIFACT ---
[spec content]
--- END REFERENCE ARTIFACT ---
```

## 2.5 Prosecutor Output Format

The Prosecutor produces a structured indictment:

```json
{
  "charges": [
    {
      "id": "P-001",
      "severity": "critical | major | minor | nit",
      "category": "logic | evidence | completeness | assumption | security | feasibility | consistency",
      "charge": "The spec claims pagination will use offset-based queries but never addresses the known performance degradation on large tables",
      "location": "Section 4.2, paragraph 3",
      "evidence": "Offset pagination requires scanning all preceding rows. At 1M+ records this becomes O(n) per page request. See PostgreSQL documentation on OFFSET performance.",
      "what_should_exist": "Cursor-based pagination strategy, or explicit justification for offset with documented performance bounds and dataset size constraints"
    }
  ],
  "overall_assessment": "string — Prosecutor's summary of how fundamentally flawed the artifact is",
  "strongest_charge": "P-001 — reference to the single most damaging finding"
}
```

**Charge severity calibration:**
- **Critical** — Would cause failure, data loss, security breach, or fundamental misalignment with stated goals
- **Major** — Significant gap that would require rework if not addressed before implementation
- **Minor** — Real issue but bounded impact; can be addressed during implementation
- **Nit** — Style, preference, or theoretical concern; not immediately actionable

**Rules:**
- Every charge must have evidence. "This is bad" is not a valid charge.
- Charges must be specific and falsifiable. "The architecture is unclear" is too vague. "The architecture diagram shows Service A calling Service B, but Section 3.2 says Service B has no public API" is specific.
- The Prosecutor must not fabricate issues. Genuine criticism only — if the artifact is genuinely good, a short indictment is the correct output.

## 2.6 Defense Output Format

The Defense produces a structured brief:

```json
{
  "strengths": [
    {
      "id": "D-001",
      "strength": "The error handling strategy is comprehensive — every API endpoint has explicit error types and the failure modes are well-documented",
      "significance": "high | moderate | low"
    }
  ],
  "anticipated_weaknesses": [
    {
      "id": "AW-001",
      "weakness": "Offset pagination won't scale to large datasets",
      "defense": "Spec constrains to <100K rows (Section 2.1). Offset is simpler and appropriate for stated requirements. Cursor-based adds complexity without benefit at this scale.",
      "concession": "full | partial | none",
      "concession_note": "Would need revisiting if scale requirements change beyond 100K rows"
    }
  ],
  "overall_assessment": "string — Defense's summary of what the artifact does well that a pure critic would miss"
}
```

**Rules:**
- The Defense must not be sycophantic. If a weakness is genuine and severe, concede it ("full" concession) and contextualize.
- Strengths must be real and substantive. "It's well-written" is not a strength. "The error taxonomy maps 1:1 to HTTP status codes, making client error handling predictable" is a strength.
- Anticipated weaknesses are the Defense's independent assessment of what would be attacked — since it doesn't see the Prosecutor's charges, it must think adversarially on its own to prepare rebuttals.

## 2.7 Judge Verdict Format

The Judge receives both briefs and produces:

```json
{
  "verdict": [
    {
      "charge_id": "P-001",
      "ruling": "sustained | partially_sustained | dismissed | insufficient_evidence",
      "defense_match": "AW-001 or null if Defense didn't anticipate this charge",
      "reasoning": "Defense correctly notes the 100K constraint, but the spec never enforces this limit at the application layer. A sustained charge reduced to major — the gap exists but is bounded by stated requirements.",
      "final_severity": "critical | major | minor | nit",
      "recommendation": "Add application-layer row count guard and document the pagination strategy's scaling boundary explicitly"
    }
  ],
  "undefended_strengths": [
    {
      "strength_id": "D-002",
      "note": "The Defense's point about comprehensive error handling stands — Prosecutor did not challenge this"
    }
  ],
  "unchallenged_charges": [
    {
      "charge_id": "P-005",
      "note": "Defense did not anticipate the missing rate limiting concern. Charge sustained at original severity."
    }
  ],
  "summary": {
    "total_charges": 12,
    "sustained": 3,
    "partially_sustained": 4,
    "dismissed": 3,
    "insufficient_evidence": 2,
    "headline": "Solid design with three real gaps: pagination scaling, error recovery in the batch processor, and missing rate limiting on the public API.",
    "overall_quality": "strong | adequate | weak | fundamentally_flawed"
  }
}
```

**Ruling definitions:**
- **Sustained** — The charge is valid and the Defense either didn't anticipate it or conceded fully. The issue exists as charged.
- **Partially sustained** — The charge has merit but the Defense successfully bounded or contextualized it. Final severity may be reduced from what the Prosecutor claimed.
- **Dismissed** — The Defense successfully rebutted the charge, or the Judge found the Prosecutor's evidence insufficient. The issue is not real.
- **Insufficient evidence** — Neither the Prosecutor nor Defense made a compelling case. The Judge cannot rule. This flags the topic for human attention.

## 2.8 Command Interface

**Command:** `/arcis:roast`

**Usage:**
```
/arcis:roast <paste text or describe what to roast>
/arcis:roast --file path/to/artifact.md
/arcis:roast --url https://example.com/doc
/arcis:roast --severity major
/arcis:roast --focus security
/arcis:roast --compare path/to/reference.md
```

**Arguments:**

| Flag | Purpose | Default |
|------|---------|---------|
| `--file <path>` | Roast a specific file or directory | None (reads from stdin/message) |
| `--url <url>` | Fetch and roast web content | None |
| `--severity <level>` | Filter verdict output: `critical`, `major`, `minor`, `nit`. Only shows findings at or above this level | Show all |
| `--focus <category>` | Bias the Prosecutor toward a specific category: `logic`, `evidence`, `security`, `feasibility`, `completeness`, `consistency` | No bias |
| `--compare <path>` | Roast artifact A (primary) against artifact B (reference). Checks: does A deliver what B promises? | None |

**Auto-trigger heuristic:** Triggers when the user says "roast", "critique", "tear apart", "find problems with", "what's wrong with", "poke holes in", "devil's advocate." Does NOT trigger for normal code review requests.

### The `--compare` Flag

The power feature. Enables cross-artifact analysis:
- Roast an implementation against its design spec
- Roast a plan against its requirements
- Roast a research report against the original question
- Roast a PR against the issue it claims to fix

When `--compare` is used, the Prosecutor specifically checks: does the primary artifact actually fulfill the promises/requirements of the reference artifact? Missing requirements become charges. The Defense can argue that deviations were justified.

## 2.9 Final Report Structure

The Director renders the Judge's verdict into a readable report:

```markdown
# Roast Report: [Artifact Name]

**Artifact type:** design-spec
**Source:** docs/superpowers/specs/feature-design.md
**Overall quality:** adequate

## Headline
Solid design with three real gaps: pagination scaling, error recovery
in the batch processor, and missing rate limiting on the public API.

## Scorecard
| | Count |
|--|-------|
| Charges filed | 12 |
| Sustained | 3 |
| Partially sustained | 4 |
| Dismissed | 3 |
| Insufficient evidence | 2 |

## Sustained Charges (action required)

### 🔴 P-003 [Critical] Missing rate limiting on public API
**Category:** security
**Location:** Section 5.1
**Charge:** [...]
**Defense:** Not anticipated
**Ruling:** Sustained — no rate limiting on a public-facing API is a security risk
**Recommendation:** [...]

### 🟠 P-001 [Major] Pagination scaling gap
[...]

## Partially Sustained (bounded concerns)
[...]

## Dismissed (considered but not real issues)
[...]

## Strengths (what's working well)
[...]
```

## 2.10 Model Tiering

| Role | Model | Rationale |
|------|-------|-----------|
| Roast Director | opus | Orchestration, artifact detection, report formatting |
| Roast Prosecutor | opus | Adversarial analysis requires strong reasoning |
| Roast Defense | opus | Steelmanning requires deep understanding |
| Roast Judge | opus | Weighing arguments requires strongest judgment |

No sonnet tier. Critique quality is the entire value proposition.

## 2.11 File Structure

```
skills/roast-me/
├── SKILL.md                    # Skill metadata, auto-trigger config
├── commands/
│   └── roast.md                # Director orchestrator (command file)
└── agents/
    ├── roast-prosecutor.md     # Adversarial critic
    ├── roast-defense.md        # Steelman advocate
    └── roast-judge.md          # Arbiter
```

No references directory needed — roast-me is simpler than research-team. The artifact detection logic and severity calibration live in the Director command file.

## 2.12 Shared Infrastructure Usage

- **findings-schema.md** — Used to detect ARCIS research output as an artifact type. If the input conforms to findings schema, the Prosecutor and Defense know to evaluate it as structured research (checking evidence quality, confidence calibration, source coverage).
- **icd203-confidence-calibration.md** — When roasting research output, both agents check whether confidence levels are properly calibrated per the ICD 203 scale.
- **source-quality-rubric.md** — When roasting research output, both agents can evaluate whether sources meet quality thresholds.
- **agent-conventions.md** — All roast-me agents follow the 5-section prompt structure and naming conventions.

---

# Part 3: Cross-Skill Integration

## 3.1 ARCIS Skill Interaction Matrix

The three ARCIS skills can be composed:

| Composition | How It Works |
|-------------|-------------|
| research-team → roast-me | Research produces findings. User roasts the findings to check evidence quality and find gaps. Natural quality gate before acting on research. |
| roast-me → research-team | Roast identifies knowledge gaps. User dispatches research-team to fill them. Critique-driven research refinement. |
| research-team → coding-team | Research informs implementation. coding-team's Planner reads research findings to understand requirements and constraints. |
| roast-me → coding-team | Roast a design spec, fix the issues, then build it. Quality gate before expensive implementation. |
| coding-team → roast-me | Build something, then roast the implementation against the spec via `--compare`. Post-implementation validation. |

## 3.2 Updated Plugin Structure

```
arcis/
├── .claude-plugin/
│   └── plugin.json
├── .mcp.json
├── docs/
│   ├── agent-conventions.md
│   └── superpowers/
│       ├── specs/
│       │   ├── 2026-04-22-arcis-research-team-design.md
│       │   └── 2026-04-23-arcis-coding-team-roast-me-design.md
│       └── plans/
│           └── 2026-04-22-arcis-research-team.md
├── server/
│   └── research_mcp_server.py
├── shared/
│   ├── schemas/
│   │   ├── findings-schema.md
│   │   └── completeness-reporting.md
│   ├── references/
│   │   ├── icd203-confidence-calibration.md
│   │   └── source-quality-rubric.md
│   └── examples/
│       └── sample-findings-output.md
└── skills/
    ├── research-team/           # ✅ Implemented
    │   ├── SKILL.md
    │   ├── commands/
    │   │   └── research.md
    │   ├── agents/
    │   │   ├── research-classifier.md
    │   │   ├── domain-lead.md
    │   │   ├── specialist.md
    │   │   └── cross-domain-analyst.md
    │   └── references/
    │       ├── classification-blocklist.md
    │       ├── complexity-calibration.md
    │       └── domain-presets/
    │           └── (13 preset files)
    ├── coding-team/             # 🔨 This spec
    │   ├── SKILL.md
    │   ├── commands/
    │   │   └── code.md
    │   ├── agents/
    │   │   ├── coding-planner.md
    │   │   ├── coding-developer.md
    │   │   ├── coding-qa-reviewer.md
    │   │   ├── coding-security-reviewer.md
    │   │   ├── coding-performance-reviewer.md
    │   │   ├── coding-documentarian.md
    │   │   └── coding-integrator.md
    │   ├── references/
    │   │   └── anti-fallacy-playbook.md
    │   └── dashboard/
    │       └── index.html
    └── roast-me/                # 🔨 This spec
        ├── SKILL.md
        ├── commands/
        │   └── roast.md
        └── agents/
            ├── roast-prosecutor.md
            ├── roast-defense.md
            └── roast-judge.md
```

## 3.3 Naming Convention Compliance

Per `docs/agent-conventions.md`, all agent files follow the `<skill>-<role>.md` pattern:

| Skill | Agent Files |
|-------|-------------|
| research-team | `research-classifier.md`, `domain-lead.md`, `specialist.md`, `cross-domain-analyst.md` |
| coding-team | `coding-planner.md`, `coding-developer.md`, `coding-qa-reviewer.md`, `coding-security-reviewer.md`, `coding-performance-reviewer.md`, `coding-documentarian.md`, `coding-integrator.md` |
| roast-me | `roast-prosecutor.md`, `roast-defense.md`, `roast-judge.md` |
