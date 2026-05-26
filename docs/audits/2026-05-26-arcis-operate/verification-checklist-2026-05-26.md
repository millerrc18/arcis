# `/arcis:operate` Skill — §12 Manual Verification Checklist Receipt

**PR:** #109  
**Version:** v0.36.67  
**Date:** 2026-05-26  
**Inspector:** T10 implementing developer (wave 3)  
**Spec reference:** `docs/audits/2026-05-26-arcis-operate/specs/2026-05-26-arcis-operate-design.md` §12

This receipt walks through all 24 checklist items (14 base + 10a-10j DA-fix items).
Each item is marked:

- **STATIC PASS** — verified at impl time via file-grep, frontmatter parse, or code inspection. File:line cited.
- **RUNTIME DEFERRED** — requires live session or env-var injection; reproduction recipe given.
- **NOT APPLICABLE** — explained.

---

## §12.1 — Cold-read by fresh session

**Status: RUNTIME DEFERRED**

Cannot verify statically. This requires a live Claude Code session with no prior `#109` context.

**Reproduction recipe:**
1. Close all Claude Code sessions that have loaded `commands/operate.md`.
2. Open a NEW session. Run: `/arcis:operate triage "test symptom"`.
3. PASS criteria: the skill self-describes its phases (ARGUMENT PARSING → PHASE 0 PREAMBLE → VERB: triage), asks the dispatch confirmation (`AskUserQuestion` T2), and proceeds without the operator needing to reference any external file.

---

## §12.2 — Verb-unknown error envelope

**Status: STATIC PASS**

Verified in `.claude/plugins/arcis/commands/operate.md` lines 47-59 (ARGUMENT PARSING > "Verb-unknown handling" section).

**What was checked:** The orchestrator prose at the "Verb-unknown handling" block prints verbatim:
```
ERROR — unknown verb: "<received>". Expected one of: triage, act, status, runbook.
Usage:
  /arcis:operate triage "<symptom>"           — investigate (no mutations)
  /arcis:operate act <action> [args]          — execute mutation with confirm
  /arcis:operate status [service]             — read-only health snapshot
  /arcis:operate runbook <name> [--dry-run]   — run a named flow
```

Cross-checked against `references/error-envelopes.md` §10.1: **exact match** (word-for-word). The `commands/operate.md` block at line 52 reads `ERROR — unknown verb: "<received>". Expected one of: triage, act, status, runbook.` and the `error-envelopes.md` §10.1 Output block reads the same.

Also confirmed: line 59 reads `2. STOP. Do NOT proceed to any phase. Do NOT write to audit log (no incident).` — matches `error-envelopes.md` §10.1 Audit field: `NO event (no incident).`

---

## §12.3 — Refuse-in-window verification

**Status: RUNTIME DEFERRED**

Requires env-var injection + live invocation.

**Reproduction recipe:**
```bash
export ARCIS_NOW_ET_OVERRIDE=2026-05-25T22:00:00-04:00
# (in Claude Code session)
/arcis:operate act restart-watchloop
```

PASS criteria:
1. Skill prints the REFUSE prose from §6 verbatim (with `Current ET: 2026-05-25 22:00 EDT` substituted).
2. `tail -5 data/logs/tool-execution.log | jq '.tool_name'` shows `arcis_operate.act.safety_window_refused` and NO `processmanager.restart` event.

The test seam (`ARCIS_NOW_ET_OVERRIDE`) is confirmed present in `commands/operate.md` line 88 (Step 0.1 one-liner) and line 142 (SAFETY WINDOW GATE re-capture one-liner) — both reference `os.environ.get('ARCIS_NOW_ET_OVERRIDE')`.

---

## §12.4 — Emergency override flow

**Status: RUNTIME DEFERRED**

Requires env-var injection + `--emergency` flag + live AskUserQuestion interaction.

**Reproduction recipe:**
```bash
export ARCIS_NOW_ET_OVERRIDE=2026-05-25T22:00:00-04:00
# (in Claude Code session)
/arcis:operate act restart-watchloop --emergency
```

PASS criteria:
1. Skill asks the emergency-confirm `AskUserQuestion` (DA8 single-confirm per DD18): "You are bypassing safety_windows.no_restart_overnight..."
2. Picking "No — wait until 22:30 ET" → STOP; `arcis_operate.act.emergency_denied` event written.
3. Picking "Yes — emergency override" → proceeds to Phase A2 dry-run → Phase A4 confirm → tool invocation.

