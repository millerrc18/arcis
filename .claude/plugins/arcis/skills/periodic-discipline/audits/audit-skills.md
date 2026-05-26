---
verb: audit-skills
risk-level: low
mutations: false
required-tools: [docconsistency]
required-agents: [research-cross-domain-analyst]
expected-duration-sec: 60
references:
  - .claude/plugins/arcis/skills/periodic-discipline/references/scanners.md
  - .claude/plugins/arcis/skills/periodic-discipline/references/findings-schema.md
  - .claude/plugins/arcis/skills/periodic-discipline/references/lockfile.md
---

# Audit-Skills Runbook

Detect drift in skill and command files: broken file:line references, dead agent names,
missing tool modules, CI/runbook parity, and LLM contradictions.

**Self-exclusion contract:** All scanners exclude `.claude/plugins/arcis/skills/periodic-discipline/**`.
This skill does not audit its own files.

---

## Preamble

```bash
set -euo pipefail

VERB="audit-skills"
INVOCATION_ID="PD-${VERB}-$(uuidgen | cut -c1-8)"
LOCKFILE="data/periodic-discipline/.lock"
START_EPOCH=$(date +%s)
PD_TS="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
export ARCIS_SESSION_ID="$INVOCATION_ID"
export INVOCATION_ID
export PD_TS

mkdir -p data/periodic-discipline/reports

if [ -f "$LOCKFILE" ] && kill -0 "$(head -1 "$LOCKFILE")" 2>/dev/null; then
  echo "periodic-discipline already running (pid=$(head -1 "$LOCKFILE"), started=$(tail -1 "$LOCKFILE"))" >&2
  exit 1
fi

printf '%s\n%s\n' "$$" "$PD_TS" > "$LOCKFILE"
trap "rm -f '$LOCKFILE'" EXIT

REPORT="data/periodic-discipline/reports/${INVOCATION_ID}.json"
RAW="${REPORT}.raw"
: > "$RAW"

# Audit-log bracket-start
printf '{}' | python -m src.tools._execution_log \
  --tool-name "arcis_periodic_discipline.audit-skills.start" \
  --result success --duration-ms 0 --session-id "$INVOCATION_ID" \
  || { echo "WARNING — audit-log start failed" >&2; }
```

---

## Scanner 1: file_line_drift

Invoke `docconsistency scan` against the arcis skills and commands directory tree.
Filter out findings about this skill's own directory (self-exclusion contract).

Note: the CLI flag is `--target` (repeatable), NOT `--paths`. Verified from
`src/tools/docconsistency/__main__.py` line 66: `scan_parser.add_argument("--target", action="append", ...)`.

```bash
python -m src.tools.docconsistency scan --json \
  --target '.claude/plugins/arcis/skills' \
  --target '.claude/plugins/arcis/commands' \
  | jq -c --arg ts "$PD_TS" '
      .findings[]?
      | select(.doc_path | test("periodic-discipline") | not)
      | {
          invocation_id: env.INVOCATION_ID,
          verb: "audit-skills",
          scanner: "file_line_drift",
          root_cause_key: ("docconsistency:" + .doc_path + ":" + (.doc_line | tostring)),
          severity: (.severity // "major"),
          first_seen_utc: $ts,
          advisory: false,
          payload: .
        }' \
  >> "$RAW"
```

---

## Scanner 2: subagent_unresolved

Detect `subagent_type` references in skills and commands that point to an agent name
not backed by any real agent file. Discovers correct names via frontmatter `name:` field
parsing — generic resolver, not hardcoded mapping.

```bash
# Build set of valid agent names from frontmatter `name:` field of every agent .md
VALID_AGENTS=$(python -c "
import yaml, glob
names = []
for p in glob.glob('.claude/plugins/arcis/agents/*.md'):
    try:
        parts = open(p, encoding='utf-8').read().split('---', 2)
        if len(parts) >= 3:
            fm = yaml.safe_load(parts[1]) or {}
            if 'name' in fm:
                names.append(fm['name'])
    except Exception:
        pass
print(' '.join(sorted(set(names))))
")

# Extract every subagent_type reference and verify against valid set
grep -rhE 'subagent_type[: =]"[a-z][a-z0-9_-]*"' \
  .claude/plugins/arcis/skills/ \
  .claude/plugins/arcis/commands/ 2>/dev/null \
  | grep -v 'periodic-discipline/' \
  | sed -E 's/.*"([a-z][a-z0-9_-]*)".*/\1/' \
  | sort -u \
  | while read -r agent; do
      if [ -n "$agent" ] && ! echo " $VALID_AGENTS " | grep -q " $agent "; then
        jq -nc --arg agent "$agent" --arg ts "$PD_TS" \
          '{invocation_id: env.INVOCATION_ID, verb: "audit-skills", scanner: "subagent_unresolved", root_cause_key: ("agent:" + $agent), severity: "major", first_seen_utc: $ts, advisory: false, payload: {agent: $agent}}' \
          >> "$RAW"
      fi
    done
```

---

