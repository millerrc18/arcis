---
verb: curate-memory
risk-level: low
mutations: false
ci-eligible: false
required-tools: []
required-agents: [research-cross-domain-analyst]
expected-duration-sec: 30
references:
  - .claude/plugins/arcis/skills/periodic-discipline/references/scanners.md
  - .claude/plugins/arcis/skills/periodic-discipline/references/findings-schema.md
  - .claude/plugins/arcis/skills/periodic-discipline/references/lockfile.md
---

# Curate-Memory Runbook

Detect operator-memory hygiene issues: duplicate topics, stale entries (>90 days untouched),
and LLM contradiction scan (advisory).

**CI-eligible: NO.** The memory tree lives at
`$HOME/.claude/projects/c--arcis/memory/` — operator-machine-local, outside the repo.
This runbook refuses to run in CI (`GITHUB_ACTIONS` env var check in preamble).

**Self-exclusion contract:** All scanners exclude `.claude/plugins/arcis/skills/periodic-discipline/**`.

**Windows `find -mtime` note:** The `stale_entry` scanner uses `find -mtime +90`.
On Windows, run this runbook via Git Bash or WSL for correct POSIX mtime semantics.
In a native Windows CMD/PowerShell shell, `find` semantics differ; the scanner may
emit false-positives or miss genuinely stale files.

---

## Preamble

```bash
set -euo pipefail

VERB="curate-memory"
INVOCATION_ID="PD-${VERB}-$(uuidgen | cut -c1-8)"
LOCKFILE="data/periodic-discipline/.lock"
START_EPOCH=$(date +%s)
PD_TS="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
export ARCIS_SESSION_ID="$INVOCATION_ID"
export INVOCATION_ID
export PD_TS

# Refuse in CI — memory tree is operator-machine-local
if [ -n "${GITHUB_ACTIONS:-}" ]; then
  echo "curate-memory requires local memory tree — refused in CI" >&2
  exit 1
fi

# Resolve memory directory
MEMORY_DIR="${ARCIS_MEMORY_DIR:-$HOME/.claude/projects/c--arcis/memory}"
if [ ! -d "$MEMORY_DIR" ]; then
  echo "Memory tree not found at $MEMORY_DIR — refusing" >&2
  echo "Set ARCIS_MEMORY_DIR env var to override the default path." >&2
  exit 1
fi
export MEMORY_DIR

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
  --tool-name "arcis_periodic_discipline.curate-memory.start" \
  --result success --duration-ms 0 --session-id "$INVOCATION_ID" \
  || { echo "WARNING — audit-log start failed" >&2; }
```

---

## Scanner 1: duplicate_topic

Detect memory filenames that share a topic suffix after stripping the standard category
prefixes (`feedback_`, `project_`, `reference_`, `user_`). Two files with the same
bare topic are consolidation candidates.

This is a heuristic — topic detection is based on filename patterns, not semantic
content analysis. Expect some false-positives for legitimately distinct files that
happen to share a word. Suppress via allowlist if needed.

```bash
ls "$MEMORY_DIR"/*.md 2>/dev/null \
  | xargs -I{} basename {} .md \
  | sed -E 's/^(feedback_|project_|reference_|user_)//' \
  | sort | uniq -c | awk '$1 > 1 {print $2}' \
  | while read -r topic; do
      jq -nc --arg topic "$topic" --arg ts "$PD_TS" \
        '{invocation_id: env.INVOCATION_ID, verb: "curate-memory", scanner: "duplicate_topic", root_cause_key: ("memory:duplicate:" + $topic), severity: "minor", first_seen_utc: $ts, advisory: false, payload: {topic: $topic, note: "heuristic: filename-prefix-stripped topic appears in more than one memory file"}}' \
        >> "$RAW"
    done
```

---

## Scanner 2: stale_entry

Flag memory files not touched in more than 90 days. Stale entries may describe
superseded incidents, resolved bugs, or outdated operator preferences.

Per DD2 in the design spec: opt-out only via allowlist. No auto-decay. A finding
persists until fixed or explicitly allowlisted with a rationale.

Add `memory:stale:<filename-without-.md>` to `allowlist.yaml` for entries you have
reviewed and intentionally keep (e.g., foundational operator preferences that rarely
change but must persist). Include a brief rationale.