---

## §12.5 — Tier 3 graceful degradation

**Status: RUNTIME DEFERRED**

No v1 runbook lists `contractcheck`, `gitarchaeology`, or `docconsistency` in `required-tools` (confirmed by `grep -l contractcheck .claude/plugins/arcis/skills/operate/runbooks/*.md` → 0 results). To test the degradation path, a transient manual edit is required.

**Reproduction recipe:**
1. Temporarily add `  - contractcheck` to the `required-tools` section of any runbook (e.g., `watchloop-wedged.md`).
2. Run `/arcis:operate runbook watchloop-wedged`.
3. PASS criteria: skill prints `"Tool contractcheck not yet shipped, gated on #107 — skipping <step>. Surfacing partial findings only."` (§10.2 envelope) and continues without crashing.
4. Revert the manual edit after verification.

The probe pattern is confirmed present in `commands/operate.md` lines 63-77 (Tier 3 availability probe block).

---

## §12.6 — Audit-log presence

**Status: STATIC PASS**

Verified in `.claude/plugins/arcis/commands/operate.md`.

**What was checked:**

1. **Start event** — `arcis_operate.${VERB}.start` is written at Phase 0.3 (lines 118-124). The `--tool-name "arcis_operate.${VERB}.start"` argument is present verbatim at line 119.

2. **Completed events** — present for all three non-status verbs:
   - `triage`: `arcis_operate.triage.completed` written at Phase T7 (line 412).
   - `act`: `arcis_operate.act.<action>.completed` written at Phase A7 (line 561).
   - `runbook`: `arcis_operate.runbook.<name>.completed` written at Phase R5 (line 722).

3. **Status verb exception** — explicitly noted at lines 619-620: `arcis_operate.status.start` and `arcis_operate.status.completed` are NOT written (DD15 — Layer 2 skill-level skipped for read-only status; per-tool Layer 1 events suffice).

**Runtime recipe to confirm:**
```bash
tail -10 data/logs/tool-execution.log | jq '.tool_name'
# Should show: "arcis_operate.<verb>.start" and "arcis_operate.<verb>.completed"
```

---

## §12.7 — Status verb fast-path

**Status: RUNTIME DEFERRED**

Requires live invocation with wall-clock timing.

**Reproduction recipe:**
```bash
time /arcis:operate status
```

PASS criteria:
1. Returns within 30s.
2. No Agent dispatch fires during the verb (verify by watching session turn count — status should be 3-4 tool calls: `processmanager status` ×3 + `healthprobe` + `tradingstate`, all in one parallel message per Phase S1).
3. No `arcis_operate.status.start` or `arcis_operate.status.completed` events in audit log (DD15 confirmed).

---

## §12.8 — Runbook resolution

**Status: RUNTIME DEFERRED**

Requires live invocation to verify the resolve/refuse behavior.

**Reproduction recipe:**
```bash
/arcis:operate runbook nonexistent
# Expected: ERROR — unknown runbook: "nonexistent". Known runbooks: watchloop-wedged, pg-tests-red, training-failed, gpu-degraded, data-anomaly.
# (from commands/operate.md Phase R1, lines 640-646)

/arcis:operate runbook watchloop-wedged --dry-run
# Expected: runbook parses, prints step plan (Step 1..5), does NOT execute any tool.
```

PASS criteria for `--dry-run`: operator sees step plan with no `ArcisWatchLoop` process mutation attempted; `DRY_RUN = true` check at Phase A5 (line 500) ensures STOP before `--confirm` invocation.

---

## §12.9 — Cross-agent composition

**Status: RUNTIME DEFERRED**

Requires live triage with a symptom that triggers 2+ agents.

**Reproduction recipe:**
```bash
/arcis:operate triage "trades stopped firing"
```

Expected agent dispatch (per Phase T1 classifier): `live-monitor` (keyword `trades`) + `db-investigator` (conditional, `shadow`/`trades` keywords).

PASS criteria:
1. Operator-facing TRIAGE COMPLETE report lists findings from BOTH agents with `Source:` fields showing the respective agent names.
2. Severity rollup applied (OR-of-must-fix / AND-of-clear) per Phase T4 composition algorithm (lines 317-329).

