# Arcis #108 Specialized Agents — Implementation Plan

**Spec:** [`docs/audits/2026-05-25-specialized-agents/specs/2026-05-25-specialized-agents-design.md`](../specs/2026-05-25-specialized-agents-design.md)
**Target release:** Docs-only PR — NO version bump (auto-discovery; no plugin.json change)
**Estimated effort:** ~0.5 day agent work + dual-Opus QA
**Tasks:** 6 across 5 execution batches
**The 4 agents are first-in-class consumers of #105 + #106 tools; substrate for #109 + #110 + #111.**

---

## Implementation Discipline (read first)

Task 1 (conventions doc) gates Tasks 2 + 3 because the agent prompts cite the new §Cross-cutting-conventions appendix headers. Tasks 2 + 3 run in parallel (independent agent files, no shared edits). Task 4 (goldens) depends on the agent files for shape reference. Task 5 (CHANGELOG) depends on having all files in their final form. Task 6 (smoke-test + lint) is the closing-gate verification: enforces DA1-DA6 compliance via grep-assertions and confirms auto-discovery works. Total: ~0.5 day implementation + 0.5 day dual-Opus QA per operator's coding-team dual-QA merge-gate. NO version bump anywhere. NO src/ code changes.

---

## Execution Order

**Batch 1:** Task 1

**Batch 2:** Task 2, Task 3

**Batch 3:** Task 4

**Batch 4:** Task 5

**Batch 5:** Task 6

---

## Tasks

### Task 1 — Extend agent-conventions.md with §Naming + §maxTurns + §Bash-subprocess + §5 OUTPUT FORMAT + §Cross-cutting-conventions addenda

**Estimated complexity:** low

**Files in scope:**
- `.claude/plugins/arcis/docs/agent-conventions.md`

**Files (read-only context):**
- `.claude/plugins/arcis/docs/findings-schema.md`
- `.claude/plugins/arcis/agents/coding-rigor-reviewer.md`
- `src/tools/_cli_envelope.py`
- `src/tools/prcomments/__main__.py`

**Description:**

Append to .claude/plugins/arcis/docs/agent-conventions.md (DO NOT rewrite existing sections): (a) §Naming addendum formalizing the investigator-class bare-name exception (DD-1); (b) §maxTurns addendum noting the investigator-class = 60 with turn-50 budget-stop precedent (DD-2, DD-17); (c) §Bash-subprocess Tool Invocation appendix encoding the canonical `cd "$(git rev-parse --show-toplevel)" && python -m src.tools.X --json` pattern, the mandatory explicit per-call timeout rule (DA2 tiered 60/90/120s defaults), the `--json` mandatory flag, the JSON envelope parsing contract referencing `cli_envelope()` in src/tools/_cli_envelope.py, the exit-code handling discipline (0/1/non-1-non-0/timeout_exceeded), the §2.3.1 single-quote shell-quoting convention for embedded SQL/regex payloads, and the §2.3.2 stdin-pipe pattern (`cat <<'EOF' | ... --body-file -`) for body-content delivery without temp files; (d) §5 OUTPUT FORMAT addendum registering the investigator-class custom-tag enum {db_report, ci_report, git_report, live_report} as documented divergence + mandating `coverage_assessment` as a required field on every investigator-class JSON payload (DD-11, DA6); (e) §Cross-cutting-conventions appendix documenting DA1 worktree-portable cwd + optional WORKTREE_PATH override (DD-12), DA3 empty-result-as-informational classification (DD-14), DA4 fingerprint-footer convention for repost-idempotent posters (DD-15), and DA5 JSONB/TEXT 200-char truncation rule (DD-16). Verify with grep-assertion that all 6 new section headers appear in the post-edit file.

**Test strategy:**

Grep the modified conventions doc for the 6 new section headers (§Naming addendum, §maxTurns addendum, §Bash-subprocess Tool Invocation, §5 OUTPUT FORMAT registered enum, §Cross-cutting-conventions, DA1/DA2/DA3/DA5/DA6 keywords). Visual diff review against the spec §2.3.0 + §2.6. Confirm no edits to pre-existing sections (§5-Section Structure lines 7-104, §Frontmatter lines 109-129, §Naming lines 133-143).

**Scope fence:** Do NOT modify existing sections of agent-conventions.md (only APPEND new addenda + appendices). Do NOT create new agent files in this task. Do NOT modify CHANGELOG.md. Do NOT touch findings-schema.md.

