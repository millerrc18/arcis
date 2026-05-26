---
verb: full
risk-level: low
mutations: false
required-tools: [docconsistency]
required-agents: [research-cross-domain-analyst]
expected-duration-sec: 180
ci-eligible: false  # curate-memory requires local memory tree
references:
  - audit-skills.md
  - curate-memory.md
  - test-tools.md
---

# Full Orchestrator Runbook

Runs all three verbs sequentially with ONE shared invocation_id:

```
audit-skills → curate-memory → test-tools
```

Produces a combined JSON report containing every finding from all three sub-verbs.

**CI-eligible: NO.** The `curate-memory` sub-verb requires the local memory tree
(`$HOME/.claude/projects/c--arcis/memory/`). The preamble below refuses to run in
`GITHUB_ACTIONS` environments, mirroring the `curate-memory.md` guard.

---

## Orchestration Contract

The SKILL.md routing layer implements the `full` verb as follows:

1. **Acquire lockfile once** using the standard PID-lockfile convention (see
   `references/lockfile.md`). The single lockfile persists across all three
   sub-verb executions — sub-verb runbooks are NOT invoked as independent
   processes (they would re-acquire the same lockfile and fail).

2. **Source each sub-verb's bash blocks in order.** The extraction idiom below
   strips the sub-verb's own preamble (which would try to acquire the lockfile
   again) and sources only the scanner blocks + postamble. The convention is:
   - **First `bash` fenced block** in each `audits/<verb>.md` = preamble
   - **Subsequent `bash` fenced blocks** = scanner blocks + postamble

3. **Sub-verb invocation_ids** are prefixed with the parent invocation_id for
   filterability: `PD-full-<id>-audit-skills`, etc.

4. **Combined report** at `data/periodic-discipline/reports/${INVOCATION_ID}.json`
   is the concatenation of all three sub-verb reports. The operator can filter by
   `verb` field to isolate findings per sub-verb.

5. **Release lockfile** on EXIT (trap).

### Block-Extraction Idiom

Sub-verb bash blocks are sourced inline using `sed` extraction. This is the only
portable way to execute fenced bash from markdown without a custom interpreter:

```bash
extract_scanner_blocks() {
  local file="$1"
  # Extract all bash code blocks (between ```bash and ```)
  # Returns all blocks EXCEPT the first (preamble)
  sed -n '/^```bash$/,/^```$/p' "$file" | sed '/^```/d' \
    | awk 'found{print} /^$/{if(!found){found=1}}' RS='' ORS='\n\n'
}
```

**Convention for sub-verb runbooks:** each `audits/<verb>.md` has:
- Block 0 (first `bash` block): preamble (set -euo pipefail, lockfile, invocation_id)
- Blocks 1..N: scanners + postamble

The `full` verb skips block 0 of each sub-verb (lockfile already held) and
sources blocks 1..N directly. Each sub-verb's `REPORT` variable must be
overridden to the sub-verb-specific path before sourcing.

---

## Sub-Verb Invocation_ID Scoping

```
Parent:   PD-full-XXXXXXXX
Children: PD-full-XXXXXXXX-audit-skills
          PD-full-XXXXXXXX-curate-memory
          PD-full-XXXXXXXX-test-tools
```

Each sub-verb writes its own report file using the child ID:
```
data/periodic-discipline/reports/PD-full-XXXXXXXX-audit-skills.json
data/periodic-discipline/reports/PD-full-XXXXXXXX-curate-memory.json
data/periodic-discipline/reports/PD-full-XXXXXXXX-test-tools.json
```

The combined report merges all three arrays and is written at:
```
data/periodic-discipline/reports/PD-full-XXXXXXXX.json
```

---

## Preamble

```bash
set -euo pipefail

VERB="full"
INVOCATION_ID="PD-${VERB}-$(uuidgen | cut -c1-8)"
LOCKFILE="data/periodic-discipline/.lock"
START_EPOCH=$(date +%s)
PD_TS="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
export ARCIS_SESSION_ID="$INVOCATION_ID"
export INVOCATION_ID
export PD_TS

# CI refusal — full requires local memory tree for curate-memory step
if [ -n "${GITHUB_ACTIONS:-}" ]; then
  echo "full verb requires local memory tree — refused in CI" >&2
  exit 1
fi

mkdir -p data/periodic-discipline/reports

if [ -f "$LOCKFILE" ] && kill -0 "$(head -1 "$LOCKFILE")" 2>/dev/null; then
  echo "periodic-discipline already running (pid=$(head -1 "$LOCKFILE"), started=$(tail -1 "$LOCKFILE"))" >&2
  exit 1
fi

printf '%s\n%s\n' "$$" "$PD_TS" > "$LOCKFILE"
trap "rm -f '$LOCKFILE'" EXIT

COMBINED_REPORT="data/periodic-discipline/reports/${INVOCATION_ID}.json"

# Audit-log bracket-start
printf '{}' | python -m src.tools._execution_log \
  --tool-name "arcis_periodic_discipline.full.start" \
  --result success --duration-ms 0 --session-id "$INVOCATION_ID" \
  || { echo "WARNING — audit-log start failed" >&2; }