---

## §12.10 — No out-of-scope deferral

**Status: RUNTIME DEFERRED**

Requires a live triage producing 8+ findings.

**Reproduction recipe:**
```bash
/arcis:operate triage "watchloop wedged and trades stalled and CI red"
# (symptom spans live + data + ci domains → dispatches live-monitor + db-investigator + ci-investigator)
```

PASS criteria:
1. Report shows ALL N findings (first 5 in detail, remaining N-5 as one-line summaries — per Phase T5 prose, lines 356-391).
2. `grep -i "deferred to\|follow-up task" <report_output>` → 0 hits.

The DA4 fix is confirmed present in `commands/operate.md` line 357: "ALL findings shown; first 5 in detail; remaining as one-line summary each." and the operator-facing template at lines 367-385 shows the ADDITIONAL FINDINGS section.

---

## §12.10a — DA1: NOW_ET re-capture at gate entry

**Status: RUNTIME DEFERRED**

Requires env-var injection AND a deliberately slow A2 preview to simulate drift between Step 0.1 and gate entry.

**Reproduction recipe:**
1. `export ARCIS_NOW_ET_OVERRIDE=2026-05-25T21:31:00-04:00` (in-window).
2. Invoke `/arcis:operate act restart-watchloop`.
3. PASS criteria: the REFUSE prose (or emergency-confirm prompt) shows `Current ET: 2026-05-25 21:31 EDT` — the FRESH re-capture from `NOW_ET_GATE` at line 142 of `commands/operate.md` — NOT a stale earlier timestamp from Step 0.1.

The DA1 fix is confirmed present in `commands/operate.md` lines 93-95 (Step 0.1 clarification: "This Step-0.1 capture is for audit-prelude bracket events ONLY") and lines 139-150 (SAFETY WINDOW GATE section: "Re-capture NOW_ET at gate entry (DA1 fix)" with its own fresh Python one-liner).

---

## §12.10b — DA2: confirm-inheritance contract

**Status: RUNTIME DEFERRED**

Requires live runbook execution with POSITIVE (watchloop-wedged) and NEGATIVE (custom test runbook) cases.

**Reproduction recipe — POSITIVE (watchloop-wedged):**
1. `/arcis:operate runbook watchloop-wedged`
2. At Step 2 ask, pick "Approve — restart now".
3. PASS criteria: `arcis_operate.act.restart-watchloop.confirmed` event in audit log has `"inherited_from_runbook": true` (per Phase A4.1 contract-success path, lines 493-494).

**Reproduction recipe — NEGATIVE (custom test):**
1. Create temporary `runbooks/custom-restart-experiment.md` with a Step 2 ask that uses `"OK"` as the approve option (fails contract requirement iv).
2. `/arcis:operate runbook custom-restart-experiment`
3. PASS criteria: audit log has `arcis_operate.runbook.custom-restart-experiment.confirm_contract_failed_at_step_2` event with `failed_requirement: "(iv)_option_label_did_not_match_action"`; inner `act` Phase A4 fires fresh with full auth-matrix prompt.

The 5-point contract checklist is confirmed present in `commands/operate.md` Phase A4.1 (lines 486-496) and mirrored in `runbooks/watchloop-wedged.md` lines 105-110 ("Confirm-inheritance contract checklist").

---

## §12.10c — DA3: JSON injection safety

**Status: RUNTIME DEFERRED**

Requires live invocation with a crafted adversarial input string.

**Reproduction recipe:**
```bash
/arcis:operate triage 'she said "it'\''s broken" $(rm -rf /)'
```

PASS criteria:
1. `jq -c "select(.session_id == \"<INCIDENT_ID>\")" data/logs/tool-execution.log` returns valid JSON lines (no parse error).
2. The `symptom` field in the triage start event shows the literal string including `$(rm -rf /)` — not shell-expanded.
3. No filesystem side-effects (the `rm -rf /` is data, not executed).
4. If `jq` is unavailable on the operator's box (Windows default), the Python fallback `json.dumps` is used per `commands/operate.md` lines 792-794.

The DA3 mitigation is confirmed present in `commands/operate.md` lines 783-809 (AUDIT TRAIL CONVENTIONS > Layer 2 write mechanism). The `_execution_log.py` `__main__` CLI block (DA3 mitigator) is confirmed at `src/tools/_execution_log.py` line 202 (`if __name__ == "__main__"`).

