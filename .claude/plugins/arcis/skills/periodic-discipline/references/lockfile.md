# Lockfile + Invocation Contract Reference

PID-lockfile contract, invocation_id format, ARCIS_SESSION_ID propagation, and report rotation for the `periodic-discipline` skill.

---

## PID Lockfile Contract

**Location:** `data/periodic-discipline/.lock`

**Format:**
```
<PID>
<ISO-8601-start-time>
```

Line 1 is the PID of the running process. Line 2 is the UTC start time in ISO 8601 format (for diagnostic: "how long has this been running?").

Example `.lock` contents:
```
12345
2026-05-26T14:00:01Z
```

---

## Acquire and Release

**Acquire (preamble):**

```bash
LOCKFILE="data/periodic-discipline/.lock"
mkdir -p data/periodic-discipline

if [ -f "$LOCKFILE" ] && kill -0 "$(head -1 $LOCKFILE)" 2>/dev/null; then
  echo "periodic-discipline already running (pid=$(head -1 $LOCKFILE), started=$(tail -1 $LOCKFILE))"
  exit 1
fi

# Write PID and start time
printf '%s\n%s\n' "$$" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "$LOCKFILE"

# Auto-cleanup on success OR interrupt
trap "rm -f $LOCKFILE" EXIT
```

**Release:** The `trap "rm -f $LOCKFILE" EXIT` fires automatically on:
- Normal exit (postamble completes)
- `Ctrl-C` (SIGINT)
- `kill` (SIGTERM)
- Any `set -e` error exit

The lockfile is never left behind by a normal or interrupted run. A stale lockfile (leftover from a SIGKILL or system crash) is detected by the `kill -0` check: if the PID no longer exists, `kill -0` returns 1, and the preamble overwrites the stale file and proceeds.

**Concurrent run detection:** `kill -0 <pid>` returns 0 if the process is alive, 1 if it is not. No signal is sent — this is a pure existence check. Distinguishes a live run from a stale lockfile left by a crash.

---

## Invocation ID Format

```bash
INVOCATION_ID="PD-${VERB}-$(uuidgen | cut -c1-8)"
```

Examples:
- `PD-audit-skills-a1b2c3d4`
- `PD-curate-memory-f9e2c1b7`
- `PD-test-tools-3d8a0f12`

**Components:**
- `PD-` prefix — identifies this as a periodic-discipline invocation
- `${VERB}` — which verb (`audit-skills`, `curate-memory`, `test-tools`)
- `$(uuidgen | cut -c1-8)` — 8-character hex suffix from a UUID for collision safety (256M unique IDs per verb per lifetime)

The `INVOCATION_ID` is set in the preamble immediately after lockfile acquisition, before any scanner runs. It is used as:
1. The `invocation_id` field on every finding record
2. The `ARCIS_SESSION_ID` env var propagated to tool subprocesses
3. The filename stem of the report: `data/periodic-discipline/reports/${INVOCATION_ID}.json`

---

## ARCIS_SESSION_ID Propagation

Before invoking any tool subprocess, set the session env var:

```bash
export ARCIS_SESSION_ID="$INVOCATION_ID"
```

The existing `_execution_log.write_event` implementation picks up `ARCIS_SESSION_ID` as the `session_id` field on each audit-log event. This allows per-invocation filtering of tool events from the shared `data/logs/tool-execution.log`:

```bash
jq 'select(.session_id == env.INVOCATION_ID)' data/logs/tool-execution.log
```

This eliminates the TOCTOU race against the watch loop and concurrent operator sessions. The `test-tools` scanner's `cli_decorator_chain` check depends on this isolation: it invokes each tool with `ARCIS_SESSION_ID=$INVOCATION_ID` and then filters the log by that value to verify the decorator chain.

**Skill-layer bracket events:** The preamble and postamble each write a skill-level event to the audit log:

```bash
# Preamble bracket
echo '{}' | python -m src.tools._execution_log \
  --tool-name "arcis_periodic_discipline.${VERB}.start" \
  --result success \
  --duration-ms 0 \
  --session-id "$INVOCATION_ID"

# Postamble bracket (include diagnostic counts)
echo "{\"raw_finding_count\": $raw_count, \"root_cause_count\": $deduped_count, \"suppressed_count\": $suppressed_count}" \
  | python -m src.tools._execution_log \
    --tool-name "arcis_periodic_discipline.${VERB}.complete" \
    --result success \
    --duration-ms "$(($(date +%s) - START_EPOCH))" \
    --session-id "$INVOCATION_ID"
```

The start and complete bracket events make the invocation duration and finding counts visible in the audit log for per-invocation analysis.

---

## Report Retention and Rotation

**Per-run reports:**
```
data/periodic-discipline/reports/${INVOCATION_ID}.json
```

**30-day rotation (in runbook postamble):**

```bash
find data/periodic-discipline/reports -type f -name '*.json' -mtime +30 -delete
```

This runs at the END of every verb execution — after the report is written but before the summary is printed. A report is never deleted in the same run that created it.

**Monthly archive (manual / future CI):**

```bash
cat data/periodic-discipline/reports/*.json > data/periodic-discipline/archive/$(date +%Y-%m).json
```

The `archive/` directory is committable (not gitignored). The operator decides archive retention policy. This skill does not auto-populate archives — that would create silent retention growth.

---

## data/periodic-discipline/ Directory Layout

```
data/periodic-discipline/
├── reports/          # per-run JSON finding files (gitignored except .gitkeep)
│   └── .gitkeep
├── archive/          # monthly concatenated archives (committable)
│   └── .gitkeep
└── .lock             # PID lockfile (gitignored — never committed)
```

**Gitignore rules** (to be added to `.gitignore` by Task 4):
```
data/periodic-discipline/reports/*.json
data/periodic-discipline/.lock
```

The `.gitkeep` sentinels ensure the `reports/` and `archive/` directories exist in a fresh clone. The `mkdir -p` in the preamble handles first-run creation if the tree is missing entirely.

---

## Full Preamble Template

```bash
set -euo pipefail

VERB="<verb>"
INVOCATION_ID="PD-${VERB}-$(uuidgen | cut -c1-8)"
LOCKFILE="data/periodic-discipline/.lock"
START_EPOCH=$(date +%s)

mkdir -p data/periodic-discipline/reports

if [ -f "$LOCKFILE" ] && kill -0 "$(head -1 $LOCKFILE)" 2>/dev/null; then
  echo "periodic-discipline already running (pid=$(head -1 $LOCKFILE), started=$(tail -1 $LOCKFILE))"
  exit 1
fi

printf '%s\n%s\n' "$$" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "$LOCKFILE"
trap "rm -f $LOCKFILE" EXIT

export ARCIS_SESSION_ID="$INVOCATION_ID"

REPORT="data/periodic-discipline/reports/${INVOCATION_ID}.json"

echo '{}' | python -m src.tools._execution_log \
  --tool-name "arcis_periodic_discipline.${VERB}.start" \
  --result success \
  --duration-ms 0 \
  --session-id "$INVOCATION_ID"
```