## Scanner 3: tool_module_missing

Detect `python -m src.tools.<name>` invocations that reference a tool module without
a `__main__.py`. Skip `_`-prefixed entries (shared infra like `_execution_log`) —
those are modules, not subcommand tools.

```bash
grep -rhEo 'python -m src\.tools\.[a-z_][a-z0-9_]*' \
  .claude/plugins/arcis/skills/ \
  .claude/plugins/arcis/commands/ 2>/dev/null \
  | grep -v 'periodic-discipline/' \
  | sed -E 's/.*src\.tools\.([a-z_][a-z0-9_]*)$/\1/' \
  | sort -u \
  | while read -r tool; do
      if [ -n "$tool" ] && [ ! -f "src/tools/$tool/__main__.py" ]; then
        # Skip _-prefixed shared infra (e.g., _execution_log) — they're modules, not subcommand tools
        if [ "${tool:0:1}" != "_" ]; then
          jq -nc --arg tool "$tool" --arg ts "$PD_TS" \
            '{invocation_id: env.INVOCATION_ID, verb: "audit-skills", scanner: "tool_module_missing", root_cause_key: ("tool:" + $tool), severity: "major", first_seen_utc: $ts, advisory: false, payload: {tool: $tool}}' \
            >> "$RAW"
        fi
      fi
    done
```

---

## Scanner 4: workflow_parity

Compare `python -m src.tools.<n>` invocations between the periodic-discipline CI workflow
and each verb's runbook. Detects drift between the two execution surfaces.

If the workflow file does not yet exist (e.g., before Task 3 ships), exit cleanly — no finding.

```bash
python -c "
import re, json, os, sys
from pathlib import Path

ts = os.environ.get('PD_TS', '')
invocation_id = os.environ.get('INVOCATION_ID', '')

def extract_tool_invocations(text):
    return sorted(set(re.findall(r'python -m src\.tools\.([a-z_][a-z0-9_]*)', text)))

wf_path = Path('.github/workflows/periodic-discipline.yml')
if not wf_path.exists():
    # Workflow not yet created (e.g., before T3) — no finding, exit cleanly
    sys.exit(0)

wf_tools = extract_tool_invocations(wf_path.read_text(encoding='utf-8'))

for verb in ['audit-skills', 'curate-memory', 'test-tools']:
    rb_path = Path(f'.claude/plugins/arcis/skills/periodic-discipline/audits/{verb}.md')
    if not rb_path.exists():
        continue
    rb_tools = extract_tool_invocations(rb_path.read_text(encoding='utf-8'))
    missing_in_wf = set(rb_tools) - set(wf_tools)
    missing_in_rb = set(wf_tools) - set(rb_tools)
    for tool in sorted(missing_in_wf):
        print(json.dumps({'invocation_id': invocation_id, 'verb': 'audit-skills', 'scanner': 'workflow_parity', 'root_cause_key': f'workflow_drift:{verb}:{tool}:missing_in_workflow', 'severity': 'critical', 'first_seen_utc': ts, 'advisory': False, 'payload': {'verb': verb, 'tool': tool, 'direction': 'missing_in_workflow'}}))
    for tool in sorted(missing_in_rb):
        print(json.dumps({'invocation_id': invocation_id, 'verb': 'audit-skills', 'scanner': 'workflow_parity', 'root_cause_key': f'workflow_drift:{verb}:{tool}:missing_in_runbook', 'severity': 'critical', 'first_seen_utc': ts, 'advisory': False, 'payload': {'verb': verb, 'tool': tool, 'direction': 'missing_in_runbook'}}))
" >> "$RAW"
```

---

## Scanner 5: llm_contradiction (Advisory)

Detect logical contradictions in the skill and command corpus via the
`research-cross-domain-analyst` agent. This is an ADVISORY scanner — findings carry
`advisory: true` and are NOT counted toward CI state transitions.

**Why bash can't dispatch the agent:** Runbook fenced bash executes in a subprocess
shell. It cannot instantiate `Agent(subagent_type=...)` — that is a SKILL.md-layer
capability. The runbook emits a placeholder advisory finding. The SKILL.md layer
dispatches the agent separately and merges results into the report post-hoc.

**SKILL.md dispatch contract:**
```
Agent(subagent_type: "research-cross-domain-analyst")
  DYNAMIC CONTEXT:
    DOMAIN_REPORTS: <concatenated text of .claude/plugins/arcis/{skills,commands}/**/*.md>
    ORIGINAL_QUERY: "Identify logical contradictions, conflicting instructions, or inconsistent guidance within this corpus of arcis skill and command files."
    OUTPUT_FORMAT: JSON array of {claim_a, claim_b, location_a, location_b, severity: high|medium|low, confidence: High|Moderate|Low}
```

Each contradiction maps to a finding with `scanner: "llm_contradiction"`, `advisory: true`,
`severity: "minor"`, and `root_cause_key: "llm_contradiction:<truncated_sha1_of_sorted_claim_pair>"`.