---

### Task 2 — Write db-investigator.md + ci-investigator.md agent prompts

**Depends on:** Task 1

**Estimated complexity:** medium

**Files in scope:**
- `.claude/plugins/arcis/agents/db-investigator.md`
- `.claude/plugins/arcis/agents/ci-investigator.md`

**Files (read-only context):**
- `.claude/plugins/arcis/docs/agent-conventions.md`
- `.claude/plugins/arcis/agents/coding-qa-reviewer.md`
- `.claude/plugins/arcis/agents/coding-security-reviewer.md`
- `.claude/plugins/arcis/agents/design-codebase-analyst.md`

**Description:**

Create .claude/plugins/arcis/agents/db-investigator.md and .claude/plugins/arcis/agents/ci-investigator.md following spec §3.1 and §3.2 verbatim. Each agent file contains the 5-section structure (EPISTEMIC LENS / TASK / CONSTRAINTS / DYNAMIC CONTEXT / OUTPUT FORMAT) per agent-conventions.md. Frontmatter: name + description + model: opus + maxTurns: 60 + allowed-tools (Read, Glob, Grep, Bash). Each agent's CONSTRAINTS mirrors the 6 cross-cutting bullets (DA1 worktree-portable cwd via `cd "$(git rev-parse --show-toplevel)"` with optional WORKTREE_PATH override, DA2 explicit per-call timeout 60/90/120s tiered, DA3 empty-result → informational, DA5 JSONB/TEXT truncate to 200 chars + `[truncated]` marker for `*_jsonb`/`*_detail`/`*_payload`/`*_body` patterns, DA6 turn-50 budget-stop with required `coverage_assessment` field, subprocess-discipline) + verbatim sibling-search prose from coding-qa-reviewer.md:58. ci-investigator's CONSTRAINTS additionally encodes TARGET-PR-SCOPING (no TARGET_PR → REFUSE post; never auto-discover PR; never post more than once per invocation) + REPOST-IDEMPOTENCY (DA4 SHA-256 fingerprint of head_sha + classification + first_200_chars_summary, 8-hex-prefix footer `<!-- [fingerprint:...] -->`, prcomments read pre-post scan, ALLOW_REPOST=false default, post_status enum: posted/skipped_duplicate/refused_no_target_pr/refused_envelope_error/not_attempted). ci-investigator's TASK Workflow step 10 implements the fingerprint pre-check + step 11 implements the stdin-pipe post pattern. Both agent files cap at 280 lines.

**Test strategy:**

Grep each agent file for: (i) literal `cd "$(git rev-parse --show-toplevel)"` (DA1 — MUST appear), (ii) literal `cd C:/arcis/halcyon-lab` (DA1 — MUST NOT appear), (iii) literal `timeout` per Bash invocation (DA2), (iv) literal `[truncated]` and `200` (DA5), (v) literal `coverage_assessment` in OUTPUT FORMAT section (DA6), (vi) literal `turn 50` or `turn-50` in Workflow (DA6), (vii) literal `informational` in CONSTRAINTS or Workflow (DA3). ci-investigator additionally: literal `fingerprint`, `ALLOW_REPOST`, `skipped_duplicate`, `existing_fingerprint` (DA4) AND literal stdin-pipe heredoc pattern `cat <<'EOF'` + `--body-file -` (§2.3.2). Visual review against spec §3.1 + §3.2. Line count ≤ 280 per file.

**Scope fence:** Do NOT create git-historian.md or live-monitor.md (those are Task 3). Do NOT modify agent-conventions.md (that was Task 1). Do NOT modify any source code in src/tools/. Do NOT modify CHANGELOG.md.

---

### Task 3 — Write git-historian.md + live-monitor.md agent prompts

**Depends on:** Task 1

**Estimated complexity:** medium

**Files in scope:**
- `.claude/plugins/arcis/agents/git-historian.md`
- `.claude/plugins/arcis/agents/live-monitor.md`

**Files (read-only context):**
- `.claude/plugins/arcis/docs/agent-conventions.md`
- `.claude/plugins/arcis/agents/coding-qa-reviewer.md`
- `.claude/plugins/arcis/agents/design-codebase-analyst.md`

**Description:**

