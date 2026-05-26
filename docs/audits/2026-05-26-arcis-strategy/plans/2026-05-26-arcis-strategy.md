# Arcis #110 — `arcis:strategy` Skill Implementation Plan

**Spec:** [`docs/audits/2026-05-26-arcis-strategy/specs/2026-05-26-arcis-strategy-design.md`](../specs/2026-05-26-arcis-strategy-design.md)
**Target release:** v0.36.6X (re-baseline at impl time; current main is v0.36.66)
**Estimated effort:** ~1-2 days agent work + dual-Opus QA
**Tasks:** 9 across 4 execution waves
**Scope:** Skill PR — SKILL.md + commands/strategy.md + references + golden transcripts + CHANGELOG + 1-column schema migration in `src/schema/registry.py` + `persist_backtest_result` signature update in `src/platform/backtest_persist.py` + caller updates in `tests/platform/test_platform_api.py`

---

## Implementation Discipline (read first)

Wave 0 (NEW — DA1 scope expansion): task 0 = schema migration + persist_backtest_result signature update. Blocks ALL subsequent tasks because the provenance_kind kwarg threading throughout commands/strategy.md depends on T0's signature. Wave 1 (parallel): tasks 1-6 are independent file authoring after T0 lands. SKILL.md, orchestrator (now 700+ lines with snapshot + lock + db_path inspection + orphan recovery + degraded-banner patterns), 4 reference files, and 2 templates. All consume only the spec doc + read-only existing source files. Wave 2 (sequential after orchestrator settles): task 7 (golden transcripts + CHANGELOG) — depends on commands/strategy.md being finalized so transcripts can use exact prompt prose for prompt_hash verification at runtime. Wave 3 (integration gate): task 8 runs the full §12 verification checklist (30 items after DA-revision) + resolves §14.2 coverage gaps + AskUserQuestion to operator for DD-13 (write target path). T0 introduces 2 Python edits (~4 lines total); everything else is markdown-only. The implementing PM dispatches T0 alone in wave 0, then tasks 1-6 in parallel via arcis:code worktree-isolation; ensures task 8 fires after dual-Opus QA approval. Per feedback_use_coding_team_skill, foundation-class dual-Opus QA gates the merge.

---

## Execution Order

**Wave 0:** Task 0

**Wave 1:** Task 1, Task 2, Task 3, Task 4, Task 5, Task 6

**Wave 2:** Task 7

**Wave 3:** Task 8

---

## Tasks

### Task 0 — T0 — Schema migration: add provenance_kind column + update persist_backtest_result signature

**Estimated complexity:** low

**Files in scope:**
- `src/schema/registry.py`
- `src/platform/backtest_persist.py`
- `tests/platform/test_platform_api.py`

**Files (read-only context):**
- `src/utils/db.py`
- `C:/Users/mille/AppData/Local/Temp/strategy-skill-architect/spec.md`

**Description:**

DA1 wave-0 prerequisite — blocks all subsequent tasks. (A) src/schema/registry.py: in the TABLES dict's `backtest_results` entry, add column `provenance_kind TEXT NOT NULL CHECK (provenance_kind IN ('quick_in_sample', 'wf_is_window', 'wf_is_window_orphan_partial_run'))`. (B) src/platform/backtest_persist.py: update `persist_backtest_result(result, *, db_path, git_sha='unknown')` to `persist_backtest_result(result, *, db_path, provenance_kind, git_sha='unknown')`. Append `provenance_kind` to the INSERT column list at line 48-54 AND to the VALUES tuple. provenance_kind is REQUIRED (no default — the CHECK constraint refuses NULL and the caller always knows). On fresh DB: registry.py applies the new column at bootstrap. On existing DB: ALTER TABLE happens via the existing bootstrap path (registry.py is idempotent). Verify by re-running existing tests/platform/test_platform_api.py with `provenance_kind='quick_in_sample'` hard-coded into any tests calling persist_backtest_result, OR refactor tests to use the new kwarg.

**Test strategy:**