---

## §12.10d — DA4: ≤3 binding prompts in worst-case triage

**Status: RUNTIME DEFERRED**

Requires live triage with unclear symptom + Modify selection + non-clear severity.

**Reproduction recipe:**
```bash
/arcis:operate triage "something weird is happening"
# (no keyword match → unclear domain → T2 disambig fires as checkpoint #1)
# At T2, pick "Modify — add or remove an agent" → sub-prompt fires (operator-initiated, NOT a new mandatory checkpoint)
# Severity != clear → T6 fires as checkpoint #3
```

PASS criteria: Total mandatory AskUserQuestion count = 3 (≤3 per DA4). The clarification note in `commands/operate.md` lines 229-230 explicitly states: "worst-case mandatory count: T2 disambig (1, if unclear) + T2 dispatch confirm (2) + T6 recommendation (3) = ≤3, within budget."

---

## §12.10e — DA5: Self-resolution downgrade

**Status: RUNTIME DEFERRED**

Requires mocking `healthprobe` to return `passed=false` then `passed=true` mid-triage.

**Reproduction recipe:**
1. Mock or simulate: first `healthprobe --service ArcisWatchLoop --json` returns `{"passed": false}`, 30s later returns `{"passed": true}`.
2. `/arcis:operate triage "watchloop not responding"`.
3. PASS criteria: After Phase T3 agent returns, Phase T4.5 re-check fires (line 333-350). Re-check detects the heartbeat is now fresh. Severity DOWNGRADED to `monitor`. T6 AskUserQuestion prompt becomes: "The primary symptom appears to have self-resolved during triage..."

The T4.5 re-check and downgrade logic is confirmed present in `commands/operate.md` lines 331-352.

---

## §12.10f — DA6: Incident-id collision

**Status: RUNTIME DEFERRED**

Requires concurrent shell invocations + manual `--incident-id` flag testing.

**Reproduction recipe — collision prevention:**
```bash
# Fire 2 triage in parallel (within same second):
/arcis:operate triage "test 1" &
/arcis:operate triage "test 2" &
wait
# grep for both incident IDs in audit log: must have different 6-hex suffixes
jq '.session_id' data/logs/tool-execution.log | sort | uniq
```

**Reproduction recipe — regex validation:**
```bash
/arcis:operate triage "test" --incident-id incident-bogus
# Expected: ERROR envelope — "unknown incident-id format: 'incident-bogus'. Expected: incident-YYYY-MM-DDTHH-MM-SSZ-XXXXXX"
```

The `secrets.token_hex(3)` collision-avoidance fix is confirmed present in `commands/operate.md` lines 35-38 (incident-id generation block). The regex validator is at lines 41-43.

---

## §12.10g — DA7: Runbook validation gate

**Status: RUNTIME DEFERRED**

Requires a synthetic malformed runbook file.

**Reproduction recipe:**
1. Create `runbooks/broken-frontmatter.md` with missing `mutations:` key (a required field).
2. `/arcis:operate runbook broken-frontmatter`.
3. PASS criteria: Graceful refuse with §10-class envelope (NOT a Python crash). `data/cache/runbooks/broken-frontmatter.validated` file created (or absent with FAIL result in validation log).