```

---

## Sub-Verb Dispatch

The SKILL.md layer invokes each sub-verb in order by sourcing its scanner blocks.
Below is the v1 implementation contract. Each sub-verb block is sourced in a
subshell to contain variable scope, with `INVOCATION_ID` and `ARCIS_SESSION_ID`
overridden to the child ID before sourcing.

```bash
# Block-extract helper: returns all bash blocks after the first (skips preamble)
extract_scanner_blocks() {
  local file="$1"
  python3 -c "
import re, sys
blocks = re.findall(r'\`\`\`bash\n(.*?)\`\`\`', open('$1', encoding='utf-8').read(), re.DOTALL)
# Skip block 0 (preamble); print blocks 1..N
for b in blocks[1:]:
    print(b)
"
}

SUB_REPORT_FILES=()

for SUB_VERB in audit-skills curate-memory test-tools; do
  CHILD_ID="${INVOCATION_ID}-${SUB_VERB}"
  SUB_REPORT="data/periodic-discipline/reports/${CHILD_ID}.json"
  SUB_REPORT_FILES+=("$SUB_REPORT")

  echo "=== running $SUB_VERB (${CHILD_ID}) ===" >&2

  # Override session variables for the sub-verb's scope
  (
    export INVOCATION_ID="$CHILD_ID"
    export ARCIS_SESSION_ID="$CHILD_ID"
    export REPORT="$SUB_REPORT"
    export RAW="${SUB_REPORT}.raw"
    export VERB="$SUB_VERB"
    export PD_TS="$PD_TS"
    export START_EPOCH="$(date +%s)"
    : > "$RAW"

    # Source the scanner blocks (skip preamble)
    RB=".claude/plugins/arcis/skills/periodic-discipline/audits/${SUB_VERB}.md"
    eval "$(extract_scanner_blocks "$RB")"
  )
done
```

---

## Combined Report

After all three sub-verbs complete, merge their individual reports into the
combined report. If a sub-verb's report is missing (sub-verb failed), record a
sentinel finding rather than silently omitting it.

```bash
# Merge sub-verb reports into combined report
python3 -c "
import json, sys, os

sub_verbs = ['audit-skills', 'curate-memory', 'test-tools']
parent_id = os.environ['INVOCATION_ID']
ts = os.environ.get('PD_TS', '')
combined = []

for sv in sub_verbs:
    child_id = f'{parent_id}-{sv}'
    path = f'data/periodic-discipline/reports/{child_id}.json'
    if os.path.exists(path):
        try:
            findings = json.load(open(path, encoding='utf-8'))
            combined.extend(findings)
        except Exception as e:
            combined.append({
                'invocation_id': parent_id,
                'verb': 'full',
                'scanner': 'sub_verb_error',
                'root_cause_key': f'full:sub_verb_error:{sv}',
                'severity': 'critical',
                'first_seen_utc': ts,
                'advisory': False,
                'payload': {'sub_verb': sv, 'error': str(e)}
            })
    else:
        combined.append({
            'invocation_id': parent_id,
            'verb': 'full',
            'scanner': 'sub_verb_missing',
            'root_cause_key': f'full:sub_verb_missing:{sv}',
            'severity': 'critical',
            'first_seen_utc': ts,
            'advisory': False,
            'payload': {'sub_verb': sv, 'expected_path': path}
        })

json.dump(combined, open(os.environ['COMBINED_REPORT'], 'w', encoding='utf-8'), indent=2)
print(len(combined))
" > /tmp/pd_full_count.txt
TOTAL_COUNT=$(cat /tmp/pd_full_count.txt)
rm -f /tmp/pd_full_count.txt
```

---

## Postamble

```bash
# Audit-log bracket-end
printf '{"sub_verbs": ["audit-skills", "curate-memory", "test-tools"], "total_findings": %s}' \
  "$TOTAL_COUNT" \
  | python -m src.tools._execution_log \
    --tool-name "arcis_periodic_discipline.full.end" \
    --result success \
    --duration-ms "$(($(date +%s) - START_EPOCH))" \
    --session-id "$INVOCATION_ID" \
  || { echo "WARNING — audit-log end failed" >&2; }

echo ""
echo "periodic-discipline [full] — $INVOCATION_ID"
echo "  Sub-verbs completed: audit-skills | curate-memory | test-tools"
echo "  Total findings: $TOTAL_COUNT"
echo ""
echo "  Sub-verb reports:"
for SUB_VERB in audit-skills curate-memory test-tools; do
  CHILD_ID="${INVOCATION_ID}-${SUB_VERB}"
  SUB_REPORT="data/periodic-discipline/reports/${CHILD_ID}.json"
  COUNT=$(jq 'length' "$SUB_REPORT" 2>/dev/null || echo "?")
  echo "    [$SUB_VERB] $COUNT findings → $SUB_REPORT"
done
echo ""
echo "  Combined report: $COMBINED_REPORT"
```
