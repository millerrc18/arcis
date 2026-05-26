# Findings Schema Reference

JSON finding shape, dedup contract, severity rubric, advisory marker, and allowlist semantics for the `periodic-discipline` skill.

---

## Finding Shape

Every finding emitted by any scanner is a JSON object conforming to this shape:

```json
{
  "invocation_id": "PD-audit-skills-a1b2c3d4",
  "verb": "audit-skills",
  "scanner": "subagent_unresolved",
  "root_cause_key": "agent:research-cross-domain-analyst",
  "severity": "major",
  "first_seen_utc": "2026-05-26T14:00:00Z",
  "advisory": false,
  "payload": {
    "agent": "research-cross-domain-analyst",
    "refs": ["skills/foo.md:42", "skills/bar.md:17"]
  }
}
```

### Field Definitions

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `invocation_id` | string | yes | Ties this finding to its log slice. Format: `PD-<verb>-<8hex>`. |
| `verb` | string | yes | Which audit verb produced this finding: `audit-skills` \| `curate-memory` \| `test-tools`. |
| `scanner` | string | yes | Which scanner within the verb produced this finding (e.g., `file_line_drift`, `subagent_unresolved`). |
| `root_cause_key` | string | yes | Dedup primary key. Namespaced by scanner prefix (e.g., `agent:`, `docconsistency:`, `tool_module:`, `decorator_chain:`, `boundary_test:`, `memory_dup:`, `memory_stale:`, `memory_contradiction:`, `llm_contradiction:`). |
| `severity` | string | yes | One of: `critical` \| `major` \| `minor` \| `info`. See severity rubric below. |
| `first_seen_utc` | string | yes | ISO 8601 UTC timestamp when this finding was first emitted in this run. Format: `YYYY-MM-DDTHH:MM:SSZ`. |
| `advisory` | boolean | yes | `true` for LLM-derived findings (non-deterministic). CI does not count advisory findings toward state transitions. |
| `payload` | object | yes | Scanner-specific detail. Shape varies by scanner; see `references/scanners.md` for per-scanner payload shapes. |

---

## root_cause_key Dedup Contract

`root_cause_key` is the dedup primary key. Multiple surface symptoms with the same root cause (e.g., 5 skill files referencing the same missing agent) collapse to a single finding.

**Dedup operation (in runbook postamble):**

```bash
jq -s 'group_by(.root_cause_key) | map(.[0])' "$REPORT.raw" > "$REPORT"
```

This keeps the first occurrence per key (insertion order = scanner emit order). The `payload.refs` field in the surviving record should be accumulated across raw findings before dedup — scanners that emit multiple findings for the same root cause should either accumulate refs into a single emit or accept that only the first payload survives.

**Diagnostic counters** — the postamble also writes these to the audit-log event:

```bash
raw_count=$(jq 'length' "$REPORT.raw" 2>/dev/null || echo 0)
deduped_count=$(jq 'length' "$REPORT" 2>/dev/null || echo 0)
```

Both `raw_finding_count` and `root_cause_count` are logged in the skill-layer audit event so the operator can see how much collapse occurred.

---

## Severity Rubric

| Severity | Meaning | Examples |
|----------|---------|---------|
| `critical` | Runtime breakage today — the system is currently broken or will break on the next execution | Tool CLI missing required decorator (`cli_decorator_chain`); CI workflow / runbook parity drift (`workflow_parity`); audit-log missing (`log_missing`); allowlist malformed (`allowlist_malformed`) |
| `major` | Drift that will break soon — not broken today but will cause failures as the infrastructure evolves | Broken file:line xref (`file_line_drift`); dead agent name in skill file (`subagent_unresolved`); missing tool module (`tool_module_missing`); missing boundary test (`boundary_test_missing`); duplicate memory root_cause_key (`duplicate_root_cause_key`) |
| `minor` | Cosmetic / style issues or LLM-advisory findings — no immediate breakage risk | Stale memory entry (`stale_entry`); LLM-identified contradiction (`llm_contradiction`, `memory_contradiction`) |
| `info` | Opt-in nudges — informational, does not indicate a defect | (Future: one info finding per run listing memory categories without decay coverage, if applicable) |

---

## Advisory Marker

LLM-derived findings carry `"advisory": true`. This applies to:

- `llm_contradiction` (from `audit-skills`)
- `memory_contradiction` (from `curate-memory`)

**Advisory semantics:**

1. The stdout summary shows advisory findings in a separate section: `Advisory findings (LLM-derived): N`
2. The CI workflow does **not** count advisory findings toward state transitions — the workflow stays GREEN even when N > 0
3. The operator reviews advisory findings alongside non-advisory findings in the JSON report; they are not suppressed, only segregated

**Why non-determinism is safe here:** The `research-cross-domain-analyst` agent may produce different contradiction findings across runs. The advisory marker isolates this non-determinism from the deterministic scanner output. Operators should expect some churn in advisory finding counts — do not allowlist an advisory finding unless the same `root_cause_key` appears in 3+ consecutive runs.

---

## Allowlist Suppression Semantics

The allowlist (`allowlist.yaml` at the skill root) is an opt-in exemption mechanism. An allowlisted `root_cause_key` is suppressed from the final report.

**Suppression timing:** Allowlist filtering happens AFTER dedup. The postamble sequence is:

1. `jq -s 'group_by(.root_cause_key) | map(.[0])'` — dedup
2. Apply allowlist filter — suppress matching keys
3. Write final `$REPORT`

**Suppression is logged:** The allowlist filter records `suppressed_count` in the skill-layer audit event so the operator can see how many findings were suppressed.

**Allowlist format:**

```yaml
keys:
  - agent:research-cross-domain-analyst-OLD-NAME  # rationale: renamed 2026-05-20, pending sweep in #NNN
  - docconsistency:CLAUDE.md:42                   # rationale: false positive — points to known-good anchor ref
```

Every entry MUST have a rationale comment. The allowlist file is reviewed alongside findings PRs.

**Allowlist malformed handling:** If the allowlist YAML fails to parse (malformed syntax, missing `keys:` field, non-list value), the runbook proceeds with an empty allowlist (no suppressions) and emits an additional finding:

```json
{
  "scanner": "allowlist_malformed",
  "root_cause_key": "allowlist_malformed:parse_error",
  "severity": "critical",
  "advisory": false,
  "payload": {"error": "<yaml parse error message>"}
}
```

The verb is never refused due to allowlist parse failure. The report (including the `allowlist_malformed` finding) is the recovery surface.

---

## Decay Policy

**Opt-in only — no auto-decay.**

Findings persist until one of two conditions is met:

1. The underlying drift is fixed (the next run will not reproduce the finding)
2. The operator explicitly adds the `root_cause_key` to `allowlist.yaml` with a rationale comment

There is no time-based or severity-based automatic suppression. An entry never silently disappears. This honors the operator's strict-rigor preference: silent suppression is worse than persistent surfacing.

**Rationale (DD2):** Time-based auto-decay was identified as a major risk during design review. An allowlist entry is a conscious decision with a paper trail; a time-expired suppression is not.

---

## Stdout Summary Format

The runbook postamble prints a human-readable summary to stdout after writing the JSON report:

```
periodic-discipline [audit-skills] — PD-audit-skills-a1b2c3d4
  Raw findings:    12
  After dedup:      8
  Suppressed:       2
  Final findings:   6

  critical:  1
  major:     4
  minor:     1

  Advisory findings (LLM-derived): 3

  Report: data/periodic-discipline/reports/PD-audit-skills-a1b2c3d4.json
```

When `final findings == 0` (after dedup and suppression): print `All clear.` instead of the breakdown table.