**Reproduction recipe — typo in required-tools:**
1. Create `runbooks/typo-test.md` with `required-tools: [capabilityregistryquery]` (wrong name — correct is `capabilityregistry`).
2. `/arcis:operate runbook typo-test`.
3. PASS criteria: validator catches the typo (Tier 3 availability probe can't resolve `capabilityregistryquery`) and refuses with appropriate warning.

The validator gate is confirmed in `commands/operate.md` Phase R2 (lines 648-676): "before parsing frontmatter, the orchestrator runs the §4 Runbook validation gate."

---

## §12.10h — DA8: Audit event prompt_hash + option_text

**Status: RUNTIME DEFERRED**

Requires live invocation of `act restart-watchloop` followed by audit log inspection.

**Reproduction recipe (outside overnight window):**
```bash
/arcis:operate act restart-watchloop
# At Phase A4 confirm, pick "Approve — execute"
jq -c 'select(.tool_name == "arcis_operate.act.restart-watchloop.confirmed")' data/logs/tool-execution.log
```

PASS criteria:
1. `prompt_hash` is a 16-char lowercase hex string matching `sha256(prompt prose shown)[:16]`.
2. `option_text` equals `"Approve — execute"` verbatim (the string the operator picked).

The DA8 fix is confirmed in `commands/operate.md` lines 476-482 (Phase A4 post-confirm event) and lines 815-819 (AUDIT TRAIL CONVENTIONS > prompt_hash + option_text section with the SHA-256 computation shell block).

---

## §12.10i — DA9: Abandonment recovery

**Status: RUNTIME DEFERRED**

Requires live runbook execution with mid-runbook cancellation.

**Reproduction recipe:**
1. `/arcis:operate runbook gpu-degraded`.
2. Allow Step 4 (`act restart-ollama-watchdog`) to execute.
3. Before Steps 5+6 (verify nvidia-smi + healthprobe) complete, cancel the runbook (simulate timeout or send cancel).
4. PASS criteria:
   - (i) Steps 5+6 attempted on best-effort 60s time-box (per `gpu-degraded.md` lines 174-175).
   - (ii) `arcis_operate.runbook.gpu-degraded.abandoned_after_mutation` event written with `last_mutation="Step 4 restart-ollama-watchdog"`.
   - (iii) Next `/arcis:operate status` within 24h shows the abandonment prompt: "Previous runbook gpu-degraded (incident <prior-id>) abandoned after mutation step 4; auto-verify result was..."

The abandonment recovery section is confirmed present in:
- `runbooks/gpu-degraded.md` lines 172-177 (Abandonment recovery section).
- `runbooks/watchloop-wedged.md` lines 182-188 (Abandonment recovery section — DA9).
- `commands/operate.md` lines 697-704 (Phase R3 mid-runbook abandonment recovery prose, general).

---

## §12.10j — DA10: Re-capture preview before execute

**Status: RUNTIME DEFERRED**

Requires live `act` invocation with an injected state change between A4 approval and A5.1 execution.

**Reproduction recipe:**
1. `/arcis:operate act restart-watchloop` (outside overnight window).
2. At Phase A4 confirm, pick "Approve — execute".
3. Between approval and A5.1 execution, manually stop ArcisWatchLoop via `sc stop ArcisWatchLoop`.
4. PASS criteria: Phase A5.1 re-runs the dry-run (lines 504-519), detects `would_do` diff (`would_do` changed from "Stop+Start" to "Start" since service is now stopped), fires re-approval `AskUserQuestion` with the diff shown.

The DA10 fix is confirmed in `commands/operate.md` Phase A5.1 (lines 503-521).

---

## §12.11 — All 5 runbooks parse (frontmatter validation)

**Status: STATIC PASS**

All 5 runbook YAML frontmatter blocks verified manually. Each has the spec §4 required keys.

### watchloop-wedged.md

File: `.claude/plugins/arcis/skills/operate/runbooks/watchloop-wedged.md` lines 1-27.

```yaml
name: watchloop-wedged         # PRESENT
verb: runbook                  # PRESENT
symptom-matchers: [...]        # PRESENT
required-tools: [processmanager, healthprobe, logtail]  # PRESENT
required-agents: [live-monitor]  # PRESENT (optional, present)
expected-duration: 5-10 min    # PRESENT
mutations: true                # PRESENT (boolean)
risk: medium                   # PRESENT (key is "risk", not "risk-level" — both spellings accepted per spec §4 note)
```

All required keys present. `mutations` is boolean `true`. No YAML syntax errors.

### pg-tests-red.md

File: `.claude/plugins/arcis/skills/operate/runbooks/pg-tests-red.md` lines 1-24.

```yaml
name: pg-tests-red             # PRESENT
verb: runbook                  # PRESENT
symptom-matchers: [...]        # PRESENT
required-tools: [ciinvestigate, dbquery, logtail, prcomments]  # PRESENT
required-agents: [ci-investigator, db-investigator]  # PRESENT
expected-duration: 10-20 min   # PRESENT
mutations: false               # PRESENT (boolean)
risk-level: low                # PRESENT (key is "risk-level")
```

All required keys present. `mutations` is boolean `false`. No YAML syntax errors.

### training-failed.md

File: `.claude/plugins/arcis/skills/operate/runbooks/training-failed.md` lines 1-25.

```yaml
name: training-failed          # PRESENT
verb: runbook                  # PRESENT
symptom-matchers: [...]        # PRESENT
required-tools: [processmanager, logtail, dbquery, tradingstate]  # PRESENT
required-agents: [live-monitor, db-investigator]  # PRESENT
expected-duration: 15-25 min   # PRESENT
mutations: false               # PRESENT (boolean)
risk-level: low                # PRESENT
```

All required keys present. `mutations` is boolean `false`. No YAML syntax errors.

### gpu-degraded.md

File: `.claude/plugins/arcis/skills/operate/runbooks/gpu-degraded.md` lines 1-28.

```yaml
name: gpu-degraded             # PRESENT
verb: runbook                  # PRESENT
symptom-matchers: [...]        # PRESENT
required-tools: [processmanager, healthprobe, logtail]  # PRESENT
required-agents: [live-monitor]  # PRESENT
expected-duration: 10-20 min   # PRESENT
mutations: true                # PRESENT (boolean)
risk: medium                   # PRESENT
risk-level: medium             # ALSO PRESENT (duplicate risk key — both spellings — see concern note below)
```

All required keys present. `mutations` is boolean `true`. Note: `gpu-degraded.md` has BOTH `risk: medium` (line 19) AND `risk-level: medium` (line 20). This is a minor spec concern (the validator checks for `risk-level OR risk` — having both is redundant but not breaking). No YAML syntax errors.

### data-anomaly.md

File: `.claude/plugins/arcis/skills/operate/runbooks/data-anomaly.md` lines 1-25.

```yaml
name: data-anomaly             # PRESENT
verb: runbook                  # PRESENT
symptom-matchers: [...]        # PRESENT
required-tools: [dbquery, capabilityregistry, logtail]  # PRESENT
required-agents: [db-investigator]  # PRESENT
expected-duration: 10-20 min   # PRESENT
mutations: false               # PRESENT (boolean)
risk-level: low                # PRESENT
```

All required keys present. `mutations` is boolean `false`. No YAML syntax errors.

---

## §12.12 — Sibling-search applied (cross-agent references)

**Status: STATIC PASS**

Verified by grepping all 5 runbook files for each agent name.

| Agent | watchloop-wedged | pg-tests-red | training-failed | gpu-degraded | data-anomaly |
|---|---|---|---|---|---|
| live-monitor | 9 mentions | 0 | 4 | 5 | 0 |
| db-investigator | 0 | 6 | 3 | 0 | 5 |
| ci-investigator | 0 | 7 | 0 | 0 | 0 |
| git-historian | 1 | 2 | 1 | 0 | 0 |

**All 4 agents are referenced in at least one runbook. No isolated silos.**

**Specific checks per spec:**

1. **`pg-tests-red.md` references git-historian** — CONFIRMED. `pg-tests-red.md` Escalation section (line 178): "run git-historian via `/arcis:operate triage` to identify the introducing commit." Also referenced inline at line 45: "that's git-historian's job for a different runbook."

2. **Each agent referenced at least once across the 5 runbooks** — CONFIRMED per table above.

3. **Mutating runbooks cross-reference live-monitor for pre-mutation diagnosis** — CONFIRMED: `watchloop-wedged` (Step 1 dispatches live-monitor before restart), `gpu-degraded` (Step 2 dispatches live-monitor before Ollama restart).

---

## §12.13 — Plugin registration

**Status: STATIC PASS**

File: `.claude/plugins/arcis/commands/operate.md` lines 1-4.

```yaml
---
name: operate
description: "Live-system incident response and change orchestration — triage symptoms, execute operator-confirmed mutations, run named runbooks. Composes 13 tools + 4 investigator agents."
---
```

Frontmatter is valid YAML. Both `name` and `description` keys are present. The `name: operate` key is what the plugin system uses to register `/arcis:operate` as a discoverable command.

**Runtime confirmation recipe:**
```
/help
```
Expected: `/arcis:operate` appears in the command listing.

---

## §12.14 — CHANGELOG entry

**Status: STATIC PASS**

File: `CHANGELOG.md` — the v0.36.67 section added in this T10 task.

The entry header reads:
```
## [v0.36.67] — 2026-05-26 — `/arcis:operate` skill — incident response + change orchestration (#109)
```

The Added section includes:
```
- **Skill: `/arcis:operate` ships with 4 verbs + 5 runbooks** (#109).
```

This matches the spec §12.14 requirement: "v0.36.6X entry mentions 'Skill: `/arcis:operate` ships with 4 verbs + 5 runbooks'."

Grep confirmation: `grep "ships with 4 verbs + 5 runbooks" CHANGELOG.md` returns the Added bullet.

---

## Summary Table

| Item | Status | Method |
|---|---|---|
| §12.1 Cold-read | RUNTIME DEFERRED | Fresh session test |
| §12.2 Verb-unknown | STATIC PASS | `commands/operate.md:52` vs `error-envelopes.md §10.1` — exact match |
| §12.3 Refuse-in-window | RUNTIME DEFERRED | `ARCIS_NOW_ET_OVERRIDE` + live act |
| §12.4 Emergency override | RUNTIME DEFERRED | `ARCIS_NOW_ET_OVERRIDE` + `--emergency` |
| §12.5 Tier 3 degradation | RUNTIME DEFERRED | Transient runbook edit + live invocation |
| §12.6 Audit-log presence | STATIC PASS | `commands/operate.md:119` (start) + `:412/:561/:722` (completed) |
| §12.7 Status fast-path | RUNTIME DEFERRED | `time /arcis:operate status` |
| §12.8 Runbook resolution | RUNTIME DEFERRED | Live `runbook nonexistent` + `--dry-run` |
| §12.9 Cross-agent composition | RUNTIME DEFERRED | Live triage with 2+ agents |
| §12.10 No-deferral | RUNTIME DEFERRED | Live triage with 8+ findings |
| §12.10a DA1 | RUNTIME DEFERRED | ET override + long act |
| §12.10b DA2 | RUNTIME DEFERRED | POSITIVE + NEGATIVE runbook chain |
| §12.10c DA3 | RUNTIME DEFERRED | Adversarial symptom string |
| §12.10d DA4 | RUNTIME DEFERRED | Unclear symptom + Modify + non-clear severity |
| §12.10e DA5 | RUNTIME DEFERRED | Mock healthprobe self-resolve |
| §12.10f DA6 | RUNTIME DEFERRED | Concurrent invocations + bad `--incident-id` |
| §12.10g DA7 | RUNTIME DEFERRED | Malformed runbook file |
| §12.10h DA8 | RUNTIME DEFERRED | Live act + audit log grep |
| §12.10i DA9 | RUNTIME DEFERRED | Mid-runbook cancel after mutation |
| §12.10j DA10 | RUNTIME DEFERRED | State-change injection between A4 and A5.1 |
| §12.11 All 5 runbooks parse | STATIC PASS | Frontmatter verified for all 5 runbook files |
| §12.12 Sibling-search | STATIC PASS | Agent cross-reference grep table (all 4 agents referenced) |
| §12.13 Plugin registration | STATIC PASS | `commands/operate.md:1-4` — valid YAML frontmatter |
| §12.14 CHANGELOG entry | STATIC PASS | `CHANGELOG.md` v0.36.67 section — "4 verbs + 5 runbooks" present |

**Static passes: 5 of 24**
**Runtime deferred: 19 of 24**

The 5 static passes are deterministically verifiable from file content. The 19 runtime-deferred items require a live Claude Code session; the reproduction recipes above provide operator-executable verification steps.

---

## Notes and Concerns

1. **`gpu-degraded.md` duplicate risk keys** — The frontmatter has both `risk: medium` (line 19) and `risk-level: medium` (line 20). Both spellings are accepted by the spec §4 schema (`risk-level OR risk`). Having both is redundant but not a validator failure. Recommendation: clean up to a single key in a follow-up edit.

2. **`test_version.py` companion update** — `tests/test_version.py` hardcodes the version literals and its own docstring states "Update the literals as part of every release PR." The sprint base's #117 hotfix bumped `src/version.py` to v0.36.66 without updating `test_version.py` (pre-existing drift), causing 3 failing tests before T10 changes. This T10 task updated `test_version.py` to v0.36.67 to fix the pre-existing failure alongside the version bump. This file was not listed in FILES_IN_SCOPE — flagged to PM.