(1) Fresh DB: run `python -m src.tools.dbquery --json "PRAGMA table_info(backtest_results)"` — verify `provenance_kind` column present with CHECK constraint. (2) Negative test: attempt INSERT with `provenance_kind=NULL` — must fail with CHECK violation. (3) Positive test: call `persist_backtest_result(result, db_path=..., provenance_kind='quick_in_sample')` — verify row written with correct provenance_kind. (4) Re-run tests/platform/test_platform_api.py — verify all tests pass after kwarg-update. (5) Bootstrap idempotency: run `bootstrap_db()` twice on an existing DB — must not crash on the duplicate ALTER.

**Scope fence:** Do NOT add any other columns. Do NOT modify other tables in registry.py. Do NOT change the INSERT pattern beyond adding the one new column. Do NOT add a default value for provenance_kind (the caller is required to pass it; CHECK refuses NULL). Do NOT touch any skill-layer files — that is Tasks 2+. T0 is purely the schema + persist contract change.

---

### Task 1 — Author SKILL.md descriptor

**Depends on:** Task 0

**Estimated complexity:** low

**Files in scope:**
- `.claude/plugins/arcis/skills/strategy/SKILL.md`

**Files (read-only context):**
- `.claude/plugins/arcis/skills/operate/SKILL.md`
- `C:/Users/mille/AppData/Local/Temp/strategy-skill-architect/spec.md`

**Description:**

Create .claude/plugins/arcis/skills/strategy/SKILL.md per §2 of the design spec. VERBATIM content from spec §2; do not paraphrase. Frontmatter has ONLY `name:` and `description:` keys. Body covers: verb-dispatched state machine (8 steps), agent hierarchy (5 agents), 8 key properties, 4-verb table, 6-flag argument table, out-of-scope list. Implementing PM reads spec §2 and pastes verbatim into the file.

**Test strategy:**

Static lint check: frontmatter has exactly two keys (name, description); body matches §2 verbatim by diff. Cold-read by fresh session: skill appears in /arcis: list with the §2 description.

**Scope fence:** Do NOT modify any agent file. Do NOT modify SKILL.md of other skills. Do NOT add Python code. Frontmatter limited to name+description ONLY (no extra keys like `version` or `enabled`). Do NOT invent content beyond what spec §2 specifies.

---

### Task 2 — Author commands/strategy.md orchestrator (incorporating DA1-DA14 fixes)

**Depends on:** Task 0

**Estimated complexity:** high

**Files in scope:**
- `.claude/plugins/arcis/commands/strategy.md`

**Files (read-only context):**
- `.claude/plugins/arcis/commands/operate.md`
- `.claude/plugins/arcis/commands/research.md`
- `.claude/plugins/arcis/commands/code.md`
- `C:/Users/mille/AppData/Local/Temp/strategy-skill-architect/spec.md`
- `src/platform/backtest_persist.py`
- `src/schema/registry.py`

**Description:**

Create .claude/plugins/arcis/commands/strategy.md per §3 of the design spec. ~700 lines after DA-revision (grew from ~540 to absorb snapshot + lock + db_path inspection + orphan recovery + degraded-banner patterns). Includes: NO OUT-OF-SCOPE DEFERRAL preamble (verbatim), ARGUMENT PARSING table, verb-unknown handling, PROD-PG GATE, PHASE 0 common preamble (Steps 0.1-0.4), then 4 per-verb sections (ideate I1-I6, backtest B1 + B1.5 snapshot + B2 + B3 + B4 + B5 dual-hash + B5.5 lock + B5.9 db_path + B6 quick + B7 wf + B7-failure-path orphan + B8 + B9, analyze AN1 provenance dispatch + AN2 + AN3 family-variance gate + AN4 + AN5 + AN6, status S1-S4 + Active Runs + Orphans), ERROR ENVELOPES section (§10.1-§10.16), AUDIT TRAIL CONVENTIONS section. stdin-driven heredocs throughout for JSON safety per spec §9.4. ALL persist_backtest_result calls pass provenance_kind kwarg. ALL spec loads use SPEC_SNAPSHOT_PATH env var, not load_spec(id). ALL persist calls are wrapped in portalocker.Lock at B5.5. ALL heredocs include _validate_db_path_not_prod inline check.