Create .claude/plugins/arcis/agents/git-historian.md and .claude/plugins/arcis/agents/live-monitor.md following spec §3.3 and §3.4 verbatim. Same 5-section structure + same 6 cross-cutting bullets (DA1-DA6) + same verbatim sibling-search prose as Task 2. git-historian's CONSTRAINTS adds the enumerated forbidden git mutating ops (commit/push/reset/rebase/checkout--/branch -D/clean -f/stash drop/tag -d/cherry-pick/revert/bisect run) — allowed git ops list: log/blame/show/diff/rev-parse/rev-list/merge-base/tag/remote -v. live-monitor's CONSTRAINTS adds the enumerated forbidden ProcessManager methods (restart/start/stop) with only allowed verb being `status` AND the Workflow Step 0 ET clock capture (TZ='America/New_York' date) populating snapshot_timestamp AND the overnight-window 21:30-22:30 ET restart-recommendation-forbidden rule. Both agent files cap at 280 lines.

**Test strategy:**

Same DA1-DA6 grep-asserts as Task 2 applied to both files. git-historian additionally: literal `FORBIDDEN` and each forbidden git op name. live-monitor additionally: literal `Step 0` and `TZ='America/New_York'` and `snapshot_timestamp` and `21:30` and `22:30` and enumerated FORBIDDEN ProcessManager methods (restart/start/stop). Visual review against spec §3.3 + §3.4. Line count ≤ 280 per file.

**Scope fence:** Do NOT create db-investigator.md or ci-investigator.md (those are Task 2). Do NOT modify agent-conventions.md (that was Task 1). Do NOT modify any source code in src/tools/. Do NOT modify CHANGELOG.md.

---

### Task 4 — Write 4 golden-question reference files

**Depends on:** Task 2, Task 3

**Estimated complexity:** low

**Files in scope:**
- `.claude/plugins/arcis/docs/agent-tests/db-investigator-golden.md`
- `.claude/plugins/arcis/docs/agent-tests/ci-investigator-golden.md`
- `.claude/plugins/arcis/docs/agent-tests/git-historian-golden.md`
- `.claude/plugins/arcis/docs/agent-tests/live-monitor-golden.md`

**Files (read-only context):**
- `.claude/plugins/arcis/agents/db-investigator.md`
- `.claude/plugins/arcis/agents/ci-investigator.md`
- `.claude/plugins/arcis/agents/git-historian.md`
- `.claude/plugins/arcis/agents/live-monitor.md`

**Description:**

