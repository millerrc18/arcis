# Implementation Plan — arcis:periodic-discipline

**Spec:** [spec.md](./spec.md)
**Issue:** #111
**Target version:** v0.36.6X (next minor at impl time)
**Total tasks:** 4 (strictly sequential)
**Total new files:** ~10 (zero `src/tools/` additions)
**Estimated effort:** 6–9h
**Consumer:** `/arcis:code --spec docs/audits/2026-05-26-arcis-periodic-discipline/spec.md --plan docs/audits/2026-05-26-arcis-periodic-discipline/plan.md`

## Execution order

```
[[Task 1]] → [[Task 2]] → [[Task 3]] → [[Task 4]]
```

Strictly sequential. Each task consumes the artifact of the prior one. Task 1 establishes contract docs that Tasks 2–4 reference; Task 2 produces runbooks the CI workflow in Task 3 must mirror; Task 4 tests the whole stack and would fail without 1–3 in place.

## File structure (created by this plan)

```
.claude/plugins/arcis/skills/periodic-discipline/   # NEW skill dir
├── SKILL.md                                        # Task 1
├── audits/
│   ├── audit-skills.md                             # Task 2
│   ├── curate-memory.md                            # Task 2
│   ├── test-tools.md                               # Task 2
│   └── full.md                                     # Task 3
├── references/
│   ├── scanners.md                                 # Task 1
│   ├── findings-schema.md                          # Task 1
│   └── lockfile.md                                 # Task 1
└── allowlist.yaml                                  # Task 2

.github/workflows/
└── periodic-discipline.yml                         # Task 3 (NEW)

data/periodic-discipline/
└── reports/.gitkeep                                # Task 4

tests/
├── skills/test_periodic_discipline.py              # Task 4 (NEW)
└── tools/test_periodic_discipline_boundary.py      # Task 4 (NEW)

.gitignore                                          # Task 4 (modified — adds data/periodic-discipline/.lock + reports/*.json)
```

**ZERO additions under `src/tools/`** — operator constraint per spec §1.2 and DD11.

---

## Task 1 — Scaffold skill (SKILL.md + reference docs)

**Complexity:** low (1h)

**Description:** Create the skill entry point and three reference documents. SKILL.md has frontmatter (name, description), describes the four verbs, and routes to `audits/<verb>.md`. `references/scanners.md` catalogs each scanner's intent, implementation strategy (bash/python-oneliner/agent dispatch), and false-positive guidance. `references/findings-schema.md` documents the JSON finding shape, `root_cause_key` contract, dedup rule, allowlist semantics, and opt-in (no auto-decay) policy. `references/lockfile.md` documents the PID-lockfile contract, invocation_id format (`PD-<verb>-<8char>`), `ARCIS_SESSION_ID` propagation, and report rotation policy (30d).

**Files in scope (created):**
- `.claude/plugins/arcis/skills/periodic-discipline/SKILL.md`
- `.claude/plugins/arcis/skills/periodic-discipline/references/scanners.md`
- `.claude/plugins/arcis/skills/periodic-discipline/references/findings-schema.md`
- `.claude/plugins/arcis/skills/periodic-discipline/references/lockfile.md`

**Files read-only:**
- `.claude/plugins/arcis/commands/operate.md` (842-line precedent for runbook composition pattern)
- `.claude/plugins/arcis/agents/research-cross-domain-analyst.md` (referenced by LLM contradiction scanner)
- `src/tools/docconsistency/__main__.py` (composed by file_line_drift scanner)

**Test strategy:** Smoke — each file parses as valid markdown; SKILL.md frontmatter is valid YAML with required keys (`name`, `description`). No runtime test at this layer — covered by Task 4.

**Scope fence:**
- Do NOT create `audits/*.md` (Task 2)
- Do NOT create `allowlist.yaml` (Task 2)
- Do NOT add anything under `src/tools/` — this is the operator-explicit constraint
- Do NOT create CI workflow (Task 3)
- Do NOT write tests (Task 4)

**Depends on:** none

---

## Task 2 — Audit runbooks (audit-skills, curate-memory, test-tools) + allowlist seed

**Complexity:** medium (3–4h)

**Description:** Create the three per-verb runbooks. Each follows the runbook skeleton from spec §2.3: preamble (lockfile + invocation_id), scanner blocks (each a fenced bash + `python -c` / `jq` one-liner that composes existing tools per spec §3), postamble (dedup + allowlist filter + rotation).

- **`audits/audit-skills.md`** contains 5 scanners:
  - `file_line_drift` — invokes `python -m src.tools.docconsistency --json`
  - `subagent_unresolved` — grep + frontmatter-resolver `python -c` (NOT special-casing the 3 historical name mismatches; the resolver finds them generically)
  - `tool_module_missing` — grep + `test -d src/tools/<name>`
  - `workflow_parity` — `python -c` diff of CI workflow inline-bash vs `audits/<verb>.md` fenced blocks (normalized)
  - `llm_contradiction` — dispatches `Agent(subagent_type="research-cross-domain-analyst")`, findings carry `advisory: true`
