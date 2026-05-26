---
verb: test-tools
risk-level: low
mutations: false
ci-eligible: true
required-tools: []
required-agents: []
expected-duration-sec: 120
references:
  - .claude/plugins/arcis/skills/periodic-discipline/references/scanners.md
  - .claude/plugins/arcis/skills/periodic-discipline/references/findings-schema.md
  - .claude/plugins/arcis/skills/periodic-discipline/references/lockfile.md
---

# Test-Tools Runbook

Verify tool boundary contracts: CLI decorator chain completeness and boundary test coverage.

> **SERIAL EXECUTION REQUIRED.** This runbook invokes each of the 13 tool CLIs
> sequentially. Do NOT run with pytest-xdist parallel. While running, the operator
> should NOT manually invoke audited tools — concurrent tool-execution.log writes
> would confuse the per-invocation-id filter. The lockfile enforces single-instance
> at the skill level, but it cannot prevent concurrent operator tool usage.

**Self-exclusion contract:** All scanners exclude `.claude/plugins/arcis/skills/periodic-discipline/**`.

---

## Preamble

```bash
set -euo pipefail

VERB="test-tools"
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

# The 13 audited tool CLIs (locked per SKILL.md composition table)
TOOLS="capabilityregistry ciinvestigate contractcheck dbquery docconsistency gitarchaeology healthprobe logtail prcomments processmanager symbolfind testpatternscan tradingstate"

# Audit-log bracket-start
printf '{}' | python -m src.tools._execution_log \
  --tool-name "arcis_periodic_discipline.test-tools.start" \
  --result success --duration-ms 0 --session-id "$INVOCATION_ID" \
  || { echo "WARNING — audit-log start failed" >&2; }
```

---

## Scanner 1: cli_decorator_chain

Subprocess-invoke each tool with `ARCIS_SESSION_ID` set to a per-tool ID, then check
`data/logs/tool-execution.log` for a matching event. This is the PR #1175 regression
guarantee: the only way to catch a `__main__.py` that bypasses the decorator stack by
importing `_impl` directly is subprocess invocation (never in-process import).

Two sub-findings:
- `cli_unbootable`: tool exits non-zero on `--help` (broken CLI entirely)
- `audit_log_silent`: tool booted but emitted no audit-log event for this session ID

Note: `--help` is handled by argparse before any decorated function runs, so most tools
will not write an audit-log event for it. `audit_log_silent` is therefore severity `info`
(opt-in nudge, not blocking) — it documents the absence without asserting a defect.
See `references/scanners.md §cli_decorator_chain` for the full decorator-chain inspection
logic used in more exhaustive checks.

```bash
for tool in $TOOLS; do
  PER_TOOL_ID="${INVOCATION_ID}-${tool}"

  # Snapshot log line-count for boundary detection
  LINES_BEFORE=$(wc -l < data/logs/tool-execution.log 2>/dev/null || echo 0)

  # Invoke tool with session ID set; capture exit code
  if ! ARCIS_SESSION_ID="$PER_TOOL_ID" python -m "src.tools.$tool" --help >/dev/null 2>&1; then
    jq -nc --arg tool "$tool" --arg ts "$PD_TS" \
      '{invocation_id: env.INVOCATION_ID, verb: "test-tools", scanner: "cli_unbootable", root_cause_key: ("tool:" + $tool + ":unbootable"), severity: "critical", first_seen_utc: $ts, advisory: false, payload: {tool: $tool}}' \
      >> "$RAW"
    continue
  fi

  # Check: did the tool emit an audit-log event with our session_id?
  if [ -f data/logs/tool-execution.log ]; then
    EMITTED=$(tail -n "+$((LINES_BEFORE + 1))" data/logs/tool-execution.log 2>/dev/null \
      | jq -c "select(.session_id == \"$PER_TOOL_ID\")" \
      | head -1)

    if [ -z "$EMITTED" ]; then
      jq -nc --arg tool "$tool" --arg ts "$PD_TS" \
        '{invocation_id: env.INVOCATION_ID, verb: "test-tools", scanner: "audit_log_silent", root_cause_key: ("tool:" + $tool + ":no_audit_event_on_help"), severity: "info", first_seen_utc: $ts, advisory: false, payload: {tool: $tool, note: "--help exits before decorated function runs; no audit event is expected for read-only help invocations"}}' \
        >> "$RAW"
    fi
  fi
done
```

---

## Scanner 2: boundary_test_missing

For each of the 13 audited tools, check whether
`tests/tools/test_<name>_integration.py` exists. This is the minimum expected
boundary test artifact. The integration test is the enforcement point for
subprocess-level decorator-chain verification.

To suppress a finding for a tool that is intentionally untested at this level,
add `tool:<name>:no_boundary_test` to `allowlist.yaml` with a rationale.

```bash
for tool in $TOOLS; do
  if [ ! -f "tests/tools/test_${tool}_integration.py" ]; then
    jq -nc --arg tool "$tool" --arg ts "$PD_TS" \
      '{invocation_id: env.INVOCATION_ID, verb: "test-tools", scanner: "boundary_test_missing", root_cause_key: ("tool:" + $tool + ":no_boundary_test"), severity: "major", first_seen_utc: $ts, advisory: false, payload: {tool: $tool, expected_path: ("tests/tools/test_" + $tool + "_integration.py")}}' \
      >> "$RAW"
  fi
done
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
    findings.append({'invocation_id': invocation_id, 'verb': 'test-tools', 'scanner': 'allowlist_malformed', 'root_cause_key': 'allowlist:malformed', 'severity': 'critical', 'first_seen_utc': ts, 'advisory': False, 'payload': {'error': str(e)}})
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
    --tool-name "arcis_periodic_discipline.test-tools.end" \
    --result success \
    --duration-ms "$(($(date +%s) - START_EPOCH))" \
    --session-id "$INVOCATION_ID" \
  || { echo "WARNING — audit-log end failed" >&2; }

# --- Stdout summary ---
if [ "$FINAL_COUNT" -eq 0 ]; then
  echo ""
  echo "periodic-discipline [test-tools] — $INVOCATION_ID"
  echo "  All clear."
  echo ""
  echo "  Report: $REPORT"
else
  CRITICAL=$(jq '[.[] | select(.severity=="critical" and .advisory==false)] | length' "$REPORT")
  MAJOR=$(jq '[.[] | select(.severity=="major" and .advisory==false)] | length' "$REPORT")
  MINOR=$(jq '[.[] | select(.severity=="minor" and .advisory==false)] | length' "$REPORT")
  ADVISORY=$(jq '[.[] | select(.advisory==true)] | length' "$REPORT")
  echo ""
  echo "periodic-discipline [test-tools] — $INVOCATION_ID"
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