See `references/scanners.md §llm_contradiction` for the full dispatch spec.

```bash
# Placeholder for advisory LLM contradiction scan
# Actual agent dispatch happens at SKILL.md layer; results merged post-hoc
jq -nc --arg ts "$PD_TS" \
  '{invocation_id: env.INVOCATION_ID, verb: "audit-skills", scanner: "llm_contradiction", root_cause_key: "advisory:placeholder", severity: "minor", first_seen_utc: $ts, advisory: true, payload: {note: "LLM contradiction scan dispatched separately at skill invocation layer"}}' \
  >> "$RAW"
```

---

## Postamble

Dedup by `root_cause_key`, apply allowlist filter, rotate old reports, write bracket-end
audit event, print stdout summary.

```bash
# --- Dedup: earliest occurrence per root_cause_key wins ---
jq -s 'group_by(.root_cause_key) | map(.[0])' "$RAW" > "$REPORT"
rm -f "$RAW"

RAW_COUNT=$(jq 'length' "${REPORT}.raw" 2>/dev/null || echo 0)
DEDUPED_COUNT=$(jq 'length' "$REPORT")

# --- Allowlist filter ---
# Malformed allowlist → emit critical finding, run with empty allowlist
SUPPRESSED_COUNT=0
python -c "
import yaml, json, sys, os
ALLOWLIST_PATH = '.claude/plugins/arcis/skills/periodic-discipline/allowlist.yaml'
report_path = os.environ['REPORT']
ts = os.environ.get('PD_TS', '')
invocation_id = os.environ.get('INVOCATION_ID', '')
try:
    raw_yaml = open(ALLOWLIST_PATH, encoding='utf-8').read()
    allow = set((yaml.safe_load(raw_yaml) or {}).get('keys', []))
    findings = json.load(open(report_path, encoding='utf-8'))
    filtered = [f for f in findings if f.get('root_cause_key') not in allow]
    suppressed = len(findings) - len(filtered)
    json.dump(filtered, open(report_path, 'w', encoding='utf-8'), indent=2)
    print(suppressed)
except yaml.YAMLError as e:
    # Malformed allowlist — emit critical finding, run with empty allowlist
    findings = json.load(open(report_path, encoding='utf-8'))
    findings.append({'invocation_id': invocation_id, 'verb': 'audit-skills', 'scanner': 'allowlist_malformed', 'root_cause_key': 'allowlist:malformed', 'severity': 'critical', 'first_seen_utc': ts, 'advisory': False, 'payload': {'error': str(e)}})
    json.dump(findings, open(report_path, 'w', encoding='utf-8'), indent=2)
    print(0)
except FileNotFoundError:
    print(0)  # No allowlist file = empty allowlist, 0 suppressed
" > /tmp/pd_suppressed.txt
SUPPRESSED_COUNT=$(cat /tmp/pd_suppressed.txt)
rm -f /tmp/pd_suppressed.txt

FINAL_COUNT=$(jq 'length' "$REPORT")

# --- Rotate reports older than 30 days ---
find data/periodic-discipline/reports -type f -mtime +30 -name '*.json' -delete 2>/dev/null || true

# --- Audit-log bracket-end ---
printf '{"raw_finding_count": %s, "root_cause_count": %s, "suppressed_count": %s}' \
  "$RAW_COUNT" "$DEDUPED_COUNT" "$SUPPRESSED_COUNT" \
  | python -m src.tools._execution_log \
    --tool-name "arcis_periodic_discipline.audit-skills.end" \
    --result success \
    --duration-ms "$(($(date +%s) - START_EPOCH))" \
    --session-id "$INVOCATION_ID" \
  || { echo "WARNING — audit-log end failed" >&2; }

# --- Stdout summary ---
if [ "$FINAL_COUNT" -eq 0 ]; then
  echo ""
  echo "periodic-discipline [audit-skills] — $INVOCATION_ID"
  echo "  All clear."
  echo ""
  echo "  Report: $REPORT"
else
  CRITICAL=$(jq '[.[] | select(.severity=="critical" and .advisory==false)] | length' "$REPORT")
  MAJOR=$(jq '[.[] | select(.severity=="major" and .advisory==false)] | length' "$REPORT")
  MINOR=$(jq '[.[] | select(.severity=="minor" and .advisory==false)] | length' "$REPORT")
  ADVISORY=$(jq '[.[] | select(.advisory==true)] | length' "$REPORT")
  echo ""
  echo "periodic-discipline [audit-skills] — $INVOCATION_ID"
  echo "  Raw findings:    $RAW_COUNT"
  echo "  After dedup:     $DEDUPED_COUNT"
  echo "  Suppressed:      $SUPPRESSED_COUNT"
  echo "  Final findings:  $FINAL_COUNT"
  echo ""
  echo "  critical:  $CRITICAL"
  echo "  major:     $MAJOR"
  echo "  minor:     $MINOR"
  echo ""
  echo "  Advisory findings (LLM-derived): $ADVISORY"
  echo ""
  echo "  Report: $REPORT"
fi
```