- **`audits/curate-memory.md`** contains 3 scanners:
  - `duplicate_root_cause_key` — `awk` + `sort` + `uniq -c`
  - `stale_entry` — `find memory -name '*.md' -mtime +90` minus allowlist (opt-in; no auto-decay)
  - `memory_contradiction` — `research-cross-domain-analyst` agent, `advisory: true`
- **`audits/test-tools.md`** contains 2 scanners:
  - `cli_decorator_chain` — invokes `python -m src.tools.<name> --help` with `ARCIS_SESSION_ID`, tails `tool-execution.log` via `jq`, asserts decorator chain
  - `boundary_test_missing` — `find src/tools` + `test -f tests/tools/test_<tool>_boundary.py`
- **`allowlist.yaml`** ships with 1–2 seed entries with inline rationale comments

**Files in scope (created):**
- `.claude/plugins/arcis/skills/periodic-discipline/audits/audit-skills.md`
- `.claude/plugins/arcis/skills/periodic-discipline/audits/curate-memory.md`
- `.claude/plugins/arcis/skills/periodic-discipline/audits/test-tools.md`
- `.claude/plugins/arcis/skills/periodic-discipline/allowlist.yaml`

**Files read-only:**
- `.claude/plugins/arcis/skills/periodic-discipline/SKILL.md` (Task 1 output)
- `.claude/plugins/arcis/skills/periodic-discipline/references/scanners.md`
- `.claude/plugins/arcis/skills/periodic-discipline/references/findings-schema.md`
- `src/tools/docconsistency/__main__.py`

**Test strategy:** Manual dry-run — for each runbook, extract fenced bash blocks and execute against a fixture skill/memory/tool tree under `/tmp`; assert JSON report conforms to schema and lockfile cleans up. Automated tests come in Task 4.

**Scope fence:**
- Do NOT add helper scripts under `src/tools/` — every scanner MUST be inline
- Do NOT modify `docconsistency` or any existing tool
- Do NOT modify `tool-execution.log` schema
- Do NOT touch agent definitions
- Do NOT create `audits/full.md` (Task 3)
- If a scanner feels too complex for a one-liner block, restructure the scanner — do NOT extract it to a Python module
- Do NOT special-case the 3 historical agent-name mismatches — the resolver finds them via frontmatter parse

**Depends on:** Task 1

---

## Task 3 — Orchestrator runbook + CI workflow

**Complexity:** medium (1–2h)

**Description:** Create `audits/full.md` — sequential invocation of `audit-skills`, `curate-memory`, `test-tools` with a single combined invocation_id (`PD-full-<id>`). Create `.github/workflows/periodic-discipline.yml` with two cron triggers (Mon/Thu 07:00 UTC) and workflow_dispatch with verb choice. The workflow's `run:` step inline-bash is a FAITHFUL COPY of the corresponding `audits/<verb>.md` fenced blocks (the workflow_parity scanner in Task 2 detects drift between the two).

Workflow honors `feedback_audit_workflow_constraints.md` verbatim:
- `permissions: contents: read` only
- NO blanket `continue-on-error: true`
- Uploads `reports/` as artifact on every run
- Job goes RED only on crash; findings surface via artifact + `$GITHUB_STEP_SUMMARY`

**Files in scope (created):**
- `.claude/plugins/arcis/skills/periodic-discipline/audits/full.md`
- `.github/workflows/periodic-discipline.yml`

**Files read-only:**
- `.claude/plugins/arcis/skills/periodic-discipline/audits/audit-skills.md`
- `.claude/plugins/arcis/skills/periodic-discipline/audits/curate-memory.md`
- `.claude/plugins/arcis/skills/periodic-discipline/audits/test-tools.md`

**Test strategy:**
- Manual: trigger `workflow_dispatch` on a feature branch with each verb; assert artifact contains valid JSON
- Assert no permissions warnings
- Run `workflow_parity` scanner manually after creation — must report zero drift initially

**Scope fence:**
- Do NOT add jobs beyond the single `run` job
- Do NOT add notification steps (Slack/email) — out of scope
- Do NOT add write permissions to `GITHUB_TOKEN`
- Do NOT add cargo-cult `continue-on-error`
- Do NOT extract the inline bash into a helper script under `.github/scripts/` — that's a tool-by-another-name; the workflow_parity scanner is what prevents drift, not extraction

**Depends on:** Task 2

---

## Task 4 — Tests + data directory bootstrap

**Complexity:** medium (1–2h)