Create .claude/plugins/arcis/docs/agent-tests/ directory and the 4 golden-question markdown reference files per spec §6: db-investigator-golden.md (5 questions per §6.1), ci-investigator-golden.md (5 questions per §6.2 — INCLUDING the DA4 repost-refusal case as golden #5), git-historian-golden.md (4 questions per §6.3), live-monitor-golden.md (5 questions per §6.4 — INCLUDING the DA5 truncation verifier and the overnight-window question). Each golden file follows the §6.5 format: question prose + expected DYNAMIC CONTEXT shape (MANDATE + any required fields, with WORKTREE_PATH opt-in per DA1 noted + ALLOW_REPOST opt-in per DA4 for ci-investigator) + expected response shape (JSON fields populated, citation density, coverage_assessment present per DA6) + negative checks (no mutations, no posting without TARGET_PR, no restart during overnight, no hardcoded cwd, mandatory per-call timeouts, empty results surface as informational, JSONB truncation applied).

**Test strategy:**

Grep each golden file for: question count match spec, mention of expected JSON fields (coverage_assessment for all 4, post_status + fingerprint + existing_fingerprint for ci-investigator-golden, snapshot_timestamp for live-monitor-golden), negative-check section. Visual review against spec §6.1-§6.5.

**Scope fence:** Do NOT modify the agent .md files (Tasks 2 + 3). Do NOT modify agent-conventions.md (Task 1). Do NOT create runtime test scaffolding — these are reference markdown only.

---

### Task 5 — Add CHANGELOG [Unreleased] entry (no version bump)

**Depends on:** Task 2, Task 3, Task 4

**Estimated complexity:** low

**Files in scope:**
- `CHANGELOG.md`

**Description:**

Edit CHANGELOG.md to add the [Unreleased] entry per spec §8 (Added — #108 specialized investigator agents (no version bump; docs-only)). Lists the 4 agents with file paths + one-line capability summary; the 4 golden-question files; the agent-conventions.md addenda (§Naming, §maxTurns, §Bash-subprocess, §5 OUTPUT FORMAT, §Cross-cutting-conventions); explicit mention of: DA1 worktree-portable cwd + DA2 mandatory per-call timeout + DA3 empty-result-as-informational + DA4 ci-investigator repost-idempotency via SHA-256 fingerprint footer + DA5 JSONB/TEXT 200-char truncation + DA6 turn-50 budget-stop + mandatory coverage_assessment field; first-time encoding of `feedback_complete_efforts_no_deferral` memory directly in agent prompts. NO version bump. Confirm no version field changes anywhere (no pyproject.toml edit, no plugin.json edit).

**Test strategy:**

Grep CHANGELOG.md for: '[Unreleased]', '#108', each of the 4 agent names, 'no version bump', 'DA1', 'DA2', 'DA3', 'DA4', 'DA5', 'DA6', 'feedback_complete_efforts_no_deferral'. Verify pyproject.toml + plugin.json files NOT modified (`git diff --name-only` should show only CHANGELOG.md among version-relevant files).

**Scope fence:** Do NOT bump any version number anywhere. Do NOT touch pyproject.toml, plugin.json, or any release manifest. Do NOT modify the agent files or conventions doc.

---

### Task 6 — Smoke-test + lint compliance grep-assertions

**Depends on:** Task 1, Task 2, Task 3, Task 4, Task 5

**Estimated complexity:** low

**Files (read-only context):**
- `.claude/plugins/arcis/agents/db-investigator.md`
- `.claude/plugins/arcis/agents/ci-investigator.md`
- `.claude/plugins/arcis/agents/git-historian.md`
- `.claude/plugins/arcis/agents/live-monitor.md`
- `.claude/plugins/arcis/docs/agent-conventions.md`
- `.claude/plugins/arcis/docs/agent-tests/db-investigator-golden.md`
- `.claude/plugins/arcis/docs/agent-tests/ci-investigator-golden.md`
- `.claude/plugins/arcis/docs/agent-tests/git-historian-golden.md`
- `.claude/plugins/arcis/docs/agent-tests/live-monitor-golden.md`
- `CHANGELOG.md`

**Description:**

Smoke-test pass: (a) Visual diff review of all 9 new + 2 modified files vs spec §2-§8. (b) Grep-lint assertions on the 4 agent files: NO occurrence of literal `cd C:/arcis/halcyon-lab` (DA1 regression guard); EVERY Bash invocation carries an explicit `timeout` parameter (DA2 — grep for `python -m src.tools` lines and verify each has timeout); EVERY agent CONSTRAINTS section contains literal `[truncated]` and `200` (DA5); EVERY agent OUTPUT FORMAT section contains literal `coverage_assessment` (DA6); EVERY agent Workflow contains literal `turn 50` or `turn-50` (DA6); EVERY agent CONSTRAINTS or Workflow contains literal `informational` (DA3). (c) ci-investigator additionally: literal `fingerprint`, `ALLOW_REPOST`, `skipped_duplicate`, `existing_fingerprint` (DA4) + literal heredoc pattern `cat <<'EOF'` + `--body-file -` (§2.3.2). (d) live-monitor additionally: literal `Step 0`, `TZ='America/New_York'`, `snapshot_timestamp`, `21:30`, `22:30`. (e) git-historian additionally: literal `FORBIDDEN` git ops list. (f) Each agent file line count ≤ 280. (g) Auto-discovery sanity check: dispatch Task tool with `subagent_type='db-investigator'` and a no-op MANDATA ("return empty <db_report>") — confirm the agent is invocable (smoke-test only, not a full golden run). (h) Verify NO src/ code changes (`git diff --name-only src/` should be empty). NO test execution required — this is a docs-only PR.

**Test strategy:**

Each grep-assertion above is a discrete pass/fail check. Auto-discovery smoke-test = single Task dispatch returning a structurally-valid <db_report> JSON (content correctness is NOT scored here; only that the agent file parses + frontmatter loads + maxTurns honored). NO pytest run, NO source-code modification, NO version-relevant file modification.

**Scope fence:** Do NOT modify any files. Do NOT fix bugs discovered during smoke-test — surface findings to the operator for a follow-up task. Do NOT run pytest or any source-test suite. Do NOT dispatch full golden-question runs (that is #111's scope).

---