**Test strategy:**

Lint: file size 600-800 lines. Grep for `<<'PY'` single-quoted heredoc on every Python subprocess. Grep for `arcis_strategy.<verb>.started/.completed` brackets per verb. Grep for `provenance_kind=` on every persist_backtest_result call — must be 2+ (B6 quick + B7 per-window loop). Grep for `portalocker.Lock` — must be at B5.5. Grep for `_validate_db_path_not_prod` — must be at B5.9 inside each heredoc. Grep for `SPEC_SNAPSHOT_PATH` — must thread through B1.5, B5, B6, B7. Cold-read: invocation /arcis:strategy with no args fires verb-unknown ERROR per §10.1.

**Scope fence:** Do NOT add new verbs beyond ideate/backtest/analyze/status. Do NOT change frontmatter shape. Do NOT add Python implementation files. Do NOT modify schema/registry.py or backtest_persist.py — those are T0's scope. Do NOT call scripts/run_backtest.py. Do NOT call src/evaluation/* modules. Do NOT call src/platform/rigor/walkforward.py (the non-rigor path). Do NOT call scripts/backtest/run_walkforward.py — architecture-locked per DA14.

---

### Task 3 — Author references/verb-conventions.md

**Depends on:** Task 0

**Estimated complexity:** low

**Files in scope:**
- `.claude/plugins/arcis/skills/strategy/references/verb-conventions.md`

**Files (read-only context):**
- `C:/Users/mille/AppData/Local/Temp/strategy-skill-architect/spec.md`
- `.claude/plugins/arcis/skills/operate/references/error-envelopes.md`

**Description:**

Create .claude/plugins/arcis/skills/strategy/references/verb-conventions.md per spec §4. Documents argument parsing convention, tool JSON envelope contract, Python-inline subprocess contract (heredoc safety), agent dispatch convention, error envelope uniform shape. Cited by commands/strategy.md.

**Test strategy:**

Lint: file 80-120 lines. Cross-reference: every convention referenced in commands/strategy.md MUST exist in this file (grep verification both directions).

**Scope fence:** Read-only reference doc — no orchestration logic. Do NOT duplicate phase prose from commands/strategy.md.

---

### Task 4 — Author references/rigor-stack-integration.md

**Depends on:** Task 0

**Estimated complexity:** low

**Files in scope:**
- `.claude/plugins/arcis/skills/strategy/references/rigor-stack-integration.md`

**Files (read-only context):**
- `src/platform/rigor/walkforward_firewall.py`
- `src/platform/rigor/walkforward_purging.py`
- `src/platform/rigor/walkforward_universe.py`
- `C:/Users/mille/AppData/Local/Temp/strategy-skill-architect/spec.md`

**Description:**

Create .claude/plugins/arcis/skills/strategy/references/rigor-stack-integration.md per spec §6. Documents R8 firewall (a/b/d), skill-layer preflight rationale (B2), purging + embargo guarantees, point-in-time universe semantics, three-state outcome reducer. Includes citations to walkforward_firewall.py line ranges, walkforward_purging.py López de Prado §7.4 reference.

**Test strategy:**

Lint: file 90-130 lines. Cross-reference: line numbers cited in this file MUST match actual file contents at impl time (PM verifies by Read tool before commit).

