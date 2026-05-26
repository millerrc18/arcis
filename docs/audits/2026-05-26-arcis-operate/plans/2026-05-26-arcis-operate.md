# Arcis #109 — `arcis:operate` Skill Implementation Plan

**Spec:** [`docs/audits/2026-05-26-arcis-operate/specs/2026-05-26-arcis-operate-design.md`](../specs/2026-05-26-arcis-operate-design.md)
**Target release:** v0.36.6X (re-baseline at impl time; current main is v0.36.64)
**Estimated effort:** ~1 day agent work + dual-Opus QA
**Tasks:** 10 across 3 execution waves
**Scope:** 1 skill PR — SKILL.md + commands/operate.md + 5 runbooks + 2 references + CHANGELOG

---

## Implementation Discipline (read first)

IMPLEMENTATION DISCIPLINE PREAMBLE:

1. **Sibling-search rule** (memory: feedback_review_sibling_search). When reviewing one runbook for a convention, GREP the other 4 runbooks for the same pattern. All 5 must handle 'tool not yet shipped' warnings consistently, all 5 must use the same memory-citation format, all 5 must use the same step-block shape, all mutating runbooks (5.1 + 5.4) must include Abandonment recovery section per DA9.

2. **Verify-by-mutation** (memory: feedback_strict_rigor_no_handwave). T10's PR description MUST include evidence for all 24 spec §12 checklist items (14 base + 10a-10j DA-fix items).