```bash
find "$MEMORY_DIR" -name '*.md' -mtime +90 -type f 2>/dev/null \
  | while read -r f; do
      bn=$(basename "$f" .md)
      jq -nc --arg file "$bn" --arg ts "$PD_TS" \
        '{invocation_id: env.INVOCATION_ID, verb: "curate-memory", scanner: "stale_entry", root_cause_key: ("memory:stale:" + $file), severity: "minor", first_seen_utc: $ts, advisory: false, payload: {file: $file}}' \
        >> "$RAW"
    done
```

---

## Scanner 3: memory_contradiction (Advisory)

Detect contradictions within the operator-memory corpus — e.g., two memory files that
give conflicting advice about the same workflow, or a newer entry that implicitly
supersedes an older one without removing it.

**Advisory marker:** `advisory: true` — CI does not count these toward state transitions.

**Why bash can't dispatch the agent:** Same as `llm_contradiction` in `audit-skills`.
The runbook emits a placeholder advisory finding. The SKILL.md layer dispatches
the agent separately and merges results into the report post-hoc.

**SKILL.md dispatch contract:**
```
Agent(subagent_type: "research-cross-domain-analyst")
  DYNAMIC CONTEXT:
    DOMAIN_REPORTS: <concatenated text of $MEMORY_DIR/*.md>
    ORIGINAL_QUERY: "Identify logical contradictions, conflicting guidance, or entries that appear to supersede each other within this operator-memory corpus."
    OUTPUT_FORMAT: JSON array of {entry_a, entry_b, conflict_description, confidence: High|Moderate|Low}
```

Each contradiction maps to `scanner: "memory_contradiction"`, `advisory: true`,
`severity: "minor"`, `root_cause_key: "memory_contradiction:<truncated_sha1_of_pair>"`.

See `references/scanners.md §memory_contradiction` for the full dispatch spec.

```bash
# Placeholder for advisory memory contradiction scan
# Actual agent dispatch happens at SKILL.md layer; results merged post-hoc
jq -nc --arg ts "$PD_TS" \
  '{invocation_id: env.INVOCATION_ID, verb: "curate-memory", scanner: "memory_contradiction", root_cause_key: "advisory:placeholder", severity: "minor", first_seen_utc: $ts, advisory: true, payload: {note: "Memory contradiction scan dispatched separately at skill invocation layer"}}' \
  >> "$RAW"
```

---

## Postamble

```bash
# Capture raw count BEFORE deleting the file
RAW_COUNT=$(jq 'length' "$RAW")

# --- Dedup: earliest occurrence per root_cause_key wins ---
jq -s 'group_by(.root_cause_key) | map(.[0])' "$RAW" > "$REPORT"
rm -f "$RAW"

DEDUPED_COUNT=$(jq 'length' "$REPORT")

# --- Allowlist filter ---
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
    findings = json.load(open(report_path, encoding='utf-8'))
    findings.append({'invocation_id': invocation_id, 'verb': 'curate-memory', 'scanner': 'allowlist_malformed', 'root_cause_key': 'allowlist:malformed', 'severity': 'critical', 'first_seen_utc': ts, 'advisory': False, 'payload': {'error': str(e)}})
    json.dump(findings, open(report_path, 'w', encoding='utf-8'), indent=2)
    print(0)
except FileNotFoundError:
    print(0)
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
    --tool-name "arcis_periodic_discipline.curate-memory.end" \
    --result success \
    --duration-ms "$(($(date +%s) - START_EPOCH))" \
    --session-id "$INVOCATION_ID" \
  || { echo "WARNING — audit-log end failed" >&2; }

# --- Stdout summary ---
if [ "$FINAL_COUNT" -eq 0 ]; then
  echo ""
  echo "periodic-discipline [curate-memory] — $INVOCATION_ID"
  echo "  All clear."
  echo ""
  echo "  Report: $REPORT"
else
  CRITICAL=$(jq '[.[] | select(.severity=="critical" and .advisory==false)] | length' "$REPORT")
  MAJOR=$(jq '[.[] | select(.severity=="major" and .advisory==false)] | length' "$REPORT")
  MINOR=$(jq '[.[] | select(.severity=="minor" and .advisory==false)] | length' "$REPORT")
  ADVISORY=$(jq '[.[] | select(.advisory==true)] | length' "$REPORT")
  echo ""
  echo "periodic-discipline [curate-memory] — $INVOCATION_ID"
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