**Scope fence:** Read-only reference. No orchestration logic. Do NOT modify any src/platform/rigor/* file. Do NOT invent rigor constants — quote verbatim from source.

---

### Task 5 — Author references/statistical-rigor.md + error-envelopes.md

**Depends on:** Task 0

**Estimated complexity:** low

**Files in scope:**
- `.claude/plugins/arcis/skills/strategy/references/statistical-rigor.md`
- `.claude/plugins/arcis/skills/strategy/references/error-envelopes.md`

**Files (read-only context):**
- `src/platform/rigor/dsr.py`
- `src/platform/rigor/cscv.py`
- `src/platform/rigor/trials.py`
- `C:/Users/mille/AppData/Local/Temp/strategy-skill-architect/spec.md`

**Description:**

Create two reference files. (A) .claude/plugins/arcis/skills/strategy/references/statistical-rigor.md per spec §8: DSR + PSR + CSCV semantics, trials_registry N_eff bookkeeping, T<30 fallback per dsr.py:85, paper-erratum notes, dual-write rationale (DD-5), DA3 family-variance threshold, DA13 variance_source classification ('empirical'|'fallback'|'fallback_with_warning'). (B) .claude/plugins/arcis/skills/strategy/references/error-envelopes.md per spec §10: all 16 envelope examples verbatim (10.1-10.16, including DA-revision additions 10.12 concurrent_refused, 10.13 db_path_blocked, 10.14 orphan_refused, 10.15 ideate_incomplete, 10.16 variance_fallback warning).

**Test strategy:**

Lint: statistical-rigor.md 90-130 lines; error-envelopes.md 90-130 lines. Grep: every error class in §10 (16 envelopes after DA-revision) has a one-to-one envelope example in error-envelopes.md.

**Scope fence:** Read-only references. Do NOT modify dsr.py / cscv.py / trials.py. Do NOT change N_eff fallback constants — quote verbatim from trials.py:33 (_VARIANCE_FALLBACK definition; RuntimeWarning emitted at trials.py:109).

---

### Task 6 — Author templates (strategy-spec-scaffold.yaml + ideation-report-template.md)

**Depends on:** Task 0

**Estimated complexity:** low

**Files in scope:**
- `.claude/plugins/arcis/skills/strategy/templates/strategy-spec-scaffold.yaml`
- `.claude/plugins/arcis/skills/strategy/templates/ideation-report-template.md`

**Files (read-only context):**
- `src/platform/specs/post_audit_ruleset_v1.yaml`
- `src/platform/specs/lazy_prices_v1.yaml`
- `src/platform/strategy_spec.py`
- `C:/Users/mille/AppData/Local/Temp/strategy-skill-architect/spec.md`

**Description:**

Create two template files used by the ideate verb. (A) .claude/plugins/arcis/skills/strategy/templates/strategy-spec-scaffold.yaml: R8-compliant YAML skeleton with `derived_from: null` explicit, all REQUIRED_KEYS per FA2 line 83 present, TODO comments where the operator fills sections. (B) .claude/plugins/arcis/skills/strategy/templates/ideation-report-template.md: markdown body shape with header + synthesis + supporting/counter/operational sections + proposed YAML block placeholder. Used by Phase I4 of the ideate verb.

**Test strategy:**

scaffold.yaml MUST pass validate_spec() with placeholder values OR with `strategy_id: __FILL_IN__` after a string substitution. Round-trip: load_spec on the scaffold raises ValueError listing missing fields the operator must fill. ideation-report-template.md is markdown-only; lint for matching {placeholder} markers referenced by spec §3 Phase I4 prose.

**Scope fence:** Templates only. Do NOT modify any existing YAML in src/platform/specs/. Do NOT add Python code. derived_from key MUST be present with `null` value (NOT omitted) per R8.

---

### Task 7 — Author golden transcripts + CHANGELOG entry

**Depends on:** Task 2

**Estimated complexity:** low

**Files in scope:**
- `.claude/plugins/arcis/skills/strategy/references/golden-transcripts.md`
- `CHANGELOG.md`

**Files (read-only context):**
- `C:/Users/mille/AppData/Local/Temp/strategy-skill-architect/spec.md`
- `.claude/plugins/arcis/commands/strategy.md`

**Description:**

Add the 5 golden transcripts (from spec §11) as a separate references/golden-transcripts.md file (commands/strategy.md is now 700+ lines after DA-revision, so externalize). Transcripts: 11.1 ideate happy, 11.2 backtest --quick happy, 11.3 backtest default happy, 11.4 analyze on walkforward, 11.5 status. Each anchored to real spec IDs (lazy_prices_v1, post_audit_ruleset_v1). Transcripts include provenance_kind in analyze output, the new 'Internal provenance' section in B9, and the Active Runs / Orphans sections in status. CHANGELOG.md entry: `v0.36.6X (impl-time-rebaseline) — Skill: /arcis:strategy ships with 4 verbs (ideate / backtest / analyze / status); adds provenance_kind column on backtest_results for three-state outcome preservation at the data layer (DA1).`

**Test strategy:**

Lint: each transcript has a complete operator-input line, expected output block, and audit-event mentions. Real spec ids only (lazy_prices_v1, post_audit_ruleset_v1) — no placeholder strings. CHANGELOG.md line added under the next unreleased version header. Verify the DA-revision elements appear: provenance_kind in §11.4 analyze; 'Internal provenance' section in §11.3 backtest default; Active Runs + Orphans sections in §11.5 status.

**Scope fence:** Do NOT invent backtest metrics with implausible values. Do NOT use a strategy_id that doesn't exist in src/platform/specs/. Do NOT bump version number — PM picks at PR open.

---

### Task 8 — Integration gate: harness test + cold-read + dry verification + run-the-checklist (DA10 strengthened)

**Depends on:** Task 1, Task 2, Task 3, Task 4, Task 5, Task 6, Task 7

**Estimated complexity:** medium

**Files in scope:**
- `docs/audits/2026-05-2X-arcis-strategy/verification-log.md`
- `tests/skills/strategy/test_engine_runner_compose.py`

**Files (read-only context):**
- `.claude/plugins/arcis/skills/strategy/SKILL.md`
- `.claude/plugins/arcis/commands/strategy.md`
- `.claude/plugins/arcis/skills/strategy/references/verb-conventions.md`
- `.claude/plugins/arcis/skills/strategy/references/rigor-stack-integration.md`
- `.claude/plugins/arcis/skills/strategy/references/statistical-rigor.md`
- `.claude/plugins/arcis/skills/strategy/references/error-envelopes.md`
- `.claude/plugins/arcis/skills/strategy/references/golden-transcripts.md`
- `.claude/plugins/arcis/skills/strategy/templates/strategy-spec-scaffold.yaml`
- `.claude/plugins/arcis/skills/strategy/templates/ideation-report-template.md`
- `CHANGELOG.md`
- `src/schema/registry.py`
- `src/platform/backtest_persist.py`
- `C:/Users/mille/AppData/Local/Temp/strategy-skill-architect/spec.md`

**Description:**

Final integration task — depends on tasks 0-7. NAMED PRE-PR SUBGOAL (FB11 + DA10): write tests/skills/strategy/test_engine_runner_compose.py that invokes the full per-window orchestration against lazy_prices_v1 + a 2-window WalkForwardConfig stub. The test asserts ALL of (DA10): (a) SELECT COUNT(*) FROM backtest_results WHERE strategy_id='lazy_prices_v1' AND provenance_kind='wf_is_window' AND created_at > <test_start> == 2; (b) SELECT COUNT(*) FROM walkforward_results WHERE strategy_id='lazy_prices_v1' AND created_at > <test_start> == 1; (c) derived_from_backtest_id IS NOT NULL AND points to a row with provenance_kind='wf_is_window'; (d) SELECT COUNT(*) FROM trials_registry WHERE created_at > <test_start> == 1; (e) wf_run_id captured equals walkforward_results.run_id; (f) ALL backtest_results rows have provenance_kind set (no NULL). Test MUST exist and pass BEFORE PR opens. THEN execute spec §12 manual verification checklist items 1-30. For each: run the command, inspect output, compare to expected. Record PASS/FAIL per item in a verification log committed alongside the PR. Surface §14.2 coverage gaps + §14.6 OQs (DD-13 write-target path, DA3 family-variance threshold, DA1 IS-WF provenance via column, DA11 --quick canonical window) to operator via AskUserQuestion BEFORE dual-Opus QA dispatch. Do NOT request review until the harness test passes AND ALL 30 items PASS.

**Test strategy:**

(1) test_engine_runner_compose.py passes ALL six DA10 assertions (a-f) above: pytest -xvs tests/skills/strategy/test_engine_runner_compose.py exits 0. (2) Manual verification log committed; all 30 items marked PASS (items 1-22 are FB-baseline, items 23-30 are DA-revision additions covering DA1/DA2/DA4/DA5/DA6/DA8/DA9/DA10 verification). Audit log inspected for: arcis_strategy.ideate.started/.completed, arcis_strategy.backtest.snapshot_captured + .started + .confirmed + .wf_run_attempt + .window_persisted + .wf_complete (or .wf_partial on failure) + .completed, arcis_strategy.analyze.started/.completed, NO arcis_strategy.status.* events. DB rows inspected for: 1 backtest_results row per --quick run with provenance_kind='quick_in_sample', 5 backtest_results rows with provenance_kind='wf_is_window' + 1 walkforward_results per default run, 1 trials_registry row per backtest AND per analyze, NO NULL provenance_kind values. Per `feedback_strict_rigor_no_handwave`: each verification done by mutation (deliberately break a precondition + confirm the right error envelope fires).

**Scope fence:** Do NOT skip the harness test — it is the FB+DA-revision pre-PR gate. Do NOT skip checklist items 23-30 — they cover DA-revision additions. Do NOT proxy verification by code-reading alone — actually run commands. Do NOT submit for dual-Opus QA until §14.2 coverage gaps + §14.6 OQs are operator-resolved.

---

## Design Decisions Log

(Full entries in `design_decisions.json` alongside the spec.)

| # | Decision | Rationale (short) | Reversibility |
|---|----------|-------------------|---------------|
| Skill structure = verb-dispatched state machine, mirroring #109 arcis | Skill structure = verb-dispatched state machine, mirroring #109 arcis:operate | The operator already has muscle memory for /arcis:operate's POSITIONAL_INPUT[0] verb pattern with verb-specific phase machines. arcis:strategy uses the SAME pattern so... | ? |
| Verb dispatch convention | Verb dispatch convention: POSITIONAL_INPUT[0] as verb, identical to #109 | Brief locks this. Also matches operate's argument parsing table shape. Operator's muscle memory. | ? |
| ? | backtest default = full walkforward via walkforward_runner.run_walkforward(); --quick = in-s... | Brief locks this. The inversion vs scripts/run_backtest.py (which defaults to IS-only) is intentional: the skill defaults to RIGOR (no operator surprise that they ran ... | ? |
| Per-window engine loop (10 invocations | Per-window engine loop (10 invocations: 5 windows × IS+OOS) orchestrated by the SKILL, not d... | Per FA7, walkforward_runner.run_walkforward() does NOT call the engine — it expects pre-computed window_trades dict. The architect verified no scripts/backtest/run_wal... | ? |
| ? | Skill records trials_registry in BOTH backtest verb (post-persist) AND analyze verb (post-DS... | Per FA11, scripts/run_backtest.py does NOT call record_trial — historical N_eff is undercounted. The skill closes the gap (no-out-of-scope-deferral). Backtest records ... | ? |
| ? | R8 preflight runs at the SKILL layer (Phase B2) BEFORE invoking the runner | The runner already enforces R8 at entry (FA9 line 246-260), but raises a Python R8ViolationError to the orchestrator. Skill-layer preflight surfaces a friendly remedia... | ? |
| ? | trials_registry N_eff is read globally (cross-strategy), not per-strategy-family | Per FA11 (trials.py:36): get_current_n_eff() is a global count. DSR's formula needs a global N for the extreme-value E[max SR] computation. The strategy-family varianc... | ? |
| AskUserQuestion budget | AskUserQuestion budget: ≤2 per ideate (clarification + cross-domain confirm), ≤2 per backtes... | Mirror #109's per-verb budget. Backtest mutation matches operate's act verb budget of 2 (one for the action, one for emergency override or spec-hash drift). Status is ... | ? |
| ? | Spec-hash re-capture between B4 confirm and B5 execute (DA10-equivalent) | The spec YAML could be edited by another process or operator between approve and execute. spec_hash mismatch triggers a re-confirm with diff display. Conservative; mat... | ? |
| Three-state outcome preservation | Three-state outcome preservation: surfaced verbatim through audit, output, AND analyze recom... | Brief locks this. PASS / FAIL / INCONCLUSIVE has different operational meanings; collapsing to boolean destroys the INCONCLUSIVE signal (which is by far the most commo... | ? |
| ideate dispatches 5 agents in two waves | ideate dispatches 5 agents in two waves: Wave A parallel (db-investigator + git-historian + ... | Cross-domain-analyst's DYNAMIC CONTEXT requires DOMAIN_REPORTS from the domain-leads (FA15). Cannot dispatch in parallel — must serialize. The domain-lead spawns its o... | ? |
| ideate merge algorithm | ideate merge algorithm: 3-category bucketing (supporting / counter / operational), dedup by ... | Brief asks 'how does the skill merge 5 agent reports'. Three-category bucketing matches the natural shape of strategy ideation: 'evidence for' / 'evidence against' / '... | ? |
| Write target = paths.db_canonical (SQLite per arcis_config.yaml | Write target = paths.db_canonical (SQLite per arcis_config.yaml:44) for v1; PM resolves A-vs... | Per FA17 DRIFT — brief says 'local PG via paths.db_canonical' but paths.db_canonical is SQLite, and the local PG sidecar at port 5433 matches prod_dsn_signatures (woul... | ? |
| ? | ARCIS_ALLOW_PROD_PG sentinel check at orchestrator entry (before any other phase) for backte... | Brief: 'skill refuses if ARCIS_ALLOW_PROD_PG is set'. Earliest-possible check minimizes wasted work on operator-typo-and-rerun cycles. Backtest-only because ideate/ana... | ? |
| --quick banner placement | --quick banner placement: FIRST and LAST line of the result block; appears in B3 plan AND B9... | Brief: 'architect specifies the exact ⚠ prefix + position in operator output to make it visually unmissable.' Triple-asterisk ⚠ ⚠ ⚠ banner before AND after the metrics... | ? |
| ? | Walkforward autofire suppression via WALKFORWARD_AUTOFIRE_ENABLED=false env var in subprocess | Per FA5 + cross-cutting concern — scripts/run_backtest.py:97 has an autofire hook that double-runs walkforward post-persist. The skill explicitly runs walkforward; dou... | ? |
| Audit event naming | Audit event naming: arcis_strategy.<verb>.<phase>; session_id = SESSION_ID (ideate) or RUN_I... | Semantically a research run is not an incident. Using INCIDENT_ID would muddle the audit-log grepability (incident-ids are operate's domain). Per FA13: research artifa... | ? |
| ? | ideate writes markdown reports to docs/strategy-ideation/<date>-<slug>.md (default) with --o... | Matches /arcis:research's docs/research/ convention (FA15 implication). Date-prefixed for chronological grep. Operator can override per --out for ad-hoc destinations. | ? |
| ? | prompt_hash + option_text on every backtest.confirmed event (mirror #109 DA8) | Mirror operate's confirm-event schema. Lets operator audit-trace 'what was operator asked, what did they pick'. Critical for understanding why a particular run with a ... | ? |
| status verb actively surfaces silently-filtered malformed YAMLs (FA2 | status verb actively surfaces silently-filtered malformed YAMLs (FA2:392) as anomalies | list_available_specs() silently skips malformed YAML with logger.warning. Operator never sees the warning if they're using the skill. no-out-of-scope-deferral demands ... | ? |
| FB-revision pass | FB-revision pass: 4 CRITICAL + 4 MAJOR + 3 MINOR feasibility findings addressed; spec verifi... | Feasibility reviewer surfaced surgical contract mismatches that would crash on first invocation: (FB1) WalkForwardWindow uses train_start/train_end/test_start/test_end... | ? |
| DA-revision pass | DA-revision pass: 2 CRITICAL + 7 MAJOR + 4 MINOR Devil's Advocate findings addressed in one ... | DA reviewer found two CRITICAL gaps the FB-pass didn't catch: (DA1) backtest_results table cannot distinguish quick / wf_is_window / orphan rows by column lookup — AN1... | ? |