3. **No out-of-scope deferral** (memory: feedback_complete_efforts_no_deferral). If during impl the PM discovers an adjacent defect, surface in PR description. The _execution_log_writer CLI entry point (DA3 mitigation per §14 OQ#7) is IN-SCOPE for #109 — a ~6-line addition to src/tools/_execution_log.py. Surface the diff.

4. **Dual-Opus QA merge gate** (memory: feedback_use_coding_team_skill). #109 is operator-experience capstone — merge requires TWO independent Opus QA reviews. Each must certify root-cause / hardening / ripple / noise / 100% confidence.

5. **Per-PR versioning.** Re-baseline at impl time. Current main: v0.36.64. Pick v0.36.6X.

6. **Worktree isolation** (memory: feedback_strict_rigor_no_handwave). Every developer worktree verifies isolation on first tool use via pwd + git rev-parse + git branch --show-current.

7. **Windows UTF-8 encoding** (memory: feedback_windows_utf8_encoding). Prefer Edit tool. If writing via Python, encoding='utf-8' explicit.

8. **DA12 wave structure — REVISED.** T1-T7 + T9 are parallel-safe (independent new files). T8 has read-only dependency on T3-T7 outputs (the 5 runbook files) and runs in wave 2 — this is so any action-row drop is clean (T8 builds the action set actually referenced by the 5 runbooks rather than guessing). T10 integration gate runs in wave 3 gated on all of T1-T9.

9. **Spec-as-deliverable-0.** Commit spec.md + plan.json + design_decisions.json to docs/audits/<sprint-id>/ BEFORE dispatching developers. PR includes the spec as its first commit for permanent provenance.

10. **§14 Open Questions resolution path:** During T1-T9, developers may surface that an OQ has impl-time-discoverable answer. They flag in their per-task PR commits. T10 resolves all OQs in the PR description before merge.

11. **AskUserQuestion budget enforcement.** T2's reviewer counts AskUserQuestion blocks per verb section: ≤3 per triage mandatory checkpoints, ≤2 per act mandatory. Conditional operator-initiated subprompts (modify-subprompt, show-runbook-first) are unbounded per DA4 clarification.

12. **No new agent files.** Skill INHERITS the 4 #108 agents. If #108 has not landed at #109 impl-time, BLOCK #109 on #108. Pre-impl verification: glob .claude/plugins/arcis/agents/{db-investigator,ci-investigator,git-historian,live-monitor}.md — all 4 must exist.

13. **DA-revision fixes applied to spec, plan, design_decisions per devils-advocate review 2026-05-26.** See spec Known Considerations section (DA11/DA13/DA15) + DD20 (DA14 operator override) + DD21 (DA-revision meta-decision).

---

## Execution Order

**Wave 1:** Task T1, Task T2, Task T3, Task T4, Task T5, Task T6, Task T7, Task T9

**Wave 2:** Task T8

**Wave 3:** Task T10

---

## Tasks

### Task T1 — Author SKILL.md descriptor

**Estimated complexity:** trivial

**Files in scope:**
- `.claude/plugins/arcis/skills/operate/SKILL.md`

**Files (read-only context):**
- `.claude/plugins/arcis/skills/coding-team/SKILL.md`
- `.claude/plugins/arcis/skills/design-team/SKILL.md`

**Description:**

Create .claude/plugins/arcis/skills/operate/SKILL.md verbatim per spec §2. User-facing skill descriptor with 2-field frontmatter (name + description), 8-step Approach section, Agent Hierarchy ASCII tree, Key Properties bullets, verbs/runbooks tables, Arguments table. NO DYNAMIC CONTEXT blocks (those live in commands/operate.md).

**Test strategy:**

Manual: load fresh Claude Code session, run /help-equivalent listing, confirm /arcis:operate appears with the description string from frontmatter. Verify Approach numbered list matches spec §2 exactly (8 steps). Verify Agent Hierarchy ASCII tree renders.

**Scope fence:** Do NOT modify commands/operate.md (T2). Do NOT create runbooks (T3-T7). Do NOT touch references/ files (T8-T9). Match coding-team/SKILL.md and design-team/SKILL.md section conventions (FA4, FA11) exactly — frontmatter is 2 fields only (name + description), no model/maxTurns at SKILL.md level. Bare name 'operate' NOT 'arcis-operate'.

---

### Task T2 — Author commands/operate.md orchestrator

**Estimated complexity:** complex

**Files in scope:**
- `.claude/plugins/arcis/commands/operate.md`

**Files (read-only context):**
- `.claude/plugins/arcis/commands/design.md`
- `.claude/plugins/arcis/commands/code.md`
- `.claude/plugins/arcis/commands/marketpulse.md`
- `config/arcis_config.yaml`
- `src/tools/_safety.py`
- `src/tools/_execution_log.py`
- `src/tools/processmanager/__main__.py`
- `.claude/plugins/arcis/agents/db-investigator.md`
- `.claude/plugins/arcis/agents/ci-investigator.md`
- `.claude/plugins/arcis/agents/git-historian.md`
- `.claude/plugins/arcis/agents/live-monitor.md`

**Description:**

Create .claude/plugins/arcis/commands/operate.md verbatim per spec §3 (post-DA revision). The executable orchestrator the LLM reads at slash-command invocation. Includes: NO OUT-OF-SCOPE DEFERRAL preamble, ARGUMENT PARSING table, Tier 3 availability probe, PHASE 0 COMMON PREAMBLE with Python NOW_ET capture honoring ARCIS_NOW_ET_OVERRIDE (DA1), SAFETY WINDOW GATE with re-capture at gate entry (DA1), four VERB sections (triage / act / status / runbook) with full phase structure including Phase T3 6-min wall-clock budget + Phase T4.5 re-verify + Phase A4.1 confirm-inheritance contract + Phase A5.1 re-capture preview, mid-runbook abandonment recovery sub-section, AUDIT TRAIL section with stdin-driven _execution_log_writer wrapper + jq -Rs/json.dumps escaping (DA3). Hardcoded 21:30-22:30 with DRIFT RISK comment per spec §6. Incident-id with 6-hex random suffix (DA6).

**Test strategy:**

Manual cold-read test per spec §12 item 1. Run §12 items 10a-10j for DA fixes (NOW_ET re-capture, confirm-inheritance contract, JSON injection safety, ≤3 binding prompts, self-resolution downgrade, incident-id collision, validation gate, prompt_hash, abandonment, re-capture preview). Verb-unknown test: /arcis:operate foobar returns §10.1 envelope verbatim with no audit event. Test all 4 verbs invoke their phase structure. AskUserQuestion budget enforcement: ≤3 per triage mandatory checkpoints, ≤2 per act — grep the file.

**Scope fence:** Do NOT touch SKILL.md (T1). Do NOT create runbook files (T3-T7). Do NOT touch references/ files (T8-T9). DRIFT RISK comment required at hardcoded safety window prose. Frontmatter is 2 fields (name + description) only. NO Python imports — markdown-only (but DOES invoke python -c for NOW_ET capture, secrets.token_hex for incident-id, json.dumps/hashlib for audit).

---

### Task T3 — Author runbooks/watchloop-wedged.md

**Estimated complexity:** standard

**Files in scope:**
- `.claude/plugins/arcis/skills/operate/runbooks/watchloop-wedged.md`

**Files (read-only context):**
- `.claude/plugins/arcis/agents/live-monitor.md`
- `.claude/plugins/arcis/docs/agent-tests/live-monitor-golden.md`
- `src/tools/processmanager/__main__.py`

**Description:**

Create the watchloop-wedged runbook verbatim per spec §5.1 (post-DA revision). Frontmatter per spec §4 schema INCLUDING optional confirm-inheritance field (DA2). 5 steps. Step 2's ask prose MUST satisfy the 5-point confirm-inheritance contract (i)-(v) so Step 3 act inherits A4. Includes Abandonment recovery section per DA9.

**Test strategy:**

Frontmatter parse test. confirm-inheritance contract verification: Step 2 prose names 'act restart-watchloop' + shows CLI + shows verify_step + has 'Approve — restart now' option. Run §12 10b POSITIVE path. Verify Abandonment recovery section present.

**Scope fence:** Do NOT touch SKILL.md (T1) or commands/operate.md (T2). Do NOT touch other runbooks (T4-T7). Mirror live-monitor-golden GQ2 DYNAMIC CONTEXT shape exactly.

---

### Task T4 — Author runbooks/pg-tests-red.md

**Estimated complexity:** standard

**Files in scope:**
- `.claude/plugins/arcis/skills/operate/runbooks/pg-tests-red.md`

**Files (read-only context):**
- `.claude/plugins/arcis/agents/ci-investigator.md`
- `.claude/plugins/arcis/agents/db-investigator.md`
- `.claude/plugins/arcis/docs/agent-tests/ci-investigator-golden.md`
- `.claude/plugins/arcis/docs/agent-tests/db-investigator-golden.md`

**Description:**

Create the pg-tests-red runbook verbatim per spec §5.2. Frontmatter per spec §4 schema. 6 steps. Diagnostic-only (mutations=false). Abandonment recovery section is a pointer to §3 (no mutations).

**Test strategy:**

Frontmatter parse test. Verify ci-investigator DYNAMIC CONTEXT matches ci-investigator-golden GQ1 shape. Step 6 ask-then-act PR-comment chain: verify if it satisfies §3.A4.1 contract OR falls to fresh A4.

**Scope fence:** Do NOT touch SKILL.md (T1) or commands/operate.md (T2). Do NOT touch other runbooks. mutations=false in frontmatter — diagnostic-only.

---

### Task T5 — Author runbooks/training-failed.md

**Estimated complexity:** standard

**Files in scope:**
- `.claude/plugins/arcis/skills/operate/runbooks/training-failed.md`

**Files (read-only context):**
- `.claude/plugins/arcis/agents/live-monitor.md`
- `.claude/plugins/arcis/agents/db-investigator.md`
- `src/tools/logtail/__main__.py`
- `src/tools/processmanager/__main__.py`

**Description:**

Create the training-failed runbook verbatim per spec §5.3. Frontmatter per spec §4 schema. 6 steps. Diagnostic-only (mutations=false). Abandonment recovery section is a no-op pointer.

**Test strategy:**

Frontmatter parse test. Verify branch logic (crash vs corpus vs not_started) is well-prosed. Verify memory references by exact file name. mutations=false confirmed; no act steps in body.

**Scope fence:** Do NOT touch SKILL.md or commands/operate.md. Do NOT touch other runbooks. mutations=false — diagnostic-only.

---

### Task T6 — Author runbooks/gpu-degraded.md

**Estimated complexity:** standard

**Files in scope:**
- `.claude/plugins/arcis/skills/operate/runbooks/gpu-degraded.md`

**Files (read-only context):**
- `.claude/plugins/arcis/agents/live-monitor.md`
- `src/tools/processmanager/__main__.py`
- `src/tools/healthprobe/__main__.py`

**Description:**

Create the gpu-degraded runbook verbatim per spec §5.4. Frontmatter per spec §4 schema INCLUDING optional confirm-inheritance field (DA2). 6 steps. Mutating (mutations=true, risk=medium). Step 3's ask prose MUST satisfy the 5-point confirm-inheritance contract so Step 4 act inherits A4. Includes Abandonment recovery section per DA9 covering Steps 5+6 best-effort verify.

**Test strategy:**

Frontmatter parse test. mutations=true confirmed. Verify Safety Window Gate referenced at Step 3 ask. Step 3 confirm-inheritance contract satisfied (names 'act restart-ollama-watchdog' + CLI + verify_step + 'Approve' option). Verify Abandonment recovery section present per §12 10i.

**Scope fence:** Do NOT touch SKILL.md or commands/operate.md. Do NOT touch other runbooks. mutations=true — must reference Safety Window Gate at confirm step.

---

### Task T7 — Author runbooks/data-anomaly.md

**Estimated complexity:** standard

**Files in scope:**
- `.claude/plugins/arcis/skills/operate/runbooks/data-anomaly.md`

**Files (read-only context):**
- `.claude/plugins/arcis/agents/db-investigator.md`
- `.claude/plugins/arcis/docs/agent-tests/db-investigator-golden.md`

**Description:**

Create the data-anomaly runbook verbatim per spec §5.5. Frontmatter per spec §4 schema. 5 steps. Diagnostic-only (mutations=false). Abandonment recovery section is a no-op pointer.

**Test strategy:**

Frontmatter parse test. required-tools value MUST be `capabilityregistry` (not `capabilityregistryquery` — FB1). Verify db-investigator DYNAMIC CONTEXT matches db-investigator-golden GQ1 shape (READ-ONLY constraint preserved). Verify A/B/C/D categorization is fully prose-defined. No deferral language.

**Scope fence:** Do NOT touch SKILL.md or commands/operate.md. Do NOT touch other runbooks. mutations=false — diagnostic-only.

---

### Task T8 — Author references/action-authorization-matrix.md (post wave-1 runbook authoring)

**Depends on:** Task T3, Task T4, Task T5, Task T6, Task T7

**Estimated complexity:** standard

**Files in scope:**
- `.claude/plugins/arcis/skills/operate/references/action-authorization-matrix.md`

**Files (read-only context):**
- `src/tools/processmanager/__main__.py`
- `src/tools/healthprobe/__main__.py`
- `src/tools/tradingstate/__main__.py`
- `src/tools/dbquery/__main__.py`
- `.claude/plugins/arcis/skills/operate/runbooks/watchloop-wedged.md`
- `.claude/plugins/arcis/skills/operate/runbooks/pg-tests-red.md`
- `.claude/plugins/arcis/skills/operate/runbooks/training-failed.md`
- `.claude/plugins/arcis/skills/operate/runbooks/gpu-degraded.md`
- `.claude/plugins/arcis/skills/operate/runbooks/data-anomaly.md`

**Description:**

Create the action authorization matrix file per spec §7 (post-FB3 + post-DA revision). **DA12 sequence:** runs in wave 2 AFTER wave 1 (T1-T7, T9) lands all 5 runbooks. T8 reads the 5 runbooks, builds the action set actually referenced, runs `python -m src.tools.<name> --help` for each presumed action (force-broker-poll, regenerate-stale-audit, post-pr-summary), removes UNVERIFIED rows that fail the help-probe, AND edits any runbook step referencing a removed action (none should exist by design — defense-in-depth). Full table with up-to-8 rows + prose intro. **Required columns (7 total, per FB3):** Action | Verification | Auth class | CLI invocation | Verify step | Risk | Notes. **Verification column values:** {verified, unverified-presumed, removed}. **MANDATORY impl-time gate (per spec §14 OQ#2/#3/#4):** before writing T8 row content, the implementing PM MUST run `python -m src.tools.processmanager --help`, `python -m src.tools.auditor --help`, `python -m src.tools.ci_summary_post --help` (plus alternates per §14 OQ#4). For any tool/verb that does NOT exist: REMOVE the row from this file AND DROP the action from any v1 runbook that references it. Surface every removal in PR description with `python -m src.tools.<name> --help` output evidence. **DA7 follow-up:** consider adding `staleness_checks` column (DA15) and `auth_matrix_checksum` (DA7 OQ#8) as v2 enhancements — not in v1.

**Test strategy:**

Verify every action row has all 7 columns populated. Verify Verification column is one of {verified, unverified-presumed, removed}. Verify auth_class is one of the 4 allowed values. **CLI-verification evidence:** for every row with Verification != 'removed', the PR description must include the `python -m src.tools.<name> --help` output excerpt confirming the CLI shape. For rows marked 'removed': PR description states which tool/verb the help-probe failed for, AND confirms (by Grep against the runbook files in files_read_only) that no v1 runbook references the dropped action.

**Scope fence:** Do NOT touch SKILL.md or commands/operate.md. T8 has read-only dependency on T3-T7 outputs (the 5 runbook files). If dropping a removed action requires editing a runbook, make ONLY the minimal removal edit and surface in PR description. This is a reference file consumed by the orchestrator's Phase A1 action lookup.

---

### Task T9 — Author references/error-envelopes.md

**Estimated complexity:** trivial

**Files in scope:**
- `.claude/plugins/arcis/skills/operate/references/error-envelopes.md`

**Files (read-only context):**
- `src/tools/_cli_envelope.py`
- `src/tools/_safety.py`

**Description:**

Create the error envelopes reference per spec §10 (post-DA revision). 9 sections (verb unknown, Tier 3 unavailable, safety window block, agent dispatch failure, tool ERROR envelope, operator denial at confirm, runbook step timeout, working dir unresolvable, **audit write failure §10.9 — DA3**). Each section: trigger, output (verbatim prose), audit event (if any), exit behavior.

**Test strategy:**

Verify each of the 9 error classes is documented with operator-facing output text verbatim. Verify audit event names match the conventions in commands/operate.md (T2) by string-matching. Verify §10.9 audit write failure envelope present per DA3.

**Scope fence:** Do NOT touch SKILL.md or commands/operate.md. This is a reference file. Verbatim prose must match what's quoted in commands/operate.md.

---

### Task T10 — Update CHANGELOG + finalize PR description + run Manual Verification Checklist

**Depends on:** Task T1, Task T2, Task T3, Task T4, Task T5, Task T6, Task T7, Task T8, Task T9

**Estimated complexity:** standard

**Files in scope:**
- `CHANGELOG.md`

**Files (read-only context):**
- `.claude/plugins/arcis/skills/operate/SKILL.md`
- `.claude/plugins/arcis/commands/operate.md`
- `.claude/plugins/arcis/skills/operate/runbooks/watchloop-wedged.md`
- `.claude/plugins/arcis/skills/operate/runbooks/pg-tests-red.md`

**Description:**

Add v0.36.6X entry to CHANGELOG.md. Run the full §12 Manual Verification Checklist (now 24 items: 14 base + 10 DA-fix items 10a-10j), post evidence in PR description. Verify cold-read by fresh session. Confirm dual-Opus QA reviewers can locate the spec.md + plan.json + design_decisions.json deliverables. **Also confirm: src/tools/_execution_log.py CLI entry point added per §14 OQ#7 (DA3 mitigation) — if added, include the diff in PR description.**

**Test strategy:**

Run all 24 items of spec §12 Manual Verification Checklist (14 base + 10a-10j). Post evidence (screenshot OR tail of data/logs/tool-execution.log) for each PASS in PR description. Cold-read test: fresh Claude Code session invokes /arcis:operate and self-describes phases. ARCIS_NOW_ET_OVERRIDE test for in-window refusal + re-capture (DA1). JSON injection test (DA3). Confirm-inheritance contract POSITIVE + NEGATIVE (DA2). Abandonment recovery simulation (DA9). Re-capture preview state-change injection (DA10). Tier 3 graceful-degradation smoke test.

**Scope fence:** Do NOT touch any of the 10 created files (T1-T9). Only CHANGELOG.md. PR description gets the Manual Verification Checklist evidence + any §14 Open Question resolutions discovered at impl time. Include _execution_log.py CLI-entry-point diff if added.

---

## Design Decisions Log

(Full entries in `design_decisions.json` alongside the spec.)

| # | Decision | Rationale (short) | Reversibility |
|---|----------|-------------------|---------------|
| DD1 | DD1: Skill structure is state-machine (8-phase) not freeform | Live-system mutations are high-stakes. Explicit phases force AskUserQuestion gates at mutation boundaries; freeform risks skipping safety. Both existing high-stakes pr... | moderate (changing to freeform later would require restructuring commands/ope... |
| DD2 | DD2: Verb parsing — single command file (operate.md), POSITIONAL_INPUT[0] as verb | Operator pre-confirmed in interview decisions (brief). Avoids 4 separate commands cluttering /arcis:* namespace. Verb dispatch is well-precedented in CLI tooling (git,... | moderate (would require renaming and adding 3 new command files) |
| DD3 | DD3: Safety window evaluation — Bash TZ='America/New_York' date + hardcoded HH:MM compare (O... | Performance: status verb target <30s, safety gate must be <1ms not 200ms (Option B). No-Python constraint: skill is markdown-only — Option B requires Python subprocess... | easy (replace hardcoded compare prose with full Python subprocess in commands... |
| DD4 | DD4: Runbook storage path — .claude/plugins/arcis/skills/operate/runbooks/<name>.md | Requirements §Must explicitly states 'Files at .claude/plugins/arcis/skills/operate/runbooks/<name>.md'. Operator-confirmed. While Option B has a coding-team precedent... | easy (rename directory + update path references in commands/operate.md Phase R1) |
| DD5 | DD5: Runbook frontmatter schema with symptom-matchers, required-tools, required-agents, muta... | Triage classifier needs symptom-matchers as machine-readable signal — embedding in YAML is parseable by the orchestrator and human-readable. required-tools enables Tie... | moderate (changing schema requires updating all 5 runbooks + orchestrator par... |
| DD6 | DD6: Cross-agent finding composition — OR-of-must-fix / AND-of-clear severity rollup, (canon... | Option A: operator pain — 3 reports with overlap = noise. Option C: loses structured data (severity field, confidence field). Option B preserves structure + reduces no... | moderate (changing algorithm requires updating commands/operate.md Phase T4 p... |
| DD7 | DD7: Audit trail — single file (tool-execution.log) + session_id bracketing, NOT new inciden... | FA10 explicitly notes operator's 'single answer to where do I find logs' preference (line 8 _execution_log.py docstring). Option B adds operational complexity: no rota... | easy (add a parallel write to incidents file later if operator changes mind —... |
| DD8 | DD8: AskUserQuestion budget — ≤3 per triage, ≤2 per act (operator-confirmed) | Requirements §Must explicitly states the budget. Strict budget prevents prompt fatigue. **DA4 clarification:** the ≤3 budget is for MANDATORY checkpoints (T2 dispatch,... | easy (relaxing the budget is non-breaking; tightening would require restructu... |
| DD9 | DD9: Tier 3 graceful-degradation — runtime probe per invocation, warn + skip on absence | Option A: marketpulse's pattern is weak — fails ungracefully at first invocation, no contextual warning. Option C: stale-manifest risk. Option B is invented by the arc... | easy (remove probe, fall back to marketpulse pattern if probe is found to be ... |
| DD10 | DD10: Action Authorization Matrix — separate references/ file, NOT inline in commands/operat... | Inline (Option A) bloats commands/operate.md to ~600+ lines. Separate file (Option B) keeps the orchestrator manageable, mirrors coding-team's references/anti-fallacy-... | easy (inline back into commands/operate.md if desired) |
| DD11 | DD11: --incident-id flag for incident continuation | Triage → runbook chaining requires session_id continuity. **DA6 amendment:** auto-gen id now includes a 6-hex random suffix (`secrets.token_hex(3)`) to resolve second-... | easy (remove flag, default to auto-gen) |
| DD12 | DD12: session_id propagation gap — bracket events workaround in v1, one-line _cli_envelope p... | Option C violates no-out-of-scope-deferral (memory: feedback_complete_efforts_no_deferral) — surfacing as an OQ is the discipline, not silent deferral. Option A is fun... | easy (add patch later as a non-breaking enhancement) |
| DD13 | DD13: Default agent dispatch for triage — always include live-monitor unless symptom is pure-CI | Option A: bad operator UX — at 3 AM, the operator wants reasonable defaults. Option C: wasteful — git-historian dispatch on a clear data-only symptom is noise. Option ... | easy (change Phase T1 classifier prose) |
| DD14 | DD14: Runbook step kinds — 5 vocabulary (tool / agent / ask / act / verify) | Option A: ambiguity at run-time, hard to verify in §12 checklist. Option C: brittle parsing, breaks if LLM modifies whitespace. Option B: each step block has a known s... | moderate (adding a 6th kind requires updating orchestrator Phase R3 parser pr... |
| DD15 | DD15: Status verb is read-only with NO audit event (Layer 2 skill-level skipped) | Status is invoked many times per day (operator's 'first thing I run'). Writing 2 skill-level events per invocation = log churn. Per-tool events (processmanager.status,... | easy (add audit event later if operator wants status-grepability) |
| DD16 | DD16: 5 v1 runbooks frozen scope (operator-confirmed) | Operator pre-confirmed in brief: 5 runbooks = watchloop-wedged, pg-tests-red, training-failed, gpu-degraded, data-anomaly. Each maps to a recurring operator-experience... | easy (additional runbooks are additive — new file in runbooks/, frontmatter s... |
| DD17 | DD17: Sibling-search applied to spec drafting — proactively surface adjacent defects | Memory: feedback_review_sibling_search + feedback_complete_efforts_no_deferral. Option A silently defers — operator's explicit anti-pattern. Option C scope creep. Opti... | n/a — discipline pattern, applies to all spec work |
| DD18 | DD18: --emergency override requires single explicit confirm (not double-confirm) | Option B = double-prompt friction for genuine emergencies (operator is already at 3 AM stress). Option C = removes the safety net entirely. Option A = single confirm w... | moderate (changing prompt structure requires editing commands/operate.md Safe... |
| DD19 | DD19: FB-revision pass — applied 1 CRITICAL + 1 MAJOR + 3 MINOR feasibility findings as surg... | Five findings, all narrowly-scoped to specific spec sections (no architecture changes). Edit tool's surgical replacement preserves the rest of the 125KB spec verbatim.... | easy (each FB edit is independently revertable) |
| DD20 | DD20: Operator override of requirements.md MUST — single-file audit pattern confirmed | DA14 surfaced the conflict between requirements.md MUST and DD7 (single-file audit). The architect's DD7 followed FA10 deep-analysis recommendation (single-file aligns... | easy — flip the bracketing-events block in §9 to ALSO write per-incident file... |
| DD21 | DD21: DA-revision pass — applied 2 CRITICAL + 7 MAJOR + 1 plan-change (DA12) via surgical Ed... | Ten findings, all narrowly-scoped to specific spec sections. Edit tool's surgical replacement preserves the rest of the 162KB spec verbatim. DA1 (CRITICAL): NOW_ET Pyt... | easy (each DA edit is independently revertable; DA1+DA2 are correctness/safet... |