**Description:** Create `tests/skills/test_periodic_discipline.py` covering 8 test scenarios (see spec §10.1):
1. `SKILL.md` + each `audits/<verb>.md` frontmatter parses as valid YAML
2. Each scanner produces schema-conformant JSON against fixture tree
3. Lockfile contention exits 1
4. `ARCIS_SESSION_ID` propagates to `tool-execution.log`
5. Allowlist filtering excludes matched keys
6. `root_cause_key` dedup collapses duplicates
7. `workflow_parity` detects deliberate drift
8. 30d report rotation works

Create `tests/tools/test_periodic_discipline_boundary.py` — for each Tier-1/Tier-2 tool in `src/tools/`, subprocess-invoke `python -m src.tools.<name> --help` with session id set and assert decorator chain in audit log.

Create `data/periodic-discipline/reports/.gitkeep` and add `data/periodic-discipline/.lock` + `data/periodic-discipline/reports/*.json` to `.gitignore`.

**Files in scope (created/modified):**
- `tests/skills/test_periodic_discipline.py` (new)
- `tests/tools/test_periodic_discipline_boundary.py` (new)
- `data/periodic-discipline/reports/.gitkeep` (new)
- `.gitignore` (modified — add the two new gitignore patterns)

**Files read-only:**
- `.claude/plugins/arcis/skills/periodic-discipline/SKILL.md`
- `.claude/plugins/arcis/skills/periodic-discipline/audits/audit-skills.md`
- `.claude/plugins/arcis/skills/periodic-discipline/audits/curate-memory.md`
- `.claude/plugins/arcis/skills/periodic-discipline/audits/test-tools.md`
- `.github/workflows/periodic-discipline.yml`
- `tests/tools/test_docconsistency_integration.py` (existing test pattern reference)

**Test strategy:**
- Run `pytest tests/skills/test_periodic_discipline.py tests/tools/test_periodic_discipline_boundary.py -v`
- All 8 skill tests + N boundary tests (one per Tier-1/Tier-2 tool) must pass
- **Vacuous-test discipline** (per `feedback_vacuous_test_pattern.md`): tests must be able to FAIL — verify by temporarily breaking a runbook fence (drop a scanner block, run workflow_parity test, confirm RED) before approving. Tests that mock `subprocess.run` without actually exercising the runbook are theater.

**Scope fence:**
- Do NOT add a Python module under `src/tools/periodic_discipline/` as a "test helper" — operator constraint is no new tools
- Test fixtures live inside the test file or under `tests/fixtures/periodic_discipline/`
- Do NOT modify existing tool tests
- Do NOT add `data/periodic-discipline/archive/.gitkeep` in this task — archive directory created lazily by future operator action
- Do NOT add notification logic to the boundary test (out of scope)

**Depends on:** Task 3

---

## Merge gate (operator's standard)

Per `feedback_use_coding_team_skill.md`:
- `/arcis:code` PM-orchestrator dispatches (NOT direct coding-developer dispatches)
- **Dual-Opus QA** on merge: 2 independent Opus QA reviews (root-cause / hardening / ripple / noise, 100% confidence)
- All tests passing (5388 floor enforced by CI)
- Verify-can-fail discipline applied to every new test (per `feedback_vacuous_test_pattern.md`)

## Review summary (this design)

| Phase | Verdict | Notes |
|-------|---------|-------|
| Feasibility | PASS (after path correction) | 1 major fix: task 2's `files_read_only` corrected from missing `skills/operate/commands/operate.md` to actual `.claude/plugins/arcis/commands/operate.md` |
| Devil's Advocate (pass 1) | CONCERNS | 6 major: workflow-parity gap, mtime-decay false-positives, dedup unspecified, scanner ambiguity, audit-log race, plan thinness. ALL ADDRESSED in revision. |
| Scope check | CRITICAL CATCH | Pass 2 silently introduced new `src/tools/periodic_discipline/` Python tool — violated operator's explicit markdown-only constraint. Revision 3 corrected by embedding all scanner logic in `audits/<verb>.md` runbook fences. DD11 documents the constraint-honoring decision. |
| Devil's Advocate strengths | 5 cited | Self-exclusion contract; well-justified DD table; honoring audit-workflow-constraints; detection-only conservatism; composition over reinvention |

## Notes for `/arcis:code` consumer

- Strict linear order: Tasks 1 → 2 → 3 → 4
- Total: 4 tasks, **ZERO additions under `src/tools/`**
- All scanner logic embedded in `audits/<verb>.md` per operator markdown-only constraint
- The `workflow_parity` scanner (audit-skills #4, critical severity) is the load-bearing mechanism that makes the deliberate duplication between CI workflow inline-bash and runbook fences safe — drift becomes a finding, not a silent divergence
- Estimated total effort: 6–9h (Task 1: 1h, Task 2: 3–4h, Task 3: 1–2h, Task 4: 1–2h)
